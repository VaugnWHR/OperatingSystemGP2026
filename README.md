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
    python main.py --scenario fragmentation --memory-map   # watch memory holes form
    python main.py --scenario fragmentation --compact      # compaction fixes fragmentation
    python main.py --scenario placement --compare-memory   # first/best/worst/next fit side by side
    python main.py --check                          # verify the simulator's rules after every tick
    python -m unittest discover -v                  # tests

## Who owns what
| File | Owner | Status in skeleton |
|---|---|---|
| process.py, config.py, eventlog.py, interfaces.py, resources.py, engine.py, checks.py, main.py | Juvaugn Foster | done; `--check` invariant checker added |
| scheduler.py | Samuel Kelly | FCFS done; **RR + Priority = TODO** |
| memory.py | Juvaugn Foster | **done**: contiguous allocation, first/best/worst/next fit, coalescing, fragmentation stats, compaction |
| io_manager.py | Britansia Austin| FIFO device queues work; **extend** |
| metrics.py, scenarios.py, tests/, power.py | Member 5 | baseline works; **extend** + bonus |

## Rules for everyone
1. Time = integer ticks. Memory = KB. **Lower priority number = higher priority.**
2. Implement the abstract classes in `rcos/interfaces.py`; do not change their signatures
   without checking with Juvaugn.
3. Only the engine changes process states (via `Process.transition`). Never set `proc.state` directly.
4. Log with `log.emit(now, Category.X, message, pid)` - format is fixed (see eventlog.py).
5. Ordinary failures (no memory) return False; contract violations raise `ResourceError`.
6. Each module owner adds their own `tests/test_<module>.py`. Run all tests before every push.
7. Work on your own branch; open a pull request; Juvaugn reviews and merges.

## Tick order (see engine.py for the full version)
arrivals -> admission (memory) -> scheduler.on_tick -> dispatch/preempt -> CPU + I/O work
-> I/O completions -> CPU-burst end (I/O request or terminate).

## Process model
NEW -> READY -> RUNNING -> (WAITING <-> READY) -> TERMINATED. Bursts alternate CPU, I/O, CPU...

## Before every merge
Run `python -m unittest discover` and then each scenario with `--check`, e.g.
`python main.py --scenario io_heavy --check --quiet`. If a module breaks one of the
simulator's rules, `--check` stops at the first bad tick and names the rule and the
process (the rules are listed at the top of `rcos/checks.py`).
