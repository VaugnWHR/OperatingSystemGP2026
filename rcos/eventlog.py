"""Structured event log (OWNER: Member 1; Member 5 consumes it).

LOG FORMAT (fixed - do not change without telling Member 1 and Member 5):

    [t=0012] [STATE ] [P03] sensor_read READY -> RUNNING (dispatched)
    [t=0014] [MEM   ] [P04] DENIED 256KB (free 32KB, largest block 32KB) - waiting in job queue
    [t=0020] [SYSTEM] [---] END ...

    [t=<tick, 4 digits>] [<CATEGORY, 6 wide>] [P<pid, 2 digits> or ---] <message>

Categories: SYSTEM (start/end), STATE (process state changes), SCHED (scheduler
decisions), MEM, IO, RES (resource manager), POWER, WARN.
"""
from __future__ import annotations

import csv
import sys
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, TextIO


class Category(Enum):
    SYSTEM = "SYSTEM"
    STATE = "STATE"
    SCHED = "SCHED"
    MEM = "MEM"
    IO = "IO"
    RES = "RES"
    POWER = "POWER"
    WARN = "WARN"


@dataclass(frozen=True)
class LogEvent:
    time: int
    category: Category
    message: str
    pid: Optional[int] = None

    def format(self) -> str:
        who = f"P{self.pid:02d}" if self.pid is not None else "---"
        return f"[t={self.time:04d}] [{self.category.value:<6}] [{who}] {self.message}"


class EventLog:
    """Collects every event (for metrics/tests/CSV) and optionally echoes it."""

    def __init__(self, echo: bool = True, stream: Optional[TextIO] = None) -> None:
        self.echo = echo
        self._stream = stream
        self.events: List[LogEvent] = []

    def emit(self, time: int, category: Category, message: str,
             pid: Optional[int] = None) -> LogEvent:
        event = LogEvent(time, category, message, pid)
        self.events.append(event)
        if self.echo:
            print(event.format(), file=self._stream or sys.stdout)
        return event

    def filter(self, category: Optional[Category] = None,
               pid: Optional[int] = None) -> List[LogEvent]:
        return [e for e in self.events
                if (category is None or e.category is category)
                and (pid is None or e.pid == pid)]

    def to_csv(self, path: str) -> None:
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["time", "category", "pid", "message"])
            for e in self.events:
                writer.writerow([e.time, e.category.value, e.pid if e.pid is not None else "", e.message])
