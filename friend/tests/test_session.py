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
    friend = Friend(tmp_path, mouth=mouth, video=NullVideo(), openai_key="", show_hold_s=0, boot_s=0)
    queue = friend.subscribe()
    await friend.handle(Power(on=True))
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
    friend = Friend(tmp_path, video=NullVideo(), openai_key="", show_hold_s=0, boot_s=0)
    queue = friend.subscribe()
    await friend.handle(Power(on=True))
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

    again = Friend(tmp_path, video=NullVideo(), openai_key="", show_hold_s=0, boot_s=0)
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
    friend = Friend(tmp_path, video=NullVideo(), openai_key="", show_hold_s=0, boot_s=0)
    queue = friend.subscribe()
    await friend.handle(Power(on=True))
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
    friend = Friend(tmp_path, video=NullVideo(), openai_key="", show_hold_s=0, boot_s=0)
    await friend.handle(Power(on=True))
    assert friend._boot_task is not None
    await friend._boot_task
    assert friend.transport_name == "fake"
    assert friend._transport is not None
    assert isinstance(friend._transport, FakeTransport)
    assert friend._transport.instructions.startswith("You are Gizmo")
    await friend.close()


@pytest.mark.asyncio
async def test_power_and_navigation_use_the_body_protocol(tmp_path: Path) -> None:
    friend = Friend(tmp_path, video=NullVideo(), openai_key="", show_hold_s=0, boot_s=0)
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
    await friend.handle(Click())
    events = await drain(friend, queue)
    assert friend.state is State.ASLEEP
    assert not any(event.get("type") == "select" for event in events)
    await friend.close()


@pytest.mark.asyncio
async def test_hard_question_goes_through_think(tmp_path: Path) -> None:
    from gizmo_friend.tools.think import ThinkBackend

    class CannedThink(ThinkBackend):
        def __init__(self) -> None:
            self.asked: list[str] = []

        async def answer(self, question: str) -> str | None:
            self.asked.append(question)
            return "Sunlight scatters in the air, and blue scatters the most."

    thinker = CannedThink()
    friend = Friend(
        tmp_path, video=NullVideo(), openai_key="", show_hold_s=0, boot_s=0, thinker=thinker
    )
    queue = friend.subscribe()
    await friend.handle(Power(on=True))
    await drain(friend, queue)

    await friend.handle(TextLine("why is the sky blue?"))
    events = await drain(friend, queue)

    assert thinker.asked == ["why is the sky blue?"]
    states = [e.get("state") for e in events]
    assert "thinking" in states
    assert "scatters" in spoken(events)
    assert friend.state is State.LISTENING
    tool_events = [e for e in events if e.get("type") == "tool" and e.get("name") == "think"]
    assert tool_events and tool_events[0]["result"]["ok"] is True
    await friend.close()


@pytest.mark.asyncio
async def test_think_fails_soft_without_cloud(tmp_path: Path) -> None:
    friend = Friend(tmp_path, video=NullVideo(), openai_key="", show_hold_s=0, boot_s=0)
    queue = friend.subscribe()
    await friend.handle(Power(on=True))
    await drain(friend, queue)

    await friend.handle(TextLine("explain black holes"))
    events = await drain(friend, queue)
    # NullThink offline: he admits it instead of pretending.
    assert "can't reach" in spoken(events).lower()
    assert friend.state is State.LISTENING
    await friend.close()


@pytest.mark.asyncio
async def test_double_click_opens_camera_and_click_closes_it(tmp_path: Path) -> None:
    friend = Friend(tmp_path, video=NullVideo(), openai_key="", show_hold_s=0, boot_s=0)
    queue = friend.subscribe()
    await friend.handle(Power(on=True))
    await drain(friend, queue)
    assert friend.state is State.LISTENING

    # Two fast clicks: camera opens and stays open.
    await friend.handle(Click())
    await friend.handle(Click())
    events = await drain(friend, queue)
    assert friend.state is State.SEEING
    assert any(e.get("type") == "camera" and e.get("open") is True for e in events)

    # One click while the camera is up: back to the face.
    await friend.handle(Click())
    await drain(friend, queue)
    assert friend.state is State.LISTENING

    # A click right after closing must not reopen the camera.
    await friend.handle(Click())
    await drain(friend, queue)
    assert friend.state is State.LISTENING
    await friend.close()


@pytest.mark.asyncio
async def test_slow_clicks_do_not_open_camera(tmp_path: Path) -> None:
    friend = Friend(tmp_path, video=NullVideo(), openai_key="", show_hold_s=0, boot_s=0)
    friend.double_click_s = 0.1
    queue = friend.subscribe()
    await friend.handle(Power(on=True))
    await drain(friend, queue)

    await friend.handle(Click())
    await asyncio.sleep(0.25)
    await friend.handle(Click())
    await drain(friend, queue)
    assert friend.state is State.LISTENING
    await friend.close()


@pytest.mark.asyncio
async def test_boot_sequence_passes_through_booting(tmp_path: Path) -> None:
    friend = Friend(tmp_path, video=NullVideo(), openai_key="", show_hold_s=0, boot_s=0.15)
    queue = friend.subscribe()

    await friend.handle(Power(on=True))
    assert friend.state is State.BOOTING

    # Input during boot is ignored.
    await friend.handle(TextLine("hello?"))
    await friend.handle(PushToTalk(active=True))
    assert friend.state is State.BOOTING

    events = await drain(friend, queue)
    states = [e.get("state") for e in events if e.get("type") == "state"]
    assert "booting" in states
    assert friend.state in {State.LISTENING, State.TALKING}
    # Screen (face) is on for every awake event.
    assert all(e.get("screen") is True for e in events if e.get("state") != "asleep")
    await friend.close()


@pytest.mark.asyncio
async def test_boot_cancelled_by_power_off(tmp_path: Path) -> None:
    friend = Friend(tmp_path, video=NullVideo(), openai_key="", show_hold_s=0, boot_s=5.0)
    await friend.handle(Power(on=True))
    assert friend.state is State.BOOTING
    await friend.handle(Power(on=False))
    assert friend.state is State.ASLEEP
    await asyncio.sleep(0.05)
    assert friend.state is State.ASLEEP
    await friend.close()


@pytest.mark.asyncio
async def test_idle_auto_sleep(tmp_path: Path) -> None:
    friend = Friend(
        tmp_path, video=NullVideo(), openai_key="", show_hold_s=0, boot_s=0, idle_sleep_s=1.0
    )
    queue = friend.subscribe()
    await friend.handle(Power(on=True))
    await drain(friend, queue)
    assert friend.state is State.LISTENING

    await asyncio.sleep(2.2)
    assert friend.state is State.ASLEEP
    events = await drain(friend, queue, n=5)
    assert any(e.get("reason") == "idle" and e.get("power") is False for e in events)
    await friend.close()


@pytest.mark.asyncio
async def test_live_voice_falls_back_to_fake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import gizmo_friend.session as session_mod

    class BoomTransport:
        def __init__(self, key: str) -> None:
            del key

        async def connect(self, instructions: str) -> None:
            raise RuntimeError("tls says no")

    monkeypatch.setattr(session_mod, "OpenAIRealtimeTransport", BoomTransport)
    friend = Friend(tmp_path, video=NullVideo(), openai_key="sk-test", show_hold_s=0, boot_s=0)
    queue = friend.subscribe()
    await friend.handle(Power(on=True))
    events = await drain(friend, queue)

    # He boots anyway, on the offline voice, and says why out loud on the bus.
    assert friend.state in {State.LISTENING, State.TALKING}
    assert friend.transport_name == "fake"
    assert any(e.get("type") == "error" for e in events)
    await friend.close()


def test_classify_does_not_require_pinecone() -> None:
    assert classify("I'm bored")[0] == "talk"
    assert classify("what is this")[0] == "see"
    assert classify("show me the spell")[0] == "show"
    assert classify("why is the sky blue?")[0] == "think"
