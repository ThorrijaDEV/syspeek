# ✦ syspeek

Dashboard TUI de sistema en **curses puro** — cero dependencias externas, solo stdlib de Python. CPU por núcleo, memoria/swap, tasas de red con sparklines y top de procesos, todo leído directamente de `/proc`.

```
 ✦ SYSPEEK ✦  archlinux · 6.9.1-arch · up 1d 3h 27m
 ──────────────────────────────────────────────────
CPU ████████████░░░░░░░░░░░░ 47.3%  hist ▁▂▂▃▅▆▇█▇▆▅
  0:████░░░░ 1:███░░░░░ 2:█████░░░ ...
MEM ██████████░░░░░░░░░░░░░░ 6.1GiB/15.5GiB
SWP █░░░░░░░░░░░░░░░░░░░░░░░ 512.0MiB/8.0GiB
RED
 wlan0     ▼    2.4MiB/s  ▲  310.5KiB/s  ▁▂▃▄▅▄▃▂
TOP PROCESOS (CPU)  [s] orden  [q] salir
     PID    CPU%    MEM%       RSS  COMANDO
   18234   89.2    4.1     2.6GiB  chrome (gpu)
    1104   12.0    0.3   180.0MiB  Xorg
```

## Por qué

`htop` y `btop` son maravillas, pero entre ambos suman decenas de miles de líneas C/C++. `syspeek` es el experimento inverso: **¿cuánto dashboard cabe en ~400 líneas de Python stdlib?** Sin psutil, sin curses wrappers de terceros: parsers propios de `/proc/stat`, `meminfo`, `net/dev` y `PID/stat`, deltas calculados a mano.

## Uso

```bash
pip install syspeek
syspeek                # dashboard en vivo (refresco 1 s)
syspeek --interval .5  # más rápido
syspeek --once         # snapshot texto plano para scripts/cron
```

Teclas: **q** salir · **s** alternar orden procesos CPU↔MEM.

## Qué lee exactamente

| Fuente | Métrica |
|---|---|
| `/proc/stat` | jiffies idle/total → % uso global y por núcleo |
| `/proc/meminfo` | MemAvailable, buffers/cache, swap |
| `/proc/net/dev` | rx/tx acumulados → tasas B/s por interfaz (sin lo) |
| `/proc/PID/stat` | utime+stime → % CPU real por proceso; statm→RSS |
| `/proc/uptime` | uptime formateado |

Solo Linux (es la gracia de leer `/proc`). El modo `--once` imprime un frame plano para pipelines:

```bash
watch -n5 syspeek --once        # o en scripts:
syspeek --once | grep '^CPU'
```

## Desarrollo

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e . pytest
pytest   # 18 tests: parsers con /proc falsos, deltas CPU/red/procs, helpers UI
```

```
src/syspeek/
├── proc.py   # snapshots crudos + cálculo de deltas (puro, testeable)
├── ui.py     # barras/sparklines/layout curses
└── cli.py    # bucle principal + modo --once
tests/
```

## Licencia

[MIT](LICENSE)
