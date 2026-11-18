"""CPU scheduling (OWNER: Member 2).

FCFS is implemented so the engine runs today.  RoundRobinScheduler and
PriorityScheduler are stubs: implement them against the contract in
interfaces.Scheduler, then they are selected with --scheduler rr / priority.

Rules of the contract (see interfaces.py):
  * the scheduler owns the READY queue; the engine does the state transitions
  * select_next() must REMOVE the process it returns
  * LOWER priority number = HIGHER priority
"""
from __future__ import annotations

from collections import deque
from typing import Deque, Dict, List, Optional

from .config import SystemConfig
from .errors import ConfigError
from .interfaces import ResourceSnapshot, Scheduler
from .process import Process


class FCFSScheduler(Scheduler):
    """First-Come-First-Served: non-preemptive, queue order = order of becoming READY."""
    name = "FCFS"

    def __init__(self) -> None:
        self._queue: Deque[Process] = deque()

    def add(self, proc: Process, now: int) -> None:
        self._queue.append(proc)

    def select_next(self, now: int, resources: ResourceSnapshot) -> Optional[Process]:
        return self._queue.popleft() if self._queue else None

    def ready_pids(self) -> List[int]:
        return [p.pid for p in self._queue]


class RoundRobinScheduler(Scheduler):
    """Time-sliced FCFS."""
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
        return quantum_used >= self.time_quantum and bool(self._queue)

    def ready_pids(self) -> List[int]:
        return [proc.pid for proc in self._queue]


class PriorityScheduler(Scheduler):
    """Preemptive priority scheduling with optional aging.

    Lower priority numbers are better.  Processes with the same effective priority
    are ordered by the tick and sequence in which they became READY.
    """
    name = "PRIORITY"

    def __init__(self, preemptive: bool = True, aging_interval: int = 0) -> None:
        if aging_interval < 0:
            raise ConfigError("priority aging interval must not be negative")
        self.preemptive = preemptive
        self.aging_interval = aging_interval
        self._queue: List[tuple[Process, int, int]] = []
        self._sequence = 0
        self._waiting_since: Dict[int, int] = {}
        self._aging_steps: Dict[int, int] = {}

    def _effective_priority(self, proc: Process) -> int:
        bonus = self._aging_steps.get(proc.pid, 0)
        return max(0, proc.priority - bonus)

    def add(self, proc: Process, now: int) -> None:
        burst = proc.current_burst
        if burst is None or burst.remaining == burst.duration:
            self._aging_steps[proc.pid] = 0          # new CPU burst: earlier aging boost is used up
        else:
            self._aging_steps.setdefault(proc.pid, 0)  # preempted mid-burst: keep the boost
        self._waiting_since[proc.pid] = now
        self._sequence += 1
        self._queue.append((proc, now, self._sequence))

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


def create_scheduler(name: str, config: SystemConfig) -> Scheduler:
    """Factory used by build_simulator().  Register new schedulers here."""
    key = name.lower()
    if key == "fcfs":
        return FCFSScheduler()
    if key == "rr":
        return RoundRobinScheduler(config.time_quantum)
    if key == "priority":
        return PriorityScheduler(aging_interval=config.priority_aging_interval)
    raise ConfigError(f"unknown scheduler {name!r} (choose: fcfs, rr, priority)")
