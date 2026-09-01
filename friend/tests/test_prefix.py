from gizmo_friend.prefix import PrefixMemory, assemble_prefix
from gizmo_friend.prompt import FROZEN_PROMPT
from gizmo_friend.transport.gemini_live import MODEL, live_config


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


def test_live_config_keeps_frozen_front_search_and_v1_tools() -> None:
    instructions = assemble_prefix(PrefixMemory(name="Maya"))
    config = live_config(instructions)
    assert MODEL == "gemini-3.1-flash-live-preview"
    assert str(config.system_instruction).startswith(FROZEN_PROMPT)
    assert config.realtime_input_config.automatic_activity_detection.disabled is True
    assert config.tools[0].google_search is not None
    names = [declaration.name for declaration in config.tools[1].function_declarations]
    assert names == ["deep_think", "set_expression"]


def test_no_second_personality_in_prompt_module() -> None:
    assert "Merlin" not in FROZEN_PROMPT
    assert "hocus pocus" in FROZEN_PROMPT  # as a ban, not a voice
    assert "as an AI" in FROZEN_PROMPT
