"""CLI de syspeek: bucle principal curses + modo snapshot sin TTY."""

from __future__ import annotations

import argparse
import curses
import os
import platform
import socket
import sys
import time

from . import proc, ui


def collect(prev_cpu, prev_net, prev_procs, state) -> dict:
    """Un frame de datos: lee /proc y calcula deltas contra el tick anterior."""
    now = time.monotonic()
    dt = now - state.get("t0", now - 1)
    state["t0"] = now

    cpu = proc.read_cpu()
    net = proc.read_net()
    procs = proc.procs_snapshot()
    mem = proc.read_meminfo()

    pct, cores = proc.cpu_pct(prev_cpu, cpu)
    hist = state.setdefault("cpu_hist", [])
    hist.append(pct)
    del hist[:-60]

    rates = proc.net_rates(prev_net, net, dt)
    spark = {
        name: state.setdefault("net_spark", {}).get(name, "")
        for name in rates
    }
    for name, (rx, tx) in rates.items():
        series = state["net_spark"].setdefault(name, [])
        series.append(rx)
        del series[:-30]

    rows = sorted(
        proc.proc_rows(prev_procs, procs, max(dt, 1e-6), mem.total),
        key=lambda r: (r.cpu_pct if state["sort"] == "cpu" else r.mem_pct),
        reverse=True,
    )

    return {
        "hostname": socket.gethostname(),
        "kernel": platform.release(),
        "uptime": proc.read_uptime(),
        "cpu": pct,
        "cores": cores,
        "cpu_hist": hist,
        "mem": mem,
        "net": rates,
        "net_spark": {k: ui.sparkline(v[-20:]) for k, v in state["net_spark"].items()},
        "procs": rows[:40],
        "sort": state["sort"],
    }


def run_loop(scr, interval: float) -> None:
    curses.curs_set(0)
    scr.nodelay(True)
    scr.timeout(int(interval * 1000))
    ui.init_colors()

    state: dict = {"sort": "cpu"}
    prev_cpu = proc.read_cpu()
    prev_net = proc.read_net()
    prev_procs = proc.procs_snapshot()
    time.sleep(interval)

    while True:
        key = scr.getch()
        if key in (ord("q"), ord("Q"), 27):
            return
        if key in (ord("s"), ord("S")):
            state["sort"] = "mem" if state["sort"] == "cpu" else "cpu"
        try:
            frame = collect(prev_cpu, prev_net, prev_procs, state)
        except OSError as exc:
            raise SystemExit(f"syspeek: no puedo leer /proc: {exc}") from exc
        ui.draw(scr, frame)
        curses.doupdate()
        prev_cpu, prev_net, prev_procs = (
            proc.read_cpu(), proc.read_net(), proc.procs_snapshot())


def snapshot_once() -> str:
    """Modo texto plano (para scripts/CI): un frame formateado."""
    state: dict = {"sort": "cpu", "t0": time.monotonic() - 1.0}
    frame = collect(proc.read_cpu(), proc.read_net(),
                    proc.procs_snapshot(), state)
    mem = frame["mem"]
    lines = [
        f"CPU   {frame['cpu']:5.1f}%  {''.join(f'{c:4.0f}' for c in frame['cores'][:16])}",
        f"MEM   {ui.human_bytes(mem.used)}/{ui.human_bytes(mem.total)} ({mem.used_pct:.0f}%)",
    ]
    for name, (rx, tx) in list(frame["net"].items())[:3]:
        lines.append(f"NET {name:<8} ▼{ui.human_bytes(rx)}/s ▲{ui.human_bytes(tx)}/s")
    for p in frame["procs"][:5]:
        lines.append(f"P {p.pid:>7} {p.cpu_pct:5.1f}% {ui.human_bytes(p.rss):>9} {p.comm}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="syspeek",
        description="Dashboard TUI de sistema leyendo /proc (solo Linux).")
    ap.add_argument("--interval", type=float, default=1.0,
                    help="segundos entre refrescos (default 1.0)")
    ap.add_argument("--once", action="store_true",
                    help="imprime un snapshot en texto plano y sale")
    args = ap.parse_args(argv)

    if args.once:
        print(snapshot_once())
        return 0
    if not sys.stdout.isatty():
        print("syspeek: sin TTY — usa --once para modo script", file=sys.stderr)
        return 2
    try:
        curses.wrapper(run_loop, max(0.2, args.interval))
    except curses.error as exc:
        if not os.isatty(sys.stdout.fileno()):
            raise SystemExit("syspeek: terminal no compatible") from exc
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
