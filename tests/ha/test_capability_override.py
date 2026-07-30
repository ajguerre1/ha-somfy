"""CAP-02: the manual capability override.

Detection has been right on all 49 nodes of the reference bus, so this exists
for hardware nobody here has seen -- a type string the classifier does not
recognise, on someone else's gateway.

The override is applied at the *coordinator*, not the entity, and that is the
whole design. Capability decides whether a node is polled at all, so an
override that only reached `supported_features` would hand someone a position
slider attached to a motor nothing ever reads.
"""

from __future__ import annotations

import pytest

from custom_components.ha_somfy.const import CONF_CAPABILITY_OVERRIDES
from custom_components.ha_somfy.uai.models import Capability

from .conftest import IRISMO_ID, SONESSE_30_ID, SONESSE_ID


def _set_overrides(hass, coordinator, overrides: dict[str, str]) -> None:
    hass.config_entries.async_update_entry(
        coordinator.config_entry, options={CONF_CAPABILITY_OVERRIDES: overrides}
    )


def _polled(mock_client) -> set[str]:
    return {call.args[0] for call in mock_client.async_get_position.call_args_list}


async def test_without_overrides_every_capability_is_the_detected_one(
    hass, coordinator, mock_client
) -> None:
    """The guard that keeps this feature invisible until someone asks for it."""
    await coordinator.async_discover()

    assert coordinator.nodes[SONESSE_ID].capability is Capability.POSITIONAL
    assert coordinator.nodes[IRISMO_ID].capability is Capability.NON_POSITIONAL


async def test_a_motor_forced_positional_starts_being_polled(
    hass, coordinator, mock_client
) -> None:
    """Forcing capability has to change behaviour, not just the feature flags."""
    _set_overrides(hass, coordinator, {IRISMO_ID: Capability.POSITIONAL})

    await coordinator.async_discover()
    assert coordinator.nodes[IRISMO_ID].capability is Capability.POSITIONAL

    mock_client.async_get_position.reset_mock()
    await coordinator._async_update_data()

    assert IRISMO_ID in _polled(mock_client)


async def test_a_motor_forced_non_positional_stops_being_polled(
    hass, coordinator, mock_client
) -> None:
    """The likelier direction in practice: silencing a motor whose position
    never resolves, so it stops generating bus traffic and a dead slider."""
    _set_overrides(hass, coordinator, {SONESSE_30_ID: Capability.NON_POSITIONAL})

    await coordinator.async_discover()
    mock_client.async_get_position.reset_mock()
    await coordinator._async_update_data()

    assert SONESSE_30_ID not in _polled(mock_client)
    assert SONESSE_ID in _polled(mock_client)


async def test_an_overridden_motor_is_never_followed_while_moving(
    hass, coordinator, mock_client
) -> None:
    """Fast-follow filters on capability too, so an override must reach it --
    otherwise a forced-non-positional motor would still be fast-polled."""
    _set_overrides(hass, coordinator, {SONESSE_ID: Capability.NON_POSITIONAL})
    await coordinator.async_discover()

    coordinator.async_follow_movement([SONESSE_ID])

    assert coordinator._moving == set()


async def test_the_override_is_reapplied_on_every_discovery(hass, coordinator, mock_client) -> None:
    """Discovery rebuilds nodes from the gateway's type strings each time. A
    once-only application would be silently undone by the next reconnect."""
    _set_overrides(hass, coordinator, {IRISMO_ID: Capability.POSITIONAL})

    await coordinator.async_discover()
    await coordinator.async_discover()
    await coordinator.async_discover()

    assert coordinator.nodes[IRISMO_ID].capability is Capability.POSITIONAL


async def test_an_override_naming_an_unknown_node_is_harmless(
    hass, coordinator, mock_client
) -> None:
    """A motor can be removed from the bus while its override lingers in the
    config entry. That must not break discovery for everything else."""
    _set_overrides(hass, coordinator, {"ZZZZZZ": Capability.POSITIONAL})

    await coordinator.async_discover()

    assert "ZZZZZZ" not in coordinator.nodes
    assert coordinator.nodes[IRISMO_ID].capability is Capability.NON_POSITIONAL


@pytest.mark.parametrize("garbage", ["", "sideways", "unknown", None])
async def test_a_meaningless_override_leaves_detection_alone(
    hass, coordinator, mock_client, garbage: object
) -> None:
    _set_overrides(hass, coordinator, {IRISMO_ID: garbage})

    await coordinator.async_discover()

    assert coordinator.nodes[IRISMO_ID].capability is Capability.NON_POSITIONAL


async def test_a_corrupt_overrides_value_does_not_break_discovery(
    hass, coordinator, mock_client
) -> None:
    """Options are JSON on disk and can be hand-edited. Discovery is the path
    to every entity in the integration, so it must not be the thing that dies."""
    hass.config_entries.async_update_entry(
        coordinator.config_entry, options={CONF_CAPABILITY_OVERRIDES: "not-a-mapping"}
    )

    await coordinator.async_discover()

    assert coordinator.nodes[IRISMO_ID].capability is Capability.NON_POSITIONAL
