"""The whole chain with a real LLM: agent -> MCP client -> stdio server -> Open-Meteo -> back.

Run with: pytest -m live   (about 12 LLM requests; answers vary, so assertions stay loose)
Each test gets its own temporary data folder, which config.server_env() passes to the server.
"""
import datetime as dt

import pytest

from agent.host import ask, build_agent, make_mcp_client, read_plans
from mishwar.validation import today_beirut

pytestmark = pytest.mark.live


@pytest.fixture
async def session():
    async with make_mcp_client("stdio") as server:
        yield server, build_agent(server)


async def test_weather_question_uses_data_tool(session):
    server, agent = session
    turn, _ = await ask(agent, [], "What's the weather in Byblos tomorrow?", verbose=False)
    assert turn.tools_called == ["get_weather_forecast"]
    assert "°" in turn.answer or "C" in turn.answer


async def test_save_request_uses_action_tool(session):
    server, agent = session
    day = (today_beirut() + dt.timedelta(days=5)).isoformat()
    turn, _ = await ask(agent, [], f"Save a plan called 'Jeita grotto visit' on {day}, indoor.", verbose=False)
    assert turn.tools_called == ["save_trip_plan"]
    assert [p["title"] for p in await read_plans(server)] == ["Jeita grotto visit"]


async def test_planning_request_uses_orchestration_tool_only(session):
    server, agent = session
    turn, _ = await ask(agent, [], "Should I go hiking in Ehden next Saturday? Plan it if it's fine.", verbose=False)
    assert turn.tools_called == ["plan_day_trip"]  # not get_weather_forecast + save_trip_plan separately
    plans = await read_plans(server)
    assert len(plans) <= 1  # saved only if the verdict allowed it
    if plans:
        assert plans[0]["plan_id"] in turn.answer


async def test_unknown_place_is_explained(session):
    server, agent = session
    turn, _ = await ask(agent, [], "What's the weather in Atlantis tomorrow?", verbose=False)
    assert turn.tools_called == ["get_weather_forecast"]
    assert "Atlantis" in turn.answer
    assert any(w in turn.answer.lower() for w in ("couldn't", "could not", "not find", "spelling", "no place"))


async def test_saved_plans_answered_from_resource_without_tools(session):
    server, agent = session
    day = (today_beirut() + dt.timedelta(days=3)).isoformat()
    _, history = await ask(agent, [], f"Remember my trip 'Cedars picnic' in Bsharri on {day}, sightseeing.", verbose=False)
    turn, _ = await ask(agent, history, "Which trips have I saved?", verbose=False)
    assert turn.tools_called == []
    assert "Cedars picnic" in turn.answer
