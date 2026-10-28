"""System resource configuration (OWNER: Member 1).

One frozen SystemConfig describes the whole simulated machine.  Anything a
module needs to know about the machine's limits comes from here, so scenarios
can be changed without touching code.

CONVENTIONS (everyone must follow these):
  * Time is measured in integer TICKS.  1 tick = 1 unit of CPU time.
  * Memory is measured in KB (integers).
  * PRIORITY: LOWER NUMBER = HIGHER PRIORITY (0 is most urgent).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from .errors import ConfigError


@dataclass(frozen=True)
class SystemConfig:
    total_memory_kb: int = 512                       # small on purpose: constrained device
    time_quantum: int = 3                            # used by Round Robin
    io_devices: Tuple[str, ...] = ("SENSOR", "FLASH", "RADIO")
    scheduler: str = "fcfs"                          # "fcfs" | "rr" | "priority"
    max_ticks: int = 5000                            # safety stop against infinite runs
    priority_aging_interval: int = 0                 # 0 = aging off (Member 2 may use)
    battery_capacity: Optional[float] = None         # None = power not modelled (bonus)
    idle_power_cost: float = 0.1                     # energy per idle CPU tick (bonus)
    log_to_console: bool = True

    def __post_init__(self) -> None:
        if self.total_memory_kb <= 0:
            raise ConfigError("total_memory_kb must be > 0")
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
