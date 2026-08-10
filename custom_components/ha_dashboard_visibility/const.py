"""Constants for Dashboard Visibility Manager."""
from __future__ import annotations

DOMAIN = "ha_dashboard_visibility"

CARD_FILENAME = "dashboard-visibility-card.js"
STATIC_URL_BASE = f"/{DOMAIN}_static"

# Data key used within HA's per-user frontend storage for sidebar
# customisation (order/hidden panels) - same key the native "Change
# order and hide items from the sidebar" profile feature uses.
SIDEBAR_USER_DATA_KEY = "sidebar"
