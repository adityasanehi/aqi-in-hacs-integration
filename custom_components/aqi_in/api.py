"""Client for the AQI.in public web API.

AQI.in has no documented public API. The website authenticates with an anonymous
JWT that its server renders into every page's HTML, valid for seven days. We
scrape that token rather than signing one ourselves, so a rotation of the
upstream signing secret cannot break us.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import math
import re
import time
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://apiserver.aqi.in"
TOKEN_URL = "https://www.aqi.in/"

TOKEN_RE = re.compile(r"eyJhbGciOiJIUzI1NiI[\w-]*\.[\w-]+\.[\w-]+")

# Re-scrape once the cached token is within a day of expiring.
REFRESH_SKEW = 86400

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/143.0.0.0 Safari/537.36"
)

HEADERS = {
    "User-Agent": USER_AGENT,
    "Referer": TOKEN_URL,
    "Accept": "application/json, text/plain, */*",
}

ENDPOINT_NEAREST = "/aqi/v2/getNearestLocation"
ENDPOINT_LOCATION = "/aqi/v2/getLocationDetailsBySlug"
ENDPOINT_IP = "/service/get/ip/details"

# The account API that backs dash.aqi.in, for users who own a monitor.
ACCOUNT_BASE_URL = "https://airquality.aqi.in/api/v1"
ENDPOINT_LOGIN = "/login"
ENDPOINT_DEVICES = "/GetAllUserDevices"

ACCOUNT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Origin": "https://dash.aqi.in",
    "Referer": "https://dash.aqi.in/",
    "Accept": "*/*",
}


class AqiInError(Exception):
    """Base error for the AQI.in API."""


class AqiInAuthError(AqiInError):
    """The API rejected our token, even after refreshing it."""


class AqiInConnectionError(AqiInError):
    """The API could not be reached."""


def _as_float(value: Any, default: float) -> float:
    """Coerce a value to float, falling back to a default."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _token_expiry(token: str) -> float:
    """Read the `exp` claim out of a JWT.

    The signature is deliberately not verified — we only need the expiry so we
    know when to re-scrape. Authentication decisions are made by the server.
    """
    try:
        payload = token.split(".")[1]
        decoded = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        return float(json.loads(decoded)["exp"])
    except (IndexError, KeyError, ValueError, binascii.Error):
        # Unreadable expiry: treat it as short-lived rather than re-scraping on
        # every single request.
        _LOGGER.debug("Could not read expiry from AQI.in token")
        return time.time() + 3600


class AqiInClient:
    """Minimal async client for the handful of endpoints we need."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        """Initialise the client with a Home Assistant managed session."""
        self._session = session
        self._token: str | None = None
        self._token_expiry = 0.0

    async def _async_token(self, *, force: bool = False) -> str:
        """Return a cached token, scraping a fresh one when needed."""
        if (
            not force
            and self._token is not None
            and self._token_expiry - time.time() > REFRESH_SKEW
        ):
            return self._token

        try:
            async with self._session.get(
                TOKEN_URL,
                headers={"User-Agent": USER_AGENT},
                timeout=REQUEST_TIMEOUT,
            ) as response:
                response.raise_for_status()
                html = await response.text()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise AqiInConnectionError(f"Cannot reach {TOKEN_URL}: {err}") from err

        match = TOKEN_RE.search(html)
        if match is None:
            raise AqiInAuthError("No API token found in the AQI.in page markup")

        self._token = match.group(0)
        self._token_expiry = _token_expiry(self._token)
        _LOGGER.debug("Fetched a new AQI.in token")
        return self._token

    async def _async_request(
        self, path: str, params: dict[str, Any] | None = None
    ) -> Any:
        """Perform a GET, refreshing the token once if it is rejected."""
        query = {**(params or {}), "source": "web"}

        # Two attempts at most: the second only ever runs after a 401, with a
        # forcibly refreshed token.
        for attempt in range(2):
            token = await self._async_token(force=attempt > 0)

            try:
                async with self._session.get(
                    f"{BASE_URL}{path}",
                    params=query,
                    headers={**HEADERS, "authorization": f"bearer {token}"},
                    timeout=REQUEST_TIMEOUT,
                ) as response:
                    if response.status == 401:
                        if attempt == 0:
                            _LOGGER.debug("AQI.in token rejected, refreshing it")
                            continue
                        raise AqiInAuthError(
                            "AQI.in rejected the token after refreshing it"
                        )

                    if response.status >= 400:
                        raise AqiInConnectionError(
                            f"AQI.in returned HTTP {response.status} for {path}"
                        )

                    body = await response.json(content_type=None)
            except (aiohttp.ClientError, TimeoutError) as err:
                raise AqiInConnectionError(f"Cannot reach AQI.in: {err}") from err
            except ValueError as err:
                raise AqiInError(f"AQI.in returned invalid JSON for {path}") from err

            # The API spells this "success" on some endpoints and "Success" on
            # others, so only the failure case is worth matching.
            if str(body.get("status", "")).lower() == "failed":
                message = body.get("message") or body.get("error") or "Unknown error"
                raise AqiInError(f"AQI.in reported an error: {message}")

            data = body.get("data")
            if data is None:
                raise AqiInError(f"AQI.in returned no data for {path}")
            return data

        raise AqiInAuthError("AQI.in rejected the token after refreshing it")

    async def async_nearest_stations(
        self, latitude: float, longitude: float
    ) -> list[dict[str, Any]]:
        """Return nearby stations, closest first."""
        data = await self._async_request(
            ENDPOINT_NEAREST, {"lat": latitude, "long": longitude, "type": 1}
        )
        if not isinstance(data, list):
            raise AqiInError("Unexpected payload for nearest stations")

        # The API already sorts these, but ordering is the one thing the user
        # actually asked for — so don't take it on trust.
        return sorted(
            data, key=lambda station: _as_float(station.get("distance"), math.inf)
        )

    async def async_station(self, slug: str) -> dict[str, Any]:
        """Return live details for one station slug."""
        data = await self._async_request(
            ENDPOINT_LOCATION, {"slug": slug, "type": slug.count("/") + 1}
        )
        if not isinstance(data, list) or not data:
            raise AqiInError(f"AQI.in returned no station data for {slug}")
        return data[0]

    async def async_ip_location(self) -> tuple[float, float] | None:
        """Return coordinates derived from the caller's IP, if available."""
        try:
            data = await self._async_request(ENDPOINT_IP)
        except AqiInError:
            _LOGGER.debug("IP based location lookup failed", exc_info=True)
            return None

        latitude, longitude = data.get("lat"), data.get("lon")
        if latitude is None or longitude is None:
            return None
        return float(latitude), float(longitude)


class AqiInAccountClient:
    """Client for the account API, which exposes a user's own monitors.

    Devices report more than the public station endpoints do — PM1, particle
    counts, and explicit units for every reading — but carry no weather data.
    """

    def __init__(
        self, session: aiohttp.ClientSession, email: str, password: str
    ) -> None:
        """Initialise the client with credentials."""
        self._session = session
        self._email = email
        self._password = password
        self._token: str | None = None

    async def async_login(self) -> dict[str, Any]:
        """Authenticate and cache the token, returning the user profile."""
        try:
            async with self._session.post(
                f"{ACCOUNT_BASE_URL}{ENDPOINT_LOGIN}",
                json={"email": self._email, "password": self._password},
                headers=ACCOUNT_HEADERS,
                timeout=REQUEST_TIMEOUT,
            ) as response:
                if response.status in (400, 401, 403):
                    raise AqiInAuthError("AQI.in rejected those credentials")
                if response.status >= 400:
                    raise AqiInConnectionError(
                        f"AQI.in login returned HTTP {response.status}"
                    )
                body = await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise AqiInConnectionError(f"Cannot reach AQI.in to sign in: {err}") from err
        except ValueError as err:
            raise AqiInError("AQI.in returned invalid JSON when signing in") from err

        token = body.get("token")
        if not token:
            raise AqiInAuthError("AQI.in login response contained no token")

        self._token = token
        return body.get("user") or {}

    async def async_devices(self) -> list[dict[str, Any]]:
        """Return the account's monitors with their live readings."""
        # Two attempts at most: the second only after the token is refused.
        for attempt in range(2):
            if self._token is None:
                await self.async_login()

            try:
                async with self._session.get(
                    f"{ACCOUNT_BASE_URL}{ENDPOINT_DEVICES}",
                    headers={
                        **ACCOUNT_HEADERS,
                        "Authorization": f"bearer {self._token}",
                    },
                    timeout=REQUEST_TIMEOUT,
                ) as response:
                    if response.status >= 400:
                        raise AqiInConnectionError(
                            f"AQI.in returned HTTP {response.status} for devices"
                        )
                    body = await response.json(content_type=None)
            except (aiohttp.ClientError, TimeoutError) as err:
                raise AqiInConnectionError(f"Cannot reach AQI.in: {err}") from err
            except ValueError as err:
                raise AqiInError("AQI.in returned invalid JSON for devices") from err

            # A dead token comes back as HTTP 200 with status 0, so the status
            # code alone would read as success.
            if body.get("status") == 0:
                message = body.get("msg") or body.get("message") or "Unknown error"
                if attempt == 0 and "token" in message.lower():
                    _LOGGER.debug("AQI.in account token expired, signing in again")
                    self._token = None
                    continue
                raise AqiInAuthError(f"AQI.in rejected the session: {message}")

            data = body.get("data")
            if not isinstance(data, list):
                raise AqiInError("Unexpected payload for account devices")
            return data

        raise AqiInAuthError("AQI.in rejected the session after signing in again")
