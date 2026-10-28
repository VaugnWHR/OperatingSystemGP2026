"""Test scenarios (OWNER: Member 5 - add more here).

Each scenario is a function returning a fresh list of Process objects
(processes are mutable, so never share them between runs).
Scenarios are written for the default config: 512KB memory, devices SENSOR/FLASH/RADIO.
"""
from __future__ import annotations

import json
from typing import Callable, Dict, List

from .errors import ConfigError
from .process import Process, cpu_burst as cpu, io_burst as io


def basic() -> List[Process]:
    """Mixed workload; P4 cannot be admitted until memory frees (memory contention)."""
    return [
        Process(1, "sensor_read",     0, 2, 128, [cpu(4), io("SENSOR", 3), cpu(2)]),
        Process(2, "data_logger",     1, 3, 192, [cpu(3), io("FLASH", 4), cpu(3)]),
        Process(3, "radio_tx",        2, 1, 160, [cpu(2), io("RADIO", 5), cpu(1)]),
        Process(4, "firmware_update", 3, 4, 256, [cpu(6), io("FLASH", 3), cpu(4)]),
        Process(5, "watchdog",        5, 0,  32, [cpu(1), io("SENSOR", 2), cpu(1)]),
    ]


def memory_pressure() -> List[Process]:
    """Several large processes + one that can never fit (rejected)."""
    return [
        Process(1, "camera_buf",  0, 2, 300, [cpu(5), io("FLASH", 2), cpu(2)]),
        Process(2, "ml_model",    1, 1, 400, [cpu(4), io("SENSOR", 1), cpu(1)]),
        Process(3, "huge_image",  2, 3, 1024, [cpu(3)]),
        Process(4, "tiny_task",   2, 5,  16, [cpu(2)]),
    ]


def io_heavy() -> List[Process]:
    """Many processes fighting for the same device (I/O contention)."""
    return [Process(i, f"flash_job_{i}", i, 3, 64, [cpu(1), io("FLASH", 4), cpu(1)])
            for i in range(1, 6)]


SCENARIOS: Dict[str, Callable[[], List[Process]]] = {
    "basic": basic, "memory_pressure": memory_pressure, "io_heavy": io_heavy,
}


def get_scenario(name: str) -> List[Process]:
    try:
        return SCENARIOS[name]()
    except KeyError:
        raise ConfigError(f"unknown scenario {name!r} (choose: {', '.join(SCENARIOS)})") from None


def load_scenario(path: str) -> List[Process]:
    """Load processes from JSON: a list of objects as described in Process.from_dict."""
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot read scenario file {path!r}: {exc}") from exc
    if not isinstance(data, list):
        raise ConfigError("scenario file must contain a JSON list of processes")
    return [Process.from_dict(item) for item in data]
