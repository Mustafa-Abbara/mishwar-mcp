"""Input checks shared by the three cores. "Today" is always Beirut's today."""
import datetime as dt
from zoneinfo import ZoneInfo

from .errors import InvalidInput
from .models import ACTIVITIES

BEIRUT = ZoneInfo("Asia/Beirut")


def today_beirut() -> dt.date:
    return dt.datetime.now(BEIRUT).date()


def parse_iso_date(text: str) -> dt.date:
    try:
        return dt.date.fromisoformat(str(text).strip())
    except ValueError:
        raise InvalidInput(f"'{text}' is not a date in YYYY-MM-DD format. Convert it first, e.g. '2026-10-24'.") from None


def check_place(place: str) -> str:
    name = str(place).strip()
    if not 2 <= len(name) <= 80:
        raise InvalidInput(f"The place name must be 2–80 characters; got {len(name)}.")
    return name


def check_activity(activity: str) -> str:
    if activity not in ACTIVITIES:
        raise InvalidInput(f"'{activity}' is not a supported activity. Use one of: {', '.join(ACTIVITIES)}.")
    return activity
