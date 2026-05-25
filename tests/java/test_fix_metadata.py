import pytest
import json
import os
from datetime import datetime, timedelta
from java.fix_metadata import (
    register_fix,
    get_fixes,
    find_entries_to_expire,
    METADATA_FILENAME,
)


def _isoformat(dt: datetime) -> str:
    return dt.isoformat()


def test_register_appends_to_metadata(tmp_path):
    path = str(tmp_path / METADATA_FILENAME)
    register_fix("opcao-6", ["does not exist"], "Project-wide import map", path=path)
    register_fix("M1", ["has private access"], "Private member handler", path=path)
    fixes = get_fixes(path=path)
    assert len(fixes) == 2
    ids = {f["id"] for f in fixes}
    assert ids == {"opcao-6", "M1"}


def test_register_idempotent(tmp_path):
    """Registering the same fix id twice updates rather than duplicates."""
    path = str(tmp_path / METADATA_FILENAME)
    register_fix("opcao-6", ["does not exist"], path=path)
    register_fix("opcao-6", ["does not exist", "added pattern"], path=path)
    fixes = get_fixes(path=path)
    assert len(fixes) == 1
    assert "added pattern" in fixes[0]["patterns"]


def test_get_fixes_returns_empty_when_no_file(tmp_path):
    path = str(tmp_path / METADATA_FILENAME)
    assert get_fixes(path=path) == []


def test_find_entries_to_expire_by_pattern_and_timestamp(tmp_path):
    """Entry with timestamp BEFORE fix.applied_at AND pattern matching → expire."""
    path = str(tmp_path / METADATA_FILENAME)
    fix_time = datetime(2026, 5, 24, 15, 0, 0)
    register_fix(
        "opcao-6", ["does not exist"], "import map",
        path=path, applied_at=_isoformat(fix_time),
    )
    entries = [
        {
            "file": "/x/A.java", "phase": "init",
            "timestamp": _isoformat(fix_time - timedelta(days=1)),
            "permanent_skip": True,
            "stack_trace": "package TransactionStatusCode does not exist",
            "reason": "build broke",
        },
        {
            "file": "/x/B.java", "phase": "init",
            "timestamp": _isoformat(fix_time + timedelta(hours=1)),  # AFTER fix
            "permanent_skip": True,
            "stack_trace": "package Foo does not exist",
            "reason": "build broke",
        },
        {
            "file": "/x/C.java", "phase": "init",
            "timestamp": _isoformat(fix_time - timedelta(days=2)),
            "permanent_skip": True,
            "stack_trace": "unrelated error",
            "reason": "other",
        },
    ]
    expired = find_entries_to_expire(entries, path=path)
    # A: timestamp before fix AND pattern matches → expire
    # B: timestamp after fix (fix didn't exist yet when this failed... but it does now) →
    #    actually we want B expired too if it would benefit. Let me reconsider.
    # For SIMPLICITY this initial version: only entries with timestamp BEFORE fix.applied_at
    # are expired. Entries AFTER the fix are kept (they failed even with the fix in place).
    assert "/x/A.java" in expired
    assert "/x/B.java" not in expired
    assert "/x/C.java" not in expired


def test_non_permanent_skip_entries_not_expired(tmp_path):
    """Entries without permanent_skip: True are ignored."""
    path = str(tmp_path / METADATA_FILENAME)
    register_fix("M1", ["has private access"], path=path,
                 applied_at=_isoformat(datetime(2026, 5, 25)))
    entries = [
        {
            "file": "/x/A.java", "phase": "init",
            "timestamp": _isoformat(datetime(2026, 5, 20)),
            "permanent_skip": False,  # not permanent
            "stack_trace": "validateInput has private access",
        },
    ]
    expired = find_entries_to_expire(entries, path=path)
    assert expired == []


def test_pattern_match_in_reason_field(tmp_path):
    """Patterns also match against the 'reason' field, not just stack_trace."""
    path = str(tmp_path / METADATA_FILENAME)
    register_fix("opcao-X", ["O arquivo se chama"], path=path,
                 applied_at=_isoformat(datetime(2026, 5, 25)))
    entries = [
        {
            "file": "/x/A.java", "phase": "init",
            "timestamp": _isoformat(datetime(2026, 5, 20)),
            "permanent_skip": True,
            "reason": "INTEGRITY ERROR: O arquivo se chama 'X.java' mas você gerou 'Y'",
            # no stack_trace
        },
    ]
    expired = find_entries_to_expire(entries, path=path)
    assert "/x/A.java" in expired


def test_multiple_fixes_only_one_needs_to_match(tmp_path):
    """If ANY registered fix would expire the entry, it's expired."""
    path = str(tmp_path / METADATA_FILENAME)
    register_fix("fix1", ["pattern-X"], path=path,
                 applied_at=_isoformat(datetime(2026, 5, 25)))
    register_fix("fix2", ["pattern-Y"], path=path,
                 applied_at=_isoformat(datetime(2026, 5, 25)))
    entries = [
        {
            "file": "/x/A.java", "phase": "init",
            "timestamp": _isoformat(datetime(2026, 5, 20)),
            "permanent_skip": True,
            "stack_trace": "error with pattern-Y here",
        },
    ]
    expired = find_entries_to_expire(entries, path=path)
    assert "/x/A.java" in expired


def test_entry_without_timestamp_not_expired(tmp_path):
    """Defensive: if entry has no timestamp, don't expire (can't compare)."""
    path = str(tmp_path / METADATA_FILENAME)
    register_fix("fix1", ["pattern"], path=path,
                 applied_at=_isoformat(datetime(2026, 5, 25)))
    entries = [
        {
            "file": "/x/A.java", "phase": "init",
            # no timestamp
            "permanent_skip": True,
            "stack_trace": "pattern here",
        },
    ]
    expired = find_entries_to_expire(entries, path=path)
    assert expired == []
