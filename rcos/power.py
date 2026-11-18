"""Battery model for the optional power-aware bonus (owner: Member 5, with Member 2).

Off by default. With --battery, every CPU tick costs the running process's
power_cost_per_tick, every idle tick costs idle_power_cost, and the system shuts
down when the battery reaches 0.
"""
from __future__ import annotations

from typing import Optional

from .eventlog import Category, EventLog
from .interfaces import PowerManager
from .process import Process


# ---- No battery: power is not modelled ----
class NullPowerManager(PowerManager):
    def consume_cpu(self, proc: Process, now: int) -> None: pass
    def consume_idle(self, now: int) -> None: pass
    def is_depleted(self) -> bool: return False

    @property
    def remaining(self) -> Optional[float]:
        return None


# ---- Battery: drains with every tick of work or idling ----
class BatteryPowerManager(PowerManager):
    def __init__(self, capacity: float, idle_cost: float = 0.1,
                 log: Optional[EventLog] = None) -> None:
        self.capacity = capacity
        self.idle_cost = idle_cost
        self.log = log or EventLog(echo=False)
        self._remaining = capacity
        self._depleted_logged = False

    def _drain(self, amount: float, now: int) -> None:
        self._remaining = max(0.0, self._remaining - amount)
        if self._remaining == 0.0 and not self._depleted_logged:
            self._depleted_logged = True
            self.log.emit(now + 1, Category.POWER, "BATTERY DEPLETED")

    def consume_cpu(self, proc: Process, now: int) -> None:
        self._drain(proc.power_cost_per_tick, now)

    def consume_idle(self, now: int) -> None:
        self._drain(self.idle_cost, now)

    def is_depleted(self) -> bool:
        return self._remaining <= 0.0

    @property
    def remaining(self) -> Optional[float]:
        return self._remaining
