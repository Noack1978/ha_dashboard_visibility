"""Config flow for Dashboard Visibility Manager."""
from __future__ import annotations

from homeassistant.config_entries import ConfigFlow

from .const import DOMAIN


class DashboardVisibilityConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Dashboard Visibility Manager."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None):
        """Single-instance setup - nothing to configure."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            return self.async_create_entry(title="Dashboard Visibility Manager", data={})

        return self.async_show_form(step_id="user")
