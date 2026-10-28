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
from typing import Deque, List, Optional

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
    """TODO (Member 2): time-sliced FCFS.
    Needs: add() to the tail; select_next() pops the head; should_preempt() returns True
    when quantum_used >= quantum AND someone else is waiting; a preempted process is
    re-added (to the tail) by the engine via add()."""
    name = "RR"

    def __init__(self, time_quantum: int) -> None:
        self.time_quantum = time_quantum

    def add(self, proc, now): raise NotImplementedError("TODO Member 2: Round Robin")
    def select_next(self, now, resources): raise NotImplementedError("TODO Member 2: Round Robin")
    def should_preempt(self, running, now, quantum_used): raise NotImplementedError("TODO Member 2")
    def ready_pids(self): raise NotImplementedError("TODO Member 2: Round Robin")


class PriorityScheduler(Scheduler):
    """TODO (Member 2): priority scheduling (lower number = higher priority).
    Decide preemptive vs non-preemptive and document why.  Break ties by arrival to READY.
    Use on_tick() to implement aging (raise priority of long-waiting processes) to show
    how starvation is prevented - this is the project's 'priority management' feature."""
    name = "PRIORITY"

    def __init__(self, preemptive: bool = True, aging_interval: int = 0) -> None:
        self.preemptive = preemptive
        self.aging_interval = aging_interval

    def add(self, proc, now): raise NotImplementedError("TODO Member 2: Priority")
    def select_next(self, now, resources): raise NotImplementedError("TODO Member 2: Priority")
    def should_preempt(self, running, now, quantum_used): raise NotImplementedError("TODO Member 2")
    def ready_pids(self): raise NotImplementedError("TODO Member 2: Priority")


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
