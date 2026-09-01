from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from gizmo_friend.brain.memory import MemoryMessage


@dataclass(frozen=True)
class TranscriptEntry:
    session_id: str
    user_id: str
    role: Literal["user", "assistant"]
    text: str
    created_at: str


class TranscriptStore:
    """Append-only final transcripts for debugging, memory, and future analytics."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._messages: list[MemoryMessage] = []

    def append(
        self,
        *,
        session_id: str,
        user_id: str,
        role: Literal["user", "assistant"],
        text: str,
    ) -> None:
        cleaned = " ".join(text.split()).strip()
        if not cleaned:
            return
        # Wake greetings are useful in the debug log but not as standalone
        # memory. A first user turn starts the memory segment cleanly.
        if role == "user" and not any(message["role"] == "user" for message in self._messages):
            self._messages.clear()
        entry = TranscriptEntry(
            session_id=session_id,
            user_id=user_id,
            role=role,
            text=cleaned,
            created_at=datetime.now(UTC).isoformat(),
        )
        path = self.directory / f"{session_id}.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
        self._messages.append({"role": role, "content": cleaned})

    def take_completed_turns(self) -> list[MemoryMessage]:
        """Return complete user/assistant pairs, retaining an unmatched user turn."""

        last_assistant = -1
        saw_user = False
        for index, message in enumerate(self._messages):
            if message["role"] == "user":
                saw_user = True
            elif saw_user:
                last_assistant = index
        if last_assistant < 0:
            return []
        completed = self._messages[: last_assistant + 1]
        self._messages = self._messages[last_assistant + 1 :]
        return completed
