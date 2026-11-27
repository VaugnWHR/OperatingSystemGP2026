"""Contracts between the modules (Member 1: Juvaugn).

Each module implements one of these classes, so the engine can use any version of it:
Scheduler (scheduler.py), MemoryManager (memory.py), IOManager (io_manager.py),
PowerManager (power.py). Ask Member 1 before changing a method signature.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .eventlog import EventLog
from .process import Process


# ---- Snapshot: a read-only view of the machine, given to schedulers and metrics ----
@dataclass(frozen=True)
class ResourceSnapshot:
    time: int
    cpu_owner: Optional[int]
    mem_used_kb: int
    mem_total_kb: int
    mem_largest_free_kb: int
    io_queue_lengths: Dict[str, int] = field(default_factory=dict)   # queued + in service
    battery_remaining: Optional[float] = None                        # None = no battery model

    @property
    def mem_free_kb(self) -> int:
        return self.mem_total_kb - self.mem_used_kb


# ---- Scheduler: owns the ready queue and picks who runs next ----
class Scheduler(ABC):
    """Each tick the engine calls on_tick, then should_preempt (CPU busy) or
    select_next (CPU free). The engine, not the scheduler, changes process states."""
    name: str = "BASE"

    @abstractmethod
    def add(self, proc: Process, now: int) -> None:
        """Put a READY process in the ready queue."""

    @abstractmethod
    def select_next(self, now: int, resources: ResourceSnapshot) -> Optional[Process]:
        """Remove and return the next process to run (None if the queue is empty)."""

    def should_preempt(self, running: Process, now: int, quantum_used: int) -> bool:
        """True = take the CPU away from the running process now."""
        return False

    def on_tick(self, now: int) -> None:
        """Called once per tick before dispatch (used for aging)."""

    @abstractmethod
    def ready_pids(self) -> List[int]:
        """PIDs in the ready queue, in the order they would be picked."""

    def __len__(self) -> int:
        return len(self.ready_pids())


# ---- Memory manager: a fixed pool of memory shared by all processes ----
class MemoryManager(ABC):
    """allocate() returns False when memory is short (normal, never an error).
    ResourceError is only for misuse, such as freeing memory that was never given."""

    def __init__(self, total_kb: int, log: Optional[EventLog] = None) -> None:
        self.total_kb = total_kb
        self.log = log or EventLog(echo=False)

    @abstractmethod
    def allocate(self, pid: int, size_kb: int, now: int) -> bool:
        """Give `pid` `size_kb` of memory if possible."""

    @abstractmethod
    def free(self, pid: int, now: int) -> int:
        """Release `pid`'s memory; return the KB freed."""

    @property
    @abstractmethod
    def used_kb(self) -> int:
        """KB currently allocated."""

    @property
    def free_kb(self) -> int:
        return self.total_kb - self.used_kb

    @property
    def largest_free_block_kb(self) -> int:
        return self.free_kb

    def memory_map(self) -> str:
        """Optional: one-line picture of memory."""
        return ""

    def summary_lines(self) -> List[str]:
        """Optional: lines printed under the final report."""
        return []


# ---- I/O manager: one queue per device; devices work alongside the CPU ----
class IOManager(ABC):
    """submit() queues a process's I/O burst. advance() serves every device for one
    tick and returns the processes whose I/O just finished (engine makes them READY)."""

    def __init__(self, devices, log: Optional[EventLog] = None) -> None:
        self.devices = tuple(devices)
        self.log = log or EventLog(echo=False)

    @abstractmethod
    def submit(self, proc: Process, now: int) -> None: ...

    @abstractmethod
    def advance(self, now: int) -> List[Process]: ...

    @abstractmethod
    def queue_lengths(self) -> Dict[str, int]:
        """Requests queued or in service, per device."""

    @abstractmethod
    def busy_ticks(self) -> Dict[str, int]:
        """Ticks each device spent serving requests (for utilisation)."""

    def held_pids(self) -> Optional[List[int]]:
        """Optional, for --check: every PID queued at or being served by a device."""
        return None


# ---- Power manager: battery model for the optional power-aware bonus ----
class PowerManager(ABC):
    @abstractmethod
    def consume_cpu(self, proc: Process, now: int) -> None:
        """Charge one tick of CPU work by `proc`."""

    @abstractmethod
    def consume_idle(self, now: int) -> None:
        """Charge one idle tick."""

    @abstractmethod
    def is_depleted(self) -> bool: ...

    @property
    @abstractmethod
    def remaining(self) -> Optional[float]:
        """Energy left (None = no battery model)."""

    def can_afford(self, proc: Process) -> bool:
        """For power-aware schedulers: can the battery pay for one more tick of `proc`?"""
        return not self.is_depleted()
