"""Domain errors. Each message is safe to show the user and follows the style
in docs/tool_design.md §5: '<ErrorType>: <what went wrong>. <How to fix it>.'

The type name is prefixed automatically, so str(error) is the full text the
MCP layer passes on unchanged.
"""


class ToolkitError(Exception):
    """Base class for every expected, user-facing failure."""

    def __init__(self, message: str):
        super().__init__(f"{type(self).__name__}: {message}")


class InvalidInput(ToolkitError):
    """An argument has the wrong format or is out of its allowed range."""


class PlaceNotFound(ToolkitError):
    """The geocoder found no place with that name in Lebanon."""


class DateOutOfRange(ToolkitError):
    """The date is outside the forecast window (today to today + 15)."""


class ServiceUnavailable(ToolkitError):
    """Open-Meteo could not be reached, timed out, failed, or the outage switch is on."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(
            f"The weather service (Open-Meteo) did not respond ({reason}). "
            "Nothing was saved. Try again in a minute."
        )


class DuplicatePlan(ToolkitError):
    """A plan with the same title and date is already saved."""

    def __init__(self, title: str, date: str, existing_plan_id: str):
        self.existing_plan_id = existing_plan_id
        super().__init__(
            f"A plan titled '{title}' on {date} already exists ({existing_plan_id}). "
            "Use a different title or date."
        )


class StorageError(ToolkitError):
    """plans.json could not be read or written."""

    def __init__(self, message: str, reason: str):
        self.reason = reason
        super().__init__(message)

    @classmethod
    def write_failed(cls, reason: str) -> "StorageError":
        return cls(f"Could not write the saved plans ({reason}). The plan was NOT saved.", reason)

    @classmethod
    def read_failed(cls, reason: str) -> "StorageError":
        return cls(f"Could not read the saved plans ({reason}). Fix or remove data/plans.json.", reason)
