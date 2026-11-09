"""Constants for the AQI.in integration."""

from __future__ import annotations

DOMAIN = "aqi_in"

DEFAULT_SCAN_INTERVAL = 600  # Upstream refreshes about every 10 minutes.
LOCAL_SCAN_INTERVAL = 30

CONF_LOCATION_ID = "location_id"
CONF_SLUG = "slug"
CONF_STATION_NAME = "station_name"
