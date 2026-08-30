from __future__ import annotations

import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from gizmo_friend.prefix import (
    MAX_EPISODES_IN_PREFIX,
    MAX_FACTS_IN_PREFIX,
    MAX_SUMMARY_CHARS,
    PrefixMemory,
)

NOT_NAMES = {
    "gizmo",
    "here",
    "just",
    "not",
    "the",
    "bored",
    "sorry",
    "fine",
    "okay",
    "back",
    "ready",
    "done",
    "good",
    "looking",
    "coming",
    "going",
    "trying",
    "waiting",
    "home",
    "lost",
    "stuck",
    "hungry",
    "tired",
}

NAME_RE = re.compile(
    r"\b(?:i(?:['’]m| am)|my name is|call me|i['’]?m called)\s+([A-Za-z][A-Za-z\-']{1,20})\b",
    re.IGNORECASE,
)
FACT_RE = re.compile(
    r"(?:remember that |remember this |(?:^|\b)I (?:like|love|hate|have|got|collect)\b)",
    re.IGNORECASE,
)
SKIP_FACT_IF_NAME = re.compile(
    r"\b(?:my name is|i(?:['’]m| am) called|call me)\b",
    re.IGNORECASE,
)
RECALL_RE = re.compile(r"\b(yesterday|last time|when we|do you remember)\b", re.IGNORECASE)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Episode:
    id: int
    ts: str
    what: str


@dataclass(frozen=True)
class SavedPage:
    id: str
    subject: str
    line: str
    still_path: str
    created_at: str


class Memory:
    """Local sqlite. Survives restart. Never a vector DB."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _init(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS identity (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    name TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS summary (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    text TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS episodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    what TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS objects (
                    id TEXT PRIMARY KEY,
                    subject TEXT NOT NULL,
                    line TEXT NOT NULL,
                    still_path TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                INSERT OR IGNORE INTO identity (id, name, updated_at)
                    VALUES (1, NULL, '');
                INSERT OR IGNORE INTO summary (id, text, updated_at)
                    VALUES (1, '', '');
                """
            )
            self._conn.commit()

    def prefix_memory(self) -> PrefixMemory:
        with self._lock:
            ident = self._conn.execute("SELECT name FROM identity WHERE id = 1").fetchone()
            facts = [
                row["text"]
                for row in self._conn.execute(
                    "SELECT text FROM facts ORDER BY id DESC LIMIT ?",
                    (MAX_FACTS_IN_PREFIX,),
                )
            ]
            facts.reverse()
            summary_row = self._conn.execute("SELECT text FROM summary WHERE id = 1").fetchone()
            episodes = [
                row["what"]
                for row in self._conn.execute(
                    "SELECT what FROM episodes ORDER BY id DESC LIMIT ?",
                    (MAX_EPISODES_IN_PREFIX,),
                )
            ]
            episodes.reverse()
            objects = [
                f"{row['id']}: {row['line']}"
                for row in self._conn.execute(
                    "SELECT id, line FROM objects ORDER BY created_at DESC"
                )
            ]
        name = ident["name"] if ident and ident["name"] else None
        summary = summary_row["text"] if summary_row else ""
        return PrefixMemory(
            name=name,
            facts=facts,
            summary=summary,
            episodes=episodes,
            objects=objects,
        )

    def get_name(self) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT name FROM identity WHERE id = 1").fetchone()
        if not row:
            return None
        return row["name"] or None

    def set_name(self, name: str) -> None:
        cleaned = name.strip()
        if not cleaned:
            return
        with self._lock:
            self._conn.execute(
                "UPDATE identity SET name = ?, updated_at = ? WHERE id = 1",
                (cleaned, utc_now()),
            )
            self._conn.commit()

    def add_fact(self, text: str) -> None:
        cleaned = text.strip()
        if not cleaned:
            return
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO facts (text, created_at) VALUES (?, ?)",
                (cleaned, utc_now()),
            )
            self._conn.commit()

    def add_episode(self, what: str) -> None:
        cleaned = what.strip()
        if not cleaned:
            return
        with self._lock:
            self._conn.execute(
                "INSERT INTO episodes (ts, what) VALUES (?, ?)",
                (utc_now(), cleaned),
            )
            self._conn.commit()

    def rewrite_summary(self) -> str:
        """End-of-session rewrite from recent episodes. Local, ≤500 tokens."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts, what FROM episodes ORDER BY id DESC LIMIT 20"
            ).fetchall()
        parts = [f"{row['what']}" for row in reversed(list(rows))]
        text = " ".join(parts).strip()[:MAX_SUMMARY_CHARS]
        with self._lock:
            self._conn.execute(
                "UPDATE summary SET text = ?, updated_at = ? WHERE id = 1",
                (text, utc_now()),
            )
            self._conn.commit()
        return text

    def save_page(self, page: SavedPage) -> SavedPage:
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO objects (id, subject, line, still_path, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (page.id, page.subject, page.line, page.still_path, page.created_at),
            )
            self._conn.commit()
        return page

    def last_page(self) -> SavedPage | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM objects ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        if not row:
            return None
        return SavedPage(
            id=row["id"],
            subject=row["subject"],
            line=row["line"],
            still_path=row["still_path"],
            created_at=row["created_at"],
        )

    def get_page(self, page_id: str) -> SavedPage | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM objects WHERE id = ?", (page_id,)
            ).fetchone()
        if not row:
            return None
        return SavedPage(
            id=row["id"],
            subject=row["subject"],
            line=row["line"],
            still_path=row["still_path"],
            created_at=row["created_at"],
        )

    def remember_from_utterance(self, text: str) -> dict[str, str]:
        """Live remember-this path. Updates identity/episodes without shutdown."""
        updates: dict[str, str] = {}
        name_match = NAME_RE.search(text)
        if name_match:
            raw = name_match.group(1)
            if raw.lower() not in NOT_NAMES:
                name = raw[0].upper() + raw[1:]
                self.set_name(name)
                self.add_episode(f"they said their name is {name}")
                updates["name"] = name
        if (
            FACT_RE.search(text)
            and not SKIP_FACT_IF_NAME.search(text)
            and not RECALL_RE.search(text)
        ):
            self.add_fact(text.strip())
            self.add_episode(f"they asked to remember: {text.strip()}")
            updates["fact"] = text.strip()
        return updates
