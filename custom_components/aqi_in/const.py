"""Constants for the AQI.in integration."""

from __future__ import annotations

DOMAIN = "aqi_in"

# Observed upstream cadence is roughly every 10 minutes (station `updated_at`
# stepped 00:01 -> 00:11 -> 00:21 -> 00:31), so match it rather than
# under-sampling and drifting out of phase with the source.
DEFAULT_SCAN_INTERVAL = 600

CONF_LOCATION_ID = "location_id"
CONF_SLUG = "slug"
CONF_STATION_NAME = "station_name"

# Account entries store credentials instead of a station.
CONF_USER_ID = "user_id"
