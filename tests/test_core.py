"""Core layer (weather, plans_store, planner) without MCP and without the network."""
import datetime as dt
import json

import httpx
import pytest

from conftest import TODAY
from mishwar import planner, plans_store, weather
from mishwar.errors import DateOutOfRange, DuplicatePlan, InvalidInput, PlaceNotFound, ServiceUnavailable, StorageError
from mishwar.models import DayForecast

TOMORROW = (TODAY + dt.timedelta(days=1)).isoformat()


def iso(days: int) -> str:
    return (TODAY + dt.timedelta(days=days)).isoformat()


# --- dates ---------------------------------------------------------------

@pytest.mark.parametrize("days", [0, 1, 15])
def test_forecast_window_accepts_today_to_today_plus_15(days):
    assert weather.parse_forecast_date(iso(days)) == TODAY + dt.timedelta(days=days)


@pytest.mark.parametrize("days", [-1, 16])
def test_forecast_window_rejects_outside(days):
    with pytest.raises(DateOutOfRange, match=r"^DateOutOfRange: .* \(2026-10-23 to 2026-11-07\)"):
        weather.parse_forecast_date(iso(days))


@pytest.mark.parametrize("text", ["24/10/2026", "Saturday", "2026-13-01", ""])
def test_bad_date_format(text):
    with pytest.raises(InvalidInput, match="YYYY-MM-DD"):
        weather.parse_forecast_date(text)


# --- fetch_json (real httpx code, fake transport) ------------------------

def use_transport(monkeypatch, handler):
    monkeypatch.setattr(weather, "_transport", httpx.MockTransport(handler))


async def test_fetch_json_http_503_is_service_unavailable(monkeypatch):
    use_transport(monkeypatch, lambda req: httpx.Response(503))
    with pytest.raises(ServiceUnavailable, match=r"\(HTTP 503\)"):
        await weather.fetch_json(weather.FORECAST_URL, {})


async def test_fetch_json_timeout_is_service_unavailable(monkeypatch):
    def slow(request):
        raise httpx.ReadTimeout("slow", request=request)
    use_transport(monkeypatch, slow)
    with pytest.raises(ServiceUnavailable, match=r"\(timed out\)"):
        await weather.fetch_json(weather.FORECAST_URL, {})


async def test_fetch_json_network_error_is_service_unavailable(monkeypatch):
    def down(request):
        raise httpx.ConnectError("no route", request=request)
    use_transport(monkeypatch, down)
    with pytest.raises(ServiceUnavailable, match="network error"):
        await weather.fetch_json(weather.FORECAST_URL, {})


async def test_fetch_json_api_rejection_is_invalid_input(monkeypatch):
    use_transport(monkeypatch, lambda req: httpx.Response(400, json={"error": True, "reason": "bad start_date"}))
    with pytest.raises(InvalidInput, match="rejected the request: bad start_date"):
        await weather.fetch_json(weather.FORECAST_URL, {})


async def test_outage_switch(monkeypatch):
    monkeypatch.setenv("MISHWAR_SIMULATE_OUTAGE", "1")
    with pytest.raises(ServiceUnavailable, match=r"^ServiceUnavailable: .*\(simulated outage\)\. Nothing was saved"):
        await weather.fetch_json(weather.FORECAST_URL, {})


# --- geocode + forecast --------------------------------------------------

async def test_get_forecast_maps_fields(fake_api):
    fake_api.set(weather_code=61, precipitation_probability_max=40)
    f = await weather.get_forecast("byblos", TOMORROW)
    assert (f.place, f.region, f.date.isoformat()) == ("Byblos", "Mount Lebanon", TOMORROW)
    assert (f.summary, f.rain_probability_pct, f.temp_max_c, f.source) == ("Light rain", 40, 26.0, "open-meteo")
    _, params = fake_api.calls[0]
    assert params["countryCode"] == "LB"
    _, params = fake_api.calls[1]
    assert params["timezone"] == "Asia/Beirut" and params["start_date"] == params["end_date"] == TOMORROW


async def test_unknown_place(fake_api):
    with pytest.raises(PlaceNotFound, match="^PlaceNotFound: No place called 'Atlantis' was found in Lebanon"):
        await weather.get_forecast("Atlantis", TOMORROW)


async def test_empty_results_list_is_not_found(fake_api, monkeypatch):
    async def empty(url, params):
        return {"results": []}
    monkeypatch.setattr(weather, "fetch_json", empty)
    with pytest.raises(PlaceNotFound):
        await weather.geocode("Byblos")


async def test_alias_is_tried_when_plain_search_fails(fake_api):
    f = await weather.get_forecast("Saida", TOMORROW)
    assert f.place == "Sidon"
    assert [p["name"] for _, p in fake_api.calls[:2]] == ["Saida", "Sidon"]


@pytest.mark.parametrize("place", ["B", " ", "x" * 81])
async def test_place_length(fake_api, place):
    with pytest.raises(InvalidInput, match="2–80 characters"):
        await weather.get_forecast(place, TOMORROW)
    assert fake_api.calls == []


async def test_date_checked_before_any_network_call(fake_api):
    with pytest.raises(DateOutOfRange):
        await weather.get_forecast("Byblos", iso(30))
    assert fake_api.calls == []


async def test_unexpected_response_shape(fake_api, monkeypatch):
    async def broken(url, params):
        return await fake_api(url, params) if url == weather.GEOCODE_URL else {"daily": {}}
    monkeypatch.setattr(weather, "fetch_json", broken)
    with pytest.raises(ServiceUnavailable, match="unexpected response"):
        await weather.get_forecast("Byblos", TOMORROW)


async def test_offline_mode_answers_from_saved_samples(monkeypatch):
    monkeypatch.setenv("MISHWAR_OFFLINE", "1")
    f = await weather.get_forecast("Tyre", iso(3))  # alias -> Sour -> saved Tyre sample
    assert (f.place, f.date.isoformat(), f.source) == ("Tyre", iso(3), "offline-sample")


# --- plans store ---------------------------------------------------------

def test_save_writes_the_file(data_file):
    plan = plans_store.save("Byblos souk walk", "Byblos", TOMORROW, "sightseeing", "lunch at the port")
    assert plan.plan_id.startswith("p-") and len(plan.plan_id) == 10
    stored = json.loads(data_file.read_text(encoding="utf-8"))
    assert stored[0]["plan_id"] == plan.plan_id and stored[0]["date"] == TOMORROW
    assert plans_store.get(plan.plan_id) == plan
    assert plans_store.load_all() == [plan]


def test_missing_file_means_no_plans():
    assert plans_store.load_all() == []
    assert plans_store.get("p-00000000") is None


def test_duplicate_is_refused_with_existing_id():
    first = plans_store.save("Beach day", "Batroun", TOMORROW, "beach")
    with pytest.raises(DuplicatePlan) as err:
        plans_store.save("  beach DAY ", "Tyre", TOMORROW, "beach")
    assert err.value.existing_plan_id == first.plan_id
    assert str(err.value).startswith("DuplicatePlan: A plan titled 'beach DAY' on 2026-10-24 already exists")
    plans_store.save("Beach day", "Batroun", iso(2), "beach")  # same title, other date: fine
    assert len(plans_store.load_all()) == 2


@pytest.mark.parametrize("kwargs, message", [
    ({"date": iso(-1)}, r"is in the past \(today is 2026-10-23 in Beirut\)"),
    ({"date": iso(366)}, "more than a year ahead"),
    ({"date": "next week"}, "YYYY-MM-DD"),
    ({"title": "ab"}, "title must be 3–80"),
    ({"activity": "skiing"}, "not a supported activity"),
    ({"notes": "x" * 501}, "at most 500"),
])
def test_save_validation(kwargs, message, data_file):
    args = {"title": "Trip", "place": "Byblos", "date": TOMORROW, "activity": "hike"} | kwargs
    with pytest.raises(InvalidInput, match=message):
        plans_store.save(**args)
    assert not data_file.exists()


def test_corrupt_file_is_storage_error(data_file):
    data_file.parent.mkdir(parents=True)
    data_file.write_text("{not json", encoding="utf-8")
    with pytest.raises(StorageError, match="plans.json is corrupt"):
        plans_store.load_all()


def test_failed_write_keeps_old_file(data_file, monkeypatch):
    plans_store.save("Keep me", "Byblos", TOMORROW, "hike")
    before = data_file.read_text(encoding="utf-8")

    def broken_replace(src, dst):
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(plans_store.os, "replace", broken_replace)
    with pytest.raises(StorageError, match=r"Could not write the saved plans \(Permission denied\)\. The plan was NOT saved"):
        plans_store.save("New one", "Byblos", TOMORROW, "hike")
    assert data_file.read_text(encoding="utf-8") == before


# --- assess (one test per rule row) --------------------------------------

def forecast(**overrides) -> DayForecast:
    values = dict(place="Byblos", region="Mount Lebanon", latitude=34.1, longitude=35.6, date=TODAY,
                  weather_code=1, summary="Mainly clear", temp_min_c=18.0, temp_max_c=26.0,
                  rain_probability_pct=10, wind_max_kmh=12.0, source="open-meteo")
    return DayForecast(**(values | overrides))


@pytest.mark.parametrize("activity, overrides, verdict, reason", [
    ("hike", {"rain_probability_pct": 60}, "not_recommended", "Rain probability 60% (≥ 60%)."),        # R1
    ("hike", {"weather_code": 95}, "not_recommended", "Thunderstorms forecast."),                      # R2
    ("hike", {"rain_probability_pct": 30}, "go_with_caution", "bring a rain jacket"),                  # R3
    ("hike", {"rain_probability_pct": 59}, "go_with_caution", "Rain probability 59% (30–59%)"),         # R3 edge
    ("hike", {"wind_max_kmh": 40}, "go_with_caution", "avoid exposed ridges"),                         # R4
    ("sightseeing", {"wind_max_kmh": 55}, "go_with_caution", "avoid exposed ridges"),                  # R4
    ("beach", {"wind_max_kmh": 40}, "not_recommended", "rough sea"),                                   # R5
    ("hike", {"temp_max_c": 33}, "go_with_caution", "start early and carry water"),                    # R6
    ("beach", {"temp_max_c": 21.9}, "go_with_caution", "too cool for swimming"),                       # R7
    ("hike", {}, "go", "No weather concerns."),                                                        # R8
    ("hike", {"rain_probability_pct": 29, "wind_max_kmh": 39.9, "temp_max_c": 32.9}, "go", "No weather concerns."),
])
def test_assess_rules(activity, overrides, verdict, reason):
    got_verdict, reasons = planner.assess(forecast(**overrides), activity)
    assert got_verdict == verdict
    assert any(reason in r for r in reasons), reasons


def test_assess_worst_verdict_wins_and_all_reasons_kept():
    verdict, reasons = planner.assess(forecast(rain_probability_pct=45, wind_max_kmh=50, temp_max_c=34), "beach")
    assert verdict == "not_recommended"
    assert len(reasons) == 3


def test_assess_indoor_always_go():
    verdict, reasons = planner.assess(forecast(rain_probability_pct=100, weather_code=99, wind_max_kmh=90), "indoor")
    assert verdict == "go"
    assert reasons == ["Indoor plan; outside it will be Mainly clear, 18–26 °C."]


def test_assess_unknown_rain_probability():
    verdict, reasons = planner.assess(forecast(rain_probability_pct=None), "hike")
    assert verdict == "go" and "Rain probability not available." in reasons


# --- plan_day_trip (orchestration) ---------------------------------------

async def test_plan_go_saves(fake_api):
    trip = await planner.plan_day_trip("Byblos", TOMORROW, "hike")
    assert (trip.verdict, trip.saved, trip.message) == ("go", True, f"Saved as {trip.plan_id}.")
    plan = plans_store.get(trip.plan_id)
    assert (plan.title, plan.place, plan.date.isoformat()) == ("Hike in Byblos", "Byblos", TOMORROW)
    assert plan.notes == "Verdict: go. No weather concerns."


async def test_plan_caution_still_saves(fake_api):
    fake_api.set(precipitation_probability_max=45)
    trip = await planner.plan_day_trip("Byblos", TOMORROW, "sightseeing")
    assert trip.verdict == "go_with_caution" and trip.saved
    assert "bring a rain jacket" in plans_store.get(trip.plan_id).notes


async def test_plan_not_recommended_is_not_saved(fake_api, data_file):
    fake_api.set(precipitation_probability_max=80)
    trip = await planner.plan_day_trip("Byblos", TOMORROW, "hike")
    assert (trip.verdict, trip.saved, trip.plan_id) == ("not_recommended", False, None)
    assert trip.message == planner.NOT_SAVED
    assert not data_file.exists()


async def test_plan_forecast_error_saves_nothing(fake_api, data_file):
    plans_store.save("Existing", "Byblos", TOMORROW, "hike")
    before = data_file.read_text(encoding="utf-8")
    with pytest.raises(PlaceNotFound):
        await planner.plan_day_trip("Atlantis", TOMORROW, "hike")
    assert data_file.read_text(encoding="utf-8") == before


async def test_plan_outage_saves_nothing(data_file, monkeypatch):
    monkeypatch.setenv("MISHWAR_SIMULATE_OUTAGE", "1")  # the real fetch_json honours the switch
    with pytest.raises(ServiceUnavailable, match="simulated outage"):
        await planner.plan_day_trip("Byblos", TOMORROW, "hike")
    assert not data_file.exists()


async def test_plan_twice_returns_existing_plan(fake_api):
    first = await planner.plan_day_trip("Byblos", TOMORROW, "hike")
    second = await planner.plan_day_trip("byblos", TOMORROW, "hike")
    assert (second.saved, second.plan_id) == (True, first.plan_id)
    assert second.message == f"Already saved as {first.plan_id}; nothing new was written."
    assert len(plans_store.load_all()) == 1


async def test_plan_storage_failure_says_not_saved(fake_api, monkeypatch):
    def broken_replace(src, dst):
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(plans_store.os, "replace", broken_replace)
    with pytest.raises(StorageError, match=r"^StorageError: The forecast was retrieved \(verdict: go\) but the plan was NOT saved: Permission denied\."):
        await planner.plan_day_trip("Byblos", TOMORROW, "hike")


async def test_plan_rejects_unknown_activity_before_any_call(fake_api):
    with pytest.raises(InvalidInput, match="not a supported activity"):
        await planner.plan_day_trip("Byblos", TOMORROW, "skiing")
    assert fake_api.calls == []
