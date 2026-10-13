import hashlib
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import tempfile
import termios
import fcntl
import struct
import unittest
import zipfile

from tests.test_integration import ROOT, wait_for
from tcar import __version__


class DistributionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="tcar-release-", dir="/tmp")
        cls.addClassCleanup(cls.directory.cleanup)
        cls.dist = Path(cls.directory.name) / "dist"
        subprocess.run([sys.executable, str(ROOT / "scripts/build_release.py"), "--output-dir", str(cls.dist)], check=True, capture_output=True)
        cls.archive = cls.dist / "tcar.pyz"

    def run_app(self, *args, cwd=None):
        return subprocess.run([sys.executable, str(self.archive), *args], cwd=cwd or self.directory.name,
                              capture_output=True, text=True, timeout=5)

    def test_standalone_archive_version_and_contents(self):
        result = self.run_app("--version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), f"tcar {__version__}")
        with zipfile.ZipFile(self.archive) as package:
            self.assertIn("tcar/data/config.example.toml", package.namelist())
            self.assertFalse(any("__pycache__" in name for name in package.namelist()))
            self.assertIn("LICENSE", package.namelist())
        checksum = (self.dist / "SHA256SUMS").read_text().split()[0]
        self.assertEqual(checksum, hashlib.sha256(self.archive.read_bytes()).hexdigest())

    def test_generated_config_and_existing_file_protection(self):
        path = Path(self.directory.name) / "generated" / "config.toml"
        result = self.run_app("--init-config", str(path))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(path.read_bytes(), (ROOT / "config.example.toml").read_bytes())
        path.write_text("my custom configuration")
        result = self.run_app("--init-config", str(path))
        self.assertEqual(result.returncode, 1)
        self.assertIn("already exists", result.stderr)
        self.assertEqual(path.read_text(), "my custom configuration")

    def test_source_and_packaged_config_match(self):
        self.assertEqual((ROOT / "tcar/data/config.example.toml").read_bytes(), (ROOT / "config.example.toml").read_bytes())

    def test_demo_child_runs_from_archive_outside_checkout(self):
        master, slave = os.openpty()
        self.addCleanup(os.close, master)
        self.addCleanup(os.close, slave)
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 100, 0, 0))
        env = os.environ.copy()
        env["TERM"] = "xterm-256color"
        process = subprocess.Popen([sys.executable, str(self.archive), "--demo-machine", "release-demo"],
                                   cwd=self.directory.name, env=env, stdin=slave, stdout=slave, stderr=slave,
                                   start_new_session=True)
        self.addCleanup(self.stop_process, process)
        output = bytearray()

        def pump():
            while select.select([master], [], [], 0)[0]:
                output.extend(os.read(master, 65536))

        wait_for(lambda: b"release-demo" in output, pump)
        self.assertIsNone(process.poll(), output.decode(errors="replace"))

    def test_checkout_installer_with_spaces_in_prefix(self):
        prefix = Path(self.directory.name) / "install with spaces"
        result = subprocess.run(["sh", str(ROOT / "scripts/install.sh"), "--prefix", str(prefix), "--python", sys.executable],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        executable = prefix / "bin" / "tcar"
        result = subprocess.run([str(executable), "--version"], cwd=self.directory.name, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), f"tcar {__version__}")
        self.assertTrue((prefix / "share/tcar/tcar.pyz").exists())

    @staticmethod
    def stop_process(process):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
