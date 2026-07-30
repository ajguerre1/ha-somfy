"""Wire protocol for the Somfy Connect UAI+ telnet interface.

The gateway speaks a JSON-RPC-ish dialect over TCP 23, one message per line.
It has several quirks that were confirmed against real hardware
(HW 04.04 / FW 02.03.11) and are documented in
docs/ai/design/feature-uai-protocol.md:

* `params` is a LIST of single-key dicts, not a bare dict.
* Errors come back as a bare integer under `error`, not a JSON-RPC error
  object, and carry no `result` key at all.
* Reply whitespace is inconsistent between message kinds, so nothing here may
  depend on formatting.
* Non-JSON chatter appears on the stream and must be skipped, not treated as a
  protocol violation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final

# -- methods ---------------------------------------------------------------
# Read-only.
METHOD_STATUS_PING: Final = "sdn.status.ping"
METHOD_STATUS_INFO: Final = "sdn.status.info"
METHOD_STATUS_POSITION: Final = "sdn.status.position"
METHOD_GROUP_GET: Final = "sdn.group.get"

# Movement. Kept separate from the read-only set above so that callers, tests
# and reviewers can tell at a glance which is which.
METHOD_MOVE_UP: Final = "sdn.move.up"
METHOD_MOVE_DOWN: Final = "sdn.move.down"
METHOD_MOVE_STOP: Final = "sdn.move.stop"
METHOD_MOVE_TO: Final = "sdn.move.to"
METHOD_MOVE_IP: Final = "sdn.move.ip"

READ_ONLY_METHODS: Final = frozenset(
    {METHOD_STATUS_PING, METHOD_STATUS_INFO, METHOD_STATUS_POSITION, METHOD_GROUP_GET}
)
MOVEMENT_METHODS: Final = frozenset(
    {METHOD_MOVE_UP, METHOD_MOVE_DOWN, METHOD_MOVE_STOP, METHOD_MOVE_TO, METHOD_MOVE_IP}
)

# Target wildcard accepted by sdn.status.ping to enumerate the whole bus.
TARGET_ALL: Final = "*"

# -- request ids -----------------------------------------------------------
#
# The gateway broadcasts replies to EVERY open telnet session. Measured on the
# reference gateway: a connection that had sent only ids 5001-5003 received
# fourteen replies carrying ids 8703-8716 -- another session's traffic arriving
# on ours.
#
# A reply echoes neither the method nor the target, only the id, so a foreign
# reply whose id matches one of our pending requests is indistinguishable from
# our own and would store one motor's position on another. Replies for ids we
# never issued are already dropped; this range is about the exact-collision
# case. A fixed base of 1000 made that a matter of hours, since polling 40
# motors a minute sweeps the counter straight through the low range other
# clients use. Starting high and at an unpredictable point does not make
# collision impossible, but it moves it to effectively never.
MIN_REQUEST_ID: Final = 100_000
MAX_REQUEST_ID: Final = 900_000

# Auth handshake. These prompts are NOT newline-terminated, so the transport
# has to read until a substring rather than until a line ending.
PROMPT_USER: Final = "User:"
PROMPT_PASSWORD: Final = "Password:"
PROMPT_CONNECTED: Final = "Connected:"

# The gateway's "unsupported" answer, e.g. asking an Irismo bridge for position.
ERROR_INVALID_REQUEST: Final = -32600


@dataclass(frozen=True, slots=True)
class Response:
    """One parsed reply.

    `has_result` distinguishes a genuine `{"result": false}` -- a position-capable
    motor that does not currently know where it is -- from an error reply that
    omits `result` entirely. Collapsing those two is how an Irismo ends up with a
    dead position slider, so the distinction is load-bearing.
    """

    id: int | None
    result: Any = None
    error: int | None = None
    has_result: bool = False

    @property
    def is_error(self) -> bool:
        return self.error is not None


def encode_request(method: str, params: dict[str, Any], msg_id: int) -> str:
    """Build one request line.

    `params` is expanded into a list of single-key dicts, which is the shape the
    gateway actually accepts.
    """
    payload = {
        "method": method,
        "params": [{key: value} for key, value in params.items()],
        "id": msg_id,
    }
    return json.dumps(payload, separators=(",", ":"))


def parse_response(line: str) -> Response | None:
    """Parse one reply line, or return None if it is not a JSON reply.

    Returning None for chatter (heartbeat echoes, the auth banner, stray NULs)
    keeps the read loop resilient: unrecognised input is skipped rather than
    breaking the stream.
    """
    text = line.strip().strip("\x00").strip()
    if not text:
        return None

    try:
        message = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None

    if not isinstance(message, dict):
        return None

    raw_id = message.get("id")
    msg_id = raw_id if isinstance(raw_id, int) and not isinstance(raw_id, bool) else None

    error = message.get("error")
    if error is not None and isinstance(error, int) and not isinstance(error, bool):
        return Response(id=msg_id, error=error, has_result=False)

    if "result" in message:
        return Response(id=msg_id, result=message["result"], has_result=True)

    # A reply with neither result nor a recognisable error is still a reply --
    # surface it rather than silently dropping it, so a caller waiting on this
    # id is not left hanging until timeout.
    return Response(id=msg_id, has_result=False)
