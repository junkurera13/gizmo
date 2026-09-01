from __future__ import annotations

import json

import pytest
from google.genai import types

from gizmo_friend.prompt import FROZEN_PROMPT
from gizmo_friend.transport.gemini_live import (
    INPUT_RATE,
    GeminiLiveTransport,
    Pcm16Resampler,
    _decode_data_url,
    live_config,
)


def test_live_config_uses_native_search_transcription_and_manual_ptt() -> None:
    config = live_config(FROZEN_PROMPT)
    assert config.response_modalities == [types.Modality.AUDIO]
    assert config.tools[0].google_search is not None
    assert [item.name for item in config.tools[1].function_declarations] == [
        "deep_think",
        "set_expression",
    ]
    assert config.input_audio_transcription is not None
    assert config.output_audio_transcription is not None
    assert config.realtime_input_config.automatic_activity_detection.disabled is True
    assert config.session_resumption is not None
    assert config.context_window_compression is not None


def test_device_pcm_is_resampled_from_24k_to_16k() -> None:
    pcm_100_ms = b"\x00\x00" * 2400
    converted = Pcm16Resampler().convert(pcm_100_ms)
    assert len(converted) == 1600 * 2
    assert INPUT_RATE == 16_000


def test_camera_data_url_is_strictly_decoded() -> None:
    mime, data = _decode_data_url("data:image/png;base64,iVBORw0KGgo=")
    assert mime == "image/png"
    assert data.startswith(b"\x89PNG")
    with pytest.raises(ValueError):
        _decode_data_url("https://example.test/image.png")


def test_server_message_maps_audio_final_transcripts_tools_and_resume() -> None:
    transport = GeminiLiveTransport(api_key="test-key")
    message = types.LiveServerMessage(
        session_resumption_update=types.LiveServerSessionResumptionUpdate(
            new_handle="resume-me",
            resumable=True,
        ),
        tool_call=types.LiveServerToolCall(
            function_calls=[
                types.FunctionCall(
                    id="call-1",
                    name="deep_think",
                    args={"question": "why?"},
                )
            ]
        ),
        server_content=types.LiveServerContent(
            model_turn=types.Content(
                role="model",
                parts=[
                    types.Part(
                        inline_data=types.Blob(
                            data=b"\x01\x00",
                            mime_type="audio/pcm;rate=24000",
                        )
                    )
                ],
            ),
            input_transcription=types.Transcription(text="hello", finished=True),
            output_transcription=types.Transcription(text="hi", finished=True),
            turn_complete=True,
        ),
    )
    events = transport._map(message)
    assert [event.kind for event in events] == [
        "session_resumption",
        "function_call",
        "user_transcript",
        "transcript_delta",
        "transcript",
        "audio",
        "done",
    ]
    assert events[1].arguments == {"question": "why?"}
    assert transport.resume_handle == "resume-me"


@pytest.mark.asyncio
async def test_tool_result_returns_to_same_live_session() -> None:
    class StubSession:
        def __init__(self) -> None:
            self.responses: list[types.FunctionResponse] = []

        async def send_tool_response(self, *, function_responses: types.FunctionResponse) -> None:
            self.responses.append(function_responses)

    transport = GeminiLiveTransport(api_key="test-key")
    session = StubSession()
    transport._session = session
    transport._tool_names["call-7"] = "deep_think"
    await transport.submit_tool_output(
        "call-7",
        json.dumps({"ok": True, "answer": "careful private result"}),
    )
    response = session.responses[0]
    assert response.id == "call-7"
    assert response.name == "deep_think"
    assert response.response["answer"] == "careful private result"
