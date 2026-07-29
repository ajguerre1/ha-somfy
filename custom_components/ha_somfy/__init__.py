"""HA Somfy -- Home Assistant integration for the Somfy Connect UAI+ gateway.

Entry-point wiring (async_setup_entry / async_unload_entry) arrives in Phase 3.
This module is intentionally free of Home Assistant imports until then, so the
vendored `uai` client can be imported and tested on its own.
"""

from __future__ import annotations
