# Architecture

## Components

```mermaid
flowchart LR
    U([User]) <--> H

    subgraph HOST["MCP Host: agent/host.py"]
        H[Chat loop + hooks<br/>prints the round trip]
        A[Agents SDK Agent<br/>Gemini via OpenAI-compatible API]
        C[MCP Client<br/>MCPServerStdio or<br/>MCPServerStreamableHttp]
        H <--> A
        A <--> C
    end

    C <-->|"JSON-RPC 2.0<br/>stdio pipe or HTTP POST /mcp"| S

    subgraph SERVER["MCP Server: mishwar/server.py (FastMCP)"]
        S["3 tools + 2 resources<br/>schemas from type hints,<br/>domain errors -> ToolError"]
        subgraph CORE["Core layer (plain Python, no MCP)"]
            W[weather.py<br/>Data]
            P[plans_store.py<br/>Action]
            O[planner.py<br/>Orchestration + rules]
        end
        S --> W
        S --> P
        S --> O
        O --> W
        O --> P
    end

    W <-->|HTTPS| OM[(Open-Meteo<br/>geocoding + forecast)]
    P <--> F[(data/plans.json)]
```

- **Host** (`agent/host.py`): the application the user talks to. It holds the agent, prints each tool call, and reads the `trips://plans` resource itself (for the agent's instructions and the `/plans` command).
- **Client** (inside the host): one dedicated connection to the one server. `MCPServerStdio` starts the server as a child process; `MCPServerStreamableHttp` connects to a server already running at `http://127.0.0.1:8000/mcp`.
- **Server** (`mishwar/server.py`): a thin FastMCP layer. Each tool calls one core function; nothing in it knows about weather rules or files.
- **Core** (`mishwar/`): all the logic, tested without MCP or an LLM. The orchestration core calls the other two cores **directly as Python**, never through MCP, so the tools stay independent.

## One request end to end: `plan_day_trip`

```mermaid
sequenceDiagram
    actor User
    participant Host as Host (agent/host.py)
    participant LLM as Gemini
    participant Client as MCP Client
    participant Server as MCP Server (FastMCP)
    participant Core as planner / weather / plans_store
    participant API as Open-Meteo

    User->>Host: "Is Saturday good for a hike in Ehden? Plan it."
    Host->>Client: read_resource("trips://plans")
    Client->>Server: resources/read
    Server-->>Host: saved plans (put into the instructions)
    Host->>LLM: instructions (today's date, saved plans) + message + 3 tool schemas
    LLM-->>Host: tool call plan_day_trip(place="Ehden", date="2026-10-31", activity="hike")
    Host->>Client: call_tool
    Client->>Server: tools/call (JSON-RPC)
    Server->>Core: planner.plan_day_trip(...)
    Core->>API: geocode "Ehden" (countryCode=LB)
    Core->>API: daily forecast for 2026-10-31
    API-->>Core: weather code, temps, rain %, wind
    Core->>Core: assess(): fixed rule table -> verdict + reasons
    alt verdict is go / go_with_caution
        Core->>Core: plans_store.save() (atomic write)
    else not_recommended
        Core->>Core: nothing saved
    end
    Core-->>Server: TripPlan
    Server-->>Client: structured result (is_error=false)
    Client-->>Host: tool output
    Host->>LLM: tool output
    LLM-->>Host: final answer (verdict, reasons, plan id)
    Host-->>User: answer
```

If anything fails (unknown place, date outside the window, Open-Meteo down, file not writable), the core raises a domain error. The server turns it into a `ToolError`, the client receives `is_error=true` with the message, and the LLM explains it to the user. If the forecast fails, nothing is saved.

## Transports

| | stdio (development) | Streamable HTTP (demo) |
|---|---|---|
| Who starts the server | the host, as a child process | you, in its own terminal |
| Command | `python -m agent.host` | `MCP_TRANSPORT=http python -m mishwar.server`, then `MCP_TRANSPORT=http python -m agent.host` |
| Where server logs appear | mixed into the host's terminal (stderr) | in the server's own window, so you can watch each request arrive |
| Settings | forwarded by `config.server_env()` (the stdio client passes only a minimal environment) | read from `.env` by the server process |

The same server code serves both; `MCP_TRANSPORT` picks one.
