from pathlib import Path
import shlex
import tempfile
import unittest

from tcar.config import load_config


class ConfigTests(unittest.TestCase):
    def load(self, text):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text(text)
            return load_config(path)

    def test_example_contains_local_and_remote(self):
        config = load_config(Path(__file__).resolve().parents[1] / "config.example.toml")
        self.assertEqual(config.machines[0].argv(), ["btop"])
        self.assertIn("-tt", config.machines[1].argv())
        self.assertIn("ServerAliveInterval=15", config.machines[1].argv())

    def test_local_only_example(self):
        config = load_config(Path(__file__).resolve().parents[1] / "config.local.toml")
        self.assertEqual(len(config.machines), 1)
        self.assertEqual(config.machines[0].argv(), ["btop"])
        self.assertIsNone(config.machines[0].host)

    def test_defaults_and_per_machine_overrides(self):
        config = self.load('''
[defaults]
command = "top"
ssh_args = ["-p", "2222"]
[[machines]]
name = "one"
host = "me@one"
[[machines]]
name = "two"
host = "two"
command = "btop --utf-force"
ssh_args = []
''')
        self.assertEqual(config.machines[0].argv(), ["ssh", "-tt", "-p", "2222", "--", "me@one", "top"])
        self.assertEqual(config.machines[1].argv(), ["ssh", "-tt", "--", "two", "btop --utf-force"])

    def test_local_argv_quotes_shell_characters(self):
        config = self.load('''[[machines]]
name = "local"
local_command = ["printf", "%s", "$(touch /tmp/should-not-exist); hello"]
''')
        self.assertIn("'$(touch /tmp/should-not-exist); hello'", config.machines[0].shell_command())

    def test_custom_ssh_command_preserves_arguments_and_overrides_ssh_defaults(self):
        config = self.load('''
[defaults]
ssh_args = ["-p", "2222"]
[[machines]]
name = "bastion"
host = "me@internal"
command = 'printf "%s" "$HOME; {host} {command}"'
ssh_command = ["/path with spaces/bastion-ssh", "--via", "gateway", "{host}", "{command}"]
''')
        machine = config.machines[0]
        expected = ["/path with spaces/bastion-ssh", "--via", "gateway", "me@internal",
                    'printf "%s" "$HOME; {host} {command}"']
        self.assertEqual(machine.argv(), expected)
        self.assertEqual(shlex.split(machine.shell_command()), ["exec", *expected])

    def test_custom_ssh_command_without_host_and_with_embedded_placeholder(self):
        config = self.load('''
[defaults]
command = "btop --utf-force"
[[machines]]
name = "wrapped"
ssh_command = ["environment-ssh", "--command={command}", "${LITERAL}"]
[[machines]]
name = "normal"
host = "normal"
''')
        self.assertIsNone(config.machines[0].host)
        self.assertEqual(config.machines[0].argv(), ["environment-ssh", "--command=btop --utf-force", "${LITERAL}"])
        self.assertEqual(config.machines[1].argv(), ["ssh", "-tt", "-o", "ServerAliveInterval=15", "-o",
                                                   "ServerAliveCountMax=3", "--", "normal", "btop --utf-force"])

    def test_invalid_custom_ssh_commands(self):
        remote = '[[machines]]\nname = "wrapped"\n'
        for options in (
            'ssh_command = []', 'ssh_command = [" ", "{command}"]',
            'ssh_command = "wrapper {command}"', 'ssh_command = [1, "{command}"]',
            'ssh_command = ["wrapper"]', 'ssh_command = ["wrapper", "{cmd}"]',
            'ssh_command = ["wrapper", "{host}", "{command}"]',
            'ssh_command = ["wrapper", "{command}"]\nssh_args = []',
            'ssh_command = ["wrapper", "{command}"]\nlocal_command = ["btop"]',
        ):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.load(remote + options)

    def test_invalid_configurations(self):
        local = '[[machines]]\nname = "local"\nlocal_command = ["btop"]\n'
        cases = [
            '', 'machines = "bad"', 'carousel = []\n' + local,
            '[carousel]\ninterval = 0\n' + local,
            '[carousel]\ninterval = nan\n' + local,
            '[carousel]\nidle_timeout = -1\n' + local,
            '[carousel]\ninterval = true\n' + local,
            '[carousel]\nauto_rotate = "yes"\n' + local,
            '[carousel]\nrestart_on_exit = "yes"\n' + local,
            '[carousel]\nrestart_limit = 0\n' + local,
            '[carousel]\nrestart_limit = true\n' + local,
            '[carousel]\nrestart_window = 0\n' + local,
            '[carousel]\nrestart_delay = -1\n' + local,
            '[carousel]\nprefix = "Left"\n' + local,
            '[carousel]\nprefix = "Escape"\n' + local,
            '[carousel]\nintervall = 20\n' + local,
            '[bindings]\nnext = "Left"\n' + local,
            '[bindings]\nquit = "C-g"\n' + local,
            '[bindings]\nquit = "M-q"\n' + local,
            '[[machines]]\nname = "one"\n',
            local + 'host = "remote"\n', local + 'command = "top"\n',
            '[[machines]]\nname = "one"\nhost = "-bad"\n',
            '[[machines]]\nname = "one"\nhost = "me@host bad"\n',
            '[[machines]]\nname = "one"\nlocal_command = []\n',
            '[[machines]]\nname = "one"\nlocal_command = [1]\n',
            local + local,
        ]
        for text in cases:
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.load(text)
