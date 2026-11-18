"""Invariant checker for --check (OWNER: Juvaugn, Member 1).

An INVARIANT is a rule that must be true at the end of every tick, no matter
which scheduler, memory strategy or scenario is running.  If one is broken, the
simulator is in a state a real OS could never be in, so there is a bug somewhere
(usually where two modules meet).  With --check on, the engine calls
check_invariants() after every tick and stops with an InvariantError that names
the tick, the rule and the process involved.

THE RULES
  I1 Location  Every process is in exactly the place its state says:
                 NEW        -> not arrived yet, or in the job queue (waiting for memory)
                 READY      -> in the scheduler's ready queue, exactly once
                 RUNNING    -> on the CPU
                 WAITING    -> held by the I/O manager (queued or being served)
                 TERMINATED -> nowhere
  I2 CPU       At most one process is RUNNING, and the resource manager's CPU owner
               is that process (or nobody when the CPU is idle).
  I3 Memory    Exactly the READY, RUNNING and WAITING processes hold memory.
     owners    NEW processes have not been admitted; TERMINATED ones have freed it.
  I4 Memory    Memory in use equals the sum of the holders' sizes and fits within
     totals    total memory; the memory manager's own check() passes if it has one.
  I5 Bursts    A READY or RUNNING process is on a CPU burst with time left; a
               WAITING process is on an I/O burst with time left; a completed
               process has used up every burst.
  I6 Time      Every arrived process has each tick since arrival booked to exactly
               one state (no ticks lost or counted twice).
  I7 Power     Battery energy, if modelled, is never negative.
"""
from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, List

from .errors import InvariantError
from .process import BurstType, ProcessState

if TYPE_CHECKING:                       # only for type hints; avoids a circular import
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

    # ---- I1 location -----------------------------------------------------
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

    # ---- I2 CPU ----------------------------------------------------------
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

    # ---- I3 memory owners ------------------------------------------------
    should_hold = {pid for pid, s in states.items()
                   if s in (ProcessState.READY, ProcessState.RUNNING, ProcessState.WAITING)}
    holders = sim.resources.memory_holders
    for pid in sorted(should_hold - holders):
        report(f"I3 memory owners: P{pid:02d} is {states[pid].value} but holds no memory")
    for pid in sorted(holders - should_hold):
        state = states[pid].value if pid in states else "unknown"
        report(f"I3 memory owners: P{pid:02d} holds memory but is {state}")

    # ---- I4 memory totals ------------------------------------------------
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

    # ---- I5 bursts -------------------------------------------------------
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

    # ---- I6 time ---------------------------------------------------------
    for pid, proc in sim.processes.items():
        if proc.arrival_time > now:
            continue                                        # has not arrived yet
        if proc.state is ProcessState.TERMINATED:
            booked, should_be = sum(proc.time_in_state.values()), proc.finish_time - proc.arrival_time
        else:
            booked, should_be = proc.time_accounted(now), now - proc.arrival_time
        if booked != should_be:
            report(f"I6 time: P{pid:02d} has {booked} ticks booked to states, expected {should_be}")

    # ---- I7 power --------------------------------------------------------
    battery = sim.resources.power.remaining
    if battery is not None and battery < 0:
        report(f"I7 power: battery is negative ({battery})")

    if problems:
        shown = problems[:MAX_REPORTED]
        more = len(problems) - len(shown)
        lines = "\n  ".join(shown) + (f"\n  ... and {more} more" if more else "")
        raise InvariantError(f"invariant check failed after tick {now - 1} (clock {now}):\n  {lines}")
