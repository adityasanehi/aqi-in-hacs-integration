# AQI.in for Home Assistant

Live air quality and weather from [AQI.in](https://www.aqi.in) monitoring stations, as Home
Assistant sensors.

- Pick a station from the **five nearest** to any point, listed closest first
- **Live AQI** (Indian and US scales), pollutants, temperature, humidity and more
- Or **sign in** to add your own monitors, with PM1 and particle counts
- Or connect a supported **Prana Air monitor locally**, without an account
- **Add as many stations as you like** — each becomes its own device
- No API key, no `configuration.yaml`

## Installation

### Marketplace (recommended)

[![Open your Home Assistant instance and open this repository in the Marketplace.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=adityasanehi&repository=aqi-in-hacs-integration&category=integration)

Home Assistant 2026.11 and newer:

1. **Settings → Marketplace → Add from link**
2. Enter `https://github.com/adityasanehi/aqi-in-hacs-integration`
3. Select **Install** on **AQI.in**. Setup opens straight away, with no restart needed.

On older versions with HACS: **HACS → three-dot menu → Custom repositories**, add the URL above
with category **Integration**, install **AQI.in**, restart, then go to
**Settings → Devices & Services → Add Integration → AQI.in**.

### Manual

Copy `custom_components/aqi_in` into your `config/custom_components/` directory and restart.

## Setup

Choose a **public monitoring station**, **AQI.in account**, or **local Prana Air monitor**.
These modes can be used alongside each other.

### Public station

Asks for a location, prefilled with your Home Assistant home coordinates. Edit it to search
anywhere — the next step lists the five nearest stations with their distances:

```
Janpath — 1.57 km
Man Singh Road Area — 1.57 km
Delhi Gymkhana Club — 1.81 km
Rabindra Nagar — 1.95 km
HT House — 2.09 km
```

To track more than one location, add the integration again. Adding a station that already exists
is rejected, so entries can't be duplicated by accident.

Coverage is global, not India-only.

### AQI.in account

Sign in with your aqi.in email and password. Every monitor on the account is added automatically,
as its own device — there's nothing to pick. If the password changes, Home Assistant prompts you
to sign in again rather than silently going stale.

Credentials are stored in the Home Assistant config entry and sent only to `aqi.in`.

### Local Prana Air monitor

Choose **Local Prana Air monitor** and enter its IPv4 address, for example
`192.168.1.50`. No AQI.in credentials are required. Setup checks the Prana Air
device ID and its `/data` page; only monitors serving this observed community
monitor interface are supported. Reserve its IP in your router. If it changes,
use the entry's **Reconfigure** menu to enter the new address; the device ID must
still match.

The integration reads **PM1, PM2.5, PM10, temperature and humidity** from the
monitor every **30 seconds**. Sensors are named **PM2.5 (local)**, etc., and have
separate identities from cloud sensors, so adding local access preserves existing
cloud values and statistics. Temperature on the observed page has less precision
than the cloud feed. Local PM10 differed from the account feed in a live paired
comparison (473 versus 403.16 µg/m³); the cause is unknown and no correction is
applied. PM2.5, PM1 and humidity matched in that comparison.

Local access exposes no AQI, TVOC, noise, particle counts or weather. The page's
CO2 zero is omitted because the same monitor's account feed has no CO2 sensor.
The page has no measurement timestamp: a successful poll confirms the page is
reachable, not that its sensors are producing fresh samples. Connection or page
validation errors make local sensors unavailable, without replacing them with
cached cloud readings. No cloud requests are made by a local entry, but operation
with the monitor's internet connection disabled has not been tested.

This interface was verified on one community monitor whose page is titled
**Bohu Monitor**. It is undocumented in the public
[community manual](https://www.aqi.in/manuals/community-monitor-manual.pdf),
so other hardware or firmware may expose different pages. Local sensor units
are based on the corresponding account sensor metadata and the live comparison.
Setup/reload checks device identity; ongoing polling only reads `/data` to avoid
repeatedly fetching the Wi-Fi setup page. Use an IP reservation to prevent an
address being reassigned to another monitor.

## Sensors

Only the sensors a given station or device actually reports are created, so nothing is cluttered
with permanently unknown entities.

### Public stations

Which pollutants appear depends on the station type.

| Sensor | Unit | Notes |
|---|---|---|
| AQI (India) | — | The Indian national standard, the headline figure on aqi.in |
| AQI (US) | — | US EPA scale |
| PM2.5 / PM10 | µg/m³ | All stations |
| Nitrogen dioxide / Ozone / Sulphur dioxide | µg/m³ | Regulatory stations |
| Carbon monoxide | µg/m³ | Regulatory stations |
| Noise | dB | Community monitors |
| TVOC | ppm | Community monitors |
| Temperature / Humidity | °C / % | |
| Pressure / Wind speed / UV index | hPa / km/h / — | Weather, not available on owned devices |
| Last updated | timestamp | Diagnostic — shows if a station has gone stale |

### Your own monitors

Signing in gives you a **superset** on a single device — the monitor's own readings, plus the
weather fields from its public listing:

| Sensor | Unit | Notes |
|---|---|---|
| PM1 | µg/m³ | Not exposed by the public endpoints |
| TVOC | ppm | Units are stated by this API, so the reading is properly typed |
| Particles 0.3 / 0.5 / 1.0 / 3.0 / 5.0 / 10.0 µm | count | Disabled by default — enable per entity |
| Pressure / Wind speed / UV index | hPa / km/h / — | Merged in from the public station |

The two sources are matched exactly: a monitor's public `locationId` **is** its serial number, so
there's no guessing by proximity. You get one device with no duplicated entities, rather than
having to add the public station separately. Where both sources report the same field, the
device's own reading wins.

If a monitor isn't published publicly (indoor units, for instance), it simply gets no weather
sensors — and if the public API is unavailable, the device readings still update normally.

Carbon monoxide intentionally carries no device class: the public API doesn't state its units and
the values (~324) are clearly not ppm, which is how Home Assistant's carbon monoxide class is
defined — tagging it would render a lethal-looking reading.

TVOC *is* typed as ppm on both paths. The public feed states no unit, but it's the same field the
device API labels ppm — cross-checked on one monitor a minute apart, the public feed read 0.006
against the device's 0.008 ppm.

Cloud data refreshes every 10 minutes, matching the observed public-station cadence —
one API call per station,
or one per account plus one per owned device for the merged weather.
History and long-term statistics come from Home Assistant's own recorder, so no extra polling is
needed.

## Development

```bash
pip install ruff
ruff check .                  # lint

python3 scripts/live_check.py # smoke-test the live API

# add AQI_EMAIL / AQI_PASSWORD to also exercise the account API
AQI_EMAIL=you@example.com AQI_PASSWORD=... python3 scripts/live_check.py
```

`live_check.py` is the quickest way to tell whether a problem is in this integration or in the
upstream API — it exercises the token scrape, the nearest-station lookup and one station's live
readings, with no Home Assistant involved.

## Disclaimer

This is an **unofficial** integration, not affiliated with, endorsed by, or associated with AQI.in
or its parent organisation. It reads the same public web endpoints the aqi.in website uses, with
the anonymous token that site issues, and is provided for personal and informational use.

## Licence

MIT
