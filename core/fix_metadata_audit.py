"""
core/fix_metadata_audit.py — boot-time check.

Reads recent `fix:` commits via `git log` and reports any whose identifier
doesn't appear in `logs/fix_metadata.json`. Pure read-only.
"""

import re
import subprocess
from datetime import datetime, timedelta


_FIX_RE = re.compile(r'^fix:\s*([\w\-+/]+)', re.MULTILINE)


def get_recent_fix_commits(days: int = 7, cwd: str = ".") -> list[str]:
    """Return the list of fix identifiers from `git log` over the last N days.
    Each ID is the first token after 'fix: ' in the commit subject.
    Returns [] if git is unavailable or no commits."""
    try:
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        result = subprocess.run(
            ["git", "log", f"--since={since}", "--format=%s"],
            cwd=cwd, capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return []
        ids: list[str] = []
        for line in result.stdout.splitlines():
            m = _FIX_RE.match(line.strip())
            if m:
                ids.append(m.group(1).rstrip(":").rstrip(","))
        return ids
    except Exception:
        return []


def find_unregistered_fixes(commit_ids: list[str], registered_ids: list[str]) -> list[str]:
    """Return commit_ids that don't appear in registered_ids.
    Case-insensitive comparison, also tolerates trailing dashes."""
    registered_set = {r.lower().rstrip("-") for r in registered_ids}
    seen: set[str] = set()
    out: list[str] = []
    for cid in commit_ids:
        norm = cid.lower().rstrip("-")
        if norm in registered_set or norm in seen:
            continue
        seen.add(norm)
        out.append(cid)
    return out


def audit_fix_metadata(cwd: str = ".") -> list[str]:
    """Top-level: return list of fix IDs in recent commits but not in fix_metadata.json.
    Returns [] on any error."""
    try:
        from java.fix_metadata import get_fixes
        registered = [f.get("id", "") for f in get_fixes()]
    except Exception:
        registered = []
    recent = get_recent_fix_commits(cwd=cwd)
    return find_unregistered_fixes(recent, registered)
