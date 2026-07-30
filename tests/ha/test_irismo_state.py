"""IRIS-01: open/closed state for motors telnet will not report.

All nine Irismo nodes refuse `sdn.status.position`, so until now their entities
had no state at all -- the group showed `unknown` forever. The gateway does
hold their open/closed state; it just serves it only from its web interface.

What these tests pin down is the *shape* of that: it is a second source, used
only for nodes the first source cannot answer, and only when a web password was
supplied. Without one, every assertion in the pre-existing suite must still
hold, which is why `test_without_a_web_password_nothing_changes` is here.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from custom_components.ha_somfy.uai.models import Capability

from .conftest import IRISMO_ID, SONESSE_30_ID, SONESSE_ID


@pytest.fixture
def web() -> AsyncMock:
    client = AsyncMock()
    client.configured = True
    client.async_get_position.return_value = 100
    return client


def _telnet_polled(mock_client) -> set[str]:
    return {call.args[0] for call in mock_client.async_get_position.call_args_list}


def _web_polled(web) -> set[str]:
    return {call.args[0] for call in web.async_get_position.call_args_list}


# ---------------------------------------------------------------------------
# The feature
# ---------------------------------------------------------------------------


async def test_an_irismo_gets_its_state_from_the_web_interface(coordinator, web) -> None:
    coordinator.web = web

    await coordinator._async_update_data()

    assert coordinator.nodes[IRISMO_ID].position == 100
    assert IRISMO_ID in _web_polled(web)


async def test_telnet_is_still_never_asked_about_an_irismo(coordinator, web, mock_client) -> None:
    """The original fan-out guard has to survive. Nine nodes that answer
    `-32600` every time must not be asked over telnet just because a second
    source appeared."""
    coordinator.web = web

    await coordinator._async_update_data()

    assert IRISMO_ID not in _telnet_polled(mock_client)


async def test_sonesse_still_comes_from_telnet_not_the_web(coordinator, web, mock_client) -> None:
    """Telnet answers position-capable motors directly and needs no session, so
    routing them through the web interface would be slower and more fragile for
    no gain."""
    coordinator.web = web

    await coordinator._async_update_data()

    assert SONESSE_ID in _telnet_polled(mock_client)
    assert SONESSE_ID not in _web_polled(web)
    assert SONESSE_30_ID not in _web_polled(web)


async def test_a_missed_web_read_keeps_the_last_known_state(coordinator, web) -> None:
    """The state only changes when the gateway is commanded, so a failed read
    is transport noise rather than news.

    Blanking it would flick the entity to `unknown` and back, and every one of
    those transitions reaches the whole wall-panel fleet.
    """
    coordinator.web = web
    await coordinator._async_update_data()
    assert coordinator.nodes[IRISMO_ID].position == 100

    web.async_get_position.return_value = None
    await coordinator._async_update_data()

    assert coordinator.nodes[IRISMO_ID].position == 100


async def test_a_never_read_irismo_stays_unknown(coordinator, web) -> None:
    """Keeping the last value must not become inventing a first one."""
    coordinator.web = web
    web.async_get_position.return_value = None

    await coordinator._async_update_data()

    assert coordinator.nodes[IRISMO_ID].position is None


async def test_an_irismo_is_followed_after_a_command(coordinator, web) -> None:
    """The gateway updates its record within about two seconds of the command,
    so waiting up to a minute for the next poll would be the same lag PERF-03
    fixed for Sonesse."""
    coordinator.web = web

    coordinator.async_follow_movement([IRISMO_ID])

    assert coordinator._moving == {IRISMO_ID}


# ---------------------------------------------------------------------------
# With no web password, nothing changes
# ---------------------------------------------------------------------------


async def test_without_a_web_password_nothing_changes(coordinator, mock_client) -> None:
    """The regression guard for every existing install."""
    coordinator.web = None

    await coordinator._async_update_data()

    assert coordinator.nodes[IRISMO_ID].position is None
    assert IRISMO_ID not in _telnet_polled(mock_client)
    assert coordinator.nodes[IRISMO_ID].capability is Capability.NON_POSITIONAL


async def test_an_unconfigured_web_client_is_the_same_as_none(coordinator, web) -> None:
    """A web client exists but no password was given -- it must not be used."""
    web.configured = False
    coordinator.web = web

    await coordinator._async_update_data()
    coordinator.async_follow_movement([IRISMO_ID])

    assert _web_polled(web) == set()
    assert coordinator._moving == set()


async def test_an_irismo_is_not_followed_without_a_web_password(coordinator) -> None:
    coordinator.web = None

    coordinator.async_follow_movement([IRISMO_ID])

    assert coordinator._moving == set()


# ---------------------------------------------------------------------------
# Capability is untouched by any of this
# ---------------------------------------------------------------------------


async def test_reading_state_does_not_make_an_irismo_positional(coordinator, web) -> None:
    """The whole point of the project. Knowing open from closed is not the same
    as being able to travel to 43 %, and the bridge still cannot do the latter.
    """
    coordinator.web = web

    await coordinator._async_update_data()

    assert coordinator.nodes[IRISMO_ID].capability is Capability.NON_POSITIONAL
