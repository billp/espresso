# espresso

```
 _____ _____ _____ _____ _____ _____ _____ _____
|   __|   __|  _  | __  |   __|   __|   __|     |
|   __|__   |   __|    -|   __|__   |__   |  |  |
|_____|_____|__|  |__|__|_____|_____|_____|_____|
```

[![CI](https://github.com/billp/espresso/actions/workflows/ci.yml/badge.svg?branch=develop)](https://github.com/billp/espresso/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Platform: macOS](https://img.shields.io/badge/platform-macOS-lightgrey)
![Python 3](https://img.shields.io/badge/python-3-blue)

A macOS mouse mover that prevents your screen from sleeping. Runs silently in the background and is managed through an interactive terminal UI.

Unlike `caffeinate`, espresso gives you a live TUI to start/stop the daemon, tune the nudge interval, and enable a **lock-screen-only** mode — all without leaving the terminal.

## Requirements

- macOS
- Python 3 (no third-party packages)

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/billp/espresso/refs/heads/develop/install.sh | bash
```

This creates `~/.local/bin/espresso`. If that directory isn't in your `PATH`, add it:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

## Usage

```bash
espresso
```

Navigate with `↑ ↓`, select with `Enter`, quit with `q`.

```
  Status    ○ NOT RUNNING

  ┌──────────────────────────────────────────────┐
  │  › ▶ Start                                   │
  │    ✕ Quit                                    │
  └──────────────────────────────────────────────┘

  options
  ┌──────────────────────────────────────────────┐
  │    [12]  Interval (seconds)                  │
  │    [ ]   Lock screen only                    │
  └──────────────────────────────────────────────┘
```

**Options**

| Option | Default | Description |
|---|---|---|
| Interval | 12 sec | How often the mouse nudges |
| Lock screen only | off | Only move the mouse when the screen is locked |

When the daemon is running, changing either option restarts it automatically in the background.

## How it works

The daemon moves the mouse ±5px in a small random jitter pattern and then restores it to the original position. The movement is imperceptible during normal use.

## Development

Source files live in `mmctl/`:

- `mmctl/mm.py` — background daemon (CoreGraphics via ctypes)
- `mmctl/mmctl.py` — interactive TUI manager

After editing either file, regenerate and reinstall:

```bash
python3 build.py   # bumps version, regenerates install.sh
bash install.sh    # installs to ~/.local/bin/espresso
```

---

If espresso is useful to you, consider giving it a ⭐ on GitHub — it helps others find it.
