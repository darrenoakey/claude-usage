"""Data access layer: read the unified subscription-usage feed from agentd.

This desktop app is a thin native CLIENT of agentd — agentd is the single poller
that scrapes Codex/Claude/GLM-5 usage. We just GET its already-computed snapshot
over HTTP and render it with native QPainter gauges. No tmux, no /usage scraping,
no provider credentials here.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)

# agentd daemon (loopback). The browser UI proxies the same route on 8421, but we
# talk to the daemon directly.
AGENTD_URL = "http://127.0.0.1:8420/v1/subscription-usage"
HTTP_TIMEOUT = 8.0


@dataclass
class Window:
    used_pct: float = 0.0
    elapsed_pct: float = 0.0
    resets_at: Optional[datetime] = None


@dataclass
class Provider:
    name: str = ""
    display_name: str = ""
    plan: str = ""
    available: bool = False
    reason: str = ""
    weekly: Optional[Window] = None
    session: Optional[Window] = None
    score: float = 0.0
    state_index: int = 6


@dataclass
class UsageData:
    providers: list[Provider] = field(default_factory=list)
    combined_score: float = 0.0
    combined_state: int = 6
    combined_pace: str = ""
    error: Optional[str] = None


def _parse_time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        # agentd emits RFC3339 with offset, e.g. 2026-06-27T16:04:38+10:00 or
        # with fractional seconds. fromisoformat handles both on Python 3.11+.
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _parse_window(raw: Optional[dict]) -> Optional[Window]:
    if not raw:
        return None
    return Window(
        used_pct=float(raw.get("used_pct", 0.0) or 0.0),
        elapsed_pct=float(raw.get("elapsed_pct", 0.0) or 0.0),
        resets_at=_parse_time(raw.get("resets_at")),
    )


def _parse_provider(raw: dict) -> Provider:
    return Provider(
        name=raw.get("name", ""),
        display_name=raw.get("display_name", raw.get("name", "")),
        plan=raw.get("plan", "") or "",
        available=bool(raw.get("available", False)),
        reason=raw.get("reason", "") or "",
        weekly=_parse_window(raw.get("weekly")),
        session=_parse_window(raw.get("session")),
        score=float(raw.get("score", 0.0) or 0.0),
        state_index=int(raw.get("state_index", 6) or 6),
    )


def poll_usage(url: str = AGENTD_URL) -> UsageData:
    """Fetch the current subscription-usage snapshot from agentd."""
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        return UsageData(error=f"agentd unreachable: {e.reason}")
    except (TimeoutError, OSError) as e:
        return UsageData(error=f"agentd request failed: {e}")
    except json.JSONDecodeError as e:
        return UsageData(error=f"bad agentd response: {e}")

    providers = [_parse_provider(p) for p in payload.get("providers", [])]
    combined = payload.get("combined", {}) or {}
    if not providers:
        return UsageData(error="agentd returned no providers")
    return UsageData(
        providers=providers,
        combined_score=float(combined.get("score", 0.0) or 0.0),
        combined_state=int(combined.get("state_index", 6) or 6),
        combined_pace=combined.get("pace", "") or "",
    )


def format_time_remaining(resets_at: Optional[datetime]) -> str:
    """Human-readable time until a window resets."""
    if resets_at is None:
        return "—"
    now = datetime.now(timezone.utc)
    delta = resets_at.astimezone(timezone.utc) - now
    total = int(delta.total_seconds())
    if total <= 0:
        return "resetting"
    days = total // 86400
    hours = (total % 86400) // 3600
    minutes = (total % 3600) // 60
    if days > 0:
        return f"{days}d {hours}h"
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"
