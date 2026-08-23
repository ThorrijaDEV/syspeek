"""Tests de syspeek: parsers de /proc con fixtures falsos y deltas."""

import os
import textwrap

import pytest

from syspeek import proc, ui


@pytest.fixture
def fakeproc(tmp_path):
    """Árbol /proc falso con stat, meminfo, net/dev y uptime."""
    p = tmp_path / "proc"
    (p / "net").mkdir(parents=True)

    (p / "stat").write_text(textwrap.dedent("""\
        cpu  100 0 50 700 40 0 10 0 0 0
        cpu0 100 0 50 300 20 0 5 0 0 0
        cpu1 100 0 50 400 20 0 5 0 0 0
        intr 0
        """))
    (p / "meminfo").write_text(textwrap.dedent("""\
        MemTotal:       8000000 kB
        MemFree:        2000000 kB
        MemAvailable:   4000000 kB
        Buffers:         500000 kB
        Cached:         1500000 kB
        SwapTotal:      2000000 kB
        SwapFree:       1500000 kB
        """))
    (p / "net" / "dev").write_text(
        "Inter-|   Receive                        "
        "|  Transmit\n"
        " face |bytes    packets errs drop fifo frame "
        "|compressed multicast|bytes    packets errs drop fifo colls carrier\n"
        "    lo: 100 10 0 0 0 0 0 0 100 10 0 0 0 0 0 0\n"
        "wlan0: 1000000 900 0 0 0 0 0 0 500000 700 0 0 0 0 0 0\n")
    (p / "uptime").write_text("98765.42 123456.78\n")

    def add_pid(pid, comm, utime, stime, rss_pages):
        d = p / str(pid)
        d.mkdir(exist_ok=True)
        # comm con paréntesis dentro para probar el parser
        (d / "stat").write_text(
            f"{pid} ({comm}) R 1 0 0 0 -1 0 0 0 0 0 {utime} {stime} 0 0 0 0 0 0 0 0 {rss_pages} 0 0\n")

    add_pid(101, "bash", 100, 50, 200)          # 200 páginas * 4096 = 800 KiB
    add_pid(102, "chrome (gpu)", 300, 100, 2500)
    return p


class TestCpu:
    def test_reads_global_and_cores(self, fakeproc):
        snap = proc.read_cpu(str(fakeproc))
        assert len(snap.cores) == 2
        assert snap.total == sum(range(0)) or snap.total > 0

    def test_pct_between_snapshots(self, fakeproc):
        a = proc.read_cpu(str(fakeproc))
        (fakeproc / "stat").write_text(
            "cpu  200 0 50 700 40 0 10 0 0 0\n"
            "cpu0 200 0 50 300 20 0 5 0 0 0\n"
            "cpu1 100 0 50 400 20 0 5 0 0 0\n")
        b = proc.read_cpu(str(fakeproc))
        glob, cores = proc.cpu_pct(a, b)
        # global: Δtotal=100 con Δidle=0 → 100% uso; cpu1 sin cambios → 0%
        assert glob == pytest.approx(100.0)
        assert cores[0] == pytest.approx(100.0)
        assert cores[1] == 0.0

    def test_no_regression_on_equal_snapshot(self, fakeproc):
        s = proc.read_cpu(str(fakeproc))
        assert proc.cpu_pct(s, s) == (0.0, [0.0] * len(s.cores))


class TestMemNet:
    def test_meminfo_kib_to_bytes(self, fakeproc):
        m = proc.read_meminfo(str(fakeproc))
        assert m.total == 8_000_000 * 1024
        assert m.used == (8_000_000 - 4_000_000) * 1024
        assert m.used_pct == 50.0

    def test_net_skips_loopback(self, fakeproc):
        n = proc.read_net(str(fakeproc))
        assert list(n.ifaces) == ["wlan0"]
        assert n.ifaces["wlan0"] == (1_000_000, 500_000)

    def test_net_rates(self, fakeproc):
        a = proc.read_net(str(fakeproc))
        (fakeproc / "net" / "dev").write_text(
            (fakeproc / "net" / "dev").read_text().replace("1000000 900", "2000000 900"))
        b = proc.read_net(str(fakeproc))
        rates = proc.net_rates(a, b, dt=2.0)
        assert rates["wlan0"][0] == pytest.approx(500_000.0)
        assert rates["wlan0"][1] == 0.0

    def test_rates_guard_zero_dt(self, fakeproc):
        n = proc.read_net(str(fakeproc))
        assert proc.net_rates(n, n, dt=0.0)["wlan0"] == (0.0, 0.0)


class TestProcs:
    def test_parse_comm_with_parens(self, fakeproc):
        s = proc.parse_pid_stat((fakeproc / "102" / "stat").read_text())
        assert s.pid == 102
        assert s.comm == "chrome (gpu)"
        assert s.utime == 300 and s.stime == 100

    def test_snapshot_collects_all(self, fakeproc):
        procs = proc.procs_snapshot(str(fakeproc))
        assert set(procs) == {101, 102}

    def test_rows_cpu_delta(self, fakeproc):
        a = proc.procs_snapshot(str(fakeproc))
        # avanza bash 100 jiffies de utime
        (fakeproc / "101" / "stat").write_text(
            f"101 (bash) R 1 0 0 0 -1 0 0 0 0 0 200 50 0 0 0 0 0 0 0 0 200 0 0\n")
        b = proc.procs_snapshot(str(fakeproc))
        rows = {r.pid: r for r in proc.proc_rows(a, b, dt=2.0, mem_total=8_000_000 * 1024)}
        # CLK_TCK suele ser 100: 100 jiffies / (100 * 2s) = 50%
        assert rows[101].cpu_pct == pytest.approx(50.0, rel=0.01)
        assert rows[102].cpu_pct == 0.0

    def test_uptime(self, fakeproc):
        assert proc.read_uptime(str(fakeproc)) == pytest.approx(98765.42)


class TestUiHelpers:
    def test_bar_bounds(self):
        assert ui.bar(0.5, 4) == "██░░"
        assert ui.bar(2, 3) == "███"
        assert ui.bar(-1, 3) == "░░░"

    def test_sparkline_scales_to_max(self):
        s = ui.sparkline([0, 50, 100])
        assert s[0] == "▁" and s[-1] == "█"

    def test_human_bytes(self):
        assert ui.human_bytes(512) == "512B"
        assert ui.human_bytes(2048) == "2.0KiB"
        assert ui.human_bytes(1536 * 1024**2) == "1.5GiB"

    def test_fmt_uptime(self):
        assert ui.fmt_uptime(30) == "30s"
        assert ui.fmt_uptime(90 * 60) == "1h 30m"
        assert ui.fmt_uptime(25 * 3600) == "1d 1h 00m"

    def test_color_thresholds(self):
        assert ui.color_for_pct(10) == ui.LIME
        assert ui.color_for_pct(70) == ui.WARN
        assert ui.color_for_pct(99) == ui.PINK
