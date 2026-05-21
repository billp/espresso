# Changelog

## [0.0.15] - 2026-05-21

### Fixed
- Piped install: use bash `VERSION` variable instead of grepping `$0`
- Version check when script is piped through bash
- Install URL updated to point to main branch

## [0.0.1] - 2026-05-20

### Added
- Initial release
- Background daemon using CoreGraphics via ctypes — no third-party dependencies
- Interactive TUI with start/stop, interval config, and lock-screen-only mode
- Imperceptible ±5px mouse jitter that restores cursor to original position
- One-line curl installer to `~/.local/bin/espresso`
- Auto-restart daemon on option change
