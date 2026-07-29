"""The probe must never be able to move a motor.

These are real blinds in an occupied home. The allowlist in probe_uai is the
only thing standing between a typo and a room full of shades slamming shut, so
it gets a test that fails loudly rather than a comment saying we were careful.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from probe_uai import UnsafeMethodError, assert_read_only  # noqa: E402

MUTATING_METHODS = [
    "sdn.move.up",
    "sdn.move.down",
    "sdn.move.stop",
    "sdn.move.to",
    "sdn.move.ip",
    "sdn.group.move.up",
    "sdn.set.position",
    "sdn.ctrl.moveto",
    "move.up",
]

UNKNOWN_METHODS = [
    "",
    "anything.else",
    "sdn.status.pingg",
    "SDN.STATUS.PING",  # case must not slip through
]

READ_ONLY_METHODS = [
    "sdn.status.ping",
    "sdn.status.info",
    "sdn.status.position",
    "sdn.group.get",
]


@pytest.mark.parametrize("method", MUTATING_METHODS)
def test_mutating_methods_are_refused(method: str) -> None:
    with pytest.raises(UnsafeMethodError):
        assert_read_only(method)


@pytest.mark.parametrize("method", UNKNOWN_METHODS)
def test_unknown_methods_fail_closed(method: str) -> None:
    """Anything not explicitly allowed is refused, rather than assumed safe."""
    with pytest.raises(UnsafeMethodError):
        assert_read_only(method)


@pytest.mark.parametrize("method", READ_ONLY_METHODS)
def test_read_only_methods_are_permitted(method: str) -> None:
    assert_read_only(method)


if __name__ == "__main__":
    # Standalone runner so this is checkable before pytest is installed.
    failures = 0
    for m in MUTATING_METHODS + UNKNOWN_METHODS:
        try:
            assert_read_only(m)
            print(f"  !! LEAKED: {m!r}")
            failures += 1
        except UnsafeMethodError:
            print(f"  refused : {m!r}")
    for m in READ_ONLY_METHODS:
        try:
            assert_read_only(m)
            print(f"  allowed : {m!r}")
        except UnsafeMethodError:
            print(f"  !! WRONGLY BLOCKED: {m!r}")
            failures += 1
    print(f"\n{'FAIL' if failures else 'PASS'}: {failures} problem(s)")
    raise SystemExit(1 if failures else 0)
