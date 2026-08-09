"""Constants for Dashboard Visibility Manager."""
from __future__ import annotations

DOMAIN = "ha_dashboard_visibility"

CARD_FILENAME = "dashboard-visibility-card.js"
STATIC_URL_BASE = f"/{DOMAIN}_static"

# Storage key format used natively by Home Assistant's own frontend
# component to persist each user's sidebar customisation (the same
# storage that "Change order and hide items from the sidebar" in the
# user profile writes to). We read/write this SAME storage so that our
# card and HA's native profile editor never disagree with each other.
FRONTEND_USER_DATA_KEY_FMT = "frontend.user_data_{user_id}"
FRONTEND_USER_DATA_VERSION = 1
SIDEBAR_USER_DATA_KEY = "sidebar"

# Component name used by lovelace-managed dashboards when registered
# as a frontend panel. We only offer panels of this type as "dashboards"
# in the card (this excludes things like config, logbook, developer-tools).
LOVELACE_COMPONENT_NAME = "lovelace"
