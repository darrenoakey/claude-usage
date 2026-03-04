"""Tests for data_access.py — usage text parsing, score calculation, state indexing."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from data_access import (
    _compute_elapsed_pct,
    _parse_reset_time,
    _parse_usage_text,
    _score_to_state,
    _strip_ansi,
    format_time_remaining,
)

# Sample /usage output captured from real claude CLI
SAMPLE_USAGE_OUTPUT = """\
❯ /usage
────────────────────────────────────────────────────────────────────────────────
 ──────────────────────────────────────────────────────────────────────────────
  Settings:  Status   Config   Usage  (←/→ or tab to cycle)


  Current session
  ██                                                 4% used
  Resets 10pm (Australia/Sydney)

  Current week (all models)
  ██████████████                                     28% used
  Resets Mar 6 at 2pm (Australia/Sydney)

  Current week (Sonnet only)
  ██                                                 4% used
  Resets Mar 6 at 5pm (Australia/Sydney)

  Esc to cancel
"""


# ---------------------------------------------------------------------------
# _strip_ansi
# ---------------------------------------------------------------------------

class TestStripAnsi:
    def test_strips_escape_codes(self):
        text = "\x1b[31mhello\x1b[0m"
        assert _strip_ansi(text) == "hello"

    def test_strips_block_characters(self):
        text = "██████  50% used"
        result = _strip_ansi(text)
        assert "█" not in result
        assert "50% used" in result

    def test_preserves_normal_text(self):
        assert _strip_ansi("hello world") == "hello world"


# ---------------------------------------------------------------------------
# _parse_reset_time
# ---------------------------------------------------------------------------

class TestParseResetTime:
    def test_time_only_today(self):
        dt = _parse_reset_time("10pm (Australia/Sydney)")
        assert dt is not None
        assert dt.tzinfo is not None
        tz = ZoneInfo("Australia/Sydney")
        local = dt.astimezone(tz)
        assert local.hour == 22

    def test_time_am(self):
        dt = _parse_reset_time("8am (Australia/Sydney)")
        assert dt is not None
        tz = ZoneInfo("Australia/Sydney")
        local = dt.astimezone(tz)
        assert local.hour == 8

    def test_date_and_time(self):
        dt = _parse_reset_time("Mar 6 at 2pm (Australia/Sydney)")
        assert dt is not None
        tz = ZoneInfo("Australia/Sydney")
        local = dt.astimezone(tz)
        assert local.month == 3
        assert local.day == 6
        assert local.hour == 14

    def test_date_and_time_am(self):
        dt = _parse_reset_time("Jan 15 at 10am (US/Eastern)")
        assert dt is not None
        tz = ZoneInfo("US/Eastern")
        local = dt.astimezone(tz)
        assert local.month == 1
        assert local.day == 15
        assert local.hour == 10

    def test_unknown_timezone_returns_none(self):
        assert _parse_reset_time("10pm (Fake/Timezone)") is None

    def test_no_timezone_returns_none(self):
        assert _parse_reset_time("10pm") is None

    def test_no_time_returns_none(self):
        assert _parse_reset_time("(Australia/Sydney)") is None

    def test_12pm_is_noon(self):
        dt = _parse_reset_time("12pm (UTC)")
        assert dt is not None
        assert dt.hour == 12

    def test_12am_is_midnight(self):
        dt = _parse_reset_time("12am (UTC)")
        assert dt is not None
        assert dt.hour == 0

    def test_time_with_minutes(self):
        dt = _parse_reset_time("1:59pm (UTC)")
        assert dt is not None
        assert dt.hour == 13
        assert dt.minute == 59

    def test_time_with_minutes_am(self):
        dt = _parse_reset_time("11:30am (UTC)")
        assert dt is not None
        assert dt.hour == 11
        assert dt.minute == 30

    def test_date_with_minutes(self):
        dt = _parse_reset_time("Mar 6 at 2:45pm (Australia/Sydney)")
        assert dt is not None
        assert dt.hour == 14
        assert dt.minute == 45


# ---------------------------------------------------------------------------
# _parse_usage_text
# ---------------------------------------------------------------------------

class TestParseUsageText:
    def test_parses_session_percentage(self):
        data = _parse_usage_text(SAMPLE_USAGE_OUTPUT)
        assert data.window_5h.used_pct == pytest.approx(4.0)

    def test_parses_weekly_percentage(self):
        data = _parse_usage_text(SAMPLE_USAGE_OUTPUT)
        assert data.period_7d.used_pct == pytest.approx(28.0)

    def test_session_reset_time_set(self):
        data = _parse_usage_text(SAMPLE_USAGE_OUTPUT)
        assert data.window_5h.resets_at is not None
        assert data.window_5h.resets_at.tzinfo is not None

    def test_weekly_reset_time_set(self):
        data = _parse_usage_text(SAMPLE_USAGE_OUTPUT)
        assert data.period_7d.resets_at is not None
        assert data.period_7d.resets_at.tzinfo is not None

    def test_window_seconds_set(self):
        data = _parse_usage_text(SAMPLE_USAGE_OUTPUT)
        assert data.window_5h.window_seconds == 5 * 3600
        assert data.period_7d.window_seconds == 7 * 24 * 3600

    def test_score_computed(self):
        data = _parse_usage_text(SAMPLE_USAGE_OUTPUT)
        # 28% used with some elapsed → score should be set
        assert data.score != 0.0 or data.period_7d.elapsed_pct == pytest.approx(28.0, abs=5)

    def test_state_index_set(self):
        data = _parse_usage_text(SAMPLE_USAGE_OUTPUT)
        assert 1 <= data.state_index <= 10

    def test_last_updated_set(self):
        data = _parse_usage_text(SAMPLE_USAGE_OUTPUT)
        assert data.last_updated is not None

    def test_empty_text_returns_defaults(self):
        data = _parse_usage_text("")
        assert data.window_5h.used_pct == 0.0
        assert data.period_7d.used_pct == 0.0
        assert data.state_index == 6  # zen default

    def test_high_usage_output(self):
        text = """\
  Current session
  ████████████████████████████████████████████████   95% used
  Resets 3am (UTC)

  Current week (all models)
  ████████████████████████████████████             72% used
  Resets Jan 10 at 6pm (UTC)
"""
        data = _parse_usage_text(text)
        assert data.window_5h.used_pct == pytest.approx(95.0)
        assert data.period_7d.used_pct == pytest.approx(72.0)


# ---------------------------------------------------------------------------
# _compute_elapsed_pct
# ---------------------------------------------------------------------------

class TestComputeElapsedPct:
    def test_midpoint_of_window(self):
        resets_at = datetime.now(timezone.utc) + timedelta(hours=2.5)
        pct = _compute_elapsed_pct(resets_at, 5 * 3600)
        assert pct == pytest.approx(50.0, abs=1.0)

    def test_nearly_full_window(self):
        resets_at = datetime.now(timezone.utc) + timedelta(minutes=30)
        pct = _compute_elapsed_pct(resets_at, 5 * 3600)
        assert pct == pytest.approx(90.0, abs=2.0)

    def test_start_of_window(self):
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
        assert "14m" in result or "13m" in result

    def test_days_and_hours(self):
        future = datetime.now(timezone.utc) + timedelta(days=4, hours=8)
        result = format_time_remaining(future)
        assert "4d" in result
        assert "h" in result

    def test_minutes_only(self):
        future = datetime.now(timezone.utc) + timedelta(minutes=45)
        result = format_time_remaining(future)
        assert "m" in result
        assert "d" not in result
        assert "h" not in result
