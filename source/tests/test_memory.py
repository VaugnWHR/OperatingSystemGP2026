"""Tests for memory allocation (Member 3 role: Juvaugn), including the Lecture Notes 06 example."""
import random
import unittest

from rcos.config import MEMORY_STRATEGIES, SystemConfig
from rcos.engine import build_simulator
from rcos.errors import ConfigError, ResourceError
from rcos.memory import ContiguousMemoryManager, Region
from rcos.scenarios import get_scenario


def make_memory(total=100, strategy="first", compaction=False):
    return ContiguousMemoryManager(total, strategy=strategy, compaction=compaction)


def two_holes(strategy):
    """100KB memory left as: [0-9 P1] [10-49 free 40] [50-59 P3] [60-89 free 30] [90-99 P5]."""
    mem = make_memory(100, strategy)
    for pid, size in [(1, 10), (2, 40), (3, 10), (4, 30), (5, 10)]:
        assert mem.allocate(pid, size, 0)
    mem.free(2, 1)
    mem.free(4, 1)
    return mem


class AllocateAndSplitTests(unittest.TestCase):
    def test_allocation_splits_the_hole(self):
        mem = make_memory(100)
        self.assertTrue(mem.allocate(1, 30, 0))
        self.assertEqual(mem.block_of(1), Region(0, 30))
        self.assertEqual(mem.holes, (Region(30, 70),))
        self.assertEqual((mem.used_kb, mem.free_kb), (30, 70))

    def test_exact_fit_removes_the_hole(self):
        mem = make_memory(100)
        self.assertTrue(mem.allocate(1, 100, 0))
        self.assertEqual(mem.holes, ())
        self.assertEqual(mem.largest_free_block_kb, 0)

    def test_failure_returns_false_and_changes_nothing(self):
        mem = make_memory(100)
        mem.allocate(1, 80, 0)
        self.assertFalse(mem.allocate(2, 30, 1))
        self.assertIsNone(mem.block_of(2))
        self.assertEqual(mem.used_kb, 80)
        self.assertIn(2, mem.stats.delayed_pids)


class PlacementStrategyTests(unittest.TestCase):
    """Request 25KB with holes of 40KB at 10 and 30KB at 60 (see two_holes)."""

    def test_first_fit_takes_the_first_hole_that_fits(self):
        mem = two_holes("first")
        mem.allocate(6, 25, 2)
        self.assertEqual(mem.block_of(6).start, 10)

    def test_best_fit_takes_the_smallest_hole_that_fits(self):
        mem = two_holes("best")
        mem.allocate(6, 25, 2)
        self.assertEqual(mem.block_of(6).start, 60)

    def test_worst_fit_takes_the_largest_hole(self):
        mem = two_holes("worst")
        mem.allocate(6, 25, 2)
        self.assertEqual(mem.block_of(6).start, 10)

    def test_next_fit_continues_from_the_last_allocation(self):
        mem = make_memory(100, "next")
        mem.allocate(1, 10, 0)                 # [0-9]
        mem.allocate(2, 10, 0)                 # [10-19]
        mem.free(1, 1)                         # hole [0-9] behind the pointer (now 20)
        mem.allocate(3, 5, 2)
        self.assertEqual(mem.block_of(3).start, 20)       # first fit would choose 0

    def test_next_fit_wraps_around(self):
        mem = make_memory(100, "next")
        mem.allocate(1, 10, 0)
        mem.allocate(2, 90, 0)                 # memory full, pointer at 100
        mem.free(1, 1)
        mem.allocate(3, 10, 2)
        self.assertEqual(mem.block_of(3).start, 0)


class CourseExampleTests(unittest.TestCase):
    """Lecture Notes 06 dynamic partitioning example: blocks of 100/500/200/600/300KB
    receive 212/417/112/83/426KB. Checks where each lands and what is left, per strategy."""
    BLOCKS = (100, 500, 200, 600, 300)
    REQUESTS = (212, 417, 112, 83, 426)

    def run_lecture_example(self, strategy):
        # Build the five free blocks with a 10KB allocated separator after each one, so
        # they stay separate holes (the separators play the part of other processes).
        mem = make_memory(sum(self.BLOCKS) + 10 * len(self.BLOCKS), strategy)
        block_start, address, fillers = {}, 0, []
        for size in self.BLOCKS:
            block_start[address] = size
            mem.allocate(1000 + address, size, 0)
            fillers.append(1000 + address)
            mem.allocate(2000 + address, 10, 0)
            address += size + 10
        for pid in fillers:
            mem.free(pid, 0)

        placed = []
        for pid, size in enumerate(self.REQUESTS, start=1):
            if mem.allocate(pid, size, 1):
                start = mem.block_of(pid).start
                placed.append(block_start[max(s for s in block_start if s <= start)])
            else:
                placed.append("blocked")
        leftovers = [hole.size for hole in mem.holes]
        return placed, leftovers, mem

    def test_first_fit_matches_lecture(self):
        placed, leftovers, mem = self.run_lecture_example("first")
        self.assertEqual(placed, [500, 600, 500, 100, "blocked"])
        self.assertEqual(leftovers, [17, 176, 200, 183, 300])      # 876KB, not contiguous
        self.assertIn(5, mem.stats.fragmentation_pids)             # external fragmentation

    def test_next_fit_matches_lecture(self):
        placed, leftovers, mem = self.run_lecture_example("next")
        self.assertEqual(placed, [500, 600, 600, 300, "blocked"])
        self.assertEqual(leftovers, [100, 288, 200, 71, 217])
        self.assertIn(5, mem.stats.fragmentation_pids)

    def test_best_fit_matches_lecture(self):
        placed, leftovers, _ = self.run_lecture_example("best")
        self.assertEqual(placed, [300, 500, 200, 500, 600])
        self.assertEqual(leftovers, [100, 88, 174, 88])            # the 500KB block is used up

    def test_worst_fit_matches_lecture(self):
        placed, leftovers, mem = self.run_lecture_example("worst")
        self.assertEqual(placed, [600, 500, 600, 300, "blocked"])
        self.assertEqual(leftovers, [100, 83, 200, 276, 217])
        self.assertIn(5, mem.stats.fragmentation_pids)


class FreeAndCoalesceTests(unittest.TestCase):
    def test_free_merges_with_both_neighbours(self):
        mem = make_memory(100)
        for pid in (1, 2, 3):
            mem.allocate(pid, 30, 0)           # [0-29][30-59][60-89] + hole [90-99]
        mem.free(1, 1)
        mem.free(3, 1)                         # merges with [90-99]
        self.assertEqual(mem.holes, (Region(0, 30), Region(60, 40)))
        mem.free(2, 2)                         # joins everything into one hole
        self.assertEqual(mem.holes, (Region(0, 100),))
        mem.check()

    def test_free_returns_the_size(self):
        mem = make_memory(100)
        mem.allocate(1, 42, 0)
        self.assertEqual(mem.free(1, 1), 42)


class FragmentationAndCompactionTests(unittest.TestCase):
    def test_external_fragmentation_is_detected(self):
        mem = two_holes("first")               # 70KB free, largest hole 40KB
        self.assertEqual(mem.free_kb, 70)
        self.assertFalse(mem.allocate(6, 50, 2))
        self.assertIn(6, mem.stats.fragmentation_pids)
        self.assertAlmostEqual(mem.external_fragmentation, 100 * (1 - 40 / 70))

    def test_shortage_is_not_counted_as_fragmentation(self):
        mem = two_holes("first")
        self.assertFalse(mem.allocate(6, 80, 2))           # more than the 70KB free
        self.assertNotIn(6, mem.stats.fragmentation_pids)

    def test_compaction_makes_one_hole_and_satisfies_the_request(self):
        mem = make_memory(100, compaction=True)
        for pid, size in [(1, 10), (2, 40), (3, 10), (4, 30), (5, 10)]:
            mem.allocate(pid, size, 0)
        mem.free(2, 1)
        mem.free(4, 1)
        self.assertTrue(mem.allocate(6, 50, 2))
        self.assertEqual(mem.stats.compactions, 1)
        self.assertEqual(mem.stats.kb_moved, 20)          # P3 and P5 slid down
        self.assertEqual(mem.block_of(6), Region(30, 50))
        self.assertEqual(mem.holes, (Region(80, 20),))
        mem.check()


class ContractTests(unittest.TestCase):
    def test_contract_violations_raise(self):
        mem = make_memory(100)
        with self.assertRaises(ResourceError):
            mem.allocate(1, 0, 0)
        mem.allocate(1, 10, 0)
        with self.assertRaises(ResourceError):
            mem.allocate(1, 10, 0)             # same pid twice
        with self.assertRaises(ResourceError):
            mem.free(99, 0)                    # never allocated

    def test_bad_strategy_is_rejected(self):
        with self.assertRaises(ConfigError):
            make_memory(100, "random")
        with self.assertRaises(ConfigError):
            SystemConfig(memory_strategy="random")

    def test_memory_map(self):
        mem = make_memory(100)
        mem.allocate(1, 30, 0)
        self.assertEqual(mem.memory_map(), "[0-29 P01] [30-99 free 70KB]")


class RandomStressTests(unittest.TestCase):
    def test_random_allocate_and_free_keeps_memory_consistent(self):
        for strategy in MEMORY_STRATEGIES:
            for compaction in (False, True):
                with self.subTest(strategy=strategy, compaction=compaction):
                    rng = random.Random(42)
                    mem = make_memory(1000, strategy, compaction)
                    held = set()
                    for step in range(2000):
                        if held and rng.random() < 0.45:
                            pid = rng.choice(sorted(held))
                            mem.free(pid, step)
                            held.discard(pid)
                        else:
                            pid = step
                            if mem.allocate(pid, rng.randint(1, 120), step):
                                held.add(pid)
                        mem.check()
                        self.assertEqual(mem.used_kb + mem.free_kb, 1000)
                    for pid in sorted(held):
                        mem.free(pid, 9999)
                    self.assertEqual(mem.holes, (Region(0, 1000),))


class EngineMemoryTests(unittest.TestCase):
    def run_scenario(self, name, **config):
        sim = build_simulator(SystemConfig(log_to_console=False, **config))
        sim.load_processes(get_scenario(name))
        return sim, sim.run()

    def test_fragmentation_scenario_without_compaction(self):
        sim, report = self.run_scenario("fragmentation")
        p5 = next(r for r in report.per_process if r.pid == 5)
        self.assertEqual(p5.admission_wait, 21)
        self.assertTrue(any("external fragmentation" in e.message for e in sim.log.events))
        self.assertEqual(sim.resources.memory.used_kb, 0)

    def test_compaction_shortens_the_wait(self):
        sim, report = self.run_scenario("fragmentation", memory_compaction=True)
        p5 = next(r for r in report.per_process if r.pid == 5)
        self.assertEqual(p5.admission_wait, 5)
        self.assertEqual(sim.resources.memory.stats.compactions, 1)

    def test_best_fit_beats_first_fit_in_placement_scenario(self):
        _, first = self.run_scenario("placement", memory_strategy="first")
        _, best = self.run_scenario("placement", memory_strategy="best")
        p6_first = next(r for r in first.per_process if r.pid == 6)
        p6_best = next(r for r in best.per_process if r.pid == 6)
        self.assertGreater(p6_first.admission_wait, 0)
        self.assertEqual(p6_best.admission_wait, 0)
        self.assertLess(best.avg_turnaround, first.avg_turnaround)

    def test_every_strategy_runs_every_scenario_without_leaks(self):
        from rcos.scenarios import SCENARIOS
        for strategy in MEMORY_STRATEGIES:
            for name in SCENARIOS:
                with self.subTest(strategy=strategy, scenario=name):
                    sim, _ = self.run_scenario(name, memory_strategy=strategy)
                    self.assertEqual(sim.resources.memory.used_kb, 0)
                    sim.resources.memory.check()


if __name__ == "__main__":
    unittest.main()
