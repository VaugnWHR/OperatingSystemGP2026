# RCOS: Resource-Constrained OS Simulator (CIT3002, Group 5)

A tick-by-tick simulator of how an operating system manages processes, CPU scheduling,
memory, I/O devices, priorities and (optionally) battery power on a small IoT/edge-style
device. Workloads are simulated as lists of CPU and I/O bursts; nothing real is executed.

Requires Python 3.8 or newer. No extra packages.

## Running it

    python main.py                                        basic scenario with FCFS
    python main.py --scheduler rr --quantum 2             Round Robin
    python main.py --scheduler priority --aging 3         Priority with aging
    python main.py --compare-schedulers                   FCFS vs Round Robin vs Priority
    python main.py --scenario fragmentation --memory-map  watch memory holes form
    python main.py --scenario fragmentation --compact     compaction fixes fragmentation
    python main.py --scenario placement --compare-memory  first / best / worst / next fit
    python main.py --scenario io_heavy                    five processes queue for one device
    python main.py --battery 40                           battery model
    python main.py --check --quiet                        verify the simulator's rules every tick
    python -m unittest discover -v                        all tests

Scenarios: `basic`, `memory_pressure`, `io_heavy`, `fragmentation`, `placement`
(or your own JSON file with `--scenario-file`). Add `--quiet` to see only the report.

## Required features and where they are

| Feature (assignment brief) | Where |
|---|---|
| Process creation | `rcos/process.py` (5-state model, bursts), `rcos/scenarios.py` |
| Scheduling: FCFS, Round Robin, Priority | `rcos/scheduler.py` |
| Memory allocation | `rcos/memory.py` (first/best/worst/next fit, coalescing, compaction) |
| I/O requests | `rcos/io_manager.py` (one queue per device, runs alongside the CPU) |
| Resource allocation | `rcos/resources.py` (CPU, memory, I/O and power go through here) |
| Priority management | `rcos/scheduler.py` (preemptive priority with aging) |
| Metrics and logging | `rcos/metrics.py`, `rcos/eventlog.py` |

The tests reproduce the course's own worked answers: the CPU Scheduling tutorial (FCFS,
Round Robin with quantum 30, preemptive and non-preemptive priority) and the Lecture
Notes 06 memory placement example (first, next, best and worst fit).

## Who owns what

| Files | Owner | Status |
|---|---|---|
| engine.py, process.py, resources.py, interfaces.py, config.py, eventlog.py, checks.py, main.py | Juvaugn Foster (Member 1) | done |
| memory.py | Juvaugn Foster (Member 3 role) | done |
| scheduler.py | Samuel Kelly (Member 2) | done |
| io_manager.py | Britansia Austin (Member 4) | done |
| metrics.py, scenarios.py, power.py | Tijauni Pandohie (Member 5) | working baseline |

## How a tick works

Arrivals, then memory admission, then aging, then dispatch (with preemption), then one
tick of CPU and I/O work, then finished I/O and finished CPU bursts. The full list is at
the top of `rcos/engine.py`. Process states: NEW, READY, RUNNING, WAITING, TERMINATED.

## Team rules

1. Time is in whole ticks, memory in KB, and a lower priority number means higher priority.
2. Modules implement the classes in `rcos/interfaces.py`; check with Juvaugn before changing them.
3. Only the engine changes a process's state.
4. Work on your own branch and open a pull request. Before merging, run
   `python -m unittest discover` and each scenario with `--check`.
