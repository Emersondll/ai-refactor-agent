import pytest
import json
import datetime
from java.refactor import FailedFilesTracker


def _seed(tmp_path, entries):
    p = tmp_path / "failed_files.json"
    p.write_text(json.dumps(entries))
    return str(tmp_path)


def _iso(dt: datetime.datetime) -> str:
    return dt.isoformat()


def test_default_threshold_is_3(monkeypatch):
    monkeypatch.delenv("MAX_FAILS_initial_coverage_fix", raising=False)
    monkeypatch.delenv("MAX_FAILS_javadoc", raising=False)
    import importlib, java.refactor
    importlib.reload(java.refactor)
    from java.refactor import _threshold_for
    assert _threshold_for("initial_coverage_fix") == 3
    assert _threshold_for("javadoc") == 3
    assert _threshold_for("anything_else") == 3


def test_phase_specific_env_overrides_default(monkeypatch):
    monkeypatch.setenv("MAX_FAILS_initial_coverage_fix", "5")
    monkeypatch.setenv("MAX_FAILS_javadoc", "1")
    import importlib, java.refactor
    importlib.reload(java.refactor)
    from java.refactor import _threshold_for
    assert _threshold_for("initial_coverage_fix") == 5
    assert _threshold_for("javadoc") == 1
    assert _threshold_for("post_solid_dip_coverage") == 3


def test_threshold_promotes_at_phase_specific_count(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_FAILS_initial_coverage_fix", "5")
    import importlib, java.refactor
    importlib.reload(java.refactor)
    from java.refactor import FailedFilesTracker
    logs_dir = _seed(tmp_path, [
        {"file": "/r/X.java", "phase": "initial_coverage_fix", "fail_count": 4,
         "retried": False, "prev_run": True, "timestamp": _iso(datetime.datetime.now())},
    ])
    t = FailedFilesTracker(logs_dir)
    t.record("/r/X.java", "initial_coverage_fix", "another fail")
    new_entry = next(e for e in t._entries
                     if e["file"] == "/r/X.java" and not e.get("prev_run"))
    assert new_entry["fail_count"] == 5
    assert new_entry.get("permanent_skip") is True


def test_threshold_promotes_immediately_with_one(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_FAILS_javadoc", "1")
    import importlib, java.refactor
    importlib.reload(java.refactor)
    from java.refactor import FailedFilesTracker
    logs_dir = _seed(tmp_path, [])
    t = FailedFilesTracker(logs_dir)
    t.record("/r/X.java", "javadoc", "first fail")
    new_entry = next(e for e in t._entries
                     if e["file"] == "/r/X.java" and not e.get("prev_run"))
    assert new_entry["fail_count"] == 1
    assert new_entry.get("permanent_skip") is True


def test_invalid_env_value_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("MAX_FAILS_javadoc", "not_a_number")
    import importlib, java.refactor
    importlib.reload(java.refactor)
    from java.refactor import _threshold_for
    assert _threshold_for("javadoc") == 3
