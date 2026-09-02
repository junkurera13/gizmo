"""Provider-side content guardrails for a device used by 9–14 year olds.

These are Gemini's own safety filters, configured once here and applied to
every model call Gizmo makes (Live voice and deep_think). The prompt's SAFETY
section handles tone; this handles what the model is allowed to produce at all.
"""

from __future__ import annotations

from google.genai import types

_LOW = types.HarmBlockThreshold.BLOCK_LOW_AND_ABOVE
_MEDIUM = types.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE

# Dangerous content stays at MEDIUM on purpose: "how do volcanoes erupt" and
# "why did the Titanic sink" are exactly the rabbit holes Gizmo exists for,
# and LOW blocks a lot of ordinary science and history for kids.
KID_SAFETY_SETTINGS: list[types.SafetySetting] = [
    types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=_LOW),
    types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=_LOW),
    types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=_LOW),
    types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=_MEDIUM),
]
