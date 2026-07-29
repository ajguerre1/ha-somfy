"""Request encoding and reply parsing, checked against verbatim gateway output.

Every response string in these tests was captured from the live UAI+, including
its inconsistent whitespace. If a parser passes here it will survive the real
device.
"""

from __future__ import annotations

import json

import pytest

from custom_components.ha_somfy.uai.protocol import (
    METHOD_GROUP_GET,
    METHOD_STATUS_INFO,
    METHOD_STATUS_PING,
    METHOD_STATUS_POSITION,
    encode_request,
    parse_response,
)

# ---------------------------------------------------------------------------
# Request encoding
# ---------------------------------------------------------------------------


def test_params_are_a_list_of_single_key_dicts() -> None:
    """PROTO-03. A bare dict is the wrong shape -- upstream gets this wrong."""
    encoded = encode_request(METHOD_STATUS_INFO, {"targetID": "136EA5"}, 1002)
    payload = json.loads(encoded)

    assert isinstance(payload["params"], list)
    assert payload["params"] == [{"targetID": "136EA5"}]
    assert payload["method"] == "sdn.status.info"
    assert payload["id"] == 1002


def test_multiple_params_become_multiple_single_key_dicts() -> None:
    payload = json.loads(encode_request("sdn.status.info", {"a": 1, "b": 2}, 7))
    assert payload["params"] == [{"a": 1}, {"b": 2}]


def test_encoded_request_matches_the_captured_wire_format(wire_samples: dict) -> None:
    expected = json.loads(wire_samples["requests"]["info"])
    actual = json.loads(encode_request(METHOD_STATUS_INFO, {"targetID": "136EA5"}, 1002))
    assert actual == expected


def test_encoded_request_is_a_single_line() -> None:
    """Framing is line-based; an embedded newline would desynchronise the stream."""
    encoded = encode_request(METHOD_STATUS_INFO, {"targetID": "136EA5"}, 1)
    assert "\n" not in encoded and "\r" not in encoded


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def test_parses_ping_reply_despite_odd_whitespace(wire_samples: dict) -> None:
    response = parse_response(wire_samples["responses"]["ping_all"])
    assert response is not None
    assert response.id == 1001
    assert response.result == ["136EA5", "136DA3", "40FD76"]
    assert not response.is_error


@pytest.mark.parametrize(
    ("key", "name", "type_string"),
    [
        ("info_sonesse_50dc", "RoomE Bed B/O", "Sonesse 50DC"),
        ("info_sonesse_30", "RoomB SH 2", "Sonesse 30"),
        ("info_sdn_module", "RoomI SH 1", "SDN Module"),
    ],
)
def test_parses_info_replies(wire_samples: dict, key: str, name: str, type_string: str) -> None:
    response = parse_response(wire_samples["responses"][key])
    assert response is not None
    assert response.result["name"] == name
    assert response.result["type"] == type_string


def test_parses_numeric_position(wire_samples: dict) -> None:
    response = parse_response(wire_samples["responses"]["position_numeric"])
    assert response.result == 100
    assert not response.is_error


def test_parses_false_position_as_a_successful_reply(wire_samples: dict) -> None:
    """`false` is a valid reply, not an error. Interpreting it is the model's job."""
    response = parse_response(wire_samples["responses"]["position_false"]["line"])
    assert response is not None
    assert response.is_error is False
    assert response.has_result is True
    assert response.result is False


def test_parses_the_irismo_position_refusal(wire_samples: dict) -> None:
    """Errors are a bare int, not a JSON-RPC error object, and carry no result key."""
    response = parse_response(wire_samples["responses"]["position_unsupported"]["line"])
    assert response is not None
    assert response.is_error is True
    assert response.error == -32600
    assert response.has_result is False
    assert response.id == 1046


def test_error_and_false_are_distinguishable(wire_samples: dict) -> None:
    """The whole capability model rests on telling these two apart.

    `false` means a position-capable motor does not know its position right now.
    `error` means the node has no position feature at all.
    """
    false_reply = parse_response(wire_samples["responses"]["position_false"]["line"])
    error_reply = parse_response(wire_samples["responses"]["position_unsupported"]["line"])
    assert false_reply.is_error != error_reply.is_error


@pytest.mark.parametrize("key", ["group_get", "group_get_multi", "group_get_empty"])
def test_parses_group_replies(wire_samples: dict, key: str) -> None:
    response = parse_response(wire_samples["responses"][key])
    assert response is not None
    assert isinstance(response.result, list)


@pytest.mark.parametrize(
    "line",
    ["", "   ", "&TYPE=?", "not json at all", "Connected:", "\x00"],
)
def test_non_json_lines_are_ignored_not_fatal(line: str) -> None:
    """The gateway emits non-JSON chatter; it must not crash or desync the reader."""
    assert parse_response(line) is None


def test_method_constants_are_read_only_shaped() -> None:
    """Guard against a movement method sneaking into the constant list."""
    for method in (
        METHOD_STATUS_PING,
        METHOD_STATUS_INFO,
        METHOD_STATUS_POSITION,
        METHOD_GROUP_GET,
    ):
        assert ".move." not in method
        assert method.startswith("sdn.")
