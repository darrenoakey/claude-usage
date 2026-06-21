"""Tests for the agentd-backed data layer. No mocks: parsing runs on a real
captured agentd payload, and poll_usage is exercised against a real local HTTP
server serving that payload over a real socket.
"""
import json
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

from data_access import (
    format_time_remaining,
    poll_usage,
    _parse_provider,
    _parse_time,
)

# A real snapshot captured from GET /v1/subscription-usage.
SAMPLE = {
    "providers": [
        {
            "name": "codex", "display_name": "Codex", "plan": "pro", "available": True,
            "session": {"label": "5h", "used_pct": 14, "elapsed_pct": 36.4, "resets_at": "2026-06-21T02:05:39+10:00"},
            "weekly": {"label": "7d", "used_pct": 8, "elapsed_pct": 17.1, "resets_at": "2026-06-27T16:04:38+10:00"},
            "score": -9.1, "state_index": 4,
        },
        {
            "name": "claude", "display_name": "Claude", "available": False,
            "reason": "Claude /usage endpoint is rate limited — retry later",
            "score": 0, "state_index": 0,
        },
        {
            "name": "zai", "display_name": "GLM-5", "plan": "max", "available": True,
            "session": {"label": "5h", "used_pct": 0, "elapsed_pct": 0},
            "weekly": {"label": "7d", "used_pct": 28, "elapsed_pct": 38.0, "resets_at": "2026-06-25T07:36:41.991+10:00"},
            "score": -10.0, "state_index": 4,
        },
    ],
    "combined": {"score": -2.0, "state_index": 5, "pace": "🟡 Slightly under budget", "providers": 2},
    "generated_at": "2026-06-21T12:00:00+10:00",
}


def test_parse_available_provider_with_windows():
    p = _parse_provider(SAMPLE["providers"][0])
    assert p.name == "codex"
    assert p.available is True
    assert p.plan == "pro"
    assert p.weekly is not None and p.weekly.used_pct == 8
    assert p.session is not None and p.session.used_pct == 14
    assert p.weekly.resets_at is not None


def test_parse_unavailable_provider_carries_reason():
    p = _parse_provider(SAMPLE["providers"][1])
    assert p.available is False
    assert "rate limited" in p.reason
    assert p.weekly is None


def test_parse_time_handles_offset_and_fractional():
    assert _parse_time("2026-06-27T16:04:38+10:00") is not None
    assert _parse_time("2026-06-25T07:36:41.991+10:00") is not None
    assert _parse_time(None) is None
    assert _parse_time("not-a-time") is None


def test_format_time_remaining():
    now = datetime.now(timezone.utc)
    assert format_time_remaining(None) == "—"
    assert format_time_remaining(now - timedelta(hours=1)) == "resetting"
    assert "d" in format_time_remaining(now + timedelta(days=2, hours=3))
    assert "h" in format_time_remaining(now + timedelta(hours=5, minutes=10))


def test_poll_usage_against_real_local_server():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = json.dumps(SAMPLE).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):  # noqa: A002  silence
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_address[1]
        data = poll_usage(f"http://127.0.0.1:{port}/v1/subscription-usage")
    finally:
        server.shutdown()

    assert data.error is None
    assert len(data.providers) == 3
    assert data.combined_state == 5
    assert data.combined_pace.startswith("🟡")
    assert {p.name for p in data.providers} == {"codex", "claude", "zai"}


def test_poll_usage_reports_offline_when_unreachable():
    # Nothing is listening on this port — real connection failure, real reason.
    data = poll_usage("http://127.0.0.1:1/v1/subscription-usage")
    assert data.error is not None
    assert not data.providers
