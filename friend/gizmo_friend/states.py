from __future__ import annotations

from enum import Enum


class State(str, Enum):
    POWERED_OFF = "powered_off"
    ASLEEP = "asleep"
    BOOTING = "booting"
    LISTENING = "listening"
    TALKING = "talking"
    THINKING = "thinking"
    SEEING = "seeing"
    SHOWING = "showing"
    MAKING = "making"
    REACHING = "reaching"


class IllegalTransition(Exception):
    def __init__(self, src: State, action: str) -> None:
        super().__init__(f"cannot {action} from {src.value}")
        self.src = src
        self.action = action


# (from, action) -> to. Tool "done" returns to listening.
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
    (State.LISTENING, "see"): State.SEEING,
    (State.TALKING, "see"): State.SEEING,
    (State.SEEING, "done"): State.LISTENING,
    (State.SEEING, "select"): State.LISTENING,
    (State.LISTENING, "show"): State.SHOWING,
    (State.TALKING, "show"): State.SHOWING,
    (State.SEEING, "show"): State.SHOWING,
    (State.SHOWING, "done"): State.LISTENING,
    (State.SHOWING, "select"): State.LISTENING,
    (State.LISTENING, "make"): State.MAKING,
    (State.TALKING, "make"): State.MAKING,
    (State.SHOWING, "make"): State.MAKING,
    (State.MAKING, "done"): State.LISTENING,
    (State.MAKING, "select"): State.LISTENING,
    (State.LISTENING, "reach"): State.REACHING,
    (State.TALKING, "reach"): State.REACHING,
    (State.SHOWING, "reach"): State.REACHING,
    (State.MAKING, "reach"): State.REACHING,
    (State.REACHING, "done"): State.LISTENING,
    (State.REACHING, "select"): State.LISTENING,
}

for active_state in (
    State.LISTENING,
    State.TALKING,
    State.THINKING,
    State.SEEING,
    State.SHOWING,
    State.MAKING,
    State.REACHING,
):
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

    def screen_on(self, viewing_page: bool = False) -> bool:
        return self.state in {State.SHOWING, State.MAKING} or viewing_page
