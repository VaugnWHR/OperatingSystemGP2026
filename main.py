"""Command-line entry point.

Examples:
    python main.py                                   # basic scenario, FCFS
    python main.py --scenario memory_pressure --memory 512
    python main.py --scheduler rr --quantum 2 --quiet
    python main.py --scenario-file my_scenario.json --log-csv run.csv
    python main.py --battery 40                      # enable the power model (bonus)

Memory examples:
    python main.py --scenario fragmentation --memory-map          # watch holes appear
    python main.py --scenario fragmentation --compact             # compaction fixes it
    python main.py --memory-strategy best --quiet                 # change placement strategy
    python main.py --scenario fragmentation --compare-memory      # every strategy side by side
"""
import argparse
import sys

from rcos.config import MEMORY_STRATEGIES, SystemConfig
from rcos.engine import build_simulator
from rcos.errors import SimulationError
from rcos.scenarios import SCENARIOS, get_scenario, load_scenario


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Resource-Constrained OS Simulator")
    p.add_argument("--scheduler", default="fcfs", choices=["fcfs", "rr", "priority"])
    p.add_argument("--scenario", default="basic", choices=sorted(SCENARIOS))
    p.add_argument("--scenario-file", help="JSON file of processes (overrides --scenario)")
    p.add_argument("--memory", type=int, default=512, help="total memory in KB")
    p.add_argument("--memory-strategy", default="first", choices=MEMORY_STRATEGIES,
                   help="hole placement strategy: first, best, worst or next fit")
    p.add_argument("--compact", action="store_true",
                   help="compact memory when external fragmentation blocks a request")
    p.add_argument("--memory-map", action="store_true",
                   help="log a map of memory after every allocate/free")
    p.add_argument("--compare-memory", action="store_true",
                   help="run the scenario once per placement strategy and print a comparison")
    p.add_argument("--quantum", type=int, default=3, help="Round Robin time quantum (ticks)")
    p.add_argument("--battery", type=float, default=None, help="battery capacity (enables power model)")
    p.add_argument("--aging", type=int, default=0, help="priority aging interval (0 = off)")
    p.add_argument("--quiet", action="store_true", help="hide the event log, show only the report")
    p.add_argument("--log-csv", help="write the event log to this CSV file")
    return p.parse_args(argv)


def run_once(args, **overrides):
    """Build, load and run one simulation.  `overrides` replace SystemConfig fields."""
    settings = dict(total_memory_kb=args.memory, memory_strategy=args.memory_strategy,
                    memory_compaction=args.compact, show_memory_map=args.memory_map,
                    time_quantum=args.quantum, scheduler=args.scheduler,
                    battery_capacity=args.battery, priority_aging_interval=args.aging,
                    log_to_console=not args.quiet)
    settings.update(overrides)
    sim = build_simulator(SystemConfig(**settings))
    sim.load_processes(load_scenario(args.scenario_file) if args.scenario_file
                       else get_scenario(args.scenario))
    return sim, sim.run()


def compare_memory(args) -> str:
    """Run the same workload under each placement strategy (compaction off, then
    first fit with compaction) and return a comparison table."""
    runs = [(strategy, False) for strategy in MEMORY_STRATEGIES] + [("first", True)]
    lines = [f"=== MEMORY STRATEGY COMPARISON [{args.scenario_file or args.scenario}, "
             f"{args.memory}KB, scheduler {args.scheduler}] ===",
             f"{'Strategy':<21}{'Done':>6}{'Time':>6}{'AvgMemWait':>12}{'AvgTAT':>8}"
             f"{'FragWaits':>11}{'PeakFrag':>10}{'Compactions':>13}"]
    for strategy, compaction in runs:
        sim, report = run_once(args, memory_strategy=strategy, memory_compaction=compaction,
                               show_memory_map=False, log_to_console=False)
        done = [r for r in report.per_process if r.status == "completed"]
        avg_mem_wait = sum(r.admission_wait for r in done) / len(done) if done else 0.0
        stats = sim.resources.memory.stats
        label = f"{strategy} fit" + (" + compact" if compaction else "")
        lines.append(f"{label:<21}{report.completed:>6}{report.total_time:>6}{avg_mem_wait:>12.2f}"
                     f"{report.avg_turnaround:>8.2f}{len(stats.fragmentation_pids):>11}"
                     f"{stats.peak_external_fragmentation:>9.1f}%{stats.compactions:>13}")
    lines += ["",
              "AvgMemWait = average ticks a completed process waited in the job queue for memory",
              "FragWaits  = processes that waited although enough memory was free in total",
              "PeakFrag   = highest share of free memory outside the largest hole"]
    return "\n".join(lines)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        if args.compare_memory:
            print(compare_memory(args))
            return 0
        sim, report = run_once(args)
    except NotImplementedError as exc:
        print(f"Not implemented yet: {exc}", file=sys.stderr)
        return 3
    except SimulationError as exc:
        print(f"Simulation error: {exc}", file=sys.stderr)
        return 2
    if args.log_csv:
        sim.log.to_csv(args.log_csv)
    print()
    print(report.format())
    memory_lines = sim.resources.memory.summary_lines()
    if memory_lines:
        print()
        print("--- Memory ---")
        print("\n".join(memory_lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
