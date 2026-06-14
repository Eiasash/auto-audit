"""Unit tests for the Tier-3 monitor-liveness guard in tier3_synthesis.detect_signals.

Regression cover for the 2026-06 outage where the Tier 1 probe was dead for
~5 weeks while Tier 3 kept reporting "Action needed: None" over zero data (a
false-green). The guard must turn an empty/stale report window into a CRITICAL
"monitor-down"/"monitor-stale" signal so the weekly synthesis self-alarms.

Hermetic: no network, no filesystem — calls detect_signals directly with empty
GitHub/spend inputs so only the liveness branch can produce signals.
"""

from __future__ import annotations

import datetime as dt
import os
import sys

# tier3_synthesis.py lives in scripts/ (parent of this scripts/probes/ dir).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tier3_synthesis as t3  # noqa: E402

# Fixed "now" inside the DISPATCH_PAT warn window floor (47 days old < 60d warn),
# so the PAT-rotation signal does not fire and only the liveness branch can.
NOW = dt.datetime(2026, 6, 15, 12, 0, 0, tzinfo=dt.timezone.utc)


def _signals(reports, days=7):
    return t3.detect_signals(
        {},  # per_repo
        {},  # cross_cutting
        {"available": False},  # spend
        {},  # open_self_issues
        {},  # open_target_issues
        NOW,
        reports,
        days,
    )


def _categories(sigs):
    return {(s["severity"], s["category"]) for s in sigs}


def test_zero_reports_emits_monitor_down_crit():
    sigs = _signals([], days=7)
    assert ("crit", "monitor-down") in _categories(sigs)


def test_stale_newest_report_emits_monitor_stale_crit():
    old = (NOW - dt.timedelta(hours=30)).isoformat()
    sigs = _signals([{"generated_at": old}], days=7)
    cats = _categories(sigs)
    assert ("crit", "monitor-stale") in cats
    assert ("crit", "monitor-down") not in cats  # reports exist, just stale


def test_fresh_reports_no_liveness_alarm():
    fresh = (NOW - dt.timedelta(minutes=20)).isoformat()
    sigs = _signals([{"generated_at": fresh}], days=7)
    cats = {c for _, c in _categories(sigs)}
    assert "monitor-down" not in cats
    assert "monitor-stale" not in cats


def test_report_just_under_stale_threshold_is_quiet():
    # 5h < PROBE_STALE_HOURS (6) → no alarm.
    recent = (NOW - dt.timedelta(hours=5)).isoformat()
    sigs = _signals([{"generated_at": recent}], days=7)
    cats = {c for _, c in _categories(sigs)}
    assert "monitor-stale" not in cats


def test_report_missing_generated_at_does_not_crash():
    # A malformed report (no generated_at) must not raise; with no parseable
    # timestamp newest stays None, so no stale alarm and no exception.
    sigs = _signals([{"foo": "bar"}], days=7)
    cats = {c for _, c in _categories(sigs)}
    assert "monitor-down" not in cats  # the list was non-empty
