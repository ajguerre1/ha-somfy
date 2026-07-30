"""Cover entities for motors and groups.

This is where the point of the integration lands. `supported_features` is built
from each node's measured capability, so an Irismo behind an SDN bridge gets
open/close/stop and an honest `assumed_state`, while a Sonesse gets a working
position slider. No entity ever advertises a feature its hardware lacks.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CLOSED_POSITION_THRESHOLD,
    DOMAIN,
    MANUFACTURER,
    gateway_to_ha_position,
    ha_to_gateway_position,
)
from .coordinator import SomfyCoordinator
from .uai.models import Capability, GroupInfo, Node, capability_for_group, unique_slug_names

_LOGGER = logging.getLogger(__name__)

BASE_FEATURES = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP


def _device_class_for(type_string: str | None) -> CoverDeviceClass:
    """Best-effort device class from the gateway's type string.

    Irismo behind an SDN bridge is a drapery motor, so it presents as a curtain;
    Sonesse tubular motors are shades. This only affects the icon and wording.
    """
    normalised = (type_string or "").lower()
    if "sdn module" in normalised or "irismo" in normalised or "glydea" in normalised:
        return CoverDeviceClass.CURTAIN
    return CoverDeviceClass.SHADE


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one cover per motor and per group."""
    coordinator: SomfyCoordinator = hass.data[DOMAIN][entry.entry_id]

    display_names = unique_slug_names(
        [(node.node_id, node.name) for node in coordinator.nodes.values()]
    )

    # Groups and motors both declare the gateway as `via_device`. It is
    # registered explicitly during setup, before any entity is added, so
    # neither can reference a parent that does not exist yet (HA-06).
    entities: list[CoverEntity] = [
        SomfyGroupCover(coordinator, entry, group) for group in coordinator.groups.values()
    ]
    entities.extend(
        SomfyMotorCover(coordinator, entry, node, display_names[node.node_id])
        for node in coordinator.nodes.values()
    )

    async_add_entities(entities)


class _SomfyCoverBase(CoordinatorEntity[SomfyCoordinator], CoverEntity):
    """Shared behaviour: capability-driven features and change-gated writes."""

    _attr_has_entity_name = False

    def __init__(self, coordinator: SomfyCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._last_written: tuple[Any, ...] | None = None

    # -- capability --------------------------------------------------------

    @property
    def _capability(self) -> Capability:
        raise NotImplementedError

    @property
    def supported_features(self) -> CoverEntityFeature:
        """Features follow measured capability, never a hardcoded constant.

        Advertising SET_POSITION for a motor that cannot report or accept one is
        exactly the defect this integration was written to fix, so this must
        stay derived.
        """
        if self._capability is Capability.POSITIONAL:
            return BASE_FEATURES | CoverEntityFeature.SET_POSITION
        return BASE_FEATURES

    @property
    def assumed_state(self) -> bool:
        """True when we cannot read the real position, so HA shows discrete
        open/close controls rather than a toggle implying known state."""
        return self._capability is not Capability.POSITIONAL

    # -- change-gated state writes ----------------------------------------

    def _state_snapshot(self) -> tuple[Any, ...]:
        return (
            self.current_cover_position,
            self.is_closed,
            self.is_opening,
            self.is_closing,
            self.available,
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Write state only when something actually changed.

        CoordinatorEntity writes unconditionally on every refresh. With ~73
        entities and a wall-panel fleet that receives every state change, that
        would generate constant no-op churn.
        """
        snapshot = self._state_snapshot()
        if snapshot == self._last_written:
            return
        self._last_written = snapshot
        self.async_write_ha_state()


class SomfyMotorCover(_SomfyCoverBase):
    """One physical motor.

    Registered but disabled by default: the groups are what day-to-day control
    uses, and enabling 49 extra entities by default would add state-change
    fan-out for no immediate benefit. Any motor can be enabled from the UI.
    """

    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        coordinator: SomfyCoordinator,
        entry: ConfigEntry,
        node: Node,
        display_name: str,
    ) -> None:
        super().__init__(coordinator, entry)
        self._node_id = node.node_id
        self._attr_name = display_name
        self._attr_unique_id = f"{entry.entry_id}_{node.node_id}"
        self._attr_device_class = _device_class_for(node.type_string)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, node.node_id)},
            name=display_name,
            manufacturer=MANUFACTURER,
            model=node.type_string or "Unknown",
            via_device=(DOMAIN, entry.entry_id),
        )

    @property
    def _node(self) -> Node | None:
        return self.coordinator.nodes.get(self._node_id)

    @property
    def _capability(self) -> Capability:
        node = self._node
        return node.capability if node else Capability.UNKNOWN

    @property
    def available(self) -> bool:
        return super().available and self._node is not None

    @property
    def current_cover_position(self) -> int | None:
        """None means genuinely unknown -- either a non-positional motor, or a
        positional one that replied `false`. It is never faked as 0."""
        node = self._node
        if node is None or node.position is None:
            return None
        return gateway_to_ha_position(node.position)

    @property
    def is_closed(self) -> bool | None:
        position = self.current_cover_position
        if position is None:
            return None
        return position <= CLOSED_POSITION_THRESHOLD

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        node = self._node
        if node is None:
            return {}
        # Static values only. Anything that changes frequently here would be
        # broadcast to the whole panel fleet on every update.
        return {
            "node_id": node.node_id,
            "motor_type": node.type_string,
            "capability": str(node.capability),
            "groups": node.groups,
        }

    def _follow(self) -> None:
        """Track this motor at the fast interval while it moves."""
        self.coordinator.async_follow_movement([self._node_id])

    async def async_open_cover(self, **kwargs: Any) -> None:
        await self.coordinator.client.async_move_up(self._node_id)
        self._follow()

    async def async_close_cover(self, **kwargs: Any) -> None:
        await self.coordinator.client.async_move_down(self._node_id)
        self._follow()

    async def async_stop_cover(self, **kwargs: Any) -> None:
        await self.coordinator.client.async_move_stop(self._node_id)
        self._follow()

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        if self._capability is not Capability.POSITIONAL:
            # Should be unreachable: SET_POSITION is not advertised for these.
            _LOGGER.warning(
                "Ignoring set_position for %s -- %s does not support position",
                self._node_id,
                self._node.type_string if self._node else "node",
            )
            return
        target = ha_to_gateway_position(int(kwargs[ATTR_POSITION]))
        await self.coordinator.client.async_move_to(self._node_id, target)
        self._follow()


class SomfyGroupCover(_SomfyCoverBase):
    """A motor group, driven by its gateway group address."""

    def __init__(self, coordinator: SomfyCoordinator, entry: ConfigEntry, group: GroupInfo) -> None:
        super().__init__(coordinator, entry)
        self._group_id = group.group_id
        self._attr_name = group.name
        # UNCHANGED, deliberately. The unique_id is what ties an entity to its
        # registry entry, so keeping it means existing installs re-parent onto
        # the new device below rather than losing their entity IDs, history and
        # any references pointing at them.
        self._attr_unique_id = f"{entry.entry_id}_group_{group.group_id}"
        self._attr_device_class = self._group_device_class()
        # One device per group, rather than all 24 hanging off the gateway.
        # A group is the thing people actually operate and assign to a room --
        # hanging them all off one hub device forced every group entity into
        # whatever area the gateway was in.
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"group_{group.group_id}")},
            name=group.name,
            manufacturer=MANUFACTURER,
            model="Motor group",
            via_device=(DOMAIN, entry.entry_id),
        )

    @property
    def _group(self) -> GroupInfo | None:
        return self.coordinator.groups.get(self._group_id)

    def _member_nodes(self) -> list[Node]:
        group = self._group
        if group is None:
            return []
        return [
            node
            for node_id in group.members
            if (node := self.coordinator.nodes.get(node_id)) is not None
        ]

    def _group_device_class(self) -> CoverDeviceClass:
        members = self._member_nodes()
        if members and all(
            _device_class_for(n.type_string) is CoverDeviceClass.CURTAIN for n in members
        ):
            return CoverDeviceClass.CURTAIN
        return CoverDeviceClass.SHADE

    @property
    def _capability(self) -> Capability:
        """A group is only as capable as its least capable member.

        Four groups on the reference bus are entirely Irismo, so they correctly
        end up without a position slider.
        """
        return capability_for_group([node.capability for node in self._member_nodes()])

    @property
    def current_cover_position(self) -> int | None:
        """Average of the members that actually report a position.

        A group has no position of its own, so this is derived. Members that do
        not know their position are excluded rather than counted as zero.

        Capability is deliberately *not* filtered on here. An all-Irismo group
        is non-positional -- it gets no slider -- but its members do report
        open/closed via the web interface, and that is exactly the state the
        group entity should show.
        """
        positions = [
            gateway_to_ha_position(node.position)
            for node in self._member_nodes()
            if node.position is not None
        ]
        if not positions:
            return None
        return round(sum(positions) / len(positions))

    @property
    def is_closed(self) -> bool | None:
        position = self.current_cover_position
        if position is None:
            return None
        return position <= CLOSED_POSITION_THRESHOLD

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        group = self._group
        if group is None:
            return {}
        return {
            "group_id": group.group_id,
            "group_index": group.index,
            "members": group.members,
            "member_count": len(group.members),
        }

    def _follow(self) -> None:
        """Track this group's member motors while they move.

        Only the members of this group, not the whole bus. An all-Irismo group
        contributes nothing, since the coordinator skips non-positional nodes.
        """
        group = self._group
        if group is not None:
            self.coordinator.async_follow_movement(group.members)

    async def async_open_cover(self, **kwargs: Any) -> None:
        await self.coordinator.client.async_move_up(self._group_id, is_group=True)
        self._follow()

    async def async_close_cover(self, **kwargs: Any) -> None:
        await self.coordinator.client.async_move_down(self._group_id, is_group=True)
        self._follow()

    async def async_stop_cover(self, **kwargs: Any) -> None:
        await self.coordinator.client.async_move_stop(self._group_id, is_group=True)
        self._follow()

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        if self._capability is not Capability.POSITIONAL:
            _LOGGER.warning(
                "Ignoring set_position for group %s -- it contains non-positional motors",
                self._group_id,
            )
            return
        target = ha_to_gateway_position(int(kwargs[ATTR_POSITION]))
        await self.coordinator.client.async_move_to(self._group_id, target, is_group=True)
        self._follow()
