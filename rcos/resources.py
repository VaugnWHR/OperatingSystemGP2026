"""Resource manager (Member 1: Juvaugn).

The one place that hands out the CPU, memory, I/O devices and power, and keeps
track of who holds what. Enforces "only one process on the CPU".
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, Optional, Set

from .errors import ResourceError
from .eventlog import Category, EventLog
from .interfaces import IOManager, MemoryManager, PowerManager, ResourceSnapshot
from .process import BurstType, Process


class AllocResult(Enum):
    GRANTED = "GRANTED"        # process now holds its memory
    DENIED = "DENIED"          # not enough right now: wait and retry
    IMPOSSIBLE = "IMPOSSIBLE"  # bigger than all memory: reject


class ResourceManager:
    def __init__(self, memory: MemoryManager, io: IOManager,
                 power: PowerManager, log: EventLog) -> None:
        self.memory = memory
        self.io = io
        self.power = power
        self.log = log
        self._cpu_owner: Optional[int] = None
        self._holding_memory: Set[int] = set()
        self._denial_logged: Dict[int, str] = {}   # pid -> last denial reason logged

    @property
    def memory_holders(self) -> frozenset:
        return frozenset(self._holding_memory)

    # ---- CPU: give it to one process at a time ----
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

    # ---- Memory: grant, deny (and say why) or reject a request ----
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
            self._denial_logged.pop(proc.pid, None)
            return AllocResult.GRANTED
        free, largest = self.memory.free_kb, self.memory.largest_free_block_kb
        reason = ("external fragmentation: enough free in total, but no single hole fits"
                  if proc.memory_kb <= free else "not enough free memory")
        if self._denial_logged.get(proc.pid) != reason:      # log once per reason, not every tick
            self._denial_logged[proc.pid] = reason
            self.log.emit(now, Category.MEM,
                          f"DENIED {proc.memory_kb}KB (free {free}KB, largest hole {largest}KB) - "
                          f"{reason}; waiting in job queue", proc.pid)
        return AllocResult.DENIED

    def release_memory(self, proc: Process, now: int) -> int:
        if proc.pid not in self._holding_memory:
            return 0
        self._holding_memory.discard(proc.pid)
        return self.memory.free(proc.pid, now)

    # ---- I/O: check the request, then hand it to the device queues ----
    def request_io(self, proc: Process, now: int) -> None:
        burst = proc.current_burst
        if burst is None or burst.kind is not BurstType.IO:
            raise ResourceError(f"{proc.label} has no pending I/O burst")
        if burst.device not in self.io.devices:
            raise ResourceError(f"{proc.label} requested unknown device {burst.device!r}")
        self.io.submit(proc, now)

    # ---- Snapshot: current state of every resource ----
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
