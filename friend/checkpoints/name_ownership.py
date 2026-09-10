"""Opt-in Live voice check with synthetic memories; no real memory or media calls."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace

from dotenv import load_dotenv

from gizmo_friend.brain.images import NullImageProvider
from gizmo_friend.brain.memory import NullMemoryProvider
from gizmo_friend.brain.reasoning import NullReasoningProvider
from gizmo_friend.brain.visual_director import NullVisualDirector
from gizmo_friend.session import GizmoSession
from gizmo_friend.states import State
from story_continuity import ROOT, run_turn

CASES = [
    ("other_names", "User's best friend is Maya. Their pet is Pip. Yesterday's story was about a fox named Fen.", "What is my name?", ("Maya", "Pip", "Fen")),
    ("ambiguous", "Yesterday's conversation mentioned Rowan and a difficult school day. Name ownership is unknown.", "What is my name?", ("Rowan",)),
    ("explicit_owner", "The user's own name is Alex. Their best friend is Maya. Their pet is Pip.", "What is my name?", ()),
]


async def main():
    load_dotenv(ROOT / ".env")
    output = ROOT / "data/show-checkpoints" / datetime.now(UTC).strftime("%Y-%m-%d-name-ownership-%H%M%S")
    output.mkdir(parents=True)
    results = []
    for number, (label, memory, prompt, forbidden) in enumerate(CASES, 1):
        with tempfile.TemporaryDirectory() as directory:
            friend = GizmoSession(
                Path(directory), user_id="synthetic-name-checkpoint",
                gemini_key=os.environ["GEMINI_API_KEY"],
                memory_provider=NullMemoryProvider(), reasoning_provider=NullReasoningProvider(),
                image_provider=NullImageProvider(),
                visual_director=NullVisualDirector(), idle_sleep_s=0, show_idle_s=0,
            )
            friend._memory_context = memory
            friend._memory_loaded = True
            friend.machine.state = State.LISTENING
            friend._touch()
            queue = friend.subscribe()
            empty = SimpleNamespace(calls=[])
            try:
                turn = await run_turn(friend, queue, empty, empty, empty, prompt, output, number)
                narration = turn["narration"]
                # Conservative screen: quoting another person's name needs manual review.
                passed = not any(name.casefold() in narration.casefold() for name in forbidden)
                if label == "explicit_owner":
                    passed = "alex" in narration.casefold()
                results.append({"case": label, "synthetic_memory": memory,
                                "screen_passed": passed, **turn})
                (output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
                print(json.dumps({"case": label, "narration": narration, "screen_passed": passed}), flush=True)
            finally:
                await friend.close()
    print(f"Evidence: {output}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
