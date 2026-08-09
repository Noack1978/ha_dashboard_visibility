"""Constants for Dashboard Visibility Manager."""
from __future__ import annotations

DOMAIN = "ha_dashboard_visibility"

CARD_FILENAME = "dashboard-visibility-card.js"
STATIC_URL_BASE = f"/{DOMAIN}_static"

# Data key used within HA's per-user frontend storage for sidebar
# customisation (order/hidden panels) - same key the native "Change
# order and hide items from the sidebar" profile feature uses.
SIDEBAR_USER_DATA_KEY = "sidebar"

# Component name used by lovelace-managed dashboards when registered
# as a frontend panel. We only offer panels of this type as "dashboards"
# in the card (this excludes things like config, logbook, developer-tools).
LOVELACE_COMPONENT_NAME = "lovelace"
