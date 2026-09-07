"""Durable daily media reservations, shared by every session on this brain."""

from __future__ import annotations

import fcntl
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from gizmo_friend.brain.shows import _atomic_write, valid_device_id


class ShowBudget:
    counter = "shows"
    ledger_name = "show-usage"
    device_default = 40
    global_default = 400
    environment_name = "GIZMO_DAILY_SHOW_LIMIT"

    def __init__(self, data_root: Path, *, device_limit: int | None = None, global_limit: int | None = None) -> None:
        self.root = Path(data_root)
        self.device_limit = max(0, self.device_default if device_limit is None else device_limit)
        self.global_limit = max(0, global_limit if global_limit is not None else int(
            os.environ.get(self.environment_name, str(self.global_default))
        ))

    def reserve(self, device_id: str) -> bool:
        """Reserve before spending; failed/superseded calls still consume a slot.

        Run outside the event loop. The lock also covers multiple server/CLI
        processes, and a restart reads the same authoritative daily ledger.
        """
        if not valid_device_id(device_id):
            raise ValueError("invalid device id")
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / f".{self.ledger_name}.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            path = self.root / f"{self.ledger_name}.json"
            today = datetime.now(UTC).date().isoformat()
            if path.exists():
                ledger = json.loads(path.read_text())
            else:
                ledger = {}
            if ledger.get("day") != today:
                ledger = {"day": today, self.counter: 0, "devices": {}}
            used = ledger["devices"].get(device_id, 0)
            if used >= self.device_limit or ledger[self.counter] >= self.global_limit:
                return False
            ledger["devices"][device_id] = used + 1
            ledger[self.counter] += 1
            # Commit the global ledger first. If a device mirror fails, this
            # reservation remains spent; a crash cannot grant extra calls.
            _atomic_write(path, (json.dumps(ledger) + "\n").encode())
            device_path = self.root / "devices" / device_id / f"{self.ledger_name}.json"
            _atomic_write(device_path, (json.dumps({"day": today, self.counter: used + 1}) + "\n").encode())
            return True


class MotionBudget(ShowBudget):
    counter = "motions"
    ledger_name = "motion-usage"
    device_default = 20
    global_default = 200
    environment_name = "GIZMO_DAILY_MOTION_LIMIT"


class OddityTurnBudget(ShowBudget):
    """Bound public-preview planning, transcription, and narration spend."""

    counter = "turns"
    ledger_name = "oddity-turn-usage"
    device_default = 16
    global_default = 120
    environment_name = "ODDITY_DAILY_TURN_LIMIT"


class OddityShowBudget(ShowBudget):
    counter = "shows"
    ledger_name = "oddity-show-usage"
    device_default = 8
    global_default = 80
    environment_name = "ODDITY_DAILY_SHOW_LIMIT"


class OddityMotionBudget(ShowBudget):
    counter = "motions"
    ledger_name = "oddity-motion-usage"
    device_default = 4
    global_default = 20
    environment_name = "ODDITY_DAILY_MOTION_LIMIT"
