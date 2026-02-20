# Claude Gauge — Project Notes

## Project Purpose
Real-time PySide6 desktop app showing Claude Code subscription usage via two retro analog gauges (5h window, 7-day period) and a humorous mood panel.

## Quick Commands
```bash
./run start    # Launch the GUI app
./run test     # Run 50 unit tests (no GUI required)
./run lint     # Run ruff
```

## File Structure
```
src/
  data_access.py       # OAuth credentials, token refresh, API polling, header parsing
  data_access_test.py  # 52 unit tests for data layer
  gauge_widget.py      # QPainter analog gauge widget
  app_display.py       # Main PySide6 window (MainWindow, ScorePanel)
assets/
  icon.png             # App icon 256x256, transparent bg (preferred over icon.jpg)
  states/
    state_01..10.png   # 400x200 transparent-bg PNGs (preferred over .jpg fallbacks)
```

## OAuth Token Authentication (IMPORTANT)
- Credentials at `~/.claude/.credentials.json` → `claudeAiOauth.accessToken` (sk-ant-oat01-...)
- The API requires `anthropic-beta: oauth-2025-04-20` header for OAuth tokens to work with `/v1/messages`
- **Token refresh endpoint**: `POST https://platform.claude.com/v1/oauth/token` with JSON body:
  ```json
  {"grant_type": "refresh_token", "refresh_token": "<rt>", "client_id": "9d1c250a-e61b-44d9-88ed-5944d1962f5e"}
  ```
- Refresh returns `{access_token, refresh_token, expires_in}` — update all three in credentials file
- DO NOT use `strings <binary>` to discover endpoints — output is 1MB+, use `grep -ao 'pattern' binary`

## Rate Limit Headers (Confirmed)
All confirmed by real API call. Resets are **Unix epoch integers** (not ISO 8601):
- `anthropic-ratelimit-unified-5h-utilization` → 5h used % (0.0-1.0 fraction)
- `anthropic-ratelimit-unified-5h-reset` → Unix epoch seconds
- `anthropic-ratelimit-unified-7d-utilization` → 7-day used % (NOT `1w`)
- `anthropic-ratelimit-unified-7d-reset` → Unix epoch seconds
- Also: `overage-*` headers for overage usage

If utilization value is 0.0–1.0, it's treated as fraction (multiplied ×100). If >1.0, treated as direct percentage.

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
- 52 tests in `data_access_test.py` — all pass without network/GUI access
- Test `test_days_and_hours` uses loose "h" assertion (not exact hours) due to execution timing drift
- GUI not tested (no headless PySide6 setup)

## Window & Daemon
- Window position persisted to `~/.claude/claude-gauge-prefs.json` via moveEvent
- Registered under `auto` daemon: auto-starts at login, auto-restarts on crash
