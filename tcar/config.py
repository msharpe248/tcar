"""Strict, dependency-free TOML configuration."""

from dataclasses import dataclass, field
import math
import os
from pathlib import Path
import shlex
import tomllib

from .keys import key_sequences, prefix_sequence


DEFAULT_BINDINGS = {
    "previous": "Left", "next": "Right", "toggle_rotation": "Space",
    "reconnect": "r", "quit": "q",
}
DEFAULT_SSH_ARGS = ["-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3"]


@dataclass(frozen=True)
class Machine:
    name: str
    host: str | None = None
    command: str = "btop"
    ssh_args: tuple[str, ...] = ()
    local_command: tuple[str, ...] = ()

    def argv(self) -> list[str]:
        if self.host is None:
            return list(self.local_command)
        return ["ssh", "-tt", *self.ssh_args, "--", self.host, self.command]

    def shell_command(self) -> str:
        return "exec " + shlex.join(self.argv())


@dataclass(frozen=True)
class Config:
    machines: tuple[Machine, ...]
    prefix: str = "C-g"
    idle_timeout: float = 30
    interval: float = 20
    auto_rotate: bool = True
    status_bar: bool = True
    bindings: dict[str, str] = field(default_factory=lambda: DEFAULT_BINDINGS.copy())

    def input_bindings(self) -> dict[bytes, str]:
        prefix = prefix_sequence(self.prefix)
        result = {}
        for action, key in self.bindings.items():
            for sequence in key_sequences(key):
                if sequence == prefix:
                    raise ValueError(f"binding {action!r} conflicts with the double-prefix escape")
                if sequence in result:
                    raise ValueError(f"bindings {result[sequence]!r} and {action!r} use the same key")
                result[sequence] = action
        return result


def default_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "tcar" / "config.toml"


def _known(table: dict, allowed: set[str], label: str) -> None:
    unknown = table.keys() - allowed
    if unknown:
        raise ValueError(f"unknown {label} option(s): {', '.join(sorted(unknown))}")


def _string(value, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\0" in value:
        raise ValueError(f"{label} must be a nonempty string without NUL characters")
    return value


def _argv(value, label: str, nonempty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(x, str) or "\0" in x for x in value):
        raise ValueError(f"{label} must be an array of strings without NUL characters")
    if nonempty and (not value or not value[0].strip()):
        raise ValueError(f"{label} must contain an executable")
    return tuple(value)


def _duration(value, label: str, allow_zero: bool = False) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or (value == 0 and not allow_zero):
        raise ValueError(f"{label} must be a finite {'nonnegative' if allow_zero else 'positive'} number")
    return float(value)


def load_config(path: Path) -> Config:
    with path.open("rb") as source:
        data = tomllib.load(source)
    _known(data, {"carousel", "bindings", "defaults", "machines"}, "top-level")
    tables = {}
    for name in ("carousel", "bindings", "defaults"):
        table = data.get(name, {})
        if not isinstance(table, dict):
            raise ValueError(f"{name} must be a TOML table")
        tables[name] = table
    carousel, bindings, defaults = (tables[x] for x in ("carousel", "bindings", "defaults"))
    _known(carousel, {"prefix", "idle_timeout", "interval", "auto_rotate", "status_bar"}, "carousel")
    _known(bindings, set(DEFAULT_BINDINGS), "bindings")
    _known(defaults, {"command", "ssh_args"}, "defaults")
    prefix = _string(carousel.get("prefix", "C-g"), "carousel.prefix")
    prefix_sequence(prefix)
    for option in ("auto_rotate", "status_bar"):
        if option in carousel and type(carousel[option]) is not bool:
            raise ValueError(f"carousel.{option} must be true or false")
    configured_bindings = {**DEFAULT_BINDINGS, **bindings}
    for action, key in configured_bindings.items():
        key_sequences(_string(key, f"bindings.{action}"))
    command = _string(defaults.get("command", "btop"), "defaults.command")
    ssh_args = _argv(defaults.get("ssh_args", DEFAULT_SSH_ARGS), "defaults.ssh_args")
    records = data.get("machines", [])
    if not isinstance(records, list) or not records:
        raise ValueError("configure at least one [[machines]] entry")
    machines = []
    names = set()
    for index, record in enumerate(records, 1):
        label = f"machines[{index}]"
        if not isinstance(record, dict):
            raise ValueError(f"{label} must be a TOML table")
        _known(record, {"name", "host", "command", "ssh_args", "local_command"}, label)
        name = _string(record.get("name"), f"{label}.name")
        if any(ord(c) < 32 or ord(c) == 127 for c in name) or name in names:
            raise ValueError(f"{label}.name must be unique and contain no control characters")
        names.add(name)
        if ("host" in record) == ("local_command" in record):
            raise ValueError(f"{label} must specify exactly one of host or local_command")
        if "local_command" in record:
            if "command" in record or "ssh_args" in record:
                raise ValueError(f"{label}: command and ssh_args are only valid for SSH machines")
            machines.append(Machine(name, local_command=_argv(record["local_command"], f"{label}.local_command", True)))
        else:
            host = _string(record["host"], f"{label}.host")
            if host.startswith("-") or any(c.isspace() for c in host):
                raise ValueError(f"{label}.host must be an SSH alias or user@hostname")
            machines.append(Machine(name, host, _string(record.get("command", command), f"{label}.command"),
                                    _argv(record.get("ssh_args", list(ssh_args)), f"{label}.ssh_args")))
    config = Config(tuple(machines), prefix,
                    _duration(carousel.get("idle_timeout", 30), "carousel.idle_timeout", True),
                    _duration(carousel.get("interval", 20), "carousel.interval"),
                    carousel.get("auto_rotate", True), carousel.get("status_bar", True), configured_bindings)
    config.input_bindings()
    return config
