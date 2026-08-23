"""Parsers de /proc: snapshots crudos y cálculo de deltas.

Cada función devuelve estructuras planas (dicts/tuples) para que la UI
solo pinte y los tests puedan alimentar /proc falsos con strings.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field


@dataclass
class CpuSnap:
    """Jiffies acumulados por núcleo + resumen global."""

    cores: list[tuple[int, int]]  # (idle, total) por cpu0..cpuN
    idle: int
    total: int


def read_cpu(proc_path: str = "/proc") -> CpuSnap:
    with open(os.path.join(proc_path, "stat")) as fh:
        lines = fh.read().splitlines()
    cores = []
    glob_idle = glob_total = 0
    for line in lines:
        parts = line.split()
        if not parts or not parts[0].startswith("cpu"):
            continue
        vals = [int(v) for v in parts[1:]]
        # user nice system idle iowait irq softirq steal ...
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
        total = sum(vals)
        if parts[0] == "cpu":
            glob_idle, glob_total = idle, total
        elif re.fullmatch(r"cpu\d+", parts[0]):
            cores.append((idle, total))
    return CpuSnap(cores=cores, idle=glob_idle, total=glob_total)


def cpu_pct(prev: CpuSnap, cur: CpuSnap) -> tuple[float, list[float]]:
    """Porcentaje de uso global y por núcleo entre dos snapshots."""

    def pct(a: tuple[int, int], b: tuple[int, int]) -> float:
        didle = b[0] - a[0]
        dtotal = b[1] - a[1]
        if dtotal <= 0:
            return 0.0
        return max(0.0, min(100.0, 100.0 * (1 - didle / dtotal)))

    per_core = [
        pct(a, b) for a, b in zip(prev.cores, cur.cores)
    ]
    return pct((prev.idle, prev.total), (cur.idle, cur.total)), per_core


@dataclass
class MemInfo:
    total: int
    avail: int
    buffers: int
    cached: int
    swap_total: int
    swap_free: int

    @property
    def used(self) -> int:
        return self.total - self.avail

    @property
    def used_pct(self) -> float:
        return 100.0 * self.used / self.total if self.total else 0.0


_KIB = 1024


def read_meminfo(proc_path: str = "/proc") -> MemInfo:
    kv: dict[str, int] = {}
    with open(os.path.join(proc_path, "meminfo")) as fh:
        for line in fh:
            key, rest = line.split(":", 1)
            kv[key] = int(rest.strip().split()[0]) * _KIB
    return MemInfo(
        total=kv.get("MemTotal", 0),
        avail=kv.get("MemAvailable", 0),
        buffers=kv.get("Buffers", 0),
        cached=kv.get("Cached", 0),
        swap_total=kv.get("SwapTotal", 0),
        swap_free=kv.get("SwapFree", 0),
    )


@dataclass
class NetSnap:
    """Bytes rx/tx acumulados por interfaz (sin loopback)."""

    ifaces: dict[str, tuple[int, int]] = field(default_factory=dict)


def read_net(proc_path: str = "/proc") -> NetSnap:
    snap = NetSnap()
    with open(os.path.join(proc_path, "net", "dev")) as fh:
        for line in fh.readlines()[2:]:
            iface, rest = line.split(":", 1)
            iface = iface.strip()
            if iface == "lo":
                continue
            fields = rest.split()
            snap.ifaces[iface] = (int(fields[0]), int(fields[8]))
    return snap


def net_rates(prev: NetSnap, cur: NetSnap, dt: float) -> dict[str, tuple[float, float]]:
    """Bytes/s de descarga y subida por interfaz entre snapshots."""
    out: dict[str, tuple[float, float]] = {}
    for name, (rx, tx) in cur.ifaces.items():
        prx, ptx = prev.ifaces.get(name, (rx, tx))
        out[name] = (
            max(0.0, (rx - prx) / dt) if dt > 0 else 0.0,
            max(0.0, (tx - ptx) / dt) if dt > 0 else 0.0,
        )
    return out


@dataclass
class ProcSample:
    pid: int
    comm: str
    utime: int
    stime: int
    rss: int  # bytes


_COMM_RE = re.compile(r"^\d+\s+\((?P<comm>.*)\)\s+(?P<rest>.*)$")


def parse_pid_stat(raw: str) -> ProcSample:
    """Parsea una línea de /proc/PID/stat tolerando paréntesis en comm."""
    m = _COMM_RE.match(raw.strip())
    if not m:
        raise ValueError(f"línea stat ilegible: {raw[:60]!r}")
    fields = m.group("rest").split()
    # tras comm el campo 3 es state; utime es campo 14 → índice 11 del resto
    return ProcSample(
        pid=int(raw.split()[0]),
        comm=m.group("comm"),
        utime=int(fields[11]),
        stime=int(fields[12]),
        rss=int(fields[21]) * os.sysconf("SC_PAGE_SIZE"),
    )


_CLK_TCK = os.sysconf("SC_CLK_TCK")


def procs_snapshot(proc_path: str = "/proc") -> dict[int, ProcSample]:
    """Muestrea todos los procesos legibles {pid: sample}."""
    out: dict[int, ProcSample] = {}
    for entry in os.listdir(proc_path):
        if not entry.isdigit():
            continue
        try:
            with open(os.path.join(proc_path, entry, "stat")) as fh:
                out[int(entry)] = parse_pid_stat(fh.read())
        except (OSError, ValueError, IndexError):
            continue  # proceso efímero o protegido
    return out


@dataclass
class ProcRow:
    pid: int
    comm: str
    cpu_pct: float
    mem_pct: float
    rss: int


def proc_rows(prev: dict[int, ProcSample], cur: dict[int, ProcSample],
              dt: float, mem_total: int) -> list[ProcRow]:
    rows = []
    for pid, c in cur.items():
        p = prev.get(pid)
        dcpu = (c.utime + c.stime) - (p.utime + p.stime) if p else 0
        cpu = 100.0 * dcpu / (_CLK_TCK * dt) if dt > 0 and _CLK_TCK else 0.0
        rows.append(ProcRow(
            pid=pid,
            comm=c.comm,
            cpu_pct=max(0.0, min(100.0 * max(1, os.cpu_count() or 1), cpu)),
            mem_pct=100.0 * c.rss / mem_total if mem_total else 0.0,
            rss=c.rss,
        ))
    return rows


def read_uptime(proc_path: str = "/proc") -> float:
    with open(os.path.join(proc_path, "uptime")) as fh:
        return float(fh.read().split()[0])
