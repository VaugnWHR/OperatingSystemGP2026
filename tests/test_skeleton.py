"""Skeleton smoke tests (OWNER: Member 5 extends; Member 1 wrote the first set).

Run from the project root:   python -m unittest discover -v
Each module owner should add their own test file (test_scheduler.py, ...).
"""
import json
import os
import re
import tempfile
import unittest
from collections import deque

from rcos.config import SystemConfig
from rcos.engine import build_simulator
from rcos.errors import ConfigError, InvalidStateTransition, ResourceError
from rcos.interfaces import Scheduler
from rcos.process import Process, ProcessState, cpu_burst as cpu, io_burst as io
from rcos.scenarios import SCENARIOS, get_scenario, load_scenario


class _TestRR(Scheduler):
    """Tiny test double so the engine's PREEMPTION path is tested before Member 2 finishes RR."""
    name = "TEST-RR"

    def __init__(self, quantum):
        self.quantum, self._q = quantum, deque()

    def add(self, proc, now): self._q.append(proc)
    def select_next(self, now, resources): return self._q.popleft() if self._q else None
    def should_preempt(self, running, now, quantum_used):
        return quantum_used >= self.quantum and len(self._q) > 0
    def ready_pids(self): return [p.pid for p in self._q]


def make_sim(**overrides):
    return build_simulator(SystemConfig(log_to_console=False, **overrides))


class ProcessModelTests(unittest.TestCase):
    def test_legal_lifecycle(self):
        p = Process(1, "a", 0, 1, 10, [cpu(1)])
        for state, t in [(ProcessState.READY, 0), (ProcessState.RUNNING, 1), (ProcessState.TERMINATED, 2)]:
            p.transition(state, t)
        self.assertEqual(p.time_in_state[ProcessState.READY], 1)

    def test_illegal_transition_rejected(self):
        p = Process(1, "a", 0, 1, 10, [cpu(1)])
        with self.assertRaises(InvalidStateTransition):
            p.transition(ProcessState.RUNNING, 0)          # NEW -> RUNNING not allowed

    def test_bursts_must_alternate_and_start_with_cpu(self):
        with self.assertRaises(ConfigError):
            Process(1, "a", 0, 1, 10, [io("FLASH", 2), cpu(1)])
        with self.assertRaises(ConfigError):
            Process(1, "a", 0, 1, 10, [cpu(1), cpu(1)])

    def test_bad_values_rejected(self):
        with self.assertRaises(ConfigError):
            Process(1, "a", 0, 1, 0, [cpu(1)])             # zero memory
        with self.assertRaises(ConfigError):
            cpu(0)


class EngineTests(unittest.TestCase):
    def test_all_scenarios_complete_with_fcfs(self):
        for name in SCENARIOS:
            with self.subTest(scenario=name):
                sim = make_sim()
                sim.load_processes(get_scenario(name))
                sim.run()
                self.assertTrue(all(p.state is ProcessState.TERMINATED for p in sim.processes.values()))
                self.assertEqual(sim.resources.memory.used_kb, 0)   # no memory leaks

    def test_time_accounting_invariant(self):
        sim = make_sim()
        sim.load_processes(get_scenario("basic"))
        sim.run()
        for p in sim.processes.values():
            self.assertEqual(p.finish_time - p.arrival_time, sum(p.time_in_state.values()))
            self.assertEqual(p.time_in_state[ProcessState.RUNNING], p.total_cpu_demand)

    def test_waiting_time_matches_course_formula(self):
        sim = make_sim()
        sim.load_processes(get_scenario("basic"))
        report = sim.run()
        for r in report.per_process:
            self.assertEqual(r.waiting, r.turnaround - r.cpu_time)   # WT = TAT - burst
            self.assertLessEqual(r.ready_wait, r.waiting)

    def test_fcfs_reproduces_course_tutorial_table(self):
        """CPU Scheduling tutorial (P1-P5): published FCFS averages TT=110, WT=62, RT=62."""
        data = [(1, 0, 50), (2, 20, 20), (3, 40, 100), (4, 60, 40), (5, 70, 30)]
        sim = make_sim()
        sim.load_processes([Process(pid, f"P{pid}", arr, 3, 10, [cpu(burst)]) for pid, arr, burst in data])
        report = sim.run()
        self.assertEqual((report.avg_turnaround, report.avg_waiting, report.avg_response), (110.0, 62.0, 62.0))

    def test_memory_contention_delays_admission(self):
        sim = make_sim()
        sim.load_processes(get_scenario("basic"))
        report = sim.run()
        p4 = next(r for r in report.per_process if r.pid == 4)
        self.assertGreater(p4.admission_wait, 0)

    def test_oversized_process_is_rejected_not_crashed(self):
        sim = make_sim()
        sim.load_processes(get_scenario("memory_pressure"))
        report = sim.run()
        huge = next(r for r in report.per_process if r.pid == 3)
        self.assertTrue(huge.status.startswith("rejected"))
        self.assertEqual(report.completed, 3)

    def test_preemption_path_with_test_scheduler(self):
        sim = make_sim()
        sim.scheduler = _TestRR(2)
        procs = [Process(i, f"p{i}", 0, 1, 50, [cpu(6)]) for i in (1, 2, 3)]
        sim.load_processes(procs)
        report = sim.run()
        self.assertEqual(report.total_time, 18)            # 3 x 6 ticks, CPU never idle
        self.assertGreater(report.context_switches, 2)
        self.assertEqual(report.completed, 3)

    def test_duplicate_pid_and_unknown_device(self):
        sim = make_sim()
        with self.assertRaises(ConfigError):
            sim.load_processes([Process(1, "a", 0, 1, 10, [cpu(1)]), Process(1, "b", 0, 1, 10, [cpu(1)])])
        sim = make_sim()
        with self.assertRaises(ConfigError):
            sim.load_processes([Process(1, "a", 0, 1, 10, [cpu(1), io("GPU", 1)])])

    def test_cpu_cannot_be_double_assigned(self):
        sim = make_sim()
        a, b = Process(1, "a", 0, 1, 10, [cpu(1)]), Process(2, "b", 0, 1, 10, [cpu(1)])
        sim.resources.assign_cpu(a)
        with self.assertRaises(ResourceError):
            sim.resources.assign_cpu(b)

    def test_battery_depletion_stops_system(self):
        sim = make_sim(battery_capacity=5)
        sim.load_processes([Process(1, "a", 0, 1, 10, [cpu(20)], power_cost_per_tick=1.0)])
        report = sim.run()
        self.assertEqual(report.completed, 0)
        self.assertIn("power exhausted", report.per_process[0].status)

    def test_log_format(self):
        sim = make_sim()
        sim.load_processes(get_scenario("basic"))
        sim.run()
        pattern = re.compile(r"^\[t=\d{4}\] \[[A-Z ]{6}\] \[(P\d{2}|---)\] .+")
        for event in sim.log.events:
            self.assertRegex(event.format(), pattern)

    def test_json_scenario_loader(self):
        data = [{"pid": 1, "name": "x", "arrival": 0, "priority": 1, "memory_kb": 64,
                 "bursts": [{"type": "CPU", "time": 2}, {"type": "IO", "device": "FLASH", "time": 1}]}]
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(data, handle)
        try:
            procs = load_scenario(handle.name)
            self.assertEqual(procs[0].name, "x")
            with self.assertRaises(ConfigError):
                load_scenario(handle.name + ".missing")
        finally:
            os.remove(handle.name)


if __name__ == "__main__":
    unittest.main()
