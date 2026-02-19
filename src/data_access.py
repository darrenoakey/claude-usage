"""Data access layer: OAuth credentials, token refresh, usage polling, header parsing."""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests

log = logging.getLogger(__name__)

CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"
API_BASE = "https://api.anthropic.com"
OAUTH_TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
ANTHROPIC_VERSION = "2023-06-01"
ANTHROPIC_BETA_OAUTH = "oauth-2025-04-20"
POLL_MODEL = "claude-haiku-4-5-20251001"

# Score boundaries for state index (score = used_pct - elapsed_pct, averaged across gauges)
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
    used_pct: float = 0.0        # 0-100, from utilization header
    elapsed_pct: float = 0.0    # 0-100, computed from reset timestamp
    resets_at: Optional[datetime] = None
    window_seconds: float = 0.0


@dataclass
class UsageData:
    window_5h: GaugeData = field(default_factory=GaugeData)
    period_7d: GaugeData = field(default_factory=GaugeData)
    score: float = 0.0           # used_pct - elapsed_pct, averaged; negative = good
    state_index: int = 6         # 1-10
    last_updated: Optional[datetime] = None
    raw_headers: dict = field(default_factory=dict)
    error: Optional[str] = None


def read_credentials() -> dict:
    """Read OAuth credentials from ~/.claude/.credentials.json."""
    if not CREDENTIALS_PATH.exists():
        raise FileNotFoundError(f"Credentials file not found: {CREDENTIALS_PATH}")
    with open(CREDENTIALS_PATH) as f:
        return json.load(f)


def write_credentials(creds: dict) -> None:
    """Write updated credentials back to disk."""
    with open(CREDENTIALS_PATH, "w") as f:
        json.dump(creds, f, indent=2)


def is_token_expired(oauth: dict) -> bool:
    """Return True if the access token is expired (with 5-minute buffer)."""
    expires_ms = oauth.get("expiresAt", 0)
    expires_s = expires_ms / 1000
    return time.time() > (expires_s - 300)  # 5-minute buffer


def maybe_refresh_token(creds: dict) -> dict:
    """Refresh the OAuth token if expired. Returns updated creds dict."""
    oauth = creds.get("claudeAiOauth", {})
    if not is_token_expired(oauth):
        return creds

    log.info("Access token expired, refreshing via platform.claude.com...")
    refresh_token = oauth.get("refreshToken", "")
    if not refresh_token:
        log.warning("No refresh token available")
        return creds

    try:
        resp = requests.post(
            OAUTH_TOKEN_URL,
            json={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": OAUTH_CLIENT_ID,
            },
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            oauth["accessToken"] = data["access_token"]
            oauth["refreshToken"] = data["refresh_token"]
            oauth["expiresAt"] = int((time.time() + data["expires_in"]) * 1000)
            creds["claudeAiOauth"] = oauth
            write_credentials(creds)
            log.info("Token refreshed successfully, expires in %ds", data["expires_in"])
        else:
            log.warning("Token refresh failed: %s %s", resp.status_code, resp.text[:200])
    except Exception as e:
        log.warning("Token refresh error: %s", e)

    return creds


def _parse_utilization(value: str) -> float:
    """Parse utilization header value to 0-100 float. Handles both 0-1 and 0-100 ranges."""
    try:
        f = float(value)
        # If value is between 0 and 1, assume it's a fraction → multiply by 100
        if 0.0 <= f <= 1.0:
            return f * 100.0
        return max(0.0, min(100.0, f))
    except (ValueError, TypeError):
        return 0.0


def _parse_reset_timestamp(value: str) -> Optional[datetime]:
    """Parse reset timestamp to aware datetime.

    Supports:
    - Unix epoch seconds (integer or float string): e.g. "1771477200"
    - ISO 8601 / RFC 3339: e.g. "2026-02-19T10:00:00Z"
    """
    if not value:
        return None
    try:
        # Try as Unix epoch integer first (most common in practice)
        epoch_s = float(value)
        return datetime.fromtimestamp(epoch_s, tz=timezone.utc)
    except ValueError:
        pass
    try:
        # Fall back to ISO 8601 with Z suffix
        val = value.replace("Z", "+00:00")
        return datetime.fromisoformat(val)
    except (ValueError, AttributeError):
        return None


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


def parse_usage_data(headers: dict) -> UsageData:
    """Parse anthropic-ratelimit-* headers into UsageData."""
    # Log all ratelimit headers for discovery
    rl_headers = {k: v for k, v in headers.items() if "ratelimit" in k.lower()}
    log.debug("Rate limit headers: %s", rl_headers)

    data = UsageData(raw_headers=rl_headers, last_updated=datetime.now(timezone.utc))

    # --- 5-hour window ---
    util_5h = None
    reset_5h = None
    for key, val in headers.items():
        k = key.lower()
        if "ratelimit" in k and ("5h" in k or "5-h" in k):
            if "utilization" in k:
                util_5h = val
            elif "reset" in k and "status" not in k:
                reset_5h = val

    if util_5h is not None:
        data.window_5h.used_pct = _parse_utilization(util_5h)
    if reset_5h is not None:
        data.window_5h.resets_at = _parse_reset_timestamp(reset_5h)
        data.window_5h.window_seconds = 5 * 3600
        if data.window_5h.resets_at:
            data.window_5h.elapsed_pct = _compute_elapsed_pct(
                data.window_5h.resets_at, data.window_5h.window_seconds
            )

    # --- 7-day period ---
    util_7d = None
    reset_7d = None
    for key, val in headers.items():
        k = key.lower()
        if "ratelimit" in k and any(p in k for p in ["7d", "7-d", "1w", "1-w", "week", "period"]):
            if "utilization" in k:
                util_7d = val
            elif "reset" in k and "status" not in k:
                reset_7d = val

    if util_7d is not None:
        data.period_7d.used_pct = _parse_utilization(util_7d)
    if reset_7d is not None:
        data.period_7d.resets_at = _parse_reset_timestamp(reset_7d)
        data.period_7d.window_seconds = 7 * 24 * 3600
        if data.period_7d.resets_at:
            data.period_7d.elapsed_pct = _compute_elapsed_pct(
                data.period_7d.resets_at, data.period_7d.window_seconds
            )

    if util_7d is None:
        log.info("No 7-day period header found. Discovered headers: %s", list(rl_headers.keys()))

    # --- Score calculation (7-day period only) ---
    if data.period_7d.used_pct > 0 or data.period_7d.elapsed_pct > 0:
        data.score = data.period_7d.used_pct - data.period_7d.elapsed_pct
    else:
        # Fall back to 5h window if 7d not available
        if data.window_5h.used_pct > 0 or data.window_5h.elapsed_pct > 0:
            data.score = data.window_5h.used_pct - data.window_5h.elapsed_pct
        else:
            data.score = 0.0

    data.state_index = _score_to_state(data.score)
    return data


def poll_usage() -> UsageData:
    """Make a minimal API call to fetch usage headers. Returns UsageData."""
    try:
        creds = read_credentials()
        creds = maybe_refresh_token(creds)
        oauth = creds.get("claudeAiOauth", {})
        access_token = oauth.get("accessToken", "")

        if not access_token:
            return UsageData(error="No access token available")

        resp = requests.post(
            f"{API_BASE}/v1/messages",
            json={
                "model": POLL_MODEL,
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "hi"}],
            },
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "anthropic-version": ANTHROPIC_VERSION,
                "anthropic-beta": ANTHROPIC_BETA_OAUTH,
            },
            timeout=20,
        )

        all_headers = dict(resp.headers)
        log.debug("API response status: %s", resp.status_code)

        if resp.status_code in (401, 403):
            error_body = {}
            if resp.headers.get("content-type", "").startswith("application/json"):
                error_body = resp.json()
            err_msg = error_body.get("error", {}).get("message", "Authentication failed")
            log.warning("Auth error: %s", err_msg)
            return UsageData(error=f"Auth: {err_msg}", raw_headers=all_headers)

        usage = parse_usage_data(all_headers)
        return usage

    except requests.RequestException as e:
        log.error("Network error polling usage: %s", e)
        return UsageData(error=f"Network: {e}")
    except Exception as e:
        log.error("Unexpected error polling usage: %s", e)
        return UsageData(error=f"Error: {e}")


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
