"""Capability classification and value parsing.

Every test here exists because the live bus proved it necessary. These are not
hypothetical edge cases -- each one maps to something observed on 2026-07-29.
"""

from __future__ import annotations

import pytest

from custom_components.ha_somfy.uai.models import (
    ALL_GROUP_ID,
    Capability,
    classify_type,
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
    """HW-03: nodes 136E33 and 136E3F are both named 'RoomA B/O 2'.

    Entity IDs must never collide, even if the gateway's labels do.
    """
    names = unique_slug_names(
        [("136E33", "RoomA B/O 2"), ("136E3F", "RoomA B/O 2"), ("136E38", "RoomA B/O 1")]
    )
    assert len(set(names.values())) == 3
    assert names["136E38"] == "RoomA B/O 1"
    assert names["136E33"] != names["136E3F"]
    assert all("RoomA" in n for n in names.values())


def test_unique_names_are_left_alone() -> None:
    names = unique_slug_names([("A", "RoomB SH 1"), ("B", "RoomB SH 2")])
    assert names == {"A": "RoomB SH 1", "B": "RoomB SH 2"}


def test_missing_names_fall_back_to_node_id() -> None:
    names = unique_slug_names([("40FCFC", None), ("40FD76", "")])
    assert names["40FCFC"] == "40FCFC"
    assert names["40FD76"] == "40FD76"


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
