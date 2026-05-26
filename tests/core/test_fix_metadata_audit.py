import pytest
from core.fix_metadata_audit import (
    get_recent_fix_commits,
    find_unregistered_fixes,
)


def test_find_unregistered_excludes_known():
    commits = ["M1", "M2", "opcao-6", "new-fix"]
    registered = ["M1", "M2", "opcao-6"]
    assert find_unregistered_fixes(commits, registered) == ["new-fix"]


def test_find_unregistered_empty_when_all_known():
    assert find_unregistered_fixes(["M1", "M2"], ["M1", "M2", "M3"]) == []


def test_find_unregistered_deduplicates():
    """Same commit ID appearing multiple times → reported once."""
    commits = ["M5", "M5", "M5", "M1"]
    registered = ["M1"]
    assert find_unregistered_fixes(commits, registered) == ["M5"]


def test_find_unregistered_case_insensitive():
    commits = ["M1", "m2"]
    registered = ["m1", "M2"]
    assert find_unregistered_fixes(commits, registered) == []


def test_find_unregistered_handles_empty_lists():
    assert find_unregistered_fixes([], []) == []
    assert find_unregistered_fixes([], ["M1"]) == []
    assert find_unregistered_fixes(["M1"], []) == ["M1"]


def test_get_recent_fix_commits_returns_list_or_empty(tmp_path):
    """In an empty/non-git dir, returns empty list (no crash)."""
    out = get_recent_fix_commits(cwd=str(tmp_path))
    assert out == []


def test_get_recent_fix_commits_parses_real_git_log(monkeypatch, tmp_path):
    """Simulate git output via monkeypatch on subprocess."""
    import subprocess
    class FakeResult:
        returncode = 0
        stdout = "fix: M99 — new fix added\nfeat: something else\nfix: opcao-7 some title\n"
    def fake_run(*args, **kwargs):
        return FakeResult()
    monkeypatch.setattr(subprocess, "run", fake_run)
    out = get_recent_fix_commits(cwd=str(tmp_path))
    assert "M99" in out
    assert "opcao-7" in out
    assert "feat" not in str(out).lower() or "feat" not in out
