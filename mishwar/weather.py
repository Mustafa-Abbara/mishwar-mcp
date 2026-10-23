"""Data core: geocode a place in Lebanon, then fetch its daily forecast from Open-Meteo.

Only fetch_json touches the network, so tests replace that one function (or
the httpx transport underneath it).
"""
import datetime as dt
import json
import logging
import math
from pathlib import Path

import httpx

from . import config, validation
from .errors import DateOutOfRange, InvalidInput, PlaceNotFound, ServiceUnavailable
from .models import DayForecast

log = logging.getLogger("mishwar.weather")

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MAX_DAYS_AHEAD = 15  # Open-Meteo serves 16 days: today + 15
TIMEOUT_S = 10
CONNECT_TIMEOUT_S = 4
CONNECT_RETRIES = 2  # about 1 connection in 6 hangs on some networks; retrying a connect is always safe
DAILY_FIELDS = "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,wind_speed_10m_max"

# Local names the geocoder misses, mapped to a name it knows (verified by tests/live).
ALIASES = {
    "jbeil": "Byblos",
    "jbail": "Byblos",
    "tyre": "Sour",
    "sur": "Sour",
    "saida": "Sidon",
    "trablous": "Tripoli",
    "bcharre": "Bsharri",
    "bsharre": "Bsharri",
    "bcharré": "Bsharri",
    "bsherri": "Bsharri",
}

WMO_SUMMARY = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Freezing fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle", 56: "Freezing drizzle", 57: "Freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain", 67: "Freezing rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Light showers", 81: "Showers", 82: "Violent showers", 85: "Snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Thunderstorm with heavy hail",
}

# Tests swap this for an httpx.MockTransport; None means the real network.
_transport: httpx.AsyncBaseTransport | None = None

OFFLINE_DIR = Path(__file__).resolve().parent / "offline_data"


async def fetch_json(url: str, params: dict) -> dict:
    if config.simulate_outage():
        raise ServiceUnavailable("simulated outage")
    if config.offline():
        return _offline_json(url, params)
    try:
        transport = _transport or httpx.AsyncHTTPTransport(retries=CONNECT_RETRIES)
        timeout = httpx.Timeout(TIMEOUT_S, connect=CONNECT_TIMEOUT_S)
        async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
            response = await client.get(url, params=params)
    except httpx.TimeoutException as e:
        raise ServiceUnavailable("timed out") from e
    except httpx.HTTPError as e:
        raise ServiceUnavailable("network error") from e
    if response.status_code >= 500:
        raise ServiceUnavailable(f"HTTP {response.status_code}")
    try:
        data = response.json()
    except ValueError as e:
        raise ServiceUnavailable("unreadable response") from e
    if response.status_code >= 400 or data.get("error"):
        raise InvalidInput(f"The weather service rejected the request: {data.get('reason', 'unknown reason')}.")
    return data


def parse_forecast_date(text: str) -> dt.date:
    day = validation.parse_iso_date(text)
    today = validation.today_beirut()
    last = today + dt.timedelta(days=MAX_DAYS_AHEAD)
    if not today <= day <= last:
        raise DateOutOfRange(f"{day} is outside the forecast window ({today} to {last}). Pick a date in that range.")
    return day


async def _search(name: str) -> dict | None:
    data = await fetch_json(GEOCODE_URL, {
        "name": name, "count": 1, "language": "en", "format": "json", "countryCode": config.country_code(),
    })
    results = data.get("results") or []  # a missing key and an empty list both mean "not found"
    return results[0] if results else None


async def geocode(place: str) -> dict:
    """Return the geocoder's record for a place in Lebanon, trying the alias table second."""
    name = validation.check_place(place)
    record = await _search(name)
    alias = ALIASES.get(name.lower())
    if record is None and alias:
        record = await _search(alias)
    if record is None:
        raise PlaceNotFound(
            f"No place called '{name}' was found in Lebanon. "
            "Check the spelling or try the English name of the town or a nearby one, e.g. 'Byblos' or 'Sidon'."
        )
    return record


async def get_forecast(place: str, date: str) -> DayForecast:
    day = parse_forecast_date(date)
    record = await geocode(place)
    data = await fetch_json(FORECAST_URL, {
        "latitude": record["latitude"], "longitude": record["longitude"], "daily": DAILY_FIELDS,
        "timezone": "Asia/Beirut", "start_date": day.isoformat(), "end_date": day.isoformat(),
    })
    try:
        daily = data["daily"]
        code = int(daily["weather_code"][0])
        rain = daily["precipitation_probability_max"][0]
        return DayForecast(
            place=record["name"],
            region=record.get("admin1", ""),
            latitude=record["latitude"],
            longitude=record["longitude"],
            date=day,
            weather_code=code,
            summary=WMO_SUMMARY.get(code, f"Weather code {code}"),
            temp_min_c=daily["temperature_2m_min"][0],
            temp_max_c=daily["temperature_2m_max"][0],
            rain_probability_pct=None if rain is None else int(rain),
            wind_max_kmh=daily["wind_speed_10m_max"][0],
            source="offline-sample" if data.get("offline") else "open-meteo",
        )
    except (KeyError, IndexError, TypeError, ValueError) as e:
        raise ServiceUnavailable("unexpected response") from e


def _offline_json(url: str, params: dict) -> dict:
    """Answer from saved responses in offline_data/. Logged on every call so it is never hidden."""
    log.warning("OFFLINE MODE: answering %s from saved responses", url.rsplit("/", 1)[-1])
    if url == GEOCODE_URL:
        path = OFFLINE_DIR / "geocode" / f"{params['name'].strip().lower()}.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    # Forecast: use the saved place nearest to the coordinates, and the saved day
    # with the same offset from today, relabelled with the requested date.
    saved = [json.loads(p.read_text(encoding="utf-8")) for p in (OFFLINE_DIR / "forecast").glob("*.json")]
    if not saved:
        raise ServiceUnavailable("offline mode has no saved forecasts")
    nearest = min(saved, key=lambda f: math.dist((f["latitude"], f["longitude"]), (params["latitude"], params["longitude"])))
    day = dt.date.fromisoformat(params["start_date"])
    index = min(max((day - validation.today_beirut()).days, 0), len(nearest["daily"]["time"]) - 1)
    daily = {key: [values[index]] for key, values in nearest["daily"].items()}
    daily["time"] = [day.isoformat()]
    return {"daily": daily, "offline": True}
