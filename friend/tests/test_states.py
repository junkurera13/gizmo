import pytest

from gizmo_friend.states import IllegalTransition, State, StateMachine


def test_click_does_not_wake() -> None:
    m = StateMachine()
    assert m.state is State.ASLEEP
    with pytest.raises(IllegalTransition):
        m.apply("click")


def test_power_on_wakes_and_click_selects() -> None:
    m = StateMachine()
    assert m.apply("power_on") is State.LISTENING
    assert m.apply("click") is State.LISTENING


def test_talking_click_interrupts() -> None:
    m = StateMachine()
    m.apply("power_on")
    m.apply("speech_out")
    assert m.state is State.TALKING
    assert m.apply("click") is State.LISTENING


def test_hold_is_reach() -> None:
    m = StateMachine()
    m.apply("power_on")
    assert m.apply("hold") is State.REACHING
    assert m.apply("done") is State.LISTENING


def test_see_show_make_cycle() -> None:
    m = StateMachine()
    m.apply("power_on")
    m.apply("see")
    assert m.state is State.SEEING
    m.apply("done")
    m.apply("show")
    assert m.screen_on()
    m.apply("done")
    m.apply("make")
    assert m.state is State.MAKING
    assert m.screen_on()
    m.apply("done")
    assert m.state is State.LISTENING
    assert not m.screen_on()


def test_screen_off_while_listening() -> None:
    m = StateMachine()
    m.apply("power_on")
    assert not m.screen_on()
    assert m.screen_on(viewing_page=True)


def test_illegal_from_asleep() -> None:
    m = StateMachine()
    with pytest.raises(IllegalTransition):
        m.apply("show")


@pytest.mark.parametrize("state", [state for state in State if state is not State.ASLEEP])
def test_power_off_from_every_awake_state(state: State) -> None:
    m = StateMachine(start=state)
    assert m.apply("power_off") is State.ASLEEP
