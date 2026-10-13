"""Byte-preserving terminal bridge and carousel controller."""

import argparse
import errno
import fcntl
from importlib.resources import files
import os
from pathlib import Path
import pty
import select
import signal
import struct
import sys
import termios
import time
import tomllib
import tty

from . import __version__
from .backend import BackendError, TmuxBackend, find_tmux
from .config import Config, default_path, load_config
from .keys import InputRouter, prefix_sequence
from .rotation import Rotation


def write_all(fd: int, data: bytes) -> None:
    while data:
        try:
            count = os.write(fd, data)
        except InterruptedError:
            continue
        data = data[count:]


class Carousel:
    def __init__(self, config: Config):
        self.config = config
        self.backend = TmuxBackend(config)
        self.router = InputRouter(prefix_sequence(config.prefix), config.input_bindings())
        self.rotation = Rotation(config.idle_timeout, config.interval, config.auto_rotate, time.monotonic())
        self.stopping = False
        self.resized = False
        self.child_pid: int | None = None
        self.master: int | None = None

    def _signal(self, signum, _frame) -> None:
        if signum == signal.SIGWINCH:
            self.resized = True
        else:
            self.stopping = True

    def _resize(self, stdin: int) -> None:
        size = os.get_terminal_size(stdin)
        dimensions = struct.pack("HHHH", size.lines, size.columns, 0, 0)
        if self.master is not None:
            fcntl.ioctl(self.master, termios.TIOCSWINSZ, dimensions)
        self.resized = False

    def _events(self, data: bytes, now: float) -> None:
        if data:
            self.rotation.activity(now)
        for event in self.router.feed(data, now):
            if event.kind == "data":
                write_all(self.master, event.value)
            elif event.kind == "literal_prefix":
                write_all(self.master, event.value * 2)
            elif event.value in ("next", "previous"):
                write_all(self.master, self.backend.action_keys(event.value))
                self.rotation.activity(now, manual_switch=True)
            elif event.value == "toggle_rotation":
                self.rotation.toggle(now)
            elif event.value == "reconnect":
                write_all(self.master, self.backend.action_keys("reconnect"))
            elif event.value == "quit":
                self.stopping = True
                break

    def run(self) -> int:
        stdin, stdout = sys.stdin.fileno(), sys.stdout.fileno()
        if not os.isatty(stdin) or not os.isatty(stdout):
            self.backend.close()
            raise BackendError("run tcar in an interactive terminal (or use --check)")
        old_term = termios.tcgetattr(stdin)
        signals = (signal.SIGWINCH, signal.SIGTERM, signal.SIGHUP, signal.SIGINT)
        old_handlers = {sig: signal.getsignal(sig) for sig in signals}
        terminal_changed = False
        client_exit = 0
        try:
            for sig in signals:
                signal.signal(sig, self._signal)
            size = os.get_terminal_size(stdin)
            self.backend.start(max(size.columns, 2), max(size.lines, 2))
            if self.stopping:
                return 0
            self.backend.status(self.rotation.mode)
            self.child_pid, self.master = pty.fork()
            if self.child_pid == 0:
                # pty.fork gives the attached client its own controlling terminal.
                try:
                    os.execvpe(self.backend.executable, self.backend.client_argv(), self.backend.env)
                except OSError as error:
                    os.write(2, f"tcar: cannot attach terminal: {error}\n".encode())
                    os._exit(1)
            self._resize(stdin)
            tty.setraw(stdin)
            terminal_changed = True
            # Starting SSH windows is not counted as time spent idle.
            self.rotation.activity(time.monotonic())
            while not self.stopping:
                if self.resized:
                    self._resize(stdin)
                ready, _, _ = select.select([stdin, self.master], [], [], 0.05)
                now = time.monotonic()
                # Input takes precedence over a rotation due at the same instant.
                if stdin in ready:
                    data = os.read(stdin, 65536)
                    if not data:
                        break
                    self._events(data, now)
                else:
                    self._events(b"", now)
                if self.master in ready:
                    try:
                        output = os.read(self.master, 65536)
                    except OSError as error:
                        if error.errno == errno.EIO:
                            break
                        raise
                    if not output:
                        break
                    write_all(stdout, output)
                # Never switch while a prefix, fragmented key, or paste is pending.
                pending = self.router.prefixed or self.router.pasting or bool(self.router.buffer)
                if not self.stopping and not pending and self.rotation.tick(now):
                    self.backend.select(1)
                if not self.stopping:
                    self.backend.maintain(now)
                    self.backend.status(self.rotation.mode, self.router.prefixed)
        finally:
            self.backend.close()
            if self.master is not None:
                # Let tmux restore the outer terminal before restoring termios.
                try:
                    deadline = time.monotonic() + 0.5
                    while time.monotonic() < deadline and select.select([self.master], [], [], 0.05)[0]:
                        data = os.read(self.master, 65536)
                        if not data:
                            break
                        write_all(stdout, data)
                except OSError:
                    pass
                finally:
                    os.close(self.master)
            if terminal_changed:
                termios.tcsetattr(stdin, termios.TCSANOW, old_term)
                write_all(stdout, b"\x1b[?1049l\x1b[?1l\x1b>\x1b[?2004l\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1006l\x1b[?25h\x1b[0m")
            for sig, handler in old_handlers.items():
                signal.signal(sig, handler)
            if self.child_pid:
                try:
                    pid, status = os.waitpid(self.child_pid, os.WNOHANG)
                    if not pid:
                        os.kill(self.child_pid, signal.SIGTERM)
                        _, status = os.waitpid(self.child_pid, 0)
                    if not self.stopping:
                        code = os.waitstatus_to_exitcode(status)
                        client_exit = code if code >= 0 else 128 - code
                except (ChildProcessError, ProcessLookupError):
                    pass
        return client_exit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tcar", description="Persistent local and SSH terminals in a rotating full-screen view.")
    parser.add_argument("-c", "--config", type=Path, default=default_path(), help="TOML configuration (default: %(default)s)")
    parser.add_argument("--check", action="store_true", help="validate configuration and dependencies without starting sessions")
    parser.add_argument("--demo", action="store_true", help="try three local demo sessions without SSH")
    parser.add_argument("--init-config", nargs="?", const=default_path(), type=Path, metavar="PATH",
                        help="write a starter configuration without overwriting an existing file")
    parser.add_argument("--demo-machine", help=argparse.SUPPRESS)
    parser.add_argument("--version", action="version", version=f"tcar {__version__}")
    args = parser.parse_args(argv)
    try:
        if args.init_config is not None:
            destination = args.init_config.expanduser()
            template = files("tcar").joinpath("data", "config.example.toml").read_text(encoding="utf-8")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("x", encoding="utf-8") as target:
                target.write(template)
            print(f"Created {destination}. Edit the SSH aliases, then run tcar --check.")
            return 0
        if args.demo_machine is not None:
            import curses
            from .demo import dashboard
            curses.wrapper(dashboard, args.demo_machine)
            return 0
        if args.demo:
            from .demo import demo_config
            config = demo_config()
        else:
            config = load_config(args.config.expanduser())
        find_tmux()
        if args.check:
            print(f"Configuration OK: {len(config.machines)} machines; prefix {config.prefix}; "
                  f"idle {config.idle_timeout:g}s; interval {config.interval:g}s")
            for machine in config.machines:
                print(f"  {machine.name} ({'SSH' if machine.host or machine.ssh_command else 'local'}): {machine.shell_command()}")
            return 0
        return Carousel(config).run()
    except FileExistsError:
        print(f"tcar: configuration already exists: {args.init_config}; keeping your existing file", file=sys.stderr)
    except FileNotFoundError as error:
        print(f"tcar: {error}. Run tcar --init-config, or try --demo.", file=sys.stderr)
    except (ValueError, tomllib.TOMLDecodeError, BackendError, OSError) as error:
        print(f"tcar: {error}", file=sys.stderr)
    return 1
