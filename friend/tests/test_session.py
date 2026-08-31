import asyncio
from pathlib import Path

import pytest

from gizmo_friend.audio_out import BroadcastMouth
from gizmo_friend.body_protocol import Click, Frame, Hold, Navigate, Power, PushToTalk, TextLine
from gizmo_friend.memory import Memory
from gizmo_friend.prompt import AFTER_MAKE, AFTER_SHOW, WAKE_LINE
from gizmo_friend.session import Friend
from gizmo_friend.states import State
from gizmo_friend.tools.show import NullVideo
from gizmo_friend.transport.fake import FakeTransport, _two_sentences, classify


async def drain(friend: Friend, queue: asyncio.Queue, n: int = 20) -> list[dict]:
    events = []
    for _ in range(n):
        try:
            events.append(await asyncio.wait_for(queue.get(), timeout=0.4))
        except TimeoutError:
            break
    return events


def spoken(events: list[dict]) -> str:
    return " ".join(e.get("text") or "" for e in events if e.get("type") == "transcript")


@pytest.mark.asyncio
async def test_wake_interrupt_and_open_talk(tmp_path: Path) -> None:
    cancelled = []

    async def on_text(text: str) -> None:
        del text

    mouth = BroadcastMouth(on_text=on_text)
    original_cancel = mouth.cancel

    def cancel() -> None:
        cancelled.append(True)
        original_cancel()

    mouth.cancel = cancel  # type: ignore[method-assign]
    friend = Friend(tmp_path, mouth=mouth, video=NullVideo(), openai_key="", show_hold_s=0)
    queue = friend.subscribe()
    await friend.handle(Click())
    events = await drain(friend, queue)
    assert friend.state in {State.LISTENING, State.TALKING}
    assert WAKE_LINE in spoken(events)
    assert "name" in spoken(events).lower()

    friend.machine.state = State.TALKING
    await friend.on_click()
    assert friend.state is State.LISTENING
    assert cancelled

    await friend.handle(TextLine("I'm bored"))
    events = await drain(friend, queue)
    talk = spoken(events)
    assert talk
    assert len(_two_sentences(talk).split(".")) <= 3
    await friend.close()


@pytest.mark.asyncio
async def test_pinecone_use_case_and_memory_restart(tmp_path: Path) -> None:
    friend = Friend(tmp_path, video=NullVideo(), openai_key="", show_hold_s=0)
    queue = friend.subscribe()
    await friend.handle(Click())
    await drain(friend, queue)
    await friend.handle(TextLine("I'm Rio"))
    await drain(friend, queue)
    await friend.handle(TextLine("I have a dog named Toast"))
    await drain(friend, queue)
    await friend.handle(Frame(hint="a pinecone on the table"))
    await friend.handle(TextLine("what is this"))
    events = await drain(friend, queue)
    assert "pinecone" in spoken(events).lower()
    await friend.handle(TextLine("show me"))
    events = await drain(friend, queue)
    assert AFTER_SHOW in spoken(events)
    glass = [e for e in events if e.get("type") == "glass"]
    assert glass
    assert glass[0].get("clips") == []
    assert glass[0].get("still")
    assert glass[0].get("screen") is True
    await friend.handle(TextLine("keep it"))
    events = await drain(friend, queue)
    assert AFTER_MAKE in spoken(events)
    page = friend.memory.last_page()
    assert page is not None
    assert page.subject == "pinecone"
    assert page.line == "pinecone"
    await friend.handle(Hold())
    events = await drain(friend, queue)
    assert friend.outbox.list_pages()
    await friend.close()

    again = Friend(tmp_path, video=NullVideo(), openai_key="", show_hold_s=0)
    prefix = again.memory.prefix_memory()
    assert prefix.name == "Rio"
    assert any("Toast" in f for f in prefix.facts)
    assert again.memory.last_page() is not None
    await again.close()

    # sqlite file itself
    mem = Memory(tmp_path / "gizmo.db")
    assert mem.get_name() == "Rio"
    mem.close()


@pytest.mark.asyncio
async def test_nonsense_and_remember_yesterday(tmp_path: Path) -> None:
    friend = Friend(tmp_path, video=NullVideo(), openai_key="", show_hold_s=0)
    queue = friend.subscribe()
    await friend.handle(Click())
    await drain(friend, queue)
    await friend.handle(TextLine("blorp zarf nine thousand bees"))
    events = await drain(friend, queue)
    assert spoken(events)
    await friend.handle(TextLine("do you remember yesterday"))
    events = await drain(friend, queue)
    # no pretend memory
    assert "don't have that" in spoken(events).lower() or "tell me again" in spoken(events).lower()
    await friend.close()


@pytest.mark.asyncio
async def test_fake_transport_keeps_frozen_instructions(tmp_path: Path) -> None:
    friend = Friend(tmp_path, video=NullVideo(), openai_key="", show_hold_s=0)
    await friend.handle(Click())
    assert friend.transport_name == "fake"
    assert friend._transport is not None
    assert isinstance(friend._transport, FakeTransport)
    assert friend._transport.instructions.startswith("You are Gizmo")
    await friend.close()


@pytest.mark.asyncio
async def test_power_and_navigation_use_the_body_protocol(tmp_path: Path) -> None:
    friend = Friend(tmp_path, video=NullVideo(), openai_key="", show_hold_s=0)
    queue = friend.subscribe()

    await friend.handle(Power(on=True))
    await drain(friend, queue)
    assert friend.state is State.LISTENING

    await friend.handle(Click())
    events = await drain(friend, queue)
    assert friend.state is State.LISTENING
    assert any(event.get("type") == "select" for event in events)

    await friend.handle(PushToTalk(active=True))
    events = await drain(friend, queue)
    assert any(event.get("type") == "ptt" and event.get("active") is True for event in events)

    await friend.handle(Navigate(direction="left"))
    events = await drain(friend, queue)
    assert any(event.get("type") == "navigate" and event.get("direction") == "left" for event in events)

    await friend.handle(Power(on=False))
    await drain(friend, queue)
    assert friend.state is State.ASLEEP
    await friend.close()


def test_classify_does_not_require_pinecone() -> None:
    assert classify("I'm bored")[0] == "talk"
    assert classify("what is this")[0] == "see"
    assert classify("show me the spell")[0] == "show"
