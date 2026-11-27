"""Simulation engine and main loop (Member 1: Juvaugn).

Time moves in ticks. Every tick, in this order:
  1. Arrivals     new processes join the job queue (NEW)
  2. Admission    each gets memory if it can: NEW -> READY; too big for all memory: rejected
  3. Aging        the scheduler's on_tick hook
  4. Dispatch     preempt if the scheduler says so; if the CPU is free, pick the next process
  5. Work         the CPU runs one tick; every I/O device serves one tick (in parallel)
  6. I/O done     WAITING -> READY
  7. Burst done   next burst is I/O: RUNNING -> WAITING; no bursts left: TERMINATED, memory freed
  8. --check      verify the rules in checks.py
Processes finishing I/O join the ready queue before one preempted at the start of the next tick.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from .checks import check_invariants
from .config import SystemConfig
from .errors import ConfigError, SimulationError
from .eventlog import Category, EventLog
from .interfaces import IOManager, MemoryManager, PowerManager, Scheduler
from .io_manager import SimpleIOManager
from .memory import ContiguousMemoryManager
from .metrics import MetricsCollector, MetricsReport
from .power import BatteryPowerManager, NullPowerManager
from .process import BurstType, Process, ProcessState
from .resources import AllocResult, ResourceManager
from .scheduler import create_scheduler


# ---- Simulator: holds the queues and runs the tick loop ----
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
        self._incoming: List[Process] = []     # not arrived yet, by arrival time
        self._job_queue: List[Process] = []    # arrived, waiting for memory (NEW)
        self._running: Optional[Process] = None
        self._quantum_used = 0
        self._last_pid: Optional[int] = None
        self.invariant_checks = 0              # ticks verified by --check

    # ---- Setup: validate and queue the scenario's processes ----
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

    # ---- Run: tick until every process has finished (or a safety stop) ----
    def run(self) -> MetricsReport:
        if not self.processes:
            raise SimulationError("no processes loaded")
        cfg = self.config
        self.log.emit(0, Category.SYSTEM,
                      f"START scheduler={self.scheduler.name} memory={cfg.total_memory_kb}KB "
                      f"({cfg.memory_strategy} fit{', compaction' if cfg.memory_compaction else ''}) "
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
        if self.config.check_invariants:
            self.log.emit(self.clock, Category.SYSTEM,
                          f"CHECK all invariants held after each of {self.invariant_checks} ticks")
        self.log.emit(self.clock, Category.SYSTEM, f"END after {self.clock} ticks")
        return self.metrics.build_report(
            self.processes.values(), self.clock, self.resources.io.busy_ticks(),
            self.resources.snapshot(self.clock), self.scheduler.name)

    def _all_done(self) -> bool:
        return all(p.state is ProcessState.TERMINATED for p in self.processes.values())

    # ---- One tick: the eight steps listed at the top of this file ----
    def _tick(self) -> None:
        now = self.clock
        self._handle_arrivals(now)
        self._admit_from_job_queue(now)
        self.scheduler.on_tick(now)
        self._dispatch(now)
        self.metrics.record_tick(now, self.resources.snapshot(now),
                                 self._running.pid if self._running else None)
        ran = self._execute_cpu(now)                   # step 5: work
        finished_io = self.resources.io.advance(now)
        end = now + 1
        for proc in finished_io:                       # steps 6-7: end of tick
            self._on_io_complete(proc, end)
        if ran is not None:
            self._on_cpu_tick_end(ran, end)
        self.clock = end
        if self.config.check_invariants:               # step 8
            check_invariants(self)
            self.invariant_checks += 1

    # ---- Steps 1-2: arrivals and memory admission ----
    def _handle_arrivals(self, now: int) -> None:
        while self._incoming and self._incoming[0].arrival_time <= now:
            proc = self._incoming.pop(0)
            self._job_queue.append(proc)
            self.log.emit(now, Category.STATE,
                          f"{proc.name} ARRIVED (pri {proc.priority}, {proc.memory_kb}KB, "
                          f"cpu demand {proc.total_cpu_demand})", proc.pid)

    def _admit_from_job_queue(self, now: int) -> None:
        for proc in list(self._job_queue):             # a blocked process does not hold up smaller ones
            result = self.resources.allocate_memory(proc, now)
            if result is AllocResult.GRANTED:
                self._job_queue.remove(proc)
                self._set_state(proc, ProcessState.READY, now, "admitted")
                self.scheduler.add(proc, now)
            elif result is AllocResult.IMPOSSIBLE:
                self._job_queue.remove(proc)
                self._terminate(proc, now, "rejected: larger than total memory")

    # ---- Step 4: preemption and dispatch (counts context switches) ----
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

    # ---- Step 5: run the CPU for one tick (or idle) ----
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

    # ---- Steps 6-7: finished CPU and I/O bursts ----
    def _on_cpu_tick_end(self, proc: Process, end: int) -> None:
        if proc.current_burst.remaining > 0:
            return                                     # burst not finished yet
        self.resources.release_cpu(proc)
        self._running = None
        if proc.advance_burst():                       # next burst is I/O
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

    # ---- Helpers: logged state changes, termination, emergency stop ----
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
            if proc.arrival_time > now:                # never arrived: stays NEW
                proc.exit_reason = f"{reason} (never arrived)"
                continue
            if proc is self._running:
                self.resources.release_cpu(proc)
                self._running = None
            self._terminate(proc, now, reason)


# ---- Build: create every component from the config and connect them ----
def build_simulator(config: SystemConfig) -> Simulator:
    log = EventLog(echo=config.log_to_console)
    scheduler = create_scheduler(config.scheduler, config)
    memory: MemoryManager = ContiguousMemoryManager(
        config.total_memory_kb, strategy=config.memory_strategy,
        compaction=config.memory_compaction, log=log, show_map=config.show_memory_map)
    io: IOManager = SimpleIOManager(config.io_devices, log)
    power: PowerManager = (BatteryPowerManager(config.battery_capacity, config.idle_power_cost, log)
                           if config.battery_capacity is not None else NullPowerManager())
    return Simulator(config, scheduler, memory, io, power, log)
