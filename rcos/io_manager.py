"""I/O devices and queues (OWNER: Member 4).

SimpleIOManager: one FIFO queue per device, one request served at a time per
device, each device works in parallel with the CPU.  Member 4 extends it, e.g.
different service speeds, request priorities, device-contention statistics
(queue length over time), an "interrupt"-style completion log.

Timing contract: a request submitted at the end of tick t starts being served in
tick t+1; after `duration` ticks of service it is returned by advance().
"""
from __future__ import annotations

from collections import deque
from typing import Deque, Dict, List, Optional

from .errors import ResourceError
from .eventlog import Category, EventLog
from .interfaces import IOManager
from .process import BurstType, Process


class SimpleIOManager(IOManager):
    def __init__(self, devices, log: Optional[EventLog] = None) -> None:
        super().__init__(devices, log)
        self._queues: Dict[str, Deque[Process]] = {d: deque() for d in self.devices}
        self._current: Dict[str, Optional[Process]] = {d: None for d in self.devices}
        self._busy: Dict[str, int] = {d: 0 for d in self.devices}

    def submit(self, proc: Process, now: int) -> None:
        burst = proc.current_burst
        if burst is None or burst.kind is not BurstType.IO:
            raise ResourceError(f"{proc.label}: current burst is not I/O")
        if burst.device not in self._queues:
            raise ResourceError(f"unknown I/O device {burst.device!r}")
        self._queues[burst.device].append(proc)
        self.log.emit(now, Category.IO,
                      f"REQUEST {burst.device} for {burst.duration} ticks "
                      f"(queue length now {self.queue_lengths()[burst.device]})", proc.pid)

    def advance(self, now: int) -> List[Process]:
        finished: List[Process] = []
        for device in self.devices:
            if self._current[device] is None and self._queues[device]:
                self._current[device] = self._queues[device].popleft()
                self.log.emit(now, Category.IO, f"START {device}", self._current[device].pid)
            proc = self._current[device]
            if proc is None:
                continue
            self._busy[device] += 1
            proc.current_burst.remaining -= 1
            if proc.current_burst.remaining == 0:
                self._current[device] = None
                finished.append(proc)
                self.log.emit(now + 1, Category.IO, f"COMPLETE {device}", proc.pid)
        return finished

    def queue_lengths(self) -> Dict[str, int]:
        return {d: len(self._queues[d]) + (1 if self._current[d] is not None else 0)
                for d in self.devices}

    def busy_ticks(self) -> Dict[str, int]:
        return dict(self._busy)
