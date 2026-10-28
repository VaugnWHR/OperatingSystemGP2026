"""Central resource manager (OWNER: Member 1).

Every resource request in the simulator goes through here: CPU, memory, I/O and
power.  This is the single place that enforces "one process on the CPU", keeps
track of who holds what, and produces snapshots for the scheduler and metrics.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional, Set

from .errors import ResourceError
from .eventlog import Category, EventLog
from .interfaces import IOManager, MemoryManager, PowerManager, ResourceSnapshot
from .process import BurstType, Process


class AllocResult(Enum):
    GRANTED = "GRANTED"        # process now holds its memory
    DENIED = "DENIED"          # not enough free memory right now - try again later
    IMPOSSIBLE = "IMPOSSIBLE"  # can never fit (bigger than total memory) - reject


class ResourceManager:
    def __init__(self, memory: MemoryManager, io: IOManager,
                 power: PowerManager, log: EventLog) -> None:
        self.memory = memory
        self.io = io
        self.power = power
        self.log = log
        self._cpu_owner: Optional[int] = None
        self._holding_memory: Set[int] = set()
        self._denial_logged: Set[int] = set()   # log a denial once, not every retry

    # -------------------------------------------------------------------- CPU
    @property
    def cpu_owner(self) -> Optional[int]:
        return self._cpu_owner

    def assign_cpu(self, proc: Process) -> None:
        if self._cpu_owner is not None:
            raise ResourceError(
                f"CPU already held by P{self._cpu_owner:02d}; cannot assign to {proc.label}")
        self._cpu_owner = proc.pid

    def release_cpu(self, proc: Process) -> None:
        if self._cpu_owner != proc.pid:
            raise ResourceError(f"{proc.label} does not hold the CPU (owner: {self._cpu_owner})")
        self._cpu_owner = None

    # ----------------------------------------------------------------- memory
    def allocate_memory(self, proc: Process, now: int) -> AllocResult:
        if proc.pid in self._holding_memory:
            raise ResourceError(f"{proc.label} already holds memory")
        if proc.memory_kb > self.memory.total_kb:
            self.log.emit(now, Category.MEM,
                          f"REJECT needs {proc.memory_kb}KB but system has only "
                          f"{self.memory.total_kb}KB", proc.pid)
            return AllocResult.IMPOSSIBLE
        if self.memory.allocate(proc.pid, proc.memory_kb, now):
            self._holding_memory.add(proc.pid)
            self._denial_logged.discard(proc.pid)
            return AllocResult.GRANTED
        if proc.pid not in self._denial_logged:
            self._denial_logged.add(proc.pid)
            self.log.emit(now, Category.MEM,
                          f"DENIED {proc.memory_kb}KB (free {self.memory.free_kb}KB, largest "
                          f"block {self.memory.largest_free_block_kb}KB) - waiting in job queue",
                          proc.pid)
        return AllocResult.DENIED

    def release_memory(self, proc: Process, now: int) -> int:
        """Free the process's memory (no-op if it never got any). Returns KB freed."""
        if proc.pid not in self._holding_memory:
            return 0
        self._holding_memory.discard(proc.pid)
        return self.memory.free(proc.pid, now)

    # -------------------------------------------------------------------- I/O
    def request_io(self, proc: Process, now: int) -> None:
        burst = proc.current_burst
        if burst is None or burst.kind is not BurstType.IO:
            raise ResourceError(f"{proc.label} has no pending I/O burst")
        if burst.device not in self.io.devices:
            raise ResourceError(f"{proc.label} requested unknown device {burst.device!r}")
        self.io.submit(proc, now)

    # --------------------------------------------------------------- snapshot
    def snapshot(self, now: int) -> ResourceSnapshot:
        return ResourceSnapshot(
            time=now,
            cpu_owner=self._cpu_owner,
            mem_used_kb=self.memory.used_kb,
            mem_total_kb=self.memory.total_kb,
            mem_largest_free_kb=self.memory.largest_free_block_kb,
            io_queue_lengths=self.io.queue_lengths(),
            battery_remaining=self.power.remaining,
        )
