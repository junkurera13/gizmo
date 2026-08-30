from __future__ import annotations

import uuid
from pathlib import Path

from gizmo_friend.memory import Memory, SavedPage, utc_now
from gizmo_friend.tools.print_still import render_still


def make(
    memory: Memory,
    media_dir: Path,
    line: str,
    subject: str = "",
    still_path: str | None = None,
) -> SavedPage:
    """Persist a page. Instant. Local."""
    cleaned_line = line.strip()
    if not cleaned_line:
        raise ValueError("make needs a line")
    cleaned_subject = subject.strip() or "page"
    media_dir = Path(media_dir)
    media_dir.mkdir(parents=True, exist_ok=True)

    path = still_path
    if not path or not Path(path).exists():
        svg = render_still(cleaned_subject)
        dest = media_dir / f"page-{uuid.uuid4().hex[:8]}.svg"
        dest.write_text(svg, encoding="utf-8")
        path = str(dest)

    page = SavedPage(
        id=uuid.uuid4().hex[:12],
        subject=cleaned_subject,
        line=cleaned_line,
        still_path=path,
        created_at=utc_now(),
    )
    memory.save_page(page)
    memory.add_episode(f"kept a page: {cleaned_line}")
    return page
