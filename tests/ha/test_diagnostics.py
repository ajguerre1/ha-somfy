"""Diagnostics must stay secret-free.

The dump exists to make bug reports cheap, which means it is meant to be
pasted into a public issue. Anything secret that reaches it is published.
"""

from __future__ import annotations

import json

from custom_components.ha_somfy.const import CONF_WEB_PASSWORD, DOMAIN
from custom_components.ha_somfy.diagnostics import async_get_config_entry_diagnostics


async def test_no_credential_survives_into_the_dump(hass, coordinator) -> None:
    """`entry.options` used to be copied verbatim, which was safe only for as
    long as nothing secret lived there. The web password now does.
    """
    entry = coordinator.config_entry
    hass.config_entries.async_update_entry(entry, options={CONF_WEB_PASSWORD: "hunter2"})
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    dump = json.dumps(await async_get_config_entry_diagnostics(hass, entry))

    assert "hunter2" not in dump
    # The telnet credentials were already redacted; keep it that way.
    assert "secret" not in dump


async def test_the_dump_still_explains_the_bus(hass, coordinator) -> None:
    """Redaction must not gut the thing's purpose."""
    entry = coordinator.config_entry
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    dump = await async_get_config_entry_diagnostics(hass, entry)

    assert dump["summary"]["node_count"] == 3
    assert dump["summary"]["type_histogram"]["SDN Module"] == 1
    assert any(node["capability"] == "non_positional" for node in dump["nodes"])
