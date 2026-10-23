"""The PDF's design rules, checked on what an MCP client actually sees (tools/list)."""
import re

import pytest
from fastmcp import Client

from mishwar.server import mcp

DATA, ACTION, ORCHESTRATION = "get_weather_forecast", "save_trip_plan", "plan_day_trip"


@pytest.fixture
async def tools():
    async with Client(mcp) as c:
        return {t.name: t for t in await c.list_tools()}


def first_sentence(text: str) -> str:
    return re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0]


async def test_exactly_three_tools(tools):
    assert sorted(tools) == sorted([DATA, ACTION, ORCHESTRATION])


async def test_every_tool_documented(tools):
    for name, tool in tools.items():
        assert len(tool.description) >= 40, name
        assert tool.output_schema and tool.output_schema.get("properties"), f"{name} has no output schema"
        for arg, schema in tool.input_schema["properties"].items():
            assert schema.get("description"), f"{name}.{arg} has no description"
            assert "type" in schema or "enum" in schema, f"{name}.{arg} has no type"


async def test_annotations(tools):
    assert tools[DATA].annotations.read_only_hint is True
    assert tools[ACTION].annotations.read_only_hint is False
    assert tools[ORCHESTRATION].annotations.read_only_hint is False
    assert not any(t.annotations.destructive_hint for t in tools.values())


async def test_single_purpose_wording(tools):
    # The PDF's "and" test applies to the Data and Action tools. The Orchestration
    # tool is exempt on purpose: listing the steps it coordinates is its job.
    for name in (DATA, ACTION):
        assert " and " not in first_sentence(tools[name].description), name


async def test_activity_is_a_closed_set(tools):
    for name in (ACTION, ORCHESTRATION):
        assert tools[name].input_schema["properties"]["activity"]["enum"] == ["hike", "beach", "sightseeing", "indoor"]
