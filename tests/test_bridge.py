"""Exercise the real PTY bridge with a local reader in place of the tmux client.

These run even when sockets are forbidden. Native tmux semantics are tested
separately in test_integration; this substitute only checks the bridge itself.
"""

import fcntl
import os
from pathlib import Path
import select
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest

from tests.test_integration import ROOT, terminal_attributes, wait_for


READER = '''
import os, select, sys, tty
tty.setraw(0)
os.write(1, b"reader-ready\\r\\n")
with open(sys.argv[1], "ab", buffering=0) as log:
    while True:
        size = os.get_terminal_size(0)
        os.write(1, f"size={size.columns}x{size.lines}\\r\\n".encode())
        if select.select([0], [], [], .05)[0]:
            data = os.read(0, 65536)
            if not data: break
            log.write(data)
            if data == b"exit23": sys.exit(23)
'''

SUBSTITUTE = '''
import os, sys
from pathlib import Path
from tcar.config import Config
import tcar.app as app
class LocalReaderBackend:
    def __init__(self, config):
        self.executable = sys.executable
        self.env = os.environ.copy()
    def start(self, columns, lines): pass
    def client_argv(self): return [sys.executable, "-u", "-c", READER, INPUT]
    def status(self, *args): pass
    def maintain(self, now): pass
    def select(self, delta): pass
    def action_keys(self, action): return b""
    def close(self): Path(CLOSED).write_text("closed")
app.TmuxBackend = LocalReaderBackend
raise SystemExit(app.Carousel(Config((), auto_rotate=False)).run())
'''


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="tcar-bridge-", dir="/tmp")
        self.addCleanup(self.directory.cleanup)
        self.input = Path(self.directory.name) / "input"
        self.closed = Path(self.directory.name) / "closed"
        self.master, self.slave = os.openpty()
        self.addCleanup(os.close, self.master)
        self.addCleanup(os.close, self.slave)
        fcntl.ioctl(self.slave, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 100, 0, 0))
        self.attributes = terminal_attributes(self.slave)
        code = f"READER={READER!r}\nINPUT={str(self.input)!r}\nCLOSED={str(self.closed)!r}\n" + SUBSTITUTE
        self.process = subprocess.Popen([sys.executable, "-c", code], cwd=ROOT,
                                        stdin=self.slave, stdout=self.slave, stderr=self.slave,
                                        start_new_session=True)
        self.addCleanup(self.stop)
        self.output = bytearray()
        wait_for(lambda: b"reader-ready" in self.output, self.pump)

    def pump(self):
        while select.select([self.master], [], [], 0)[0]:
            self.output.extend(os.read(self.master, 65536))

    def stop(self):
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait(timeout=3)

    def assert_clean_exit(self, expected_code=0):
        wait_for(lambda: self.process.poll() is not None, self.pump)
        self.pump()
        self.assertEqual(self.process.returncode, expected_code, self.output.decode(errors="replace"))
        self.assertTrue(self.closed.exists())
        self.assertEqual(terminal_attributes(self.slave), self.attributes)
        self.assertIn(b"\x1b[?1049l", self.output)

    def test_raw_input_and_prefix_quit_restore_terminal(self):
        data = "héllo".encode() + b"\x03\x04q\r\x1b[D"
        os.write(self.master, data)
        wait_for(lambda: self.input.exists() and self.input.read_bytes() == data, self.pump)
        self.assertIsNone(self.process.poll())
        os.write(self.master, b"\x07qshould-not-be-forwarded")
        self.assert_clean_exit()
        self.assertEqual(self.input.read_bytes(), data)

    def test_resize_and_external_termination_restore_terminal(self):
        fcntl.ioctl(self.slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
        os.kill(self.process.pid, signal.SIGWINCH)
        wait_for(lambda: b"size=120x40" in self.output, self.pump)
        self.process.terminate()
        self.assert_clean_exit()

    def test_terminal_client_failure_is_reported(self):
        os.write(self.master, b"exit23")
        self.assert_clean_exit(expected_code=23)
