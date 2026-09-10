from __future__ import annotations

import os
from pathlib import Path

from gizmo_friend.session import GizmoSession

__all__ = ["GizmoSession"]


def default_data_dir() -> Path:
    raw = os.environ.get("GIZMO_DATA_DIR")
    if raw:
        return Path(raw).expanduser()
    return Path.cwd() / "data"
