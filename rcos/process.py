"""Process model: states, bursts and the Process Control Block (OWNER: Member 1).

5-STATE MODEL used by the whole project:

    NEW ──admit (memory granted)──> READY ──dispatch──> RUNNING ──CPU burst done──> TERMINATED
                                      ^  <──preempt────────┤  │
                                      │                    │  └──I/O request──> WAITING
                                      └────I/O complete────┴──────────────────────┘

  NEW        arrived, but not yet given memory (waiting in the job queue)
  READY      in memory, waiting for the CPU (the scheduler's ready queue)
  RUNNING    currently on the CPU (only ONE process at a time)
  WAITING    blocked on an I/O device (queued or being served)
  TERMINATED finished, rejected, or aborted (memory already freed)

A process is a list of bursts that must ALTERNATE and START WITH CPU:
    CPU(4) -> IO(FLASH,3) -> CPU(2)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from .errors import ConfigError, InvalidStateTransition


class ProcessState(Enum):
    NEW = "NEW"
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    TERMINATED = "TERMINATED"


ALLOWED_TRANSITIONS: Dict[ProcessState, set] = {
    ProcessState.NEW: {ProcessState.READY, ProcessState.TERMINATED},
    ProcessState.READY: {ProcessState.RUNNING, ProcessState.TERMINATED},
    ProcessState.RUNNING: {ProcessState.READY, ProcessState.WAITING, ProcessState.TERMINATED},
    ProcessState.WAITING: {ProcessState.READY, ProcessState.TERMINATED},
    ProcessState.TERMINATED: set(),
}


class BurstType(Enum):
    CPU = "CPU"
    IO = "IO"


@dataclass
class Burst:
    """One CPU or I/O burst.  `remaining` counts down as the burst is served."""
    kind: BurstType
    duration: int
    device: Optional[str] = None
    remaining: int = field(init=False, default=0)

    def __post_init__(self) -> None:
        if self.duration <= 0:
            raise ConfigError(f"burst duration must be > 0 (got {self.duration})")
        if self.kind is BurstType.IO and not self.device:
            raise ConfigError("an IO burst needs a device name")
        if self.kind is BurstType.CPU and self.device:
            raise ConfigError("a CPU burst must not name a device")
        self.remaining = self.duration


def cpu_burst(duration: int) -> Burst:
    return Burst(BurstType.CPU, duration)


def io_burst(device: str, duration: int) -> Burst:
    return Burst(BurstType.IO, duration, device)


@dataclass(eq=False)  # identity equality: two processes are never "equal"
class Process:
    """Process Control Block (PCB) + the accounting the metrics need."""
    pid: int
    name: str
    arrival_time: int
    priority: int                       # LOWER number = HIGHER priority
    memory_kb: int
    bursts: List[Burst]
    power_cost_per_tick: float = 1.0    # used by the power-aware bonus

    # ---- runtime fields (managed by the engine; do not set from outside) ----
    state: ProcessState = field(default=ProcessState.NEW, init=False)
    burst_index: int = field(default=0, init=False)
    first_run_time: Optional[int] = field(default=None, init=False)
    finish_time: Optional[int] = field(default=None, init=False)
    exit_reason: str = field(default="", init=False)
    cpu_time_used: int = field(default=0, init=False)
    time_in_state: Dict[ProcessState, int] = field(
        default_factory=lambda: {s: 0 for s in ProcessState}, init=False, repr=False)
    _state_entered: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.name:
            raise ConfigError("process needs a name")
        if self.arrival_time < 0:
            raise ConfigError(f"P{self.pid}: arrival_time must be >= 0")
        if self.memory_kb <= 0:
            raise ConfigError(f"P{self.pid}: memory_kb must be > 0")
        if self.power_cost_per_tick < 0:
            raise ConfigError(f"P{self.pid}: power_cost_per_tick must be >= 0")
        if not self.bursts:
            raise ConfigError(f"P{self.pid}: needs at least one burst")
        for i, burst in enumerate(self.bursts):
            expected = BurstType.CPU if i % 2 == 0 else BurstType.IO
            if burst.kind is not expected:
                raise ConfigError(
                    f"P{self.pid}: bursts must alternate CPU/IO starting with CPU "
                    f"(burst {i} is {burst.kind.value})")
        self._state_entered = self.arrival_time

    # ------------------------------------------------------------------ helpers
    @property
    def label(self) -> str:
        return f"P{self.pid:02d}({self.name})"

    @property
    def current_burst(self) -> Optional[Burst]:
        return self.bursts[self.burst_index] if self.burst_index < len(self.bursts) else None

    @property
    def total_cpu_demand(self) -> int:
        return sum(b.duration for b in self.bursts if b.kind is BurstType.CPU)

    @property
    def remaining_cpu_demand(self) -> int:
        """Total CPU ticks still needed (useful for SJF-style / resource-aware schedulers)."""
        return sum(b.remaining for b in self.bursts[self.burst_index:] if b.kind is BurstType.CPU)

    def advance_burst(self) -> bool:
        """Move to the next burst.  Returns True if another burst exists."""
        self.burst_index += 1
        return self.burst_index < len(self.bursts)

    # -------------------------------------------------------- state management
    def transition(self, new_state: ProcessState, now: int) -> ProcessState:
        """Validate and apply a state change, updating time-in-state accounting.
        Returns the previous state.  Raises InvalidStateTransition if illegal."""
        if new_state not in ALLOWED_TRANSITIONS[self.state]:
            raise InvalidStateTransition(
                f"{self.label}: {self.state.value} -> {new_state.value} is not allowed")
        if now < self._state_entered:
            raise InvalidStateTransition(
                f"{self.label}: time went backwards ({now} < {self._state_entered})")
        old = self.state
        self.time_in_state[old] += now - self._state_entered
        self.state = new_state
        self._state_entered = now
        if new_state is ProcessState.RUNNING and self.first_run_time is None:
            self.first_run_time = now
        if new_state is ProcessState.TERMINATED:
            self.finish_time = now
        return old

    # ---------------------------------------------------------------- loading
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Process":
        """Build a Process from a JSON-style dict:
        {"pid":1,"name":"sensor_read","arrival":0,"priority":2,"memory_kb":128,
         "power_cost":1.5,
         "bursts":[{"type":"CPU","time":4},{"type":"IO","device":"SENSOR","time":3}]}"""
        try:
            bursts = [Burst(BurstType(b["type"].upper()), int(b["time"]), b.get("device"))
                      for b in data["bursts"]]
            return cls(pid=int(data["pid"]), name=str(data["name"]),
                       arrival_time=int(data.get("arrival", 0)),
                       priority=int(data.get("priority", 5)),
                       memory_kb=int(data["memory_kb"]), bursts=bursts,
                       power_cost_per_tick=float(data.get("power_cost", 1.0)))
        except (KeyError, ValueError, TypeError) as exc:
            raise ConfigError(f"bad process definition {data!r}: {exc}") from exc
