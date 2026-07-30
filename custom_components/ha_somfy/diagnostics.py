"""Diagnostics dump.

Makes a future bug report cheap: one download shows every node, its reported
type, the capability derived from it, and its group membership -- which is
almost always enough to explain a misbehaving blind without a live session.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import CONF_WEB_PASSWORD, DOMAIN, GATEWAY_POSITION_IS_INVERTED
from .coordinator import SomfyCoordinator

# The web password can live in either data or options, so both are redacted.
# Options were previously dumped verbatim, which was safe only for as long as
# nothing secret was kept there.
TO_REDACT = {CONF_PASSWORD, CONF_USERNAME, CONF_WEB_PASSWORD}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    coordinator: SomfyCoordinator = hass.data[DOMAIN][entry.entry_id]

    type_histogram: dict[str, int] = {}
    for node in coordinator.nodes.values():
        key = node.type_string or "<none>"
        type_histogram[key] = type_histogram.get(key, 0) + 1

    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
        "gateway": {
            "connected": coordinator.client.connected,
            "position_polarity_inverted": GATEWAY_POSITION_IS_INVERTED,
        },
        "summary": {
            "node_count": len(coordinator.nodes),
            "group_count": len(coordinator.groups),
            "type_histogram": type_histogram,
        },
        "nodes": [
            {
                "node_id": node.node_id,
                "name": node.name,
                "type": node.type_string,
                "capability": str(node.capability),
                "position": node.position,
                "groups": node.groups,
                "missed_discoveries": node.missed_discoveries,
            }
            for node in coordinator.nodes.values()
        ],
        "groups": [
            {
                "group_id": group.group_id,
                "index": group.index,
                "name": group.name,
                "members": group.members,
            }
            for group in coordinator.groups.values()
        ],
    }
