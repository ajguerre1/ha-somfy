"""Constants for the HA Somfy integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "ha_somfy"
MANUFACTURER: Final = "Somfy"
GATEWAY_MODEL: Final = "Connect UAI+"

CONF_POLL_INTERVAL: Final = "poll_interval"

# Per-motor capability overrides, keyed by node ID. Absent means "trust
# detection", which is the case for every node on the reference bus -- see
# CAP-02 and `apply_capability_override`.
CONF_CAPABILITY_OVERRIDES: Final = "capability_overrides"
CONF_MOTOR: Final = "motor"
CONF_CAPABILITY: Final = "capability"

# --- The gateway's web interface (IRIS-01) ---------------------------------
#
# A second, separate credential from the telnet one. Optional: without it the
# integration works exactly as it did before, and motors with no telnet
# position simply report no state. With it, Irismo nodes gain open/closed.
CONF_WEB_PASSWORD: Final = "web_password"

WEB_TIMEOUT: Final = 10

# `somfy_device.json` intermittently answers with a different node's payload,
# or 404. Measured over 11 nodes: all resolved within five attempts and only
# two needed more than one, so three is comfortable headroom.
WEB_MAX_ATTEMPTS: Final = 5
WEB_RETRY_DELAY: Final = 0.3

# Consecutive whole-read failures, with no success ever, before saying so at
# WARNING level. One poll of nine Irismo nodes is nine reads, so this fires
# on the second cycle rather than instantly on a transient stumble.
WEB_FAILURES_BEFORE_WARNING: Final = 3

DEFAULT_POLL_INTERVAL: Final = 60
MIN_POLL_INTERVAL: Final = 10
MAX_POLL_INTERVAL: Final = 3600

# --- Following a moving motor ----------------------------------------------
#
# At the default 60 s interval a shade you just opened can read its old
# position for most of a minute, which looks broken. While a motor is moving we
# poll it faster -- but *only that motor*, never the fleet, because every state
# change fans out to the whole wall-panel estate.
#
# The bus is fast (measured mean 0.03 s per request), so this costs very little.
MOVING_POLL_INTERVAL: Final = 2

# Consecutive unchanged readings before a motor is considered settled. Three
# (~6 s) comfortably covers the delay between issuing a command and the motor
# actually starting, so we do not give up before it has moved.
MOVING_SETTLE_READS: Final = 3

# Hard ceiling, so a motor that never settles cannot poll forever.
MOVING_POLL_MAX_SECONDS: Final = 120

# A node can miss a discovery pass and come back; one was observed absent from
# a single ping and present in the four that followed. Entities must survive
# that, so a node is only considered gone after this many consecutive misses.
MAX_MISSED_DISCOVERIES: Final = 3

# --- Position polarity -----------------------------------------------------
#
# PROTO-08, UNRESOLVED. Somfy's convention is 0 = open / 100 = closed, which is
# the inverse of Home Assistant's 0 = closed / 100 = open. Every motor on the
# reference bus currently reads exactly 0 or 100, so the captured data cannot
# settle it, and guessing wrong inverts every slider in the house.
#
# The conversion is deliberately funnelled through the two helpers below so
# that confirming this on hardware is a one-line change here, not a hunt
# through the entity code.
GATEWAY_POSITION_IS_INVERTED: Final = True


def gateway_to_ha_position(value: int) -> int:
    """Convert a gateway position (0-100) to Home Assistant's scale."""
    return 100 - value if GATEWAY_POSITION_IS_INVERTED else value


def ha_to_gateway_position(value: int) -> int:
    """Convert a Home Assistant position (0-100) to the gateway's scale."""
    return 100 - value if GATEWAY_POSITION_IS_INVERTED else value


# A cover is reported closed at or beyond this HA-scale position. Somfy motors
# do not always land exactly on 0, so an exact comparison would leave blinds
# stuck reporting "open" when they are visibly shut.
CLOSED_POSITION_THRESHOLD: Final = 2
