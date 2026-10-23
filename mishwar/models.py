"""Pydantic models. They are the tools' output schemas, so every field is described."""
import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

Activity = Literal["hike", "beach", "sightseeing", "indoor"]
Verdict = Literal["go", "go_with_caution", "not_recommended"]

ACTIVITIES: tuple[str, ...] = Activity.__args__


class DayForecast(BaseModel):
    """The daily forecast for one place on one date."""

    place: str = Field(description="Resolved place name, e.g. 'Byblos'")
    region: str = Field(description="Governorate the place is in, e.g. 'Mount Lebanon'")
    latitude: float = Field(description="Latitude in decimal degrees")
    longitude: float = Field(description="Longitude in decimal degrees")
    date: dt.date = Field(description="Forecast date (YYYY-MM-DD)")
    weather_code: int = Field(description="WMO weather code for the day")
    summary: str = Field(description="Plain-language weather, e.g. 'Light rain'")
    temp_min_c: float = Field(description="Minimum temperature, °C")
    temp_max_c: float = Field(description="Maximum temperature, °C")
    rain_probability_pct: int | None = Field(description="Highest chance of rain that day, %; null if unknown")
    wind_max_kmh: float = Field(description="Maximum wind speed at 10 m, km/h")
    source: Literal["open-meteo", "offline-sample"] = Field(
        description="'open-meteo' for a live answer, 'offline-sample' when offline mode served a saved response"
    )


class SavedPlan(BaseModel):
    """One saved day-trip plan."""

    plan_id: str = Field(description="Plan id, e.g. 'p-3fa9c2d1'")
    title: str = Field(description="Short title of the plan")
    place: str = Field(description="Place of the trip")
    date: dt.date = Field(description="Trip date (YYYY-MM-DD)")
    activity: Activity = Field(description="Kind of trip")
    notes: str = Field(default="", description="Free-text notes")
    created_at: dt.datetime = Field(description="When the plan was saved (UTC, ISO 8601)")


class TripPlan(BaseModel):
    """Result of plan_day_trip: the forecast, the verdict and whether a plan was saved."""

    forecast: DayForecast = Field(description="The forecast the verdict is based on")
    verdict: Verdict = Field(description="Decided by fixed weather rules, not by the model")
    reasons: list[str] = Field(description="One line per weather rule that fired")
    saved: bool = Field(description="Whether a plan for this trip is in the saved plans after this call")
    plan_id: str | None = Field(description="The saved plan's id (new or already existing); null if not saved")
    message: str = Field(description="One sentence saying what was saved, to relay to the user")
