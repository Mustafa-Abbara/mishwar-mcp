"""Orchestration core: forecast -> fixed go/no-go rules -> save.

plan_day_trip calls the other two cores as plain Python (never through MCP),
and the verdict comes from the rule table in docs/tool_design.md §6, not from
the model.
"""
from . import plans_store, validation, weather
from .errors import DuplicatePlan, StorageError
from .models import DayForecast, TripPlan, Verdict

SEVERITY: dict[Verdict, int] = {"go": 0, "go_with_caution": 1, "not_recommended": 2}

NOT_SAVED = "Not saved because the trip is not recommended. Call save_trip_plan if the user still wants it saved."


def assess(forecast: DayForecast, activity: str) -> tuple[Verdict, list[str]]:
    """Apply the rule table. The worst verdict wins; every rule that fired adds a reason."""
    f = forecast
    if activity == "indoor":
        return "go", [f"Indoor plan; outside it will be {f.summary}, {f.temp_min_c:.0f}–{f.temp_max_c:.0f} °C."]

    fired: list[tuple[Verdict, str]] = []
    rain = f.rain_probability_pct
    if rain is not None and rain >= 60:
        fired.append(("not_recommended", f"Rain probability {rain}% (≥ 60%)."))
    elif rain is not None and rain >= 30:
        fired.append(("go_with_caution", f"Rain probability {rain}% (30–59%): bring a rain jacket."))
    if 95 <= f.weather_code <= 99:
        fired.append(("not_recommended", "Thunderstorms forecast."))
    if f.wind_max_kmh >= 40:
        if activity == "beach":
            fired.append(("not_recommended", f"Wind up to {f.wind_max_kmh:.0f} km/h: rough sea."))
        else:
            fired.append(("go_with_caution", f"Wind up to {f.wind_max_kmh:.0f} km/h: avoid exposed ridges."))
    if f.temp_max_c >= 33:
        fired.append(("go_with_caution", f"Up to {f.temp_max_c:.0f} °C: start early and carry water."))
    if activity == "beach" and f.temp_max_c < 22:
        fired.append(("go_with_caution", f"Only {f.temp_max_c:.0f} °C: too cool for swimming."))

    notes = ["Rain probability not available."] if rain is None else []
    if not fired:
        return "go", ["No weather concerns."] + notes
    verdict = max((v for v, _ in fired), key=SEVERITY.__getitem__)
    return verdict, [reason for _, reason in fired] + notes


async def plan_day_trip(place: str, date: str, activity: str) -> TripPlan:
    validation.check_activity(activity)
    forecast = await weather.get_forecast(place, date)  # any failure propagates: nothing is saved
    verdict, reasons = assess(forecast, activity)

    def result(saved: bool, plan_id: str | None, message: str) -> TripPlan:
        return TripPlan(forecast=forecast, verdict=verdict, reasons=reasons, saved=saved, plan_id=plan_id, message=message)

    if verdict == "not_recommended":
        return result(False, None, NOT_SAVED)

    title = f"{activity.capitalize()} in {forecast.place}"
    notes = f"Verdict: {verdict}. " + " ".join(reasons)
    try:
        plan = plans_store.save(title, forecast.place, forecast.date.isoformat(), activity, notes[: plans_store.MAX_NOTES])
    except DuplicatePlan as e:
        return result(True, e.existing_plan_id, f"Already saved as {e.existing_plan_id}; nothing new was written.")
    except StorageError as e:
        raise StorageError(
            f"The forecast was retrieved (verdict: {verdict}) but the plan was NOT saved: {e.reason}. Try again.",
            e.reason,
        ) from e
    return result(True, plan.plan_id, f"Saved as {plan.plan_id}.")
