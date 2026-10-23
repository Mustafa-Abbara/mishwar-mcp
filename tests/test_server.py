"""The MCP server through FastMCP's in-memory client: real protocol, no subprocess, no network."""
import datetime as dt
import json

import pytest
from fastmcp import Client
from mcp.shared.exceptions import MCPError

from conftest import TODAY
from mishwar import plans_store, weather
from mishwar.server import mcp

TOMORROW = (TODAY + dt.timedelta(days=1)).isoformat()
REAL_FETCH_JSON = weather.fetch_json  # captured before any fixture patches it


@pytest.fixture
async def client(fake_api):
    async with Client(mcp) as c:
        yield c


async def call(client, tool, **args):
    return await client.call_tool(tool, args, raise_on_error=False)


def error_text(result) -> str:
    assert result.is_error, result.structured_content
    return result.content[0].text


# --- get_weather_forecast (Data) -----------------------------------------

async def test_forecast_ok(client):
    r = await call(client, "get_weather_forecast", place="Byblos", date=TOMORROW)
    assert not r.is_error
    assert r.structured_content["place"] == "Byblos"
    assert r.structured_content["date"] == TOMORROW


async def test_forecast_unknown_place_is_clear_error(client):
    text = error_text(await call(client, "get_weather_forecast", place="Atlantis", date=TOMORROW))
    assert text.startswith("PlaceNotFound: No place called 'Atlantis' was found in Lebanon.")


async def test_forecast_date_out_of_range(client):
    text = error_text(await call(client, "get_weather_forecast", place="Byblos", date="2027-01-01"))
    assert text.startswith("DateOutOfRange: 2027-01-01 is outside the forecast window")


async def test_forecast_service_down(client, monkeypatch):
    monkeypatch.setattr(weather, "fetch_json", REAL_FETCH_JSON)  # real code path, so the outage switch is honoured
    monkeypatch.setenv("MISHWAR_SIMULATE_OUTAGE", "1")
    text = error_text(await call(client, "get_weather_forecast", place="Byblos", date=TOMORROW))
    assert text.startswith("ServiceUnavailable:") and "simulated outage" in text


async def test_forecast_place_too_short_rejected_by_schema(client, fake_api):
    r = await call(client, "get_weather_forecast", place="B", date=TOMORROW)
    assert r.is_error and fake_api.calls == []


# --- save_trip_plan (Action) ---------------------------------------------

async def test_save_ok(client):
    r = await call(client, "save_trip_plan", title="Souk walk", place="Byblos", date=TOMORROW,
                   activity="sightseeing", notes="lunch at the port")
    assert not r.is_error
    plan_id = r.structured_content["plan_id"]
    assert plans_store.get(plan_id).notes == "lunch at the port"


async def test_save_duplicate_is_clear_error(client):
    await call(client, "save_trip_plan", title="Souk walk", place="Byblos", date=TOMORROW, activity="sightseeing")
    text = error_text(await call(client, "save_trip_plan", title="souk walk", place="Byblos", date=TOMORROW, activity="hike"))
    assert text.startswith("DuplicatePlan: A plan titled 'souk walk' on 2026-10-24 already exists (p-")


async def test_save_past_date_is_clear_error(client):
    text = error_text(await call(client, "save_trip_plan", title="Too late", place="Byblos", date="2026-10-01", activity="hike"))
    assert text.startswith("InvalidInput: 2026-10-01 is in the past")


async def test_invalid_activity_rejected_by_schema_before_code_runs(client, data_file):
    text = error_text(await call(client, "save_trip_plan", title="Ski day", place="Faraya", date=TOMORROW, activity="skiing"))
    assert "activity" in text and "'hike', 'beach', 'sightseeing' or 'indoor'" in text
    assert not data_file.exists()


# --- plan_day_trip (Orchestration) ---------------------------------------

async def test_plan_ok_saves(client):
    r = await call(client, "plan_day_trip", place="Byblos", date=TOMORROW, activity="hike")
    trip = r.structured_content
    assert (trip["verdict"], trip["saved"]) == ("go", True)
    assert plans_store.get(trip["plan_id"]).title == "Hike in Byblos"


async def test_plan_not_recommended_not_saved(client, fake_api, data_file):
    fake_api.set(weather_code=95)
    trip = (await call(client, "plan_day_trip", place="Byblos", date=TOMORROW, activity="beach")).structured_content
    assert (trip["verdict"], trip["saved"], trip["plan_id"]) == ("not_recommended", False, None)
    assert "Thunderstorms forecast." in trip["reasons"]
    assert not data_file.exists()


async def test_plan_forecast_failure_leaves_store_empty(client, data_file):
    text = error_text(await call(client, "plan_day_trip", place="Atlantis", date=TOMORROW, activity="hike"))
    assert text.startswith("PlaceNotFound:")
    assert not data_file.exists()


async def test_plan_storage_failure_says_not_saved(client, monkeypatch):
    def broken_replace(src, dst):
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(plans_store.os, "replace", broken_replace)
    text = error_text(await call(client, "plan_day_trip", place="Byblos", date=TOMORROW, activity="hike"))
    assert text.startswith("StorageError: The forecast was retrieved (verdict: go) but the plan was NOT saved")


async def test_unexpected_bug_is_masked(client, monkeypatch):
    async def bug(*args):
        raise RuntimeError("secret internal detail")
    monkeypatch.setattr("mishwar.planner.plan_day_trip", bug)
    text = error_text(await call(client, "plan_day_trip", place="Byblos", date=TOMORROW, activity="hike"))
    assert "secret internal detail" not in text


# --- resources -----------------------------------------------------------

async def read_json(client, uri):
    contents = await client.read_resource(uri)
    assert contents[0].mime_type == "application/json"
    return json.loads(contents[0].text)


async def test_plans_resource_newest_first(client):
    assert await read_json(client, "trips://plans") == []
    await call(client, "save_trip_plan", title="First", place="Byblos", date=TOMORROW, activity="hike")
    await call(client, "save_trip_plan", title="Second", place="Sidon", date=TOMORROW, activity="beach")
    plans = await read_json(client, "trips://plans")
    assert [p["title"] for p in plans] == ["Second", "First"]


async def test_one_plan_resource(client):
    r = await call(client, "save_trip_plan", title="First", place="Byblos", date=TOMORROW, activity="hike")
    plan_id = r.structured_content["plan_id"]
    assert (await read_json(client, f"trips://plans/{plan_id}"))["title"] == "First"


async def test_unknown_plan_id_is_clear_error(client):
    with pytest.raises(MCPError, match=r"PlanNotFound: No saved plan has id 'p-nope'"):
        await client.read_resource("trips://plans/p-nope")
