"""The Mishwar MCP server: 3 tools + 2 resources over stdio or Streamable HTTP.

Thin by design: the type hints become the input schemas, the Pydantic return
types become the output schemas, each tool calls one core function, and
domain errors become ToolError messages (is_error=true on the wire).

Run:  python -m mishwar.server                         (stdio)
      MCP_TRANSPORT=http python -m mishwar.server      (http://127.0.0.1:8000/mcp)
"""
import logging
import sys
from contextlib import contextmanager
from typing import Annotated
from urllib.parse import urlparse

from fastmcp import FastMCP
from fastmcp.exceptions import ResourceError, ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from . import config, planner, plans_store, weather
from .errors import ToolkitError
from .models import Activity, DayForecast, SavedPlan, TripPlan

# In stdio mode stdout carries the protocol, so every log line goes to stderr.
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="[SERVER] %(message)s")
log = logging.getLogger("mishwar")

mcp = FastMCP(
    "mishwar",
    instructions=(
        "Tools to plan weather-aware day trips in Lebanon. Dates are YYYY-MM-DD; "
        "forecasts cover today up to 15 days ahead (Beirut time)."
    ),
    mask_error_details=True,  # unexpected bugs reach the client as a generic error; ToolError text always gets through
)

Place = Annotated[str, Field(description="Town or site in Lebanon, e.g. 'Byblos' or 'Baalbek'", min_length=2, max_length=80)]
IsoDate = Annotated[str, Field(description="Date in YYYY-MM-DD format. Convert words like 'next Saturday' to a date first.")]
ActivityArg = Annotated[Activity, Field(description="Kind of trip: hike, beach, sightseeing or indoor")]


@contextmanager
def clear_errors(tool: str):
    """Turn a domain error into a ToolError with the same user-safe text."""
    try:
        yield
    except ToolkitError as e:
        log.info("x %s failed -> %s", tool, e)
        raise ToolError(str(e)) from e


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True))
async def get_weather_forecast(place: Place, date: IsoDate) -> DayForecast:
    """Get the daily weather forecast for one place in Lebanon on one date (today up to 15 days ahead).

    Returns temperatures, rain probability and wind. Read-only: it never saves anything.
    """
    log.info("<- get_weather_forecast(place=%r, date=%r)", place, date)
    with clear_errors("get_weather_forecast"):
        forecast = await weather.get_forecast(place, date)
    log.info("-> %s %s: %s, %.0f-%.0f C, rain %s%%", forecast.place, forecast.date, forecast.summary,
             forecast.temp_min_c, forecast.temp_max_c, forecast.rain_probability_pct)
    return forecast


@mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False))
async def save_trip_plan(
    title: Annotated[str, Field(description="Short name for the plan, e.g. 'Byblos souk walk'", min_length=3, max_length=80)],
    place: Place,
    date: Annotated[str, Field(description="Trip date in YYYY-MM-DD format, today or later (up to a year ahead)")],
    activity: ActivityArg,
    notes: Annotated[str, Field(description="Optional free-text notes", max_length=500)] = "",
) -> SavedPlan:
    """Save one day-trip plan to the user's saved plans.

    Refuses a duplicate (same title and date). Does not check the weather; use plan_day_trip for that.
    """
    log.info("<- save_trip_plan(title=%r, place=%r, date=%r, activity=%r)", title, place, date, activity)
    with clear_errors("save_trip_plan"):
        plan = plans_store.save(title, place, date, activity, notes)
    log.info("-> saved %s", plan.plan_id)
    return plan


@mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=True))
async def plan_day_trip(place: Place, date: IsoDate, activity: ActivityArg) -> TripPlan:
    """Plan a day trip in Lebanon: gets the forecast for the place and date, judges it for the activity
    with fixed weather rules, and saves the plan unless the trip is not recommended.

    Use this when the user wants a recommendation; use the other two tools for a plain forecast or a plain save.
    """
    log.info("<- plan_day_trip(place=%r, date=%r, activity=%r): forecast -> assess -> save", place, date, activity)
    with clear_errors("plan_day_trip"):
        trip = await planner.plan_day_trip(place, date, activity)
    log.info("-> verdict %s, saved=%s %s", trip.verdict, trip.saved, trip.plan_id or "")
    return trip


@mcp.resource("trips://plans", mime_type="application/json")
def all_saved_plans() -> list[dict]:
    """All saved trip plans, newest first (read-only)."""
    try:
        return [p.model_dump(mode="json") for p in reversed(plans_store.load_all())]
    except ToolkitError as e:
        raise ResourceError(str(e)) from e


@mcp.resource("trips://plans/{plan_id}", mime_type="application/json")
def one_saved_plan(plan_id: str) -> dict:
    """One saved trip plan by its id, e.g. trips://plans/p-3fa9c2d1 (read-only)."""
    try:
        plan = plans_store.get(plan_id)
    except ToolkitError as e:
        raise ResourceError(str(e)) from e
    if plan is None:
        raise ResourceError(f"PlanNotFound: No saved plan has id '{plan_id}'. Read trips://plans to see the saved ids.")
    return plan.model_dump(mode="json")


def main() -> None:
    if config.offline():
        log.warning("OFFLINE MODE is on: weather answers come from saved samples")
    if config.simulate_outage():
        log.warning("SIMULATED OUTAGE is on: every weather call will fail")
    log.info("data folder: %s", config.data_dir())
    if config.transport() == "http":
        url = urlparse(config.http_url())
        log.info("listening on %s", config.http_url())
        mcp.run(transport="http", host=url.hostname, port=url.port, path=url.path or "/mcp", show_banner=False)
    else:
        mcp.run(show_banner=False)


if __name__ == "__main__":
    main()
