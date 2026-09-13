"""Curated OddityOS moments for the public browser preview."""
from __future__ import annotations

import os
import json
from pathlib import Path
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Moment:
    id: str
    line: str
    seed: str | Callable[[], str]
    contract: str
    demo: dict[str, object] | None = None

    def seed_text(self) -> str:
        return self.seed() if callable(self.seed) else self.seed

    def public(self) -> dict[str, object]:
        payload: dict[str, object] = {"id": self.id, "line": self.line}
        if self.demo:
            payload["demo"] = self.demo
        return payload


def _today():
    tz_name = os.environ.get("GIZMO_TZ", "UTC").strip() or "UTC"
    try:
        zone = ZoneInfo(tz_name)
    except Exception:
        zone = ZoneInfo("UTC")
    return datetime.now(zone).date()


def birthday_seed() -> str:
    today = _today()
    when = today + timedelta(days=11)
    return (
        f"Today is {today.strftime('%B')} {today.day}, {today.year}. The kid's birthday is "
        f"{when.strftime('%B')} {when.day}, {when.year}. They have already asked you to remember it. "
        "Do not mention the date unless the current question needs it."
    )


MOMENTS: dict[str, Moment] = {}
_RECORDINGS = json.loads((Path(__file__).resolve().parents[1] / 'static' / 'demo-refresh-timing.json').read_text())


def _recording(name: str) -> dict:
    return {key: _RECORDINGS[name][key] for key in ('reply', 'reply_audio', 'reply_timed')}

ORDER: tuple[str, ...] = (
    "birthday",
    "plant",
    "draw",
    "mathcheck",
    "rainbow",
    "ants",
    "homework",
    "trex",
    "antarctica",
    "pompeii",
)


def _register(*moments: Moment) -> None:
    for moment in moments:
        MOMENTS[moment.id] = moment


_register(
    Moment(
        id="birthday",
        line="How many more days until my birthday?",
        seed=birthday_seed,
        contract=(
            "The kid is asking how many days remain until their birthday. You already know "
            "the date from memory. Answer with the number of days in two or three warm, friendly "
            "sentences. Keep the "
            "normal Gizmo face on screen: do not generate an image, video, diagram, or "
            "interactive scene. Do not ask them to restate the date."
        ),
        demo={
            "prompt": "Gizmo, how many more days until my birthday?",
            "prompt_audio": "/static/demo-birthday-kid.mp3?v=days1",
            "prompt_timed": [
                [0.19, "Gizmo,"],
                [1.30, "how many more"],
                [2.19, "days until my"],
                [3.07, "birthday?"],
            ],
            "reply": (
                "Eleven more days. That's close enough to start getting excited. "
                "Your birthday will be here before you know it."
            ),
            "reply_audio": "/static/demo-birthday-gizmo.wav?v=days1",
            **_recording('birthday'),
        },
    ),
    Moment(
        id="plant",
        line="What's wrong with this plant?",
        seed="",
        contract=(
            "The kid is showing you an outdoor plant through Gizmo's camera. Describe only "
            "the visible symptoms instead of claiming a certain diagnosis. Give a short, "
            "calm answer and suggest what to inspect next. Keep the live camera view moving "
            "while you answer and do not generate other media."
        ),
        demo={
            "prompt": "Gizmo, what's wrong with this plant?",
            "prompt_audio": "/static/demo-plant-question.mp3?v=plant5",
            "reply": (
                "Your plant caught a tiny fungal bug, which causes dark spots, yellow circles, and crispy "
                "brown edges. Help it heal by snipping off the sick leaves and throwing them in the trash. "
                "Water only the dirt around the base, keeping the other leaves dry so the fungus can't spread."
            ),
            "reply_audio": "/static/demo-plant-gizmo.wav?v=plant8",
            "reply_audio_rate": 0.92,
            **_recording('plant'),
            "camera": {
                "video": "/static/demo-plant-camera.mp4?v=plant6",
                "start_at": 2.6,
                "reply_wait_ms": 1000,
                "loop": True,
                "cues": [
                    {
                        "at": 3.05,
                        "prompt": "Gizmo, what's wrong with this plant?",
                        "audio": "/static/demo-plant-question.mp3?v=plant5",
                    },
                ],
            },
        },
    ),
    Moment(
        id="draw",
        line="What should I draw?",
        seed=(
            "The kid often talks about Adventure Time and especially likes Jake the Dog. "
            "They have asked you to remember that."
        ),
        contract=(
            "They want a drawing idea. Use what you remember about their interests. "
            "Propose one concrete subject and put a simple visual reference on screen. "
            "Do not ask them to pick a medium or app."
        ),
        demo={
            "prompt": "Gizmo, what should I draw?",
            "prompt_audio": "/static/demo-draw-kid.mp3?v=draw1",
            "reply": (
                "You're always talking about Adventure Time, so I recommend Jake the Dog. "
                "His round body, simple legs, and big eyes make him easy and fun to draw."
            ),
            "reply_audio": "/static/demo-draw-gizmo.wav?v=draw1",
            "image": "/static/demo-draw-jake.png?v=draw1",
            "subject": "Jake the Dog from Adventure Time",
            "keep_scene": True,
            "fullscreen_after_reply": True,
        },
    ),
    Moment(
        id="mathcheck",
        line="Did I get this right?",
        seed=(
            "The kid is checking a fraction picture. Two of four equal parts are blue, but they wrote 2/3."
        ),
        contract=(
            "Praise the attempt before correcting it. Explain that the numerator counts the two shaded "
            "parts and the denominator counts all four equal parts. Show that the picture is 2/4, which "
            "simplifies to 1/2. Keep the tone suitable for a child aged 6 to 10."
        ),
        demo={
            "prompt": "Gizmo, did I get this right?",
            "prompt_audio": "/static/demo-math-kid.mp3?v=math2",
            "reply": (
                "Almost! You counted the two blue parts correctly, so two goes on top. "
                "But the circle is split into four equal parts, so four goes on the bottom. "
                "That is two-fourths, which is the same as one-half. Nice job checking!"
            ),
            "reply_audio": "/static/demo-math-fraction-gizmo.wav?v=fraction1",
            "reply_audio_rate": 1.0,
            "camera": {
                "video": "/static/demo-math-fraction-camera.mp4?v=fraction1",
                "start_at": 5.2,
                "home_wait_ms": 1000,
                "reply_wait_ms": 900,
                "loop": True,
                "cues": [
                    {
                        "at": 6.0,
                        "prompt": "Gizmo, did I get this right?",
                        "audio": "/static/demo-math-kid.mp3?v=math2",
                    },
                ],
            },
            "math": {
                "visual_timed": [[0.0, 0], [2.8, 1], [4.2, 2], [7.8, 3], [11.5, 4]],
                "attempt": "2/3",
                "attempt_lead": "You wrote ",
                "shaded": "shaded parts",
                "total": "equal parts",
                "answer": "2/4 = 1/2",
                "description": (
                    "A colorful fraction circle split into four equal pieces with two pieces shaded, "
                    "showing that two-fourths simplifies to one-half."
                ),
            },
        },
    ),
    Moment(
        id="rainbow",
        line="How does a rainbow happen?",
        seed="",
        contract=(
            "Explain how sunlight makes a rainbow inside raindrops with a simple animated visual: "
            "light bends as it enters, reflects inside, then bends again and separates into colors. "
            "If the kid interrupts to ask why the light splits, pause the first explanation, zoom in "
            "on the outgoing light, and explain that white light contains many colors that bend by "
            "slightly different amounts. Keep the language warm and suitable for ages 6 to 10."
        ),
        demo={
            "prompt": "Gizmo, how does a rainbow happen?",
            "prompt_audio": "/static/demo-rainbow-kid.mp3?v=rainbow2",
            "beats": [
                {
                    "reply": (
                        "Sunlight enters a raindrop and bends. It reflects off the back of the drop, "
                        "then bends again as it comes out. That spreading light makes a rainbow."
                    ),
                    "reply_audio": "/static/demo-rainbow-gizmo-intro.wav?v=rainbow2",
                    "rainbow": {"focus": "overview"},
                    "interruption": {
                        "after_ms": 12600,
                        "prompt": "Wait, why does the light split?",
                        "audio": "/static/demo-rainbow-kid-followup.mp3?v=rainbow2",
                        "think_wait_ms": 1200,
                    },
                },
                {
                    "reply": (
                        "White sunlight is actually many colors traveling together. Each color bends "
                        "by a slightly different amount, so they spread apart like a fan opening—red "
                        "through violet."
                    ),
                    "reply_audio": "/static/demo-rainbow-gizmo-split.wav?v=rainbow2",
                    "rainbow": {"focus": "split"},
                },
            ],
        },
    ),
    Moment(
        id="ants",
        line="Who would win, 100 ants or one spider?",
        seed="",
        contract=(
            "This is a playful matchup, not a gore fight. Clarify the kinds of ants and "
            "spider so the contest is fair, then reason out loud with a tiny battle-card "
            "or diagram. Keep it short, funny, and specific. Do not declare a winner "
            "before the comparison is visible."
        ),
    ),
    Moment(
        id="homework",
        line="I don't get this.",
        seed="",
        contract=(
            "They are stuck on schoolwork. If the problem is not in this turn, ask once "
            "what they are looking at, then wait. When you have the problem, find the "
            "actual confusion, teach one idea with a concrete visual analogy (pizza "
            "slices for fractions when that fits), and check understanding. Do not invent "
            "a worksheet. Stay with them if they are still lost."
        ),
    ),
    Moment(
        id="trex",
        line="Could a T-Rex beat an elephant?",
        seed="",
        contract=(
            "Do not give the conclusion first. Ask what they think, let them make a case, "
            "challenge one assumption, and bring in visual comparisons (size, bite, tusks, "
            "speed) as evidence. Help them reach a conclusion together. The value is "
            "reasoning, not crowning a winner."
        ),
    ),
    Moment(
        id="antarctica",
        line="What does Antarctica look like?",
        seed="",
        contract=(
            "Answer with a short educational film that first locates Antarctica on a globe, "
            "then travels across its ice sheet, mountains, glaciers, coast, icebergs, and "
            "penguins. Explain that it surrounds the South Pole and that its interior is a "
            "cold, windy desert. Keep the geography accurate, the transitions fluid, and the "
            "imagery colorful, gentle, and suitable for children."
        ),
        demo={
            "prompt": "Gizmo, what does Antarctica look like?",
            "prompt_audio": "/static/demo-antarctica-kid.mp3?v=antarctica1",
            "reply": (
                "Antarctica is the icy continent at the very bottom of Earth. On a globe, it "
                "wraps around the South Pole. Most of it is covered by a huge sheet of ice, "
                "with bright glaciers, tall mountains, and deep blue cracks. Along the coast, "
                "you can see floating icebergs and penguins, while the middle is a cold, windy "
                "white desert."
            ),
            "reply_audio": "/static/demo-antarctica-gizmo.wav?v=antarctica3",
            "video": "/static/demo-antarctica.mp4?v=antarctica1",
            "beats": [
                {
                    "reply": (
                        "Antarctica is the icy continent at the very bottom of Earth. On a globe, "
                        "it wraps around the South Pole. Most of it is covered by a huge sheet of "
                        "ice, with bright glaciers, tall mountains, and deep blue cracks. Along the "
                        "coast, you can see floating icebergs and penguins."
                    ),
                    "reply_audio": "/static/demo-antarctica-gizmo.wav?v=antarctica3",
                    "video": "/static/demo-antarctica.mp4?v=antarctica1",
                    "interruption": {
                        "after_ms": 22000,
                        "prompt": "Do penguins live anywhere else besides Antarctica?",
                        "audio": "/static/demo-antarctica-followup-kid.mp3?v=penguin1",
                        "think_wait_ms": 650,
                        "fullscreen_during_prompt": True,
                    },
                },
                {
                    "reply": (
                        "Yes! Penguins also live in South America, southern Africa, Australia, "
                        "New Zealand, and the Galapagos Islands. Not every penguin lives somewhere icy."
                    ),
                    "reply_audio": "/static/demo-antarctica-followup-gizmo.wav?v=penguin1",
                    "video": "/static/demo-antarctica-followup.mp4?v=penguin1",
                },
            ],
        },
    ),
    Moment(
        id="pompeii",
        line="What happened to Pompeii?",
        seed="",
        contract=(
            "This is a living encyclopedia, not an article: the story of Pompeii is a "
            "film. Brief Cinema to set the scene, reconstruct the eruption, and land on "
            "what the ash preserved, in roughly 35 to 45 seconds. Every shot must be "
            "gentle, colorful, kid-friendly, and free of injury, bodies, remains, or "
            "frightening close-ups. If they interrupt, answer that curiosity first, then "
            "continue. Keep Vesuvius serious but not gory."
        ),
        demo={
            "prompt": "Gizmo, what happened to Pompeii a long time ago?",
            "prompt_audio": "/static/demo-pompeii-kid.mp3",
            "prompt_timed": [
                [0.25, "Gizmo,"],
                [1.29, "what happened to"],
                [2.26, "Pompeii"],
                [2.59, "a long time ago?"],
            ],
            "reply": (
                "Almost two thousand years ago, the city of Pompeii sat at the "
                "foot of a mountain called Vesuvius, and one day it erupted "
                "without warning. The mountain blasted ash and rock high into "
                "the sky, and a giant grey cloud raced down its sides faster "
                "than anyone could run. The ash buried Pompeii so completely "
                "that it stayed hidden for centuries, and when diggers "
                "uncovered it, the houses, streets and paintings were still "
                "there."
            ),
            "reply_audio": "/static/demo-pompeii.wav",
            "video": "/static/demo-pompeii-polished.mp4",
            "followup": {
                "prompt": _RECORDINGS['pompeii-kid-followup']['reply'],
                "audio": "/static/demo-pompeii-kid-followup-user.mp3?v=pompeii1",
                "video": "/static/demo-pompeii-followup.mp4?v=pompeii1",
                "fullscreen_during_prompt": True,
                "reply_wait_ms": 800,
                **_recording('pompeii-followup'),
            },
        },
    ),
)


def catalog() -> list[dict[str, object]]:
    return [MOMENTS[key].public() for key in ORDER if key in MOMENTS and MOMENTS[key].demo]


def lookup(moment_id: str) -> Moment | None:
    return MOMENTS.get(moment_id)
