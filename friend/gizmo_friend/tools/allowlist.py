from __future__ import annotations

ALLOWED_TOOLS = ("see", "show", "make", "reach")
FORBIDDEN_TOOLS = ("web_search", "browser", "search", "mcp", "code_interpreter")

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "name": "see",
        "description": (
            "Look out the world camera. Name what's there in one beat. "
            "Use only when this moment needs looking. The body provides the frame; "
            "you may omit image."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "image": {
                    "type": "string",
                    "description": "Unused. The current outward frame is grabbed by the body.",
                }
            },
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "show",
        "description": (
            "Show the thing in our print look: one still, then at most two short clips. "
            "Never photoreal, never their face, never a third clip, never a player."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "subject": {
                    "type": "string",
                    "description": "What to show, in a few words (e.g. pinecone).",
                }
            },
            "required": ["subject"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "make",
        "description": (
            "Keep one page — the still plus one line you wrote together. Instant. Tomorrow you still have it."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "line": {
                    "type": "string",
                    "description": "The one line on the page.",
                },
                "subject": {
                    "type": "string",
                    "description": "Optional. What the page is of.",
                },
            },
            "required": ["line"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "reach",
        "description": (
            "They held the stick. Queue the current page to a parent's phone. "
            "Not a live call. You are not a phone."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
]


def assert_allowlist(schemas: list[dict] | None = None) -> list[str]:
    names = [s["name"] for s in (schemas if schemas is not None else TOOL_SCHEMAS)]
    extra = [n for n in names if n not in ALLOWED_TOOLS]
    if extra:
        raise ValueError(f"tools not on allowlist: {extra}")
    forbidden = [n for n in names if n in FORBIDDEN_TOOLS]
    if forbidden:
        raise ValueError(f"forbidden tools: {forbidden}")
    missing = [n for n in ALLOWED_TOOLS if n not in names]
    if missing:
        raise ValueError(f"missing tools: {missing}")
    return names
