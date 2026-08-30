from pathlib import Path

import pytest

from gizmo_friend.body_protocol import WorldCamera
from gizmo_friend.memory import Memory
from gizmo_friend.tools.allowlist import ALLOWED_TOOLS, FORBIDDEN_TOOLS, TOOL_SCHEMAS, assert_allowlist
from gizmo_friend.tools.make import make
from gizmo_friend.tools.reach import reach
from gizmo_friend.tools.see import see
from gizmo_friend.tools.show import NullVideo, show
from gizmo_reach.outbox import ParentOutbox


def test_allowlist_is_exactly_four() -> None:
    names = assert_allowlist()
    assert tuple(names) == ALLOWED_TOOLS
    assert "web_search" not in names
    for forbidden in FORBIDDEN_TOOLS:
        assert forbidden not in names


def test_allowlist_rejects_web() -> None:
    with pytest.raises(ValueError, match="not on allowlist"):
        assert_allowlist([{"name": "web_search", "type": "function"}])


@pytest.mark.asyncio
async def test_see_names_injected_frame() -> None:
    cam = WorldCamera()
    cam.inject(hint="a pinecone on the table")
    result = await see(cam)
    assert "pinecone" in result["beat"].lower()


@pytest.mark.asyncio
async def test_show_still_and_at_most_two_clips(tmp_path: Path) -> None:
    class TwoClips(NullVideo):
        def __init__(self) -> None:
            self.n = 0

        async def clip(self, subject: str, still_svg: str) -> str | None:
            self.n += 1
            return f"https://example.test/clip-{self.n}.mp4"

    result = await show("pinecone", tmp_path / "media", video=TwoClips())
    assert Path(result["still"]).exists()
    assert len(result["clips"]) == 2
    svg = Path(result["still"]).read_text()
    assert "ellipse" in svg
    assert "photoreal" not in svg.lower()


@pytest.mark.asyncio
async def test_show_skips_clips_without_fal(tmp_path: Path) -> None:
    result = await show("leaf", tmp_path / "media", video=NullVideo())
    assert result["clips"] == []
    assert Path(result["still"]).exists()


def test_make_persists(tmp_path: Path) -> None:
    mem = Memory(tmp_path / "gizmo.db")
    page = make(mem, tmp_path / "media", line="A pinecone we kept.", subject="pinecone")
    assert mem.last_page() is not None
    assert mem.last_page().line == page.line
    assert Path(page.still_path).exists()
    mem.close()


def test_reach_fail_soft_without_page(tmp_path: Path) -> None:
    outbox = ParentOutbox(tmp_path / "outbox.jsonl")
    result = reach(outbox, None)
    assert result["ok"] is False
    assert outbox.list_pages() == []


def test_reach_queues(tmp_path: Path) -> None:
    mem = Memory(tmp_path / "gizmo.db")
    page = make(mem, tmp_path / "media", line="Yours.", subject="rock")
    outbox = ParentOutbox(tmp_path / "outbox.jsonl")
    result = reach(outbox, page)
    assert result["ok"] is True
    queued = outbox.list_pages()
    assert queued[0].line == "Yours."
    mem.close()


def test_no_web_in_schemas() -> None:
    blob = str(TOOL_SCHEMAS).lower()
    assert "web_search" not in blob
    assert "mcp" not in blob
