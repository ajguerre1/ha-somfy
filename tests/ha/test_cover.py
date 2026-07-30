"""Entity behaviour -- the payoff of the whole project.

The assertions that matter: an Irismo must not advertise SET_POSITION, and a
Sonesse must. Everything else in this repository exists to make those two lines
true.
"""

from __future__ import annotations

from homeassistant.components.cover import CoverDeviceClass, CoverEntityFeature

from custom_components.ha_somfy.const import DOMAIN
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


# ---------------------------------------------------------------------------
# Entity attributes (TEST-01)
# ---------------------------------------------------------------------------
#
# These attributes ride along with every state write, and every state write
# reaches ~48 wall panels. So the assertion that earns its keep is not what the
# attributes contain but that they stay *still* while a motor moves.


def test_a_motor_publishes_its_identity_and_group_membership(coordinator) -> None:
    attrs = _motor(coordinator, IRISMO_ID).extra_state_attributes

    assert attrs["node_id"] == IRISMO_ID
    assert attrs["motor_type"] == "SDN Module"
    assert attrs["capability"] == "non_positional"
    assert attrs["groups"] == ["01010A"]


def test_a_group_publishes_its_address_and_members(coordinator) -> None:
    group = SomfyGroupCover(coordinator, coordinator.entry, coordinator.groups["010114"])
    attrs = group.extra_state_attributes

    assert attrs["group_id"] == "010114"
    assert attrs["group_index"] == 20
    assert attrs["members"] == [SONESSE_ID]
    assert attrs["member_count"] == 1


def test_motor_attributes_do_not_move_when_the_blind_does(coordinator) -> None:
    """The fan-out guard. A blind travelling from 0 to 100 writes state many
    times; if any attribute tracked position, each of those writes would carry a
    changed attribute payload to every panel."""
    cover = _motor(coordinator, SONESSE_ID)
    before = cover.extra_state_attributes

    for position in (10, 45, 90, 100):
        coordinator.nodes[SONESSE_ID].position = position
        assert cover.extra_state_attributes == before


def test_group_attributes_do_not_move_when_its_members_do(coordinator) -> None:
    group = SomfyGroupCover(coordinator, coordinator.entry, coordinator.groups["010114"])
    before = group.extra_state_attributes

    coordinator.nodes[SONESSE_ID].position = 55

    assert group.extra_state_attributes == before


def test_a_vanished_motor_publishes_no_attributes(coordinator) -> None:
    """A node dropped after three missed discovery passes must not raise while
    its entity is still registered."""
    cover = _motor(coordinator, SONESSE_ID)
    del coordinator.nodes[SONESSE_ID]

    assert cover.extra_state_attributes == {}


def test_a_vanished_group_publishes_no_attributes(coordinator) -> None:
    group = SomfyGroupCover(coordinator, coordinator.entry, coordinator.groups["010114"])
    del coordinator.groups["010114"]

    assert group.extra_state_attributes == {}


# ---------------------------------------------------------------------------
# Manual capability override (CAP-02)
# ---------------------------------------------------------------------------


def test_an_overridden_motor_gains_the_position_slider(coordinator) -> None:
    """The escape hatch working end to end.

    The coordinator applies the override to the node, so the entity needs no
    knowledge of overrides at all -- it keeps deriving features from capability,
    which is what CAP-03 guards.
    """
    coordinator.nodes[IRISMO_ID].capability = Capability.POSITIONAL

    cover = _motor(coordinator, IRISMO_ID)
    assert CoverEntityFeature.SET_POSITION in cover.supported_features
    assert cover.assumed_state is False


def test_overriding_one_member_lifts_its_whole_group(coordinator) -> None:
    """A group follows its least capable member, so an override on the member
    has to reach the group entity too."""
    group = SomfyGroupCover(coordinator, coordinator.entry, coordinator.groups["01010A"])
    assert CoverEntityFeature.SET_POSITION not in group.supported_features

    coordinator.nodes[IRISMO_ID].capability = Capability.POSITIONAL

    assert CoverEntityFeature.SET_POSITION in group.supported_features


# ---------------------------------------------------------------------------
# Irismo open/closed state (IRIS-01)
# ---------------------------------------------------------------------------


def test_an_irismo_reports_state_without_gaining_a_slider(coordinator) -> None:
    """Knowing open from closed is not the same as being able to travel to
    43 %. The bridge still cannot do the latter, so the feature set must not
    move an inch."""
    cover = _motor(coordinator, IRISMO_ID)

    coordinator.nodes[IRISMO_ID].position = 100  # gateway 100 = closed
    assert cover.is_closed is True
    assert CoverEntityFeature.SET_POSITION not in cover.supported_features
    assert cover.assumed_state is True

    coordinator.nodes[IRISMO_ID].position = 0
    assert cover.is_closed is False
    assert CoverEntityFeature.SET_POSITION not in cover.supported_features


def test_an_all_irismo_group_stops_reading_unknown(coordinator) -> None:
    """The reported symptom: `cover.somfy_uai_roomd_sh` sat at `unknown`
    forever because group position filtered on capability, and an Irismo is
    non-positional however much state it reports."""
    group = SomfyGroupCover(coordinator, coordinator.entry, coordinator.groups["01010A"])
    assert group.is_closed is None

    coordinator.nodes[IRISMO_ID].position = 100

    assert group.is_closed is True
    assert CoverEntityFeature.SET_POSITION not in group.supported_features


# ---------------------------------------------------------------------------
# One device per group (MIGRATE-06)
# ---------------------------------------------------------------------------


def test_each_group_is_its_own_device(coordinator) -> None:
    """All 24 groups used to hang off the single gateway device, which forced
    every group entity into whatever area the gateway was in. A group is the
    thing people actually operate and assign to a room."""
    roomd = SomfyGroupCover(coordinator, coordinator.entry, coordinator.groups["01010A"])
    guest = SomfyGroupCover(coordinator, coordinator.entry, coordinator.groups["010114"])

    assert roomd.device_info["identifiers"] != guest.device_info["identifiers"]
    assert roomd.device_info["name"] == "RoomI SH"
    assert guest.device_info["name"] == "RoomE Bed B/O"


def test_a_group_device_hangs_off_the_gateway(coordinator) -> None:
    """The gateway stays as the hub, so the device page still shows the whole
    installation as one tree."""
    group = SomfyGroupCover(coordinator, coordinator.entry, coordinator.groups["01010A"])

    assert group.device_info["via_device"] == (DOMAIN, coordinator.entry.entry_id)
    assert group.device_info["identifiers"] != {(DOMAIN, coordinator.entry.entry_id)}


def test_a_group_keeps_its_unique_id(coordinator) -> None:
    """The load-bearing assertion for existing installs.

    unique_id is what ties an entity to its registry entry. Changing it while
    moving the device would orphan all 24 entities -- new IDs, lost history,
    and every dashboard reference silently pointing at nothing.
    """
    group = SomfyGroupCover(coordinator, coordinator.entry, coordinator.groups["01010A"])

    assert group.unique_id == f"{coordinator.entry.entry_id}_group_01010A"


def test_motors_still_have_their_own_devices(coordinator) -> None:
    motor = _motor(coordinator, SONESSE_ID)

    assert motor.device_info["identifiers"] == {(DOMAIN, SONESSE_ID)}
    assert motor.device_info["via_device"] == (DOMAIN, coordinator.entry.entry_id)
