# Part 1 Summary: MCP and the Fetch Server

## 1. What MCP is

The Model Context Protocol (MCP), announced by Anthropic in November 2024, is an open standard for connecting AI applications to tools and data. Before it, each app needed a custom connector for each service, an N×M problem; with one shared protocol each side implements MCP once (N+M). Being open and model-agnostic, it spread quickly in 2025, with over a thousand community servers [1][2].

## 2. Host, Client and Server

The **Host** is the AI application the user talks to (an IDE, Claude Desktop, or my Agents SDK program); it holds the LLM. For every Server it uses, the Host creates one **Client**, which keeps a dedicated one-to-one connection to that Server. A **Server** wraps an external system, such as a website or weather API, and advertises its capabilities. A round trip: the model requests a tool, the Host routes it to the right Client, the Client sends a JSON-RPC `tools/call` to the Server, and the result returns to the model as context, over stdio locally or Streamable HTTP remotely [3].

## 3. Primitives

Servers expose tools (called by the model), resources (read-only data the application pulls in) and prompts (templates the user picks). MCP does not make tools good by itself: results still depend on tool descriptions, and for one or two simple APIs it can be overkill [2].

## 4. Critique of the Fetch server

I explored the reference Fetch server through the Agents SDK client [4]. Its **well-defined interface** is strong: one `fetch` tool with typed, bounded arguments, a read-only annotation, and a truncation note naming the next `start_index`. **Isolated functionality** is weaker: one tool hides a robots.txt check, download, HTML-to-Markdown conversion and truncation, and the `raw` flag switches between two output formats that could be two tools. **Predictable behaviour** is mostly good, since bad input returns `is_error: true` with a clear message. However, an unreachable host is reported as a robots.txt failure, truncation arrives as an `<error>` tag inside a successful result, and the description tells the model to ignore earlier instructions, so tool text can steer the model.

## 5. Takeaway

So my toolkit keeps each tool to one verb, reports failures as real errors, and moves composition into an explicit orchestration tool.

## References

1. Kseniase, "What Is MCP, and Why Is Everyone – Suddenly! – Talking About It?", Hugging Face blog. https://huggingface.co/blog/Kseniase/mcp
2. Turing Post, "What Is MCP? Model Context Protocol in Agentic AI, Explained" (full article). https://www.turingpost.com/p/mcp
3. "Architecture overview", modelcontextprotocol.io. https://modelcontextprotocol.io/docs/learn/architecture
4. `mcp-server-fetch` 2026.10.19, explored with `scripts/explore_fetch.py`; output in `docs/fetch_exploration.txt`. https://pypi.org/project/mcp-server-fetch/
