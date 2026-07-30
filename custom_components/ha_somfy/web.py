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
   blind's state to another is worse than reporting nothing. Note that a *stale
   session* produces the same symptom rather than a clean 403, so a wrong-node
   reply is ambiguous between "buffer lagging" and "not logged in".
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

from .const import (
    WEB_FAILURES_BEFORE_WARNING,
    WEB_MAX_ATTEMPTS,
    WEB_RELOGIN_AFTER,
    WEB_RETRY_DELAY,
    WEB_TIMEOUT,
)
from .uai.models import dotted_node_id, parse_web_position, undotted_node_id

_LOGGER = logging.getLogger(__name__)


class SomfyWebClient:
    """Reads per-node detail from the gateway's HTTP interface."""

    def __init__(self, hass: HomeAssistant, host: str, password: str | None) -> None:
        self._hass = hass
        self._host = host
        self._password = (password or "").strip()
        self._login_lock = asyncio.Lock()
        self._read_lock = asyncio.Lock()
        self._logged_in = False
        # Every failure below is individually unremarkable and logged at debug.
        # Collectively they mean the feature is dead, and the first time this
        # shipped it died in exactly that way -- silently, with on-disk logging
        # off, leaving nothing to look at. These two counters exist so that
        # "configured but never working" says so out loud, once.
        self._reads = 0
        self._failures = 0
        self._warned = False
        self._succeeded = False
        self._last_error: str | None = None
        self._last_login: str | None = None

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
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=WEB_TIMEOUT)
            ) as response:
                self._last_login = f"HTTP {response.status}"
        except (aiohttp.ClientError, TimeoutError) as err:
            # Expected: the gateway often drops this connection while still
            # having accepted the credential. Recorded rather than acted on.
            self._last_login = type(err).__name__
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
                    self._last_error = "HTTP 403 (no session)"
                    self._logged_in = False
                    return None
                if response.status != 200:
                    self._last_error = f"HTTP {response.status}"
                    return None
                payload = await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            self._last_error = f"{type(err).__name__}: {err}"
            _LOGGER.debug("Web read failed for %s: %s", node_id, err)
            return None

        device = payload.get("DEVICE") if isinstance(payload, dict) else None
        if not isinstance(device, dict):
            self._last_error = "no DEVICE object in the reply"
            return None

        returned = undotted_node_id(str(device.get("NODE", "")))
        if returned != node_id.upper():
            # The gateway served a different node. Silently accepting this
            # would put one blind's state on another blind's entity.
            self._last_error = f"asked for {node_id}, answered with {returned}"
            _LOGGER.debug("Web read for %s answered with %s; discarding", node_id, returned)
            return None
        return device

    async def async_get_device(self, node_id: str) -> dict[str, Any] | None:
        """Read one node, logging in and retrying as needed.

        Reads are serialised. The gateway holds a single "current device"
        buffer, so two overlapping reads retarget it under each other and
        neither converges -- the failure looks like a flaky endpoint but is
        self-inflicted.
        """
        if not self._password:
            return None

        async with self._read_lock:
            device = await self._async_read_with_retries(node_id)

        self._reads += 1
        if device is None:
            self._failures += 1
        else:
            self._succeeded = True
        self._maybe_warn()
        return device

    async def _async_read_with_retries(self, node_id: str) -> dict[str, Any] | None:
        """Retry a read, re-authenticating if it keeps being rejected.

        A stale session does **not** reliably answer 403. It can answer HTTP
        200 carrying a different node's payload, which is indistinguishable
        from the buffer lag this endpoint also has. Re-authenticating only on
        403 therefore deadlocks: the guard rejects every reply, nothing ever
        looks like an auth failure, and the client retries a dead session
        forever. That is precisely how this failed on the reference system.

        So after a couple of rejected reads, stop blaming the buffer and
        assume the session.
        """
        for attempt in range(WEB_MAX_ATTEMPTS):
            if not self._logged_in:
                async with self._login_lock:
                    if not self._logged_in:
                        await self.async_login()

            device = await self._async_fetch_device(node_id)
            if device is not None:
                return device

            if attempt + 1 >= WEB_RELOGIN_AFTER:
                self._logged_in = False
            if attempt < WEB_MAX_ATTEMPTS - 1:
                await asyncio.sleep(WEB_RETRY_DELAY)

        # Give the next read a fresh session rather than inheriting this one.
        self._logged_in = False
        return None

    def _maybe_warn(self) -> None:
        """Say once, out loud, that a configured feature is not working.

        This shipped without it and failed exactly this way: silently, with
        on-disk logging off, leaving no way to tell a wrong password from an
        unreachable endpoint. The reason is included because "it didn't work"
        is not a diagnosis.
        """
        if self._warned or self._succeeded or self._reads < WEB_FAILURES_BEFORE_WARNING:
            return
        if self._failures < self._reads:
            return
        self._warned = True
        _LOGGER.warning(
            "A web interface password is configured for %s, but all %d reads of motor "
            "state have failed, so motors without telnet position feedback (Irismo behind "
            "an SDN bridge) will stay unknown. Last login attempt: %s. Last read failure: "
            "%s. If that says HTTP 403, the password does not match the one the gateway's "
            "own web page asks for -- it is a separate credential from the telnet one.",
            self._host,
            self._reads,
            self._last_login or "never attempted",
            self._last_error or "none recorded",
        )

    @property
    def health(self) -> dict[str, Any]:
        """Whether this source is working, for the diagnostics dump."""
        return {
            "configured": self.configured,
            "reads": self._reads,
            "failures": self._failures,
            "ever_succeeded": self._succeeded,
            "last_login": self._last_login,
            "last_error": self._last_error,
        }

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
