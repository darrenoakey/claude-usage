# Claude Gauge — Project Notes

## Project Purpose
Real-time PySide6 desktop app showing Claude Code subscription usage via two retro analog gauges (5h window, 7-day period) and a humorous mood panel.

## Quick Commands
```bash
./run start    # Launch the GUI app
./run test     # Run unit tests (no GUI required)
./run lint     # Run ruff
```

## File Structure
```
src/
  data_access.py       # Tmux-based /usage scraping, text parsing, score calculation
  data_access_test.py  # unit tests for data layer (no GUI/network required)
  gauge_widget.py      # QPainter analog gauge widget
  app_display.py       # Main PySide6 window (MainWindow, ScorePanel)
assets/
  icon.png             # App icon 256x256, transparent bg (preferred over icon.jpg)
  states/
    state_01..10.png   # 400x200 transparent-bg PNGs (preferred over .jpg fallbacks)
```

## Data Collection Architecture
- Runs an interactive `claude` CLI session in a dedicated tmux pane (`claude-usage-poll`)
- Periodically sends `/usage` slash command, captures the TUI dialog output, then dismisses with Escape
- Parses the text output for usage percentages and reset times
- No direct API calls, no OAuth tokens, no `requests` dependency
- Requires `tmux` installed (`brew install tmux`)
- `CLAUDECODE` env var must be unset in the tmux session to avoid nested-session errors

## /usage Dialog Format (captured from real CLI)
```
  Current session
  ██                                                 4% used
  Resets 10pm (Australia/Sydney)

  Current week (all models)
  ██████████████                                     28% used
  Resets Mar 6 at 2pm (Australia/Sydney)

  Current week (Sonnet only)
  ██                                                 4% used
  Resets Mar 6 at 5pm (Australia/Sydney)
```
- "Current session" → 5h window gauge
- "Current week (all models)" → 7-day period gauge
- Reset times are human-readable with timezone in parens (e.g., "10pm", "1:59pm", "Mar 6 at 2:45pm")

## Score System
- `score = used_pct - elapsed_pct` using **7-day period only** (5h window ignored for score)
- Negative = over budget (bad), Positive = under budget (good)
- Display is negated: `display_score = -score`, shown as "Ahead: X%" or "Behind: X%"
- Maps to state 1-10 via `STATE_BOUNDARIES` in data_access.py (state 1 = best, 10 = worst)
- State 6 = zen perfect balance (internal score -2 to +2)

## Screen Sleep Detection
- `MainWindow._setup_screen_sleep_detection()` registers NSWorkspace notifications via PyObjC
- Requires `pyobjc-framework-Cocoa` in venv (installed)
- Polls are skipped while `_screens_sleeping=True`; catch-up poll fires 2s after wake
- Gracefully degrades if AppKit unavailable (just logs a warning)

## Testing Notes
- Tests in `data_access_test.py` — all pass without network/GUI/tmux access
- Test `test_days_and_hours` uses loose "h" assertion (not exact hours) due to execution timing drift
- GUI not tested (no headless PySide6 setup)

## Tmux Liveness Detection
- `_is_claude_alive()` checks only the last 15 lines of the pane (NOT deep scrollback)
- The `❯` character is Claude CLI's TUI prompt — distinct from shell prompts (e.g., `src/foo >`)
- Deep scrollback (`-S -80`) retains stale "Claude Code" banners after Claude exits → false positives
- `_capture_pane()` (full 80-line scrollback) is for /usage dialog content only

## Window & Daemon
- Window position persisted to `~/.claude/claude-gauge-prefs.json` via moveEvent
- Registered under `auto` daemon: auto-starts at login, auto-restarts on crash
