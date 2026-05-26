import pytest
import json
import datetime
from java.report_runner import _build_fix_candidates_section


def _iso(dt):
    return dt.isoformat()


def test_no_candidates_returns_empty_string(tmp_path):
    """No permanent_skip entries → empty section (caller drops it)."""
    out = _build_fix_candidates_section([], fixes=[])
    assert out == ""


def test_candidate_listed_when_fix_matches(tmp_path):
    fix_ts = datetime.datetime(2026, 5, 25, 12, 0, 0)
    entries = [
        {
            "file": "/repo/Foo.java", "phase": "p",
            "permanent_skip": True,
            "timestamp": _iso(fix_ts - datetime.timedelta(days=2)),
            "stack_trace": "has private access",
            "reason": "stuck",
        },
    ]
    fixes = [
        {
            "id": "M1",
            "patterns": ["has private access"],
            "applied_at": _iso(fix_ts),
            "description": "Private access handler",
        },
    ]
    out = _build_fix_candidates_section(entries, fixes=fixes)
    assert "Fix Candidates" in out
    assert "Foo.java" in out
    assert "M1" in out
    # Mentions FORCE_RETRY hint
    assert "FORCE_RETRY" in out


def test_entry_newer_than_fix_not_listed():
    """An entry whose timestamp is AFTER the fix's applied_at is not a candidate
    (the fix existed when the failure happened — so the fix doesn't cover this case)."""
    fix_ts = datetime.datetime(2026, 5, 25, 12, 0, 0)
    entries = [
        {
            "file": "/repo/Foo.java", "phase": "p",
            "permanent_skip": True,
            "timestamp": _iso(fix_ts + datetime.timedelta(days=1)),  # AFTER fix
            "stack_trace": "has private access",
            "reason": "stuck",
        },
    ]
    fixes = [
        {
            "id": "M1", "patterns": ["has private access"],
            "applied_at": _iso(fix_ts),
        },
    ]
    out = _build_fix_candidates_section(entries, fixes=fixes)
    # No candidates → empty
    assert out == ""


def test_non_permanent_entries_ignored():
    fix_ts = datetime.datetime(2026, 5, 25)
    entries = [
        {
            "file": "/repo/Foo.java", "phase": "p",
            "permanent_skip": False, "prev_run": True,
            "timestamp": _iso(fix_ts - datetime.timedelta(days=2)),
            "stack_trace": "has private access",
        },
    ]
    fixes = [
        {"id": "M1", "patterns": ["has private access"], "applied_at": _iso(fix_ts)},
    ]
    out = _build_fix_candidates_section(entries, fixes=fixes)
    assert out == ""


def test_multiple_candidates_aggregated():
    fix_ts = datetime.datetime(2026, 5, 25)
    entries = [
        {
            "file": "/repo/Foo.java", "phase": "p",
            "permanent_skip": True,
            "timestamp": _iso(fix_ts - datetime.timedelta(days=2)),
            "stack_trace": "has private access",
        },
        {
            "file": "/repo/Bar.java", "phase": "p",
            "permanent_skip": True,
            "timestamp": _iso(fix_ts - datetime.timedelta(days=3)),
            "stack_trace": "package TransactionStatusCode does not exist",
        },
    ]
    fixes = [
        {"id": "M1", "patterns": ["has private access"], "applied_at": _iso(fix_ts)},
        {"id": "opcao-6", "patterns": ["does not exist"], "applied_at": _iso(fix_ts)},
    ]
    out = _build_fix_candidates_section(entries, fixes=fixes)
    assert "Foo.java" in out
    assert "Bar.java" in out
    assert "M1" in out
    assert "opcao-6" in out


def test_entry_without_timestamp_skipped():
    fix_ts = datetime.datetime(2026, 5, 25)
    entries = [
        {
            "file": "/repo/Foo.java", "phase": "p",
            "permanent_skip": True,
            # no timestamp
            "stack_trace": "has private access",
        },
    ]
    fixes = [
        {"id": "M1", "patterns": ["has private access"], "applied_at": _iso(fix_ts)},
    ]
    out = _build_fix_candidates_section(entries, fixes=fixes)
    assert out == ""
