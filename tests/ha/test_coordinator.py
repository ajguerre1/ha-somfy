"""Following a moving motor.

At the default 60 s interval a shade you just opened reads its old position for
most of a minute, which looks broken. These tests pin the fix down, and just as
importantly pin down what it must *not* do: the target system fans every state
change out to ~48 wall panels, so fast-polling must stay narrow.
"""

from __future__ import annotations

import pytest

from custom_components.ha_somfy import coordinator as coordinator_module

from .conftest import IRISMO_ID, SONESSE_30_ID, SONESSE_ID


@pytest.fixture(autouse=True)
def _instant_polls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove the real 2 s wait so these run instantly."""
    monkeypatch.setattr(coordinator_module, "MOVING_POLL_INTERVAL", 0)


async def test_irismo_is_never_followed(coordinator, mock_client) -> None:
    """An Irismo has no position to read, so following it is pure noise.

    This is the fan-out guard: nine motors that can never report anything must
    not generate a single extra request.
    """
    coordinator.async_follow_movement([IRISMO_ID])

    assert coordinator._moving == set()
    mock_client.async_get_position.assert_not_called()


async def test_unknown_node_is_ignored(coordinator, mock_client) -> None:
    coordinator.async_follow_movement(["ZZZZZZ"])

    assert coordinator._moving == set()
    mock_client.async_get_position.assert_not_called()


async def test_only_the_commanded_motor_is_polled(coordinator, mock_client) -> None:
    """Moving one blind must not poll the other forty."""
    mock_client.async_get_position.side_effect = [90, 80, 80, 80, 80]
    coordinator._moving = {SONESSE_ID}

    await coordinator._async_follow_movement()

    polled = {call.args[0] for call in mock_client.async_get_position.call_args_list}
    assert polled == {SONESSE_ID}
    assert SONESSE_30_ID not in polled


async def test_following_stops_once_the_motor_settles(coordinator, mock_client) -> None:
    """Three unchanged readings end it, rather than running to the ceiling."""
    mock_client.async_get_position.side_effect = [90, 80, 80, 80, 80, 80, 80]
    coordinator._moving = {SONESSE_ID}

    await coordinator._async_follow_movement()

    # 2 changing reads, then 3 unchanged to settle. Anything more means it
    # kept polling a stationary motor.
    assert mock_client.async_get_position.call_count == 5
    assert coordinator._moving == set()
    assert coordinator.nodes[SONESSE_ID].position == 80


async def test_position_is_updated_while_moving(coordinator, mock_client) -> None:
    """The whole point: the entity sees the new position promptly."""
    mock_client.async_get_position.side_effect = [70, 70, 70]
    coordinator._moving = {SONESSE_ID}
    assert coordinator.nodes[SONESSE_ID].position == 0

    await coordinator._async_follow_movement()

    assert coordinator.nodes[SONESSE_ID].position == 70


async def test_a_slow_start_does_not_end_the_follow_early(coordinator, mock_client) -> None:
    """A motor takes a moment to start after the command.

    If the first unchanged reading ended the follow, every movement would be
    missed entirely -- the settle threshold exists for exactly this.
    """
    # Unchanged twice while the motor spins up, then it actually moves.
    mock_client.async_get_position.side_effect = [0, 0, 40, 30, 30, 30, 30]
    coordinator._moving = {SONESSE_ID}

    await coordinator._async_follow_movement()

    assert coordinator.nodes[SONESSE_ID].position == 30


async def test_a_failed_poll_does_not_abort_the_follow(coordinator, mock_client) -> None:
    """One dropped reply should not strand the entity on a stale position."""
    from custom_components.ha_somfy.uai.client import UaiTimeoutError

    mock_client.async_get_position.side_effect = [
        60,
        UaiTimeoutError("dropped"),
        50,
        50,
        50,
        50,
    ]
    coordinator._moving = {SONESSE_ID}

    await coordinator._async_follow_movement()

    assert coordinator.nodes[SONESSE_ID].position == 50
