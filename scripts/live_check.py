#!/usr/bin/env python3
"""Smoke-test the live AQI.in API without Home Assistant.

Confirms the token scrape still works and that a station payload still carries
the fields the integration reads.

    python3 scripts/live_check.py [latitude] [longitude]

Set AQI_EMAIL and AQI_PASSWORD to also exercise the authenticated account API.
Credentials are read from the environment only, never stored.
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import sys

import aiohttp

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from custom_components.aqi_in.api import AqiInAccountClient, AqiInClient

IAQI_KEYS = ("AQI-IN", "aqi", "pm25", "pm10", "co", "no2", "o3", "so2", "noise", "tvoc")
WEATHER_KEYS = ("temp_c", "humidity", "pressure_mb", "wind_kph", "uv")


async def main() -> None:
    """Fetch nearby stations and dump one station's readings."""
    latitude = float(sys.argv[1]) if len(sys.argv) > 2 else 28.6139
    longitude = float(sys.argv[2]) if len(sys.argv) > 2 else 77.2090

    async with aiohttp.ClientSession() as session:
        client = AqiInClient(session)

        stations = await client.async_nearest_stations(latitude, longitude)
        print(f"\n{len(stations)} nearest stations to {latitude}, {longitude}:")
        for station in stations:
            print(
                f"  {station.get('distance')!s:>6} km  "
                f"{station['station'][:44]:44}  {station['location_slug']}"
            )

        slug = stations[0]["location_slug"]
        details = await client.async_station(slug)

        print(f"\nLive readings for {details['station']}")
        print(f"  source     : {details.get('source', 'unknown')}")
        print(f"  locationId : {details['locationId']!r}")
        print(f"  updated_at : {details.get('updated_at')}")
        print(f"  online     : {details.get('isOnline')}")

        iaqi = details.get("iaqi") or {}
        weather = details.get("weather") or {}
        print("  iaqi       : " + ", ".join(
            f"{key}={iaqi[key]}" for key in IAQI_KEYS if key in iaqi
        ))
        print("  weather    : " + ", ".join(
            f"{key}={weather[key]}" for key in WEATHER_KEYS if key in weather
        ))

        missing = [key for key in ("AQI-IN", "aqi", "pm25", "pm10") if key not in iaqi]
        if missing:
            print(f"\n  WARNING: expected keys absent: {missing}")

        await check_account(session)


async def check_account(session: aiohttp.ClientSession) -> None:
    """Exercise the authenticated API when credentials are in the environment."""
    email, password = os.getenv("AQI_EMAIL"), os.getenv("AQI_PASSWORD")
    if not email or not password:
        print("\n(set AQI_EMAIL and AQI_PASSWORD to also check the account API)")
        return

    client = AqiInAccountClient(session, email, password)
    user = await client.async_login()
    print(f"\nSigned in as {user.get('email')} (id {user.get('id')})")

    for device in await client.async_devices():
        print(
            f"\n  {device['serialNo']}  {device.get('devicename')}  "
            f"type={device.get('dev_type')}  online={device.get('isOnline')}"
        )
        for reading in device.get("realtime") or ():
            print(
                f"      id={reading['sensorid']:>3}  {reading['sensorname']:22}"
                f"{reading['sensorvalue']:>9}  {reading['unit']}"
            )


if __name__ == "__main__":
    asyncio.run(main())
