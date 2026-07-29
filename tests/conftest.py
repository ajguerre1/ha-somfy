"""Shared test setup.

The integration lives under custom_components/ so Home Assistant can load it in
place. Putting the repo root on sys.path lets tests import it as a normal
package without an install step.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(scope="session")
def wire_samples() -> dict:
    """Verbatim gateway replies captured from the live UAI+ on 2026-07-29."""
    return json.loads((FIXTURE_DIR / "wire_samples.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def bus_inventory() -> dict:
    """Full 49-node inventory captured from the live bus."""
    return json.loads((FIXTURE_DIR / "bus_inventory.json").read_text(encoding="utf-8"))
