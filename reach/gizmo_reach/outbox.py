from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class OutboxPage:
    page_id: str
    subject: str
    line: str
    still_path: str
    queued_at: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


class ParentOutbox:
    """Append-only local stub of the parent-phone queue. Fail soft at the caller."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def enqueue(self, page: OutboxPage) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(page.to_json() + "\n")

    def list_pages(self) -> list[OutboxPage]:
        if not self.path.exists():
            return []
        pages: list[OutboxPage] = []
        for raw in self.path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            data = json.loads(raw)
            pages.append(OutboxPage(**data))
        return pages


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
