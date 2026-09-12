"""Curated OddityOS moments for the public browser preview."""
from __future__ import annotations

import os
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
ORDER: tuple[str, ...] = (
    "birthday",
    "plant",
    "draw",
    "mathcheck",
    "ants",
    "homework",
    "trex",
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
            "reply": "Brown spots and yellow edges mean this leaf needs more shade.",
            "reply_audio": "/static/demo-plant-gizmo.wav?v=plant8",
            "reply_audio_rate": 1.0,
            "camera": {
                "video": "/static/demo-plant-camera.mp4?v=plant5",
                "start_at": 2.6,
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
        },
    ),
    Moment(
        id="mathcheck",
        line="Did I get this right?",
        seed=(
            "The kid is checking their work on 27 + 16. They wrote 42, but the correct answer is 43."
        ),
        contract=(
            "Praise the attempt before correcting it. Explain regrouping with a make-a-ten method in "
            "simple language: move 3 from the 6 to the 7 to make another 10, leaving 3, then combine "
            "four tens and three ones. Show each step visually and keep the tone suitable for a child "
            "aged 6 to 10."
        ),
        demo={
            "prompt": "Gizmo, did I get this right?",
            "prompt_audio": "/static/demo-math-kid.mp3?v=math2",
            "reply": (
                "Nice work—you were only one away! Twenty-seven plus sixteen is forty-three, not "
                "forty-two. Look at the ones: move three from the six to the seven to make a new ten, "
                "with three left. Now we have four tens and three ones, which makes forty-three. "
                "Great job checking your answer!"
            ),
            "reply_audio": "/static/demo-math-gizmo.wav?v=math1",
            "reply_audio_rate": 1.0,
            "camera": {
                "video": "/static/demo-math-camera.mp4?v=math3",
                "start_at": 0,
                "home_wait_ms": 1000,
                "reply_wait_ms": 2000,
                "loop": True,
                "cues": [
                    {
                        "at": 1.0,
                        "prompt": "Gizmo, did I get this right?",
                        "audio": "/static/demo-math-kid.mp3?v=math2",
                    },
                ],
            },
            "math": {
                "attempt": "27 + 16 = 42",
                "make_ten": "7 + 3 = 10",
                "left": "3 left",
                "answer": "40 + 3 = 43",
                "description": (
                    "Twenty-seven plus sixteen corrected from forty-two to forty-three by regrouping "
                    "the ones into a new ten, with three ones left."
                ),
            },
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
            "video": "/static/demo-pompeii.mp4",
        },
    ),
)


def catalog() -> list[dict[str, object]]:
    return [MOMENTS[key].public() for key in ORDER if key in MOMENTS and MOMENTS[key].demo]


def lookup(moment_id: str) -> Moment | None:
    return MOMENTS.get(moment_id)
