"""The web-interface client.

`somfy_device.json` is a scraped page, not an API, and it misbehaves in three
specific ways that were measured against the live gateway. Each has a test
here, because each would otherwise surface as a wrong blind state rather than
as an error.

These use a hand-rolled session rather than `aioclient_mock` because most of
what is worth testing is a *sequence* -- a bad answer followed by a good one --
and the mocker cannot express that.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from custom_components.ha_somfy.const import WEB_MAX_ATTEMPTS
from custom_components.ha_somfy.web import SomfyWebClient

HOST = "10.0.0.1"
NODE = "40FCFC"
OTHER = "136EA5"


def device(node: str, position: str, label: str = "RoomD Hall SH") -> dict[str, Any]:
    dotted = ".".join(node[i : i + 2] for i in range(0, len(node), 2))
    return {"DEVICE": {"NODE": dotted, "TYPE": "SDN Module", "LABEL": label, "POSITION": position}}


class _Response:
    def __init__(self, status: int, payload: Any) -> None:
        self.status = status
        self._payload = payload

    async def json(self, content_type: Any = None) -> Any:
        if self._payload is None:
            raise ValueError("not json")
        return self._payload

    async def __aenter__(self) -> _Response:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _Session:
    """Serves a queued sequence of device responses; logins always succeed."""

    def __init__(self, *responses: _Response) -> None:
        self._queue = list(responses)
        self.device_urls: list[str] = []
        self.login_count = 0

    def get(self, url: Any, **_: Any) -> _Response:
        text = str(url)
        if "password.cgi" in text:
            self.login_count += 1
            return _Response(200, {})
        self.device_urls.append(text)
        # The last queued response repeats, so "always fails" is expressible.
        return self._queue.pop(0) if len(self._queue) > 1 else self._queue[0]


@pytest.fixture
def make_client(hass):
    def _make(*responses: _Response, password: str | None = "webpw"):
        session = _Session(*responses) if responses else _Session(_Response(404, None))
        client = SomfyWebClient(hass, HOST, password)
        patcher = patch(
            "custom_components.ha_somfy.web.async_get_clientsession", return_value=session
        )
        patcher.start()
        return client, session, patcher

    made: list[Any] = []

    def _factory(*responses: _Response, password: str | None = "webpw"):
        client, session, patcher = _make(*responses, password=password)
        made.append(patcher)
        return client, session

    yield _factory

    for patcher in made:
        patcher.stop()


# ---------------------------------------------------------------------------
# Reading a position
# ---------------------------------------------------------------------------


async def test_the_percentage_is_returned_not_the_raw_value(make_client) -> None:
    client, _ = make_client(_Response(200, device(NODE, "1000 (100 %)")))

    assert await client.async_get_position(NODE) == 100


async def test_an_open_irismo_reads_zero(make_client) -> None:
    client, _ = make_client(_Response(200, device(NODE, "0 (0 %)")))

    assert await client.async_get_position(NODE) == 0


async def test_the_node_is_addressed_in_dotted_form(make_client) -> None:
    client, session = make_client(_Response(200, device(NODE, "0 (0 %)")))

    await client.async_get_position(NODE)

    assert session.device_urls[0].endswith("somfy_device.json?40.FC.FC")


async def test_an_unreadable_position_string_is_unknown(make_client) -> None:
    """A firmware that reformats this string must leave the blind unknown,
    never wrong."""
    client, _ = make_client(_Response(200, device(NODE, "somewhere in the middle")))

    assert await client.async_get_position(NODE) is None


# ---------------------------------------------------------------------------
# The gateway answering with the wrong node
# ---------------------------------------------------------------------------


async def test_a_payload_for_a_different_node_is_discarded(make_client) -> None:
    """The one that matters most.

    The gateway really does answer a request for one node with another node's
    payload. Accepting it would put the hallway drape's state onto a bedroom
    blind, silently, until the next successful read.
    """
    client, _ = make_client(_Response(200, device(OTHER, "0 (0 %)")))

    assert await client.async_get_position(NODE) is None


async def test_a_mismatch_is_retried_and_can_succeed(make_client) -> None:
    """Measured: 11/11 nodes resolved within five attempts, two needing more
    than one."""
    client, session = make_client(
        _Response(200, device(OTHER, "0 (0 %)")),
        _Response(200, device(NODE, "1000 (100 %)")),
    )

    assert await client.async_get_position(NODE) == 100
    assert len(session.device_urls) == 2


async def test_a_404_is_retried(make_client) -> None:
    client, _ = make_client(_Response(404, None), _Response(200, device(NODE, "1000 (100 %)")))

    assert await client.async_get_position(NODE) == 100


async def test_giving_up_reports_unknown_rather_than_guessing(make_client) -> None:
    client, session = make_client(_Response(404, None))

    assert await client.async_get_position(NODE) is None
    assert len(session.device_urls) == WEB_MAX_ATTEMPTS


# ---------------------------------------------------------------------------
# The session
# ---------------------------------------------------------------------------


async def test_a_403_logs_in_and_retries(make_client) -> None:
    """The session expires on its own schedule, so a 403 is routine rather
    than a failure."""
    client, session = make_client(
        _Response(403, None), _Response(200, device(NODE, "1000 (100 %)"))
    )

    assert await client.async_get_position(NODE) == 100
    assert session.login_count >= 1


async def test_the_password_is_sent_unencoded(make_client, hass) -> None:
    """Percent-encoding it is rejected with 403. Measured, not assumed."""
    session = _Session(_Response(200, device(NODE, "0 (0 %)")))
    captured: list[str] = []

    class _Recording(_Session):
        def get(self, url: Any, **kw: Any) -> _Response:
            captured.append(str(url))
            return super().get(url, **kw)

    recording = _Recording(_Response(200, device(NODE, "0 (0 %)")))
    with patch("custom_components.ha_somfy.web.async_get_clientsession", return_value=recording):
        client = SomfyWebClient(hass, HOST, "Volvo@1980")
        await client.async_get_position(NODE)

    assert any("VERIFY=Volvo@1980" in url for url in captured)
    assert not any("%40" in url for url in captured)
    assert session.login_count == 0  # the unused fixture session stayed idle


async def test_without_a_password_no_request_is_made(make_client) -> None:
    """Not merely 'returns None' -- an unconfigured client must not talk to the
    gateway at all."""
    client, session = make_client(_Response(200, device(NODE, "0 (0 %)")), password=None)

    assert client.configured is False
    assert await client.async_get_position(NODE) is None
    assert session.device_urls == []
    assert session.login_count == 0


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------


async def test_labels_come_back_keyed_by_node(make_client) -> None:
    client, _ = make_client(_Response(200, device(NODE, "1000 (100 %)", label="RoomD Hall SH")))

    assert await client.async_get_labels([NODE]) == {NODE: "RoomD Hall SH"}


async def test_a_node_the_gateway_will_not_serve_is_simply_absent(make_client) -> None:
    """Discovery keeps the telnet name for those, so a miss must not raise."""
    client, _ = make_client(_Response(404, None))

    assert await client.async_get_labels([NODE]) == {}


# ---------------------------------------------------------------------------
# A stale session that does not announce itself (IRIS-04)
# ---------------------------------------------------------------------------


async def test_persistent_wrong_node_answers_trigger_a_re_login(make_client) -> None:
    """The bug that made v0.3.0 fail silently on real hardware.

    A dead session answers HTTP 200 with another node's payload, not 403. The
    NODE guard rejects it correctly, but re-authenticating only on 403 meant
    nothing ever looked like an auth failure -- so the client retried a dead
    session forever and the blinds stayed unknown.
    """
    client, session = make_client(_Response(200, device(OTHER, "0 (0 %)")))

    assert await client.async_get_position(NODE) is None
    assert session.login_count >= 2, "a persistently rejected read must re-authenticate"


async def test_a_failed_read_does_not_poison_the_next_one(make_client) -> None:
    """Nine Irismo are read in sequence. If a dead session were inherited from
    one node to the next, one bad read would take the whole fleet down."""
    client, session = make_client(
        _Response(200, device(OTHER, "0 (0 %)")),
        _Response(200, device(OTHER, "0 (0 %)")),
        _Response(200, device(OTHER, "0 (0 %)")),
        _Response(200, device(OTHER, "0 (0 %)")),
        _Response(200, device(OTHER, "0 (0 %)")),
        _Response(200, device(NODE, "1000 (100 %)")),
    )

    assert await client.async_get_position(NODE) is None
    before = session.login_count
    assert await client.async_get_position(NODE) == 100
    assert session.login_count > before, "the next read must start a fresh session"
