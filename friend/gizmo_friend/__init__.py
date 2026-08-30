from __future__ import annotations

import os
from pathlib import Path

from gizmo_friend.session import Friend

__all__ = ["Friend"]

REPO_ROOT = Path(__file__).resolve().parents[2]


def default_data_dir() -> Path:
    raw = os.environ.get("GIZMO_DATA_DIR")
    if raw:
        return Path(raw).expanduser()
    return Path.cwd() / "data"
