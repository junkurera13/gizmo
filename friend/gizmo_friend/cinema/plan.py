"""One score drives the words and the pictures; Google is used only for speech."""

from __future__ import annotations

import asyncio
import io
import json
import os
import wave
from dataclasses import dataclass, field
from typing import Literal

import fal_client
from pydantic import BaseModel, Field

from gizmo_friend.brain.gemini_text import TEXT_MODEL, GeminiTextClient
from gizmo_friend.brain.narration import narration_provider_from_env
from gizmo_friend.prompt import ART_STYLE, FROZEN_PROMPT

FILM_NARRATION_STYLE = (
    "Read the following verbatim as a clear, curious science explainer speaking "
    "to one interested listener. Use a natural, brisk conversational pace, about "
    "165–180 words per minute. Sound alert, matter-of-fact and lightly amused. "
    "Use a clean, fully voiced speaking tone, crisp consonants and decisive sentence "
    "endings. Keep pitch movement restrained and pauses short. Carry momentum "
    "through the sentence; emphasize the physical cause and effect. "
    "No whispering, breathy delivery, drawn-out vowels, dramatic suspense, "
    "sing-song intonation or announcer performance. Start speaking promptly and "
    "finish cleanly. Do not add words."
)

STYLE = f"""Original educational motion design. {ART_STYLE}
Purposeful movement, smooth revealing transitions and close-up cutaways.
Show cause and effect,
not a static illustration with ambient particles. The central requested object stays
visible. Leave typography and labels out of the generated picture."""

INSTRUCTIONS = (
    FROZEN_PROMPT
    + """
LIVE FILM CONTRACT — overrides device delivery constraints only.
You make a short, original animated explanation whose pictures demonstrate the words.
Return JSON matching the schema. Choose three connected visual beats, each with one
spoken sentence of 10–18 words and a concrete visible action. Answer the user's actual
question. Start with the interesting mechanism, not an introduction. Gizmo is dry,
curious, warm, never an announcer. No 'let me', no 'imagine', no menus of tools.
Use established science; don't invent facts, dates or first-ever claims.
The pictures must obey the SAME physical mechanism as the narration. Do not use
visual shorthand that teaches a different cause. In particular: rockets gain
momentum by ejecting propellant, never by pushing on the ground or surrounding air;
they carry oxidizer and work in vacuum. Gravity remains in space. Orbit is continuous
free fall around a planet, not escape from gravity. Equal opposite forces do not mean
equal accelerations for unequal masses. Fire alone is not an explanation: show gas
and momentum. Apply the same causal care to other subjects. If uncertain, simplify
to the mechanism you know rather than inventing an impressive claim. Separate
fiction/analogy from fact. If accuracy needs unavailable live research, say that.
A rocket explanation must show ignition, lifting, and propulsion as appropriate;
not an empty launchpad with smoke. Each action must visibly match that beat's words.
When interrupted, answer the new question using the established subject and facts.
The supplied context distinguishes completed narration from an interrupted plan;
do not assume unplayed content was heard. Keep characters, palette and geometry
consistent. End naturally after one useful idea, leaving space for the user.
Set relation to new for an unrelated subject, detour for a related question, and continue for the same idea.
The thread field is one short sentence describing where this curiosity can go next.
"""
)


class FilmBeat(BaseModel):
    narration: str = Field(min_length=1, max_length=220)
    action: str = Field(min_length=1, max_length=500)


class FilmPlan(BaseModel):
    title: str = Field(min_length=1, max_length=65)
    beats: list[FilmBeat] = Field(min_length=1, max_length=3)
    thread: str = Field(max_length=240)
    relation: Literal["continue", "detour", "new"] = "continue"

    @property
    def narration(self):
        return " ".join(beat.narration for beat in self.beats)

    def direction(self):
        score = "\n".join(
            f'When the soundtrack says "{b.narration}": {b.action}' for b in self.beats
        )
        return (
            STYLE
            + "\nFollow the supplied audio recording exactly. Time each visual action to its corresponding spoken sentence.\n"
            + score
        )


@dataclass
class PreparedFilm:
    plan: FilmPlan
    audio_url: str
    duration: float
    wav: bytes
    timings: list[dict] = field(default_factory=list)


class FilmMaker:
    def __init__(self):
        self.text = GeminiTextClient(
            os.environ["GEMINI_API_KEY"], model=os.environ.get("GIZMO_FILM_MODEL", TEXT_MODEL)
        )
        self.voice = narration_provider_from_env(
            voice=os.environ.get("GIZMO_FILM_VOICE")
            or os.environ.get("GIZMO_VOICE", "Umbriel"),
            style=FILM_NARRATION_STYLE,
        )
        self.upload = fal_client.AsyncClient(
            key=os.environ["FAL_KEY"], default_timeout=20
        )

    async def plan(self, question: str, context: list[dict]) -> FilmPlan:
        raw = await self.text.complete(
            INSTRUCTIONS,
            json.dumps({"question": question, "context": context[-8:]}),
            schema=FilmPlan.model_json_schema(),
            timeout=12,
            max_tokens=1100,
        )
        return FilmPlan.model_validate_json(raw)

    async def synthesize(self, plan: FilmPlan) -> PreparedFilm:
        # Short sentences synthesize concurrently. Their actual PCM lengths,
        # not word-count estimates, define the director's audio timeline.
        voices = await asyncio.gather(
            *(self.voice.narrate(beat.narration) for beat in plan.beats)
        )
        if any(voice is None for voice in voices):
            raise RuntimeError("The narration did not arrive. Please try again.")
        pcm = bytearray()
        timings = []
        for beat, voice in zip(plan.beats, voices):
            start = len(pcm) / 48000
            pcm.extend(voice.pcm)
            timings.append(
                {
                    "start": start,
                    "end": len(pcm) / 48000,
                    "narration": beat.narration,
                    "action": beat.action,
                }
            )
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(24000)
            audio.writeframes(bytes(pcm))
        return PreparedFilm(plan, "", len(pcm) / 48000, buffer.getvalue(), timings)

    async def upload_audio(self, wav: bytes) -> str:
        if not wav:
            raise RuntimeError("The narration recording is empty.")
        async with asyncio.timeout(20):
            return await self.upload.upload(
                wav, "audio/wav", file_name="gizmo-narration.wav"
            )

    async def prepare(self, plan: FilmPlan) -> PreparedFilm:
        prepared = await self.synthesize(plan)
        url = await self.upload_audio(prepared.wav)
        return PreparedFilm(
            prepared.plan, url, prepared.duration, prepared.wav, prepared.timings
        )

    async def transcribe(self, audio: bytes, mime: str) -> str:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        try:
            async with asyncio.timeout(25):
                response = await client.aio.models.generate_content(
                    model=os.environ.get(
                        "ODDITY_TRANSCRIBE_MODEL", "gemini-3.1-flash-lite"
                    ),
                    contents=[
                        types.Part.from_bytes(data=audio, mime_type=mime),
                        "Transcribe only the spoken words. Do not answer them. Empty text for silence.",
                    ],
                    config=types.GenerateContentConfig(
                        max_output_tokens=500, temperature=0
                    ),
                )
            return (response.text or "").strip()[:1200]
        finally:
            await client.aio.aclose()
            client.close()

    async def close(self):
        await asyncio.gather(self.text.close(), self.voice.close())
        # fal-client does not yet expose a public async close method.
        if "_client" in self.upload.__dict__:
            await self.upload._client.aclose()
