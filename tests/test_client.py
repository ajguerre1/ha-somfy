"""Transport tests against an in-process fake UAI+.

A fake gateway that speaks the real dialect over a real socket is used rather
than mocking `asyncio.open_connection`. That way the auth handshake, the
line framing, and id correlation are genuinely exercised -- these are precisely
the parts that break against real hardware, so stubbing them out would test
nothing worth testing.

The fake reproduces the gateway's actual quirks: prompts without newlines, a
NUL in the success banner, inconsistent whitespace, and errors as bare ints.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator, Callable

import pytest

from custom_components.ha_somfy.uai.client import (
    UaiAuthError,
    UaiClient,
    UaiConnectionError,
)
from custom_components.ha_somfy.uai.models import Capability

USER = "homeassistant"
PASSWORD = "hunter2"

# Node IDs and type strings mirror the real bus.
SONESSE_50 = "136EA5"
SONESSE_30 = "07753E"  # the one that answers position with `false`
IRISMO = "40FD76"


class FakeGateway:
    """Minimal UAI+ emulator: auth handshake plus canned method replies."""

    def __init__(
        self,
        *,
        accept_auth: bool = True,
        drop_after: int | None = None,
        responder: Callable[[str, dict, int], str | None] | None = None,
    ) -> None:
        self.accept_auth = accept_auth
        self.drop_after = drop_after
        self.responder = responder or self.default_responder
        self.requests: list[dict] = []
        self.connections = 0
        self._server: asyncio.Server | None = None

    @property
    def port(self) -> int:
        assert self._server is not None
        return self._server.sockets[0].getsockname()[1]

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    @staticmethod
    def default_responder(method: str, params: dict, msg_id: int) -> str | None:
        target = params.get("targetID")
        if method == "sdn.status.ping":
            return json.dumps({"result": [SONESSE_50, SONESSE_30, IRISMO], "id": msg_id})
        if method == "sdn.status.info":
            info = {
                SONESSE_50: {"name": "RoomE Bed B/O", "type": "Sonesse 50DC"},
                SONESSE_30: {"name": "RoomB SH 2", "type": "Sonesse 30"},
                IRISMO: {"name": "RoomI SH 1", "type": "SDN Module"},
            }[target]
            # Reproduce the gateway's irregular spacing.
            return (
                f'{{ "result" : {{ "name" : "{info["name"]}",'
                f'"type":"{info["type"]}"}},"id":{msg_id}}}'
            )
        if method == "sdn.status.position":
            if target == IRISMO:
                return json.dumps({"error": -32600, "id": msg_id})
            if target == SONESSE_30:
                return json.dumps({"result": False, "id": msg_id})
            return json.dumps({"result": 100, "id": msg_id})
        if method == "sdn.group.get":
            return json.dumps({"result": ["01010A"], "id": msg_id})
        if method.startswith("sdn.move."):
            return json.dumps({"result": True, "id": msg_id})
        return json.dumps({"error": -32601, "id": msg_id})

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.connections += 1
        try:
            writer.write(b"User:")
            await writer.drain()
            await reader.readline()

            writer.write(b"Password:")
            await writer.drain()
            await reader.readline()

            if not self.accept_auth:
                writer.close()
                return

            # The real banner carries a trailing NUL.
            writer.write(b"Connected:\n\x00")
            await writer.drain()

            served = 0
            while True:
                line = await reader.readline()
                if not line:
                    return
                text = line.decode("ascii", errors="replace").strip()
                if not text or not text.startswith("{"):
                    continue
                request = json.loads(text)
                self.requests.append(request)

                flat: dict = {}
                for item in request.get("params", []):
                    flat.update(item)

                reply = self.responder(request["method"], flat, request["id"])
                if reply is not None:
                    writer.write(reply.encode("ascii") + b"\r\n")
                    await writer.drain()

                served += 1
                if self.drop_after is not None and served >= self.drop_after:
                    writer.close()
                    return
        except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
            return
        finally:
            with contextlib.suppress(Exception):
                writer.close()


@pytest.fixture
async def gateway() -> AsyncIterator[FakeGateway]:
    gw = FakeGateway()
    await gw.start()
    yield gw
    await gw.stop()


@pytest.fixture
async def client(gateway: FakeGateway) -> AsyncIterator[UaiClient]:
    c = UaiClient("127.0.0.1", gateway.port, USER, PASSWORD)
    await c.async_connect()
    yield c
    await c.async_disconnect()


# ---------------------------------------------------------------------------
# Connection and authentication
# ---------------------------------------------------------------------------


async def test_connects_and_completes_the_handshake(gateway: FakeGateway) -> None:
    c = UaiClient("127.0.0.1", gateway.port, USER, PASSWORD)
    await c.async_connect()
    assert c.connected is True
    await c.async_disconnect()
    assert c.connected is False


async def test_rejected_auth_raises_auth_error(gateway: FakeGateway) -> None:
    gateway.accept_auth = False
    c = UaiClient("127.0.0.1", gateway.port, USER, "wrong")
    with pytest.raises(UaiAuthError):
        await c.async_connect()


async def test_unreachable_host_raises_connection_error() -> None:
    # Port 1 on loopback: reliably closed, and fails fast.
    c = UaiClient("127.0.0.1", 1, USER, PASSWORD, timeout=2.0)
    with pytest.raises(UaiConnectionError):
        await c.async_connect()


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


async def test_ping_all_returns_every_node(client: UaiClient) -> None:
    assert await client.async_ping_all() == [SONESSE_50, SONESSE_30, IRISMO]


async def test_request_uses_the_list_params_shape(client: UaiClient, gateway: FakeGateway) -> None:
    await client.async_get_info(SONESSE_50)
    sent = gateway.requests[-1]
    assert sent["params"] == [{"targetID": SONESSE_50}]


async def test_info_parses_irregular_whitespace(client: UaiClient) -> None:
    info = await client.async_get_info(SONESSE_50)
    assert info == ("RoomE Bed B/O", "Sonesse 50DC")


async def test_numeric_position(client: UaiClient) -> None:
    assert await client.async_get_position(SONESSE_50) == 100


async def test_false_position_reads_as_unknown(client: UaiClient) -> None:
    """`false` means 'position unknown right now', not position 0."""
    assert await client.async_get_position(SONESSE_30) is None


async def test_unsupported_position_reads_as_unknown(client: UaiClient) -> None:
    assert await client.async_get_position(IRISMO) is None


async def test_position_supported_distinguishes_false_from_error(client: UaiClient) -> None:
    """The capability probe must tell the two apart.

    A Sonesse replying `false` is still position-capable; an Irismo replying
    `error` is not. Conflating them is what puts a dead slider on an Irismo.
    """
    assert await client.async_position_supported(SONESSE_30) is True
    assert await client.async_position_supported(IRISMO) is False


async def test_group_membership(client: UaiClient) -> None:
    assert await client.async_get_groups(IRISMO) == ["01010A"]


async def test_concurrent_requests_correlate_by_id(client: UaiClient) -> None:
    """Replies must reach the right waiter even when requests overlap."""
    results = await asyncio.gather(
        client.async_get_info(SONESSE_50),
        client.async_get_info(SONESSE_30),
        client.async_get_info(IRISMO),
    )
    assert [r[1] for r in results] == ["Sonesse 50DC", "Sonesse 30", "SDN Module"]


async def test_ids_are_not_reused_within_a_session(client: UaiClient, gateway: FakeGateway) -> None:
    for _ in range(5):
        await client.async_get_info(SONESSE_50)
    ids = [r["id"] for r in gateway.requests]
    assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


async def test_discovery_assigns_capability_from_type(client: UaiClient) -> None:
    nodes = await client.async_discover_nodes()
    by_id = {n.node_id: n for n in nodes}

    assert by_id[SONESSE_50].capability is Capability.POSITIONAL
    assert by_id[SONESSE_30].capability is Capability.POSITIONAL
    assert by_id[IRISMO].capability is Capability.NON_POSITIONAL


async def test_discovery_does_not_demote_a_motor_that_replied_false(
    client: UaiClient,
) -> None:
    """CAP-06. Capability comes from the type string, so a bad reading must not
    change the entity's feature set between polls."""
    nodes = await client.async_discover_nodes()
    sonesse_30 = next(n for n in nodes if n.node_id == SONESSE_30)
    assert sonesse_30.capability is Capability.POSITIONAL
    assert sonesse_30.position is None


async def test_unknown_type_is_resolved_by_probing(gateway: FakeGateway) -> None:
    """Unrecognised hardware gets its capability measured, never assumed."""

    def responder(method: str, params: dict, msg_id: int) -> str:
        if method == "sdn.status.ping":
            return json.dumps({"result": ["AAAAAA", "BBBBBB"], "id": msg_id})
        if method == "sdn.status.info":
            return json.dumps(
                {"result": {"name": "Mystery", "type": "Totally New Motor"}, "id": msg_id}
            )
        if method == "sdn.status.position":
            # AAAAAA answers with a number, BBBBBB refuses.
            if params.get("targetID") == "AAAAAA":
                return json.dumps({"result": 42, "id": msg_id})
            return json.dumps({"error": -32600, "id": msg_id})
        return json.dumps({"result": [], "id": msg_id})

    gateway.responder = responder
    c = UaiClient("127.0.0.1", gateway.port, USER, PASSWORD)
    await c.async_connect()
    try:
        nodes = {n.node_id: n for n in await c.async_discover_nodes()}
        assert nodes["AAAAAA"].capability is Capability.POSITIONAL
        assert nodes["BBBBBB"].capability is Capability.NON_POSITIONAL
    finally:
        await c.async_disconnect()


async def test_discovery_skips_the_all_group(client: UaiClient, gateway: FakeGateway) -> None:
    def responder(method: str, params: dict, msg_id: int) -> str:
        if method == "sdn.group.get":
            return json.dumps({"result": ["010101", "01010A"], "id": msg_id})
        return FakeGateway.default_responder(method, params, msg_id)

    gateway.responder = responder
    nodes = await client.async_discover_nodes()
    for node in nodes:
        assert "010101" not in node.groups


# ---------------------------------------------------------------------------
# Resilience
# ---------------------------------------------------------------------------


async def test_reconnects_after_the_gateway_drops_the_link(gateway: FakeGateway) -> None:
    gateway.drop_after = 1
    c = UaiClient("127.0.0.1", gateway.port, USER, PASSWORD, timeout=3.0)
    await c.async_connect()
    try:
        assert await c.async_ping_all() == [SONESSE_50, SONESSE_30, IRISMO]
        gateway.drop_after = None
        # The link is gone; the next call must transparently reconnect.
        assert await c.async_get_position(SONESSE_50) == 100
        assert gateway.connections >= 2
    finally:
        await c.async_disconnect()
