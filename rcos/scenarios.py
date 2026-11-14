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


def fragmentation() -> List[Process]:
    """External fragmentation (Member 3 demo).  Four 128KB processes fill 512KB.
    The two short ones (P02, P04) finish first and leave two 128KB holes that are
    NOT next to each other.  P05 needs 200KB: 256KB is free in total, but no single
    hole is big enough, so it waits.  Run with --compact to see compaction fix it."""
    return [
        Process(1, "camera_driver", 0, 2, 128, [cpu(1), io("FLASH", 20), cpu(1)]),
        Process(2, "button_check",  0, 3, 128, [cpu(2)]),
        Process(3, "radio_stack",   0, 2, 128, [cpu(1), io("RADIO", 20), cpu(1)]),
        Process(4, "led_blink",     0, 3, 128, [cpu(2)]),
        Process(5, "image_buffer",  1, 1, 200, [cpu(3)]),
    ]


def placement() -> List[Process]:
    """Placement strategies (Member 3 demo).  By t=6 memory has two holes of
    different sizes: 200KB at [100-299] and 132KB at [380-511].  P05 asks for 110KB,
    then P06 asks for 200KB.
      best fit  puts P05 in the 132KB hole, so the 200KB hole is still whole for P06.
      first fit and worst fit put P05 in the 200KB hole, so P06 is blocked by
      external fragmentation until P05 finishes its sensor read.
      next fit starts searching after the last allocation (address 500), so here it
      happens to pick the 132KB hole too.
    Compare with:  python main.py --scenario placement --compare-memory"""
    return [
        Process(1, "logger",       0, 2, 100, [cpu(1), io("FLASH", 30), cpu(1)]),
        Process(2, "boot_check",   0, 3, 200, [cpu(2)]),
        Process(3, "net_stack",    0, 2,  80, [cpu(1), io("RADIO", 30), cpu(1)]),
        Process(4, "self_test",    0, 3, 120, [cpu(2)]),
        Process(5, "sample_task",  6, 2, 110, [cpu(1), io("SENSOR", 12), cpu(1)]),
        Process(6, "frame_buffer", 7, 2, 200, [cpu(3)]),
    ]


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
    """Load processes from JSON: a list of objects as described in Process.from_dict."""
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot read scenario file {path!r}: {exc}") from exc
    if not isinstance(data, list):
        raise ConfigError("scenario file must contain a JSON list of processes")
    return [Process.from_dict(item) for item in data]
