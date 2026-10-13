# Changelog

## 1.1.0 — 2026-10-13

- Add per-machine `ssh_command` argument templates for bastion wrappers and
  custom SSH executables, with `{command}` and optional `{host}` placeholders.
- Allow wrappers that already know their destination to omit `host`.
- Preserve command arguments literally and reuse templates on manual and
  automatic restarts.

## 1.0.2 — 2026-10-13

- Make every manual restart (prefix + r by default) clear the active session's
  automatic restart counter and failure state, even before it reaches FAILED.
- Preserve automatic retry counts and other sessions' restart budgets.

## 1.0.1 — 2026-10-13

- Add configurable automatic restart for exited local commands and SSH sessions.
- Stop automatic retries and mark a session FAILED on the third restart attempt
  within a rolling minute, keeping other sessions running.
- Allow manual retry with prefix + r to clear the failure and restart budget.

## 1.0.0 — 2026-10-12

First release of **TermCarousel**, the `tcar` terminal carousel.

- Persistent local and SSH sessions in one full-screen terminal view.
- Configurable prefix keys, manual switching, idle rotation, and viewing intervals.
- Pause/resume rotation, forward literal prefixes, and restart the active session.
- Retained screens, exited-session indicators, resize handling, and terminal cleanup.
- Bracketed paste protection and common extended keyboard encodings.
- Local demo, configuration validation, and `--init-config` starter configuration.
- Python package, standalone zipapp, and a dependency-free checkout installer.
- Tests and automated release builds for macOS and Linux.

Requires Python 3.11+ and tmux locally. Remote machines only need SSH and the
command being run, such as btop or top.
