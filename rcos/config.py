"""Machine settings (Member 1: Juvaugn).

One SystemConfig describes the whole simulated device. Conventions used everywhere:
time is in whole ticks, memory is in KB, and a LOWER priority number = HIGHER priority.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from .errors import ConfigError

MEMORY_STRATEGIES = ("first", "best", "worst", "next")


# ---- Settings: every limit of the simulated machine, with defaults ----
@dataclass(frozen=True)
class SystemConfig:
    total_memory_kb: int = 512
    memory_strategy: str = "first"           # first | best | worst | next fit
    memory_compaction: bool = False          # compact when fragmentation blocks a request
    show_memory_map: bool = False            # log the memory map after every change
    time_quantum: int = 3                    # Round Robin time slice
    io_devices: Tuple[str, ...] = ("SENSOR", "FLASH", "RADIO")
    scheduler: str = "fcfs"                  # fcfs | rr | priority
    max_ticks: int = 5000                    # safety stop
    check_invariants: bool = False           # --check
    priority_aging_interval: int = 0         # 0 = aging off
    battery_capacity: Optional[float] = None # None = power not modelled
    idle_power_cost: float = 0.1             # energy per idle CPU tick
    log_to_console: bool = True

    # ---- Validation: reject impossible settings up front ----
    def __post_init__(self) -> None:
        if self.total_memory_kb <= 0:
            raise ConfigError("total_memory_kb must be > 0")
        if self.memory_strategy not in MEMORY_STRATEGIES:
            raise ConfigError(f"memory_strategy must be one of {', '.join(MEMORY_STRATEGIES)}")
        if self.time_quantum <= 0:
            raise ConfigError("time_quantum must be > 0")
        if self.max_ticks <= 0:
            raise ConfigError("max_ticks must be > 0")
        if self.priority_aging_interval < 0:
            raise ConfigError("priority_aging_interval must be >= 0")
        if not self.io_devices or len(set(self.io_devices)) != len(self.io_devices):
            raise ConfigError("io_devices must be a non-empty list of unique names")
        if self.battery_capacity is not None and self.battery_capacity <= 0:
            raise ConfigError("battery_capacity must be > 0 (or None to disable power)")
        if self.idle_power_cost < 0:
            raise ConfigError("idle_power_cost must be >= 0")
