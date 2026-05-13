"""
core/live_state.py — Estado ao vivo partilhado entre pipeline e dashboard.

Grava logs/live_state.json com o modelo e skill ativos no momento.
Gravação é best-effort: falhas silenciosas para não interromper o pipeline.
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
