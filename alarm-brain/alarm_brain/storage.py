"""JSON persistence utilities with atomic writes."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict


def default_state() -> Dict[str, Any]:
    return {
        "version": 1,
        "next_id": 1,
        "alarms": [],
        "timers": [],
    }


def load_state(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return default_state()

    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)

    state = default_state()
    state.update(payload)
    if not isinstance(state.get("alarms"), list):
        state["alarms"] = []
    if not isinstance(state.get("timers"), list):
        state["timers"] = []
    if not isinstance(state.get("next_id"), int):
        state["next_id"] = 1
    return state


def save_state(path: Path, state: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")

    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2, sort_keys=True)

    os.replace(tmp_path, path)
