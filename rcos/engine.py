"""Simulation engine and main loop (OWNER: Juvaugn).

TICK ORDER (one tick = the interval [t, t+1)):

  START OF TICK  (events stamped t)
   1. arrivals        processes whose arrival_time <= t enter the job queue (state NEW)
   2. admission       job queue -> ResourceManager.allocate_memory
                        granted    -> NEW -> READY, scheduler.add()
                        denied     -> stays NEW (retried every tick)
                        impossible -> NEW -> TERMINATED (rejected)
   3. scheduler.on_tick()                      (aging hook)
   4. dispatch        if running and scheduler.should_preempt(): RUNNING -> READY, re-queued
                      if CPU free: scheduler.select_next() -> READY -> RUNNING (context switch)
  WORK PHASE     (CPU and I/O devices run in PARALLEL)
   5. CPU runs the running process for 1 tick;  I/O devices serve 1 tick each
  END OF TICK    (events stamped t+1)
   6. I/O completions   WAITING -> READY (or TERMINATED if that was the last burst)
   7. CPU burst done?   next burst is I/O -> RUNNING -> WAITING + I/O request
                        no more bursts    -> RUNNING -> TERMINATED, memory freed

Tie-break convention: processes finishing I/O at t+1 join the ready queue before a
process preempted at the start of the next tick.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from .config import SystemConfig
from .errors import ConfigError, SimulationError
from .eventlog import Category, EventLog
from .interfaces import IOManager, MemoryManager, PowerManager, Scheduler
from .io_manager import SimpleIOManager
from .memory import SimpleMemoryManager
from .metrics import MetricsCollector, MetricsReport
from .power import BatteryPowerManager, NullPowerManager
from .process import BurstType, Process, ProcessState
from .resources import AllocResult, ResourceManager
from .scheduler import create_scheduler


class Simulator:
    def __init__(self, config: SystemConfig, scheduler: Scheduler, memory: MemoryManager,
                 io: IOManager, power: PowerManager, log: EventLog) -> None:
        self.config = config
        self.scheduler = scheduler
        self.log = log
        self.resources = ResourceManager(memory, io, power, log)
        self.metrics = MetricsCollector()
        self.clock = 0
        self.processes: Dict[int, Process] = {}
        self._incoming: List[Process] = []     # not yet arrived, sorted by arrival
        self._job_queue: List[Process] = []    # arrived, state NEW, waiting for memory
        self._running: Optional[Process] = None
        self._quantum_used = 0
        self._last_pid: Optional[int] = None

    # ------------------------------------------------------------------ setup
    def load_processes(self, processes: Iterable[Process]) -> None:
        if self.clock != 0:
            raise SimulationError("cannot load processes after the simulation has started")
        for proc in processes:
            if proc.pid in self.processes:
                raise ConfigError(f"duplicate pid {proc.pid}")
            for burst in proc.bursts:
                if burst.kind is BurstType.IO and burst.device not in self.config.io_devices:
                    raise ConfigError(f"{proc.label}: unknown I/O device {burst.device!r} "
                                      f"(configured: {', '.join(self.config.io_devices)})")
            self.processes[proc.pid] = proc
            self._incoming.append(proc)
        self._incoming.sort(key=lambda p: (p.arrival_time, p.pid))

    # -------------------------------------------------------------------- run
    def run(self) -> MetricsReport:
        if not self.processes:
            raise SimulationError("no processes loaded")
        cfg = self.config
        self.log.emit(0, Category.SYSTEM,
                      f"START scheduler={self.scheduler.name} memory={cfg.total_memory_kb}KB "
                      f"quantum={cfg.time_quantum} devices={','.join(cfg.io_devices)} "
                      f"battery={cfg.battery_capacity if cfg.battery_capacity else 'off'}")
        while not self._all_done():
            if self.clock >= cfg.max_ticks:
                self.log.emit(self.clock, Category.WARN, "max_ticks reached - aborting")
                self._abort_all(self.clock, "aborted: max_ticks reached")
                break
            if self.resources.power.is_depleted():
                self.log.emit(self.clock, Category.POWER, "system shutdown - battery empty")
                self._abort_all(self.clock, "aborted: power exhausted")
                break
            self._tick()
        self.log.emit(self.clock, Category.SYSTEM, f"END after {self.clock} ticks")
        return self.metrics.build_report(
            self.processes.values(), self.clock, self.resources.io.busy_ticks(),
            self.resources.snapshot(self.clock), self.scheduler.name)

    def _all_done(self) -> bool:
        return all(p.state is ProcessState.TERMINATED for p in self.processes.values())

    # ------------------------------------------------------------------- tick
    def _tick(self) -> None:
        now = self.clock
        self._handle_arrivals(now)
        self._admit_from_job_queue(now)
        self.scheduler.on_tick(now)
        self._dispatch(now)
        self.metrics.record_tick(now, self.resources.snapshot(now),
                                 self._running.pid if self._running else None)
        ran = self._execute_cpu(now)                   # work phase
        finished_io = self.resources.io.advance(now)
        end = now + 1
        for proc in finished_io:                       # end phase
            self._on_io_complete(proc, end)
        if ran is not None:
            self._on_cpu_tick_end(ran, end)
        self.clock = end

    def _handle_arrivals(self, now: int) -> None:
        while self._incoming and self._incoming[0].arrival_time <= now:
            proc = self._incoming.pop(0)
            self._job_queue.append(proc)
            self.log.emit(now, Category.STATE,
                          f"{proc.name} ARRIVED (pri {proc.priority}, {proc.memory_kb}KB, "
                          f"cpu demand {proc.total_cpu_demand})", proc.pid)

    def _admit_from_job_queue(self, now: int) -> None:
        for proc in list(self._job_queue):             # FIFO; a blocked process does not block smaller ones
            result = self.resources.allocate_memory(proc, now)
            if result is AllocResult.GRANTED:
                self._job_queue.remove(proc)
                self._set_state(proc, ProcessState.READY, now, "admitted")
                self.scheduler.add(proc, now)
            elif result is AllocResult.IMPOSSIBLE:
                self._job_queue.remove(proc)
                self._terminate(proc, now, "rejected: larger than total memory")

    def _dispatch(self, now: int) -> None:
        running = self._running
        if running is not None and self.scheduler.should_preempt(running, now, self._quantum_used):
            self._set_state(running, ProcessState.READY, now, "preempted")
            self.resources.release_cpu(running)
            self._running = None
            self.scheduler.add(running, now)
        if self._running is None:
            nxt = self.scheduler.select_next(now, self.resources.snapshot(now))
            if nxt is not None:
                self.resources.assign_cpu(nxt)
                self._set_state(nxt, ProcessState.RUNNING, now, "dispatched")
                self._running = nxt
                self._quantum_used = 0
                if self._last_pid is not None and self._last_pid != nxt.pid:
                    self.metrics.record_context_switch()
                self._last_pid = nxt.pid

    def _execute_cpu(self, now: int) -> Optional[Process]:
        proc = self._running
        if proc is None:
            self.resources.power.consume_idle(now)
            return None
        burst = proc.current_burst
        if burst is None or burst.kind is not BurstType.CPU:
            raise SimulationError(f"{proc.label} dispatched without a CPU burst")
        burst.remaining -= 1
        proc.cpu_time_used += 1
        self._quantum_used += 1
        self.resources.power.consume_cpu(proc, now)
        return proc

    def _on_cpu_tick_end(self, proc: Process, end: int) -> None:
        if proc.current_burst.remaining > 0:
            return                                     # still running; may be preempted next tick
        self.resources.release_cpu(proc)
        self._running = None
        if proc.advance_burst():                       # next burst is I/O (bursts alternate)
            burst = proc.current_burst
            self._set_state(proc, ProcessState.WAITING, end,
                            f"I/O request {burst.device} x{burst.duration}")
            self.resources.request_io(proc, end)
        else:
            self._terminate(proc, end, "completed")

    def _on_io_complete(self, proc: Process, end: int) -> None:
        if proc.advance_burst():                       # next burst is CPU
            self._set_state(proc, ProcessState.READY, end, "I/O complete")
            self.scheduler.add(proc, end)
        else:
            self._terminate(proc, end, "completed")

    # ---------------------------------------------------------------- helpers
    def _set_state(self, proc: Process, new: ProcessState, now: int, reason: str) -> None:
        old = proc.transition(new, now)
        self.log.emit(now, Category.STATE,
                      f"{proc.name} {old.value} -> {new.value} ({reason})", proc.pid)

    def _terminate(self, proc: Process, now: int, reason: str) -> None:
        proc.exit_reason = reason
        self.resources.release_memory(proc, now)
        self._set_state(proc, ProcessState.TERMINATED, now, reason)

    def _abort_all(self, now: int, reason: str) -> None:
        for proc in self.processes.values():
            if proc.state is ProcessState.TERMINATED:
                continue
            if proc.arrival_time > now:                # never arrived: leave state NEW
                proc.exit_reason = f"{reason} (never arrived)"
                continue
            if proc is self._running:
                self.resources.release_cpu(proc)
                self._running = None
            self._terminate(proc, now, reason)


def build_simulator(config: SystemConfig) -> Simulator:
    """Wire the default components together.  Swap a component here to use a new implementation."""
    log = EventLog(echo=config.log_to_console)
    scheduler = create_scheduler(config.scheduler, config)
    memory: MemoryManager = SimpleMemoryManager(config.total_memory_kb, log)
    io: IOManager = SimpleIOManager(config.io_devices, log)
    power: PowerManager = (BatteryPowerManager(config.battery_capacity, config.idle_power_cost, log)
                           if config.battery_capacity is not None else NullPowerManager())
    return Simulator(config, scheduler, memory, io, power, log)
