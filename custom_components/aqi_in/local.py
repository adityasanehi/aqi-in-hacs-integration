"""Read the observed Prana Air community monitor's local HTTP pages."""

from __future__ import annotations

import math
import re
from html.parser import HTMLParser
from ipaddress import IPv4Address
from typing import Any

import aiohttp

from .api import REQUEST_TIMEOUT, AqiInConnectionError, AqiInError


class _Labels(HTMLParser):
    """Collect complete label text, including nested markup."""

    def __init__(self) -> None:
        super().__init__()
        self.labels: list[str] = []
        self._parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "label":
            self._parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "label" and self._parts is not None:
            self.labels.append("".join(self._parts).strip())
            self._parts = None

    def handle_data(self, data: str) -> None:
        if self._parts is not None:
            self._parts.append(data)


def parse_local_data(html: str) -> dict[str, Any]:
    """Validate the five observed measurements; ignore the unsupported CO2 zero."""
    parser = _Labels()
    parser.feed(html)
    values: dict[str, float] = {}
    fields = {"PM1": "pm1", "PM10": "pm10", "Temp": "temp_c", "Humi": "humidity"}
    try:
        for index, label in enumerate(parser.labels):
            if label == "PM2.5":
                if parser.labels[index + 2] != "ug":
                    raise ValueError("Unrecognised PM2.5 unit")
                key, text = "pm25", parser.labels[index + 1]
            else:
                name, separator, text = label.partition(":")
                if not separator or name not in fields:
                    continue
                key = fields[name]
            value = float(text)
            if key in values or not math.isfinite(value):
                raise ValueError("Duplicate or non-finite measurement")
            if key != "temp_c" and value < 0:
                raise ValueError("Negative measurement")
            if key == "humidity" and value > 100:
                raise ValueError("Humidity exceeds 100 percent")
            values[key] = value
    except (IndexError, ValueError) as err:
        raise AqiInError("Invalid Prana Air local measurement page") from err
    if values.keys() != {"pm1", "pm25", "pm10", "temp_c", "humidity"}:
        raise AqiInError("Prana Air local page is missing measurements")
    return {
        "iaqi": {key: values[key] for key in ("pm1", "pm25", "pm10")},
        "weather": {key: values[key] for key in ("temp_c", "humidity")},
    }


class AqiInLocalClient:
    """Read a local monitor without credentials or cloud requests."""

    def __init__(self, session: aiohttp.ClientSession, host: str) -> None:
        """Bind a Home Assistant session to one IPv4 address."""
        self._session = session
        self.host = str(IPv4Address(host.strip()))
        self.base_url = f"http://{self.host}"

    async def _async_page(self, path: str) -> str:
        """Read a bounded page without following redirects off the monitor."""
        try:
            async with self._session.get(
                f"{self.base_url}{path}",
                timeout=REQUEST_TIMEOUT,
                allow_redirects=False,
            ) as response:
                if response.status != 200:
                    raise AqiInConnectionError(
                        f"Prana Air local {path} returned HTTP {response.status}"
                    )
                body = bytearray()
                async for chunk in response.content.iter_chunked(4096):
                    body.extend(chunk)
                    if len(body) > 65536:
                        raise AqiInError("Prana Air local page exceeds 64 KiB")
                return body.decode("utf-8")
        except (aiohttp.ClientError, TimeoutError) as err:
            raise AqiInConnectionError("Cannot reach the Prana Air monitor") from err
        except UnicodeDecodeError as err:
            raise AqiInError("Invalid Prana Air local page encoding") from err

    async def async_serial(self) -> str:
        """Identify the monitor from its setup page without submitting the form."""
        parser = _Labels()
        parser.feed(await self._async_page("/"))
        if "By Prana Air" not in parser.labels:
            raise AqiInError("This is not a recognised Prana Air monitor")
        serials = [
            match[1].upper()
            for label in parser.labels
            if (match := re.fullmatch(r"ID:\s*([0-9a-fA-F]{12})", label))
        ]
        if len(serials) != 1:
            raise AqiInError("Prana Air monitor did not provide a unique device ID")
        return serials[0]

    async def async_readings(self) -> dict[str, Any]:
        """Fetch local measurements; the page provides no sample timestamp."""
        return parse_local_data(await self._async_page("/data"))
