from __future__ import annotations

from enum import Enum


class State(str, Enum):
    ASLEEP = "asleep"
    LISTENING = "listening"
    TALKING = "talking"
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
# Hold (reach) is allowed from listening or talking.
_TRANSITIONS: dict[tuple[State, str], State] = {
    (State.ASLEEP, "power_on"): State.LISTENING,
    (State.LISTENING, "click"): State.LISTENING,
    (State.LISTENING, "speech_out"): State.TALKING,
    (State.TALKING, "click"): State.LISTENING,
    (State.TALKING, "done"): State.LISTENING,
    (State.LISTENING, "see"): State.SEEING,
    (State.TALKING, "see"): State.SEEING,
    (State.SEEING, "done"): State.LISTENING,
    (State.SEEING, "click"): State.LISTENING,
    (State.LISTENING, "show"): State.SHOWING,
    (State.TALKING, "show"): State.SHOWING,
    (State.SEEING, "show"): State.SHOWING,
    (State.SHOWING, "done"): State.LISTENING,
    (State.SHOWING, "click"): State.LISTENING,
    (State.LISTENING, "make"): State.MAKING,
    (State.TALKING, "make"): State.MAKING,
    (State.SHOWING, "make"): State.MAKING,
    (State.MAKING, "done"): State.LISTENING,
    (State.MAKING, "click"): State.LISTENING,
    (State.LISTENING, "hold"): State.REACHING,
    (State.TALKING, "hold"): State.REACHING,
    (State.SHOWING, "hold"): State.REACHING,
    (State.MAKING, "hold"): State.REACHING,
    (State.REACHING, "done"): State.LISTENING,
    (State.REACHING, "click"): State.LISTENING,
    (State.LISTENING, "power_off"): State.ASLEEP,
    (State.TALKING, "power_off"): State.ASLEEP,
    (State.SEEING, "power_off"): State.ASLEEP,
    (State.SHOWING, "power_off"): State.ASLEEP,
    (State.MAKING, "power_off"): State.ASLEEP,
    (State.REACHING, "power_off"): State.ASLEEP,
}


class StateMachine:
    def __init__(self, start: State = State.ASLEEP) -> None:
        self.state = start

    def can(self, action: str) -> bool:
        return (self.state, action) in _TRANSITIONS

    def apply(self, action: str) -> State:
        key = (self.state, action)
        if key not in _TRANSITIONS:
            raise IllegalTransition(self.state, action)
        self.state = _TRANSITIONS[key]
        return self.state

    def screen_on(self, viewing_page: bool = False) -> bool:
        return self.state in {State.SHOWING, State.MAKING} or viewing_page
