"""Data access layer: tmux-based /usage scraping from Claude CLI."""
from __future__ import annotations

import logging
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

TMUX_SESSION = "claude-usage-poll"
TMUX_PANE_WIDTH = 200
TMUX_PANE_HEIGHT = 50
MAX_CONSECUTIVE_FAILURES = 2  # Restart session after this many failed polls

# Score boundaries for state index (score = used_pct - elapsed_pct)
STATE_BOUNDARIES = [
    (-30, 1),   # score <= -30 → state 1 (hammock)
    (-20, 2),   # -30 < score <= -20 → state 2
    (-10, 3),   # -20 < score <= -10 → state 3
    (-5, 4),    # -10 < score <= -5 → state 4
    (-2, 5),    # -5 < score <= -2 → state 5
    (2, 6),     # -2 < score <= 2 → state 6 (zen)
    (10, 7),    # 2 < score <= 10 → state 7
    (20, 8),    # 10 < score <= 20 → state 8
    (30, 9),    # 20 < score <= 30 → state 9
]
# score > 30 → state 10


@dataclass
class GaugeData:
    used_pct: float = 0.0        # 0-100, from utilization
    elapsed_pct: float = 0.0    # 0-100, computed from reset timestamp
    resets_at: Optional[datetime] = None
    window_seconds: float = 0.0


@dataclass
class UsageData:
    window_5h: GaugeData = field(default_factory=GaugeData)
    period_7d: GaugeData = field(default_factory=GaugeData)
    score: float = 0.0           # used_pct - elapsed_pct; negative = good
    state_index: int = 6         # 1-10
    last_updated: Optional[datetime] = None
    raw_headers: dict = field(default_factory=dict)
    error: Optional[str] = None


def _compute_elapsed_pct(resets_at: datetime, window_seconds: float) -> float:
    """Compute what fraction of the window has elapsed (0-100)."""
    if window_seconds <= 0:
        return 0.0
    now = datetime.now(timezone.utc)
    reset_utc = resets_at.astimezone(timezone.utc)
    # resets_at is the END of the current window
    window_start = reset_utc - timedelta(seconds=window_seconds)
    elapsed = (now - window_start).total_seconds()
    pct = (elapsed / window_seconds) * 100.0
    return max(0.0, min(100.0, pct))


def _score_to_state(score: float) -> int:
    """Map a score value to a state index 1-10."""
    for threshold, state in STATE_BOUNDARIES:
        if score <= threshold:
            return state
    return 10


def format_time_remaining(resets_at: Optional[datetime]) -> str:
    """Format time until reset as human-readable string."""
    if resets_at is None:
        return "Unknown"
    now = datetime.now(timezone.utc)
    delta = resets_at.astimezone(timezone.utc) - now
    total_secs = int(delta.total_seconds())
    if total_secs <= 0:
        return "Resetting..."
    days = total_secs // 86400
    hours = (total_secs % 86400) // 3600
    minutes = (total_secs % 3600) // 60
    if days > 0:
        return f"{days}d {hours}h"
    elif hours > 0:
        return f"{hours}h {minutes}m"
    else:
        return f"{minutes}m"


# ---------------------------------------------------------------------------
# Reset time parsing
# ---------------------------------------------------------------------------

def _parse_reset_time(text: str) -> Optional[datetime]:
    """Parse a reset time string from /usage output into an aware datetime.

    Formats observed:
    - "10pm (Australia/Sydney)"            → today at 22:00 in that tz
    - "10am (Australia/Sydney)"            → today at 10:00 in that tz
    - "Mar 6 at 2pm (Australia/Sydney)"    → March 6 at 14:00 in that tz
    - "Mar 6 at 10am (Australia/Sydney)"   → March 6 at 10:00 in that tz
    """
    text = text.strip()

    # Extract timezone from parentheses
    tz_match = re.search(r'\(([^)]+)\)', text)
    if not tz_match:
        return None
    tz_name = tz_match.group(1)
    try:
        tz = ZoneInfo(tz_name)
    except (KeyError, ValueError):
        log.warning("Unknown timezone: %s", tz_name)
        return None

    # Strip the timezone part for time parsing
    time_part = text[:tz_match.start()].strip()

    # Parse time component (e.g., "2pm", "10am", "1:59pm", "12:30am")
    time_match = re.search(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)', time_part, re.IGNORECASE)
    if not time_match:
        return None
    hour = int(time_match.group(1))
    minute = int(time_match.group(2)) if time_match.group(2) else 0
    ampm = time_match.group(3).lower()
    if ampm == 'pm' and hour != 12:
        hour += 12
    elif ampm == 'am' and hour == 12:
        hour = 0

    now_local = datetime.now(tz)

    # Check for date component (e.g., "Mar 6 at")
    date_match = re.match(r'(\w{3})\s+(\d{1,2})\s+at\s+', time_part)
    if date_match:
        month_str = date_match.group(1)
        day = int(date_match.group(2))
        # Parse month abbreviation
        month_map = {
            'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
            'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12,
        }
        month = month_map.get(month_str)
        if month is None:
            return None
        # Use current year, but handle year boundary
        year = now_local.year
        try:
            dt = datetime(year, month, day, hour, minute, 0, tzinfo=tz)
        except ValueError:
            return None
        # If the date is far in the past, it's probably next year
        if dt < now_local - timedelta(days=30):
            dt = dt.replace(year=year + 1)
        return dt
    else:
        # Time only — assume today, but if already passed, assume tomorrow
        dt = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if dt < now_local:
            dt += timedelta(days=1)
        return dt


# ---------------------------------------------------------------------------
# /usage text parsing
# ---------------------------------------------------------------------------

def _strip_ansi(text: str) -> str:
    """Strip ANSI escape codes and unicode box-drawing/block chars."""
    text = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)
    # Remove block characters (█ etc) but keep normal text
    text = re.sub(r'[█▏▎▍▌▋▊▉░▒▓]+', '', text)
    return text


def _parse_usage_text(text: str) -> UsageData:
    """Parse the captured /usage dialog text into UsageData.

    Expected sections:
      Current session         → 5h window
      Current week (all models) → 7d period
    """
    data = UsageData(last_updated=datetime.now(timezone.utc))
    clean = _strip_ansi(text)

    # Split into sections by looking for "Current session" and "Current week"
    # Each section has: title line, progress bar + "X% used", "Resets ..." line
    sections = re.split(r'(?=Current session|Current week)', clean)

    for section in sections:
        section = section.strip()
        if not section:
            continue

        # Extract percentage
        pct_match = re.search(r'(\d+)%\s*used', section)
        used_pct = float(pct_match.group(1)) if pct_match else 0.0

        # Extract reset time
        reset_match = re.search(r'Resets\s+(.+?)(?:\n|$)', section)
        resets_at = _parse_reset_time(reset_match.group(1)) if reset_match else None

        if section.startswith('Current session'):
            data.window_5h.used_pct = used_pct
            data.window_5h.resets_at = resets_at
            data.window_5h.window_seconds = 5 * 3600
            if resets_at:
                data.window_5h.elapsed_pct = _compute_elapsed_pct(resets_at, 5 * 3600)

        elif 'all models' in section:
            data.period_7d.used_pct = used_pct
            data.period_7d.resets_at = resets_at
            data.period_7d.window_seconds = 7 * 24 * 3600
            if resets_at:
                data.period_7d.elapsed_pct = _compute_elapsed_pct(resets_at, 7 * 24 * 3600)

    # Score calculation (7-day period only)
    if data.period_7d.used_pct > 0 or data.period_7d.elapsed_pct > 0:
        data.score = data.period_7d.used_pct - data.period_7d.elapsed_pct
    elif data.window_5h.used_pct > 0 or data.window_5h.elapsed_pct > 0:
        data.score = data.window_5h.used_pct - data.window_5h.elapsed_pct
    else:
        data.score = 0.0

    data.state_index = _score_to_state(data.score)
    return data


# ---------------------------------------------------------------------------
# Tmux session management
# ---------------------------------------------------------------------------

def _run_tmux(*args: str, timeout: int = 10) -> str:
    """Run a tmux command and return stdout."""
    cmd = ["tmux"] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result.stdout


def _tmux_session_exists() -> bool:
    """Check if our dedicated tmux session exists."""
    result = subprocess.run(
        ["tmux", "has-session", "-t", TMUX_SESSION],
        capture_output=True, timeout=5,
    )
    return result.returncode == 0


def _capture_pane() -> str:
    """Capture the current tmux pane content."""
    return _run_tmux("capture-pane", "-t", TMUX_SESSION, "-p", "-S", "-80")


def _capture_pane_tail(lines: int = 10) -> str:
    """Capture just the last N visible lines of the tmux pane."""
    return _run_tmux("capture-pane", "-t", TMUX_SESSION, "-p", "-S", f"-{lines}")


def _is_claude_alive() -> bool:
    """Check if claude CLI is running and responsive in the tmux session."""
    if not _tmux_session_exists():
        return False
    # Only check recent lines — deep scrollback has stale "Claude Code" banners
    content = _capture_pane_tail(15)
    if "Resume this session" in content:
        return False
    # Detect shell prompt (Claude exited/crashed back to shell)
    # Common shell prompts end with $ or % or >
    stripped_lines = [ln.strip() for ln in content.strip().splitlines() if ln.strip()]
    if stripped_lines:
        last_line = stripped_lines[-1]
        # If last line looks like a shell prompt, Claude isn't running
        if re.match(r'.*[\$%#>]\s*$', last_line) and "❯" not in content:
            log.info("Detected shell prompt — Claude CLI not running")
            return False
    # ❯ is Claude's TUI prompt character (distinct from shell prompts)
    if "❯" in content:
        return True
    return False


_consecutive_failures = 0


def _kill_tmux_session() -> None:
    """Kill the tmux session if it exists."""
    if _tmux_session_exists():
        subprocess.run(
            ["tmux", "kill-session", "-t", TMUX_SESSION],
            capture_output=True, timeout=5,
        )


def _ensure_tmux_session() -> bool:
    """Ensure our tmux session exists with claude running. Returns True if ready."""
    if _is_claude_alive():
        return True

    log.info("Creating tmux session %s with claude CLI...", TMUX_SESSION)

    # Kill any stale session
    _kill_tmux_session()

    # Create new detached session with specific pane size
    env = {**__import__('os').environ}
    env.pop("CLAUDECODE", None)  # Must unset to avoid nested-session error

    subprocess.run(
        ["tmux", "new-session", "-d", "-s", TMUX_SESSION,
         "-x", str(TMUX_PANE_WIDTH), "-y", str(TMUX_PANE_HEIGHT)],
        capture_output=True, timeout=5, env=env,
    )

    # Start claude in the session
    _run_tmux("send-keys", "-t", TMUX_SESSION, "unset CLAUDECODE && claude", "Enter")

    # Wait for claude to boot (up to 15 seconds)
    for _ in range(15):
        time.sleep(1)
        content = _capture_pane()
        if "Claude Code" in content and "❯" in content:
            log.info("Claude CLI started in tmux session")
            return True

    log.warning("Claude CLI did not start in time")
    return False


def _send_usage_command() -> Optional[str]:
    """Send /usage to the claude CLI and capture the dialog output.

    The CLI shows an autocomplete dropdown when typing /usage.
    We type the command, wait for autocomplete, then press Enter to select.
    After the usage dialog renders, we press Escape to dismiss it.
    Retries once if the first attempt fails (Claude TUI can be slow).
    """
    for attempt in range(2):
        if attempt > 0:
            log.info("Retrying /usage command (attempt %d)", attempt + 1)
            time.sleep(2)

        # Type /usage — this triggers autocomplete dropdown
        _run_tmux("send-keys", "-t", TMUX_SESSION, "/usage", "")
        time.sleep(1)

        # Press Enter to select /usage from the autocomplete menu
        _run_tmux("send-keys", "-t", TMUX_SESSION, "Enter", "")

        # Wait for the usage dialog to appear (look for "% used")
        content = ""
        for _ in range(15):
            time.sleep(1)
            content = _capture_pane()
            if "% used" in content:
                # Dismiss the dialog
                time.sleep(0.5)
                _run_tmux("send-keys", "-t", TMUX_SESSION, "Escape", "")
                return content

        # Dismiss anything that might be showing before retry
        _run_tmux("send-keys", "-t", TMUX_SESSION, "Escape", "")

    log.warning("Usage dialog did not appear after retries")
    return None


def _restart_and_retry() -> UsageData:
    """Kill the tmux session, recreate it, and retry a single poll."""
    global _consecutive_failures
    log.warning(
        "Restarting tmux session after %d consecutive failures",
        _consecutive_failures,
    )
    _kill_tmux_session()
    _consecutive_failures = 0  # Reset so _ensure_tmux_session gets a clean slate

    if not _ensure_tmux_session():
        return UsageData(error="Could not restart claude CLI in tmux")

    # Give Claude a few seconds to fully initialize before sending /usage
    time.sleep(3)

    content = _send_usage_command()
    if content is None:
        return UsageData(error="No response after restart")

    data = _parse_usage_text(content)
    if data.window_5h.used_pct == 0 and data.period_7d.used_pct == 0:
        if "% used" not in content:
            data.error = "Could not parse /usage output"
    return data


def poll_usage() -> UsageData:
    """Poll usage by sending /usage to the tmux-hosted claude CLI session."""
    global _consecutive_failures
    try:
        if not _ensure_tmux_session():
            _consecutive_failures += 1
            if _consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                return _restart_and_retry()
            return UsageData(error="Could not start claude CLI in tmux")

        content = _send_usage_command()
        if content is None:
            _consecutive_failures += 1
            if _consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                return _restart_and_retry()
            return UsageData(error="No response from /usage command")

        data = _parse_usage_text(content)
        if data.window_5h.used_pct == 0 and data.period_7d.used_pct == 0:
            # Might be a parse failure — check if we got any content
            if "% used" not in content:
                _consecutive_failures += 1
                if _consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    return _restart_and_retry()
                data.error = "Could not parse /usage output"

        if data.error is None:
            _consecutive_failures = 0

        return data

    except subprocess.TimeoutExpired:
        _consecutive_failures += 1
        log.error("Tmux command timed out")
        if _consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            return _restart_and_retry()
        return UsageData(error="Tmux timeout")
    except FileNotFoundError:
        log.error("tmux not found — install with: brew install tmux")
        return UsageData(error="tmux not installed")
    except Exception as e:
        _consecutive_failures += 1
        log.error("Unexpected error polling usage: %s", e)
        if _consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            return _restart_and_retry()
        return UsageData(error=f"Error: {e}")
