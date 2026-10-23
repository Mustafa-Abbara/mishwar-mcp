"""Stage 0: two turns of tool calling on the configured model, without MCP.

Turn 2 re-sends turn 1's tool call, which is where Gemini 3 fails with HTTP 400
if the thought signature was dropped. Expected output: 29, then 34.
"""
import asyncio
import os

from dotenv import load_dotenv
from openai import AsyncOpenAI
from agents import Agent, OpenAIChatCompletionsModel, Runner, function_tool, set_tracing_disabled

load_dotenv()
set_tracing_disabled(True)  # no OpenAI key -> trace upload would fail with 401


@function_tool
def add(a: int, b: int) -> int:
    """Add two integers."""
    print(f"  [tool] add({a}, {b})")
    return a + b


async def main() -> None:
    client = AsyncOpenAI(base_url=os.environ["LLM_BASE_URL"], api_key=os.environ["LLM_API_KEY"])
    model = OpenAIChatCompletionsModel(model=os.environ["LLM_MODEL"], openai_client=client)
    agent = Agent(name="Smoke", instructions="Always use the add tool for arithmetic.", tools=[add], model=model)
    print(f"model: {os.environ['LLM_MODEL']}")

    r1 = await Runner.run(agent, "What is 7 + 22?")
    print("turn 1:", r1.final_output)

    r2 = await Runner.run(agent, r1.to_input_list() + [{"role": "user", "content": "Now add 5 to that."}])
    print("turn 2:", r2.final_output)


if __name__ == "__main__":
    asyncio.run(main())
