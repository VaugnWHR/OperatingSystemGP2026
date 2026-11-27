"""Memory allocation (Member 3 role: Juvaugn).

Contiguous allocation with dynamic partitions: each process gets one unbroken block
(small devices usually have no MMU, so no paging). Free space is a sorted list of holes.
  allocate: the strategy (first, best, worst or next fit) picks a hole, which is split
  free:     the block becomes a hole and merges with any hole touching it (coalescing)
  failure:  allocate() returns False; if enough is free but no hole fits, that is
            external fragmentation, and optional compaction slides blocks together
            (compaction is free here; a real OS pays CPU time to copy memory)
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from .config import MEMORY_STRATEGIES
from .errors import ConfigError, ResourceError
from .eventlog import Category, EventLog
from .interfaces import MemoryManager


# ---- Region: a run of addresses (a hole or an allocated block) ----
@dataclass(frozen=True, order=True)
class Region:
    start: int
    size: int

    @property
    def end(self) -> int:
        """First address after the region."""
        return self.start + self.size

    def label(self) -> str:
        return f"[{self.start}-{self.end - 1}]"


# ---- Stats: counters for the end-of-run memory summary ----
@dataclass
class MemoryStats:
    allocations: int = 0
    frees: int = 0
    failed_attempts: int = 0                                    # includes every-tick retries
    delayed_pids: Set[int] = field(default_factory=set)         # had to wait for memory
    fragmentation_pids: Set[int] = field(default_factory=set)   # waited although enough was free
    compactions: int = 0
    kb_moved: int = 0
    peak_holes: int = 1
    peak_external_fragmentation: float = 0.0                    # percent


class ContiguousMemoryManager(MemoryManager):
    def __init__(self, total_kb: int, strategy: str = "first", compaction: bool = False,
                 log: Optional[EventLog] = None, show_map: bool = False) -> None:
        super().__init__(total_kb, log)
        if strategy not in MEMORY_STRATEGIES:
            raise ConfigError(f"unknown memory strategy {strategy!r} "
                              f"(choose: {', '.join(MEMORY_STRATEGIES)})")
        self.strategy = strategy
        self.compaction = compaction
        self.show_map = show_map
        self._holes: List[Region] = [Region(0, total_kb)]   # sorted by address
        self._blocks: Dict[int, Region] = {}                 # pid -> its block
        self._next_start = 0                                 # where next fit resumes
        self.stats = MemoryStats()

    # ---- Allocate: find a hole, compact if fragmentation blocks the request, split ----
    def allocate(self, pid: int, size_kb: int, now: int) -> bool:
        if size_kb <= 0:
            raise ResourceError(f"invalid allocation size {size_kb}KB for pid {pid}")
        if pid in self._blocks:
            raise ResourceError(f"pid {pid} already has memory allocated")

        index = self._find_hole(size_kb)
        if index is None:
            self.stats.failed_attempts += 1
            self.stats.delayed_pids.add(pid)
            if size_kb <= self.free_kb:                      # enough in total: fragmentation
                self.stats.fragmentation_pids.add(pid)
                if self.compaction:
                    self._compact(now, pid)
                    index = self._find_hole(size_kb)
            if index is None:
                return False

        hole = self._holes[index]
        block = Region(hole.start, size_kb)
        if hole.size == size_kb:                             # exact fit: hole disappears
            del self._holes[index]
        else:                                                # split: leftover stays a hole
            self._holes[index] = Region(hole.start + size_kb, hole.size - size_kb)
        self._blocks[pid] = block
        self._next_start = block.end
        self.stats.allocations += 1
        self.log.emit(now, Category.MEM,
                      f"ALLOC {size_kb}KB at {block.label()} ({self.strategy} fit; "
                      f"used {self.used_kb}/{self.total_kb}KB, {len(self._holes)} hole(s))", pid)
        self._after_change(now)
        return True

    # ---- Placement strategies: which hole to use (None = nothing fits) ----
    def _find_hole(self, size_kb: int) -> Optional[int]:
        fits = [i for i, hole in enumerate(self._holes) if hole.size >= size_kb]
        if not fits:
            return None
        if self.strategy == "first":
            return fits[0]
        if self.strategy == "best":
            return min(fits, key=lambda i: (self._holes[i].size, self._holes[i].start))
        if self.strategy == "worst":
            return max(fits, key=lambda i: (self._holes[i].size, -self._holes[i].start))
        for i in fits:                                       # next fit: resume after last block
            if self._holes[i].end > self._next_start:
                return i
        return fits[0]                                       # ...or wrap around to the start

    # ---- Free: return the block and merge it with neighbouring holes ----
    def free(self, pid: int, now: int) -> int:
        if pid not in self._blocks:
            raise ResourceError(f"pid {pid} has no memory to free")
        block = self._blocks.pop(pid)
        merged = self._insert_hole(block)
        self.stats.frees += 1
        note = "" if merged == block else f", merged into free hole {merged.label()} ({merged.size}KB)"
        self.log.emit(now, Category.MEM,
                      f"FREE {block.size}KB at {block.label()}{note} "
                      f"(used {self.used_kb}/{self.total_kb}KB)", pid)
        self._after_change(now)
        return block.size

    def _insert_hole(self, region: Region) -> Region:
        index = bisect.bisect_left(self._holes, region)
        self._holes.insert(index, region)
        # merge with the hole AFTER it
        if index + 1 < len(self._holes) and self._holes[index].end == self._holes[index + 1].start:
            after = self._holes.pop(index + 1)
            self._holes[index] = Region(self._holes[index].start, self._holes[index].size + after.size)
        # merge with the hole BEFORE it
        if index > 0 and self._holes[index - 1].end == self._holes[index].start:
            current = self._holes.pop(index)
            index -= 1
            self._holes[index] = Region(self._holes[index].start, self._holes[index].size + current.size)
        return self._holes[index]

    # ---- Compaction: slide every block down so all free space is one hole ----
    def _compact(self, now: int, requester: int) -> None:
        address, moved_blocks, moved_kb = 0, 0, 0
        for pid, block in sorted(self._blocks.items(), key=lambda item: item[1].start):
            if block.start != address:
                moved_blocks += 1
                moved_kb += block.size
                self._blocks[pid] = Region(address, block.size)
            address += block.size
        self._holes = [Region(address, self.total_kb - address)] if address < self.total_kb else []
        self._next_start = address
        self.stats.compactions += 1
        self.stats.kb_moved += moved_kb
        self.log.emit(now, Category.MEM,
                      f"COMPACT moved {moved_blocks} block(s), {moved_kb}KB copied; free space is now "
                      f"one {self.free_kb}KB hole", requester)

    # ---- Read-only views: usage, holes, fragmentation, memory map, summary ----
    @property
    def used_kb(self) -> int:
        return sum(block.size for block in self._blocks.values())

    @property
    def largest_free_block_kb(self) -> int:
        return max((hole.size for hole in self._holes), default=0)

    @property
    def holes(self) -> Tuple[Region, ...]:
        return tuple(self._holes)

    def block_of(self, pid: int) -> Optional[Region]:
        return self._blocks.get(pid)

    @property
    def external_fragmentation(self) -> float:
        """Percent of free memory outside the largest hole (0 = all of it usable)."""
        free = self.free_kb
        return 0.0 if free == 0 else 100.0 * (1 - self.largest_free_block_kb / free)

    def memory_map(self) -> str:
        """e.g. [0-127 P01] [128-255 free 128KB] [256-511 P03]"""
        regions = [(block.start, block.end, f"P{pid:02d}") for pid, block in self._blocks.items()]
        regions += [(hole.start, hole.end, f"free {hole.size}KB") for hole in self._holes]
        return " ".join(f"[{start}-{end - 1} {what}]" for start, end, what in sorted(regions))

    def summary_lines(self) -> List[str]:
        s = self.stats
        return [
            f"Placement strategy      : {self.strategy} fit | compaction {'on' if self.compaction else 'off'}",
            f"Allocations / frees     : {s.allocations} / {s.frees}",
            f"Processes kept waiting  : {len(s.delayed_pids)} "
            f"({len(s.fragmentation_pids)} of them by external fragmentation)",
            f"Failed attempts         : {s.failed_attempts} (each waiting process retries every tick)",
            f"Peak holes / peak frag. : {s.peak_holes} / {s.peak_external_fragmentation:.1f}%",
            f"Compactions             : {s.compactions} ({s.kb_moved}KB copied)",
        ]

    # ---- Self-check: holes sorted and merged, regions cover memory exactly ----
    def check(self) -> None:
        for a, b in zip(self._holes, self._holes[1:]):
            if a.start >= b.start:
                raise ResourceError(f"holes out of order: {a} before {b}")
            if a.end == b.start:
                raise ResourceError(f"holes not coalesced: {a} touches {b}")
        regions = sorted(list(self._holes) + list(self._blocks.values()))
        address = 0
        for region in regions:
            if region.size <= 0:
                raise ResourceError(f"empty region {region}")
            if region.start != address:
                raise ResourceError(f"gap or overlap at address {address} (next region {region})")
            address = region.end
        if address != self.total_kb:
            raise ResourceError(f"regions cover {address}KB, expected {self.total_kb}KB")

    def _after_change(self, now: int) -> None:
        self.stats.peak_holes = max(self.stats.peak_holes, len(self._holes))
        self.stats.peak_external_fragmentation = max(self.stats.peak_external_fragmentation,
                                                     self.external_fragmentation)
        if self.show_map:
            self.log.emit(now, Category.MEM, "MAP " + self.memory_map())
