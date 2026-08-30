from __future__ import annotations

from dataclasses import dataclass, field

from gizmo_friend.prompt import FROZEN_PROMPT

# ~500 tokens. Local rewrite, no extra model required.
MAX_SUMMARY_CHARS = 2000
MAX_EPISODES_IN_PREFIX = 6
MAX_FACTS_IN_PREFIX = 12


@dataclass
class PrefixMemory:
    name: str | None = None
    facts: list[str] = field(default_factory=list)
    summary: str = ""
    episodes: list[str] = field(default_factory=list)
    objects: list[str] = field(default_factory=list)


def assemble_prefix(memory: PrefixMemory) -> str:
    """Frozen prompt first (cacheable), then a compact memory block."""
    return FROZEN_PROMPT + "\n\n" + _memory_block(memory)


def _memory_block(memory: PrefixMemory) -> str:
    name = memory.name if memory.name else "(unknown — ask once)"
    facts = memory.facts[:MAX_FACTS_IN_PREFIX]
    facts_line = "; ".join(facts) if facts else "(none yet)"
    summary = (memory.summary or "").strip()[:MAX_SUMMARY_CHARS] or "(none yet)"
    episodes = memory.episodes[-MAX_EPISODES_IN_PREFIX:]
    episode_lines = "\n".join(f"- {e}" for e in episodes) if episodes else "- (none yet)"
    objects = memory.objects
    object_lines = "\n".join(f"- {o}" for o in objects) if objects else "- (none yet)"
    return (
        "Memory for this kid (use it; do not dump it at them):\n"
        f"Name: {name}\n"
        f"Facts they told you: {facts_line}\n"
        f"Running summary: {summary}\n"
        f"Recent episodes:\n{episode_lines}\n"
        f"Pages they have:\n{object_lines}"
    )
