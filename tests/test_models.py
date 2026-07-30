"""Capability classification and value parsing.

Every test here exists because the live bus proved it necessary. These are not
hypothetical edge cases -- each one maps to something observed on 2026-07-29.
"""

from __future__ import annotations

import pytest

from custom_components.ha_somfy.uai.models import (
    ALL_GROUP_ID,
    OVERRIDE_AUTO,
    Capability,
    GroupInfo,
    Node,
    apply_capability_override,
    classify_type,
    find_name_group_conflicts,
    group_id_for_index,
    group_index_for_id,
    parse_position,
    unique_slug_names,
)

# ---------------------------------------------------------------------------
# Capability classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "type_string",
    ["Sonesse 50DC", "Sonesse 30", "sonesse 50dc", "SONESSE 30", " Sonesse  50DC "],
)
def test_sonesse_is_positional(type_string: str) -> None:
    assert classify_type(type_string) is Capability.POSITIONAL


def test_sdn_module_is_non_positional() -> None:
    """CAP-05: this is how Irismo actually presents itself.

    The gateway reports the 1811129 bridge module, so the string 'Irismo' never
    appears on the wire. All 9 Irismo motors on the live bus report exactly this.
    """
    assert classify_type("SDN Module") is Capability.NON_POSITIONAL


@pytest.mark.parametrize("type_string", ["sdn module", "SDN MODULE", "  SDN Module  "])
def test_sdn_module_matching_is_forgiving(type_string: str) -> None:
    assert classify_type(type_string) is Capability.NON_POSITIONAL


def test_irismo_kept_as_an_alias() -> None:
    """Never observed, but harmless to accept in case other firmware reports it."""
    assert classify_type("Irismo 35") is Capability.NON_POSITIONAL


@pytest.mark.parametrize("type_string", ["Glydea", "LSU 50", "Sonesse 50AC"])
def test_other_known_positional_families(type_string: str) -> None:
    assert classify_type(type_string) is Capability.POSITIONAL


@pytest.mark.parametrize("type_string", ["Something New", "", None, "   "])
def test_unrecognised_types_are_unknown_not_positional(type_string: str | None) -> None:
    """Unknown hardware must never be assumed position-capable.

    Assuming capability is the exact bug this project exists to fix: it is what
    puts a dead slider on an Irismo. UNKNOWN triggers a live position probe
    instead of a guess.
    """
    assert classify_type(type_string) is Capability.UNKNOWN


# ---------------------------------------------------------------------------
# Position parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw", [False, True])
def test_bool_is_never_a_position(raw: bool) -> None:
    """CAP-04: bool subclasses int in Python, so isinstance(False, int) is True.

    The gateway really does reply {"result": false} for a position-capable
    Sonesse 30 whose position is currently unknown. A naive numeric check reads
    that as position 0 -- i.e. 'fully closed' -- which would be a visible lie.
    """
    assert parse_position(raw) is None


@pytest.mark.parametrize(("raw", "expected"), [(0, 0), (100, 100), (50, 50), (37.0, 37)])
def test_numeric_positions_pass_through(raw: object, expected: int) -> None:
    assert parse_position(raw) == expected


@pytest.mark.parametrize("raw", [None, "50", [], {}, -1, 101])
def test_non_numeric_and_out_of_range_are_unknown(raw: object) -> None:
    assert parse_position(raw) is None


# ---------------------------------------------------------------------------
# Group addressing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("index", "group_id"),
    [(1, "010101"), (6, "010106"), (12, "01010C"), (18, "010112"), (25, "010119")],
)
def test_group_id_round_trip(index: int, group_id: str) -> None:
    """Formula verified against all 24 member-bearing groups on the live bus."""
    assert group_id_for_index(index) == group_id
    assert group_index_for_id(group_id) == index


def test_group_index_is_case_insensitive() -> None:
    assert group_index_for_id("01010c") == 12


@pytest.mark.parametrize("group_id", ["", "0101", "999999", "nonsense", None])
def test_malformed_group_ids_return_none(group_id: str | None) -> None:
    assert group_index_for_id(group_id) is None


def test_all_group_constant_matches_index_one() -> None:
    """Group 1 is 'ALL'. It is a broadcast with no stored membership, and the
    owner chose to omit it, so discovery needs to recognise and skip it."""
    assert group_id_for_index(1) == ALL_GROUP_ID


# ---------------------------------------------------------------------------
# Name uniqueness
# ---------------------------------------------------------------------------


def test_duplicate_names_are_disambiguated() -> None:
    """Entity IDs must never collide, even if the gateway's labels do.

    Synthetic input. No duplicate exists on the reference bus -- an earlier
    capture appeared to show one, but the gateway had briefly reported a stale
    name for a node whose group membership already said otherwise. The guard is
    kept because nothing stops an installer from labelling two motors
    identically, and a collision would silently drop an entity.
    """
    names = unique_slug_names(
        [("AAA111", "Bedroom Shade"), ("BBB222", "Bedroom Shade"), ("CCC333", "Bedroom Blackout")]
    )
    assert len(set(names.values())) == 3
    assert names["CCC333"] == "Bedroom Blackout"
    assert names["AAA111"] != names["BBB222"]
    assert all("Bedroom" in n for n in names.values())


def test_unique_names_are_left_alone() -> None:
    names = unique_slug_names([("A", "RoomB SH 1"), ("B", "RoomB SH 2")])
    assert names == {"A": "RoomB SH 1", "B": "RoomB SH 2"}


def test_missing_names_fall_back_to_node_id() -> None:
    names = unique_slug_names([("40FCFC", None), ("40FD76", "")])
    assert names["40FCFC"] == "40FCFC"
    assert names["40FD76"] == "40FD76"


# ---------------------------------------------------------------------------
# Name vs group cross-check
# ---------------------------------------------------------------------------


def _groups(*pairs: tuple[str, str]) -> dict[str, GroupInfo]:
    return {gid: GroupInfo(group_id=gid, index=int(gid[4:], 16), name=name) for gid, name in pairs}


REAL_GROUPS = _groups(
    ("010102", "RoomA B/O"),
    ("010103", "RoomA SH"),
    ("010105", "RoomB SH"),
    ("01010A", "RoomI SH"),
    ("010112", "RoomD SH"),
)


def _node(node_id: str, name: str, group: str) -> Node:
    return Node(node_id=node_id, name=name, groups=[group])


def test_a_name_pointing_at_another_group_is_flagged() -> None:
    """The real case this exists for.

    Node 136E33 once reported the name "RoomA B/O 2" while sitting in the
    "RoomA SH" group. Both facts were in the captured data and nothing
    compared them, so a false "duplicate name" finding was built on top.
    """
    conflicts = find_name_group_conflicts(
        [_node("136E33", "RoomA B/O 2", "010103")], REAL_GROUPS
    )

    assert len(conflicts) == 1
    assert conflicts[0].node_id == "136E33"
    assert conflicts[0].own_group == "RoomA SH"
    assert conflicts[0].suggested_group == "RoomA B/O"


def test_whitespace_differences_are_not_flagged() -> None:
    """ "RoomI SH 1" in the "RoomI SH" group is legitimate.

    Six real Irismo motors are labelled this way; warning about them would be
    noise that trains you to ignore the warning.
    """
    conflicts = find_name_group_conflicts(
        [_node("40FD76", "RoomI SH 1", "01010A")], REAL_GROUPS
    )
    assert conflicts == []


def test_a_name_resembling_no_other_group_is_not_flagged() -> None:
    """ "RoomD Hall SH" in the "RoomD SH" group differs, but harmlessly.

    It matches no *other* group, so there is nothing to suspect.
    """
    conflicts = find_name_group_conflicts(
        [_node("40FCFC", "RoomD Hall SH", "010112")], REAL_GROUPS
    )
    assert conflicts == []


def test_a_consistent_name_is_not_flagged() -> None:
    conflicts = find_name_group_conflicts([_node("07752B", "RoomB SH 1", "010105")], REAL_GROUPS)
    assert conflicts == []


def test_nodes_without_a_name_or_group_are_skipped() -> None:
    conflicts = find_name_group_conflicts(
        [
            Node(node_id="AAA", name=None, groups=["010105"]),
            Node(node_id="BBB", name="RoomB SH 9", groups=[]),
        ],
        REAL_GROUPS,
    )
    assert conflicts == []


def test_group_id_case_does_not_matter() -> None:
    """Group IDs appear in both cases across the gateway's replies."""
    conflicts = find_name_group_conflicts(
        [_node("136E33", "RoomA B/O 2", "01010a".upper())], REAL_GROUPS
    )
    # 01010A is RoomI SH, so the RoomA B/O name is still a conflict.
    assert len(conflicts) == 1


def test_the_real_bus_produces_no_warnings(bus_inventory: dict) -> None:
    """The current fleet must be quiet, or the check is useless in practice."""
    nodes = [
        Node(node_id=n["node_id"], name=n["name"], groups=n["groups"])
        for n in bus_inventory["nodes"]
    ]
    groups: dict[str, GroupInfo] = {}
    names = {
        2: "RoomA B/O",
        3: "RoomA SH",
        4: "RoomB B/O",
        5: "RoomB SH",
        6: "RoomG B/O",
        7: "RoomG SH",
        8: "RoomH SH",
        9: "RoomI B/O",
        10: "RoomI SH",
        11: "RoomJ B/O",
        12: "RoomJ SH",
        13: "RoomL B/O",
        14: "RoomL SH",
        15: "RoomM B/O",
        16: "RoomM SH",
        17: "RoomC B/O",
        18: "RoomD SH",
        19: "RoomE Bath SH",
        20: "RoomE Bed B/O",
        21: "RoomE Bed SH",
        22: "RoomF Bath SH",
        23: "RoomF Bed B/O",
        24: "RoomF Bed SH",
        25: "RoomK SH",
    }
    for index, name in names.items():
        gid = group_id_for_index(index)
        groups[gid] = GroupInfo(group_id=gid, index=index, name=name)

    assert find_name_group_conflicts(nodes, groups) == []


# ---------------------------------------------------------------------------
# Whole-bus consistency, replayed from the captured inventory
# ---------------------------------------------------------------------------


def test_classifier_against_the_real_bus(bus_inventory: dict) -> None:
    """The 49 real nodes must split exactly 40 positional / 9 non-positional."""
    counts: dict[Capability, int] = {}
    for node in bus_inventory["nodes"]:
        cap = classify_type(node["type"])
        counts[cap] = counts.get(cap, 0) + 1

    assert counts.get(Capability.POSITIONAL) == 40
    assert counts.get(Capability.NON_POSITIONAL) == 9
    assert counts.get(Capability.UNKNOWN, 0) == 0


def test_every_sdn_module_node_refused_position(bus_inventory: dict) -> None:
    """Cross-check the classifier against what the hardware actually did."""
    for node in bus_inventory["nodes"]:
        if node["type"] == "SDN Module":
            assert parse_position(node["position"]) is None
            assert node["position_error"] is not None


def test_the_false_position_node_keeps_its_capability(bus_inventory: dict) -> None:
    """CAP-06: 07753E is a Sonesse 30 that replies false.

    It stays POSITIONAL -- capability comes from the type string. Demoting it on
    a bad reading would make its supported_features flap between polls.
    """
    node = next(n for n in bus_inventory["nodes"] if n["node_id"] == "07753E")
    assert node["position"] is False
    assert classify_type(node["type"]) is Capability.POSITIONAL
    assert parse_position(node["position"]) is None


# ---------------------------------------------------------------------------
# CAP-02: manual capability override
# ---------------------------------------------------------------------------
#
# Detection has been right on all 49 nodes of the reference bus, so this exists
# for other people's hardware -- a motor type the classifier has never seen.
# The override is the escape hatch, which means its failure modes matter more
# than its happy path: a bad value in the options must never break the entity.


def test_no_override_leaves_detection_untouched() -> None:
    assert (
        apply_capability_override(Capability.NON_POSITIONAL, OVERRIDE_AUTO)
        is Capability.NON_POSITIONAL
    )
    assert apply_capability_override(Capability.POSITIONAL, None) is Capability.POSITIONAL


def test_a_motor_can_be_forced_positional() -> None:
    """The case that matters: hardware that reports position but is classified
    non-positional because its type string is unrecognised."""
    assert (
        apply_capability_override(Capability.NON_POSITIONAL, Capability.POSITIONAL)
        is Capability.POSITIONAL
    )


def test_a_motor_can_be_forced_non_positional() -> None:
    """The inverse: a motor whose type string looks positional but which has no
    working feedback, leaving a slider that never resolves."""
    assert (
        apply_capability_override(Capability.POSITIONAL, Capability.NON_POSITIONAL)
        is Capability.NON_POSITIONAL
    )


def test_an_unknown_node_can_be_resolved_by_hand() -> None:
    """UNKNOWN is precisely the state a human is best placed to settle."""
    assert (
        apply_capability_override(Capability.UNKNOWN, Capability.POSITIONAL)
        is Capability.POSITIONAL
    )


@pytest.mark.parametrize("garbage", ["", "  ", "yes", "POSITIONAL", "unknown", 7, None, True])
def test_a_meaningless_override_falls_back_to_detection(garbage: object) -> None:
    """Options survive downgrades and hand-editing, so a value that is not a
    real capability must be ignored rather than raise. `unknown` is included
    deliberately: forcing a node to UNKNOWN would strip its controls, which is
    never what someone reaching for this setting wants.
    """
    assert apply_capability_override(Capability.POSITIONAL, garbage) is Capability.POSITIONAL
