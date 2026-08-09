"""Dashboard Visibility Manager.

Provides a Lovelace card that lets an admin control, per user, which
dashboards show up in that user's sidebar - without having to log in
as that user or open per-view visibility dialogs one by one.

Technical approach: dashboards that are registered as frontend panels
of component "lovelace" are listed. For each (user, dashboard) pair we
read/write the SAME storage Home Assistant's own frontend uses for the
"Change order and hide items from the sidebar" feature in the user
profile (storage key "frontend.user_data_{user_id}", data key
"sidebar" -> {"panelOrder": [...], "hiddenPanels": [...]}). This means
changes take effect immediately (next sidebar refresh / reload), no
restart required, and stay fully compatible with HA's native per-user
sidebar customisation - our card and the native profile editor are
just two doors into the same room.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.components.http import StaticPathConfig
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CoreState, HomeAssistant, callback
from homeassistant.helpers.storage import Store

from .const import (
    CARD_FILENAME,
    DOMAIN,
    FRONTEND_USER_DATA_KEY_FMT,
    FRONTEND_USER_DATA_VERSION,
    LOVELACE_COMPONENT_NAME,
    SIDEBAR_USER_DATA_KEY,
    STATIC_URL_BASE,
)

_LOGGER = logging.getLogger(__name__)

LOVELACE_RESOURCES_STORAGE_KEY = "lovelace_resources"
LOVELACE_RESOURCES_STORAGE_VERSION = 1


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Dashboard Visibility Manager from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    await _async_register_static_path(hass)
    await _async_register_lovelace_resource(hass)

    websocket_api.async_register_command(hass, websocket_get_data)
    websocket_api.async_register_command(hass, websocket_set_hidden)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    hass.data.pop(DOMAIN, None)
    return True


async def _async_register_static_path(hass: HomeAssistant) -> None:
    """Serve the card's JavaScript file."""
    frontend_dir = Path(__file__).parent / "frontend"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(STATIC_URL_BASE, str(frontend_dir), cache_headers=False)]
    )


async def _async_register_lovelace_resource(hass: HomeAssistant) -> None:
    """Make sure the card's JS module is registered as a Lovelace resource.

    Written directly to the lovelace_resources storage so it works
    regardless of whether dashboards are in storage or YAML mode, and
    without requiring the user to add the resource manually via
    Settings -> Dashboards -> Resources.
    """
    url = f"{STATIC_URL_BASE}/{CARD_FILENAME}"
    store: Store = Store(
        hass, LOVELACE_RESOURCES_STORAGE_VERSION, LOVELACE_RESOURCES_STORAGE_KEY
    )
    data = await store.async_load()
    if data is None:
        data = {"items": []}
    items = data.setdefault("items", [])

    if any(item.get("url") == url for item in items):
        return

    next_id = str(
        max((int(item["id"]) for item in items if str(item.get("id", "")).isdigit()), default=0)
        + 1
    )
    items.append({"id": next_id, "type": "module", "url": url})

    async def _register_when_ready(*_: Any) -> None:
        await store.async_save(data)
        _LOGGER.debug("Registered Lovelace resource %s", url)

    if hass.state is CoreState.running:
        await _register_when_ready()
    else:
        hass.bus.async_listen_once("homeassistant_started", _register_when_ready)


def _get_dashboards(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Return all dashboards registered as lovelace frontend panels."""
    panels: dict[str, Any] = hass.data.get("frontend_panels", {})
    dashboards = []
    for url_path, panel in panels.items():
        if getattr(panel, "component_name", None) != LOVELACE_COMPONENT_NAME:
            continue
        dashboards.append(
            {
                "url_path": url_path,
                "title": panel.sidebar_title or url_path,
                "icon": panel.sidebar_icon,
                "require_admin": panel.require_admin,
            }
        )
    dashboards.sort(key=lambda d: d["title"].lower())
    return dashboards


def _sidebar_store(hass: HomeAssistant, user_id: str) -> Store:
    key = FRONTEND_USER_DATA_KEY_FMT.format(user_id=user_id)
    return Store(hass, FRONTEND_USER_DATA_VERSION, key)


async def _async_get_hidden_panels(hass: HomeAssistant, user_id: str) -> list[str]:
    store = _sidebar_store(hass, user_id)
    data = await store.async_load()
    if not data:
        return []
    sidebar = data.get(SIDEBAR_USER_DATA_KEY) or {}
    hidden = sidebar.get("hiddenPanels")
    if isinstance(hidden, list):
        return list(hidden)
    return []


async def _async_set_hidden_panel(
    hass: HomeAssistant, user_id: str, url_path: str, hidden: bool
) -> None:
    """Add or remove a single dashboard from a user's hiddenPanels list.

    Only touches hiddenPanels - panelOrder and any other keys already
    stored for the user (including other, unrelated frontend user_data
    such as onboarding flags) are preserved as-is.
    """
    store = _sidebar_store(hass, user_id)
    data = await store.async_load()
    if not isinstance(data, dict):
        data = {}
    sidebar = dict(data.get(SIDEBAR_USER_DATA_KEY) or {})
    hidden_panels = list(sidebar.get("hiddenPanels") or [])

    if hidden and url_path not in hidden_panels:
        hidden_panels.append(url_path)
    elif not hidden and url_path in hidden_panels:
        hidden_panels.remove(url_path)
    else:
        return  # no change needed

    sidebar["hiddenPanels"] = hidden_panels
    sidebar.setdefault("panelOrder", [])
    data[SIDEBAR_USER_DATA_KEY] = sidebar
    await store.async_save(data)


@websocket_api.websocket_command({"type": f"{DOMAIN}/get_data"})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_get_data(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return dashboards, users and the current visibility matrix."""
    dashboards = _get_dashboards(hass)
    users = [
        {"id": user.id, "name": user.name, "is_admin": user.is_admin}
        for user in await hass.auth.async_get_users()
        if not user.system_generated
    ]

    matrix: dict[str, dict[str, bool]] = {}
    for user in users:
        hidden_panels = await _async_get_hidden_panels(hass, user["id"])
        matrix[user["id"]] = {
            dash["url_path"]: dash["url_path"] in hidden_panels for dash in dashboards
        }

    connection.send_result(
        msg["id"],
        {"dashboards": dashboards, "users": users, "matrix": matrix},
    )


@websocket_api.websocket_command(
    {
        "type": f"{DOMAIN}/set_hidden",
        vol.Required("user_id"): str,
        vol.Required("url_path"): str,
        vol.Required("hidden"): bool,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_set_hidden(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Show or hide one dashboard for one user."""
    await _async_set_hidden_panel(hass, msg["user_id"], msg["url_path"], msg["hidden"])
    connection.send_result(msg["id"], {"success": True})
