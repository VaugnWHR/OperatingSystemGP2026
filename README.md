# RCOS - Resource-Constrained OS Simulator (CIT3002 Group 5)

A tick-driven simulator showing how an OS manages **processes, CPU scheduling, memory,
I/O and priorities** (and optionally **power**) on a resource-constrained IoT/edge-style
device. Workloads are *simulated* (lists of CPU/I-O bursts) - nothing real is executed.

Requires Python 3.8+, no third-party packages.

## Run
    python main.py                                  # basic scenario, FCFS
    python main.py --scheduler rr --quantum 2       # once Member 2 finishes RR
    python main.py --scenario memory_pressure --quiet
    python main.py --battery 40                     # power model (bonus)
    python -m unittest discover -v                  # tests

## Who owns what
| File | Owner | Status in skeleton |
|---|---|---|
| process.py, config.py, eventlog.py, interfaces.py, resources.py, engine.py, main.py | Juvaugn Foster | done (extend/harden) |
| scheduler.py | Samuel Kelly | FCFS done; **RR + Priority = TODO** |
| memory.py | Member 3 | simple pool works; **placement strategy + fragmentation = TODO** |
| io_manager.py | Britansia Austin| FIFO device queues work; **extend** |
| metrics.py, scenarios.py, tests/, power.py | Member 5 | baseline works; **extend** + bonus |

## Rules for everyone
1. Time = integer ticks. Memory = KB. **Lower priority number = higher priority.**
2. Implement the abstract classes in `rcos/interfaces.py`; do not change their signatures
   without asking Member 1.
3. Only the engine changes process states (via `Process.transition`). Never set `proc.state` directly.
4. Log with `log.emit(now, Category.X, message, pid)` - format is fixed (see eventlog.py).
5. Ordinary failures (no memory) return False; contract violations raise `ResourceError`.
6. Each module owner adds their own `tests/test_<module>.py`. Run all tests before every push.
7. Work on your own branch; open a pull request; Member 1 reviews and merges.

## Tick order (see engine.py for the full version)
arrivals -> admission (memory) -> scheduler.on_tick -> dispatch/preempt -> CPU + I/O work
-> I/O completions -> CPU-burst end (I/O request or terminate).

## Process model
NEW -> READY -> RUNNING -> (WAITING <-> READY) -> TERMINATED. Bursts alternate CPU, I/O, CPU...
