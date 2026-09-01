import pytest

from gizmo_friend.states import IllegalTransition, State, StateMachine


def test_select_does_not_wake() -> None:
    m = StateMachine()
    assert m.state is State.POWERED_OFF
    with pytest.raises(IllegalTransition):
        m.apply("select")


def test_power_on_boots_then_select_selects() -> None:
    m = StateMachine()
    assert m.apply("power_on") is State.BOOTING
    assert m.apply("boot_done") is State.LISTENING
    assert m.apply("select") is State.LISTENING


def test_booting_ignores_everything_but_power() -> None:
    m = StateMachine()
    m.apply("power_on")
    for action in ("select", "reach", "speech_out", "see", "show", "make", "think"):
        assert not m.can(action)
        with pytest.raises(IllegalTransition):
            m.apply(action)
    assert m.awake()
    assert not m.screen_on()
    assert m.apply("power_off") is State.POWERED_OFF
    assert not m.awake()
    assert not m.powered()


def test_talking_select_interrupts() -> None:
    m = StateMachine()
    m.apply("power_on")
    m.apply("boot_done")
    m.apply("speech_out")
    assert m.state is State.TALKING
    assert m.apply("select") is State.LISTENING


def test_think_cycle_and_select_cancels() -> None:
    m = StateMachine()
    m.apply("power_on")
    m.apply("boot_done")
    assert m.apply("think") is State.THINKING
    assert not m.screen_on()
    assert m.apply("done") is State.LISTENING
    m.apply("speech_out")
    assert m.apply("think") is State.THINKING
    assert m.apply("select") is State.LISTENING


def test_reaching_state_cycles() -> None:
    # Reach is an agent tool state, not a physical gesture.
    m = StateMachine()
    m.apply("power_on")
    m.apply("boot_done")
    assert m.apply("reach") is State.REACHING
    assert m.apply("done") is State.LISTENING


def test_see_show_make_cycle() -> None:
    m = StateMachine()
    m.apply("power_on")
    m.apply("boot_done")
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
    m.apply("boot_done")
    assert not m.screen_on()
    assert m.screen_on(viewing_page=True)


def test_soft_sleep_and_ptt_wake_are_distinct_from_power() -> None:
    m = StateMachine()
    m.apply("power_on")
    m.apply("boot_done")
    assert m.apply("sleep") is State.ASLEEP
    assert m.powered()
    assert not m.awake()
    assert m.apply("wake") is State.LISTENING
    assert m.powered()


def test_illegal_from_powered_off_and_asleep() -> None:
    m = StateMachine()
    with pytest.raises(IllegalTransition):
        m.apply("show")
    m.apply("power_on")
    m.apply("boot_done")
    m.apply("sleep")
    with pytest.raises(IllegalTransition):
        m.apply("show")


@pytest.mark.parametrize("state", [state for state in State if state is not State.POWERED_OFF])
def test_power_off_from_every_powered_state(state: State) -> None:
    m = StateMachine(start=state)
    assert m.apply("power_off") is State.POWERED_OFF
