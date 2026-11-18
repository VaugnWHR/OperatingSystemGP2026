"""CPU scheduling (owner: Member 2, Samuel Kelly).

Three algorithms, chosen with --scheduler: FCFS, Round Robin and Priority (with aging).
Each keeps its own ready queue; select_next() removes the process it returns.
Lower priority number = higher priority.
"""
from __future__ import annotations

from collections import deque
from typing import Deque, Dict, List, Optional

from .config import SystemConfig
from .errors import ConfigError
from .interfaces import ResourceSnapshot, Scheduler
from .process import Process


# ---- FCFS: run in the order processes became READY, never preempt ----
class FCFSScheduler(Scheduler):
    name = "FCFS"

    def __init__(self) -> None:
        self._queue: Deque[Process] = deque()

    def add(self, proc: Process, now: int) -> None:
        self._queue.append(proc)

    def select_next(self, now: int, resources: ResourceSnapshot) -> Optional[Process]:
        return self._queue.popleft() if self._queue else None

    def ready_pids(self) -> List[int]:
        return [p.pid for p in self._queue]


# ---- Round Robin: FCFS order, but preempt after one time quantum ----
class RoundRobinScheduler(Scheduler):
    name = "RR"

    def __init__(self, time_quantum: int) -> None:
        if time_quantum <= 0:
            raise ConfigError("time quantum must be greater than zero")
        self.time_quantum = time_quantum
        self._queue: Deque[Process] = deque()

    def add(self, proc: Process, now: int) -> None:
        self._queue.append(proc)

    def select_next(self, _now: int, _resources: ResourceSnapshot) -> Optional[Process]:
        return self._queue.popleft() if self._queue else None

    def should_preempt(self, _running: Process, _now: int, quantum_used: int) -> bool:
        return quantum_used >= self.time_quantum and bool(self._queue)   # only if someone waits

    def ready_pids(self) -> List[int]:
        return [proc.pid for proc in self._queue]


# ---- Priority: best (lowest) priority number first; ties go to whoever was READY first ----
class PriorityScheduler(Scheduler):
    """Preemptive by default. Aging lowers a waiting process's priority number by 1
    every `aging_interval` ticks, so low-priority work cannot starve."""
    name = "PRIORITY"

    def __init__(self, preemptive: bool = True, aging_interval: int = 0) -> None:
        if aging_interval < 0:
            raise ConfigError("priority aging interval must not be negative")
        self.preemptive = preemptive
        self.aging_interval = aging_interval
        self._queue: List[tuple[Process, int, int]] = []   # (process, ready time, sequence)
        self._sequence = 0
        self._waiting_since: Dict[int, int] = {}
        self._aging_steps: Dict[int, int] = {}

    def _effective_priority(self, proc: Process) -> int:
        bonus = self._aging_steps.get(proc.pid, 0)
        return max(0, proc.priority - bonus)

    # ---- Add: join the ready queue (a new CPU burst starts with no aging boost) ----
    def add(self, proc: Process, now: int) -> None:
        burst = proc.current_burst
        if burst is None or burst.remaining == burst.duration:
            self._aging_steps[proc.pid] = 0
        else:
            self._aging_steps.setdefault(proc.pid, 0)   # preempted mid-burst: keep its boost
        self._waiting_since[proc.pid] = now
        self._sequence += 1
        self._queue.append((proc, now, self._sequence))

    # ---- Aging: the longer a process waits, the better its effective priority ----
    def on_tick(self, now: int) -> None:
        if self.aging_interval == 0:
            return
        for proc in {entry[0].pid: entry[0] for entry in self._queue}.values():
            waiting_since = self._waiting_since.get(proc.pid, now)
            elapsed = now - waiting_since
            expected_steps = elapsed // self.aging_interval
            bonus = self._aging_steps.get(proc.pid, 0)
            if bonus < expected_steps:
                self._aging_steps[proc.pid] = max(0, expected_steps)

    # ---- Pick: best effective priority, then earliest READY ----
    def select_next(self, _now: int, _resources: ResourceSnapshot) -> Optional[Process]:
        if not self._queue:
            return None
        index = min(
            range(len(self._queue)),
            key=lambda i: (
                self._effective_priority(self._queue[i][0]),
                self._queue[i][1],
                self._queue[i][2],
            ),
        )
        proc, _, _ = self._queue.pop(index)
        self._waiting_since.pop(proc.pid, None)
        return proc

    # ---- Preempt: a strictly better process is waiting ----
    def should_preempt(self, running: Process, _now: int, _quantum_used: int) -> bool:
        if not self.preemptive or not self._queue:
            return False
        highest_waiting_priority = min(
            self._effective_priority(proc)
            for proc, _ready_time, _sequence in self._queue
        )
        return highest_waiting_priority < self._effective_priority(running)

    def ready_pids(self) -> List[int]:
        ordered = sorted(
            self._queue,
            key=lambda entry: (
                self._effective_priority(entry[0]),
                entry[1],
                entry[2],
            ),
        )
        return [proc.pid for proc, _ready_time, _sequence in ordered]


# ---- Factory: build the scheduler named on the command line ----
def create_scheduler(name: str, config: SystemConfig) -> Scheduler:
    key = name.lower()
    if key == "fcfs":
        return FCFSScheduler()
    if key == "rr":
        return RoundRobinScheduler(config.time_quantum)
    if key == "priority":
        return PriorityScheduler(aging_interval=config.priority_aging_interval)
    raise ConfigError(f"unknown scheduler {name!r} (choose: fcfs, rr, priority)")
