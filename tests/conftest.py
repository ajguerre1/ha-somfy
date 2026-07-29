"""Shared test setup.

The integration lives under custom_components/ so Home Assistant can load it in
place, and importing `custom_components.ha_somfy.uai.*` normally executes the
package's `__init__.py` -- which imports Home Assistant.

Home Assistant cannot be imported on Windows (`homeassistant.runner` imports
POSIX-only `fcntl`), so on a machine without it we install lightweight stub
parent packages. That lets the vendored client -- which has no Home Assistant
imports at all -- be tested anywhere, while CI on Linux imports the real thing
and additionally runs the HA-dependent tests under tests/ha/.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    import homeassistant  # noqa: F401

    HA_AVAILABLE = True
except ImportError:
    HA_AVAILABLE = False


def _install_stub_parents() -> None:
    """Expose custom_components.ha_somfy.* without running its __init__.py.

    The real __init__.py imports Home Assistant. Registering path-only module
    objects lets Python resolve the `uai` subpackage directly.
    """
    for name, path in (
        ("custom_components", REPO_ROOT / "custom_components"),
        ("custom_components.ha_somfy", REPO_ROOT / "custom_components" / "ha_somfy"),
    ):
        if name not in sys.modules:
            module = types.ModuleType(name)
            module.__path__ = [str(path)]  # type: ignore[attr-defined]
            sys.modules[name] = module


if not HA_AVAILABLE:
    _install_stub_parents()
    # Skip the HA-dependent suite rather than failing it. The directory itself
    # must be ignored, not just its files: tests/ha/conftest.py imports Home
    # Assistant and would be loaded during collection otherwise.
    collect_ignore = ["ha"]
    collect_ignore_glob = ["ha/*"]


@pytest.fixture(scope="session")
def wire_samples() -> dict:
    """Verbatim gateway replies captured from the live UAI+ on 2026-07-29."""
    return json.loads((FIXTURE_DIR / "wire_samples.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def bus_inventory() -> dict:
    """Full 49-node inventory captured from the live bus."""
    return json.loads((FIXTURE_DIR / "bus_inventory.json").read_text(encoding="utf-8"))
