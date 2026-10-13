# TermCarousel (`tcar`)

[![Tests](https://github.com/msharpe248/tcar/actions/workflows/release.yml/badge.svg)](https://github.com/msharpe248/tcar/actions/workflows/release.yml)

A full-screen terminal carousel for local commands and persistent SSH sessions.
Run `btop` on your laptop and several servers in one Ghostty pane, switch between
them, or let tcar rotate after you stop typing. Every session keeps running while
hidden; each retains its own screen and process.

## Install

Requires **Python 3.11+** and **tmux** on your local machine. On macOS, install
tmux with `brew install tmux`; on Linux, use your distribution's package manager.
Remote machines need SSH and the command you want to run. They do not need tmux,
Python, or tcar.

Install version 1.0.1 with pipx:

```sh
pipx install https://github.com/msharpe248/tcar/releases/download/v1.0.1/tcar-1.0.1-py3-none-any.whl
tcar --demo
```

Or download the single-file executable from the
[release page](https://github.com/msharpe248/tcar/releases/latest). It needs no
Python package dependencies or virtual environment:

```sh
mkdir -p ~/.local/bin
curl -fL https://github.com/msharpe248/tcar/releases/download/v1.0.1/tcar.pyz -o ~/.local/bin/tcar
chmod +x ~/.local/bin/tcar
~/.local/bin/tcar --demo
```

Add `~/.local/bin` to PATH if needed. The standalone executable runs with
`python3` from PATH, which must be Python 3.11 or newer. `SHA256SUMS` is included
with each release so you can verify the downloaded files.

From a checkout, the installer can select a specific Python interpreter and
handles installation paths containing spaces:

```sh
git clone https://github.com/msharpe248/tcar.git
cd tcar
sh scripts/install.sh
# Optional: sh scripts/install.sh --prefix "$HOME/.local" --python python3.13
```

It installs the command in `~/.local/bin/tcar` and the application in
`~/.local/share/tcar/tcar.pyz`. It does not install system packages or modify
your shell configuration.

## Run

Create a starter config, replace the SSH aliases with your own, and launch:

```sh
tcar --init-config
tcar --check
tcar
```

`--init-config` never overwrites an existing configuration. An optional path is
accepted: `tcar --init-config ./my-machines.toml`.

Try it without connecting to any remote machines:

```sh
python3 -m tcar --demo
```

The demo runs three independent local dashboards, starts rotating after 5 seconds
without input, and shows each for 4 seconds. Type something to see which session
receives it.

To run your actual local `btop` without SSH:

```sh
python3 -m tcar -c config.local.toml
```

Copy [config.example.toml](config.example.toml), replace the server aliases with
your own, then validate and launch it:

```sh
python3 -m tcar --check -c config.example.toml
python3 -m tcar -c config.example.toml
```

`--check` validates the configuration and checks that tmux is installed. It does
not connect to hosts or check whether remote commands are installed.

For a `tcar` command available outside this directory, install into a virtual
environment (or use `pipx install .`):

```sh
python3 -m venv .venv
.venv/bin/pip install .
.venv/bin/tcar --demo
```

The default configuration path is `$XDG_CONFIG_HOME/tcar/config.toml`, or
`~/.config/tcar/config.toml` when `XDG_CONFIG_HOME` is unset.

## Keys

Press and release **Ctrl+G**, then the action key:

| Key after prefix | Action |
| --- | --- |
| Left / Right | Previous / next machine, wrapping around |
| Space | Pause / resume automatic rotation |
| r | Restart the active command or SSH connection |
| q | Quit tcar and close all its sessions |
| Ctrl+G again | Send a literal Ctrl+G to the active program |

All ordinary keys go to the active program, including bare arrows and Ctrl+C.
An unrecognized prefix combination forwards both keys. The prefix waits until
you press another key; the status bar indicates that it is waiting. Bracketed
paste is forwarded as paste, so pasted prefix combinations cannot switch machines
or quit tcar.

Typing pauses rotation and restarts the inactivity timer. Once the inactivity
timeout expires, tcar switches to the next machine, then advances every viewing
interval. Output from monitoring programs does not count as activity. Manual
switches give the selected machine at least one full viewing interval. Explicitly
pausing with prefix + Space stays paused until you resume; resuming gives the
current machine a full interval before switching.

## Configuration

```toml
[carousel]
prefix = "C-g"
idle_timeout = 30
interval = 20
auto_rotate = true
status_bar = true
restart_on_exit = false
restart_limit = 3
restart_window = 60
restart_delay = 1

[bindings]
previous = "Left"
next = "Right"
toggle_rotation = "Space"
reconnect = "r"
quit = "q"

[defaults]
command = "btop"
ssh_args = ["-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3"]

[[machines]]
name = "laptop"
local_command = ["btop"]

[[machines]]
name = "fileserver"
host = "fileserver"

[[machines]]
name = "build"
host = "me@build.example.com"
command = "top"
```

Each machine specifies `host` (optionally with `ssh_command`), `ssh_command`, or
`local_command`. Local commands
are argument arrays, so shell characters are passed literally. To explicitly run
a local shell pipeline, use `local_command = ["sh", "-lc", "your pipeline"]`.
Remote `command` is a shell command interpreted by the SSH server, as with
ordinary `ssh host 'command'`.

SSH uses your usual `~/.ssh/config`, authorized keys, agent, proxy settings, and
host-key checks. Sessions request a remote PTY with `ssh -tt`. Per-machine
`ssh_args` replaces the defaults; include the keepalive options if you override
it and still want keepalives. Authentication prompts remain interactive in each
machine's view.

To use a bastion wrapper or a different SSH executable, set `ssh_command` on
that machine:

```toml
[[machines]]
name = "production"
host = "me@internal-server"
command = "btop --utf-force"
ssh_command = ["/usr/local/bin/bastion-ssh", "{host}", "{command}"]
```

`ssh_command` is the complete argument array to execute locally. `{command}`
is required and is replaced with the remote `command`; `{host}` is optional and
is replaced with `host`. Omit `host` when the wrapper already knows its target.
Placeholders can also appear within arguments, such as `"--command={command}"`.
Replacement text stays in its argument, including spaces and shell characters;
it is not split or expanded by a local shell. Only `{host}` and `{command}` are
substituted. Other text is passed literally.

The template replaces the standard `ssh -tt ...` invocation, including the
default `ssh_args`. Include any PTY, keepalive, port, or bastion options your
wrapper needs in the template itself; `ssh_args` cannot be set alongside it on
the same machine. Manual and automatic restarts run the same template again.

Bindings accept ASCII characters, `C-a` through `C-z` and ASCII control keys,
`Left`, `Right`, `Up`, `Down`, `Home`, `End`, `PageUp`, `PageDown`, `Space`, `Tab`,
`Enter`, `Escape`, and `Backspace`. The prefix must represent a single ASCII or
control character; Escape and arrow keys cannot serve as the prefix. Bindings
must be distinct and cannot reuse the prefix because double prefix sends it
literally. Unknown configuration keys are errors to catch typos.
Common CSI-u and xterm modifyOtherKeys encodings of ASCII prefix and binding
keys are also recognized, while ordinary encoded keys are forwarded intact.

`status_bar = false` hides the one-line bar and gives all rows to the program.
`auto_rotate = false` starts with rotation paused. `idle_timeout = 0` starts
automatic rotation immediately; `interval` must be positive. Durations can be
fractional seconds.

## Sessions and terminal behavior

tcar starts a private tmux server with a private socket and never loads your
personal tmux configuration. tmux supplies PTYs, terminal emulation, resize
handling, color, Unicode, cursor modes, and separate retained screens. Manual
switches travel in the same input stream as ordinary keys so a burst of typing
around a switch reaches the appropriate machine in order.

Set `restart_on_exit = true` to restart exited local commands and SSH sessions.
The defaults wait one second before retrying and allow two automatic restarts.
On the third restart attempt within a rolling 60 seconds, that session is marked
**FAILED** and automatic retries stop. Other sessions keep running. The failure
status is displayed even if you normally hide the status bar. `restart_limit`,
`restart_window`, and `restart_delay` configure this policy.

Use prefix + r to restart the active command or SSH session. Every manual restart
clears that session's automatic restart counter and failure state, including when
the command is still running or has not reached the limit. With automatic restarts
disabled, an exited session waits for this manual action. The `reconnect` binding
configures the restart key.
Quitting tcar closes all
its connections and local commands. Normal exit and handled termination signals
restore the terminal and clean up the private server.

This implementation uses tmux's terminal protocols. It supports conventional
interactive terminal programs such as btop, top, shells, and editors; graphics
and protocols outside tmux's support are subject to tmux's limitations. If tcar
is itself run inside another multiplexer, choose a prefix that the outer
multiplexer passes through.

[libghostty-vt](https://github.com/ghostty-org/ghostty#cross-platform-libghostty-for-embeddable-terminals)
was considered as an alternative terminal engine. Its C API is still evolving;
this version uses tmux to avoid requiring a native library build and a custom
screen renderer.

## Tests

```sh
python3 -m unittest discover -v
```

The suite tests fragmented key sequences, literal prefix forwarding, unknown
chords, paste protection, timing, and configuration. PTY bridge tests also verify
input, resizing, terminal restoration, termination signals, and client errors
using a local reader in place of the tmux client. Integration tests start
actual tmux sessions and a PTY client to verify retained screens, input routing
around switches, reconnection, exited programs, rotation, resizing, and terminal
cleanup. They skip explicitly when tmux is missing or a sandbox prohibits Unix
sockets. Run them in your normal terminal to exercise the live backend.

CI runs the complete suite on macOS and Linux with Python 3.11 and 3.14. Live
tmux tests are required in CI. A version tag, such as `v1.0.1`, publishes a
GitHub release only after the tests and package builds pass. Releases include
a wheel, source distribution, standalone executable, and SHA-256 checksums.

## License

MIT. See [LICENSE](LICENSE).
