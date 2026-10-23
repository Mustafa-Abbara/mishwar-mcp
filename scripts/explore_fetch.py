"""Stage 1: explore the reference Fetch MCP server through the Agents SDK's MCP client.

Run: python scripts/explore_fetch.py > docs/fetch_exploration.txt
"""
import asyncio
import json
import sys

from agents.mcp import MCPServerStdio


async def main() -> None:
    async with MCPServerStdio(
        name="fetch",
        params={"command": sys.executable, "args": ["-m", "mcp_server_fetch"]},
        client_session_timeout_seconds=30,
    ) as server:
        print("=== TOOLS ===")
        for t in await server.list_tools():
            print("TOOL:", t.name)
            print("  description:", t.description)
            print("  input schema:", json.dumps(t.input_schema, indent=2))
            print("  annotations:", t.annotations)

        print("\n=== PROMPTS ===")
        prompts = await server.list_prompts()
        for p in prompts.prompts:
            print("PROMPT:", p.name, "-", p.description)
            print("  arguments:", [(a.name, a.required) for a in p.arguments or []])

        print("\n=== CALL: fetch https://example.com (max_length=300) ===")
        res = await server.call_tool("fetch", {"url": "https://example.com", "max_length": 300})
        print("is_error:", res.is_error)
        print(res.content[0].text[:600])

        print("\n=== CALL: raw=True (same page, HTML instead of Markdown) ===")
        raw = await server.call_tool("fetch", {"url": "https://example.com", "max_length": 300, "raw": True})
        print("is_error:", raw.is_error)
        print(raw.content[0].text[:600])

        print("\n=== FAILURE CASE: invalid URL ===")
        bad = await server.call_tool("fetch", {"url": "not-a-url"})
        print("is_error:", bad.is_error)
        print(bad.content[0].text[:400])

        print("\n=== FAILURE CASE: unreachable host ===")
        down = await server.call_tool("fetch", {"url": "https://no-such-host.invalid/"})
        print("is_error:", down.is_error)
        print(down.content[0].text[:400])


if __name__ == "__main__":
    asyncio.run(main())
