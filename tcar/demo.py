"""Independent local dashboards for trying the carousel without remote access."""

from __future__ import annotations

import curses
import os
import socket
import sys
import time
import zipfile


def demo_config() -> Config:
    from .config import Config, Machine

    # Both installed packages and a standalone .pyz can launch hidden sessions.
    if zipfile.is_zipfile(sys.argv[0]):
        launcher = (sys.executable, os.path.abspath(sys.argv[0]))
    else:
        launcher = (sys.executable, "-m", "tcar")
    machines = tuple(Machine(name, local_command=(*launcher, "--demo-machine", name))
                     for name in ("local-alpha", "local-beta", "local-gamma"))
    return Config(machines, idle_timeout=5, interval=4)


def dashboard(screen, name: str) -> None:
    curses.curs_set(0)
    screen.nodelay(True)
    started = time.monotonic()
    last_key = "none"
    while True:
        key = screen.getch()
        if key != -1:
            last_key = repr(chr(key)) if key < 256 else str(key)
        screen.erase()
        lines = [
            f"{name} — local demo session",
            "", f"Host: {socket.gethostname()}", f"Process: {os.getpid()}",
            f"Running: {time.monotonic() - started:.1f}s (keeps updating while hidden)",
            f"Local load average: {', '.join(f'{x:.2f}' for x in os.getloadavg())}",
            f"Last forwarded key: {last_key}", "",
            "Ctrl+G then Left/Right: switch | Space: toggle rotation | q: quit tcar",
            "Ordinary keys reach this demo and pause rotation for 5 seconds.",
        ]
        height, width = screen.getmaxyx()
        for row, line in enumerate(lines[:max(0, height - 1)]):
            try:
                screen.addnstr(row, 0, line, max(0, width - 1), curses.A_BOLD if row == 0 else 0)
            except curses.error:
                pass
        screen.refresh()
        time.sleep(0.1)


if __name__ == "__main__":
    curses.wrapper(dashboard, sys.argv[1])
