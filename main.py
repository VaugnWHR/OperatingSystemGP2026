"""Command-line entry point.

Examples:
    python main.py                                   # basic scenario, FCFS
    python main.py --scenario memory_pressure --memory 512
    python main.py --scheduler rr --quantum 2 --quiet
    python main.py --scenario-file my_scenario.json --log-csv run.csv
    python main.py --battery 40                      # enable the power model (bonus)
"""
import argparse
import sys

from rcos.config import SystemConfig
from rcos.engine import build_simulator
from rcos.errors import SimulationError
from rcos.scenarios import SCENARIOS, get_scenario, load_scenario


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Resource-Constrained OS Simulator")
    p.add_argument("--scheduler", default="fcfs", choices=["fcfs", "rr", "priority"])
    p.add_argument("--scenario", default="basic", choices=sorted(SCENARIOS))
    p.add_argument("--scenario-file", help="JSON file of processes (overrides --scenario)")
    p.add_argument("--memory", type=int, default=512, help="total memory in KB")
    p.add_argument("--quantum", type=int, default=3, help="Round Robin time quantum (ticks)")
    p.add_argument("--battery", type=float, default=None, help="battery capacity (enables power model)")
    p.add_argument("--aging", type=int, default=0, help="priority aging interval (0 = off)")
    p.add_argument("--quiet", action="store_true", help="hide the event log, show only the report")
    p.add_argument("--log-csv", help="write the event log to this CSV file")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        config = SystemConfig(total_memory_kb=args.memory, time_quantum=args.quantum,
                              scheduler=args.scheduler, battery_capacity=args.battery,
                              priority_aging_interval=args.aging, log_to_console=not args.quiet)
        sim = build_simulator(config)
        sim.load_processes(load_scenario(args.scenario_file) if args.scenario_file
                           else get_scenario(args.scenario))
        report = sim.run()
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
