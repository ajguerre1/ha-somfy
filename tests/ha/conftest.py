"""Fixtures for the Home Assistant dependent suite.

These run in CI on Linux only -- Home Assistant cannot be imported on Windows,
and the root conftest skips this directory when it is unavailable.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME

from custom_components.ha_somfy.const import DOMAIN
from custom_components.ha_somfy.uai.models import Capability, GroupInfo, Node

SONESSE_ID = "136EA5"
SONESSE_30_ID = "07753E"
IRISMO_ID = "40FD76"

ENTRY_DATA = {
    CONF_HOST: "10.0.0.1",
    CONF_PORT: 23,
    CONF_USERNAME: "user",
    CONF_PASSWORD: "secret",
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Required for Home Assistant to load a custom component in tests."""
    return


@pytest.fixture
def nodes() -> dict[str, Node]:
    """Three nodes mirroring the real bus: two Sonesse and one Irismo."""
    return {
        SONESSE_ID: Node(
            node_id=SONESSE_ID,
            name="RoomE Bed B/O",
            type_string="Sonesse 50DC",
            capability=Capability.POSITIONAL,
            position=0,
            groups=["010114"],
        ),
        SONESSE_30_ID: Node(
            node_id=SONESSE_30_ID,
            name="RoomB SH 2",
            type_string="Sonesse 30",
            capability=Capability.POSITIONAL,
            # The real motor replies `false`; position is unknown but the node
            # is still position-capable.
            position=None,
            groups=["010105"],
        ),
        IRISMO_ID: Node(
            node_id=IRISMO_ID,
            name="RoomI SH 1",
            type_string="SDN Module",
            capability=Capability.NON_POSITIONAL,
            position=None,
            groups=["01010A"],
        ),
    }


@pytest.fixture
def groups() -> dict[str, GroupInfo]:
    return {
        "010114": GroupInfo(
            group_id="010114", index=20, name="RoomE Bed B/O", members=[SONESSE_ID]
        ),
        "01010A": GroupInfo(group_id="01010A", index=10, name="RoomI SH", members=[IRISMO_ID]),
    }


@pytest.fixture
def mock_client(nodes: dict[str, Node]) -> AsyncMock:
    client = AsyncMock()
    client.connected = True
    client.async_discover_nodes.return_value = list(nodes.values())
    client.async_get_position.return_value = None
    client.async_move_up.return_value = True
    client.async_move_down.return_value = True
    client.async_move_stop.return_value = True
    client.async_move_to.return_value = True
    return client


@pytest.fixture
def coordinator(hass, mock_client, nodes, groups):
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.ha_somfy.coordinator import SomfyCoordinator

    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, entry_id="test_entry")
    entry.add_to_hass(hass)

    coord = SomfyCoordinator(hass, entry, mock_client, poll_interval=60)
    coord.nodes = nodes
    coord.groups = groups
    coord.entry = entry
    return coord
