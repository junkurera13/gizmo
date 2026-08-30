from __future__ import annotations

from gizmo_friend.memory import SavedPage
from gizmo_reach.outbox import OutboxPage, ParentOutbox, now_iso


def reach(outbox: ParentOutbox, page: SavedPage | None) -> dict:
    """Queue the page to the parent-phone outbox. Not a live call. Fail soft."""
    if page is None:
        return {"ok": False, "reason": "no page yet"}
    try:
        outbox.enqueue(
            OutboxPage(
                page_id=page.id,
                subject=page.subject,
                line=page.line,
                still_path=page.still_path,
                queued_at=now_iso(),
            )
        )
    except OSError as exc:
        return {"ok": False, "reason": str(exc)}
    return {"ok": True, "page_id": page.id}
