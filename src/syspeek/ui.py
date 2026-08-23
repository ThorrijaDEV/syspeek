"""Renderizado curses: barras ASCII, sparklines y layout del dashboard."""

from __future__ import annotations

import curses

BLOCKS = "▁▂▃▄▅▆▇█"

PINK = 1
CYAN = 2
LIME = 3
VIOLET = 4
WARN = 5
DIM = 6


def init_colors() -> None:
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(PINK, 201, -1)
    curses.init_pair(CYAN, 51, -1)
    curses.init_pair(LIME, 154, -1)
    curses.init_pair(VIOLET, 135, -1)
    curses.init_pair(WARN, 226, -1)
    curses.init_pair(DIM, 243, -1)


def bar(frac: float, width: int) -> str:
    frac = max(0.0, min(1.0, frac))
    filled = round(frac * width)
    return "█" * filled + "░" * (width - filled)


def sparkline(series: list[float], max_val: float | None = None) -> str:
    if not series:
        return ""
    top = max(max_val or 0.0, max(series), 1e-9)
    return "".join(
        BLOCKS[min(len(BLOCKS) - 1, int(v / top * len(BLOCKS)))] for v in series
    )


def human_bytes(n: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < 1024 or unit == "TiB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TiB"


def fmt_uptime(seconds: float) -> str:
    m = int(seconds // 60)
    return f"{m // 60 // 24}d {m // 60 % 24}h {m % 60:02d}m" if m >= 1440 else (
        f"{m // 60}h {m % 60:02d}m" if m >= 60 else f"{int(seconds)}s")


def color_for_pct(pct: float) -> int:
    return LIME if pct < 60 else (WARN if pct < 85 else PINK)


def draw(scr, state: dict) -> None:
    """Pinta un frame completo a partir de `state` ya calculado."""
    scr.erase()
    H, W = scr.getmaxyx()
    row = 0

    title = " ✦ SYSPEEK ✦ "
    scr.addstr(row, 2, title, curses.color_pair(PINK) | curses.A_BOLD)
    meta = f"{state['hostname']} · {state['kernel']} · up {fmt_uptime(state['uptime'])}"
    scr.addstr(row, min(len(title) + 4, W - len(meta) - 2),
               meta[: W - len(title) - 6], curses.color_pair(DIM))
    row += 1
    scr.addstr(row, 2, "─" * max(0, W - 4), curses.color_pair(VIOLET))
    row += 1

    # CPU global + núcleos
    cpu = state["cpu"]
    ccol = color_for_pct(cpu)
    scr.addstr(row, 2, f"CPU {bar(cpu / 100, 24)} {cpu:5.1f}%  ",
               curses.color_pair(ccol) | curses.A_BOLD)
    scr.addstr(f"hist {sparkline(state['cpu_hist'], 100)}",
               curses.color_pair(CYAN))
    row += 1
    per_core_line = "  ".join(
        f"{i}:{bar(v / 100, 8):<8}" for i, v in enumerate(state["cores"])
    )
    scr.addstr(row, 4, per_core_line[: W - 6], curses.color_pair(DIM))
    row += 2

    # Memoria + swap
    mem = state["mem"]
    scr.addstr(row, 2,
               f"MEM {bar(mem.used_pct / 100, 24)} {human_bytes(mem.used)}/{human_bytes(mem.total)}",
               curses.color_pair(color_for_pct(mem.used_pct)))
    row += 1
    swap_used = mem.swap_total - mem.swap_free
    if mem.swap_total:
        pct = 100.0 * swap_used / mem.swap_total
        scr.addstr(row, 2,
                   f"SWP {bar(pct / 100, 24)} {human_bytes(swap_used)}/{human_bytes(mem.swap_total)}",
                   curses.color_pair(color_for_pct(pct)))
        row += 1
    row += 1

    # Red
    scr.addstr(row, 2, "RED", curses.color_pair(CYAN) | curses.A_BOLD)
    row += 1
    for name, rates in list(state["net"].items())[:3]:
        rx_h, tx_h = human_bytes(rates[0]) + "/s", human_bytes(rates[1]) + "/s"
        line = f" {name:<10} ▼{rx_h:>12}  ▲{tx_h:>12}  {state['net_spark'].get(name, '')}"
        scr.addstr(row, 2, line[: W - 4], curses.color_pair(LIME))
        row += 1
    row += 1

    # Procesos
    scr.addstr(row, 2,
               f"TOP PROCESOS ({state['sort'].upper()}){' ↑↓' if False else ''}",
               curses.color_pair(VIOLET) | curses.A_BOLD)
    scr.addstr("  [s] orden  [q] salir", curses.color_pair(DIM))
    row += 1
    hdr = f" {'PID':>7}  {'CPU%':>6}  {'MEM%':>6}  {'RSS':>9}  COMANDO"
    scr.addstr(row, 2, hdr[: W - 4], curses.color_pair(DIM))
    row += 1
    for p in state["procs"][: max(0, H - row - 1)]:
        scr.addstr(row, 2,
                   f" {p.pid:>7}  {p.cpu_pct:>6.1f}  {p.mem_pct:>6.1f}  "
                   f"{human_bytes(p.rss):>9}  {p.comm[: max(4, W - 40)]}",
                   curses.color_pair(color_for_pct(p.cpu_pct)))
        row += 1
    scr.noutrefresh()
