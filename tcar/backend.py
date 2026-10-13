"""An isolated tmux server owns PTYs, terminal emulation, and retained screens."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from .config import Config
from .keys import prefix_sequence


class BackendError(RuntimeError):
    pass


def find_tmux() -> str:
    executable = shutil.which("tmux")
    if not executable:
        raise BackendError("tmux is required; install it with brew install tmux or your Linux package manager")
    return executable


class TmuxBackend:
    def __init__(self, config: Config):
        self.config = config
        self.executable = find_tmux()
        self.directory = tempfile.TemporaryDirectory(prefix="tcar-", dir="/tmp")
        self.socket = str(Path(self.directory.name) / "socket")
        self.env = os.environ.copy()
        self.env.pop("TMUX", None)
        self.env.pop("TMUX_PANE", None)
        self.env.setdefault("TERM", "xterm-256color")
        self.windows: list[str] = []
        self._closed = False
        self._mode = None

    def native_prefix(self) -> str:
        code = prefix_sequence(self.config.prefix)[0]
        if code == 0:
            return "C-Space"
        if code < 32:
            return "C-" + chr(code + 64).lower()
        if code == 127:
            return "BSpace"
        return "Space" if code == 32 else chr(code)

    def client_argv(self) -> list[str]:
        return [self.executable, "-S", self.socket, "-f", "/dev/null", "attach-session", "-t", "tcar"]

    def run(self, *args: str) -> str:
        try:
            result = subprocess.run([self.executable, "-S", self.socket, "-f", "/dev/null", *args],
                                    env=self.env, capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise BackendError(f"tmux command failed: {error}") from error
        if result.returncode:
            raise BackendError(result.stderr.strip() or f"tmux exited with status {result.returncode}")
        if args and args[0] == "new-session" and not Path(self.socket).exists():
            raise BackendError(result.stderr.strip() or "tmux did not create its server socket")
        return result.stdout.strip()

    def start(self, columns: int, lines: int) -> None:
        # Configure remain-on-exit before launching programs, even short-lived ones.
        self.run("new-session", "-d", "-s", "tcar", "-x", str(columns), "-y", str(lines),
                 "exec sleep 2147483647")
        options = {
            "prefix": self.native_prefix(), "prefix2": "None", "mouse": "off",
            "default-terminal": "xterm-256color", "default-shell": "/bin/sh",
            "base-index": "1", "status": "on" if self.config.status_bar else "off",
            "assume-paste-time": "0",
            "status-style": "bg=colour234,fg=colour250", "status-left": " tcar ",
            "status-left-length": "8", "status-right-length": "80", "status-interval": "1",
            "status-justify": "left", "automatic-rename": "off", "allow-rename": "off",
            "remain-on-exit": "on", "window-size": "largest", "aggressive-resize": "off",
            "window-status-format": " #I:#W#{?pane_dead, (exited),} ",
            "window-status-current-format": "#[bg=colour24,fg=colour255,bold] #I:#W#{?pane_dead, (exited),} #[default]",
        }
        # One command transaction avoids dozens of server round trips.
        commands: list[str] = ["unbind-key", "-a", ";", "unbind-key", "-a", "-T", "root"]
        for name, value in options.items():
            commands.extend([";", "set-option", "-g", name, value])
        commands.extend([";", "set-option", "-s", "escape-time", "10"])
        # Manual switches travel through the same client stream as application
        # input. This preserves ordering when a read contains typing AND a switch.
        for key, command in (("Left", "previous-window"), ("Right", "next-window"), ("Home", "respawn-window -k")):
            if len(self.config.machines) == 1 and key in ("Left", "Right"):
                command = "select-window"
            commands.extend([";", "bind-key", "-T", "prefix", key, command])
        commands.extend([";", "bind-key", "-T", "prefix", self.native_prefix(), "send-prefix"])
        self.run(*commands)
        for machine in self.config.machines:
            window = self.run("new-window", "-d", "-t", "tcar:", "-n", machine.name,
                              "-P", "-F", "#{window_id}", machine.shell_command())
            self.windows.append(window)
        self.run("select-window", "-t", self.windows[0], ";", "kill-window", "-t", "tcar:0")

    def select(self, delta: int) -> None:
        if len(self.windows) <= 1:
            return
        self.run("next-window" if delta > 0 else "previous-window", "-t", "tcar")

    def reconnect(self) -> None:
        self.run("respawn-window", "-k", "-t", "tcar:")

    def action_keys(self, action: str) -> bytes:
        return prefix_sequence(self.config.prefix) + {
            "next": b"\x1b[C", "previous": b"\x1b[D", "reconnect": b"\x1b[H",
        }[action]

    def status(self, mode: str, prefix_pending: bool = False) -> None:
        state = (mode, prefix_pending)
        if state == self._mode or not self.config.status_bar:
            return
        prefix = self.config.prefix.replace("#", "##")
        quit_key = self.config.bindings["quit"].replace("#", "##")
        right = f" {mode} | {prefix} + {quit_key}: quit "
        if prefix_pending:
            right = f" PREFIX: choose a key | {right}"
        self.run("set-option", "-g", "status-right", right)
        self._mode = state

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            subprocess.run([self.executable, "-S", self.socket, "kill-server"], env=self.env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass
        finally:
            self.directory.cleanup()
