"""Async client for the Somfy Connect UAI+ telnet interface.

Pure asyncio -- no Home Assistant imports, so this is testable on any platform
(which matters, because Home Assistant itself cannot be imported on Windows).

Design notes:

* A single background reader task owns the socket and dispatches replies to
  per-request futures keyed by message id. That is what lets several requests
  be in flight at once without their answers getting crossed.
* Requests transparently reconnect once if the link has dropped. The gateway
  closes idle connections, and a coordinator poll should not fail for that.
* Capability is *measured* for unrecognised hardware rather than assumed. See
  models.classify_type for why assuming is the bug this integration exists to
  fix.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
from typing import Any, Final

from .models import (
    ALL_GROUP_ID,
    Capability,
    Node,
    classify_type,
    parse_position,
)
from .protocol import (
    MAX_REQUEST_ID,
    METHOD_GROUP_GET,
    METHOD_MOVE_DOWN,
    METHOD_MOVE_STOP,
    METHOD_MOVE_TO,
    METHOD_MOVE_UP,
    METHOD_STATUS_INFO,
    METHOD_STATUS_PING,
    METHOD_STATUS_POSITION,
    MIN_REQUEST_ID,
    PROMPT_CONNECTED,
    PROMPT_PASSWORD,
    PROMPT_USER,
    TARGET_ALL,
    Response,
    encode_request,
    parse_response,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_PORT: Final = 23
DEFAULT_TIMEOUT: Final = 10.0
DISCOVERY_TIMEOUT: Final = 45.0
_RECONNECT_BACKOFF: Final = (0.5, 1.0, 2.0, 5.0)


class UaiError(Exception):
    """Base error for all gateway problems."""


class UaiConnectionError(UaiError):
    """The gateway could not be reached, or the link dropped."""


class UaiAuthError(UaiError):
    """The gateway rejected the credentials."""


class UaiTimeoutError(UaiError):
    """The gateway did not answer in time."""


class UaiClient:
    """Talks to one UAI+ gateway."""

    def __init__(
        self,
        host: str,
        port: int = DEFAULT_PORT,
        username: str = "",
        password: str = "",
        *,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.host = host
        self.port = port
        self._username = username
        self._password = password
        self._timeout = timeout

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._reader_task: asyncio.Task | None = None
        self._pending: dict[int, asyncio.Future[Response]] = {}
        # Started at an unpredictable high point rather than a fixed base:
        # the gateway broadcasts replies to every open telnet session, and a
        # reply carries only an id. See MIN_REQUEST_ID.
        self._msg_id = random.randrange(MIN_REQUEST_ID, MAX_REQUEST_ID)
        self._connect_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()

    # -- lifecycle ---------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def async_connect(self) -> None:
        async with self._connect_lock:
            if self.connected:
                return
            await self._open()

    async def _open(self) -> None:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port), timeout=self._timeout
            )
        except (TimeoutError, OSError) as exc:
            raise UaiConnectionError(f"cannot reach {self.host}:{self.port}: {exc}") from exc

        self._reader, self._writer = reader, writer
        try:
            await self._authenticate()
        except UaiError:
            await self._teardown()
            raise

        self._reader_task = asyncio.create_task(self._read_loop())

    async def _authenticate(self) -> None:
        """Complete the login prompts.

        The prompts are not newline-terminated, so this reads until a substring
        appears rather than until a line ending.
        """
        try:
            await self._read_until(PROMPT_USER)
            await self._write_line(self._username)
            await self._read_until(PROMPT_PASSWORD)
            await self._write_line(self._password)
            await self._read_until(PROMPT_CONNECTED)
        except TimeoutError as exc:
            raise UaiAuthError("gateway did not complete the login handshake") from exc
        except (ConnectionError, OSError) as exc:
            # The gateway hangs up on bad credentials rather than saying so.
            raise UaiAuthError("gateway closed the connection during login") from exc

    async def _read_until(self, needle: str) -> str:
        assert self._reader is not None
        buffer = ""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._timeout
        while needle not in buffer:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError(f"timed out waiting for {needle!r}")
            chunk = await asyncio.wait_for(self._reader.read(4096), timeout=remaining)
            if not chunk:
                raise ConnectionError(f"connection closed waiting for {needle!r}")
            buffer += chunk.decode("ascii", errors="replace")
        return buffer

    async def _write_line(self, text: str) -> None:
        if self._writer is None:
            raise UaiConnectionError("not connected")
        self._writer.write((text + "\r\n").encode("ascii"))
        await self._writer.drain()

    async def _read_loop(self) -> None:
        """Own the socket and hand each reply to whoever is waiting for it."""
        assert self._reader is not None
        try:
            while True:
                line = await self._reader.readline()
                if not line:
                    break
                response = parse_response(line.decode("ascii", errors="replace"))
                if response is None or response.id is None:
                    # Heartbeat echoes and other chatter. Not an error.
                    continue
                future = self._pending.pop(response.id, None)
                if future is not None and not future.done():
                    future.set_result(response)
        except (ConnectionError, OSError, asyncio.CancelledError):
            pass
        finally:
            self._fail_pending(UaiConnectionError("connection closed by gateway"))

    def _fail_pending(self, error: Exception) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(error)
        self._pending.clear()

    async def _teardown(self) -> None:
        if self._reader_task is not None:
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader_task
            self._reader_task = None
        if self._writer is not None:
            self._writer.close()
            with contextlib.suppress(Exception):
                await self._writer.wait_closed()
        self._reader = self._writer = None
        self._fail_pending(UaiConnectionError("disconnected"))

    async def async_disconnect(self) -> None:
        await self._teardown()

    # -- requests ----------------------------------------------------------

    def _next_id(self) -> int:
        self._msg_id += 1
        return self._msg_id

    async def async_request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
        _retrying: bool = False,
    ) -> Response:
        """Send one request and wait for its reply, reconnecting once if needed."""
        if not self.connected:
            await self.async_connect()

        msg_id = self._next_id()
        future: asyncio.Future[Response] = asyncio.get_running_loop().create_future()
        self._pending[msg_id] = future

        try:
            async with self._write_lock:
                await self._write_line(encode_request(method, params or {}, msg_id))
            return await asyncio.wait_for(future, timeout=timeout or self._timeout)
        except TimeoutError as exc:
            self._pending.pop(msg_id, None)
            raise UaiTimeoutError(f"no reply to {method} within timeout") from exc
        except (UaiConnectionError, ConnectionError, OSError) as exc:
            self._pending.pop(msg_id, None)
            if _retrying:
                raise UaiConnectionError(f"{method} failed: {exc}") from exc
            # The gateway closes idle links; one transparent retry keeps a
            # routine poll from failing for a reason the user cannot act on.
            _LOGGER.debug("Reconnecting after dropped link during %s", method)
            await self._teardown()
            return await self.async_request(method, params, timeout=timeout, _retrying=True)

    # -- read-only operations ---------------------------------------------

    async def async_ping_all(self) -> list[str]:
        """Enumerate every node on the bus.

        Nodes occasionally miss a pass, so callers should treat successive
        results as a union over time rather than an authoritative snapshot.
        """
        response = await self.async_request(
            METHOD_STATUS_PING, {"targetID": TARGET_ALL}, timeout=DISCOVERY_TIMEOUT
        )
        if response.is_error or not isinstance(response.result, list):
            return []
        return [str(node) for node in response.result]

    async def async_get_info(self, node_id: str) -> tuple[str | None, str | None] | None:
        """Return (name, type) for a node."""
        response = await self.async_request(METHOD_STATUS_INFO, {"targetID": node_id})
        if response.is_error or not isinstance(response.result, dict):
            return None
        return response.result.get("name"), response.result.get("type")

    async def async_get_position(self, node_id: str) -> int | None:
        """Return 0-100, or None when the gateway did not give a usable value.

        None covers both "this node has no position feature" and "it does, but
        does not know it right now". Use async_position_supported to tell those
        apart -- the difference decides the entity's feature set.
        """
        try:
            response = await self.async_request(METHOD_STATUS_POSITION, {"targetID": node_id})
        except (UaiTimeoutError, UaiConnectionError):
            return None
        if response.is_error:
            return None
        return parse_position(response.result)

    async def async_position_supported(self, node_id: str) -> bool:
        """Does this node implement position at all?

        An error reply means no. Any successful reply means yes -- including
        `false`, which is a position-capable motor reporting that it currently
        does not know where it is.
        """
        try:
            response = await self.async_request(METHOD_STATUS_POSITION, {"targetID": node_id})
        except (UaiTimeoutError, UaiConnectionError):
            return False
        return response.has_result and not response.is_error

    async def async_get_groups(self, node_id: str) -> list[str]:
        """Group IDs this node belongs to, excluding the ALL broadcast group."""
        try:
            response = await self.async_request(METHOD_GROUP_GET, {"targetID": node_id})
        except (UaiTimeoutError, UaiConnectionError):
            return []
        if response.is_error or not isinstance(response.result, list):
            return []
        return [str(gid) for gid in response.result if str(gid).upper() != ALL_GROUP_ID.upper()]

    async def async_get_info_settled(self, node_id: str) -> tuple[str | None, str | None] | None:
        """Read a node's info twice and return the second answer.

        The gateway answers the *first* `sdn.status.info` for a node with a
        placeholder name derived from its group membership -- literally the
        group's name plus the node's position in it -- when it has not yet read
        the device's own label. The query itself triggers that read, so a second
        call returns the true label.

        Observed across all 7 SDN Module (Irismo) nodes on the reference bus:
        first read gave "RoomI SH 1" and "RoomD SH", second gave
        "RoomI SH 1" and "RoomD Hall SH", matching the gateway's web UI.

        This matters only at discovery, but it matters permanently: entity IDs
        are derived from the name and are assigned once.
        """
        first = await self.async_get_info(node_id)
        second = await self.async_get_info(node_id)
        return second if second is not None else first

    async def async_discover_nodes(
        self, name_overrides: dict[str, str] | None = None
    ) -> list[Node]:
        """Enumerate the bus and work out what each node can do.

        `name_overrides` maps node ID to an authoritative label -- in practice
        the gateway's own HTTP label, which was correct on every node it served
        even when telnet was not. Nodes it does not cover fall back to the
        settled telnet name.
        """
        overrides = name_overrides or {}
        nodes: list[Node] = []
        for node_id in await self.async_ping_all():
            info = await self.async_get_info_settled(node_id)
            name, type_string = info if info else (None, None)
            name = overrides.get(node_id) or name

            capability = classify_type(type_string)
            if capability is Capability.UNKNOWN:
                # Unrecognised hardware: measure rather than guess.
                supported = await self.async_position_supported(node_id)
                capability = Capability.POSITIONAL if supported else Capability.NON_POSITIONAL

            position: int | None = None
            if capability is Capability.POSITIONAL:
                position = await self.async_get_position(node_id)

            nodes.append(
                Node(
                    node_id=node_id,
                    name=name,
                    type_string=type_string,
                    capability=capability,
                    position=position,
                    groups=await self.async_get_groups(node_id),
                )
            )
        return nodes

    # -- movement ----------------------------------------------------------
    #
    # These physically move blinds. Everything above is read-only.

    @staticmethod
    def _target(target_id: str, is_group: bool) -> dict[str, str]:
        return {"groupID" if is_group else "targetID": target_id}

    async def async_move_up(self, target_id: str, *, is_group: bool = False) -> bool:
        response = await self.async_request(METHOD_MOVE_UP, self._target(target_id, is_group))
        return not response.is_error

    async def async_move_down(self, target_id: str, *, is_group: bool = False) -> bool:
        response = await self.async_request(METHOD_MOVE_DOWN, self._target(target_id, is_group))
        return not response.is_error

    async def async_move_stop(self, target_id: str, *, is_group: bool = False) -> bool:
        response = await self.async_request(METHOD_MOVE_STOP, self._target(target_id, is_group))
        return not response.is_error

    async def async_move_to(self, target_id: str, position: int, *, is_group: bool = False) -> bool:
        """Move to a gateway-scale position (0-100).

        Callers are responsible for polarity: the gateway's scale is not
        necessarily Home Assistant's. See PROTO-08.
        """
        params = self._target(target_id, is_group)
        params["position"] = max(0, min(100, int(position)))
        response = await self.async_request(METHOD_MOVE_TO, params)
        return not response.is_error
