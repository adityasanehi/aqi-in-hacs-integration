"""Config flow for the AQI.in integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import (
    CONF_EMAIL,
    CONF_LATITUDE,
    CONF_LOCATION,
    CONF_LONGITUDE,
    CONF_PASSWORD,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    LocationSelector,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    AqiInAccountClient,
    AqiInAuthError,
    AqiInClient,
    AqiInConnectionError,
    AqiInError,
)
from .const import (
    CONF_LOCATION_ID,
    CONF_SLUG,
    CONF_STATION_NAME,
    CONF_USER_ID,
    DOMAIN,
)

ACCOUNT_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): TextSelector(
            TextSelectorConfig(type=TextSelectorType.EMAIL, autocomplete="username")
        ),
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(
                type=TextSelectorType.PASSWORD, autocomplete="current-password"
            )
        ),
    }
)

_LOGGER = logging.getLogger(__name__)

CONF_STATION = "station"


def short_name(station: dict[str, Any]) -> str:
    """Return the leading part of a station's name.

    Station names arrive fully qualified, e.g.
    "Janpath, New Delhi, Delhi, India".
    """
    return str(station.get("station", "")).split(",")[0].strip() or "AQI.in station"


class AqiInConfigFlow(ConfigFlow, domain=DOMAIN):
    """Pick a monitoring station and create an entry for it."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise flow state."""
        self._stations: list[dict[str, Any]] = []

    async def _async_default_location(self) -> dict[str, float]:
        """Prefill coordinates from Home Assistant, falling back to IP lookup."""
        latitude = self.hass.config.latitude
        longitude = self.hass.config.longitude

        if not latitude and not longitude:
            client = AqiInClient(async_get_clientsession(self.hass))
            if (location := await client.async_ip_location()) is not None:
                latitude, longitude = location

        return {CONF_LATITUDE: latitude, CONF_LONGITUDE: longitude}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose between a public station and signing in to an account."""
        return self.async_show_menu(
            step_id="user", menu_options=["location", "account"]
        )

    async def async_step_location(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for coordinates and look up the stations around them."""
        errors: dict[str, str] = {}

        if user_input is not None:
            location = user_input[CONF_LOCATION]
            client = AqiInClient(async_get_clientsession(self.hass))

            try:
                self._stations = await client.async_nearest_stations(
                    location[CONF_LATITUDE], location[CONF_LONGITUDE]
                )
            except AqiInAuthError:
                errors["base"] = "invalid_auth"
            except AqiInConnectionError:
                errors["base"] = "cannot_connect"
            except AqiInError:
                _LOGGER.exception("Unexpected AQI.in error while finding stations")
                errors["base"] = "unknown"

            if not errors and not self._stations:
                errors["base"] = "no_stations_found"

            if not errors:
                return await self.async_step_station()

            location_default = location
        else:
            location_default = await self._async_default_location()

        return self.async_show_form(
            step_id="location",
            data_schema=vol.Schema(
                {vol.Required(CONF_LOCATION, default=location_default): LocationSelector()}
            ),
            errors=errors,
        )

    async def async_step_station(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick one of the nearby stations, closest first."""
        if user_input is not None:
            slug = user_input[CONF_STATION]
            station = next(
                s for s in self._stations if s.get("location_slug") == slug
            )

            # locationId is what keeps duplicates out: Home Assistant aborts a
            # second entry for the same station, while distinct stations
            # coexist as independent entries.
            await self.async_set_unique_id(str(station["locationId"]))
            self._abort_if_unique_id_configured()

            name = short_name(station)
            return self.async_create_entry(
                title=name,
                data={
                    CONF_LOCATION_ID: str(station["locationId"]),
                    CONF_SLUG: slug,
                    CONF_STATION_NAME: name,
                    CONF_LATITUDE: station.get("latitude"),
                    CONF_LONGITUDE: station.get("longitude"),
                },
            )

        options = []
        for station in self._stations:
            label = short_name(station)
            if (distance := station.get("distance")) is not None:
                label = f"{label} — {distance} km"
            options.append({"value": station["location_slug"], "label": label})

        return self.async_show_form(
            step_id="station",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_STATION): SelectSelector(
                        SelectSelectorConfig(
                            options=options, mode=SelectSelectorMode.LIST
                        )
                    )
                }
            ),
        )

    async def _async_check_credentials(
        self, user_input: dict[str, Any], errors: dict[str, str]
    ) -> dict[str, Any] | None:
        """Sign in, returning the user profile or recording an error."""
        client = AqiInAccountClient(
            async_get_clientsession(self.hass),
            user_input[CONF_EMAIL],
            user_input[CONF_PASSWORD],
        )
        try:
            return await client.async_login()
        except AqiInAuthError:
            errors["base"] = "invalid_auth"
        except AqiInConnectionError:
            errors["base"] = "cannot_connect"
        except AqiInError:
            _LOGGER.exception("Unexpected AQI.in error while signing in")
            errors["base"] = "unknown"
        return None

    async def async_step_account(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Sign in to an AQI.in account and adopt every monitor it owns."""
        errors: dict[str, str] = {}

        if user_input is not None:
            user = await self._async_check_credentials(user_input, errors)

            if user is not None:
                # One entry per account: every monitor on it becomes a device,
                # so a second entry for the same account is a duplicate.
                await self.async_set_unique_id(f"account_{user.get('id')}")
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=user.get("email") or "AQI.in account",
                    data={
                        CONF_EMAIL: user_input[CONF_EMAIL],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_USER_ID: user.get("id"),
                    },
                )

        return self.async_show_form(
            step_id="account", data_schema=ACCOUNT_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Start reauthentication after the account credentials stop working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for fresh credentials and update the existing entry."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()

        if user_input is not None:
            credentials = {CONF_EMAIL: entry.data[CONF_EMAIL], **user_input}
            user = await self._async_check_credentials(credentials, errors)

            if user is not None:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(
                            type=TextSelectorType.PASSWORD,
                            autocomplete="current-password",
                        )
                    )
                }
            ),
            description_placeholders={CONF_EMAIL: entry.data[CONF_EMAIL]},
            errors=errors,
        )
