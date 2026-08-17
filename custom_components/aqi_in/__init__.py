"""The AQI.in integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AqiInAccountClient, AqiInClient
from .const import CONF_SLUG
from .coordinator import AqiInAccountCoordinator, AqiInCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]

type AqiInCoordinatorType = AqiInCoordinator | AqiInAccountCoordinator
type AqiInConfigEntry = ConfigEntry[AqiInCoordinatorType]


def is_account_entry(entry: AqiInConfigEntry) -> bool:
    """Return True for entries that sign in to an AQI.in account."""
    return CONF_EMAIL in entry.data


async def async_setup_entry(hass: HomeAssistant, entry: AqiInConfigEntry) -> bool:
    """Set up AQI.in from a config entry."""
    session = async_get_clientsession(hass)

    coordinator: AqiInCoordinatorType
    if is_account_entry(entry):
        coordinator = AqiInAccountCoordinator(
            hass,
            AqiInAccountClient(
                session, entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD]
            ),
            AqiInClient(session),
        )
    else:
        coordinator = AqiInCoordinator(hass, AqiInClient(session), entry.data[CONF_SLUG])

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AqiInConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
