"""Limited memory pool (OWNER: Member 3).

SimpleMemoryManager is a baseline: a single counter with a per-process table.
It has NO placement strategy and therefore NO fragmentation.  Member 3 replaces
or extends it (e.g. contiguous variable partitions with first-fit / best-fit,
free-list coalescing, external-fragmentation reporting, largest_free_block_kb).

Contract reminders (interfaces.MemoryManager):
  allocate() -> False on ordinary failure (never raise); free() returns KB freed;
  raise ResourceError for contract violations only.
"""
from __future__ import annotations

from typing import Dict, Optional

from .errors import ResourceError
from .eventlog import Category, EventLog
from .interfaces import MemoryManager


class SimpleMemoryManager(MemoryManager):
    def __init__(self, total_kb: int, log: Optional[EventLog] = None) -> None:
        super().__init__(total_kb, log)
        self._allocations: Dict[int, int] = {}

    def allocate(self, pid: int, size_kb: int, now: int) -> bool:
        if size_kb <= 0:
            raise ResourceError(f"invalid allocation size {size_kb}KB for pid {pid}")
        if pid in self._allocations:
            raise ResourceError(f"pid {pid} already has memory allocated")
        if size_kb > self.free_kb:
            return False
        self._allocations[pid] = size_kb
        self.log.emit(now, Category.MEM,
                      f"ALLOC {size_kb}KB (used {self.used_kb}/{self.total_kb}KB)", pid)
        return True

    def free(self, pid: int, now: int) -> int:
        if pid not in self._allocations:
            raise ResourceError(f"pid {pid} has no memory to free")
        size = self._allocations.pop(pid)
        self.log.emit(now, Category.MEM,
                      f"FREE {size}KB (used {self.used_kb}/{self.total_kb}KB)", pid)
        return size

    @property
    def used_kb(self) -> int:
        return sum(self._allocations.values())
