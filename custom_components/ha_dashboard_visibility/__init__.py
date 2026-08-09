"""Dashboard Visibility Manager.

Provides a Lovelace card that lets an admin control, per user, which
dashboards show up in that user's sidebar - without having to log in
as that user or open per-view visibility dialogs one by one.

Technical approach: dashboards that are registered as frontend panels
of component "lovelace" are listed. For each (user, dashboard) pair we
read/write via async_user_store() from
homeassistant.components.frontend.storage - the exact same cached
per-user store Home Assistant's own frontend uses for the "Change
order and hide items from the sidebar" feature in the user profile
(data key "sidebar" -> {"panelOrder": [...], "hiddenPanels": [...]}).
Going through this function (rather than reading/writing the backing
Store file directly) matters: HA keeps a per-user UserStore cached in
memory once it's been loaded, and a raw file write would be invisible
to a running instance until that cache is evicted. Using
async_user_store() updates the live cache too, so changes take effect
immediately, no restart required, and stay fully compatible with HA's
native per-user sidebar customisation.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.components.http import StaticPathConfig
from homeassistant.components import websocket_api
from homeassistant.components.frontend.storage import async_user_store
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant, callback
from homeassistant.helpers.storage import Store

from .const import (
    CARD_FILENAME,
    DOMAIN,
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

    _async_register_card(hass)

    websocket_api.async_register_command(hass, websocket_get_data)
    websocket_api.async_register_command(hass, websocket_set_hidden)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    hass.data.pop(DOMAIN, None)
    return True


@callback
def _async_register_card(hass: HomeAssistant) -> None:
    """Serve the card's JS and register it as a Lovelace resource.

    Same pattern as ha-parcel-tracking: static path + resource-store
    write happen together in one deferred function, either right away
    (task) if HA is already fully running, or once EVENT_HOMEASSISTANT_STARTED
    fires (during a normal boot, config entries are set up before HA
    reaches the "running" state, so the module wouldn't be picked up by
    Lovelace's already-loaded resource collection otherwise).
    """
    static_url = f"{STATIC_URL_BASE}/{CARD_FILENAME}"
    js_path = Path(__file__).parent / "frontend" / CARD_FILENAME

    async def _register(_event: Any = None) -> None:
        try:
            await hass.http.async_register_static_paths(
                [StaticPathConfig(static_url, str(js_path), cache_headers=False)]
            )
        except RuntimeError:
            pass  # Route bereits registriert (z. B. nach Reload)

        store = Store(hass, LOVELACE_RESOURCES_STORAGE_VERSION, LOVELACE_RESOURCES_STORAGE_KEY)
        data = await store.async_load() or {"items": [], "deleted_items": []}
        if not any(r.get("url") == static_url for r in data.get("items", [])):
            data.setdefault("items", []).append(
                {"id": "ha_dashboard_visibility_card", "type": "module", "url": static_url}
            )
            await store.async_save(data)
            _LOGGER.info("Dashboard-Visibility-Karte als Lovelace-Ressource registriert.")

    if hass.state is CoreState.running:
        hass.async_create_task(_register())
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _register)


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


async def _async_get_hidden_panels(hass: HomeAssistant, user_id: str) -> list[str]:
    """Read hiddenPanels via HA's own cached UserStore (not a raw file read).

    Home Assistant keeps a per-user in-memory cache (UserStore, populated
    the first time anything - including the user's own browser - reads
    or writes their frontend user data). Reading the file directly on
    disk would miss any change that only exists in that cache, and
    writing directly to the file would be invisible to the running
    instance until the cache is evicted (effectively: until next HA
    restart). Going through async_user_store() guarantees we see/update
    the exact same data the frontend itself uses.
    """
    store = await async_user_store(hass, user_id)
    sidebar = store.data.get(SIDEBAR_USER_DATA_KEY) or {}
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
    such as onboarding flags) are preserved as-is. Uses async_user_store()
    so the change is written through HA's own cache: it takes effect
    immediately for a connected client (via the store's subscription
    mechanism) and is correctly seen on the next sidebar load, instead of
    only reaching the file on disk.
    """
    store = await async_user_store(hass, user_id)
    sidebar = dict(store.data.get(SIDEBAR_USER_DATA_KEY) or {})
    hidden_panels = list(sidebar.get("hiddenPanels") or [])

    if hidden and url_path not in hidden_panels:
        hidden_panels.append(url_path)
    elif not hidden and url_path in hidden_panels:
        hidden_panels.remove(url_path)
    else:
        return  # no change needed

    sidebar["hiddenPanels"] = hidden_panels
    sidebar.setdefault("panelOrder", [])
    await store.async_set_item(SIDEBAR_USER_DATA_KEY, sidebar)


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
