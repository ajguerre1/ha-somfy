"""HA Somfy -- Home Assistant integration for the Somfy Connect UAI+ gateway.

Existing integrations for this gateway assume every motor reports its position.
Irismo motors reach the SDN bus through a Somfy 1811129 bridge that supports
only open, close, stop and groups, so that assumption leaves them with a dead
position slider. This integration derives each entity's features from what its
hardware actually reports.
"""

from __future__ import annotations

import asyncio
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
    CONF_WEB_PASSWORD,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    GATEWAY_MODEL,
    MANUFACTURER,
)
from .coordinator import SomfyCoordinator
from .uai.client import DEFAULT_PORT, UaiAuthError, UaiClient, UaiError
from .web import SomfyWebClient

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.COVER]

GROUP_NAMES_TIMEOUT = 10
GROUP_NAMES_ATTEMPTS = 3
GROUP_NAMES_RETRY_DELAY = 1.0


async def async_fetch_group_names(hass: HomeAssistant, host: str) -> dict[int, str]:
    """Read friendly group names from the gateway's web interface.

    Group names are not available over telnet -- `sdn.group.get` returns only
    IDs. The gateway's HTTP interface serves them unauthenticated, so this is a
    cheap way to get "RoomB SH" instead of "Group 5". Failure is non-fatal:
    groups simply fall back to numbered names.
    """
    url = f"http://{host}/somfy_groups.json"
    session = async_get_clientsession(hass)
    payload: object = None

    # Retried, because losing this one request costs all 25 group names and
    # every group falls back to "Group 18". That happened on a busy Home
    # Assistant startup, where the gateway's small HTTP server was slow enough
    # for a single attempt to time out.
    for attempt in range(GROUP_NAMES_ATTEMPTS):
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=GROUP_NAMES_TIMEOUT)
            ) as response:
                if response.status != 200:
                    _LOGGER.debug("Group names unavailable (HTTP %s)", response.status)
                else:
                    # The gateway does not send a JSON content type.
                    payload = await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            _LOGGER.debug("Could not read group names from %s: %s", url, err)
        if payload is not None:
            break
        if attempt < GROUP_NAMES_ATTEMPTS - 1:
            await asyncio.sleep(GROUP_NAMES_RETRY_DELAY)

    if payload is None:
        _LOGGER.warning(
            "Could not read group names from %s after %d attempts; groups will be "
            "named by number until the next reload.",
            url,
            GROUP_NAMES_ATTEMPTS,
        )
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


async def async_fetch_gateway_info(hass: HomeAssistant, host: str) -> dict[str, str]:
    """Read firmware version and serial from the gateway's about endpoint.

    Purely cosmetic -- it populates the device page. Unauthenticated, and any
    failure just leaves those fields blank.
    """
    try:
        session = async_get_clientsession(hass)
        async with session.get(
            f"http://{host}/about.json", timeout=aiohttp.ClientTimeout(total=GROUP_NAMES_TIMEOUT)
        ) as response:
            if response.status != 200:
                return {}
            payload = await response.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, ValueError) as err:
        _LOGGER.debug("Could not read gateway info: %s", err)
        return {}

    if not isinstance(payload, dict):
        return {}
    return {
        key: str(payload[key]).strip()
        for key in ("VERSION_FW", "SERIAL_NO")
        if isinstance(payload.get(key), str) and payload[key].strip()
    }


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
    # The web password may be set at install time or added later from the
    # options flow, so an existing entry can gain the feature without being
    # removed and re-added.
    web_password = entry.options.get(CONF_WEB_PASSWORD) or entry.data.get(CONF_WEB_PASSWORD)
    web = SomfyWebClient(hass, host, web_password)
    coordinator = SomfyCoordinator(hass, entry, client, poll_interval, web=web)

    try:
        group_names = await async_fetch_group_names(hass, host)
        await client.async_ping_all()
        # Names come from telnet alone. Reading all 49 labels over HTTP made
        # setup the slowest integration on the system -- Home Assistant warned
        # four times that it was still waiting, and entities took ~5 minutes to
        # appear -- because that endpoint serves one node per request from a
        # slow embedded server, with retries. It bought nothing: the double
        # telnet read already names all 49 nodes correctly, and did so
        # throughout the period when this HTTP path was silently failing.
        await coordinator.async_discover(group_names)
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
    gateway_info = await async_fetch_gateway_info(hass, host)
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name="Somfy UAI+",
        manufacturer=MANUFACTURER,
        model=GATEWAY_MODEL,
        sw_version=gateway_info.get("VERSION_FW"),
        serial_number=gateway_info.get("SERIAL_NO"),
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
