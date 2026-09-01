from pathlib import Path

import pytest

from gizmo_friend.body_protocol import WorldCamera
from gizmo_friend.memory import Memory
from gizmo_friend.tools.allowlist import (
    ALLOWED_TOOLS,
    FUTURE_MEDIA_TOOLS,
    RETIRED_AGENT_TOOLS,
    TOOL_SCHEMAS,
    assert_allowlist,
)
from gizmo_friend.tools.make import make
from gizmo_friend.tools.reach import reach
from gizmo_friend.tools.see import see
from gizmo_friend.tools.show import NullVideo, show
from gizmo_reach.outbox import ParentOutbox


def test_agent_allowlist_is_exactly_v1_tools() -> None:
    names = assert_allowlist()
    assert tuple(names) == ALLOWED_TOOLS
    assert names == ["deep_think", "set_expression"]
    assert not set(RETIRED_AGENT_TOOLS).intersection(names)
    assert FUTURE_MEDIA_TOOLS == ("show_image", "show_video")


def test_allowlist_rejects_custom_search() -> None:
    with pytest.raises(ValueError, match="not on allowlist"):
        assert_allowlist([{"name": "search", "type": "function"}])


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


@pytest.mark.asyncio
async def test_think_returns_answer_from_backend() -> None:
    from gizmo_friend.tools.think import ThinkBackend, think

    class CannedThink(ThinkBackend):
        async def answer(self, question: str) -> str | None:
            return f"Short true answer about: {question}"

    result = await think(CannedThink(), "why is the sky blue?")
    assert result["ok"] is True
    assert "sky blue" in result["answer"]


@pytest.mark.asyncio
async def test_think_fails_soft_offline() -> None:
    from gizmo_friend.tools.think import NullThink, think

    result = await think(NullThink(), "why is the sky blue?")
    assert result["ok"] is False
    assert "say" in result
    # He never pretends: the fallback admits he can't reach the deep mind.
    assert "can't reach" in result["say"].lower()

    empty = await think(NullThink(), "   ")
    assert empty["ok"] is False


def test_think_backend_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    from gizmo_friend.tools.think import (
        NullThink,
        OpenAIThink,
        OpenRouterThink,
        think_backend_from_env,
    )

    assert isinstance(think_backend_from_env(), NullThink)

    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    backend = think_backend_from_env()
    assert isinstance(backend, OpenRouterThink)
    assert backend.model == "openai/gpt-5.6-terra"

    # OpenAI key wins when both are present.
    assert isinstance(think_backend_from_env(api_key="oa-key"), OpenAIThink)


def test_openrouter_chat_parsing() -> None:
    from gizmo_friend.tools.think import _chat_text

    good = {"choices": [{"message": {"content": "Blue light scatters the most."}}]}
    assert _chat_text(good) == "Blue light scatters the most."
    assert _chat_text({"choices": []}) is None
    assert _chat_text({"choices": [{"message": {"content": "  "}}]}) is None
    assert _chat_text("nope") is None


def test_search_is_not_a_custom_function_schema() -> None:
    blob = str(TOOL_SCHEMAS).lower()
    assert "google_search" not in blob
    assert "deep_think" in blob
