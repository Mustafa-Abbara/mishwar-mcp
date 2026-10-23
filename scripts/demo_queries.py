"""Run a fixed list of queries through the host, one after another (same code path as the chat).

    python scripts/demo_queries.py            # the default demo script
    python scripts/demo_queries.py "q1" "q2"  # your own queries

The conversation history carries over between queries, as in the chat.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent.host import ask, build_agent, format_plans, make_mcp_client, read_plans  # noqa: E402
from agent.llm import model_name  # noqa: E402
from mishwar import config  # noqa: E402

DEFAULT_QUERIES = [
    "What's the weather in Byblos tomorrow?",                                   # Data
    "Save a plan called 'Sunset at Raouche' in Beirut for the day after tomorrow, sightseeing.",  # Action
    "Is next Saturday a good day for a hike in Ehden? If so, plan it.",         # Orchestration
    "What's the weather in Atlantis tomorrow?",                                 # failure case
    "Which trips have I saved?",                                                # resource, no tool
]


async def main(queries: list[str]) -> None:
    async with make_mcp_client() as server:
        print(f"[CLIENT] connected over {config.transport()}; model {model_name()}")
        agent = build_agent(server)
        history: list = []
        for query in queries:
            print(f"\nYou: {query}")
            turn, history = await ask(agent, history, query)
            print(f"Mishwar: {turn.answer}")
        print("\n[HOST] trips://plans now holds:\n" + format_plans(await read_plans(server)))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main(sys.argv[1:] or DEFAULT_QUERIES))
