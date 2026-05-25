"""
fix_metadata.py — java/fix_metadata.py

Fix-metadata registry: each pipeline fix can register itself with a list of
error-message patterns it knows how to resolve, plus the timestamp it was
applied. FailedFilesTracker.reset() consults this registry to auto-expire
permanent_skip entries whose timestamp predates a fix that would have
prevented or repaired the failure.

The file lives at `logs/fix_metadata.json` (created on first write).
"""

import json
import os
from datetime import datetime

METADATA_FILENAME = "fix_metadata.json"
_DEFAULT_PATH = os.path.join("logs", METADATA_FILENAME)


def _load(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save(path: str, fixes: list[dict]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(fixes, f, indent=2, ensure_ascii=False)


def register_fix(
    fix_id: str,
    patterns: list[str],
    description: str = "",
    path: str = _DEFAULT_PATH,
    applied_at: str | None = None,
) -> None:
    """Register or update a fix in the metadata file. Idempotent by fix_id."""
    fixes = _load(path)
    entry = {
        "id": fix_id,
        "patterns": list(patterns),
        "description": description,
        "applied_at": applied_at or datetime.now().isoformat(),
    }
    # Update existing by id, else append
    for i, f in enumerate(fixes):
        if f.get("id") == fix_id:
            fixes[i] = entry
            break
    else:
        fixes.append(entry)
    _save(path, fixes)


def get_fixes(path: str = _DEFAULT_PATH) -> list[dict]:
    return _load(path)


def find_entries_to_expire(
    entries: list[dict],
    path: str = _DEFAULT_PATH,
) -> list[str]:
    """Return the list of file paths whose permanent_skip entry should be expired.

    An entry is expirable when:
      - permanent_skip is True
      - timestamp is parseable AND predates the applied_at of some registered fix
      - that fix has at least one pattern present in stack_trace + reason
    """
    fixes = get_fixes(path)
    if not fixes:
        return []

    expired_files: list[str] = []
    for entry in entries:
        if not entry.get("permanent_skip"):
            continue
        ts_raw = entry.get("timestamp")
        if not ts_raw:
            continue
        try:
            entry_ts = datetime.fromisoformat(ts_raw)
        except Exception:
            continue
        haystack = (entry.get("stack_trace") or "") + " " + (entry.get("reason") or "")
        for fix in fixes:
            try:
                fix_ts = datetime.fromisoformat(fix.get("applied_at", ""))
            except Exception:
                continue
            if entry_ts >= fix_ts:
                continue  # entry is newer than the fix → don't expire
            if any(pat in haystack for pat in fix.get("patterns", [])):
                expired_files.append(entry["file"])
                break  # one matching fix is enough
    return expired_files
