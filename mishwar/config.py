"""Settings read from the environment (.env at the repo root).

Every getter reads os.environ on each call, so tests can change a setting
with monkeypatch.setenv and see the effect immediately.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

# The stdio server is started by the host, possibly from another directory,
# so .env is found relative to this file, not to the current directory.
load_dotenv(ROOT / ".env")


def _flag(name: str) -> bool:
    return os.getenv(name, "0").strip().lower() in {"1", "true", "yes", "on"}


def data_dir() -> Path:
    """Absolute folder that holds plans.json (relative paths are taken from the repo root)."""
    path = Path(os.getenv("MISHWAR_DATA_DIR", "data"))
    return path if path.is_absolute() else ROOT / path


def country_code() -> str:
    return os.getenv("MISHWAR_COUNTRY_CODE", "LB")


def simulate_outage() -> bool:
    """MISHWAR_SIMULATE_OUTAGE=1 makes every weather call fail as if Open-Meteo were down."""
    return _flag("MISHWAR_SIMULATE_OUTAGE")


def offline() -> bool:
    """MISHWAR_OFFLINE=1 answers weather calls from saved responses (demo-day safety net)."""
    return _flag("MISHWAR_OFFLINE")
