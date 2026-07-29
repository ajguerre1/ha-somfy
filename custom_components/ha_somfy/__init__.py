"""HA Somfy -- Home Assistant integration for the Somfy Connect UAI+ gateway.

Existing integrations for this gateway assume every motor reports its position.
Irismo motors reach the SDN bus through a Somfy 1811129 bridge that supports
only open, close, stop and groups, so that assumption leaves them with a dead
position slider. This integration derives each entity's features from what its
hardware actually reports.
"""

from __future__ import annotations

import logging

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    GATEWAY_MODEL,
    MANUFACTURER,
)
from .coordinator import SomfyCoordinator
from .uai.client import DEFAULT_PORT, UaiAuthError, UaiClient, UaiError

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.COVER]

GROUP_NAMES_TIMEOUT = 10
DEVICE_LABEL_TIMEOUT = 10


async def async_fetch_group_names(hass: HomeAssistant, host: str) -> dict[int, str]:
    """Read friendly group names from the gateway's web interface.

    Group names are not available over telnet -- `sdn.group.get` returns only
    IDs. The gateway's HTTP interface serves them unauthenticated, so this is a
    cheap way to get "RoomB SH" instead of "Group 5". Failure is non-fatal:
    groups simply fall back to numbered names.
    """
    url = f"http://{host}/somfy_groups.json"
    try:
        session = async_get_clientsession(hass)
        async with session.get(
            url, timeout=aiohttp.ClientTimeout(total=GROUP_NAMES_TIMEOUT)
        ) as response:
            if response.status != 200:
                _LOGGER.debug("Group names unavailable (HTTP %s)", response.status)
                return {}
            # The gateway does not send a JSON content type.
            payload = await response.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, ValueError) as err:
        _LOGGER.debug("Could not read group names from %s: %s", url, err)
        return {}

    groups = payload.get("GROUPS") if isinstance(payload, dict) else None
    if not isinstance(groups, dict):
        return {}

    names: dict[int, str] = {}
    for key, value in groups.items():
        try:
            names[int(key)] = str(value).strip()
        except (TypeError, ValueError):
            continue
    return names


def _dotted(node_id: str) -> str:
    """136E33 -> 13.6E.33, the node form the HTTP endpoint expects."""
    return ".".join(node_id[index : index + 2] for index in range(0, len(node_id), 2))


async def async_fetch_device_labels(
    hass: HomeAssistant, host: str, node_ids: list[str]
) -> dict[str, str]:
    """Read authoritative motor labels from the gateway's web interface.

    Telnet's first `sdn.status.info` for a node can return a placeholder derived
    from its group, whereas this endpoint returned the true label for every node
    it served. It does not cover every node, so callers must keep a fallback.

    Discovery-time only, and entirely optional: any failure just means that node
    keeps its telnet name.
    """
    session = async_get_clientsession(hass)
    labels: dict[str, str] = {}

    for node_id in node_ids:
        url = f"http://{host}/somfy_device.json?{_dotted(node_id)}"
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=DEVICE_LABEL_TIMEOUT)
            ) as response:
                if response.status != 200:
                    continue
                payload = await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            _LOGGER.debug("No HTTP label for %s: %s", node_id, err)
            continue

        device = payload.get("DEVICE") if isinstance(payload, dict) else None
        label = device.get("LABEL") if isinstance(device, dict) else None
        if isinstance(label, str) and label.strip():
            labels[node_id] = label.strip()

    _LOGGER.debug("Read %d/%d motor labels over HTTP", len(labels), len(node_ids))
    return labels


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Connect to the gateway, discover the bus, and set up entities."""
    host = entry.data[CONF_HOST]
    client = UaiClient(
        host,
        entry.data.get(CONF_PORT, DEFAULT_PORT),
        entry.data.get(CONF_USERNAME, ""),
        entry.data.get(CONF_PASSWORD, ""),
    )

    try:
        await client.async_connect()
    except UaiAuthError as err:
        raise ConfigEntryAuthFailed(f"Gateway rejected credentials: {err}") from err
    except UaiError as err:
        raise ConfigEntryNotReady(f"Cannot reach gateway at {host}: {err}") from err

    poll_interval = entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
    coordinator = SomfyCoordinator(hass, entry, client, poll_interval)

    try:
        group_names = await async_fetch_group_names(hass, host)
        node_ids = await client.async_ping_all()
        labels = await async_fetch_device_labels(hass, host, node_ids)
        await coordinator.async_discover(group_names, name_overrides=labels)
    except UaiError as err:
        await client.async_disconnect()
        raise ConfigEntryNotReady(f"Discovery failed: {err}") from err

    if not coordinator.nodes:
        await client.async_disconnect()
        raise ConfigEntryNotReady("Gateway returned no motors")

    _LOGGER.info(
        "Discovered %d motor(s) and %d group(s) on %s",
        len(coordinator.nodes),
        len(coordinator.groups),
        host,
    )

    await coordinator.async_config_entry_first_refresh()

    # Register the gateway explicitly, before any entity is added.
    #
    # Each motor device declares `via_device` pointing here. If the gateway is
    # only created implicitly by the group entities' device_info, the motors are
    # added first and reference a parent that does not exist yet -- which Home
    # Assistant currently warns about and will eventually reject.
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name="Somfy UAI+",
        manufacturer=MANUFACTURER,
        model=GATEWAY_MODEL,
        configuration_url=f"http://{host}/",
    )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Tear down the entry and close the gateway connection."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        coordinator: SomfyCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.client.async_disconnect()
    return unloaded


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
