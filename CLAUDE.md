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
  data_access.py       # agentd /v1/subscription-usage client and snapshot parsing
  data_access_test.py  # data-layer tests using captured payloads and a real local HTTP server
  ui_fonts.py          # shared installed monospace font helpers for Qt widgets/painting
  ui_fonts_test.py     # font helper tests
  gauge_widget.py      # QPainter analog gauge widget
  app_display.py       # Main PySide6 window (MainWindow, provider cards, combined panel)
assets/
  icon.png             # App icon 256x256, transparent bg (preferred over icon.jpg)
  states/
    state_01..10.png   # 400x200 transparent-bg PNGs (preferred over .jpg fallbacks)
```

## Data Collection Architecture
- This app does not poll Claude/Codex/ZAI itself. It is a native dock client for
  `agentd` and GETs `http://127.0.0.1:8420/v1/subscription-usage`.
- `agentd` is the single authoritative usage poller. Restart `agentd` to force
  a backend refresh, then restart the `agentd-gauge` auto service to force the
  UI's immediate first fetch.
- The UI refreshes every 60 seconds and also fetches once shortly after startup.
- A transient `agentd` outage is reported as an offline UI state; no local
  fallback polling or fabricated values are used.

## Score System
- Scores and state indexes come from `agentd`'s combined snapshot.
- `app_display.py` negates the combined score for display: negative backend
  scores are under budget and show as "Ahead: X%".
- State 6 = zen perfect balance (internal score -2 to +2)

## Testing Notes
- `./run test` covers `data_access.py` with captured payload parsing and a real
  loopback HTTP server; it covers `ui_fonts.py` without launching the GUI.
- `./run lint` runs ruff.
- A clean `auto -q restart agentd-gauge` log is part of runtime verification
  because Qt warnings indicate visible/runtime quality issues.

## Window & Daemon
- Registered under `auto` as `agentd-gauge`.
- Canonical command: `sh -lc 'cd /Users/darrenoakey/src/claude-usage && exec ./run start'`.
- The retired Gio binary path is `/Users/darrenoakey/src/agentd-gauge`; if a
  stale process from that path is still running, kill it and start `agentd-gauge`
  through `auto` so the active UI is the PySide6 client.
