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
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_CAPABILITY,
    CONF_CAPABILITY_OVERRIDES,
    CONF_MOTOR,
    CONF_POLL_INTERVAL,
    CONF_WEB_PASSWORD,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
)
from .uai.client import DEFAULT_PORT, UaiAuthError, UaiClient, UaiError
from .uai.models import OVERRIDE_AUTO, Capability, unique_slug_names

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Optional(CONF_USERNAME, default=""): str,
        vol.Optional(CONF_PASSWORD, default=""): str,
        # Optional, and a *different* credential from the telnet one above:
        # this is the web interface password. Without it, motors that telnet
        # cannot read -- Irismo behind an SDN bridge -- report no state at all.
        vol.Optional(CONF_WEB_PASSWORD, default=""): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
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
    """Adjust polling, and correct a motor that was classified wrongly.

    Every step below takes exactly one positional parameter -- see this
    module's docstring for the bug that rule exists to prevent.
    """

    def __init__(self) -> None:
        self._motor: str | None = None

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="init", menu_options=["polling", "capability", "web"])

    # -- web interface credential ------------------------------------------

    async def async_step_web(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Set or clear the web interface password.

        Kept in the options rather than the entry data so an integration set up
        before this existed can gain the feature without being removed and
        re-added. Submitting an empty box clears it and turns the feature off.
        """
        if user_input is not None:
            return self._save(
                {CONF_WEB_PASSWORD: str(user_input.get(CONF_WEB_PASSWORD, "")).strip()}
            )

        schema = vol.Schema(
            {
                vol.Optional(CONF_WEB_PASSWORD, default=""): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                )
            }
        )
        return self.async_show_form(
            step_id="web",
            data_schema=schema,
            description_placeholders={"state": "set" if self._web_password() else "not set"},
        )

    def _web_password(self) -> str:
        entry = self.config_entry
        return str(entry.options.get(CONF_WEB_PASSWORD) or entry.data.get(CONF_WEB_PASSWORD) or "")

    # -- polling -----------------------------------------------------------

    async def async_step_polling(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self._save({CONF_POLL_INTERVAL: int(user_input[CONF_POLL_INTERVAL])})

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
        return self.async_show_form(step_id="polling", data_schema=schema)

    # -- capability override -----------------------------------------------

    async def async_step_capability(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick which motor to correct.

        The list comes from discovery rather than a text box: hand-typing node
        IDs is precisely the failure mode this integration was written against.
        """
        if user_input is not None:
            self._motor = user_input[CONF_MOTOR]
            return await self.async_step_motor()

        motors = self._motor_options()
        if not motors:
            return self.async_abort(reason="no_motors")

        schema = vol.Schema(
            {
                vol.Required(CONF_MOTOR): SelectSelector(
                    SelectSelectorConfig(options=motors, mode=SelectSelectorMode.DROPDOWN)
                )
            }
        )
        return self.async_show_form(step_id="capability", data_schema=schema)

    async def async_step_motor(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Set, or clear, one motor's override."""
        assert self._motor is not None

        if user_input is not None:
            return self._save_override(self._motor, user_input[CONF_CAPABILITY])

        current = self._overrides().get(self._motor, OVERRIDE_AUTO)
        schema = vol.Schema(
            {
                vol.Required(CONF_CAPABILITY, default=current): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            OVERRIDE_AUTO,
                            Capability.POSITIONAL.value,
                            Capability.NON_POSITIONAL.value,
                        ],
                        translation_key="capability",
                        mode=SelectSelectorMode.LIST,
                    )
                )
            }
        )
        return self.async_show_form(
            step_id="motor",
            data_schema=schema,
            description_placeholders={"motor": self._motor_label(self._motor)},
        )

    # -- helpers -----------------------------------------------------------

    def _coordinator(self) -> Any | None:
        return self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)

    def _motor_options(self) -> list[dict[str, str]]:
        coordinator = self._coordinator()
        if coordinator is None:
            return []
        names = unique_slug_names(
            [(node.node_id, node.name) for node in coordinator.nodes.values()]
        )
        return [
            {
                "value": node.node_id,
                "label": f"{names[node.node_id]} ({node.type_string or 'unknown type'})",
            }
            for node in coordinator.nodes.values()
        ]

    def _motor_label(self, node_id: str) -> str:
        for option in self._motor_options():
            if option["value"] == node_id:
                return option["label"]
        return node_id

    def _overrides(self) -> dict[str, str]:
        stored = self.config_entry.options.get(CONF_CAPABILITY_OVERRIDES)
        return dict(stored) if isinstance(stored, dict) else {}

    def _save_override(self, node_id: str, capability: str) -> ConfigFlowResult:
        overrides = self._overrides()
        if capability == OVERRIDE_AUTO:
            # Clear it rather than storing "auto", so returning to automatic
            # leaves no trace to resurface as the current setting later.
            overrides.pop(node_id, None)
        else:
            overrides[node_id] = capability
        return self._save({CONF_CAPABILITY_OVERRIDES: overrides})

    def _save(self, changes: dict[str, Any]) -> ConfigFlowResult:
        """Merge into the existing options.

        `async_create_entry` replaces the options dict wholesale, so writing
        only the section just edited would silently discard the other one --
        setting a capability override would quietly reset the poll interval.
        """
        options = dict(self.config_entry.options)
        options.update(changes)
        return self.async_create_entry(data=options)
