# Contributing

## Setup

```bash
git clone https://github.com/billp/espresso.git
cd espresso
```

## Project structure

- `mmctl/mm.py` — background daemon (CoreGraphics via ctypes)
- `mmctl/mmctl.py` — interactive TUI manager
- `build.py` — bumps version and regenerates `install.sh`
- `install.sh` — generated installer (do not edit by hand)

## Making changes

1. Edit `mmctl/mm.py` or `mmctl/mmctl.py`
2. Regenerate and reinstall:
   ```bash
   python3 build.py
   bash install.sh
   ```
3. Test by running `espresso` in a new terminal

## Submitting a PR

- Keep changes focused — one fix or feature per PR
- Include a short description of what changed and why
- Make sure `python3 -m py_compile mmctl/mm.py mmctl/mmctl.py` passes
