"""Save real Open-Meteo responses into mishwar/offline_data/ for offline mode (MISHWAR_OFFLINE=1).

For each name: the geocoding response, and a 16-day forecast for the place it
resolves to. Names the geocoder does not know are reported and skipped.
Run again any time to refresh the samples.
"""
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mishwar.weather import DAILY_FIELDS, FORECAST_URL, GEOCODE_URL, OFFLINE_DIR  # noqa: E402

NAMES = ["Byblos", "Baalbek", "Batroun", "Sour", "Sidon", "Tripoli", "Beirut", "Zahle",
         "Bsharri", "Ehden", "Jounieh", "Faraya", "Cedars"]


def get(client: httpx.Client, url: str, params: dict) -> dict:
    for attempt in range(4):
        try:
            response = client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            print(f"  retry {attempt + 1} after {type(e).__name__}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))
    raise SystemExit(f"giving up on {url}")


def main() -> None:
    (OFFLINE_DIR / "geocode").mkdir(parents=True, exist_ok=True)
    (OFFLINE_DIR / "forecast").mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=20) as client:
        for name in NAMES:
            geo = get(client, GEOCODE_URL, {"name": name, "count": 1, "language": "en", "format": "json", "countryCode": "LB"})
            if not geo.get("results"):
                print(f"{name:<8} not found by the geocoder, skipped")
                continue
            place = geo["results"][0]
            fc = get(client, FORECAST_URL, {"latitude": place["latitude"], "longitude": place["longitude"],
                                            "daily": DAILY_FIELDS, "timezone": "Asia/Beirut", "forecast_days": 16})
            (OFFLINE_DIR / "geocode" / f"{name.lower()}.json").write_text(json.dumps(geo, indent=1), encoding="utf-8")
            (OFFLINE_DIR / "forecast" / f"{place['id']}.json").write_text(json.dumps(fc, indent=1), encoding="utf-8")
            print(f"{name:<8} -> {place['name']} ({place.get('admin1', '')}), {len(fc['daily']['time'])} days")


if __name__ == "__main__":
    main()
