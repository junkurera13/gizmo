from __future__ import annotations

import asyncio
import base64
import json
import os
from typing import Any

from google import genai
from google.genai import types

from gizmo_friend.tools.allowlist import NON_BLOCKING_TOOLS, TOOL_SCHEMAS, assert_allowlist
from gizmo_friend.transport.base import TransportEvent

try:
    import audioop
except ImportError:  # Python 3.13+
    import audioop_lts as audioop  # type: ignore[no-redef]


MODEL = "gemini-3.1-flash-live-preview"
# Gizmo's one voice. Google's default is Puck (upbeat), the opposite of him.
# Umbriel is the easy-going male voice: unhurried, low energy, warm underneath.
VOICE = "Umbriel"
INPUT_RATE = 16_000
DEVICE_RATE = 24_000
OUTPUT_RATE = 24_000

# Speech gate. With automatic VAD off, activity_end tells Gemini "the user
# spoke, answer now" — so a held button with nothing said must never open a
# turn, or the model answers a phrase it hallucinated from room noise.
# RMS on int16: a quiet room sits around 50-200, speech well above 1000.
SPEECH_RMS = int(os.environ.get("GIZMO_SPEECH_RMS", "400"))
# Voiced audio needed before the gate opens: ~160 ms at 16 kHz mono PCM16.
# A chair creak is one chunk; a word is several.
SPEECH_OPEN_BYTES = int(0.16 * INPUT_RATE * 2)
# Everything heard before the gate opens is kept and sent right behind
# activity_start, so the first syllable is never lost. Bounded for safety.
PRE_GATE_LIMIT_BYTES = 30 * INPUT_RATE * 2


class Pcm16Resampler:
    """Stateful mono PCM16 conversion across device audio chunks."""

    def __init__(self, input_rate: int = DEVICE_RATE, output_rate: int = INPUT_RATE) -> None:
        self.input_rate = input_rate
        self.output_rate = output_rate
        self._state: Any = None

    def reset(self) -> None:
        self._state = None

    def convert(self, pcm: bytes) -> bytes:
        if not pcm or self.input_rate == self.output_rate:
            return pcm
        converted, self._state = audioop.ratecv(
            pcm,
            2,
            1,
            self.input_rate,
            self.output_rate,
            self._state,
        )
        return converted


def live_config(instructions: str, resume_handle: str = "") -> types.LiveConnectConfig:
    assert_allowlist(TOOL_SCHEMAS)
    # Visual routing belongs to the separate structured director. Live stays
    # the voice and cannot make a second, competing show/animate choice.
    live_schemas = [
        schema for schema in TOOL_SCHEMAS if schema["name"] not in {"show", "animate"}
    ]
    declarations = [
        types.FunctionDeclaration(
            name=schema["name"],
            description=schema["description"],
            parameters_json_schema=schema["parameters"],
            behavior=(
                types.Behavior.NON_BLOCKING
                if schema["name"] in NON_BLOCKING_TOOLS
                else types.Behavior.BLOCKING
            ),
        )
        for schema in live_schemas
    ]
    return types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=instructions,
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=os.environ.get("GIZMO_VOICE", VOICE)
                )
            )
        ),
        # enable_affective_dialog is rejected by this model at setup (1007),
        # like safetySettings. Retest when the model line moves.
        # Live setup does not accept safetySettings (provider returns 1007).
        # Its built-in filters remain active; custom thresholds apply only
        # to supported generate-content calls in the reasoning provider.
        tools=[
            types.Tool(google_search=types.GoogleSearch()),
            types.Tool(function_declarations=declarations),
        ],
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(disabled=True)
        ),
        session_resumption=types.SessionResumptionConfig(handle=resume_handle or None),
        context_window_compression=types.ContextWindowCompressionConfig(
            sliding_window=types.SlidingWindow()
        ),
    )


class GeminiLiveTransport:
    """Gemini Live adapter for Gizmo's existing device transport contract."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        model: str | None = None,
        resume_handle: str = "",
    ) -> None:
        self.api_key = api_key if api_key is not None else os.environ.get("GEMINI_API_KEY")
        self.model = model or os.environ.get("GIZMO_LIVE_MODEL", MODEL)
        self.resume_handle = resume_handle
        self.instructions = ""
        self._client: genai.Client | None = None
        self._connection: Any = None
        self._session: Any = None
        self._reader: asyncio.Task[None] | None = None
        self._queue: asyncio.Queue[TransportEvent | None] = asyncio.Queue()
        self._resampler = Pcm16Resampler()
        self._tool_names: dict[str, str] = {}
        self._input_transcript = ""
        self._output_transcript = ""
        self._suppress_audio = False
        self._audio_active = False
        self._activity_open = False
        self._audio_received = False
        self._pre_gate: list[bytes] = []
        self._pre_gate_bytes = 0
        self._voiced_bytes = 0
        self._pending_image: types.Blob | None = None
        self._closed = False

    async def connect(self, instructions: str) -> None:
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY missing")
        self.instructions = instructions
        self._client = genai.Client(api_key=self.api_key)
        self._connection = self._client.aio.live.connect(
            model=self.model,
            config=live_config(instructions, self.resume_handle),
        )
        self._session = await self._connection.__aenter__()
        self._reader = asyncio.create_task(self._read_loop())

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._reader and self._reader is not asyncio.current_task():
            self._reader.cancel()
        if self._connection is not None:
            try:
                await self._connection.__aexit__(None, None, None)
            except Exception:  # noqa: BLE001 - closing a dead socket is best-effort
                pass
        if self._client is not None:
            await self._client.aio.aclose()
            self._client.close()
        await self._queue.put(None)

    async def send_text(self, text: str) -> None:
        if not text.strip():
            return
        if self._activity_open:
            await self._require_session().send_realtime_input(activity_end=types.ActivityEnd())
            self._activity_open = False
            self._audio_active = False
        self._suppress_audio = False
        self._output_transcript = ""
        parts = []
        if self._pending_image is not None:
            parts.append(types.Part(inline_data=self._pending_image))
            self._pending_image = None
        parts.append(types.Part(text=text))
        # Keep the deployed text/image path: this model/key's manual-PTT
        # session rejects activity-wrapped realtime text (1007), while this
        # existing client-content path is verified against the live provider.
        await self._require_session().send_client_content(
            turns=types.Content(role="user", parts=parts),
            turn_complete=True,
        )

    async def remember(self, text: str) -> None:
        """Append words he already said (scripted narration) to the conversation, silently.

        The storytelling conductor speaks through its own voice, so Live never
        hears those words. Adding them as a model turn without completing the
        turn keeps his memory of the story straight for the next question.
        """
        if not text.strip() or self._activity_open:
            return
        await self._require_session().send_client_content(
            turns=types.Content(role="model", parts=[types.Part(text=text)]),
            turn_complete=False,
        )

    async def begin_audio(self) -> None:
        self._suppress_audio = True
        self._input_transcript = ""
        self._output_transcript = ""
        self._audio_received = False
        self._pre_gate.clear()
        self._pre_gate_bytes = 0
        self._voiced_bytes = 0
        self._resampler.reset()
        self._audio_active = True

    async def send_audio(self, pcm: bytes) -> None:
        if not self._audio_active:
            return
        converted = self._resampler.convert(pcm)
        if not converted:
            return
        if self._activity_open:
            await self._send_pcm(converted)
            return

        # Gate closed: hold the audio and listen for actual speech.
        self._pre_gate.append(converted)
        self._pre_gate_bytes += len(converted)
        while self._pre_gate and self._pre_gate_bytes > PRE_GATE_LIMIT_BYTES:
            self._pre_gate_bytes -= len(self._pre_gate.pop(0))
        if audioop.rms(converted, 2) >= SPEECH_RMS:
            self._voiced_bytes += len(converted)
        if self._voiced_bytes < SPEECH_OPEN_BYTES:
            return

        # Someone is talking. Open the turn and replay what we held.
        session = self._require_session()
        await session.send_realtime_input(activity_start=types.ActivityStart())
        self._activity_open = True
        self._audio_received = True
        if self._pending_image is not None:
            await session.send_realtime_input(video=self._pending_image)
            self._pending_image = None
        for chunk in self._pre_gate:
            await self._send_pcm(chunk)
        self._pre_gate.clear()
        self._pre_gate_bytes = 0

    async def _send_pcm(self, converted: bytes) -> None:
        await self._require_session().send_realtime_input(
            audio=types.Blob(data=converted, mime_type=f"audio/pcm;rate={INPUT_RATE}")
        )

    async def commit_audio(self) -> None:
        if not self._audio_active:
            return
        # A hold with no speech in it is dropped whole: no activity pair, no
        # reply. Gizmo stays quiet, which is what a silent press means.
        self._suppress_audio = not self._audio_received
        if self._activity_open:
            await self._require_session().send_realtime_input(activity_end=types.ActivityEnd())
        self._audio_active = False
        self._activity_open = False
        # A silent hold must not lend pending visual input to a later
        # voice/text turn. Spoken turns have already consumed their image.
        self._pending_image = None
        self._pre_gate.clear()
        self._pre_gate_bytes = 0
        self._voiced_bytes = 0
        self._resampler.reset()

    async def interrupt(self, played_ms: int = 0, item_id: str = "") -> None:
        del played_ms, item_id
        # Gemini interrupts its current output when new activity begins. The
        # controller immediately stops local playback as well.
        self._suppress_audio = True
        self._output_transcript = ""
        self._audio_received = False
        self._audio_active = False
        self._pre_gate.clear()
        self._pre_gate_bytes = 0
        self._voiced_bytes = 0
        # Mute locally now. The next *real* input's activity-start interrupts
        # generation upstream. Sleep/select are not fabricated user turns.

    async def request_response(self) -> None:
        # Compatibility with the transport protocol; waking is not a user turn.
        return

    async def submit_tool_output(self, call_id: str, output: str) -> None:
        try:
            payload = json.loads(output) if output else {}
        except json.JSONDecodeError:
            payload = {"ok": False, "reason": "tool returned invalid JSON"}
        if not isinstance(payload, dict):
            payload = {"result": payload}
        name = self._tool_names.pop(call_id, "")
        await self._require_session().send_tool_response(
            function_responses=types.FunctionResponse(
                id=call_id,
                name=name,
                response=payload,
                scheduling=(
                    types.FunctionResponseScheduling.SILENT
                    if name in NON_BLOCKING_TOOLS
                    else None
                ),
            )
        )

    async def send_image(self, data_url: str) -> None:
        mime, data = _decode_data_url(data_url)
        image = types.Blob(data=data, mime_type=mime)
        # With manual activity boundaries, a video frame sent outside an
        # active turn may be ignored. Bind snapshots to the next user turn.
        if self._activity_open:
            await self._require_session().send_realtime_input(video=image)
        else:
            self._pending_image = image

    async def clear_pending_image(self) -> None:
        self._pending_image = None

    def _require_session(self):
        if self._session is None:
            raise RuntimeError("Gemini Live session is closed")
        return self._session

    async def _read_loop(self) -> None:
        try:
            while not self._closed:
                async for message in self._require_session().receive():
                    for event in self._map(message):
                        await self._queue.put(event)
        except asyncio.CancelledError:
            return
        except Exception as error:  # noqa: BLE001 - controller owns reconnection
            await self._queue.put(TransportEvent(kind="error", text=f"Gemini Live: {error}"))
            await self._queue.put(TransportEvent(kind="disconnected"))

    def _map(self, message: types.LiveServerMessage) -> list[TransportEvent]:
        raw = message.model_dump(mode="json", exclude_none=True)
        events: list[TransportEvent] = []

        update = message.session_resumption_update
        if update and update.new_handle:
            self.resume_handle = update.new_handle
            events.append(TransportEvent(kind="session_resumption", text=update.new_handle, raw=raw))
        if message.go_away:
            events.append(TransportEvent(kind="reconnect_required", raw=raw))

        tool_call = message.tool_call
        if tool_call and not self._suppress_audio:
            for call in tool_call.function_calls or []:
                call_id = call.id or ""
                name = call.name or ""
                self._tool_names[call_id] = name
                args = call.args if isinstance(call.args, dict) else {}
                events.append(
                    TransportEvent(
                        kind="function_call",
                        name=name,
                        arguments=args,
                        call_id=call_id,
                        raw=raw,
                    )
                )

        content = message.server_content
        if not content:
            return events
        if content.interrupted:
            events.append(TransportEvent(kind="cancelled", raw=raw))

        if content.input_transcription and content.input_transcription.text:
            self._input_transcript += content.input_transcription.text
            if content.input_transcription.finished:
                events.append(
                    TransportEvent(kind="user_transcript", text=self._input_transcript.strip(), raw=raw)
                )
                self._input_transcript = ""
            else:
                # Live can send the entire utterance without `finished`, then
                # defer turn_complete until its spoken answer has ended. Expose
                # a preview for visual planning, while retaining the final
                # transcript boundary for memory and conversation history.
                events.append(TransportEvent(
                    kind="user_transcript_preview", text=self._input_transcript.strip(), raw=raw,
                ))

        if (
            not self._suppress_audio
            and content.output_transcription
            and content.output_transcription.text
        ):
            text = content.output_transcription.text
            self._output_transcript += text
            events.append(TransportEvent(kind="transcript_delta", text=text, raw=raw))
            if content.output_transcription.finished:
                events.append(
                    TransportEvent(kind="transcript", text=self._output_transcript.strip(), raw=raw)
                )
                self._output_transcript = ""

        if content.model_turn:
            for part in content.model_turn.parts or []:
                blob = part.inline_data
                if blob and blob.data and (blob.mime_type or "").startswith("audio/pcm"):
                    if not self._suppress_audio:
                        events.append(TransportEvent(kind="audio", pcm=blob.data, raw=raw))
                elif part.text and not content.output_transcription and not self._suppress_audio:
                    self._output_transcript += part.text
                    events.append(TransportEvent(kind="transcript_delta", text=part.text, raw=raw))

        if content.grounding_metadata:
            events.append(
                TransportEvent(kind="grounding", raw=content.grounding_metadata.model_dump(mode="json", exclude_none=True))
            )

        if content.turn_complete:
            if self._input_transcript.strip():
                events.append(
                    TransportEvent(kind="user_transcript", text=self._input_transcript.strip(), raw=raw)
                )
                self._input_transcript = ""
            if self._output_transcript.strip() and not self._suppress_audio:
                events.append(
                    TransportEvent(kind="transcript", text=self._output_transcript.strip(), raw=raw)
                )
                self._output_transcript = ""
            elif self._suppress_audio:
                self._output_transcript = ""
            events.append(TransportEvent(kind="done", raw=raw))
        return events

    def __aiter__(self) -> GeminiLiveTransport:
        return self

    async def __anext__(self) -> TransportEvent:
        item = await self._queue.get()
        if item is None:
            raise StopAsyncIteration
        return item


def _decode_data_url(data_url: str) -> tuple[str, bytes]:
    header, marker, encoded = data_url.partition(",")
    if not marker or ";base64" not in header:
        raise ValueError("camera frame must be a base64 data URL")
    mime = header.removeprefix("data:").split(";", 1)[0] or "image/jpeg"
    return mime, base64.b64decode(encoded, validate=True)
