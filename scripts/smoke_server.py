"""Stage 4: talk to the real server process through the Agents SDK's MCP client (no LLM).

    python scripts/smoke_server.py stdio    # starts the server itself
    python scripts/smoke_server.py http     # server must already run: MCP_TRANSPORT=http python -m mishwar.server

Lists the tools and resources, calls each tool once plus one failure case,
and reads the saved plans. Stands in for the MCP Inspector (needs Node.js).
"""
import asyncio
import datetime as dt
import json
import sys
from pathlib import Path

from agents.mcp import MCPServerStdio, MCPServerStreamableHttp

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from mishwar import config  # noqa: E402
from mishwar.validation import today_beirut  # noqa: E402


def connect(mode: str):
    if mode == "http":
        return MCPServerStreamableHttp(name="mishwar", params={"url": config.http_url()}, client_session_timeout_seconds=30)
    return MCPServerStdio(
        name="mishwar",
        params={"command": sys.executable, "args": ["-m", "mishwar.server"], "cwd": str(ROOT), "env": config.server_env()},
        client_session_timeout_seconds=30,
    )


def show(label: str, result) -> None:
    text = result.content[0].text if result.content else ""
    print(f"\n{label}\n  is_error: {result.is_error}\n  {text[:300]}")


async def main(mode: str) -> None:
    day = (today_beirut() + dt.timedelta(days=2)).isoformat()
    async with connect(mode) as server:
        print(f"=== connected over {mode} ===")
        for tool in await server.list_tools():
            print(f"TOOL {tool.name}: {tool.description.splitlines()[0]}")
        resources = await server.list_resources()
        templates = await server.list_resource_templates()
        print("RESOURCES:", [str(r.uri) for r in resources.resources], [t.uri_template for t in templates.resource_templates])

        show(f"get_weather_forecast(Byblos, {day})", await server.call_tool("get_weather_forecast", {"place": "Byblos", "date": day}))
        show("get_weather_forecast(Atlantis)  <- failure case", await server.call_tool("get_weather_forecast", {"place": "Atlantis", "date": day}))
        show("save_trip_plan(...)", await server.call_tool("save_trip_plan", {
            "title": f"Smoke test {mode}", "place": "Byblos", "date": day, "activity": "sightseeing"}))
        show(f"plan_day_trip(Batroun, {day}, beach)", await server.call_tool("plan_day_trip", {"place": "Batroun", "date": day, "activity": "beach"}))

        plans = await server.read_resource("trips://plans")
        print("\ntrips://plans ->", [p["title"] for p in json.loads(plans.contents[0].text)])


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "stdio"))
