import json
import threading
from datetime import datetime, timedelta, timezone

import requests

from . import db
from .settings_store import get_settings

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
REQUEST_TIMEOUT = 10
CACHE_TTL_MINUTES = 30
HOURLY_COUNT = 8      # "now" plus the next 7 hours
FORECAST_DAYS = 5     # days after today shown in the strip

# WMO weather codes -> a simple condition label + icon category.
_CODE_MAP = {
    0: ("Clear", "clear"),
    1: ("Mostly clear", "clear"),
    2: ("Partly cloudy", "cloudy"),
    3: ("Overcast", "cloudy"),
    45: ("Fog", "cloudy"),
    48: ("Fog", "cloudy"),
    51: ("Light drizzle", "rain"),
    53: ("Drizzle", "rain"),
    55: ("Heavy drizzle", "rain"),
    56: ("Freezing drizzle", "rain"),
    57: ("Freezing drizzle", "rain"),
    61: ("Light rain", "rain"),
    63: ("Rain", "rain"),
    65: ("Heavy rain", "rain"),
    66: ("Freezing rain", "rain"),
    67: ("Freezing rain", "rain"),
    71: ("Light snow", "snow"),
    73: ("Snow", "snow"),
    75: ("Heavy snow", "snow"),
    77: ("Snow grains", "snow"),
    80: ("Rain showers", "rain"),
    81: ("Rain showers", "rain"),
    82: ("Heavy showers", "rain"),
    85: ("Snow showers", "snow"),
    86: ("Snow showers", "snow"),
    95: ("Thunderstorm", "storm"),
    96: ("Thunderstorm", "storm"),
    99: ("Thunderstorm", "storm"),
}


def describe_code(code: int) -> tuple[str, str]:
    return _CODE_MAP.get(code, ("Unknown", "cloudy"))


def is_configured() -> bool:
    return bool(db.get_setting("weather_lat")) and bool(db.get_setting("weather_lon"))


def geocode(query: str) -> dict | None:
    resp = requests.get(
        GEOCODE_URL, params={"name": query, "count": 1, "language": "en", "format": "json"},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    results = resp.json().get("results") or []
    if not results:
        return None
    r = results[0]
    label_parts = [r.get("name")]
    if r.get("admin1"):
        label_parts.append(r["admin1"])
    if r.get("country_code"):
        label_parts.append(r["country_code"])
    return {"lat": r["latitude"], "lon": r["longitude"], "label": ", ".join(label_parts)}


def clear_cache() -> None:
    db.set_setting("weather_cache_json", "")
    db.set_setting("weather_cache_at", "")


def set_location(lat: float, lon: float, label: str) -> None:
    db.set_setting("weather_lat", str(lat))
    db.set_setting("weather_lon", str(lon))
    db.set_setting("weather_label", label)
    clear_cache()


def get_location_label() -> str | None:
    return db.get_setting("weather_label")


def _hour_label(iso: str) -> str:
    hour = datetime.fromisoformat(iso).hour
    suffix = "am" if hour < 12 else "pm"
    return f"{hour % 12 or 12}{suffix}"


def _fetch_forecast(lat: float, lon: float, units: str) -> dict:
    metric = units == "c"
    resp = requests.get(
        FORECAST_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
            "hourly": "temperature_2m,weather_code,precipitation_probability",
            "daily": "temperature_2m_max,temperature_2m_min,weather_code,precipitation_probability_max",
            "temperature_unit": "celsius" if metric else "fahrenheit",
            "wind_speed_unit": "kmh" if metric else "mph",
            "timezone": "auto",
            "forecast_days": FORECAST_DAYS + 1,
        },
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()

    current = data["current"]
    cond_label, cond_icon = describe_code(current["weather_code"])

    # Hourly: start at the current hour (current["time"] is local, minute precision).
    hourly_src = data["hourly"]
    now_hour = current["time"][:13]
    start = next((i for i, t in enumerate(hourly_src["time"]) if t[:13] >= now_hour), 0)
    hourly = []
    for i in range(start, min(start + HOURLY_COUNT, len(hourly_src["time"]))):
        _, icon = describe_code(hourly_src["weather_code"][i])
        hourly.append(
            {
                "label": "Now" if i == start else _hour_label(hourly_src["time"][i]),
                "temp": round(hourly_src["temperature_2m"][i]),
                "icon": icon,
                "rain": hourly_src["precipitation_probability"][i] or 0,
            }
        )

    daily = data["daily"]
    forecast = []
    for i in range(1, min(FORECAST_DAYS + 1, len(daily["time"]))):
        day_label, day_icon = describe_code(daily["weather_code"][i])
        day_date = datetime.fromisoformat(daily["time"][i])
        rain = daily.get("precipitation_probability_max") or []
        forecast.append(
            {
                "label": day_date.strftime("%a"),
                "hi": round(daily["temperature_2m_max"][i]),
                "lo": round(daily["temperature_2m_min"][i]),
                "icon": day_icon,
                "condition": day_label,
                "rain": (rain[i] if i < len(rain) and rain[i] is not None else 0),
            }
        )

    return {
        "temp": round(current["temperature_2m"]),
        "feels_like": round(current["apparent_temperature"]),
        "condition": cond_label,
        "icon": cond_icon,
        "wind": round(current["wind_speed_10m"]),
        "wind_unit": "km/h" if metric else "mph",
        "hi": round(daily["temperature_2m_max"][0]),
        "lo": round(daily["temperature_2m_min"][0]),
        "hourly": hourly,
        "forecast": forecast,
        "units": units,
    }


def _cached(stored: dict) -> tuple[dict | None, bool]:
    """(cached forecast or None, is it fresh?) from the stored settings."""
    try:
        cached = json.loads(stored.get("weather_cache_json") or "null")
    except json.JSONDecodeError:
        cached = None
    # A cache written by the old version (no hourly) or in other units is stale.
    units = get_settings(stored)["units"]
    if not isinstance(cached, dict) or cached.get("units") != units or "hourly" not in cached:
        return None, False
    try:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(stored.get("weather_cache_at") or "")
    except ValueError:
        return cached, False
    return cached, age < timedelta(minutes=CACHE_TTL_MINUTES)


def get_weather() -> dict | None:
    """Return cached weather if fresh, otherwise fetch, cache, and return it.
    Returns None if no location has been configured, or the API call fails
    and there's no usable cache to fall back to."""
    stored = db.all_settings()
    lat_str, lon_str = stored.get("weather_lat"), stored.get("weather_lon")
    if not lat_str or not lon_str:
        return None
    cached, fresh = _cached(stored)
    if cached and fresh:
        return cached
    try:
        weather = _fetch_forecast(float(lat_str), float(lon_str), get_settings(stored)["units"])
    except (requests.RequestException, KeyError, ValueError, IndexError, TypeError):
        return cached

    db.set_setting("weather_cache_json", json.dumps(weather))
    db.set_setting("weather_cache_at", datetime.now(timezone.utc).isoformat())
    return weather


_refreshing = threading.Lock()


def current(stored: dict | None = None) -> dict | None:
    """For page renders: never waits on the network, except the first time after
    a location or units change (no usable cache at all). A stale forecast is
    shown as-is and refreshed in a background thread for the next page."""
    stored = db.all_settings() if stored is None else stored
    if not stored.get("weather_lat") or not stored.get("weather_lon"):
        return None
    cached, fresh = _cached(stored)
    if cached is None:
        return get_weather()
    if not fresh and _refreshing.acquire(blocking=False):
        def refresh():
            try:
                get_weather()
            finally:
                _refreshing.release()
        threading.Thread(target=refresh, name="weather-refresh", daemon=True).start()
    return cached