from gizmo_friend.prefix import PrefixMemory, assemble_prefix
from gizmo_friend.prompt import FROZEN_PROMPT
from gizmo_friend.transport.openai_realtime import session_update_payload


def test_frozen_prompt_is_the_prefix() -> None:
    built = assemble_prefix(PrefixMemory(name="Rio", facts=["has a dog named Toast"]))
    assert built.startswith(FROZEN_PROMPT)
    assert built.index(FROZEN_PROMPT) == 0
    assert "Rio" in built
    assert "Toast" in built
    assert built.find("Rio") > len(FROZEN_PROMPT)


def test_unknown_name_asks_once_in_memory_block() -> None:
    built = assemble_prefix(PrefixMemory())
    assert "unknown" in built
    assert built.startswith(FROZEN_PROMPT)


def test_session_payload_keeps_frozen_front_and_low_reasoning() -> None:
    instructions = assemble_prefix(PrefixMemory(name="Maya"))
    payload = session_update_payload(instructions)
    session = payload["session"]
    assert session["model"] == "gpt-realtime-2.1-mini"
    assert session["reasoning"]["effort"] == "low"
    assert session["audio"]["input"]["turn_detection"] is None
    assert session["instructions"].startswith(FROZEN_PROMPT)
    names = [t["name"] for t in session["tools"]]
    assert names == ["see", "show", "make", "think", "reach"]
    assert "web_search" not in names


def test_no_second_personality_in_prompt_module() -> None:
    assert "Merlin" not in FROZEN_PROMPT
    assert "hocus pocus" in FROZEN_PROMPT  # as a ban, not a voice
    assert "as an AI" in FROZEN_PROMPT
