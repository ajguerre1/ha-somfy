"""Config and options flow.

Two things here are deliberate corrections of defects in prior art:

1. Every step handler takes exactly ONE positional argument. Home Assistant
   always calls a step with the submitted user input as the first positional
   parameter, so a two-parameter signature binds the form data to the wrong
   name, leaves `user_input` permanently None, and the form loops forever. That
   is a real, filed bug in an existing UAI+ integration.
2. Validation actually authenticates and discovers. Merely opening a TCP socket
   proves nothing -- it succeeds with completely wrong credentials.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .const import (
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
)
from .uai.client import DEFAULT_PORT, UaiAuthError, UaiClient, UaiError
from .uai.models import Capability

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Optional(CONF_USERNAME, default=""): str,
        vol.Optional(CONF_PASSWORD, default=""): str,
    }
)


async def _validate(data: dict[str, Any]) -> dict[str, Any]:
    """Authenticate and enumerate the bus.

    Returns a summary used to confirm the entry, so the user sees what was found
    before committing rather than discovering an empty integration afterwards.
    """
    client = UaiClient(
        data[CONF_HOST],
        data.get(CONF_PORT, DEFAULT_PORT),
        data.get(CONF_USERNAME, ""),
        data.get(CONF_PASSWORD, ""),
    )
    try:
        await client.async_connect()
        nodes = await client.async_discover_nodes()
    finally:
        await client.async_disconnect()

    positional = sum(1 for n in nodes if n.capability is Capability.POSITIONAL)
    group_ids = {gid.upper() for node in nodes for gid in node.groups}
    return {
        "motor_count": len(nodes),
        "positional_count": positional,
        "non_positional_count": len(nodes) - positional,
        "group_count": len(group_ids),
    }


class SomfyConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._summary: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_HOST])
            self._abort_if_unique_id_configured()
            try:
                self._summary = await _validate(user_input)
            except UaiAuthError:
                errors["base"] = "invalid_auth"
            except UaiError:
                errors["base"] = "cannot_connect"
            except Exception:  # surfaced to the user as a generic form error
                _LOGGER.exception("Unexpected error validating the gateway")
                errors["base"] = "unknown"
            else:
                if self._summary["motor_count"] == 0:
                    errors["base"] = "no_motors"
                else:
                    self._data = dict(user_input)
                    return await self.async_step_confirm()

        return self.async_show_form(step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors)

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show what discovery found, then create the entry.

        NOTE the single positional parameter -- see this module's docstring.
        """
        if user_input is not None:
            return self.async_create_entry(
                title=f"Somfy UAI+ ({self._data[CONF_HOST]})", data=self._data
            )

        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            description_placeholders={
                "host": self._data[CONF_HOST],
                "motors": str(self._summary["motor_count"]),
                "positional": str(self._summary["positional_count"]),
                "non_positional": str(self._summary["non_positional_count"]),
                "groups": str(self._summary["group_count"]),
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SomfyOptionsFlow:
        return SomfyOptionsFlow()


class SomfyOptionsFlow(OptionsFlow):
    """Adjust polling behaviour after setup."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                data={CONF_POLL_INTERVAL: int(user_input[CONF_POLL_INTERVAL])}
            )

        current = self.config_entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
        schema = vol.Schema(
            {
                vol.Required(CONF_POLL_INTERVAL, default=current): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_POLL_INTERVAL,
                        max=MAX_POLL_INTERVAL,
                        step=5,
                        unit_of_measurement="seconds",
                        mode=NumberSelectorMode.BOX,
                    )
                )
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
