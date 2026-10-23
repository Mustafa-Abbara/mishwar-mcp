# Challenges and How They Were Solved

Every problem met while building Mishwar, how it showed up, and what fixed it. The ones marked 🎬 are good material for the video's challenges section.

## 1. Keeping tools single-purpose 🎬

| Question | Decision |
|---|---|
| The Data tool geocodes **and** fetches a forecast. Two jobs? | One job from the caller's side ("forecast for a named place"). Taking raw coordinates, as notebook 7's `get_forecast(latitude, longitude)` does, would push geocoding onto the LLM. |
| The Orchestration tool fetches, judges **and** saves. | Allowed: coordinating is its purpose, like the PDF's `plan_trip`. It calls the two cores as plain Python and adds nothing except the fixed rule table. |
| Who decides "go / no-go"? | Fixed rules (`planner.assess`), not the LLM. The same forecast always gives the same verdict, and each rule is a unit test. |
| Listing saved plans: a 4th tool? | No: a **resource** (`trips://plans`). The host reads it and puts it into the agent's instructions, so "which trips have I saved?" needs no tool call. |

## 2. Handling failures predictably 🎬

Notebook 7's weather server is the "before" example: `make_nws_request` does `except Exception: return None`, and the tools return "Unable to fetch forecast data" as a *normal* result. The protocol's error flag stays false, so the model cannot tell an error from data.

Mishwar raises typed domain errors (`PlaceNotFound`, `DateOutOfRange`, `ServiceUnavailable`, `DuplicatePlan`, `StorageError`, `InvalidInput`). The server turns them into `ToolError` with a message that says what went wrong, which input caused it and how to fix it. The client receives `is_error: true`, and the evaluation shows the agent explaining every failure case correctly (8/8 runs). Unexpected bugs are masked (`mask_error_details=True`), so no stack trace leaks.

The orchestration tool's **partial-failure policy**: if the forecast fails, nothing is saved; if the verdict is `not_recommended`, nothing is saved and it says so; if saving fails, the error says "forecast retrieved, plan NOT saved".

## 3. Problems found while building

| # | Problem | How it showed up | Fix | Evidence |
|---|---|---|---|---|
| 1 | **mcp 2.x renamed fields to snake_case** (`inputSchema` → `input_schema`, `isError` → `is_error`, `readOnlyHint` → `read_only_hint`) | The roadmap and course code crashed with `AttributeError` | Followed the installed library, not older docs | `scripts/explore_fetch.py` |
| 2 | **Windows has no time-zone database**, so `ZoneInfo("Asia/Beirut")` failed | Crash on first import | Pinned `tzdata` in `requirements.txt` (a fresh install on the grader's machine would hit the same crash) | `requirements.txt` |
| 3 | **About 1 in 6 connections to Open-Meteo hung** at the connect step on this network | Random `ConnectTimeout` in live tests | Measured: 6 attempts gave 1 timeout without retries and 0 with 2 retries. `fetch_json` now retries the *connection* twice (4 s each); retrying a connect is always safe because no request was sent | `mishwar/weather.py` |
| 4 | **The geocoder misses local names** ("Jbeil", "Tyre", "Bcharre"), while "Sour" and "Saida" work | Probing Open-Meteo before designing | A small alias table inside the Data tool (Jbeil → Byblos, Tyre → Sour, Bcharre → Bsharri, …). Every target is checked by a live test. Jeita has no entry at all, so it is left out rather than silently mapped to another town | `tests/live/test_live_weather.py` |
| 5 | **The model wrote "The Cedars"**, which the geocoder does not know | Routing evaluation, case R2: right tool, but `PlaceNotFound` in both runs | `geocode` retries without a leading "the". Before: R2 2/2 failed; after: 2/2 pass | `evals/results/routing_2026-10-23_1124.md` (before) and `_1128.md` (after) |
| 6 | **Settings silently ignored in stdio mode** 🎬 | A smoke test wrote plans to the repo's `data/` instead of the folder set in the shell | The MCP stdio client gives the server process only a minimal environment (PATH, TEMP, …), so `MISHWAR_SIMULATE_OUTAGE=1` never reached it. `config.server_env()` now forwards `MISHWAR_*`/`MCP_*` explicitly (merged over the defaults) | `tests/test_core.py::test_server_env_forwards_settings_to_stdio_child` |
| 7 | **Gemini free tier: 15 requests per minute** | The evaluation stopped with HTTP 429 after ~8 runs | The Agents SDK's runner retry policy (429/5xx/network) with backoff 10 → 20 → 40 → 60 s, which covers one quota window. The OpenAI client's own short retries are turned off so they don't burn the quota | `agent/llm.py` |
| 8 | **The SDK's MCP client times out after 5 s by default** | Known from the docs; a geocode plus forecast with connect retries can take longer | `client_session_timeout_seconds=30`. The worst-case weather call (~22 s) stays under it | `agent/host.py` |
| 9 | **stdout belongs to the protocol in stdio mode** | Any `print` in the server would corrupt JSON-RPC | All server logs go to stderr (`[SERVER] <- tool(...)` / `-> result`) | `mishwar/server.py` |
| 10 | **Tool results printed as a Python dict** in the round-trip trace | Hook output looked like `{'type': 'text', 'text': ...}` | Unwrap the SDK's text items before printing | `agent/host.py` |
| 11 | **Instructions must match the tool set** | In the chaining experiment, with `plan_day_trip` hidden, the model still called it (instructions named it), so the SDK raised `ModelBehaviorError` | The experiment gives chaining mode its own rule ("forecast, judge, then save"). Lesson: tool descriptions and agent instructions are one contract | `scripts/eval_routing.py --chaining` |
| 12 | **Gemini 3 thought signatures** could break multi-turn tool calls (HTTP 400) | Stage 0 smoke test, a known risk | No problem with `gemini-3.5-flash-lite` and openai-agents 0.24.0: two turns of tool calls passed | `scripts/smoke_llm_tools.py` |

## 4. Evaluation results

Routing evaluation (`scripts/eval_routing.py`, 11 cases × 2 runs, fresh data folder and server per run, `gemini-3.5-flash-lite`):

| Metric | First run | After fix #5 |
|---|---|---|
| Routing accuracy (right tools called) | 100% (22/22) | 100% (22/22) |
| Failure cases handled (right tools + clear answer) | 100% (8/8) | 100% (8/8) |
| All checks passed | 91% (20/22) | 100% (22/22) |
| Mean latency / LLM calls per query | 4.1 s / 1.9 | 4.2 s / 1.9 |

**Orchestration tool vs LLM chaining** (`--chaining`: the same 3 planning requests × 2 runs, with `plan_day_trip` hidden so the model must call `get_weather_forecast`, judge, then `save_trip_plan`):

| Mode | LLM calls | Tool calls | Latency | Saved exactly when the rules allow | Saved before checking weather |
|---|---|---|---|---|---|
| With `plan_day_trip` | 2.0 | 1.0 | 6.6 s | 6/6 | 0/6 |
| LLM chaining | 2.7 | 1.7 | 9.0 s | 6/6 | 0/6 |

Reading it honestly:
- **Cost:** the orchestration tool saves about a third of the LLM calls, one round trip per plan.
- **Latency is noisy:** the two slow orchestrator runs (11–14 s) most likely include rate-limit backoff waits, so LLM calls is the more reliable cost measure.
- **Easy forecasts:** chaining matched the rules 6/6 here, but these forecasts were clear-cut (0% or 80%+ rain). A borderline day (45% rain, 34 °C) is where an LLM's own judgement would drift and the fixed rules would not. This is the main argument for keeping the verdict deterministic.
