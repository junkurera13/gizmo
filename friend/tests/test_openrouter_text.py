import asyncio
import json
from pathlib import Path

import pytest

from gizmo_friend.body_protocol import Power, TextLine
from gizmo_friend.session import Friend
from gizmo_friend.states import State
from gizmo_friend.tools.show import NullVideo
from gizmo_friend.transport.base import TransportEvent
from gizmo_friend.transport.openrouter_text import OpenRouterTextTransport, chat_tools


def test_chat_tools_wrap_realtime_schemas() -> None:
    tools = chat_tools()
    names = [t["function"]["name"] for t in tools]
    assert names == ["see", "show", "make", "think", "reach"]
    assert all(t["type"] == "function" for t in tools)
    think = next(t for t in tools if t["function"]["name"] == "think")
    assert "question" in think["function"]["parameters"]["properties"]


async def _connected_transport() -> OpenRouterTextTransport:
    transport = OpenRouterTextTransport(api_key="test-key", model="test-model")

    async def no_check() -> None:
        return

    transport._check_key = no_check  # type: ignore[method-assign]
    await transport.connect("You are Gizmo — test prefix.")
    return transport


async def _next(transport: OpenRouterTextTransport) -> TransportEvent:
    return await asyncio.wait_for(transport.__anext__(), timeout=1)


@pytest.mark.asyncio
async def test_plain_reply_is_transcript_then_done() -> None:
    transport = await _connected_transport()
    replies = [{"choices": [{"message": {"content": "Okay. Go on."}}]}]

    async def complete() -> dict:
        return replies.pop(0)

    transport._complete = complete  # type: ignore[method-assign]
    await transport.send_text("hi")
    first = await _next(transport)
    second = await _next(transport)
    assert (first.kind, first.text) == ("transcript", "Okay. Go on.")
    assert second.kind == "done"
    # History keeps the exchange for the next turn.
    roles = [m["role"] for m in transport._messages]
    assert roles == ["system", "user", "assistant"]


@pytest.mark.asyncio
async def test_tool_call_round_trip() -> None:
    transport = await _connected_transport()
    replies = [
        {
            "choices": [
                {
                    "message": {
                        "content": "Hold on. Big one.",
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "function": {
                                    "name": "think",
                                    "arguments": json.dumps({"question": "why is the sky blue?"}),
                                },
                            }
                        ],
                    }
                }
            ]
        },
        {"choices": [{"message": {"content": "Blue light scatters the most."}}]},
    ]

    async def complete() -> dict:
        return replies.pop(0)

    transport._complete = complete  # type: ignore[method-assign]
    await transport.send_text("why is the sky blue?")

    beat = await _next(transport)
    call = await _next(transport)
    assert (beat.kind, beat.text) == ("transcript", "Hold on. Big one.")
    assert call.kind == "function_call"
    assert call.name == "think"
    assert call.arguments == {"question": "why is the sky blue?"}

    await transport.submit_tool_output("call-1", json.dumps({"ok": True, "answer": "scatters"}))
    answer = await _next(transport)
    done = await _next(transport)
    assert (answer.kind, answer.text) == ("transcript", "Blue light scatters the most.")
    assert done.kind == "done"


@pytest.mark.asyncio
async def test_yap_is_cut_to_two_sentences() -> None:
    transport = await _connected_transport()
    yap = (
        "Boredom is a tin can. Here is an idea. And another idea. "
        "Also consider this. And one more thing."
    )
    replies = [{"choices": [{"message": {"content": yap}}]}]

    async def complete() -> dict:
        return replies.pop(0)

    transport._complete = complete  # type: ignore[method-assign]
    await transport.send_text("im bored")
    reply = await _next(transport)
    assert reply.text == "Boredom is a tin can. Here is an idea."
    # History matches what he actually said.
    assert transport._messages[-1]["content"] == reply.text


@pytest.mark.asyncio
async def test_cloud_error_fails_soft() -> None:
    transport = await _connected_transport()

    async def complete() -> None:
        return None

    transport._complete = complete  # type: ignore[method-assign]
    await transport.send_text("hi")
    error = await _next(transport)
    done = await _next(transport)
    assert error.kind == "error"
    assert done.kind == "done"


@pytest.mark.asyncio
async def test_openai_falls_back_to_text_brain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import gizmo_friend.session as session_mod

    class BoomRealtime:
        def __init__(self, key: str) -> None:
            del key

        async def connect(self, instructions: str) -> None:
            raise RuntimeError("insufficient_quota")

    class StubText:
        def __init__(self, key: str) -> None:
            del key
            self._queue: asyncio.Queue[TransportEvent | None] = asyncio.Queue()
            self.instructions = ""

        async def connect(self, instructions: str) -> None:
            self.instructions = instructions

        async def close(self) -> None:
            await self._queue.put(None)

        async def interrupt(self, played_ms: int = 0, item_id: str = "") -> None:
            return

        async def send_text(self, text: str) -> None:
            await self._queue.put(TransportEvent(kind="transcript", text=f"echo: {text}"))
            await self._queue.put(TransportEvent(kind="done"))

        async def send_audio(self, pcm: bytes) -> None:
            return

        async def commit_audio(self) -> None:
            return

        async def request_response(self) -> None:
            await self._queue.put(TransportEvent(kind="transcript", text="Hey. I'm here."))
            await self._queue.put(TransportEvent(kind="done"))

        def __aiter__(self) -> "StubText":
            return self

        async def __anext__(self) -> TransportEvent:
            item = await self._queue.get()
            if item is None:
                raise StopAsyncIteration
            return item

    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setattr(session_mod, "OpenAIRealtimeTransport", BoomRealtime)
    monkeypatch.setattr(session_mod, "OpenRouterTextTransport", StubText)

    friend = Friend(tmp_path, video=NullVideo(), openai_key="sk-dead", show_hold_s=0, boot_s=0)
    queue = friend.subscribe()
    await friend.handle(Power(on=True))

    events = []
    for _ in range(20):
        try:
            events.append(await asyncio.wait_for(queue.get(), timeout=0.4))
        except TimeoutError:
            break

    assert friend.transport_name == "openrouter"
    assert friend.state in {State.LISTENING, State.TALKING}
    assert any("openai unreachable" in str(e.get("message")) for e in events if e.get("type") == "error")
    assert any(e.get("type") == "transcript" for e in events)

    await friend.handle(TextLine("hello"))
    replies = []
    for _ in range(10):
        try:
            replies.append(await asyncio.wait_for(queue.get(), timeout=0.4))
        except TimeoutError:
            break
    assert any("echo: hello" in str(e.get("text")) for e in replies if e.get("type") == "transcript")
    await friend.close()
