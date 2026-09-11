"""Small trusted interaction vocabulary; a model never supplies executable code."""
from __future__ import annotations

import math


def orbit_result(value: object) -> dict:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Invalid launch speed")
    speed = float(value)
    if not math.isfinite(speed) or not 0.4 <= speed <= 1.7:
        raise ValueError("Invalid launch speed")
    # Units: Earth radius = 1, GM = 1. Launch tangentially at r = 1.4.
    # For subcircular launches r_peri = r_apo*f^2/(2-f^2).
    if speed >= math.sqrt(2):
        outcome = "escape"
    elif speed < 1 and 1.4 * speed**2 / (2 - speed**2) <= 1:
        outcome = "surface"
    elif abs(speed - 1) < 0.005:
        outcome = "circular"
    else:
        outcome = "elliptical"
    return {"speed": speed, "outcome": outcome, "model": "central gravity, no atmosphere, launch radius 1.4 Earth radii"}


def interaction_answer(current: dict, message: dict, turn: str) -> tuple[str, dict]:
    """Validate against the presented invitation, never client-authored narration."""
    invitation = current.get("interaction")
    if (not invitation or not current.get("awaiting") or message.get("turn") != turn
            or message.get("id") != current.get("id")):
        raise ValueError("That invitation is no longer active")
    if invitation["kind"] == "orbit":
        trials = current.get("trials", [])
        if not trials:
            raise ValueError("Launch once before discussing the result")
        trial = trials[-1]
        text = f"I tried a launch at {trial['speed']:g} times circular speed. What happened?"
        return text, {"kind": "orbit", "trials": trials[-6:], "prompt": invitation["prompt"]}
    raise ValueError("Tell Gizmo your thought using voice or text")
