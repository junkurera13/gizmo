import pytest

from gizmo_friend.states import IllegalTransition, State, StateMachine


def test_click_wakes_and_sleeps() -> None:
    m = StateMachine()
    assert m.state is State.ASLEEP
    assert m.apply("click") is State.LISTENING
    assert m.apply("click") is State.ASLEEP


def test_talking_click_interrupts() -> None:
    m = StateMachine()
    m.apply("click")
    m.apply("speech_out")
    assert m.state is State.TALKING
    assert m.apply("click") is State.LISTENING


def test_hold_is_reach() -> None:
    m = StateMachine()
    m.apply("click")
    assert m.apply("hold") is State.REACHING
    assert m.apply("done") is State.LISTENING


def test_see_show_make_cycle() -> None:
    m = StateMachine()
    m.apply("click")
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
    m.apply("click")
    assert not m.screen_on()
    assert m.screen_on(viewing_page=True)


def test_illegal_from_asleep() -> None:
    m = StateMachine()
    with pytest.raises(IllegalTransition):
        m.apply("show")
