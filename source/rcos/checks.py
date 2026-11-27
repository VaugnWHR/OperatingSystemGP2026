"""--check: rules that must hold after every tick (Member 1: Juvaugn).

If one breaks, two modules disagree (a bug), so the run stops and names the tick,
the rule and the process.
  I1 Location  each process is exactly where its state says (job queue, ready queue,
               CPU, I/O device, or nowhere once TERMINATED)
  I2 CPU       at most one RUNNING process, matching the CPU owner
  I3 Memory    only READY, RUNNING and WAITING processes hold memory
  I4 Memory    memory in use matches its holders and fits in total memory
  I5 Bursts    READY/RUNNING have CPU work left, WAITING has I/O work left
  I6 Time      every tick since arrival is booked to exactly one state
  I7 Power     the battery is never negative
"""
from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, List

from .errors import InvariantError
from .process import BurstType, ProcessState

if TYPE_CHECKING:                       # type hints only (avoids a circular import)
    from .engine import Simulator

MAX_REPORTED = 10                       # violations listed in one error message

EXPECTED_PLACES = {
    ProcessState.NEW: {"not yet arrived", "job queue"},
    ProcessState.READY: {"ready queue"},
    ProcessState.RUNNING: {"CPU"},
    ProcessState.WAITING: {"I/O manager"},
}


def check_invariants(sim: "Simulator") -> None:
    """Raise InvariantError listing every rule broken at the current clock."""
    # ---- Gather: where every process currently is ----
    now = sim.clock
    problems: List[str] = []
    report = problems.append

    states = {pid: proc.state for pid, proc in sim.processes.items()}
    incoming = {p.pid for p in sim._incoming}
    job_queue = {p.pid for p in sim._job_queue}
    ready_list = list(sim.scheduler.ready_pids())
    ready = Counter(ready_list)
    running = sim._running
    io_held = sim.resources.io.held_pids()
    io_count = Counter(io_held) if io_held is not None else None

    # ---- I1 Location: each process in exactly one place ----
    for pid, count in ready.items():
        if pid not in sim.processes:
            report(f"I1 location: unknown pid {pid} is in the ready queue")
        elif count > 1:
            report(f"I1 location: P{pid:02d} is in the ready queue {count} times")
    if io_count is not None:
        for pid, count in io_count.items():
            if pid not in sim.processes:
                report(f"I1 location: unknown pid {pid} is held by the I/O manager")
            elif count > 1:
                report(f"I1 location: P{pid:02d} is held by the I/O manager {count} times")

    for pid, state in states.items():
        places = []
        if pid in incoming:
            places.append("not yet arrived")
        if pid in job_queue:
            places.append("job queue")
        if ready[pid]:
            places.append("ready queue")
        if running is not None and running.pid == pid:
            places.append("CPU")
        if io_count is not None and io_count[pid]:
            places.append("I/O manager")

        if state is ProcessState.TERMINATED or (state is ProcessState.WAITING and io_count is None):
            ok = not places             # terminated: nowhere; WAITING but I/O can't be listed: skip
        else:
            ok = len(places) == 1 and places[0] in EXPECTED_PLACES[state]
        if not ok:
            where = ", ".join(places) if places else "nowhere"
            report(f"I1 location: P{pid:02d} is {state.value} but is in: {where}")

    # ---- I2 CPU: one running process, matching the CPU owner ----
    running_pids = [pid for pid, s in states.items() if s is ProcessState.RUNNING]
    if len(running_pids) > 1:
        report(f"I2 CPU: {len(running_pids)} processes are RUNNING: "
               + ", ".join(f"P{pid:02d}" for pid in running_pids))
    owner = sim.resources.cpu_owner
    expected_owner = running.pid if running is not None else None
    if owner != expected_owner:
        report(f"I2 CPU: CPU owner is {owner} but the running process is {expected_owner}")
    if running is not None and running.state is not ProcessState.RUNNING:
        report(f"I2 CPU: P{running.pid:02d} is on the CPU but its state is {running.state.value}")

    # ---- I3 Memory owners: admitted, unfinished processes only ----
    should_hold = {pid for pid, s in states.items()
                   if s in (ProcessState.READY, ProcessState.RUNNING, ProcessState.WAITING)}
    holders = sim.resources.memory_holders
    for pid in sorted(should_hold - holders):
        report(f"I3 memory owners: P{pid:02d} is {states[pid].value} but holds no memory")
    for pid in sorted(holders - should_hold):
        state = states[pid].value if pid in states else "unknown"
        report(f"I3 memory owners: P{pid:02d} holds memory but is {state}")

    # ---- I4 Memory totals: usage adds up and the free list is sound ----
    memory = sim.resources.memory
    expected_used = sum(sim.processes[pid].memory_kb for pid in holders if pid in sim.processes)
    if memory.used_kb != expected_used:
        report(f"I4 memory totals: {memory.used_kb}KB in use, but the holders asked for "
               f"{expected_used}KB")
    if not 0 <= memory.used_kb <= memory.total_kb:
        report(f"I4 memory totals: {memory.used_kb}KB in use out of {memory.total_kb}KB")
    if memory.largest_free_block_kb > memory.free_kb:
        report(f"I4 memory totals: largest hole {memory.largest_free_block_kb}KB is bigger "
               f"than all free memory ({memory.free_kb}KB)")
    own_check = getattr(memory, "check", None)
    if callable(own_check):
        try:
            own_check()
        except Exception as exc:                # report it as a rule break, not a crash
            report(f"I4 memory totals: memory manager check failed: {exc}")

    # ---- I5 Bursts: each state has the right kind of work left ----
    for pid, proc in sim.processes.items():
        burst = proc.current_burst
        if proc.state in (ProcessState.READY, ProcessState.RUNNING):
            if burst is None or burst.kind is not BurstType.CPU or burst.remaining <= 0:
                report(f"I5 bursts: P{pid:02d} is {proc.state.value} without CPU work left")
        elif proc.state is ProcessState.WAITING:
            if burst is None or burst.kind is not BurstType.IO or burst.remaining <= 0:
                report(f"I5 bursts: P{pid:02d} is WAITING without I/O work left")
        elif proc.state is ProcessState.TERMINATED and proc.exit_reason == "completed":
            if proc.burst_index != len(proc.bursts):
                report(f"I5 bursts: P{pid:02d} completed with bursts left over")

    # ---- I6 Time: no tick lost or counted twice ----
    for pid, proc in sim.processes.items():
        if proc.arrival_time > now:
            continue                                        # has not arrived yet
        if proc.state is ProcessState.TERMINATED:
            booked, should_be = sum(proc.time_in_state.values()), proc.finish_time - proc.arrival_time
        else:
            booked, should_be = proc.time_accounted(now), now - proc.arrival_time
        if booked != should_be:
            report(f"I6 time: P{pid:02d} has {booked} ticks booked to states, expected {should_be}")

    # ---- I7 Power: battery never negative ----
    battery = sim.resources.power.remaining
    if battery is not None and battery < 0:
        report(f"I7 power: battery is negative ({battery})")

    # ---- Report: one error listing every broken rule ----
    if problems:
        shown = problems[:MAX_REPORTED]
        more = len(problems) - len(shown)
        lines = "\n  ".join(shown) + (f"\n  ... and {more} more" if more else "")
        raise InvariantError(f"invariant check failed after tick {now - 1} (clock {now}):\n  {lines}")
