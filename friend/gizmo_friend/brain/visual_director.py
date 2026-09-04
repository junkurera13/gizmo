"""Fast, structured routing for Gizmo's words/still/motion decision."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DIRECTOR_MODEL = "gemini-3.1-flash-lite"
DIRECTOR_TIMEOUT_SECONDS = 4.0
NO_MOTION_SENTINELS = {
    "n/a",
    "no motion",
    "no movement",
    "none",
    "none needed",
    "not applicable",
    "static",
    "still",
}

DIRECTOR_INSTRUCTIONS = """You are Gizmo's silent visual director. You do not answer the kid. You only choose whether this one utterance should stay words, show a still illustration, show a moving illustration, or animate the illustration already on the glass.

Return exactly one structured decision.

WORDS
- Most utterances stay words.
- Always words for feelings, emotional support, small talk, jokes, personal advice, people, and ordinary facts where seeing adds no understanding.
- Simple classifications, definitions, dates, causes, and factual status questions stay words even when their subject could be illustrated.
- A follow-up about the subject already on the glass stays words unless the kid explicitly asks to move it.

STILL
- Use a still when spatial understanding is the point: what something looks like, where it is, how parts fit, anatomy, a cross-section, a map, or a place.
- Historical or geographic questions about where routes, regions, or places sit relative to one another get a still map.
- An explicit request to draw, show, or make a picture gets a still unless meaningful change over time is the point.

MOTION
- Use motion only when seeing meaningful change over time explains the answer: a rocket lifting, a wave breaking, a heart beating, a volcano erupting, or the Moon orbiting Earth.
- Never add motion merely because a subject is alive or capable of moving. Appearance, maps, anatomy, objects, and places remain still.
- A story's first chapter may open one moving scene when it establishes a genuinely new setting. A continuation in the same setting stays words. Depict the place and atmosphere, never a child.

ANIMATE
- Use animate only when an illustration is currently on the glass and the kid directly asks to make it move or animate it.
- Never redraw the subject for animate.

For still or motion, subject is a short concrete noun phrase with the one important detail and no style instructions. For motion or animate, motion is one short phrase describing only quiet subject motion: no camera movement, cuts, new objects, or cinematic language. For words, leave subject and motion empty. Never output the literal word "none" as motion."""

DIRECTOR_SCHEMA = {
    "type": "object",
    "properties": {
        "route": {"type": "string", "enum": ["words", "still", "motion", "animate"]},
        "subject": {"type": "string"},
        "motion": {"type": "string"},
    },
    "required": ["route", "subject", "motion"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class VisualDecision:
    route: str = "words"
    subject: str = ""
    motion: str = ""


def is_bare_animate_request(utterance: str) -> bool:
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", utterance.casefold())
    cleaned = " ".join(cleaned.split())
    if cleaned.startswith("please "):
        cleaned = cleaned.removeprefix("please ")
    if cleaned.endswith(" please"):
        cleaned = cleaned.removesuffix(" please")
    return cleaned in {"animate it", "make it move", "make that move", "make this move", "move it"}


def decision_from_payload(payload: object, *, has_visual: bool) -> VisualDecision:
    if not isinstance(payload, dict):
        return VisualDecision()
    route = str(payload.get("route") or "").strip().casefold()
    subject = str(payload.get("subject") or "").strip()[:300]
    motion = str(payload.get("motion") or "").strip()[:200]
    if motion.casefold().rstrip(".") in NO_MOTION_SENTINELS:
        motion = ""
    if route == "animate":
        return VisualDecision(route="animate", motion=motion) if has_visual and motion else VisualDecision()
    if route == "motion":
        if subject and motion:
            return VisualDecision(route="motion", subject=subject, motion=motion)
        if subject:
            return VisualDecision(route="still", subject=subject)
        return VisualDecision()
    if route == "still" and subject:
        return VisualDecision(route="still", subject=subject)
    return VisualDecision()


class VisualDirector(ABC):
    @abstractmethod
    async def decide(
        self, utterance: str, *, has_visual: bool, current_subject: str = ""
    ) -> VisualDecision:
        """Choose one visual route without speaking or generating media."""

    async def close(self) -> None:
        return


class NullVisualDirector(VisualDirector):
    async def decide(
        self, utterance: str, *, has_visual: bool, current_subject: str = ""
    ) -> VisualDecision:
        del utterance, has_visual, current_subject
        return VisualDecision()


class GeminiVisualDirector(VisualDirector):
    def __init__(self, api_key: str, *, model: str = DIRECTOR_MODEL) -> None:
        from google import genai
        from google.genai import types

        self.model = model
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                # Gemini rejects HTTP deadlines below ten seconds. The tighter
                # product deadline is enforced by asyncio around each call.
                timeout=10_000,
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )

    async def decide(
        self, utterance: str, *, has_visual: bool, current_subject: str = ""
    ) -> VisualDecision:
        from google.genai import types

        from gizmo_friend.safety import KID_SAFETY_SETTINGS

        cleaned = utterance.strip()
        if not cleaned:
            return VisualDecision()
        request = json.dumps(
            {
                "utterance": cleaned,
                "visual_on_glass": has_visual,
                "current_subject": current_subject if has_visual else "",
            },
            ensure_ascii=False,
        )
        try:
            async with asyncio.timeout(DIRECTOR_TIMEOUT_SECONDS):
                response = await self._client.aio.models.generate_content(
                    model=self.model,
                    contents=request,
                    config=types.GenerateContentConfig(
                        system_instruction=DIRECTOR_INSTRUCTIONS,
                        safety_settings=KID_SAFETY_SETTINGS,
                        response_mime_type="application/json",
                        response_json_schema=DIRECTOR_SCHEMA,
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(
                            disable=True
                        ),
                        temperature=0,
                        max_output_tokens=256,
                    ),
                )
            parsed = response.parsed
            if parsed is None:
                parsed = json.loads(response.text or "{}")
            return decision_from_payload(parsed, has_visual=has_visual)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            # A director outage degrades to words and can never spend media.
            logger.warning(
                "Visual director unavailable: model=%s error=%s code=%s",
                self.model,
                type(error).__name__,
                getattr(error, "code", None),
            )
            return VisualDecision()

    async def close(self) -> None:
        await self._client.aio.aclose()
        self._client.close()


def visual_director_from_env(api_key: str | None = None) -> VisualDirector:
    key = (api_key or os.environ.get("GEMINI_API_KEY") or "").strip()
    if not key:
        return NullVisualDirector()
    return GeminiVisualDirector(
        api_key=key,
        model=os.environ.get("GIZMO_DIRECTOR_MODEL", DIRECTOR_MODEL),
    )
