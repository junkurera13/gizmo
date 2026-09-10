from __future__ import annotations

# Google Search is a native Gemini tool and is deliberately not represented as
# an application function. These are the only functions Gizmo itself executes.
ALLOWED_TOOLS = ("deep_think", "set_expression", "show")

# Visual work never pauses speech or provokes a follow-up model turn.
# set_expression remains a placeholder while Jun designs the face.
NON_BLOCKING_TOOLS = frozenset({"set_expression", "show"})

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "name": "show",
        "description": (
            "Put an original illustration of a subject on the glass. Returns immediately; "
            "the picture arrives in the background while you continue answering. "
            "The visual style is fixed by the device. After calling this tool, never mention the picture "
            "or ask whether the user wants to see it move."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "subject": {
                    "type": "string",
                    "description": "A concrete noun phrase with the one detail to depict, without style instructions.",
                },
            },
            "required": ["subject"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "deep_think",
        "description": (
            "Privately ask the deeper reasoning model to solve a genuinely difficult question. "
            "Use for multi-step reasoning, difficult math or science, or when a quick answer may "
            "be wrong. After the result returns, answer the user in Gizmo's own voice."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The complete question and any context needed to solve it.",
                }
            },
            "required": ["question"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "set_expression",
        "description": (
            "Placeholder. Character animation is not designed yet. Do not call this."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "enum": ["idle", "curious", "thinking", "happy", "concerned", "surprised"],
                }
            },
            "required": ["expression"],
            "additionalProperties": False,
        },
    },
]


def assert_allowlist(schemas: list[dict] | None = None) -> list[str]:
    names = [str(schema.get("name") or "") for schema in (schemas or TOOL_SCHEMAS)]
    extra = [name for name in names if name not in ALLOWED_TOOLS]
    if extra:
        raise ValueError(f"tools not on allowlist: {extra}")
    missing = [name for name in ALLOWED_TOOLS if name not in names]
    if missing:
        raise ValueError(f"missing tools: {missing}")
    return names
