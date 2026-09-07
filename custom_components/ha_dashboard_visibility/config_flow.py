"""Config Flow fuer Rezepte Import."""
from __future__ import annotations
from typing import Any
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
from . import DOMAIN, AGENT_ID_DEFAULT, LLMVISION_PROVIDER_DEFAULT, _PROMPT_BASE, _PROMPT_IMAGE

LLMVISION_PROVIDERS = ["Google", "OpenAI", "Anthropic", "Ollama", "Groq", "Custom OpenAI"]
PROMPT_MODES = [
    {"value": "standard", "label": "Standard (empfohlen)"},
    {"value": "custom",   "label": "Eigener Prompt"},
]


def _schema(defaults: dict) -> vol.Schema:
    prompt_mode = defaults.get("prompt_mode", "standard")
    custom      = defaults.get("custom_prompt", "")
    # Eigener Prompt mit Standard vorausfuellen wenn leer
    if not custom:
        custom = _PROMPT_BASE.strip()

    return vol.Schema({
        vol.Required(
            "conversation_agent",
            default=defaults.get("conversation_agent", AGENT_ID_DEFAULT),
        ): selector.TextSelector(),

        vol.Required(
            "llmvision_provider",
            default=defaults.get("llmvision_provider", LLMVISION_PROVIDER_DEFAULT),
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(options=LLMVISION_PROVIDERS)
        ),

        vol.Required(
            "prompt_mode",
            default=prompt_mode,
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(options=PROMPT_MODES)
        ),

        vol.Optional(
            "custom_prompt",
            default=custom,
        ): selector.TextSelector(
            selector.TextSelectorConfig(multiline=True)
        ),

        vol.Optional(
            "vision_api_key",
            default=defaults.get("vision_api_key", ""),
        ): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        ),

        vol.Optional(
            "vision_model",
            default=defaults.get("vision_model", "meta-llama/llama-4-maverick-17b-128e-instruct"),
        ): selector.TextSelector(),

        vol.Required(
            "image_prompt_mode",
            default=defaults.get("image_prompt_mode", "standard"),
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(options=[
                {"value": "standard", "label": "Standard (empfohlen)"},
                {"value": "custom",   "label": "Eigener Bild-Prompt"},
            ])
        ),

        vol.Optional(
            "custom_image_prompt",
            default=defaults.get("custom_image_prompt", "").strip() or _PROMPT_IMAGE.strip(),
        ): selector.TextSelector(
            selector.TextSelectorConfig(multiline=True)
        ),
    })


class RezepteImportConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Einrichtungs-Dialog."""
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title="Rezepte Import", data=user_input)
        return self.async_show_form(step_id="user", data_schema=_schema({}))

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Einstellungen nachtraeglich aendern."""
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            return self.async_update_reload_and_abort(
                entry,
                data=user_input,
                reason="reconfigure_successful",
            )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_schema(entry.data),
        )


class RezepteImportOptionsFlow(config_entries.OptionsFlowWithReload):
    """Fallback fuer aeltere HA-Versionen ohne Reconfigure-Support."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            self.hass.config_entries.async_update_entry(
                self.config_entry, data={**self.config_entry.data, **user_input}
            )
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=_schema(self.config_entry.data),
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        entry: config_entries.ConfigEntry,
    ) -> "RezepteImportOptionsFlow":
        return RezepteImportOptionsFlow()
