"""Entity behaviour -- the payoff of the whole project.

The assertions that matter: an Irismo must not advertise SET_POSITION, and a
Sonesse must. Everything else in this repository exists to make those two lines
true.
"""

from __future__ import annotations

from homeassistant.components.cover import CoverDeviceClass, CoverEntityFeature

from custom_components.ha_somfy.cover import SomfyGroupCover, SomfyMotorCover
from custom_components.ha_somfy.uai.models import Capability, GroupInfo, Node

from .conftest import IRISMO_ID, SONESSE_30_ID, SONESSE_ID


def _motor(coordinator, node_id: str) -> SomfyMotorCover:
    node = coordinator.nodes[node_id]
    return SomfyMotorCover(coordinator, coordinator.entry, node, node.name)


# ---------------------------------------------------------------------------
# The core fix
# ---------------------------------------------------------------------------


def test_irismo_does_not_advertise_set_position(coordinator) -> None:
    """The bug this project exists to fix.

    An Irismo behind an SDN bridge has no position feedback at all. Advertising
    SET_POSITION gives it a slider that can never work and a state that is
    permanently unknown -- which is what every other UAI+ integration does.
    """
    cover = _motor(coordinator, IRISMO_ID)
    assert CoverEntityFeature.SET_POSITION not in cover.supported_features
    assert CoverEntityFeature.OPEN in cover.supported_features
    assert CoverEntityFeature.CLOSE in cover.supported_features
    assert CoverEntityFeature.STOP in cover.supported_features


def test_irismo_reports_assumed_state_and_no_position(coordinator) -> None:
    cover = _motor(coordinator, IRISMO_ID)
    assert cover.assumed_state is True
    assert cover.current_cover_position is None
    assert cover.is_closed is None


def test_sonesse_does_advertise_set_position(coordinator) -> None:
    cover = _motor(coordinator, SONESSE_ID)
    assert CoverEntityFeature.SET_POSITION in cover.supported_features
    assert cover.assumed_state is False


def test_sonesse_with_unknown_position_keeps_set_position(coordinator) -> None:
    """A motor that replied `false` is still position-capable.

    Its position reads as unknown, but its feature set must not change -- a
    slider that appears and disappears between polls would be worse than one
    that occasionally shows nothing.
    """
    cover = _motor(coordinator, SONESSE_30_ID)
    assert CoverEntityFeature.SET_POSITION in cover.supported_features
    assert cover.current_cover_position is None


def test_position_is_never_faked_as_zero(coordinator) -> None:
    """Unknown must stay unknown. Reporting 0 would show a blind as fully
    closed when nobody actually knows where it is."""
    for node_id in (IRISMO_ID, SONESSE_30_ID):
        assert _motor(coordinator, node_id).current_cover_position is None


# ---------------------------------------------------------------------------
# Device registry
# ---------------------------------------------------------------------------


def test_each_motor_is_its_own_device_showing_its_model(coordinator) -> None:
    """Upstream hangs all motors off one gateway device, which hides the very
    thing you need when diagnosing an Irismo."""
    irismo = _motor(coordinator, IRISMO_ID)
    sonesse = _motor(coordinator, SONESSE_ID)

    assert irismo.device_info["model"] == "SDN Module"
    assert sonesse.device_info["model"] == "Sonesse 50DC"
    assert irismo.device_info["identifiers"] != sonesse.device_info["identifiers"]


def test_irismo_presents_as_a_curtain(coordinator) -> None:
    assert _motor(coordinator, IRISMO_ID).device_class is CoverDeviceClass.CURTAIN
    assert _motor(coordinator, SONESSE_ID).device_class is CoverDeviceClass.SHADE


def test_motors_are_disabled_by_default_but_groups_are_not(coordinator) -> None:
    """Keeps state-change fan-out unchanged on a large panel fleet."""
    motor = _motor(coordinator, SONESSE_ID)
    group = SomfyGroupCover(coordinator, coordinator.entry, coordinator.groups["010114"])
    assert motor.entity_registry_enabled_default is False
    assert group.entity_registry_enabled_default is True


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------


def test_all_irismo_group_has_no_position_slider(coordinator) -> None:
    group = SomfyGroupCover(coordinator, coordinator.entry, coordinator.groups["01010A"])
    assert CoverEntityFeature.SET_POSITION not in group.supported_features
    assert group.current_cover_position is None


def test_all_sonesse_group_has_a_position_slider(coordinator) -> None:
    group = SomfyGroupCover(coordinator, coordinator.entry, coordinator.groups["010114"])
    assert CoverEntityFeature.SET_POSITION in group.supported_features


def test_mixed_group_falls_back_to_least_capable(coordinator) -> None:
    """No mixed group exists on the reference bus, but claiming SET_POSITION
    for a group containing an Irismo would reintroduce the original bug."""
    coordinator.groups["0101FF"] = GroupInfo(
        group_id="0101FF", index=255, name="Mixed", members=[SONESSE_ID, IRISMO_ID]
    )
    group = SomfyGroupCover(coordinator, coordinator.entry, coordinator.groups["0101FF"])
    assert CoverEntityFeature.SET_POSITION not in group.supported_features


def test_group_position_ignores_members_with_unknown_position(coordinator) -> None:
    """Averaging must not treat 'unknown' as zero and drag the average down."""
    coordinator.nodes["AAAAAA"] = Node(
        node_id="AAAAAA",
        name="Extra",
        type_string="Sonesse 50DC",
        capability=Capability.POSITIONAL,
        position=None,
    )
    coordinator.groups["0101FE"] = GroupInfo(
        group_id="0101FE", index=254, name="Partial", members=[SONESSE_ID, "AAAAAA"]
    )
    group = SomfyGroupCover(coordinator, coordinator.entry, coordinator.groups["0101FE"])
    # Only SONESSE_ID contributes; gateway 0 maps to HA 100.
    assert group.current_cover_position == 100


# ---------------------------------------------------------------------------
# Churn control
# ---------------------------------------------------------------------------


async def test_state_is_written_only_when_something_changed(hass, coordinator) -> None:
    """Every state change is broadcast to the whole panel fleet, so a no-op
    refresh must not produce a write."""
    cover = _motor(coordinator, SONESSE_ID)
    cover.hass = hass
    cover.entity_id = "cover.test"

    writes = 0

    def count_write() -> None:
        nonlocal writes
        writes += 1

    cover.async_write_ha_state = count_write  # type: ignore[method-assign]

    cover._handle_coordinator_update()
    assert writes == 1

    # Nothing changed -- must not write again.
    cover._handle_coordinator_update()
    cover._handle_coordinator_update()
    assert writes == 1

    # A real change must write.
    coordinator.nodes[SONESSE_ID].position = 50
    cover._handle_coordinator_update()
    assert writes == 2
