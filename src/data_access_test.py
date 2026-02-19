"""Tests for data_access.py — header parsing, score calculation, state indexing."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from data_access import (
    _compute_elapsed_pct,
    _parse_reset_timestamp,
    _parse_utilization,
    _score_to_state,
    format_time_remaining,
    is_token_expired,
    parse_usage_data,
    read_credentials,
)


# ---------------------------------------------------------------------------
# _parse_utilization
# ---------------------------------------------------------------------------

class TestParseUtilization:
    def test_fraction_0_to_1_multiplied_by_100(self):
        assert _parse_utilization("0.47") == pytest.approx(47.0)

    def test_zero_fraction(self):
        assert _parse_utilization("0.0") == pytest.approx(0.0)

    def test_one_fraction(self):
        assert _parse_utilization("1.0") == pytest.approx(100.0)

    def test_percentage_0_to_100_unchanged(self):
        # Values > 1 are treated as direct percentages
        assert _parse_utilization("47.5") == pytest.approx(47.5)

    def test_invalid_string_returns_zero(self):
        assert _parse_utilization("n/a") == 0.0

    def test_empty_string_returns_zero(self):
        assert _parse_utilization("") == 0.0

    def test_clamped_above_100(self):
        assert _parse_utilization("150") == pytest.approx(100.0)

    def test_clamped_below_0(self):
        assert _parse_utilization("-10") == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# _parse_reset_timestamp
# ---------------------------------------------------------------------------

class TestParseResetTimestamp:
    def test_unix_epoch_integer_string(self):
        # 2026-02-19 10:00:00 UTC = 1771477200
        dt = _parse_reset_timestamp("1771477200")
        assert dt is not None
        assert dt.year == 2026
        assert dt.tzinfo is not None

    def test_unix_epoch_float_string(self):
        dt = _parse_reset_timestamp("1771477200.5")
        assert dt is not None
        assert dt.tzinfo is not None

    def test_iso8601_with_z_suffix(self):
        dt = _parse_reset_timestamp("2026-02-19T10:00:00Z")
        assert dt is not None
        assert dt.year == 2026
        assert dt.month == 2
        assert dt.tzinfo is not None

    def test_iso8601_with_offset(self):
        dt = _parse_reset_timestamp("2026-02-19T10:00:00+00:00")
        assert dt is not None

    def test_invalid_returns_none(self):
        assert _parse_reset_timestamp("not-a-date") is None

    def test_empty_returns_none(self):
        assert _parse_reset_timestamp("") is None


# ---------------------------------------------------------------------------
# _compute_elapsed_pct
# ---------------------------------------------------------------------------

class TestComputeElapsedPct:
    def test_midpoint_of_window(self):
        # resets_at is 2.5 hours from now → half of 5h window elapsed
        resets_at = datetime.now(timezone.utc) + timedelta(hours=2.5)
        pct = _compute_elapsed_pct(resets_at, 5 * 3600)
        assert pct == pytest.approx(50.0, abs=1.0)

    def test_nearly_full_window(self):
        # resets_at is 0.5h from now → ~90% elapsed in 5h window
        resets_at = datetime.now(timezone.utc) + timedelta(minutes=30)
        pct = _compute_elapsed_pct(resets_at, 5 * 3600)
        assert pct == pytest.approx(90.0, abs=2.0)

    def test_start_of_window(self):
        # resets_at is 5h from now → 0% elapsed
        resets_at = datetime.now(timezone.utc) + timedelta(hours=5)
        pct = _compute_elapsed_pct(resets_at, 5 * 3600)
        assert pct == pytest.approx(0.0, abs=1.0)

    def test_clamped_to_100_when_past_reset(self):
        resets_at = datetime.now(timezone.utc) - timedelta(hours=1)
        pct = _compute_elapsed_pct(resets_at, 5 * 3600)
        assert pct == pytest.approx(100.0)

    def test_zero_window_returns_zero(self):
        resets_at = datetime.now(timezone.utc) + timedelta(hours=1)
        assert _compute_elapsed_pct(resets_at, 0) == 0.0


# ---------------------------------------------------------------------------
# _score_to_state
# ---------------------------------------------------------------------------

class TestScoreToState:
    @pytest.mark.parametrize("score,expected_state", [
        (-35, 1),   # very under budget
        (-25, 2),
        (-15, 3),
        (-7, 4),
        (-3, 5),
        (0, 6),     # zen
        (5, 7),
        (15, 8),
        (25, 9),
        (35, 10),   # disaster
    ])
    def test_score_to_state_boundaries(self, score, expected_state):
        assert _score_to_state(score) == expected_state

    def test_exact_boundary_minus_30(self):
        assert _score_to_state(-30) == 1

    def test_exact_boundary_minus_2(self):
        assert _score_to_state(-2) == 5

    def test_exact_boundary_plus_2(self):
        assert _score_to_state(2) == 6

    def test_exact_boundary_plus_30(self):
        assert _score_to_state(30) == 9

    def test_just_above_30(self):
        assert _score_to_state(30.1) == 10


# ---------------------------------------------------------------------------
# parse_usage_data
# ---------------------------------------------------------------------------

class TestParseUsageData:
    def _make_headers(self, util_5h="0.47", reset_5h=None, util_7d=None, reset_7d=None):
        if reset_5h is None:
            # Use unix epoch (real API format)
            reset_5h = str(int((datetime.now(timezone.utc) + timedelta(hours=2.5)).timestamp()))
        headers = {
            "anthropic-ratelimit-unified-5h-utilization": util_5h,
            "anthropic-ratelimit-unified-5h-reset": reset_5h,
        }
        if util_7d is not None:
            headers["anthropic-ratelimit-unified-7d-utilization"] = util_7d
        if reset_7d is not None:
            headers["anthropic-ratelimit-unified-7d-reset"] = reset_7d
        return headers

    def test_5h_utilization_parsed(self):
        headers = self._make_headers(util_5h="0.47")
        data = parse_usage_data(headers)
        assert data.window_5h.used_pct == pytest.approx(47.0)

    def test_5h_elapsed_computed(self):
        headers = self._make_headers()
        data = parse_usage_data(headers)
        # reset_5h is 2.5h from now → ~50% elapsed
        assert 40.0 < data.window_5h.elapsed_pct < 60.0

    def test_7d_utilization_parsed(self):
        reset_7d = str(int((datetime.now(timezone.utc) + timedelta(days=3)).timestamp()))
        headers = self._make_headers(util_7d="0.23", reset_7d=reset_7d)
        data = parse_usage_data(headers)
        assert data.period_7d.used_pct == pytest.approx(23.0)

    def test_no_7d_header_leaves_zeroed(self):
        headers = self._make_headers()
        data = parse_usage_data(headers)
        assert data.period_7d.used_pct == 0.0
        assert data.period_7d.elapsed_pct == 0.0

    def test_score_computed_from_7d_only(self):
        reset_5h = str(int((datetime.now(timezone.utc) + timedelta(hours=2.5)).timestamp()))
        reset_7d = str(int((datetime.now(timezone.utc) + timedelta(days=3.5)).timestamp()))
        headers = {
            "anthropic-ratelimit-unified-5h-utilization": "0.47",
            "anthropic-ratelimit-unified-5h-reset": reset_5h,
            "anthropic-ratelimit-unified-7d-utilization": "0.23",
            "anthropic-ratelimit-unified-7d-reset": reset_7d,
        }
        data = parse_usage_data(headers)
        # 7d: used=23, elapsed≈50 → score ≈ -27 (7d only, not averaged with 5h)
        assert data.score < 0  # under budget
        assert data.score == pytest.approx(data.period_7d.used_pct - data.period_7d.elapsed_pct)
        assert data.state_index in (1, 2, 3)

    def test_last_updated_set(self):
        data = parse_usage_data(self._make_headers())
        assert data.last_updated is not None
        assert data.last_updated.tzinfo is not None

    def test_raw_headers_stored(self):
        headers = self._make_headers()
        data = parse_usage_data(headers)
        assert len(data.raw_headers) > 0


# ---------------------------------------------------------------------------
# is_token_expired
# ---------------------------------------------------------------------------

class TestIsTokenExpired:
    def test_future_token_not_expired(self):
        expires_ms = int((time.time() + 3600) * 1000)
        oauth = {"expiresAt": expires_ms}
        assert is_token_expired(oauth) is False

    def test_past_token_expired(self):
        expires_ms = int((time.time() - 3600) * 1000)
        oauth = {"expiresAt": expires_ms}
        assert is_token_expired(oauth) is True

    def test_missing_expires_at_treated_as_expired(self):
        assert is_token_expired({}) is True

    def test_within_5_minute_buffer_treated_as_expired(self):
        # 4 minutes from now → within 5-minute buffer → expired
        expires_ms = int((time.time() + 240) * 1000)
        oauth = {"expiresAt": expires_ms}
        assert is_token_expired(oauth) is True


# ---------------------------------------------------------------------------
# format_time_remaining
# ---------------------------------------------------------------------------

class TestFormatTimeRemaining:
    def test_none_returns_unknown(self):
        assert format_time_remaining(None) == "Unknown"

    def test_past_time_returns_resetting(self):
        past = datetime.now(timezone.utc) - timedelta(minutes=5)
        assert format_time_remaining(past) == "Resetting..."

    def test_hours_and_minutes(self):
        future = datetime.now(timezone.utc) + timedelta(hours=2, minutes=14)
        result = format_time_remaining(future)
        assert "2h" in result
        assert "14m" in result or "13m" in result  # allow 1 second drift

    def test_days_and_hours(self):
        future = datetime.now(timezone.utc) + timedelta(days=4, hours=8)
        result = format_time_remaining(future)
        assert "4d" in result
        assert "h" in result  # hours present, allow 1h drift in test execution

    def test_minutes_only(self):
        future = datetime.now(timezone.utc) + timedelta(minutes=45)
        result = format_time_remaining(future)
        assert "m" in result
        assert "d" not in result
        assert "h" not in result


# ---------------------------------------------------------------------------
# read_credentials (integration — uses real file)
# ---------------------------------------------------------------------------

class TestReadCredentials:
    def test_reads_real_credentials_file(self):
        """Real credentials file must exist and contain claudeAiOauth."""
        creds = read_credentials()
        assert "claudeAiOauth" in creds
        oauth = creds["claudeAiOauth"]
        assert "accessToken" in oauth
        assert "refreshToken" in oauth
        assert "expiresAt" in oauth

    def test_missing_file_raises(self):
        with patch("data_access.CREDENTIALS_PATH", Path("/nonexistent/path/.credentials.json")):
            with pytest.raises(FileNotFoundError):
                read_credentials()
