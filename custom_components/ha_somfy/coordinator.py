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

import asyncio
import logging
from collections.abc import Iterable
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    MAX_MISSED_DISCOVERIES,
    MOVING_POLL_INTERVAL,
    MOVING_POLL_MAX_SECONDS,
    MOVING_SETTLE_READS,
)
from .uai.client import UaiClient, UaiError
from .uai.models import (
    Capability,
    GroupInfo,
    Node,
    find_name_group_conflicts,
    group_index_for_id,
)

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
        # Nodes currently being followed at the fast interval, and the single
        # task doing the following. Kept as a set so overlapping movements
        # merge instead of cancelling each other.
        self._moving: set[str] = set()
        self._follow_task: asyncio.Task | None = None

    async def async_discover(
        self,
        group_names: dict[int, str] | None = None,
        name_overrides: dict[str, str] | None = None,
    ) -> None:
        """Enumerate the bus and build the node and group topology.

        Discovery is treated as a union over time rather than a snapshot: nodes
        occasionally miss a pass, and dropping an entity because of one missed
        reply would make blinds flicker to unavailable for no reason.

        `name_overrides` carries authoritative labels read over HTTP; see
        `UaiClient.async_get_info_settled` for why telnet alone is not enough.
        """
        try:
            discovered = await self.client.async_discover_nodes(name_overrides)
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
        self._warn_on_name_group_conflicts()

    def _warn_on_name_group_conflicts(self) -> None:
        """Flag any node whose name points at a group it is not a member of.

        This mismatch is the only thing that would have caught a stale name the
        gateway once reported, and it was sitting unexamined in the captured
        data at the time. Cheap to check now that both fields are already here.
        """
        for conflict in find_name_group_conflicts(list(self.nodes.values()), self.groups):
            _LOGGER.warning(
                "Node %s is named %r but belongs to group %r, not %r. "
                "Check its label in the UAI+ web interface -- its Home Assistant "
                "name may be wrong.",
                conflict.node_id,
                conflict.name,
                conflict.own_group,
                conflict.suggested_group,
            )

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

    # -- following a moving motor -----------------------------------------

    @callback
    def async_follow_movement(self, node_ids: Iterable[str]) -> None:
        """Poll the given nodes at the fast interval until they settle.

        Called right after a movement command. Deliberately narrow: only the
        nodes just commanded are followed, so a moving blind updates promptly
        without the other 40-odd motors generating any extra traffic.

        Non-positional nodes are skipped entirely -- an Irismo has no position
        to read, so following it would be pure noise.
        """
        targets = {
            node_id
            for node_id in node_ids
            if (node := self.nodes.get(node_id)) is not None
            and node.capability is Capability.POSITIONAL
        }
        if not targets:
            return

        self._moving |= targets
        if self._follow_task is None or self._follow_task.done():
            self._follow_task = self.config_entry.async_create_background_task(
                self.hass, self._async_follow_movement(), name=f"{DOMAIN}_follow_movement"
            )

    async def _async_follow_movement(self) -> None:
        """Poll moving nodes until each stops changing, or the ceiling is hit."""
        unchanged: dict[str, int] = dict.fromkeys(self._moving, 0)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + MOVING_POLL_MAX_SECONDS

        try:
            while self._moving and loop.time() < deadline:
                await asyncio.sleep(MOVING_POLL_INTERVAL)
                changed = False

                for node_id in list(self._moving):
                    node = self.nodes.get(node_id)
                    if node is None:
                        self._moving.discard(node_id)
                        continue

                    previous = node.position
                    try:
                        node.position = await self.client.async_get_position(node_id)
                    except UaiError as err:
                        _LOGGER.debug("Position poll failed for %s: %s", node_id, err)
                        continue

                    if node.position != previous:
                        changed = True
                        unchanged[node_id] = 0
                        continue

                    unchanged[node_id] = unchanged.get(node_id, 0) + 1
                    if unchanged[node_id] >= MOVING_SETTLE_READS:
                        self._moving.discard(node_id)

                if changed:
                    # Entities are change-gated, so a no-op refresh still
                    # writes nothing and nothing reaches the panels.
                    self.async_update_listeners()
        except asyncio.CancelledError:
            raise
        finally:
            self._moving.clear()
            self.async_update_listeners()

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
