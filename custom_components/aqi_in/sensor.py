"""Sensor platform for AQI.in."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    CONCENTRATION_PARTS_PER_MILLION,
    PERCENTAGE,
    EntityCategory,
    UnitOfPressure,
    UnitOfSoundPressure,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import AqiInConfigEntry, is_account_entry
from .const import CONF_LOCATION_ID, CONF_SLUG, CONF_STATION_NAME, DOMAIN
from .coordinator import AqiInAccountCoordinator, AqiInCoordinator


def _iaqi(key: str) -> Callable[[dict[str, Any]], StateType]:
    """Read a pollutant out of the payload's iaqi block."""
    return lambda data: (data.get("iaqi") or {}).get(key)


def _weather(key: str) -> Callable[[dict[str, Any]], StateType]:
    """Read a field out of the payload's weather block."""
    return lambda data: (data.get("weather") or {}).get(key)


def _last_updated(data: dict[str, Any]) -> datetime | None:
    """Parse the station's own timestamp."""
    if (updated := data.get("updated_at")) is None:
        return None
    return dt_util.parse_datetime(str(updated))


@dataclass(frozen=True, kw_only=True)
class AqiInSensorDescription(SensorEntityDescription):
    """Describes an AQI.in sensor."""

    value_fn: Callable[[dict[str, Any]], StateType | datetime]


SENSORS: tuple[AqiInSensorDescription, ...] = (
    AqiInSensorDescription(
        key="aqi_in",
        translation_key="aqi_in",
        # The Indian national standard, and the headline number on aqi.in.
        value_fn=_iaqi("AQI-IN"),
        device_class=SensorDeviceClass.AQI,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AqiInSensorDescription(
        key="aqi_us",
        translation_key="aqi_us",
        value_fn=_iaqi("aqi"),
        device_class=SensorDeviceClass.AQI,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AqiInSensorDescription(
        key="pm25",
        translation_key="pm25",
        value_fn=_iaqi("pm25"),
        device_class=SensorDeviceClass.PM25,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    ),
    AqiInSensorDescription(
        key="pm10",
        translation_key="pm10",
        value_fn=_iaqi("pm10"),
        device_class=SensorDeviceClass.PM10,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    ),
    AqiInSensorDescription(
        key="no2",
        translation_key="no2",
        value_fn=_iaqi("no2"),
        device_class=SensorDeviceClass.NITROGEN_DIOXIDE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    ),
    AqiInSensorDescription(
        key="o3",
        translation_key="o3",
        value_fn=_iaqi("o3"),
        device_class=SensorDeviceClass.OZONE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    ),
    AqiInSensorDescription(
        key="so2",
        translation_key="so2",
        value_fn=_iaqi("so2"),
        device_class=SensorDeviceClass.SULPHUR_DIOXIDE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    ),
    # ponytail: no device_class on CO. Home Assistant's CARBON_MONOXIDE class is
    # defined in ppm, but the API reports µg/m³ (observed ~324); tagging it ppm
    # would render a lethal-looking value. Revisit if the API ever states units.
    AqiInSensorDescription(
        key="co",
        translation_key="co",
        value_fn=_iaqi("co"),
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    ),
    # Community monitors report these two instead of the regulatory gases.
    AqiInSensorDescription(
        key="noise",
        translation_key="noise",
        value_fn=_iaqi("noise"),
        device_class=SensorDeviceClass.SOUND_PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfSoundPressure.DECIBEL,
    ),
    # The public feed states no unit, but it is the same field the device API
    # labels ppm: cross-checked on one monitor a minute apart, public read 0.006
    # against the device's 0.008 ppm. Same magnitude, so treat it as ppm.
    AqiInSensorDescription(
        key="tvoc",
        translation_key="tvoc",
        value_fn=_iaqi("tvoc"),
        device_class=SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS_PARTS,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=CONCENTRATION_PARTS_PER_MILLION,
    ),
    AqiInSensorDescription(
        key="temperature",
        translation_key="temperature",
        value_fn=_weather("temp_c"),
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
    ),
    AqiInSensorDescription(
        key="humidity",
        translation_key="humidity",
        value_fn=_weather("humidity"),
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
    ),
    AqiInSensorDescription(
        key="pressure",
        translation_key="pressure",
        value_fn=_weather("pressure_mb"),
        device_class=SensorDeviceClass.ATMOSPHERIC_PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPressure.HPA,
    ),
    AqiInSensorDescription(
        key="wind_speed",
        translation_key="wind_speed",
        value_fn=_weather("wind_kph"),
        device_class=SensorDeviceClass.WIND_SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
    ),
    AqiInSensorDescription(
        key="uv_index",
        translation_key="uv_index",
        value_fn=_weather("uv"),
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AqiInSensorDescription(
        key="last_updated",
        translation_key="last_updated",
        value_fn=_last_updated,
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


@dataclass(frozen=True, kw_only=True)
class AqiInDeviceSensorDescription(SensorEntityDescription):
    """Describes a sensor on a user's own AQI.in monitor.

    Readings come either from the device's own `realtime` list (`sensor_id`) or
    from the public station's weather block, which the coordinator folds in
    (`weather_key`).
    """

    sensor_id: int | None = None
    weather_key: str | None = None


# Keyed by the API's stable numeric sensorid rather than its display name.
# Fahrenheit (id 30) is skipped: Home Assistant converts from Celsius itself.
DEVICE_SENSORS: tuple[AqiInDeviceSensorDescription, ...] = (
    AqiInDeviceSensorDescription(
        key="aqi_in",
        translation_key="aqi_in",
        sensor_id=1,
        device_class=SensorDeviceClass.AQI,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AqiInDeviceSensorDescription(
        key="aqi_us",
        translation_key="aqi_us",
        sensor_id=2,
        device_class=SensorDeviceClass.AQI,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AqiInDeviceSensorDescription(
        key="pm25",
        translation_key="pm25",
        sensor_id=3,
        device_class=SensorDeviceClass.PM25,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    ),
    AqiInDeviceSensorDescription(
        key="pm10",
        translation_key="pm10",
        sensor_id=4,
        device_class=SensorDeviceClass.PM10,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    ),
    AqiInDeviceSensorDescription(
        key="pm1",
        translation_key="pm1",
        sensor_id=5,
        device_class=SensorDeviceClass.PM1,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    ),
    AqiInDeviceSensorDescription(
        key="temperature",
        translation_key="temperature",
        sensor_id=11,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
    ),
    AqiInDeviceSensorDescription(
        key="humidity",
        translation_key="humidity",
        sensor_id=12,
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
    ),
    AqiInDeviceSensorDescription(
        key="noise",
        translation_key="noise",
        sensor_id=13,
        device_class=SensorDeviceClass.SOUND_PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfSoundPressure.DECIBEL,
    ),
    # The device API states its units, so unlike the public feed this one can
    # safely claim a device class.
    AqiInDeviceSensorDescription(
        key="tvoc",
        translation_key="tvoc",
        sensor_id=18,
        device_class=SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS_PARTS,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=CONCENTRATION_PARTS_PER_MILLION,
    ),
    # Particle counts. The API labels the unit "μm", but that is the particle
    # size the channel counts, not the unit of the value — so no unit is set.
    *(
        AqiInDeviceSensorDescription(
            key=f"particles_{size.replace('.', '_')}",
            translation_key=f"particles_{size.replace('.', '_')}",
            sensor_id=sensor_id,
            state_class=SensorStateClass.MEASUREMENT,
            entity_registry_enabled_default=False,
        )
        for sensor_id, size in (
            (71, "0.3"),
            (72, "0.5"),
            (73, "1.0"),
            (74, "3.0"),
            (75, "5.0"),
            (76, "10.0"),
        )
    ),
    # Weather has no device sensor behind it; the coordinator copies it from the
    # matching public station so one device carries the full picture.
    AqiInDeviceSensorDescription(
        key="pressure",
        translation_key="pressure",
        weather_key="pressure_mb",
        device_class=SensorDeviceClass.ATMOSPHERIC_PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPressure.HPA,
    ),
    AqiInDeviceSensorDescription(
        key="wind_speed",
        translation_key="wind_speed",
        weather_key="wind_kph",
        device_class=SensorDeviceClass.WIND_SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
    ),
    AqiInDeviceSensorDescription(
        key="uv_index",
        translation_key="uv_index",
        weather_key="uv",
        state_class=SensorStateClass.MEASUREMENT,
    ),
)


def device_reading(device: dict[str, Any], sensor_id: int) -> StateType:
    """Pull one reading out of a device's realtime list."""
    for reading in device.get("realtime") or ():
        if reading.get("sensorid") == sensor_id:
            return reading.get("sensorvalue")
    return None


def device_value(
    device: dict[str, Any], description: AqiInDeviceSensorDescription
) -> StateType:
    """Resolve a device sensor from whichever source backs it."""
    if description.sensor_id is not None:
        return device_reading(device, description.sensor_id)
    if description.weather_key is not None:
        return (device.get("weather") or {}).get(description.weather_key)
    return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AqiInConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the AQI.in sensors.

    Stations report different pollutants depending on their type: regulatory
    stations return CO/NO2/O3/SO2, community monitors return noise/TVOC. Only
    create the sensors this station actually reports, so neither kind is
    cluttered with permanently unknown entities.
    """
    coordinator = entry.runtime_data
    data = coordinator.data or {}

    if is_account_entry(entry):
        async_add_entities(
            AqiInDeviceSensor(coordinator, serial, description)
            for serial, device in data.items()
            for description in DEVICE_SENSORS
            if device_value(device, description) is not None
        )
        return

    async_add_entities(
        AqiInSensor(coordinator, entry, description)
        for description in SENSORS
        if description.value_fn(data) is not None
    )


class AqiInSensor(CoordinatorEntity[AqiInCoordinator], SensorEntity):
    """A single reading from an AQI.in station."""

    entity_description: AqiInSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AqiInCoordinator,
        entry: AqiInConfigEntry,
        description: AqiInSensorDescription,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator)
        self.entity_description = description

        location_id = entry.data[CONF_LOCATION_ID]
        self._attr_unique_id = f"{location_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, location_id)},
            name=entry.data[CONF_STATION_NAME],
            manufacturer="AQI.in",
            model="Air quality station",
            configuration_url=f"https://www.aqi.in/dashboard/{entry.data[CONF_SLUG]}",
        )

    @property
    def native_value(self) -> StateType | datetime:
        """Return the current reading, or None when the API omits it."""
        if not self.coordinator.data:
            return None
        return self.entity_description.value_fn(self.coordinator.data)


class AqiInDeviceSensor(CoordinatorEntity[AqiInAccountCoordinator], SensorEntity):
    """A single reading from a monitor owned by the account."""

    entity_description: AqiInDeviceSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AqiInAccountCoordinator,
        serial: str,
        description: AqiInDeviceSensorDescription,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._serial = serial

        device = coordinator.data[serial]
        self._attr_unique_id = f"{serial}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, serial)},
            name=device.get("devicename") or serial,
            manufacturer="AQI.in",
            model=device.get("dev_type") or "Air quality monitor",
            serial_number=serial,
            configuration_url="https://dash.aqi.in/",
        )

    @property
    def available(self) -> bool:
        """Return False when the device drops out of the account payload."""
        return super().available and self._serial in (self.coordinator.data or {})

    @property
    def native_value(self) -> StateType:
        """Return the current reading, or None when the device omits it."""
        device = (self.coordinator.data or {}).get(self._serial)
        if device is None:
            return None
        return device_value(device, self.entity_description)
