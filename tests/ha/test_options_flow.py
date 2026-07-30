"""The options flow.

Two things here are load-bearing.

Every step handler takes exactly one positional parameter -- see `config_flow`'s
module docstring for the filed, unfixed bug in prior art that rule prevents.

And saving one section must not wipe the other. `async_create_entry` replaces
the options dict wholesale, so the obvious implementation of a second step
silently discards the poll interval the moment anyone sets a capability
override. There is a test for each direction below, because that failure is
invisible until someone notices their polling went back to 60 s.
"""

from __future__ import annotations

import pytest
from homeassistant.data_entry_flow import FlowResultType

from custom_components.ha_somfy.const import (
    CONF_CAPABILITY,
    CONF_CAPABILITY_OVERRIDES,
    CONF_MOTOR,
    CONF_POLL_INTERVAL,
    CONF_WEB_PASSWORD,
    DOMAIN,
)
from custom_components.ha_somfy.uai.models import OVERRIDE_AUTO, Capability

from .conftest import IRISMO_ID, SONESSE_ID


@pytest.fixture
def entry(hass, coordinator):
    """A configured entry whose coordinator is reachable, since the capability
    step lists the motors discovery actually found."""
    hass.data.setdefault(DOMAIN, {})[coordinator.config_entry.entry_id] = coordinator
    return coordinator.config_entry


async def _override_motor(hass, entry, node_id: str, capability: str) -> dict:
    """Walk the whole flow: menu -> capability -> pick motor -> set it."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "capability"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_MOTOR: node_id}
    )
    return await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_CAPABILITY: capability}
    )


async def _set_poll_interval(hass, entry, seconds: int) -> dict:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "polling"}
    )
    return await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_POLL_INTERVAL: seconds}
    )


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------


async def test_the_flow_offers_polling_capability_and_the_web_password(hass, entry) -> None:
    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] is FlowResultType.MENU
    assert set(result["menu_options"]) == {"polling", "capability", "web"}


async def test_the_motor_list_comes_from_discovery(hass, entry, coordinator) -> None:
    """Typing a node ID by hand is exactly the kind of thing this integration
    exists to avoid, so the picker offers what was actually found."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "capability"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "capability"

    options = result["data_schema"].schema[CONF_MOTOR].config["options"]
    assert {option["value"] for option in options} == set(coordinator.nodes)


# ---------------------------------------------------------------------------
# Saving
# ---------------------------------------------------------------------------


async def test_an_override_is_saved_against_the_motor(hass, entry) -> None:
    result = await _override_motor(hass, entry, IRISMO_ID, Capability.POSITIONAL)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_CAPABILITY_OVERRIDES] == {IRISMO_ID: Capability.POSITIONAL}


async def test_choosing_auto_clears_a_previous_override(hass, entry) -> None:
    """Returning to automatic must remove the key, not store the string "auto"
    -- a lingering value would keep reappearing as the current setting."""
    await _override_motor(hass, entry, IRISMO_ID, Capability.POSITIONAL)
    result = await _override_motor(hass, entry, IRISMO_ID, OVERRIDE_AUTO)

    assert result["data"][CONF_CAPABILITY_OVERRIDES] == {}


async def test_two_motors_can_be_overridden_independently(hass, entry) -> None:
    await _override_motor(hass, entry, IRISMO_ID, Capability.POSITIONAL)
    result = await _override_motor(hass, entry, SONESSE_ID, Capability.NON_POSITIONAL)

    assert result["data"][CONF_CAPABILITY_OVERRIDES] == {
        IRISMO_ID: Capability.POSITIONAL,
        SONESSE_ID: Capability.NON_POSITIONAL,
    }


# ---------------------------------------------------------------------------
# The merge guard
# ---------------------------------------------------------------------------


async def test_setting_an_override_keeps_the_poll_interval(hass, entry) -> None:
    await _set_poll_interval(hass, entry, 120)

    result = await _override_motor(hass, entry, IRISMO_ID, Capability.POSITIONAL)

    assert result["data"][CONF_POLL_INTERVAL] == 120


async def test_changing_the_poll_interval_keeps_the_overrides(hass, entry) -> None:
    await _override_motor(hass, entry, IRISMO_ID, Capability.POSITIONAL)

    result = await _set_poll_interval(hass, entry, 120)

    assert result["data"][CONF_CAPABILITY_OVERRIDES] == {IRISMO_ID: Capability.POSITIONAL}
    assert result["data"][CONF_POLL_INTERVAL] == 120


async def test_the_poll_interval_still_saves_on_its_own(hass, entry) -> None:
    """The pre-existing behaviour, kept honest now that a menu sits in front."""
    result = await _set_poll_interval(hass, entry, 30)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_POLL_INTERVAL] == 30


# ---------------------------------------------------------------------------
# The web interface credential (IRIS-01)
# ---------------------------------------------------------------------------


async def _set_web_password(hass, entry, password: str) -> dict:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "web"}
    )
    return await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_WEB_PASSWORD: password}
    )


async def test_the_web_password_can_be_added_after_setup(hass, entry) -> None:
    """It lives in the options precisely so an integration installed before
    this feature existed does not have to be removed and re-added."""
    result = await _set_web_password(hass, entry, "webpw")

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_WEB_PASSWORD] == "webpw"


async def test_clearing_it_turns_the_feature_off(hass, entry) -> None:
    await _set_web_password(hass, entry, "webpw")

    result = await _set_web_password(hass, entry, "")

    assert result["data"][CONF_WEB_PASSWORD] == ""


async def test_the_web_password_survives_the_other_options_steps(hass, entry) -> None:
    await _set_web_password(hass, entry, "webpw")

    result = await _set_poll_interval(hass, entry, 120)

    assert result["data"][CONF_WEB_PASSWORD] == "webpw"
    assert result["data"][CONF_POLL_INTERVAL] == 120
