"""
core/live_state.py — Live state shared between pipeline and dashboard.

Writes logs/live_state.json with the currently active model and skill.
Write is best-effort: silent failures to avoid interrupting the pipeline.
"""

import json
import os

_STATE_FILE = os.path.join("logs", "live_state.json")


def update(**kwargs) -> None:
    state = _read()
    state.update(kwargs)
    try:
        os.makedirs("logs", exist_ok=True)
        with open(_STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception:
        pass


def _read() -> dict:
    try:
        if os.path.exists(_STATE_FILE):
            with open(_STATE_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def read() -> dict:
    return _read()
