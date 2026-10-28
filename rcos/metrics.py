"""Performance metrics and reporting (OWNER: Member 5).

A working baseline is provided so the demo produces output today.  Member 5
extends it: comparison tables across schedulers, CSV export, charts, extra
metrics (memory fragmentation, I/O queue length over time, energy used).

DEFINITIONS (these match the course notes - CPU Scheduling / Lecture Notes 03-4):
  Turnaround time = finish_time - arrival_time
  Waiting time    = turnaround time - total CPU burst time   (course formula)
  Ready-queue wait = ticks spent in READY only (extra metric: waiting time also
                    includes time blocked on I/O and time waiting for memory)
  Response time   = first_run_time - arrival_time
  Throughput      = completed processes / total simulated ticks
  CPU utilisation = ticks the CPU ran a process / total ticks
  Memory util.    = average (used KB / total KB) sampled every tick
  Device util.    = ticks the device was serving / total ticks
Averages are taken over COMPLETED processes only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

from .interfaces import ResourceSnapshot
from .process import Process, ProcessState


@dataclass(frozen=True)
class ProcessMetrics:
    pid: int
    name: str
    priority: int
    arrival: int
    first_run: Optional[int]
    finish: Optional[int]
    cpu_time: int
    admission_wait: int      # ticks in NEW (waiting for memory)
    waiting: Optional[int]   # course definition: turnaround - CPU burst time
    ready_wait: int          # ticks in READY (ready-queue time only)
    io_wait: int             # ticks in WAITING (I/O queue + service)
    turnaround: Optional[int]
    response: Optional[int]
    status: str


@dataclass
class MetricsReport:
    label: str
    total_time: int
    per_process: List[ProcessMetrics]
    completed: int
    not_completed: int
    avg_waiting: float
    avg_ready_wait: float
    avg_turnaround: float
    avg_response: float
    throughput: float
    cpu_utilization: float            # percent
    avg_memory_utilization: float     # percent
    peak_memory_utilization: float    # percent
    io_utilization: Dict[str, float]  # percent per device
    context_switches: int
    battery_remaining: Optional[float]
    gantt: List[Tuple[int, int, Optional[int]]] = field(default_factory=list)

    def format(self) -> str:
        def n(v): return "-" if v is None else str(v)
        lines = [f"=== SIMULATION REPORT [{self.label}] ===",
                 f"Total time: {self.total_time} ticks | completed {self.completed}/"
                 f"{self.completed + self.not_completed}",
                 "",
                 f"{'PID':<4}{'Name':<16}{'Pri':>4}{'Arr':>5}{'1stRun':>7}{'Fin':>5}{'CPU':>5}"
                 f"{'Wait':>6}{'RdyW':>6}{'TAT':>5}{'Resp':>6}{'I/Ow':>6}{'MemW':>6}  Status"]
        for m in self.per_process:
            lines.append(f"P{m.pid:02d} {m.name:<16}{m.priority:>4}{m.arrival:>5}{n(m.first_run):>7}"
                         f"{n(m.finish):>5}{m.cpu_time:>5}{n(m.waiting):>6}{m.ready_wait:>6}{n(m.turnaround):>5}"
                         f"{n(m.response):>6}{m.io_wait:>6}{m.admission_wait:>6}  {m.status}")
        lines += ["",
                  f"Average waiting time    : {self.avg_waiting:.2f}   (turnaround - CPU burst)",
                  f"Average ready-queue wait: {self.avg_ready_wait:.2f}   (READY state only)",
                  f"Average turnaround time : {self.avg_turnaround:.2f}",
                  f"Average response time   : {self.avg_response:.2f}",
                  f"Throughput              : {self.throughput:.3f} processes/tick",
                  f"CPU utilisation         : {self.cpu_utilization:.1f}%",
                  f"Memory utilisation      : avg {self.avg_memory_utilization:.1f}% | "
                  f"peak {self.peak_memory_utilization:.1f}%",
                  "I/O utilisation         : " + " | ".join(
                      f"{d} {u:.1f}%" for d, u in self.io_utilization.items()),
                  f"Context switches        : {self.context_switches}"]
        if self.battery_remaining is not None:
            lines.append(f"Battery remaining       : {self.battery_remaining:.2f}")
        lines.append("Gantt (CPU)             : " + " ".join(
            f"[{s}-{e} {'IDLE' if p is None else f'P{p:02d}'}]" for s, e, p in self.gantt))
        return "\n".join(lines)


class MetricsCollector:
    def __init__(self) -> None:
        self._cpu_busy = 0
        self._ticks = 0
        self._mem_samples: List[float] = []
        self._timeline: List[Tuple[int, Optional[int]]] = []
        self.context_switches = 0

    def record_tick(self, now: int, snap: ResourceSnapshot, running_pid: Optional[int]) -> None:
        self._ticks += 1
        if running_pid is not None:
            self._cpu_busy += 1
        self._mem_samples.append(snap.mem_used_kb / snap.mem_total_kb)
        self._timeline.append((now, running_pid))

    def record_context_switch(self) -> None:
        self.context_switches += 1

    def _gantt(self) -> List[Tuple[int, int, Optional[int]]]:
        segments: List[Tuple[int, int, Optional[int]]] = []
        for t, pid in self._timeline:
            if segments and segments[-1][2] == pid and segments[-1][1] == t:
                segments[-1] = (segments[-1][0], t + 1, pid)
            else:
                segments.append((t, t + 1, pid))
        return segments

    def build_report(self, processes: Iterable[Process], total_time: int,
                     io_busy_ticks: Dict[str, int], final: ResourceSnapshot,
                     label: str) -> MetricsReport:
        rows: List[ProcessMetrics] = []
        for p in sorted(processes, key=lambda x: x.pid):
            done = p.exit_reason == "completed"
            rows.append(ProcessMetrics(
                pid=p.pid, name=p.name, priority=p.priority, arrival=p.arrival_time,
                first_run=p.first_run_time, finish=p.finish_time, cpu_time=p.cpu_time_used,
                admission_wait=p.time_in_state[ProcessState.NEW],
                waiting=((p.finish_time - p.arrival_time - p.cpu_time_used) if done else None),
                ready_wait=p.time_in_state[ProcessState.READY],
                io_wait=p.time_in_state[ProcessState.WAITING],
                turnaround=(p.finish_time - p.arrival_time) if done else None,
                response=(p.first_run_time - p.arrival_time) if (done and p.first_run_time is not None) else None,
                status=p.exit_reason or p.state.value))
        finished = [r for r in rows if r.status == "completed"]

        def avg(values: List[float]) -> float:
            return sum(values) / len(values) if values else 0.0

        denom = max(total_time, 1)
        return MetricsReport(
            label=label, total_time=total_time, per_process=rows,
            completed=len(finished), not_completed=len(rows) - len(finished),
            avg_waiting=avg([r.waiting for r in finished]),
            avg_ready_wait=avg([r.ready_wait for r in finished]),
            avg_turnaround=avg([r.turnaround for r in finished]),
            avg_response=avg([r.response for r in finished if r.response is not None]),
            throughput=len(finished) / denom,
            cpu_utilization=100.0 * self._cpu_busy / denom,
            avg_memory_utilization=100.0 * avg(self._mem_samples),
            peak_memory_utilization=100.0 * max(self._mem_samples, default=0.0),
            io_utilization={d: 100.0 * b / denom for d, b in io_busy_ticks.items()},
            context_switches=self.context_switches,
            battery_remaining=final.battery_remaining,
            gantt=self._gantt())
