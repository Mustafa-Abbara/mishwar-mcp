"""Live checks against the real Open-Meteo API. Run with: pytest -m live"""
import datetime as dt

import pytest

from mishwar import validation, weather

pytestmark = pytest.mark.live


@pytest.mark.parametrize("alias, target", sorted(weather.ALIASES.items()))
async def test_alias_target_is_known_to_the_geocoder(alias, target):
    record = await weather._search(target)
    assert record is not None, f"alias {alias!r} points to {target!r}, which the geocoder does not know"
    assert record["country_code"] == "LB"


async def test_real_forecast_for_byblos_tomorrow():
    tomorrow = (validation.today_beirut() + dt.timedelta(days=1)).isoformat()
    f = await weather.get_forecast("Byblos", tomorrow)
    assert f.place == "Byblos" and f.source == "open-meteo"
    assert -20 < f.temp_min_c <= f.temp_max_c < 55


async def test_real_unknown_place():
    with pytest.raises(weather.PlaceNotFound):
        await weather.geocode("Atlantis")
