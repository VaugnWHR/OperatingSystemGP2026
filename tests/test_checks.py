"""Tests for the --check invariant checker (OWNER: Juvaugn, Member 1).

Two kinds of test:
  * correct runs never trigger a false alarm (every scenario, strategy and path);
  * deliberately broken modules ARE caught, with the right rule named.
The broken modules are the kind of mistake that shows up during integration.

Run from the project root:   python -m unittest discover -v
"""
import io
import unittest
from collections import deque
from contextlib import redirect_stdout

import main
from rcos.config import MEMORY_STRATEGIES, SystemConfig
from rcos.engine import build_simulator
from rcos.errors import InvalidStateTransition, InvariantError
from rcos.interfaces import Scheduler
from rcos.memory import ContiguousMemoryManager
from rcos.process import Process, cpu_burst as cpu, io_burst as io_b
from rcos.scenarios import SCENARIOS, get_scenario
from tests.test_skeleton import _TestRR


def checked_sim(**config):
    return build_simulator(SystemConfig(log_to_console=False, check_invariants=True, **config))


def mixed_workload():
    return [Process(1, "a", 0, 2, 64, [cpu(3), io_b("FLASH", 2), cpu(2)]),
            Process(2, "b", 0, 1, 64, [cpu(2), io_b("FLASH", 3), cpu(1)]),
            Process(3, "c", 1, 3, 64, [cpu(4)])]


# ---------------------------------------------------------------- broken modules
class _ForgetfulScheduler(Scheduler):
    """Bug: select_next() returns the head but forgets to remove it."""
    name = "BROKEN-FORGETFUL"

    def __init__(self):
        self._q = deque()

    def add(self, proc, now): self._q.append(proc)
    def select_next(self, now, resources): return self._q[0] if self._q else None
    def ready_pids(self): return [p.pid for p in self._q]


class _LosingScheduler(Scheduler):
    """Bug: add() drops processes with an even pid."""
    name = "BROKEN-LOSING"

    def __init__(self):
        self._q = deque()

    def add(self, proc, now):
        if proc.pid % 2:
            self._q.append(proc)

    def select_next(self, now, resources): return self._q.popleft() if self._q else None
    def ready_pids(self): return [p.pid for p in self._q]


class _LeakyMemory(ContiguousMemoryManager):
    """Bug: free() reports success but never gives the memory back."""

    def free(self, pid, now):
        return self.block_of(pid).size


# ------------------------------------------------------------------------ tests
class NoFalseAlarmTests(unittest.TestCase):
    def test_every_scenario_and_memory_setting_passes(self):
        for name in SCENARIOS:
            for strategy in MEMORY_STRATEGIES:
                for compaction in (False, True):
                    with self.subTest(scenario=name, strategy=strategy, compaction=compaction):
                        sim = checked_sim(memory_strategy=strategy, memory_compaction=compaction)
                        sim.load_processes(get_scenario(name))
                        sim.run()
                        self.assertEqual(sim.invariant_checks, sim.clock)

    def test_preemption_path_passes(self):
        sim = checked_sim()
        sim.scheduler = _TestRR(2)
        sim.load_processes(mixed_workload())
        report = sim.run()
        self.assertEqual(report.completed, 3)
        self.assertGreater(sim.invariant_checks, 0)

    def test_battery_shutdown_passes(self):
        sim = checked_sim(battery_capacity=5)
        sim.load_processes([Process(1, "a", 0, 1, 10, [cpu(20)])])
        sim.run()                                   # aborts cleanly, no false alarm

    def test_check_is_off_by_default(self):
        sim = build_simulator(SystemConfig(log_to_console=False))
        sim.load_processes(get_scenario("basic"))
        sim.run()
        self.assertEqual(sim.invariant_checks, 0)


class CatchesBugsTests(unittest.TestCase):
    def assert_caught(self, sim, rule):
        sim.load_processes(mixed_workload())
        with self.assertRaises(InvariantError) as caught:
            sim.run()
        self.assertIn(rule, str(caught.exception))
        return str(caught.exception)

    def test_scheduler_that_does_not_remove_is_caught(self):
        sim = checked_sim()
        sim.scheduler = _ForgetfulScheduler()
        message = self.assert_caught(sim, "I1 location")
        self.assertIn("RUNNING but is in: ready queue, CPU", message)
        self.assertIn("after tick 0", message)      # caught on the very first tick

    def test_scheduler_that_loses_processes_is_caught(self):
        sim = checked_sim()
        sim.scheduler = _LosingScheduler()
        message = self.assert_caught(sim, "I1 location")
        self.assertIn("P02 is READY but is in: nowhere", message)

    def test_memory_leak_is_caught(self):
        sim = checked_sim()
        leaky = _LeakyMemory(512, log=sim.log)
        sim.resources.memory = leaky
        self.assert_caught(sim, "I4 memory totals")

    def test_without_check_the_same_bug_shows_up_later_and_misleads(self):
        sim = build_simulator(SystemConfig(log_to_console=False, max_ticks=50))
        sim.scheduler = _ForgetfulScheduler()
        sim.load_processes(mixed_workload())
        with self.assertRaises(InvalidStateTransition) as caught:
            sim.run()
        self.assertEqual(sim.clock, 3)              # 3 ticks late, and the message
        self.assertIn("WAITING -> RUNNING", str(caught.exception))   # blames a state change


class CommandLineTests(unittest.TestCase):
    def test_check_flag_prints_summary(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main.main(["--check", "--quiet"])
        self.assertEqual(code, 0)
        self.assertIn("all rules held after each of 30 ticks", output.getvalue())


if __name__ == "__main__":
    unittest.main()
