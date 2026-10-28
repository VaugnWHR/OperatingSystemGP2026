"""Battery / power model for the optional bonus (OWNER: Member 5 + Member 2).

NullPowerManager  - power not modelled (default; config.battery_capacity is None).
BatteryPowerManager - simple working battery: each CPU tick costs
    proc.power_cost_per_tick, each idle tick costs config.idle_power_cost.
    When the battery reaches 0 the engine shuts the system down.

TODO (bonus): the real "power-aware" part is a SCHEDULING decision - e.g. a
scheduler that uses ResourceSnapshot.battery_remaining and each process's
power cost to choose what to run (or defer) when CPU time AND energy are both
limited, then compare it against FCFS/RR/Priority.  That lives in scheduler.py.
"""
from __future__ import annotations

from typing import Optional

from .eventlog import Category, EventLog
from .interfaces import PowerManager
from .process import Process


class NullPowerManager(PowerManager):
    def consume_cpu(self, proc: Process, now: int) -> None: pass
    def consume_idle(self, now: int) -> None: pass
    def is_depleted(self) -> bool: return False

    @property
    def remaining(self) -> Optional[float]:
        return None


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
