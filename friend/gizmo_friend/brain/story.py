"""Storyboards for the storytelling conductor: what he says, what appears, when.

Two structured calls, both silent and both outside the voice model:

- scout: is this ask a told piece (a story, a history, an explainer with
  pictures), and if a story is already running, is the kid continuing,
  steering, asking a side question, or leaving? Fast; runs before the kid
  hears Live's first syllable.
- plan: one chapter of beats. Each beat is a few spoken sentences and the one
  picture that belongs under them. The conductor renders every beat before it
  is spoken, so narration and picture change together.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from gizmo_friend.brain.fal_text import FalTextClient, TEXT_MODEL

logger = logging.getLogger(__name__)

SCOUT_MODEL = TEXT_MODEL
PLAN_MODEL = "anthropic/claude-sonnet-4.6"
SCOUT_TIMEOUT_SECONDS = 4.0
PLAN_TIMEOUT_SECONDS = 20.0
DEFAULT_BEATS = 3
MAX_BEATS = 5
MAX_TOLD_CHARS = 2400
MAX_UTTERANCE_CHARS = 1200

SCOUT_ROUTES = ("none", "begin", "continue", "steer", "question", "leave")

# Cheap gate: only asks that could plausibly want a told piece pay for the
# scout and the hold. Everything else keeps Live's zero-added-latency path.
_STORY_GATE = re.compile(
    r"\b(story|stories|tale|legend|myth|fable|history|historic|happened|"
    r"once upon|chapter|episode|step by step|walk me through|narrat\w*|"
    r"documentary|videos?|clips?)\b"
)


def story_gate(utterance: str) -> bool:
    """Whether an utterance is worth a scout call when no story is running."""
    return bool(_STORY_GATE.search(" ".join(utterance.casefold().split())))


@dataclass(frozen=True)
class StoryIntent:
    route: str = "none"
    premise: str = ""
    opener: str = ""
    edit: str = ""


@dataclass(frozen=True)
class Beat:
    narration: str
    scene: str
    motion: str


@dataclass(frozen=True)
class Storyboard:
    title: str
    setting: str
    character: str
    beats: tuple[Beat, ...]
    remaining: str
    finished: bool

    @property
    def text(self) -> str:
        return " ".join(beat.narration for beat in self.beats)


SCOUT_INSTRUCTIONS = """You are Gizmo's silent story scout. You do not answer the kid. You decide one thing: whether this utterance asks for a told piece, and if a story is already running, what the kid is doing to it.

Gizmo is a small dry wizard in a kid's pocket. A "told piece" is something he tells in chapters with a picture under each part: a story, a tale, the true story of a place or event, the history of a thing, or an explanation the kid explicitly asks to be shown step by step with pictures, clips, or video.

ROUTES
- none: no story is running and this is ordinary conversation: a fact, a definition, a sum, a joke, a feeling, small talk, homework, a single "what does X look like". Most utterances are none.
- begin: the kid asks for a told piece: "tell me a story about...", "tell me the story of Pompeii", "what happened at Chernobyl", "the history of the Silk Road", "explain black holes step by step with clips". Also begin when a story is running and the kid asks for a different, unrelated story.
- continue (story running): the kid wants the next part with no change: "then what", "go on", "next", "keep going", "and then?", "more", "yeah", "okay", "what happened next".
- steer (story running): the kid changes or adds to the running story: a new character, a different choice, "wait, make it...", "what about the dog", "skip to the eruption", "go back to the market". The story bends and continues.
- question (story running): the kid asks something a friend answers in a sentence or two without changing the story: "why did it explode?", "is that real?", "how many people lived there?", "what's lava?". The story resumes after the answer.
- leave (story running): the kid changes the subject entirely, asks for homework help, brings a feeling, or says stop / enough / I'm done.

FIELDS
- premise (begin only): the piece to tell, one concrete line. For true stories name the real place, people or event and the real time; for fiction keep the kid's premise exactly. A generic story about a rocket or animal is fiction unless the kid asks for real history; do not silently turn it into a named historical event. Otherwise empty.
- opener (begin and steer only): one or two short sentences Gizmo says right now, in his voice, while the first picture is drawn. Dry, plain, warm underneath. At most twenty words. Never mention pictures, video, the screen, or that he is about to tell something. No "let me", no "sure", no "great question". Example for Pompeii: "Pompeii. A whole town, gone in one afternoon." For steer, acknowledge the change in under ten words: "Fine. The dog stays." Otherwise empty.
- edit (steer only): the kid's change as one line the writer can follow. Otherwise empty.

Resolve pronouns and references against the running story. A single word like "yeah" while a story is paused means continue. Feelings and safety topics are always leave."""

SCOUT_SCHEMA = {
    "type": "object",
    "properties": {
        "route": {"type": "string", "enum": list(SCOUT_ROUTES)},
        "premise": {"type": "string"},
        "opener": {"type": "string"},
        "edit": {"type": "string"},
    },
    "required": ["route", "premise", "opener", "edit"],
    "additionalProperties": False,
}

PLAN_INSTRUCTIONS = """You write one chapter of a told piece for Gizmo, a small dry wizard in a kid's pocket. The kid is 9 to 14. Everything you write is spoken aloud in his voice, and every beat has one picture under it. You return a storyboard, not prose.

HIS VOICE
Dry, a little weird, warm underneath. Short sentences. Concrete words. One idea per beat. Never a list, never a lecture, never "imagine" or "picture this". Never mention pictures, clips, video, the screen, or that a story is being told. He does not perform; he tells. A joke lands better dry. True over impressive: for real history and science, use only what is actually known, name real places and dates, and say plainly when something is uncertain. No invented facts, no invented quotes. Avoid unsupported claims that something was the first ever, and dramatic comparisons about destruction. If the premise is fiction, do not introduce real historical dates or missions as fact.

THE CHAPTER
- Exactly the requested number of beats. Each beat's narration is two or three short sentences, twenty-five to forty-five words, that stand alone when heard.
- The first sentence of the first beat lands in the world at once: a place, a time, a thing happening. No preamble, no title read aloud.
- A chapter is one movement of the piece. Chapter one opens the world and ends on its first turn. Later chapters carry it forward. The final chapter closes it; then finished is true and remaining is empty.
- The last beat of every unfinished chapter ends on a hook: an open thread the kid would want to pull. Not a question offering choices, not "want to hear more", never a menu. Then quiet.
- Keep established names, facts, and events consistent with what has been told so far. If an edit is given, it is the kid's change: honor it as an edit to this same piece, not a restart.
- remaining: one line saying what the next chapter covers, or empty when finished.

THE PICTURES
Each beat's scene is the one picture under its narration, drawn in a fixed two-ink print style you do not control.
- Keep the central subject and action in view. A rocket launch must show the rocket, not just mist on an empty launchpad; a swimming whale must show the whale, not just ripples.
- scene: a concrete noun phrase, at most twenty-five words, of a lived-in place, object, animal, or force with weather, light, and atmosphere. It must show the beat's idea without people: no people, no human faces, no children, no crowds, no hands. Tell of people through their world: an empty street, bread left in an oven, a dog's paw print in ash, a ship at the dock. No text, letters, numbers, labels, arrows, maps, or diagrams.
- motion: empty unless this chapter should actually move — a launch, a voyage, a storm, or an opening in a new place. Quiet talking beats stay still. If any beat has motion, the chapter plays as one narrated Cinema film, not a silent clip. No cuts, no people, no unrelated objects.
- setting: the broad location of this chapter, one or two words, such as "Pompeii" or "ocean floor".
- character: only for fiction with a recurring NON-HUMAN protagonist: a compact visual identity (name if known, species, silhouette, markings, one accessory), copied exactly from the saved one when given. Otherwise empty. Never a person.
- Each beat is a new picture. Vary the shot: wide, close, high, low. Keep one world."""

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "setting": {"type": "string"},
        "character": {"type": "string"},
        "beats": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "narration": {"type": "string"},
                    "scene": {"type": "string"},
                    "motion": {"type": "string"},
                },
                "required": ["narration", "scene", "motion"],
                "additionalProperties": False,
            },
        },
        "remaining": {"type": "string"},
        "finished": {"type": "boolean"},
    },
    "required": ["title", "setting", "character", "beats", "remaining", "finished"],
    "additionalProperties": False,
}


def _line(value: object, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def intent_from_payload(payload: object, *, story_active: bool) -> StoryIntent:
    if not isinstance(payload, dict):
        return StoryIntent()
    route = str(payload.get("route") or "").strip().casefold()
    if route not in SCOUT_ROUTES:
        return StoryIntent()
    if not story_active and route not in {"none", "begin"}:
        # Without a running story there is nothing to continue, steer, or leave.
        return StoryIntent()
    premise = _line(payload.get("premise"), 300)
    opener = _line(payload.get("opener"), 200)
    edit = _line(payload.get("edit"), 300)
    if route == "begin":
        if not premise:
            return StoryIntent()
        return StoryIntent(route="begin", premise=premise, opener=opener)
    if route == "steer":
        return StoryIntent(route="steer", opener=opener, edit=edit)
    return StoryIntent(route=route)


def storyboard_from_payload(payload: object, *, beats: int, current_character: str = "") -> Storyboard | None:
    if not isinstance(payload, dict) or not isinstance(payload.get("beats"), list):
        return None
    parsed: list[Beat] = []
    for item in payload["beats"][:MAX_BEATS]:
        if not isinstance(item, dict):
            continue
        narration = _line(item.get("narration"), 600)
        scene = _line(item.get("scene"), 300)
        motion = _line(item.get("motion"), 200)
        if narration and scene:
            parsed.append(Beat(narration=narration, scene=scene, motion=motion))
    if not parsed:
        return None
    del beats  # The count is a request, not a contract; a shorter chapter still plays.
    character = _line(payload.get("character"), 600)
    return Storyboard(
        title=_line(payload.get("title"), 120),
        setting=_line(payload.get("setting"), 100).casefold(),
        character=current_character or character,
        beats=tuple(parsed),
        remaining=_line(payload.get("remaining"), 300),
        finished=payload.get("finished") is True,
    )


@dataclass(frozen=True)
class StoryContext:
    """What the scout and writer know about the running piece."""

    premise: str = ""
    told: str = ""
    remaining: str = ""
    character: str = ""
    chapter: int = 0
    at_boundary: bool = True

    @property
    def active(self) -> bool:
        return bool(self.premise)


class StoryPlanner(ABC):
    @abstractmethod
    async def scout(self, utterance: str, context: StoryContext) -> StoryIntent:
        """Classify one utterance against the running story without speaking."""

    @abstractmethod
    async def plan(self, context: StoryContext, *, beats: int = DEFAULT_BEATS, edit: str = "") -> Storyboard | None:
        """Write the next chapter, or nothing when the writer is unavailable."""

    async def close(self) -> None:
        return


class NullStoryPlanner(StoryPlanner):
    async def scout(self, utterance: str, context: StoryContext) -> StoryIntent:
        del utterance, context
        return StoryIntent()

    async def plan(self, context: StoryContext, *, beats: int = DEFAULT_BEATS, edit: str = "") -> Storyboard | None:
        del context, beats, edit
        return None


class FalStoryPlanner(StoryPlanner):
    def __init__(self, api_key: str, *, scout_model: str = SCOUT_MODEL, plan_model: str = PLAN_MODEL) -> None:
        self._scout = FalTextClient(api_key, model=scout_model)
        self._plan = FalTextClient(api_key, model=plan_model)

    async def scout(self, utterance: str, context: StoryContext) -> StoryIntent:
        cleaned = " ".join(utterance.split())[:MAX_UTTERANCE_CHARS]
        if not cleaned:
            return StoryIntent()
        request = json.dumps({
            "utterance": cleaned,
            "story_running": context.active,
            "premise": context.premise,
            "told_so_far": context.told[-800:],
            "paused_mid_chapter": context.active and not context.at_boundary,
        }, ensure_ascii=False)
        try:
            response = await self._scout.complete(
                SCOUT_INSTRUCTIONS, request, schema=SCOUT_SCHEMA,
                timeout=SCOUT_TIMEOUT_SECONDS, max_tokens=300,
            )
            return intent_from_payload(json.loads(response), story_active=context.active)
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - a scout outage means ordinary conversation
            logger.warning("Story scout unavailable: model=%s error=%s", self._scout.model, type(error).__name__)
            return StoryIntent()

    async def plan(self, context: StoryContext, *, beats: int = DEFAULT_BEATS, edit: str = "") -> Storyboard | None:
        beats = max(1, min(MAX_BEATS, beats))
        request = json.dumps({
            "premise": context.premise,
            "chapter_number": context.chapter + 1,
            "beats": beats,
            "told_so_far": context.told[-MAX_TOLD_CHARS:],
            "planned_next": context.remaining,
            "saved_character": context.character,
            "edit": edit,
        }, ensure_ascii=False)
        try:
            response = await self._plan.complete(
                PLAN_INSTRUCTIONS, request, schema=PLAN_SCHEMA,
                timeout=PLAN_TIMEOUT_SECONDS, max_tokens=1400,
            )
            board = storyboard_from_payload(json.loads(response), beats=beats, current_character=context.character)
            if board is None:
                logger.warning("Story plan unusable: model=%s", self._plan.model)
            return board
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - no chapter is better than a broken one
            logger.warning("Story plan unavailable: model=%s error=%s", self._plan.model, type(error).__name__)
            return None

    async def close(self) -> None:
        await self._scout.close()
        await self._plan.close()


def story_planner_from_env(api_key: str | None = None) -> StoryPlanner:
    key = (api_key or os.environ.get("FAL_KEY") or "").strip()
    if not key:
        logger.warning("STORY PLANNER UNAVAILABLE: FAL_KEY missing")
        return NullStoryPlanner()
    return FalStoryPlanner(
        key,
        scout_model=os.environ.get("GIZMO_STORY_SCOUT_MODEL", SCOUT_MODEL),
        plan_model=os.environ.get("GIZMO_STORY_MODEL", PLAN_MODEL),
    )
