"""THE CONTRACTS between modules (OWNER: Member 1 - changes go through Member 1).

Each team member implements one of these abstract classes in their own file:

    Member 2 -> Scheduler       in scheduler.py
    Member 3 -> MemoryManager   in memory.py
    Member 4 -> IOManager       in io_manager.py
    Member 5 -> PowerManager    in power.py   (bonus)  and MetricsCollector in metrics.py

Working baseline versions already exist in each file so the whole simulator
runs end-to-end from day one.  Replace/extend them; keep these signatures.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .eventlog import EventLog
from .process import Process


@dataclass(frozen=True)
class ResourceSnapshot:
    """Read-only view of the machine at one instant (handed to schedulers and metrics)."""
    time: int
    cpu_owner: Optional[int]
    mem_used_kb: int
    mem_total_kb: int
    mem_largest_free_kb: int
    io_queue_lengths: Dict[str, int] = field(default_factory=dict)   # queued + in service
    battery_remaining: Optional[float] = None                        # None = not modelled

    @property
    def mem_free_kb(self) -> int:
        return self.mem_total_kb - self.mem_used_kb


# --------------------------------------------------------------------- Scheduler
class Scheduler(ABC):
    """Owns the READY queue and decides who runs next (Member 2).

    The engine calls, every tick:  on_tick -> should_preempt (if CPU busy) -> select_next (if CPU free)
    The engine - not the scheduler - performs the READY<->RUNNING state transitions.
    Lower priority number = higher priority.
    """
    name: str = "BASE"

    @abstractmethod
    def add(self, proc: Process, now: int) -> None:
        """Put a READY process in the ready queue (new arrival, I/O finished, or preempted)."""

    @abstractmethod
    def select_next(self, now: int, resources: ResourceSnapshot) -> Optional[Process]:
        """REMOVE and return the next process to run, or None if the queue is empty.
        `resources` lets a resource-aware scheduler look at memory/I/O/battery."""

    def should_preempt(self, running: Process, now: int, quantum_used: int) -> bool:
        """Return True to take the CPU away from `running` right now (default: never)."""
        return False

    def on_tick(self, now: int) -> None:
        """Called once per tick before dispatch (hook for priority aging)."""

    @abstractmethod
    def ready_pids(self) -> List[int]:
        """PIDs currently in the ready queue, in the order they would be considered."""

    def __len__(self) -> int:
        return len(self.ready_pids())


# ------------------------------------------------------------------ MemoryManager
class MemoryManager(ABC):
    """Limited memory pool (Member 3).

    allocate() returns False for an ordinary failure (not enough memory) - it must
    NOT raise.  Raise ResourceError only for contract violations (double allocate,
    freeing an unknown pid).  Do NOT log the same failure every tick.
    """

    def __init__(self, total_kb: int, log: Optional[EventLog] = None) -> None:
        self.total_kb = total_kb
        self.log = log or EventLog(echo=False)

    @abstractmethod
    def allocate(self, pid: int, size_kb: int, now: int) -> bool:
        """Try to give `pid` `size_kb` of memory.  True = granted, False = not now."""

    @abstractmethod
    def free(self, pid: int, now: int) -> int:
        """Release everything held by `pid`.  Returns the KB freed."""

    @property
    @abstractmethod
    def used_kb(self) -> int:
        """KB currently allocated."""

    @property
    def free_kb(self) -> int:
        return self.total_kb - self.used_kb

    @property
    def largest_free_block_kb(self) -> int:
        """Override if your design can fragment (free_kb >= largest block)."""
        return self.free_kb


# ---------------------------------------------------------------------- IOManager
class IOManager(ABC):
    """I/O device queues (Member 4).

    submit(): called when a process finishes a CPU burst whose next burst is I/O.
              Read the request from proc.current_burst (kind IO, .device, .remaining).
    advance(): called ONCE per tick; serve each device for one tick (decrement the
              served process's current_burst.remaining).  Return the processes whose I/O
              burst just reached 0.  The engine moves them WAITING -> READY.
    """

    def __init__(self, devices, log: Optional[EventLog] = None) -> None:
        self.devices = tuple(devices)
        self.log = log or EventLog(echo=False)

    @abstractmethod
    def submit(self, proc: Process, now: int) -> None: ...

    @abstractmethod
    def advance(self, now: int) -> List[Process]: ...

    @abstractmethod
    def queue_lengths(self) -> Dict[str, int]:
        """Requests queued OR in service, per device."""

    @abstractmethod
    def busy_ticks(self) -> Dict[str, int]:
        """Total ticks each device spent serving a request (for utilisation)."""


# ------------------------------------------------------------------ PowerManager
class PowerManager(ABC):
    """Battery model for the optional Power-Aware module (Member 5 + Member 2)."""

    @abstractmethod
    def consume_cpu(self, proc: Process, now: int) -> None:
        """Charge one tick of CPU time for `proc`."""

    @abstractmethod
    def consume_idle(self, now: int) -> None:
        """Charge one idle tick."""

    @abstractmethod
    def is_depleted(self) -> bool: ...

    @property
    @abstractmethod
    def remaining(self) -> Optional[float]:
        """Energy left, or None if power is not modelled."""

    def can_afford(self, proc: Process) -> bool:
        """Hook for power-aware schedulers: can the battery pay for one more tick of `proc`?"""
        return not self.is_depleted()
