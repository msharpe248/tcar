"""Real PTY/tmux tests. Run on macOS or Linux where Unix sockets are permitted."""

import errno
import fcntl
import os
from pathlib import Path
import select
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest

from tcar.backend import TmuxBackend
from tcar.config import Config, Machine


ROOT = Path(__file__).resolve().parents[1]
WORKER = '''
import os, select, sys, time, tty
tty.setraw(0)
name, path = sys.argv[1:]
started = time.monotonic()
with open(path, "ab", buffering=0) as log:
    while True:
        os.write(1, ("\\x1b[H\\x1b[2J" + name + " alive " + str(os.getpid()) + " " + str(round(time.monotonic()-started, 2))).encode())
        if select.select([0], [], [], .05)[0]:
            data = os.read(0, 65536)
            if not data: break
            log.write(data)
'''


def wait_for(predicate, pump=lambda: None, timeout=4):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pump()
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError("timed out waiting for terminal state")


def terminal_attributes(fd):
    attributes = termios.tcgetattr(fd)
    # macOS sets PENDIN itself when switching back from raw mode. It is a
    # transient kernel flag, not a change to the user's terminal configuration.
    attributes[3] &= ~getattr(termios, "PENDIN", 0)
    return attributes


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("tmux"):
            if os.environ.get("TCAR_REQUIRE_INTEGRATION") == "1":
                raise AssertionError("tmux is required for release validation")
            raise unittest.SkipTest("tmux is not installed")
        with tempfile.TemporaryDirectory(prefix="tcar-test-", dir="/tmp") as directory:
            probe = socket.socket(socket.AF_UNIX)
            try:
                probe.bind(directory + "/probe")
            except OSError as error:
                if error.errno in (errno.EPERM, errno.EACCES):
                    if os.environ.get("TCAR_REQUIRE_INTEGRATION") == "1":
                        raise AssertionError("release validation requires live tmux tests") from error
                    raise unittest.SkipTest("execution sandbox blocks tmux's Unix sockets") from error
                raise
            finally:
                probe.close()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="tcar-test-", dir="/tmp")
        self.addCleanup(self.directory.cleanup)
        self.paths = [Path(self.directory.name) / f"input-{i}" for i in range(3)]
        machines = tuple(Machine(f"machine-{i}", local_command=(sys.executable, "-u", "-c", WORKER, f"machine-{i}", str(path)))
                         for i, path in enumerate(self.paths))
        self.backend = TmuxBackend(Config(machines))
        self.addCleanup(self.backend.close)

    def test_background_sessions_keep_running_and_reconnect_is_independent(self):
        self.backend.start(100, 30)
        for window in self.backend.windows:
            wait_for(lambda: "alive" in self.backend.run("capture-pane", "-p", "-t", window))
        pids = self.backend.run("list-panes", "-a", "-F", "#{pane_pid}").splitlines()
        before = self.backend.run("capture-pane", "-p", "-t", self.backend.windows[0])
        self.backend.select(1)
        time.sleep(.15)
        after = self.backend.run("capture-pane", "-p", "-t", self.backend.windows[0])
        self.assertNotEqual(before, after)
        self.assertEqual(pids, self.backend.run("list-panes", "-a", "-F", "#{pane_pid}").splitlines())
        self.backend.reconnect()
        new_pids = self.backend.run("list-panes", "-a", "-F", "#{pane_pid}").splitlines()
        self.assertEqual(pids[0], new_pids[0])
        self.assertNotEqual(pids[1], new_pids[1])
        self.assertEqual(pids[2], new_pids[2])

    def test_exited_command_keeps_its_window(self):
        self.backend.close()
        self.backend = TmuxBackend(Config((Machine("exited", local_command=(sys.executable, "-c", "print('done')")),)))
        self.addCleanup(self.backend.close)
        self.backend.start(100, 30)
        self.assertTrue(wait_for(lambda: self.backend.run("display-message", "-p", "-t", self.backend.windows[0], "#{pane_dead}") == "1"))
        self.assertIn("done", self.backend.run("capture-pane", "-p", "-t", self.backend.windows[0]))

    def test_single_local_session_can_rotate_without_exiting(self):
        self.backend.close()
        self.backend = TmuxBackend(Config((self.backend.config.machines[0],), status_bar=False))
        self.addCleanup(self.backend.close)
        self.backend.start(100, 30)
        self.backend.select(1)
        self.backend.select(-1)
        self.assertEqual(len(self.backend.run("list-windows", "-t", "tcar").splitlines()), 1)
        self.assertEqual(self.backend.run("show-options", "-gv", "status"), "off")

    def test_automatic_restart_stops_at_limit_and_manual_retry_resets(self):
        self.backend.close()
        counter = Path(self.directory.name) / "starts"
        script = "from pathlib import Path; p=Path(%r); p.write_text((p.read_text() if p.exists() else '')+'x')" % str(counter)
        machines = (Machine("crashing", local_command=(sys.executable, "-c", script)),
                    self.backend.config.machines[1])
        self.backend = TmuxBackend(Config(machines, status_bar=False, restart_on_exit=True, restart_delay=0))
        self.addCleanup(self.backend.close)
        self.backend.start(100, 30)
        window = self.backend.windows[0]
        healthy = self.backend.run("display-message", "-p", "-t", self.backend.windows[1], "#{pane_pid}")
        for index, now in enumerate((0, 1, 2), 1):
            wait_for(lambda: counter.exists() and counter.read_text() == "x" * index and
                     self.backend.run("display-message", "-p", "-t", window, "#{pane_dead}") == "1")
            self.backend.maintain(now)
        self.assertEqual(counter.read_text(), "xxx")  # Initial launch and two automatic retries.
        self.assertEqual(self.backend.run("display-message", "-p", "-t", window, "#{@tcar_failed}"), "1")
        self.assertEqual(self.backend.run("show-options", "-gv", "status"), "on")
        self.backend.maintain(100)
        self.assertEqual(counter.read_text(), "xxx")
        self.assertEqual(self.backend.run("display-message", "-p", "-t", self.backend.windows[1], "#{pane_pid}"), healthy)
        self.backend.reconnect()
        wait_for(lambda: counter.read_text() == "xxxx")
        self.backend.maintain(101)
        self.assertEqual(self.backend.run("display-message", "-p", "-t", window, "#{@tcar_failed}"), "0")
        self.assertEqual(self.backend.run("show-options", "-gv", "status"), "off")

    def test_bridge_input_order_prefix_rotation_resize_and_cleanup(self):
        self.backend.close()
        config = Path(self.directory.name) / "config.toml"
        # Serialize argv as JSON arrays, which are valid TOML string arrays here.
        import json
        config.write_text('[carousel]\nidle_timeout = 0.5\ninterval = 0.3\nauto_rotate = false\n' +
                          "".join(f'[[machines]]\nname = "{machine.name}"\nlocal_command = {json.dumps(machine.argv())}\n'
                                  for machine in self.backend.config.machines))
        socket_file = Path(self.directory.name) / "socket-path"
        code = ("from pathlib import Path; from tcar.app import Carousel; from tcar.config import load_config; "
                f"app=Carousel(load_config(Path({str(config)!r}))); "
                f"Path({str(socket_file)!r}).write_text(app.backend.socket); raise SystemExit(app.run())")
        master, slave = os.openpty()
        self.addCleanup(os.close, master)
        self.addCleanup(os.close, slave)
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 100, 0, 0))
        attributes = terminal_attributes(slave)
        env = os.environ.copy()
        env["TERM"] = "xterm-256color"
        process = subprocess.Popen([sys.executable, "-c", code], cwd=ROOT, env=env,
                                   stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
        self.addCleanup(self.stop_process, process)
        output = bytearray()

        def pump():
            while select.select([master], [], [], 0)[0]:
                output.extend(os.read(master, 65536))

        wait_for(lambda: socket_file.exists(), pump)
        server_socket = socket_file.read_text()

        def tmux(*args):
            return subprocess.check_output([shutil.which("tmux"), "-S", server_socket, *args], text=True).strip()

        wait_for(lambda: b"machine-0 alive" in output, pump)
        wait_for(lambda: all(path.exists() for path in self.paths), pump)
        os.write(master, b"a\x07\x1b[Cb")
        wait_for(lambda: self.paths[0].read_bytes() == b"a" and self.paths[1].read_bytes() == b"b", pump)
        os.write(master, b"\x07\x07\x07x\x1b[D")
        wait_for(lambda: self.paths[1].read_bytes() == b"b\x07\x07x\x1b[D", pump)
        # Prefix-looking bytes pasted into a program must stay in that program.
        os.write(master, b"\x1b[200~\x07q\x07\x1b[C\x1b[201~")
        wait_for(lambda: b"\x07q\x07\x1b[C" in self.paths[1].read_bytes(), pump)
        self.assertIsNone(process.poll())
        self.assertEqual(tmux("display-message", "-p", "-t", "tcar:", "#{window_name}"), "machine-1")
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
        os.kill(process.pid, signal.SIGWINCH)
        wait_for(lambda: tmux("display-message", "-p", "-t", "tcar:", "#{pane_width}x#{pane_height}") == "120x39", pump)
        os.write(master, b"\x07 ")
        wait_for(lambda: tmux("display-message", "-p", "-t", "tcar:", "#{window_name}") == "machine-2", pump)
        os.write(master, b"z")
        wait_for(lambda: self.paths[2].read_bytes() == b"z", pump)
        time.sleep(.15)
        pump()
        self.assertEqual(tmux("display-message", "-p", "-t", "tcar:", "#{window_name}"), "machine-2")
        os.write(master, b"\x07q")
        wait_for(lambda: process.poll() is not None, pump)
        self.assertEqual(process.returncode, 0, output.decode(errors="replace"))
        self.assertEqual(terminal_attributes(slave), attributes)
        self.assertFalse(Path(server_socket).exists())

    @staticmethod
    def stop_process(process):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)


if __name__ == "__main__":
    unittest.main()
