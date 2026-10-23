"""The MCP host: a chat loop around an Agents SDK agent whose tools come from the Mishwar MCP server.

    python -m agent.host                      # stdio: starts the server itself
    MCP_TRANSPORT=http python -m agent.host   # http: connect to a server already running in another terminal

Commands: /plans (the host reads the trips://plans resource), /help, exit.
Each tool call is printed as it crosses host -> client -> server -> back.
"""
import asyncio
import datetime as dt
import json
import sys
from dataclasses import dataclass, field

import openai
from agents import Agent, MaxTurnsExceeded, RunHooks, Runner
from agents.mcp import MCPServer, MCPServerStdio, MCPServerStreamableHttp

from mishwar import config
from mishwar.validation import today_beirut

from .llm import build_model, model_name, model_settings

MAX_PLANS_IN_PROMPT = 20


def make_mcp_client(transport: str | None = None, tool_filter=None) -> MCPServer:
    """The MCP client: one dedicated connection to one server. tool_filter can hide tools (evaluation only)."""
    if (transport or config.transport()) == "http":
        return MCPServerStreamableHttp(
            name="mishwar",
            params={"url": config.http_url(), "timeout": 30},
            cache_tools_list=True,
            tool_filter=tool_filter,
            client_session_timeout_seconds=30,  # the SDK default of 5 s is shorter than a slow weather call
        )
    return MCPServerStdio(
        name="mishwar",
        params={
            "command": sys.executable,  # the same venv Python, never a bare "python"
            "args": ["-m", "mishwar.server"],
            "cwd": str(config.ROOT),
            "env": config.server_env(),  # merged over the minimal default env, so MISHWAR_* overrides arrive
        },
        cache_tools_list=True,
        tool_filter=tool_filter,
        client_session_timeout_seconds=30,
    )


async def read_plans(server: MCPServer) -> list[dict]:
    result = await server.read_resource("trips://plans")
    return json.loads(result.contents[0].text)


def format_plans(plans: list[dict]) -> str:
    if not plans:
        return "(no saved plans yet)"
    return "\n".join(f"- {p['plan_id']}: {p['title']} | {p['place']} | {p['date']} | {p['activity']}" for p in plans)


PLAN_RULE = """3. The user wants you to judge whether a trip is a good idea, or to plan it -> call plan_day_trip
   (do NOT call the other two separately for this; plan_day_trip already does both)."""

# Evaluation only (scripts/eval_routing.py --chaining): plan_day_trip is hidden and the model must chain.
CHAINING_PLAN_RULE = """3. The user wants you to judge whether a trip is a good idea, or to plan it -> first call
   get_weather_forecast, judge the forecast for the activity yourself, then call save_trip_plan only if the trip is a good idea."""


def build_agent(server: MCPServer, plan_rule: str = PLAN_RULE) -> Agent:
    async def instructions(ctx, agent) -> str:
        # Rebuilt on every run: today's date stays correct, and the saved plans
        # come from the trips://plans resource (app-controlled context, not a tool).
        today = today_beirut()
        plans = (await read_plans(server))[:MAX_PLANS_IN_PROMPT]
        return f"""You are Mishwar, a friendly day-trip planner for Lebanon. Today is {today:%A, %Y-%m-%d} (Beirut).

Choose tools like this:
1. The user only asks about the weather -> call get_weather_forecast.
2. The user has already decided on a trip and asks to save or remember it -> call save_trip_plan.
{plan_rule}
4. Questions about the user's saved plans -> answer from the list below; no tool is needed.
5. Anything else -> answer briefly without tools.

Rules:
- Convert relative dates ('tomorrow', 'next Saturday') to YYYY-MM-DD before calling a tool.
- If a tool returns an error, explain it in plain words and suggest a fix. Never invent weather data.
- Never say a plan was saved unless the tool result has saved=true or a plan_id.
- Keep answers short: the key numbers, the verdict and its reasons, and the plan id when one was saved.

Saved plans (newest first, from trips://plans):
{format_plans(plans)}"""

    return Agent(name="Mishwar", instructions=instructions, model=build_model(), model_settings=model_settings(),
                 mcp_servers=[server])


class RoundTrip(RunHooks):
    """Prints each tool call as it goes out to the server and comes back."""

    async def on_tool_start(self, context, agent, tool):
        args = getattr(context, "tool_arguments", "") or ""
        print(f"  [HOST -> CLIENT] model chose '{tool.name}' {args} -> tools/call sent to the MCP server")

    async def on_tool_end(self, context, agent, tool, result):
        # The SDK hands MCP output over as {"type": "text", "text": ...} items; show just the text.
        text = " ".join(_output_text(result).split())
        print(f"  [CLIENT -> HOST] '{tool.name}' returned: {text[:200]}{'...' if len(text) > 200 else ''}")


@dataclass
class Turn:
    answer: str
    tools_called: list[str] = field(default_factory=list)
    tool_arguments: list[str] = field(default_factory=list)
    tool_outputs: list[str] = field(default_factory=list)
    llm_calls: int = 0


async def ask(agent: Agent, history: list, text: str, verbose: bool = True) -> tuple[Turn, list]:
    """Run one user turn. Returns the answer, the tools called, and the new history."""
    result = await Runner.run(agent, history + [{"role": "user", "content": text}],
                              hooks=RoundTrip() if verbose else None, max_turns=8)
    calls = [item.raw_item for item in result.new_items if item.type == "tool_call_item"]
    outputs = [_output_text(item.output) for item in result.new_items if item.type == "tool_call_output_item"]
    turn = Turn(str(result.final_output), [c.name for c in calls], [c.arguments for c in calls], outputs,
                len(result.raw_responses))
    return turn, result.to_input_list()


def _output_text(output) -> str:
    items = output if isinstance(output, list) else [output]
    return " ".join(i.get("text", str(i)) if isinstance(i, dict) else str(i) for i in items)


HELP = "Ask about the weather, save a trip, or ask me to plan one. Commands: /plans, /help, exit."


async def chat() -> None:
    transport = config.transport()
    try:
        async with make_mcp_client(transport) as server:
            tools = await server.list_tools()
            print(f"[CLIENT] connected to MCP server 'mishwar' over {transport}; "
                  f"discovered {len(tools)} tools: {', '.join(t.name for t in tools)}")
            print(f"[HOST] model: {model_name()}. {HELP}")
            agent = build_agent(server)
            history: list = []
            while True:
                text = (await asyncio.to_thread(input, "\nYou: ")).strip()
                if text.lower() in {"", "exit", "quit"}:
                    break
                if text == "/help":
                    print(HELP)
                    continue
                if text == "/plans":
                    print("[HOST] reading resource trips://plans")
                    print(format_plans(await read_plans(server)))
                    continue
                try:
                    turn, history = await ask(agent, history, text)
                except openai.APIError as e:
                    print(f"[HOST] the model request failed ({type(e).__name__}: {getattr(e, 'message', e)}). Try again.")
                    continue
                except MaxTurnsExceeded:
                    print("[HOST] the agent took too many steps for that request. Try rephrasing it.")
                    continue
                print(f"\nMishwar: {turn.answer}")
    except (ConnectionError, OSError) as e:
        if transport == "http":
            raise SystemExit(f"Could not reach the MCP server at {config.http_url()} ({e}). "
                             "Start it first: MCP_TRANSPORT=http python -m mishwar.server") from e
        raise


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # answers contain °C and place names like Batroûn
    try:
        asyncio.run(chat())
    except (KeyboardInterrupt, EOFError):
        pass
    print("Bye.")


if __name__ == "__main__":
    main()
