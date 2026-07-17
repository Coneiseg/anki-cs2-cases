"""Atomic JSON persistence for the player's state.

Kept Anki-free: callers pass an explicit path (the add-on points it at
``user_files/state.json`` so progress survives add-on updates).
"""
from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Dict

from . import economy


def _merge_defaults(state: Dict[str, Any]) -> Dict[str, Any]:
    """Fill any keys missing from an older/partial state with fresh defaults."""
    base = economy.new_state()
    for key, default in base.items():
        state.setdefault(key, default)
    for key, default in base["stats"].items():
        state["stats"].setdefault(key, default)
    return state


def load(path: str) -> Dict[str, Any]:
    """Load state, or return a fresh state. A corrupt file is backed up, not lost."""
    if not os.path.exists(path):
        return economy.new_state()
    try:
        with open(path, encoding="utf-8") as f:
            return _merge_defaults(json.load(f))
    except (ValueError, OSError):
        try:
            os.replace(path, path + ".corrupt")
        except OSError:
            pass
        return economy.new_state()


def save(path: str, state: Dict[str, Any]) -> None:
    """Write state atomically: serialize to a temp file in the same dir, then
    ``os.replace`` it into place so a crash mid-write can't corrupt the real file."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".state-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
