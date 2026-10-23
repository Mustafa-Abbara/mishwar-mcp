"""Shared fixtures. Every non-live test runs with no network, a frozen 'today'
and a temporary data folder, whatever .env says."""
import datetime as dt
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mishwar import validation, weather  # noqa: E402

TODAY = dt.date(2026, 10, 23)

BYBLOS = {"id": 273203, "name": "Byblos", "latitude": 34.12111, "longitude": 35.64806,
          "country_code": "LB", "country": "Lebanon", "admin1": "Mount Lebanon", "timezone": "Asia/Beirut"}
SIDON = {"id": 268064, "name": "Sidon", "latitude": 33.55751, "longitude": 35.37148,
         "country_code": "LB", "country": "Lebanon", "admin1": "South Governorate", "timezone": "Asia/Beirut"}


def _refuse_network(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"offline test tried to reach the network: {request.url}")


@pytest.fixture(autouse=True)
def isolated(request, monkeypatch, tmp_path):
    for flag in ("MISHWAR_OFFLINE", "MISHWAR_SIMULATE_OUTAGE"):
        monkeypatch.setenv(flag, "0")
    monkeypatch.setenv("MISHWAR_DATA_DIR", str(tmp_path / "data"))
    if request.node.get_closest_marker("live") is None:
        monkeypatch.setattr(weather, "_transport", httpx.MockTransport(_refuse_network))
        monkeypatch.setattr(validation, "today_beirut", lambda: TODAY)


@pytest.fixture
def data_file(tmp_path) -> Path:
    return tmp_path / "data" / "plans.json"


class FakeOpenMeteo:
    """Stands in for weather.fetch_json: knows Byblos and Sidon, and serves one configurable day."""

    def __init__(self):
        self.places = {"byblos": BYBLOS, "sidon": SIDON}
        self.day = {"weather_code": 1, "temperature_2m_max": 26.0, "temperature_2m_min": 18.0,
                    "precipitation_probability_max": 10, "wind_speed_10m_max": 12.0}
        self.calls: list[tuple[str, dict]] = []

    def set(self, **values):
        self.day.update(values)

    async def __call__(self, url: str, params: dict) -> dict:
        self.calls.append((url, params))
        if url == weather.GEOCODE_URL:
            record = self.places.get(params["name"].lower())
            return {"results": [record]} if record else {"generationtime_ms": 0.1}
        return {"daily": {"time": [params["start_date"]], **{k: [v] for k, v in self.day.items()}}}


@pytest.fixture
def fake_api(monkeypatch) -> FakeOpenMeteo:
    fake = FakeOpenMeteo()
    monkeypatch.setattr(weather, "fetch_json", fake)
    return fake
