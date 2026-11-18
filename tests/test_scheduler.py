"""CPU scheduler tests (OWNER: Member 2)."""
import unittest

from rcos.config import SystemConfig
from rcos.engine import build_simulator
from rcos.errors import ConfigError
from rcos.process import Process, cpu_burst
from rcos.scheduler import PriorityScheduler, RoundRobinScheduler


class RoundRobinSchedulerTests(unittest.TestCase):
    def test_add_and_select_use_fifo_order(self):
        scheduler = RoundRobinScheduler(2)
        p1 = Process(1, "p1", 0, 2, 10, [cpu_burst(4)])
        p2 = Process(2, "p2", 0, 1, 10, [cpu_burst(4)])
        scheduler.add(p1, 0)
        scheduler.add(p2, 0)

        self.assertEqual(scheduler.ready_pids(), [1, 2])
        self.assertIs(scheduler.select_next(1, None), p1)
        self.assertIs(scheduler.select_next(1, None), p2)

    def test_preempts_only_at_quantum_with_waiting_process(self):
        scheduler = RoundRobinScheduler(3)
        running = Process(1, "p1", 0, 1, 10, [cpu_burst(6)])
        waiting = Process(2, "p2", 0, 1, 10, [cpu_burst(6)])
        scheduler.add(waiting, 0)

        self.assertFalse(scheduler.should_preempt(running, 2, 2))
        self.assertTrue(scheduler.should_preempt(running, 3, 3))

    def test_quantum_must_be_positive(self):
        with self.assertRaises(ConfigError):
            RoundRobinScheduler(0)

    def test_rr_engine_run_completes_all_processes(self):
        sim = build_simulator(SystemConfig(scheduler="rr", time_quantum=2,
                                           log_to_console=False))
        sim.load_processes([
            Process(i, f"p{i}", 0, 1, 50, [cpu_burst(6)])
            for i in (1, 2, 3)
        ])
        report = sim.run()
        self.assertEqual(report.completed, 3)
        self.assertEqual(report.total_time, 18)
        self.assertGreater(report.context_switches, 2)


class PrioritySchedulerTests(unittest.TestCase):
    def test_lower_number_is_selected_first(self):
        scheduler = PriorityScheduler(preemptive=False)
        p1 = Process(1, "p1", 0, 4, 10, [cpu_burst(2)])
        p2 = Process(2, "p2", 0, 1, 10, [cpu_burst(2)])
        p3 = Process(3, "p3", 0, 3, 10, [cpu_burst(2)])
        for proc in (p1, p2, p3):
            scheduler.add(proc, 0)

        self.assertEqual(scheduler.ready_pids(), [2, 3, 1])
        self.assertIs(scheduler.select_next(0, None), p2)

    def test_equal_priority_uses_ready_time_then_sequence(self):
        scheduler = PriorityScheduler(preemptive=False)
        p1 = Process(1, "p1", 0, 2, 10, [cpu_burst(2)])
        p2 = Process(2, "p2", 1, 2, 10, [cpu_burst(2)])
        p3 = Process(3, "p3", 0, 2, 10, [cpu_burst(2)])
        scheduler.add(p1, 2)
        scheduler.add(p2, 3)
        scheduler.add(p3, 2)

        self.assertEqual(scheduler.ready_pids(), [1, 3, 2])

    def test_preemptive_priority_preempts_lower_priority_running_process(self):
        scheduler = PriorityScheduler(preemptive=True)
        running = Process(1, "p1", 0, 5, 10, [cpu_burst(4)])
        waiting = Process(2, "p2", 0, 1, 10, [cpu_burst(4)])
        scheduler.add(waiting, 1)

        self.assertTrue(scheduler.should_preempt(running, 1, 0))

    def test_non_preemptive_priority_never_preempts(self):
        scheduler = PriorityScheduler(preemptive=False)
        running = Process(1, "p1", 0, 5, 10, [cpu_burst(4)])
        waiting = Process(2, "p2", 0, 1, 10, [cpu_burst(4)])
        scheduler.add(waiting, 1)

        self.assertFalse(scheduler.should_preempt(running, 1, 0))

    def test_aging_prevents_low_priority_starvation(self):
        scheduler = PriorityScheduler(preemptive=False, aging_interval=2)
        low_priority = Process(1, "low", 0, 5, 10, [cpu_burst(2)])
        scheduler.add(low_priority, 0)

        scheduler.on_tick(2)
        self.assertEqual(scheduler.ready_pids(), [1])
        self.assertEqual(scheduler._effective_priority(low_priority), 4)

        scheduler.on_tick(4)
        self.assertEqual(scheduler._effective_priority(low_priority), 3)

    def test_priority_engine_run_completes_all_processes(self):
        sim = build_simulator(SystemConfig(scheduler="priority",
                                           priority_aging_interval=3,
                                           log_to_console=False))
        sim.load_processes([
            Process(1, "low", 0, 5, 50, [cpu_burst(4)]),
            Process(2, "high", 0, 1, 50, [cpu_burst(2)]),
            Process(3, "medium", 0, 3, 50, [cpu_burst(3)]),
        ])
        report = sim.run()
        self.assertEqual(report.completed, 3)


if __name__ == "__main__":
    unittest.main()
