"""Dashboard Visibility Manager.

Provides a Lovelace card that lets an admin control, per user, which
dashboards show up in that user's sidebar - without having to log in
as that user or open per-view visibility dialogs one by one.

Card/resource registration follows the "Developer Guide: Embedded
Lovelace Card in a Home Assistant Integration" pattern: registration
happens once in async_setup() (not async_setup_entry), and the
Lovelace resource is written through the REAL, running lovelace
object (hass.data["lovelace"].resources) rather than a separate,
raw Store("lovelace_resources") instance. Lovelace's own
ResourceStorageCollection is lazy-loaded; writing to a second, raw
Store for the same storage key can race with it and get silently
overwritten once the real collection saves its own (stale) in-memory
state. Going through resources.async_create_item()/async_update_item()
avoids that entirely.

Per-user sidebar visibility (which dashboards are hidden for whom) is
read/written via async_user_store() from
homeassistant.components.frontend.storage - the exact same cached
per-user store Home Assistant's own frontend uses for the "Change
order and hide items from the sidebar" feature in the user profile
(data key "sidebar" -> {"panelOrder": [...], "hiddenPanels": [...]}).
HA keeps a per-user UserStore cached in memory once loaded; a raw
file write to frontend.user_data_{user_id} would be invisible to a
running instance until that cache is evicted (effectively: until the
next HA restart). async_user_store() updates the live cache too, so
changes take effect immediately.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.components.http import StaticPathConfig
from homeassistant.components import websocket_api
from homeassistant.components.frontend.storage import async_user_store
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.typing import ConfigType

from .const import (
    CARD_FILENAME,
    DOMAIN,
    SIDEBAR_USER_DATA_KEY,
    STATIC_URL_BASE,
)

_LOGGER = logging.getLogger(__name__)

RESOURCE_RETRY_SECONDS = 5


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration (runs once, regardless of config entries)."""
    await _async_register_card(hass)

    websocket_api.async_register_command(hass, websocket_get_data)
    websocket_api.async_register_command(hass, websocket_set_hidden)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Dashboard Visibility Manager from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    hass.data.pop(DOMAIN, None)
    return True


def _read_manifest_version() -> str:
    """Read the version from manifest.json (sync, run in executor)."""
    manifest_path = Path(__file__).parent / "manifest.json"
    try:
        with manifest_path.open(encoding="utf-8") as f:
            return json.load(f).get("version", "0")
    except (OSError, json.JSONDecodeError):
        return "0"


async def _async_register_card(hass: HomeAssistant) -> None:
    """Serve the card's JS and register it as a Lovelace resource.

    Static path registration happens immediately (idempotent via
    try/except RuntimeError). The Lovelace resource registration is
    deferred until the real lovelace object's resource collection has
    finished loading, since it's lazy-loaded and not necessarily ready
    yet when async_setup() runs.
    """
    js_path = Path(__file__).parent / "frontend" / CARD_FILENAME
    resource_url_base = f"{STATIC_URL_BASE}/{CARD_FILENAME}"

    try:
        await hass.http.async_register_static_paths(
            [StaticPathConfig(resource_url_base, str(js_path), cache_headers=False)]
        )
    except RuntimeError:
        pass  # Route bereits registriert (z. B. nach Reload)

    version = await hass.async_add_executor_job(_read_manifest_version)
    resource_url = f"{resource_url_base}?v={version}"

    async def _register_resource(_now: Any = None) -> None:
        lovelace = hass.data.get("lovelace")
        if lovelace is None or getattr(lovelace, "mode", None) != "storage":
            # YAML-Modus: keine Auto-Registrierung möglich, User muss die
            # Ressource manuell im Dashboard-YAML eintragen.
            return

        resources = lovelace.resources
        if not resources.loaded:
            async_call_later(hass, RESOURCE_RETRY_SECONDS, _register_resource)
            return

        existing = next(
            (
                item
                for item in resources.async_items()
                if item["url"].split("?")[0] == resource_url_base
            ),
            None,
        )
        if existing is None:
            await resources.async_create_item({"res_type": "module", "url": resource_url})
            _LOGGER.info("Dashboard-Visibility-Karte als Lovelace-Ressource registriert.")
        elif existing["url"] != resource_url:
            await resources.async_update_item(
                existing["id"], {"res_type": "module", "url": resource_url}
            )
            _LOGGER.info("Dashboard-Visibility-Karte auf Version %s aktualisiert.", version)

    if hass.state is CoreState.running:
        hass.async_create_task(_register_resource())
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _register_resource)


def _panel_display_title(url_path: str, panel: Any) -> str:
    """Return a human-friendly title for a panel.

    Built-in system panels and some auto-generated dashboards don't
    always have a sidebar_title set (HA's frontend fills in a
    localized label at display time instead). Without a translation
    layer available here, fall back to something more readable than
    the raw url_path.
    """
    if panel.sidebar_title:
        return panel.sidebar_title
    if url_path == "lovelace":
        return "Übersicht (Standard-Dashboard)"
    return url_path.replace("-", " ").replace("_", " ").title()


def _get_dashboards(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Return all panels that Home Assistant considers sidebar-eligible.

    This includes user-created Lovelace dashboards as well as panels
    registered by integrations (e.g. Energy, Map, Calendar, To-do,
    Settings) and add-on/ingress panels - anything with show_in_sidebar
    True, since that's the same flag HA's own sidebar uses to decide
    what CAN appear there at all. A handful of purely technical panels
    that are never meant to show up (like the 404 fallback panel) are
    excluded explicitly. component_name is included so the card can
    group entries and show what kind of panel each one is.
    """
    panels: dict[str, Any] = hass.data.get("frontend_panels", {})
    excluded_url_paths = {
        "notfound",  # 404-Fallback, nie sinnvoll in der Sidebar
        "profile",  # eigenes Profil, immer über Avatar erreichbar, kein echtes Dashboard
        "_my_redirect",  # technischer Weiterleitungs-Mechanismus (my.home-assistant.io), keine eigene Seite
        "config",  # Häkchen hat keine Auswirkung auf die Sichtbarkeit (von Mirko bestätigt)
        "app",  # "App"-Eintrag, Häkchen hat keine Auswirkung auf die Sichtbarkeit (von Mirko bestätigt)
    }
    dashboards = []
    for url_path, panel in panels.items():
        if url_path in excluded_url_paths:
            continue
        if not getattr(panel, "show_in_sidebar", True):
            continue
        dashboards.append(
            {
                "url_path": url_path,
                "title": _panel_display_title(url_path, panel),
                "icon": panel.sidebar_icon,
                "require_admin": panel.require_admin,
                "component_name": getattr(panel, "component_name", "") or "",
            }
        )
    dashboards.sort(key=lambda d: (d["component_name"], d["title"].lower()))
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
