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


def transport() -> str:
    """'stdio' (development: the host starts the server) or 'http' (demo: the server runs in its own terminal)."""
    value = os.getenv("MCP_TRANSPORT", "stdio").split("#")[0].strip().lower()
    return "http" if value in {"http", "streamable-http"} else "stdio"


def http_url() -> str:
    return os.getenv("MCP_HTTP_URL", "http://127.0.0.1:8000/mcp").split("#")[0].strip()


def server_env() -> dict[str, str]:
    """Settings to hand to a stdio server process.

    The MCP stdio client gives the child only a minimal environment (PATH,
    TEMP, ...), so without this a shell override such as
    MISHWAR_SIMULATE_OUTAGE=1 would silently not reach the server.
    """
    keep = ("MISHWAR_", "MCP_", "PYTHON")
    return {k: v for k, v in os.environ.items() if k.startswith(keep)}
