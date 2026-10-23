"""Action core: the saved plans, kept as a JSON list in <data_dir>/plans.json."""
import datetime as dt
import json
import os
import uuid

from pydantic import ValidationError

from . import config, validation
from .errors import DuplicatePlan, InvalidInput, StorageError
from .models import SavedPlan

MAX_DAYS_AHEAD = 365
MAX_NOTES = 500


def _path():
    return config.data_dir() / "plans.json"


def load_all() -> list[SavedPlan]:
    """All saved plans in the order they were saved. A missing file means no plans yet."""
    path = _path()
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return [SavedPlan.model_validate(item) for item in raw]
    except OSError as e:
        raise StorageError.read_failed(e.strerror or type(e).__name__) from e
    except (ValueError, TypeError, ValidationError) as e:
        raise StorageError.read_failed("plans.json is corrupt") from e


def get(plan_id: str) -> SavedPlan | None:
    return next((p for p in load_all() if p.plan_id == plan_id), None)


def save(title: str, place: str, date: str, activity: str, notes: str = "") -> SavedPlan:
    title = str(title).strip()
    if not 3 <= len(title) <= 80:
        raise InvalidInput(f"The title must be 3–80 characters; got {len(title)}.")
    place = validation.check_place(place)
    activity = validation.check_activity(activity)
    notes = str(notes).strip()
    if len(notes) > MAX_NOTES:
        raise InvalidInput(f"The notes must be at most {MAX_NOTES} characters; got {len(notes)}.")
    day = validation.parse_iso_date(date)
    today = validation.today_beirut()
    if day < today:
        raise InvalidInput(f"{day} is in the past (today is {today} in Beirut). Choose today or a later date.")
    if day > today + dt.timedelta(days=MAX_DAYS_AHEAD):
        raise InvalidInput(f"{day} is more than a year ahead. Choose a date up to {today + dt.timedelta(days=MAX_DAYS_AHEAD)}.")

    plans = load_all()
    for existing in plans:
        if existing.title.casefold() == title.casefold() and existing.date == day:
            raise DuplicatePlan(title, day.isoformat(), existing.plan_id)

    plan = SavedPlan(
        plan_id=f"p-{uuid.uuid4().hex[:8]}",
        title=title,
        place=place,
        date=day,
        activity=activity,
        notes=notes,
        created_at=dt.datetime.now(dt.timezone.utc).replace(microsecond=0),
    )
    _write(plans + [plan])
    return plan


def _write(plans: list[SavedPlan]) -> None:
    """Atomic write: a crash leaves either the old file or the new one, never half a file."""
    path = _path()
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps([p.model_dump(mode="json") for p in plans], indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as e:
        raise StorageError.write_failed(e.strerror or type(e).__name__) from e
