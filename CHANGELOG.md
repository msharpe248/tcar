# Changelog

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
