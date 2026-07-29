"""Config flow.

The headline test is that the flow can actually finish. An existing UAI+
integration's flow cannot: its second step takes two positional parameters, so
Home Assistant binds the submitted form to the wrong one and the step loops
forever. That is a filed, unfixed bug, and this suite exists to make sure the
same mistake cannot land here unnoticed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_HOST
from homeassistant.data_entry_flow import FlowResultType

from custom_components.ha_somfy.const import DOMAIN
from custom_components.ha_somfy.uai.client import UaiAuthError, UaiConnectionError

from .conftest import ENTRY_DATA


def _client_returning(nodes):
    client = AsyncMock()
    client.async_discover_nodes.return_value = nodes
    return client


async def test_flow_completes_and_creates_an_entry(hass, nodes) -> None:
    """The regression guard: a flow that runs to completion."""
    with patch(
        "custom_components.ha_somfy.config_flow.UaiClient",
        return_value=_client_returning(list(nodes.values())),
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "user"

        result = await hass.config_entries.flow.async_configure(result["flow_id"], ENTRY_DATA)
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "confirm"

        # Submitting the confirm step must create the entry, not redisplay
        # the form.
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_HOST] == ENTRY_DATA[CONF_HOST]


async def test_confirm_step_reports_the_capability_split(hass, nodes) -> None:
    """The user should see how many motors lack position feedback before
    committing, rather than discovering it later from a broken slider."""
    with patch(
        "custom_components.ha_somfy.config_flow.UaiClient",
        return_value=_client_returning(list(nodes.values())),
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(result["flow_id"], ENTRY_DATA)

    placeholders = result["description_placeholders"]
    assert placeholders["motors"] == "3"
    assert placeholders["positional"] == "2"
    assert placeholders["non_positional"] == "1"


async def test_bad_credentials_are_rejected(hass) -> None:
    """Merely opening a socket succeeds with any credentials, so the flow has
    to authenticate for real."""
    client = AsyncMock()
    client.async_connect.side_effect = UaiAuthError("nope")

    with patch("custom_components.ha_somfy.config_flow.UaiClient", return_value=client):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(result["flow_id"], ENTRY_DATA)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_unreachable_gateway_is_reported(hass) -> None:
    client = AsyncMock()
    client.async_connect.side_effect = UaiConnectionError("no route")

    with patch("custom_components.ha_somfy.config_flow.UaiClient", return_value=client):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(result["flow_id"], ENTRY_DATA)

    assert result["errors"] == {"base": "cannot_connect"}


async def test_gateway_with_no_motors_is_rejected(hass) -> None:
    """Better an explicit error than an integration that installs empty."""
    with patch(
        "custom_components.ha_somfy.config_flow.UaiClient",
        return_value=_client_returning([]),
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(result["flow_id"], ENTRY_DATA)

    assert result["errors"] == {"base": "no_motors"}


async def test_same_gateway_cannot_be_added_twice(hass, nodes) -> None:
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, unique_id=ENTRY_DATA[CONF_HOST]).add_to_hass(
        hass
    )

    with patch(
        "custom_components.ha_somfy.config_flow.UaiClient",
        return_value=_client_returning(list(nodes.values())),
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(result["flow_id"], ENTRY_DATA)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
