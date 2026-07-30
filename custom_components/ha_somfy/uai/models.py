"""Domain model: what a node is, what it can do, and how groups are addressed.

The central idea of this integration lives here. Every other UAI+ integration
assumes every motor reports position and hardcodes SET_POSITION for all of them,
which leaves Irismo blinds with a dead slider and a permanently unknown state.
Here, capability is derived from what the gateway reports and verified when it
is unclear -- never assumed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final


class Capability(StrEnum):
    """What a node can actually do."""

    POSITIONAL = "positional"
    NON_POSITIONAL = "non_positional"
    UNKNOWN = "unknown"


# Type-string markers, matched case-insensitively against the gateway's
# `sdn.status.info` reply after whitespace normalisation.
#
# On the reference bus the complete set of observed strings is
# "Sonesse 50DC" (28), "Sonesse 30" (12) and "SDN Module" (9).
POSITIONAL_MARKERS: Final = (
    "sonesse",
    "glydea",
    "lsu",
    "50dc",
    "50ac",
    "40ac",
    "30dc",
)

# "sdn module" is how an Irismo motor behind a Somfy 1811129 bridge presents
# itself. The gateway names the BRIDGE, never the motor, so the string "irismo"
# does not appear anywhere on the wire -- matching on it would miss every single
# Irismo. It is retained below only as a defensive alias in case other firmware
# revisions report differently.
NON_POSITIONAL_MARKERS: Final = (
    "sdn module",
    "irismo",
    "dct",
)

GROUP_ID_PREFIX: Final = "0101"
GROUP_INDEX_MIN: Final = 1
GROUP_INDEX_MAX: Final = 16 * 16 - 1

# Group 1 is "ALL". It has no stored membership and behaves as a broadcast, so
# discovery skips it.
ALL_GROUP_ID: Final = f"{GROUP_ID_PREFIX}01"

_GROUP_ID_RE: Final = re.compile(rf"^{GROUP_ID_PREFIX}([0-9A-Fa-f]{{2}})$")
_WHITESPACE_RE: Final = re.compile(r"\s+")

POSITION_MIN: Final = 0
POSITION_MAX: Final = 100


def _normalise(type_string: str | None) -> str:
    if not type_string:
        return ""
    return _WHITESPACE_RE.sub(" ", type_string).strip().lower()


def classify_type(type_string: str | None) -> Capability:
    """Map a gateway type string to a capability.

    Unrecognised hardware returns UNKNOWN rather than POSITIONAL. That matters:
    guessing "positional" is what produces a broken slider, whereas UNKNOWN
    tells the caller to settle the question with a live position probe.
    """
    normalised = _normalise(type_string)
    if not normalised:
        return Capability.UNKNOWN

    # Non-positional is checked first: it is the more specific claim, and a
    # future string like "Sonesse SDN Module" should resolve to non-positional.
    if any(marker in normalised for marker in NON_POSITIONAL_MARKERS):
        return Capability.NON_POSITIONAL
    if any(marker in normalised for marker in POSITIONAL_MARKERS):
        return Capability.POSITIONAL
    return Capability.UNKNOWN


def parse_position(raw: Any) -> int | None:
    """Return a 0-100 position, or None when the gateway did not give one.

    `bool` is rejected before the numeric check because it subclasses `int` in
    Python: `isinstance(False, int)` is True, so the gateway's legitimate
    `{"result": false}` -- meaning "position currently unknown" -- would
    otherwise be read as position 0, i.e. reported as fully closed. A real
    Sonesse 30 on the reference bus replies exactly this way.
    """
    if isinstance(raw, bool):
        return None
    if not isinstance(raw, int | float):
        return None
    value = int(raw)
    if value < POSITION_MIN or value > POSITION_MAX:
        return None
    return value


def group_id_for_index(index: int) -> str:
    """Group index (1-based, as used by GET /somfy_groups.json) -> group ID."""
    return f"{GROUP_ID_PREFIX}{index:02X}"


def group_index_for_id(group_id: str | None) -> int | None:
    """Group ID -> 1-based index, or None if it is not a well-formed group ID."""
    if not group_id or not isinstance(group_id, str):
        return None
    match = _GROUP_ID_RE.match(group_id.strip())
    if match is None:
        return None
    index = int(match.group(1), 16)
    if index < GROUP_INDEX_MIN or index > GROUP_INDEX_MAX:
        return None
    return index


def unique_slug_names(pairs: list[tuple[str, str | None]]) -> dict[str, str]:
    """Make node display names unique, keyed by node ID.

    The gateway permits duplicate labels -- two nodes on the reference bus are
    both called "RoomA B/O 2" -- but Home Assistant entity IDs must be
    unique. Names that are already unique are left untouched so entity IDs stay
    stable and human-readable; only genuine collisions get a node-ID suffix.
    """
    counts: dict[str, int] = {}
    for _, name in pairs:
        key = (name or "").strip()
        if key:
            counts[key] = counts.get(key, 0) + 1

    resolved: dict[str, str] = {}
    for node_id, name in pairs:
        key = (name or "").strip()
        if not key:
            resolved[node_id] = node_id
        elif counts.get(key, 0) > 1:
            resolved[node_id] = f"{key} ({node_id})"
        else:
            resolved[node_id] = key
    return resolved


@dataclass(slots=True)
class Node:
    """One motor on the SDN bus."""

    node_id: str
    name: str | None = None
    type_string: str | None = None
    capability: Capability = Capability.UNKNOWN
    position: int | None = None
    groups: list[str] = field(default_factory=list)
    # Consecutive discovery passes in which this node did not answer. Nodes drop
    # out transiently, so entities must survive a miss rather than disappearing.
    missed_discoveries: int = 0

    @property
    def supports_position(self) -> bool:
        return self.capability is Capability.POSITIONAL


def _squash(text: str) -> str:
    """Lowercase and strip all whitespace, for tolerant name comparison."""
    return _WHITESPACE_RE.sub("", text).lower()


@dataclass(frozen=True, slots=True)
class NameConflict:
    """A node whose name points at a group it is not a member of."""

    node_id: str
    name: str
    own_group: str
    suggested_group: str


def find_name_group_conflicts(
    nodes: list[Node], groups: dict[str, GroupInfo]
) -> list[NameConflict]:
    """Flag nodes whose name points at a group they are not in.

    A node called "RoomA B/O 2" that sits in the "RoomA SH" group is
    suspicious: the name claims membership of a *different group that actually
    exists*. That exact case occurred on the reference bus, where the gateway
    briefly reported a stale name while the group membership was already
    correct -- and it went unnoticed because nothing compared the two.

    Deliberately narrow, to stay quiet on legitimate naming:

    * Whitespace and case are ignored, so "RoomI SH 1" in the "RoomI
      SH" group is fine.
    * A name that simply differs from its group's, like "RoomD Hall SH" in
      "RoomD SH", is fine too -- it resembles no *other* group.

    Only a name that matches some other group's name raises a flag.
    """
    conflicts: list[NameConflict] = []
    by_squashed = {_squash(group.name): group for group in groups.values() if group.name}
    upper_groups = {gid.upper(): group for gid, group in groups.items()}

    for node in nodes:
        if not node.name or not node.groups:
            continue
        own_ids = {gid.upper() for gid in node.groups}
        own_names = [_squash(upper_groups[gid].name) for gid in own_ids if gid in upper_groups]
        squashed_name = _squash(node.name)

        # A name consistent with one of its own groups is never a conflict,
        # so "RoomB SH 1" in "RoomB SH" stays quiet.
        if any(name and squashed_name.startswith(name) for name in own_names):
            continue

        for squashed_group, group in by_squashed.items():
            if not squashed_group or group.group_id.upper() in own_ids:
                continue
            if squashed_name.startswith(squashed_group):
                own_group = next(
                    (upper_groups[gid].name for gid in own_ids if gid in upper_groups),
                    "unknown",
                )
                conflicts.append(NameConflict(node.node_id, node.name, own_group, group.name))
                break

    return conflicts


@dataclass(slots=True)
class GroupInfo:
    """One motor group, addressed as 0101 + hex(index)."""

    group_id: str
    index: int
    name: str
    members: list[str] = field(default_factory=list)

    @property
    def is_all_group(self) -> bool:
        return self.group_id.upper() == ALL_GROUP_ID


def capability_for_group(member_capabilities: list[Capability]) -> Capability:
    """A group is only as capable as its least capable member.

    Every group on the reference bus is homogeneous, but a mixed group would be
    ambiguous, and claiming SET_POSITION for a group containing an Irismo would
    reintroduce exactly the bug this integration exists to fix.
    """
    if not member_capabilities:
        return Capability.UNKNOWN
    if any(cap is Capability.NON_POSITIONAL for cap in member_capabilities):
        return Capability.NON_POSITIONAL
    if all(cap is Capability.POSITIONAL for cap in member_capabilities):
        return Capability.POSITIONAL
    return Capability.UNKNOWN
