"""Demo workloads (owner: Member 5). Pick one with --scenario NAME.

Each function returns fresh processes for the default 512KB machine with
SENSOR, FLASH and RADIO devices. load_scenario() reads a JSON file instead.
"""
from __future__ import annotations

import json
from typing import Callable, Dict, List

from .errors import ConfigError
from .process import Process, cpu_burst as cpu, io_burst as io


# ---- Built-in scenarios: each shows one OS problem ----
def basic() -> List[Process]:
    """Mixed workload; P04 waits for memory until another process finishes."""
    return [
        Process(1, "sensor_read",     0, 2, 128, [cpu(4), io("SENSOR", 3), cpu(2)]),
        Process(2, "data_logger",     1, 3, 192, [cpu(3), io("FLASH", 4), cpu(3)]),
        Process(3, "radio_tx",        2, 1, 160, [cpu(2), io("RADIO", 5), cpu(1)]),
        Process(4, "firmware_update", 3, 4, 256, [cpu(6), io("FLASH", 3), cpu(4)]),
        Process(5, "watchdog",        5, 0,  32, [cpu(1), io("SENSOR", 2), cpu(1)]),
    ]


def memory_pressure() -> List[Process]:
    """Large processes; one is bigger than all memory and is rejected."""
    return [
        Process(1, "camera_buf",  0, 2, 300, [cpu(5), io("FLASH", 2), cpu(2)]),
        Process(2, "ml_model",    1, 1, 400, [cpu(4), io("SENSOR", 1), cpu(1)]),
        Process(3, "huge_image",  2, 3, 1024, [cpu(3)]),
        Process(4, "tiny_task",   2, 5,  16, [cpu(2)]),
    ]


def io_heavy() -> List[Process]:
    """Five processes queue for the same FLASH device (I/O contention)."""
    return [Process(i, f"flash_job_{i}", i, 3, 64, [cpu(1), io("FLASH", 4), cpu(1)])
            for i in range(1, 6)]


def fragmentation() -> List[Process]:
    """External fragmentation: P02 and P04 leave two separate 128KB holes, so P05
    (200KB) waits although 256KB is free. Try --compact."""
    return [
        Process(1, "camera_driver", 0, 2, 128, [cpu(1), io("FLASH", 20), cpu(1)]),
        Process(2, "button_check",  0, 3, 128, [cpu(2)]),
        Process(3, "radio_stack",   0, 2, 128, [cpu(1), io("RADIO", 20), cpu(1)]),
        Process(4, "led_blink",     0, 3, 128, [cpu(2)]),
        Process(5, "image_buffer",  1, 1, 200, [cpu(3)]),
    ]


def placement() -> List[Process]:
    """Placement: holes of 200KB and 132KB, then requests of 110KB and 200KB.
    Best fit (and next fit here) uses the 132KB hole and keeps 200KB free for P06;
    first and worst fit split the 200KB hole, so P06 waits. Try --compare-memory."""
    return [
        Process(1, "logger",       0, 2, 100, [cpu(1), io("FLASH", 30), cpu(1)]),
        Process(2, "boot_check",   0, 3, 200, [cpu(2)]),
        Process(3, "net_stack",    0, 2,  80, [cpu(1), io("RADIO", 30), cpu(1)]),
        Process(4, "self_test",    0, 3, 120, [cpu(2)]),
        Process(5, "sample_task",  6, 2, 110, [cpu(1), io("SENSOR", 12), cpu(1)]),
        Process(6, "frame_buffer", 7, 2, 200, [cpu(3)]),
    ]


# ---- Lookup and loading ----
SCENARIOS: Dict[str, Callable[[], List[Process]]] = {
    "basic": basic, "memory_pressure": memory_pressure, "io_heavy": io_heavy,
    "fragmentation": fragmentation, "placement": placement,
}


def get_scenario(name: str) -> List[Process]:
    try:
        return SCENARIOS[name]()
    except KeyError:
        raise ConfigError(f"unknown scenario {name!r} (choose: {', '.join(SCENARIOS)})") from None


def load_scenario(path: str) -> List[Process]:
    """Read a JSON list of processes (format shown in Process.from_dict)."""
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot read scenario file {path!r}: {exc}") from exc
    if not isinstance(data, list):
        raise ConfigError("scenario file must contain a JSON list of processes")
    return [Process.from_dict(item) for item in data]
