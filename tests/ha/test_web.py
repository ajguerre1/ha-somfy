"""The web-interface client.

`somfy_device.json` is a scraped page, not an API, and it misbehaves in three
specific ways that were measured against the live gateway. Each one has a test
here, because each one would otherwise surface as a wrong blind state rather
than as an error.
"""

from __future__ import annotations

import pytest

from custom_components.ha_somfy.web import SomfyWebClient

HOST = "10.0.0.1"
NODE = "40FCFC"
OTHER = "136EA5"

DEVICE_URL = f"http://{HOST}/somfy_device.json?40.FC.FC"
LOGIN_URL = f"http://{HOST}/password.cgi?VERIFY=webpw"


def device(node: str, position: str, label: str = "RoomD Hall SH") -> dict:
    dotted = ".".join(node[i : i + 2] for i in range(0, len(node), 2))
    return {"DEVICE": {"NODE": dotted, "TYPE": "SDN Module", "LABEL": label, "POSITION": position}}


@pytest.fixture
def client(hass) -> SomfyWebClient:
    return SomfyWebClient(hass, HOST, "webpw")


async def test_the_percentage_is_returned_not_the_raw_value(hass, aioclient_mock, client) -> None:
    aioclient_mock.get(LOGIN_URL, text="")
    aioclient_mock.get(DEVICE_URL, json=device(NODE, "1000 (100 %)"))

    assert await client.async_get_position(NODE) == 100


async def test_an_open_irismo_reads_zero(hass, aioclient_mock, client) -> None:
    aioclient_mock.get(LOGIN_URL, text="")
    aioclient_mock.get(DEVICE_URL, json=device(NODE, "0 (0 %)"))

    assert await client.async_get_position(NODE) == 0


async def test_a_payload_for_a_different_node_is_discarded(hass, aioclient_mock, client) -> None:
    """The one that matters most.

    The gateway really does answer a request for one node with another node's
    payload. Accepting it would put the hallway drape's state on a bedroom
    blind -- silently, and permanently until the next successful read.
    """
    aioclient_mock.get(LOGIN_URL, text="")
    aioclient_mock.get(DEVICE_URL, json=device(OTHER, "0 (0 %)"))

    assert await client.async_get_position(NODE) is None


async def test_a_mismatch_is_retried_and_can_succeed(hass, aioclient_mock, client) -> None:
    """Measured behaviour: 11/11 nodes resolved within five attempts, two of
    them needing more than one."""
    aioclient_mock.get(LOGIN_URL, text="")
    aioclient_mock.get(
        DEVICE_URL,
        side_effect=[
            {"json": device(OTHER, "0 (0 %)")},
            {"json": device(NODE, "1000 (100 %)")},
        ],
    )

    assert await client.async_get_position(NODE) == 100


async def test_a_404_is_retried(hass, aioclient_mock, client) -> None:
    aioclient_mock.get(LOGIN_URL, text="")
    aioclient_mock.get(
        DEVICE_URL, side_effect=[{"status": 404}, {"json": device(NODE, "1000 (100 %)")}]
    )

    assert await client.async_get_position(NODE) == 100


async def test_a_403_logs_in_and_retries(hass, aioclient_mock, client) -> None:
    """The session expires on its own schedule, so a 403 is a routine event
    rather than a failure."""
    aioclient_mock.get(LOGIN_URL, text="")
    aioclient_mock.get(
        DEVICE_URL, side_effect=[{"status": 403}, {"json": device(NODE, "1000 (100 %)")}]
    )

    assert await client.async_get_position(NODE) == 100
    assert any(str(call[1]).startswith(LOGIN_URL) for call in aioclient_mock.mock_calls)


async def test_giving_up_reports_unknown_rather_than_guessing(hass, aioclient_mock, client) -> None:
    aioclient_mock.get(LOGIN_URL, text="")
    aioclient_mock.get(DEVICE_URL, status=404)

    assert await client.async_get_position(NODE) is None


async def test_an_unreadable_position_string_is_unknown(hass, aioclient_mock, client) -> None:
    """A firmware that reformats this string must leave the blind unknown, not
    wrong."""
    aioclient_mock.get(LOGIN_URL, text="")
    aioclient_mock.get(DEVICE_URL, json=device(NODE, "somewhere in the middle"))

    assert await client.async_get_position(NODE) is None


async def test_without_a_password_no_request_is_made(hass, aioclient_mock) -> None:
    """Not merely 'returns None' -- an unconfigured client must not talk to the
    gateway at all."""
    client = SomfyWebClient(hass, HOST, None)

    assert client.configured is False
    assert await client.async_get_position(NODE) is None
    assert aioclient_mock.call_count == 0


async def test_labels_come_back_keyed_by_node(hass, aioclient_mock, client) -> None:
    aioclient_mock.get(LOGIN_URL, text="")
    aioclient_mock.get(DEVICE_URL, json=device(NODE, "1000 (100 %)", label="RoomD Hall SH"))

    assert await client.async_get_labels([NODE]) == {NODE: "RoomD Hall SH"}
