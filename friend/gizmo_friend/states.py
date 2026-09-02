from __future__ import annotations

from enum import Enum


class State(str, Enum):
    POWERED_OFF = "powered_off"
    ASLEEP = "asleep"
    BOOTING = "booting"
    LISTENING = "listening"
    TALKING = "talking"
    THINKING = "thinking"


class IllegalTransition(Exception):
    def __init__(self, src: State, action: str) -> None:
        super().__init__(f"cannot {action} from {src.value}")
        self.src = src
        self.action = action


# (from, action) -> to. "done" always returns to listening.
_TRANSITIONS: dict[tuple[State, str], State] = {
    (State.POWERED_OFF, "power_on"): State.BOOTING,
    (State.ASLEEP, "wake"): State.LISTENING,
    (State.ASLEEP, "power_off"): State.POWERED_OFF,
    (State.BOOTING, "boot_done"): State.LISTENING,
    (State.BOOTING, "power_off"): State.POWERED_OFF,
    (State.LISTENING, "select"): State.LISTENING,
    (State.LISTENING, "speech_out"): State.TALKING,
    (State.TALKING, "select"): State.LISTENING,
    (State.TALKING, "done"): State.LISTENING,
    (State.LISTENING, "think"): State.THINKING,
    (State.TALKING, "think"): State.THINKING,
    (State.THINKING, "done"): State.LISTENING,
    (State.THINKING, "select"): State.LISTENING,
}

for active_state in (State.LISTENING, State.TALKING, State.THINKING):
    _TRANSITIONS[(active_state, "sleep")] = State.ASLEEP
    _TRANSITIONS[(active_state, "power_off")] = State.POWERED_OFF


class StateMachine:
    def __init__(self, start: State = State.POWERED_OFF) -> None:
        self.state = start

    def can(self, action: str) -> bool:
        return (self.state, action) in _TRANSITIONS

    def apply(self, action: str) -> State:
        key = (self.state, action)
        if key not in _TRANSITIONS:
            raise IllegalTransition(self.state, action)
        self.state = _TRANSITIONS[key]
        return self.state

    def awake(self) -> bool:
        return self.state not in {State.POWERED_OFF, State.ASLEEP}

    def powered(self) -> bool:
        return self.state is not State.POWERED_OFF
