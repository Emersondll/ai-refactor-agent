import pytest
import os
import json
from unittest.mock import patch
from java.refactor import FailedFilesTracker


def _seed(tmp_path, entries):
    p = tmp_path / "failed_files.json"
    p.write_text(json.dumps(entries))
    return str(tmp_path)


def test_force_retry_overrides_permanent_skip(tmp_path, monkeypatch):
    """FORCE_RETRY contains the basename → is_permanent_skip returns False."""
    logs_dir = _seed(tmp_path, [{
        "file": "/repo/src/test/java/com/x/TransactionControllerTest.java",
        "phase": "initial_coverage_fix",
        "permanent_skip": True,
        "fail_count": 3,
        "reason": "stuck",
    }])
    monkeypatch.setenv("FORCE_RETRY", "TransactionControllerTest.java")
    # Reload config to pick up env override
    import importlib, config
    importlib.reload(config)
    import java.refactor
    importlib.reload(java.refactor)
    from java.refactor import FailedFilesTracker
    t = FailedFilesTracker(logs_dir)
    assert t.is_permanent_skip(
        "/repo/src/test/java/com/x/TransactionControllerTest.java",
        "initial_coverage_fix",
    ) is False


def test_force_retry_does_not_affect_other_files(tmp_path, monkeypatch):
    """Only files in FORCE_RETRY get overridden — others stay permanently skipped."""
    logs_dir = _seed(tmp_path, [{
        "file": "/repo/X.java",
        "phase": "p",
        "permanent_skip": True,
        "fail_count": 3,
    }])
    monkeypatch.setenv("FORCE_RETRY", "OtherFile.java")
    import importlib, config
    importlib.reload(config)
    import java.refactor
    importlib.reload(java.refactor)
    from java.refactor import FailedFilesTracker
    t = FailedFilesTracker(logs_dir)
    assert t.is_permanent_skip("/repo/X.java", "p") is True


def test_force_retry_multiple_files(tmp_path, monkeypatch):
    """Comma-separated list works — multiple files overridable in one .env entry."""
    logs_dir = _seed(tmp_path, [
        {"file": "/r/A.java", "phase": "p", "permanent_skip": True, "fail_count": 3},
        {"file": "/r/B.java", "phase": "p", "permanent_skip": True, "fail_count": 3},
        {"file": "/r/C.java", "phase": "p", "permanent_skip": True, "fail_count": 3},
    ])
    monkeypatch.setenv("FORCE_RETRY", "A.java,B.java")
    import importlib, config
    importlib.reload(config)
    import java.refactor
    importlib.reload(java.refactor)
    from java.refactor import FailedFilesTracker
    t = FailedFilesTracker(logs_dir)
    assert t.is_permanent_skip("/r/A.java", "p") is False
    assert t.is_permanent_skip("/r/B.java", "p") is False
    assert t.is_permanent_skip("/r/C.java", "p") is True  # not in FORCE_RETRY


def test_force_retry_handles_whitespace(tmp_path, monkeypatch):
    """Tolerates spaces around commas (common .env mistake)."""
    logs_dir = _seed(tmp_path, [
        {"file": "/r/A.java", "phase": "p", "permanent_skip": True, "fail_count": 3},
    ])
    monkeypatch.setenv("FORCE_RETRY", "  A.java , B.java  ")
    import importlib, config
    importlib.reload(config)
    import java.refactor
    importlib.reload(java.refactor)
    from java.refactor import FailedFilesTracker
    t = FailedFilesTracker(logs_dir)
    assert t.is_permanent_skip("/r/A.java", "p") is False


def test_no_force_retry_preserves_old_behavior(tmp_path, monkeypatch):
    """Without FORCE_RETRY set, is_permanent_skip works exactly as before."""
    logs_dir = _seed(tmp_path, [
        {"file": "/r/X.java", "phase": "p", "permanent_skip": True, "fail_count": 3},
    ])
    monkeypatch.delenv("FORCE_RETRY", raising=False)
    import importlib, config
    importlib.reload(config)
    import java.refactor
    importlib.reload(java.refactor)
    from java.refactor import FailedFilesTracker
    t = FailedFilesTracker(logs_dir)
    assert t.is_permanent_skip("/r/X.java", "p") is True


def test_force_retry_basename_match_not_substring(tmp_path, monkeypatch):
    """Match must be exact basename — 'X.java' must NOT match 'PrefixX.java'."""
    logs_dir = _seed(tmp_path, [
        {"file": "/r/PrefixX.java", "phase": "p", "permanent_skip": True, "fail_count": 3},
    ])
    monkeypatch.setenv("FORCE_RETRY", "X.java")
    import importlib, config
    importlib.reload(config)
    import java.refactor
    importlib.reload(java.refactor)
    from java.refactor import FailedFilesTracker
    t = FailedFilesTracker(logs_dir)
    # PrefixX.java's basename is 'PrefixX.java' != 'X.java' → stays skipped
    assert t.is_permanent_skip("/r/PrefixX.java", "p") is True
