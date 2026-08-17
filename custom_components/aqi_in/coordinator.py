"""Data update coordinator for AQI.in."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AqiInAccountClient, AqiInAuthError, AqiInClient, AqiInError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class AqiInCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch one station's live readings."""

    def __init__(self, hass: HomeAssistant, client: AqiInClient, slug: str) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.client = client
        self.slug = slug

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch the station payload.

        Auth failures map to UpdateFailed rather than ConfigEntryAuthFailed:
        there are no user credentials to re-enter, so a reauth prompt would be a
        dead end. Token recovery happens inside the client.
        """
        try:
            return await self.client.async_station(self.slug)
        except AqiInError as err:
            raise UpdateFailed(f"Cannot update {self.slug}: {err}") from err


class AqiInAccountCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch every monitor on an AQI.in account, keyed by serial number.

    The account API carries no weather block, so each device is enriched from
    its public station listing. A monitor's public `locationId` is its serial
    number, which makes that match exact rather than a guess by proximity.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        client: AqiInAccountClient,
        public_client: AqiInClient,
    ) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.client = client
        self.public_client = public_client
        # serial -> public slug, or None for a monitor that isn't published.
        self._public_slugs: dict[str, str | None] = {}

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch all devices, then fold in public weather where available.

        Unlike the public station flow, these entries hold real credentials, so
        an auth failure can be fixed by the user — raise ConfigEntryAuthFailed
        to trigger the reauth prompt.
        """
        try:
            devices = await self.client.async_devices()
        except AqiInAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except AqiInError as err:
            raise UpdateFailed(f"Cannot update AQI.in devices: {err}") from err

        data = {str(device["serialNo"]): device for device in devices}
        for serial, device in data.items():
            await self._async_add_weather(serial, device)
        return data

    async def _async_add_weather(self, serial: str, device: dict[str, Any]) -> None:
        """Attach the public station's weather to a device, if it has one.

        Weather is a bonus on top of the device's own readings, so every failure
        here is swallowed — it must never take the whole update down.
        """
        try:
            slug = await self._async_public_slug(serial, device)
            if slug is None:
                return
            station = await self.public_client.async_station(slug)
        except AqiInError as err:
            _LOGGER.debug("No public weather for %s: %s", serial, err)
            return

        if (weather := station.get("weather")) is not None:
            device["weather"] = weather

    async def _async_public_slug(
        self, serial: str, device: dict[str, Any]
    ) -> str | None:
        """Find the public slug for a monitor, looking it up once."""
        if serial in self._public_slugs:
            return self._public_slugs[serial]

        try:
            latitude = float(device["adddevicelat"])
            longitude = float(device["adddevicelon"])
        except (KeyError, TypeError, ValueError):
            self._public_slugs[serial] = None
            return None

        # Let API errors propagate so a transient failure isn't cached as
        # "this monitor is not public".
        stations = await self.public_client.async_nearest_stations(latitude, longitude)
        slug = next(
            (
                station["location_slug"]
                for station in stations
                if str(station.get("locationId")) == serial
            ),
            None,
        )
        self._public_slugs[serial] = slug
        return slug
