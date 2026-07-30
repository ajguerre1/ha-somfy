"""The gateway's web interface, for what telnet will not answer.

Telnet refuses `sdn.status.position` for every SDN Module node -- all nine
Irismo motors on the reference bus. The gateway *does* hold their open/closed
state, but serves it only from `somfy_device.json`. That endpoint has three
awkward properties, and containing them here is this module's whole purpose:

1. **It needs a session.** `GET /password.cgi?VERIFY=<web password>`, a separate
   credential from telnet, bound to the client IP and expiring on its own
   schedule. The login can also drop the connection *while still succeeding*,
   so its response is not evidence of anything -- only a subsequent successful
   read is.
2. **It answers with the wrong node.** A request for one node sometimes returns
   another node's payload, or 404. The payload carries its own `NODE` field, so
   this is detectable, and detecting it is not optional: attributing one
   blind's state to another is worse than reporting nothing.
3. **Its position is a display string**, `"1000 (100 %)"`, whose leading number
   is on a different scale per motor family. See `parse_web_position`.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from yarl import URL

from .const import WEB_MAX_ATTEMPTS, WEB_RETRY_DELAY, WEB_TIMEOUT
from .uai.models import dotted_node_id, parse_web_position, undotted_node_id

_LOGGER = logging.getLogger(__name__)


class SomfyWebClient:
    """Reads per-node detail from the gateway's HTTP interface."""

    def __init__(self, hass: HomeAssistant, host: str, password: str | None) -> None:
        self._hass = hass
        self._host = host
        self._password = (password or "").strip()
        self._login_lock = asyncio.Lock()
        self._logged_in = False

    @property
    def configured(self) -> bool:
        """False when no web password was supplied, which disables the feature."""
        return bool(self._password)

    async def async_login(self) -> None:
        """Establish the pilot.htm session.

        Deliberately returns nothing and raises nothing. The gateway answers
        this request inconsistently -- 200 normally, but an abrupt disconnect
        when called in quick succession, *with the session established anyway*.
        Treating a transport error as failure would then wrongly disable the
        feature. Whether it worked is decided by the next read, not here.

        The password is sent unencoded. Percent-encoding it is rejected with
        403; this was measured, not assumed.
        """
        if not self._password:
            return
        session = async_get_clientsession(self._hass)
        url = URL(f"http://{self._host}/password.cgi?VERIFY={self._password}", encoded=True)
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=WEB_TIMEOUT)):
                pass
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.debug("Web login request did not complete cleanly: %s", err)
        self._logged_in = True

    async def _async_fetch_device(self, node_id: str) -> dict[str, Any] | None:
        """One read. Returns the payload only if it is for the node requested."""
        session = async_get_clientsession(self._hass)
        url = f"http://{self._host}/somfy_device.json?{dotted_node_id(node_id)}"
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=WEB_TIMEOUT)
            ) as response:
                if response.status == 403:
                    self._logged_in = False
                    return None
                if response.status != 200:
                    return None
                payload = await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            _LOGGER.debug("Web read failed for %s: %s", node_id, err)
            return None

        device = payload.get("DEVICE") if isinstance(payload, dict) else None
        if not isinstance(device, dict):
            return None

        returned = undotted_node_id(str(device.get("NODE", "")))
        if returned != node_id.upper():
            # The gateway served a different node. Silently accepting this
            # would put one blind's state on another blind's entity.
            _LOGGER.debug("Web read for %s answered with %s; discarding", node_id, returned)
            return None
        return device

    async def async_get_device(self, node_id: str) -> dict[str, Any] | None:
        """Read one node, logging in and retrying as needed."""
        if not self._password:
            return None

        for attempt in range(WEB_MAX_ATTEMPTS):
            if not self._logged_in:
                async with self._login_lock:
                    if not self._logged_in:
                        await self.async_login()
            device = await self._async_fetch_device(node_id)
            if device is not None:
                return device
            if attempt < WEB_MAX_ATTEMPTS - 1:
                await asyncio.sleep(WEB_RETRY_DELAY)
        return None

    async def async_get_position(self, node_id: str) -> int | None:
        """The open/closed state of a node telnet will not report.

        Returns a 0-100 gateway-scale value, or None when it could not be read.
        None must stay None: a blind whose state is unknown has to look unknown.
        """
        device = await self.async_get_device(node_id)
        if device is None:
            return None
        return parse_web_position(device.get("POSITION"))

    async def async_get_labels(self, node_ids: list[str]) -> dict[str, str]:
        """Authoritative motor labels, where the gateway will serve them.

        Discovery-time only, and entirely optional -- any node this misses keeps
        the name telnet gave it.
        """
        labels: dict[str, str] = {}
        for node_id in node_ids:
            device = await self.async_get_device(node_id)
            label = device.get("LABEL") if device else None
            if isinstance(label, str) and label.strip():
                labels[node_id] = label.strip()
        _LOGGER.debug("Read %d/%d motor labels over HTTP", len(labels), len(node_ids))
        return labels
