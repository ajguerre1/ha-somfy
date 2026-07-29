"""Polling coordinator.

Two things drive the design here:

1. Only position-capable motors are polled. The 9 Irismo nodes have no position
   to read, so asking would be pure noise on the bus and in the logs.
2. State is written only when a value actually changes. The target system fans
   every state change out to ~48 wall panels, where excess churn has already
   caused a visible problem once. `CoordinatorEntity` writes state on every
   refresh by default, so entities here override that -- see `_handle_coordinator_update`
   in cover.py.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, MAX_MISSED_DISCOVERIES
from .uai.client import UaiClient, UaiError
from .uai.models import Capability, GroupInfo, Node, group_index_for_id

_LOGGER = logging.getLogger(__name__)


class SomfyCoordinator(DataUpdateCoordinator[dict[str, Node]]):
    """Keeps motor state fresh and holds the discovered bus topology."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: UaiClient,
        poll_interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=poll_interval),
            config_entry=entry,
        )
        self.client = client
        self.nodes: dict[str, Node] = {}
        self.groups: dict[str, GroupInfo] = {}

    async def async_discover(self, group_names: dict[int, str] | None = None) -> None:
        """Enumerate the bus and build the node and group topology.

        Discovery is treated as a union over time rather than a snapshot: nodes
        occasionally miss a pass, and dropping an entity because of one missed
        reply would make blinds flicker to unavailable for no reason.
        """
        try:
            discovered = await self.client.async_discover_nodes()
        except UaiError as err:
            raise UpdateFailed(f"discovery failed: {err}") from err

        seen: set[str] = set()
        for node in discovered:
            seen.add(node.node_id)
            existing = self.nodes.get(node.node_id)
            # Preserve a known capability if this pass could not determine one,
            # so an entity's features never flap between refreshes.
            if existing is not None and node.capability is Capability.UNKNOWN:
                node.capability = existing.capability
            node.missed_discoveries = 0
            self.nodes[node.node_id] = node

        for node_id, node in list(self.nodes.items()):
            if node_id in seen:
                continue
            node.missed_discoveries += 1
            if node.missed_discoveries >= MAX_MISSED_DISCOVERIES:
                _LOGGER.warning(
                    "Node %s (%s) missed %d consecutive discovery passes; dropping it",
                    node_id,
                    node.name,
                    node.missed_discoveries,
                )
                del self.nodes[node_id]
            else:
                _LOGGER.debug(
                    "Node %s did not answer discovery (%d/%d) -- keeping it",
                    node_id,
                    node.missed_discoveries,
                    MAX_MISSED_DISCOVERIES,
                )

        self.groups = self._build_groups(group_names or {})

    def _build_groups(self, group_names: dict[int, str]) -> dict[str, GroupInfo]:
        """Derive groups from per-node membership.

        The gateway's group list is only available over HTTP, so names are
        passed in when we have them and fall back to the group ID otherwise.
        """
        members: dict[str, list[str]] = {}
        for node in self.nodes.values():
            for group_id in node.groups:
                members.setdefault(group_id.upper(), []).append(node.node_id)

        groups: dict[str, GroupInfo] = {}
        for group_id, member_ids in members.items():
            index = group_index_for_id(group_id)
            if index is None:
                continue
            groups[group_id] = GroupInfo(
                group_id=group_id,
                index=index,
                name=group_names.get(index) or f"Group {index}",
                members=sorted(member_ids),
            )
        return groups

    async def _async_update_data(self) -> dict[str, Node]:
        """Refresh position for position-capable motors only."""
        for node in self.nodes.values():
            if node.capability is not Capability.POSITIONAL:
                # Irismo has nothing to report; asking would be noise.
                continue
            try:
                node.position = await self.client.async_get_position(node.node_id)
            except UaiError as err:
                _LOGGER.debug("Position poll failed for %s: %s", node.node_id, err)
        return self.nodes
