import asyncio
import json
from pathlib import Path

import pytest

from gizmo_friend.audio_out import BroadcastMouth
from gizmo_friend.brain.memory import MemoryMessage, MemoryProvider
from gizmo_friend.body_protocol import Frame, MicChunk, Navigate, Power, PushToTalk, Select, TextLine
from gizmo_friend.memory import Memory
from gizmo_friend.prefix import PrefixMemory
from gizmo_friend.prompt import WAKE_LINE
from gizmo_friend.session import Friend, GizmoSession
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
    await friend.on_select()
    assert friend.state is State.LISTENING
    assert cancelled

    await friend.handle(TextLine("I'm bored"))
    events = await drain(friend, queue)
    talk = spoken(events)
    assert talk
    assert len(_two_sentences(talk).split(".")) <= 3
    await friend.close()


@pytest.mark.asyncio
async def test_memobase_context_transcripts_and_background_write(tmp_path: Path) -> None:
    class RecordingMemory(MemoryProvider):
        def __init__(self) -> None:
            self.remembered: list[list[MemoryMessage]] = []
            self.flushed = 0

        async def context(self, user_id: str) -> str:
            assert user_id == "rio"
            return "Rio has a dog named Toast."

        async def remember(self, user_id: str, messages: list[MemoryMessage]) -> None:
            assert user_id == "rio"
            await asyncio.sleep(0)
            self.remembered.append(list(messages))

        async def flush(self, user_id: str) -> None:
            assert user_id == "rio"
            self.flushed += 1

    provider = RecordingMemory()
    friend = GizmoSession(
        tmp_path,
        video=NullVideo(),
        gemini_key="",
        memory_provider=provider,
        user_id="rio",
        show_hold_s=0,
        boot_s=0,
    )
    queue = friend.subscribe()
    await friend.handle(Power(on=True))
    await drain(friend, queue)
    assert "Rio has a dog named Toast" in friend.instructions()

    await friend.handle(TextLine("Do you remember my dog?"))
    await drain(friend, queue)
    await asyncio.sleep(0)
    assert provider.remembered
    assert [message["role"] for message in provider.remembered[-1]] == ["user", "assistant"]

    transcript_files = list((tmp_path / "transcripts").glob("*.jsonl"))
    assert len(transcript_files) == 1
    records = [json.loads(line) for line in transcript_files[0].read_text().splitlines()]
    assert any(record["role"] == "user" for record in records)
    assert any(record["role"] == "assistant" for record in records)
    await friend.close()
    assert provider.flushed >= 1


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
async def test_power_select_and_vertical_navigation_use_the_body_protocol(tmp_path: Path) -> None:
    friend = Friend(tmp_path, video=NullVideo(), openai_key="", show_hold_s=0, boot_s=0)
    queue = friend.subscribe()

    await friend.handle(Power(on=True))
    await drain(friend, queue)
    assert friend.state is State.LISTENING

    await friend.handle(Select())
    events = await drain(friend, queue)
    assert friend.state is State.LISTENING
    assert any(event.get("type") == "select" for event in events)

    friend.ptt_hold_s = 0.05
    await friend.handle(PushToTalk(active=True))
    await asyncio.sleep(0.15)
    events = await drain(friend, queue)
    assert any(event.get("type") == "ptt" and event.get("active") is True for event in events)

    await friend.handle(Navigate(direction="up"))
    events = await drain(friend, queue)
    assert any(event.get("type") == "navigate" and event.get("direction") == "up" for event in events)

    await friend.handle(Navigate(direction="left"))
    events = await drain(friend, queue)
    assert not any(event.get("type") == "navigate" for event in events)

    await friend.handle(Power(on=False))
    await drain(friend, queue)
    assert friend.state is State.POWERED_OFF
    await friend.handle(Select())
    events = await drain(friend, queue)
    assert friend.state is State.POWERED_OFF
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
    tool_events = [
        e for e in events if e.get("type") == "tool" and e.get("name") == "deep_think"
    ]
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
    assert "offline" in spoken(events).lower()
    assert friend.state is State.LISTENING
    await friend.close()


@pytest.mark.asyncio
async def test_repeated_select_never_opens_camera(tmp_path: Path) -> None:
    friend = Friend(tmp_path, video=NullVideo(), openai_key="", show_hold_s=0, boot_s=0)
    queue = friend.subscribe()
    await friend.handle(Power(on=True))
    await drain(friend, queue)
    assert friend.state is State.LISTENING

    await friend.handle(Select())
    await friend.handle(Select())
    events = await drain(friend, queue)
    assert friend.state is State.LISTENING
    assert not any(e.get("type") == "camera" for e in events)
    await friend.close()


@pytest.mark.asyncio
async def test_talk_button_wakes_from_sleep(tmp_path: Path) -> None:
    friend = Friend(tmp_path, video=NullVideo(), openai_key="", show_hold_s=0, boot_s=0)
    queue = friend.subscribe()
    assert friend.state is State.POWERED_OFF

    await friend.handle(Power(on=True))
    await drain(friend, queue)
    await friend.handle(PushToTalk(active=True))
    await friend.handle(PushToTalk(active=False))
    await drain(friend, queue)
    assert friend.state is State.ASLEEP

    await friend.handle(PushToTalk(active=True))
    events = await drain(friend, queue)
    assert friend.state in {State.LISTENING, State.TALKING}
    # The waking press is swallowed: no ptt session begins.
    assert not any(e.get("type") == "ptt" for e in events)

    # Releasing after the wake press is a no-op, not a commit.
    await friend.handle(PushToTalk(active=False))
    events = await drain(friend, queue)
    assert not any(e.get("type") == "ptt" for e in events)
    await friend.close()


@pytest.mark.asyncio
async def test_tap_talk_button_sleeps_hold_talks(tmp_path: Path) -> None:
    friend = Friend(tmp_path, video=NullVideo(), openai_key="", show_hold_s=0, boot_s=0)
    friend.ptt_hold_s = 0.1
    queue = friend.subscribe()
    await friend.handle(Power(on=True))
    await drain(friend, queue)
    assert friend.state is State.LISTENING

    # Quick tap: no mic, straight to sleep.
    await friend.handle(PushToTalk(active=True))
    await friend.handle(PushToTalk(active=False))
    events = await drain(friend, queue)
    assert friend.state is State.ASLEEP
    assert not any(e.get("type") == "ptt" for e in events)
    assert any(e.get("reason") == "ptt" and e.get("power") is True for e in events)

    # Press again: wakes. Then a real hold: mic opens, release commits.
    await friend.handle(PushToTalk(active=True))
    await friend.handle(PushToTalk(active=False))
    await drain(friend, queue)
    assert friend.state is State.LISTENING

    await friend.handle(PushToTalk(active=True))
    await asyncio.sleep(0.25)
    await friend.handle(PushToTalk(active=False))
    events = await drain(friend, queue)
    ptt = [e.get("active") for e in events if e.get("type") == "ptt"]
    assert ptt == [True, False]
    assert friend.state is not State.ASLEEP
    await friend.close()


@pytest.mark.asyncio
async def test_holding_ptt_interrupts_talking_and_opens_mic(tmp_path: Path) -> None:
    friend = Friend(tmp_path, video=NullVideo(), openai_key="", show_hold_s=0, boot_s=0)
    friend.ptt_hold_s = 0.05
    queue = friend.subscribe()
    await friend.handle(Power(on=True))
    await drain(friend, queue)
    friend.machine.state = State.TALKING

    await friend.handle(PushToTalk(active=True))
    await asyncio.sleep(0.15)
    events = await drain(friend, queue)

    assert friend.state is State.LISTENING
    assert any(e.get("type") == "interrupted" for e in events)
    assert any(e.get("type") == "ptt" and e.get("active") is True for e in events)

    await friend.handle(PushToTalk(active=False))
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
    assert all(
        e.get("screen") is True
        for e in events
        if e.get("state") not in {"powered_off", "asleep"}
    )
    await friend.close()


@pytest.mark.asyncio
async def test_boot_cancelled_by_power_off(tmp_path: Path) -> None:
    friend = Friend(tmp_path, video=NullVideo(), openai_key="", show_hold_s=0, boot_s=5.0)
    await friend.handle(Power(on=True))
    assert friend.state is State.BOOTING
    await friend.handle(Power(on=False))
    assert friend.state is State.POWERED_OFF
    await asyncio.sleep(0.05)
    assert friend.state is State.POWERED_OFF
    await friend.close()


@pytest.mark.asyncio
async def test_power_off_survives_a_stale_voice_transport(tmp_path: Path) -> None:
    class StaleTransport(FakeTransport):
        async def interrupt(self, played_ms: int = 0, item_id: str = "") -> None:
            del played_ms, item_id
            raise RuntimeError("voice socket is gone")

    friend = Friend(tmp_path, video=NullVideo(), openai_key="", show_hold_s=0, boot_s=0)
    queue = friend.subscribe()
    await friend.handle(Power(on=True))
    await drain(friend, queue)
    friend._transport = StaleTransport(lambda: friend.memory.prefix_memory())

    await friend.handle(Power(on=False))
    events = await drain(friend, queue)

    assert friend.state is State.POWERED_OFF
    assert any(event.get("type") == "error" for event in events)
    await friend.close()


@pytest.mark.asyncio
async def test_talk_button_tap_sleeps_with_a_stale_voice_transport(tmp_path: Path) -> None:
    class StaleTransport(FakeTransport):
        async def interrupt(self, played_ms: int = 0, item_id: str = "") -> None:
            del played_ms, item_id
            raise RuntimeError("voice socket is gone")

    friend = Friend(tmp_path, video=NullVideo(), openai_key="", show_hold_s=0, boot_s=0)
    friend.ptt_hold_s = 0.1
    queue = friend.subscribe()
    await friend.handle(Power(on=True))
    await drain(friend, queue)
    friend._transport = StaleTransport(lambda: friend.memory.prefix_memory())

    await friend.handle(PushToTalk(active=True))
    await friend.handle(PushToTalk(active=False))
    await drain(friend, queue)

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
    assert any(e.get("reason") == "idle" and e.get("power") is True for e in events)
    await friend.close()


@pytest.mark.asyncio
async def test_live_voice_falls_back_to_fake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import gizmo_friend.session as session_mod

    class BoomTransport:
        def __init__(self, key: str, *, resume_handle: str = "") -> None:
            del key, resume_handle

        async def connect(self, instructions: str) -> None:
            raise RuntimeError("tls says no")

    monkeypatch.setattr(session_mod, "GeminiLiveTransport", BoomTransport)
    friend = Friend(tmp_path, video=NullVideo(), gemini_key="test-key", show_hold_s=0, boot_s=0)
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
    assert classify("what is this")[0] == "talk"
    assert classify("show me the spell")[0] == "talk"
    assert classify("why is the sky blue?")[0] == "deep_think"


@pytest.mark.asyncio
async def test_memory_flush_cannot_overtake_insert(tmp_path: Path) -> None:
    friend = GizmoSession(tmp_path)
    events = []

    async def insert():
        await asyncio.sleep(0.02)
        events.append("insert")

    async def flush():
        events.append("flush")

    friend._background_memory(insert())
    friend._background_memory(flush())
    assert events == []
    await asyncio.gather(*tuple(friend._memory_tasks))
    assert events == ["insert", "flush"]
    await friend.close()


@pytest.mark.asyncio
async def test_live_agent_does_not_inject_legacy_sqlite_memory(tmp_path: Path) -> None:
    friend = GizmoSession(tmp_path, gemini_key="test-key")
    friend.memory.remember_from_utterance("My name is LegacyUser")
    friend._memory_context = "The user's name is Nova."
    assert "LegacyUser" not in friend.instructions()
    assert "Nova" in friend.instructions()
    await friend.close()


@pytest.mark.asyncio
async def test_existing_device_protocol_forwards_camera_and_ptt_preroll(tmp_path: Path) -> None:
    holder: dict[str, FakeTransport] = {}

    class RecordingTransport(FakeTransport):
        def __init__(self) -> None:
            super().__init__(lambda: PrefixMemory())
            self.begins = 0
            self.audio: list[bytes] = []
            self.images: list[str] = []
            self.commits = 0

        async def begin_audio(self) -> None:
            self.begins += 1

        async def send_audio(self, pcm: bytes) -> None:
            self.audio.append(pcm)

        async def commit_audio(self) -> None:
            self.commits += 1

        async def send_image(self, data_url: str) -> None:
            self.images.append(data_url)

    def factory(resume_handle: str) -> RecordingTransport:
        del resume_handle
        transport = RecordingTransport()
        holder["transport"] = transport
        return transport

    friend = GizmoSession(tmp_path, transport_factory=factory, boot_s=0, idle_sleep_s=0)
    friend.ptt_hold_s = 0.05
    await friend.handle(Power(on=True))
    assert friend._boot_task is not None
    await friend._boot_task
    transport = holder["transport"]
    assert isinstance(transport, RecordingTransport)

    png = b"\x89PNG\r\n\x1a\n" + b"camera"
    await friend.handle(Frame(image=png, mime="image/jpeg"))
    assert transport.images and transport.images[-1].startswith("data:image/png;base64,")

    await friend.handle(PushToTalk(active=True))
    await friend.handle(MicChunk(pcm=b"\x01\x00" * 480))
    await asyncio.sleep(0.08)
    await friend.handle(PushToTalk(active=False))
    assert transport.begins == 1
    assert transport.audio == [b"\x01\x00" * 480]
    assert transport.commits == 1
    await friend.close()
