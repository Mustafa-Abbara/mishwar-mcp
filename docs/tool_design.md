# Mishwar Tool Design

Mishwar is a weather-aware day-trip planner for Lebanon. Its MCP server exposes **exactly three tools**, one per category, plus two read-only resources. This document is the contract the code in Stages 3–4 follows.

| Tool | Category | One-sentence purpose |
|---|---|---|
| `get_weather_forecast` | **Data** | Look up the daily forecast for one place in Lebanon on one date. |
| `save_trip_plan` | **Action** | Save one trip plan to the user's saved plans. |
| `plan_day_trip` | **Orchestration** | Plan a day trip by getting the forecast, judging it for the activity, then saving the plan. |

| Resource | What it returns |
|---|---|
| `trips://plans` | All saved plans (JSON list of `SavedPlan`), newest first |
| `trips://plans/{plan_id}` | One saved plan (JSON `SavedPlan`) |

Resources are read by the **application** (the host), not chosen by the model, so listing plans does not count as a fourth tool. The Agents SDK does not show resources to the model by itself, so before each turn the host calls `read_resource("trips://plans")` and puts a compact list of saved plans into the agent's instructions. That way the agent can answer "what have I saved?" without a tool call.

---

## 1. Shared conventions

- **Dates** are ISO `YYYY-MM-DD` strings. The tools never parse "Saturday" or "tomorrow": the *agent* turns those into a date (its instructions carry today's date). "Today" is computed in the `Asia/Beirut` time zone.
- **Places** are names inside Lebanon (2–80 characters). The geocoder is called with `countryCode=LB`, so "Tripoli" can never resolve to Libya.
- **Activities** are a closed set: `hike`, `beach`, `sightseeing`, `indoor`.
- **Units** are metric: °C, km/h, % (probability).
- **Errors** are raised as FastMCP `ToolError` (`is_error: true` on the wire), never returned as normal text. Every message follows the style guide in §5.

### Facts checked against Open-Meteo (2026-10-23)

| Probe | Result | Design consequence |
|---|---|---|
| `start_date` 2026-12-24 | HTTP 400 `"out of allowed range from 2026-07-22 to 2026-11-07"` | Window = today … today+15. We check it **ourselves before** calling, so the user gets our clear message, not the API's. |
| Search "Byblos" (`countryCode=LB`) | 1 result, Mount Lebanon | OK |
| Search "Jbeil", "Tyre" | Response with **no `results` key** | Local or alternative names often fail, so this needs a small alias table (below) and a helpful `PlaceNotFound` message |
| Search "Sour", "Saida" | Resolve to Tyre and Sidon | The geocoder knows some local names, but not consistently |
| Search "Bcharre", "Jeita" (Stage 3) | Not found; "Bsharri" works, Jeita has no entry at all | Spelling variants go in the alias table; Jeita is left out rather than silently mapped to another town |
| 6 connections in a row (Stage 3) | About 1 in 6 hangs at the connect step | `fetch_json` retries the connection twice (§5) |
| Forecast for Byblos | `weather_code`, `temperature_2m_max/min`, `precipitation_probability_max`, `wind_speed_10m_max`, units included | These five daily fields are all `DayForecast` needs |

**Alias table (internal to the Data tool):** a short dictionary such as `{"jbeil": "Byblos", "tyre": "Sour", "saida": "Sidon", "trablous": "Tripoli", "bcharre": "Bsharri", …}` is tried when the plain search finds nothing. Every alias target is checked against the real geocoder by `tests/live/test_live_weather.py`. This is an implementation detail of "look up the forecast for a named place", not a new capability.

---

## 2. Tool contracts

### 2.1 `get_weather_forecast` (Data)

- **Why Data:** it only reads. Calling it twice changes nothing anywhere.
- **Description (what the model sees):** "Get the daily weather forecast for one place in Lebanon on one date (today up to 15 days ahead). Returns temperatures, rain probability and wind. Does not save anything."

| Input | Type | Constraints | Example |
|---|---|---|---|
| `place` | `str` | 2–80 chars, trimmed | `"Byblos"` |
| `date` | `str` | `YYYY-MM-DD`, today ≤ date ≤ today+15 (Beirut) | `"2026-10-24"` |

**Output `DayForecast`**

| Field | Type | Example |
|---|---|---|
| `place` | str, resolved name | `"Byblos"` |
| `region` | str, governorate | `"Mount Lebanon"` |
| `latitude`, `longitude` | float | `34.12111`, `35.64806` |
| `date` | str | `"2026-10-24"` |
| `weather_code` | int (WMO) | `3` |
| `summary` | str, from the WMO code | `"Overcast"` |
| `temp_min_c`, `temp_max_c` | float °C | `22.1`, `28.8` |
| `rain_probability_pct` | int % | `0` |
| `wind_max_kmh` | float km/h | `10.6` |
| `source` | `"open-meteo"` or `"offline-sample"` | `"open-meteo"` |

- **Side effects:** none.
- **Annotations:** `readOnlyHint=True`, `idempotentHint=True`, `openWorldHint=True`.
- **Failures:** `InvalidInput` (bad date format, empty place), `DateOutOfRange`, `PlaceNotFound`, `ServiceUnavailable` (timeout, 5xx, network error, outage switch). Exact texts are in §5.

### 2.2 `save_trip_plan` (Action)

- **Why Action:** it changes the world by writing `data/plans.json`.
- **Description:** "Save one day-trip plan to the user's saved plans. Refuses a duplicate (same title and date). Does not check the weather; use plan_day_trip for that."

| Input | Type | Constraints | Example |
|---|---|---|---|
| `title` | `str` | 3–80 chars, trimmed | `"Byblos old souk walk"` |
| `place` | `str` | 2–80 chars | `"Byblos"` |
| `date` | `str` | `YYYY-MM-DD`, today ≤ date ≤ today+365 | `"2026-10-24"` |
| `activity` | `Literal["hike","beach","sightseeing","indoor"]` | closed set | `"sightseeing"` |
| `notes` | `str` | 0–500 chars, default `""` | `"Lunch at the port"` |

**Output `SavedPlan`:** `plan_id` (`"p-"` + 8 hex characters), `title`, `place`, `date`, `activity`, `notes`, `created_at` (ISO 8601 UTC).

- **Side effects:** appends one plan to `plans.json` with an atomic write (temp file + `os.replace`), so a crash never leaves half a file.
- **Annotations:** `readOnlyHint=False`, `destructiveHint=False` (it only adds; it never overwrites or deletes), `idempotentHint=True` (repeating the same call cannot create a second copy, because duplicates are refused), `openWorldHint=False`.
- **Failures:** `InvalidInput` (short title, past date, bad format), `DuplicatePlan`, `StorageError`.
- **Duplicate rule:** same title (case-insensitive, trimmed) **and** same date.

### 2.3 `plan_day_trip` (Orchestration)

- **Why Orchestration:** it does nothing new itself. It calls the Data core, applies the fixed rule table, then calls the Action core. Coordinating them is its single purpose, the same shape as the PDF's own `plan_trip` example.
- **Description:** "Plan a day trip in Lebanon: gets the forecast for the place and date, judges it for the activity with fixed weather rules, and saves the plan unless the trip is not recommended. Use this when the user wants a recommendation; use the other two tools for a plain forecast or a plain save."

| Input | Type | Constraints | Example |
|---|---|---|---|
| `place` | `str` | as in the Data tool | `"Baalbek"` |
| `date` | `str` | as in the Data tool (needs a forecast) | `"2026-10-25"` |
| `activity` | `Literal[...]` | closed set | `"hike"` |

**Output `TripPlan`**

| Field | Type | Meaning |
|---|---|---|
| `forecast` | `DayForecast` | what the verdict is based on |
| `verdict` | `"go"`, `"go_with_caution"` or `"not_recommended"` | from the rule table (§6), never from the LLM |
| `reasons` | `list[str]` | one line per rule that fired, e.g. `"Rain probability 45% (30–59%): bring a rain jacket."` |
| `saved` | bool | whether a plan is in the store after this call |
| `plan_id` | str or null | the new plan, or the existing one if it was a duplicate |
| `message` | str | one sentence the agent can relay, e.g. `"Saved as p-3fa9c2d1."` |

- **The plan it saves:** title `"<Activity> in <place>"` (e.g. `"Hike in Baalbek"`), notes = verdict + reasons, so the saved record explains itself.
- **Side effects:** may write `plans.json`, but only through the Action core.
- **Annotations:** `readOnlyHint=False`, `destructiveHint=False`, `idempotentHint=True`, `openWorldHint=True`.
- **Failures:** see the partial-failure policy in §4.

---

## 3. The "and" test (PDF: "If you find yourself describing a tool with 'and', consider splitting it")

| Suspicion | Decision | Why |
|---|---|---|
| The Data tool geocodes the name **and** fetches the forecast. | Keep as **one** tool. | From the caller's side it is one job: "forecast for a named place". Coordinates are never useful to the agent on its own in this toolkit, and taking raw lat/lon (as notebook 7's `get_forecast` does) pushes geocoding onto the LLM, which gets it wrong. If the toolkit grew, `geocode_place` would be a 4th tool or a resource. This goes in the reflection. |
| The Action tool validates **and** checks duplicates **and** writes. | Keep. | Validation and the duplicate check are preconditions of "save one plan", not separate capabilities. |
| The Orchestration tool checks weather **and** judges **and** saves. | Allowed. | Coordination *is* its purpose. It must not add a fourth hidden capability: it only calls the two cores plus the deterministic rules. A test checks that it calls nothing else. |
| Why no `list_plans` tool? | Use a **resource**. | Reading saved plans is a pure lookup with no arguments the model needs to choose, which is exactly what the PDF says `@mcp.resource` is for. It also keeps the tool count at exactly three. |

---

## 4. Orchestration partial-failure policy

| Step that fails | Result | Saved? | Error / message |
|---|---|---|---|
| Input invalid (date format, place length) | `ToolError` | no | `InvalidInput: …` (same text as the Data tool) |
| Forecast fails (`PlaceNotFound`, `DateOutOfRange`, `ServiceUnavailable`) | `ToolError`, re-raised unchanged | **no** | the Data tool's message, so the agent sees one consistent wording |
| Verdict is `not_recommended` | normal result | **no** (`saved=false`, `plan_id=null`) | `"Not saved because the trip is not recommended. Call save_trip_plan if the user still wants it saved."` |
| Plan already exists (same title + date) | normal result | already there (`saved=true`, existing `plan_id`) | `"Already saved as p-…; nothing new was written."` |
| Storage write fails | `ToolError` | **no** | `StorageError: The forecast was retrieved (verdict: go) but the plan was NOT saved: could not write plans.json. Try again.` |
| Everything works | normal result | yes | `"Saved as p-…."` |

The rule: **never save a plan whose forecast was not retrieved, and always say plainly whether something was saved.**

---

## 5. Error messages

**Style guide.** Every message is `<ErrorType>: <what went wrong>, naming the input that caused it. <How to fix it>.` Messages are safe to show the user: no stack traces, URLs with keys or file paths. With `mask_error_details=True`, unexpected bugs reach the client as a generic error, while these `ToolError`s always get through.

| Error | Raised by | Exact text (placeholders in `{}`) |
|---|---|---|
| `InvalidInput` (date format) | all | `InvalidInput: '{date}' is not a date in YYYY-MM-DD format. Convert it first, e.g. '2026-10-24'.` |
| `InvalidInput` (place) | Data, Orch. | `InvalidInput: The place name must be 2–80 characters; got {n}.` |
| `InvalidInput` (past date) | Action | `InvalidInput: {date} is in the past (today is {today} in Beirut). Choose today or a later date.` |
| `InvalidInput` (title) | Action | `InvalidInput: The title must be 3–80 characters; got {n}.` |
| `InvalidInput` (far date) | Action | `InvalidInput: {date} is more than a year ahead. Choose a date up to {today+365}.` |
| `InvalidInput` (notes) | Action | `InvalidInput: The notes must be at most 500 characters; got {n}.` |
| `InvalidInput` (activity) | Action, Orch. | `InvalidInput: '{activity}' is not a supported activity. Use one of: hike, beach, sightseeing, indoor.` |
| `InvalidInput` (API rejected) | Data, Orch. | `InvalidInput: The weather service rejected the request: {reason}.` (should not happen: dates are checked first) |
| `DateOutOfRange` | Data, Orch. | `DateOutOfRange: {date} is outside the forecast window ({today} to {today+15}). Pick a date in that range.` |
| `PlaceNotFound` | Data, Orch. | `PlaceNotFound: No place called '{place}' was found in Lebanon. Check the spelling or try the English name of the town or a nearby one, e.g. 'Byblos' or 'Sidon'.` |
| `ServiceUnavailable` | Data, Orch. | `ServiceUnavailable: The weather service (Open-Meteo) did not respond ({reason}). Nothing was saved. Try again in a minute.` |
| `DuplicatePlan` | Action | `DuplicatePlan: A plan titled '{title}' on {date} already exists ({plan_id}). Use a different title or date.` |
| `StorageError` | Action | `StorageError: Could not write the saved plans ({reason}). The plan was NOT saved.` |
| `StorageError` (read) | Action, resource | `StorageError: Could not read the saved plans ({reason}). Fix or remove data/plans.json.` |
| `PlanNotFound` | resource | `PlanNotFound: No saved plan has id '{plan_id}'. Read trips://plans to see the saved ids.` (raised as `ResourceError`) |

`{reason}` is short and fixed: `timed out`, `HTTP 503`, `network error`, `unexpected response`, or `simulated outage`. Connection attempts are retried twice (4 s each) before giving up, because on some networks about one connection in six hangs; the worst case (~22 s) stays under the host's 30 s MCP timeout.

---

## 6. Rule table for `assess(forecast, activity)`

For outdoor activities (`hike`, `beach`, `sightseeing`):

| # | Condition | Verdict | Reason text |
|---|---|---|---|
| R1 | rain probability ≥ 60 % | `not_recommended` | `Rain probability {p}% (≥ 60%).` |
| R2 | weather code 95–99 (thunderstorm) | `not_recommended` | `Thunderstorms forecast.` |
| R3 | rain probability 30–59 % | `go_with_caution` | `Rain probability {p}% (30–59%): bring a rain jacket.` |
| R4 | max wind ≥ 40 km/h, hike or sightseeing | `go_with_caution` | `Wind up to {w} km/h: avoid exposed ridges.` |
| R5 | max wind ≥ 40 km/h, beach | `not_recommended` | `Wind up to {w} km/h: rough sea.` |
| R6 | max temperature ≥ 33 °C | `go_with_caution` | `Up to {t} °C: start early and carry water.` |
| R7 | beach and max temperature < 22 °C | `go_with_caution` | `Only {t} °C: too cool for swimming.` |
| R8 | none of the above | `go` | `No weather concerns.` |

For `indoor`: always `go`, with one informational reason such as `Indoor plan; outside it will be Overcast, 22–29 °C.`

**Combining:** the worst verdict wins (`not_recommended` > `go_with_caution` > `go`), and every rule that fired adds its reason. The same forecast always gives the same verdict, and each row is one unit test.

---

## 7. Round trips (one query per tool)

**"What's the weather in Byblos tomorrow?" → `get_weather_forecast`**
1. The user types into the host (`agent/host.py`, Agents SDK).
2. The LLM sees three tool schemas and picks `get_weather_forecast(place="Byblos", date="2026-10-24")`, converting "tomorrow" itself.
3. The SDK's MCP client sends a JSON-RPC `tools/call` to the server (stdio pipe, or HTTP POST to `/mcp`).
4. `server.py` calls `weather.get_forecast()`, which geocodes, then requests the forecast from Open-Meteo.
5. A `DayForecast` comes back as structured content; the server logs the call on stderr.
6. The client hands the result to the LLM, which writes the answer.

**"Save a plan: sunset at Raouche, Beirut on 2026-10-30" → `save_trip_plan`**
- Same path. The LLM fills in `title`, `place`, `date` and `activity="sightseeing"`. The server calls `plans_store.save()` and returns a `SavedPlan` with its `plan_id`.

**"Should I hike in Baalbek on Sunday? If it's fine, save it." → `plan_day_trip`**
- One tool call. Inside the server, `planner.plan_day_trip()` calls `weather.get_forecast()`, then `assess()`, then `plans_store.save()`, all as plain Python with no MCP calls in between. The `TripPlan` comes back with the verdict, reasons and `saved`/`plan_id`.

**Failure: "Weather in Atlantis tomorrow?"**
- The Data tool raises `PlaceNotFound`. The client receives `is_error: true` with the message, and the LLM explains it to the user and suggests a real place.

---

## 8. Routing check (gate)

Reading only this document, which tool should each request use?

| # | Request | Expected |
|---|---|---|
| 1 | "What will the weather be like in Tripoli on 2026-10-27?" | `get_weather_forecast` |
| 2 | "Save 'Cedars picnic' in Bcharre on 2026-11-01, sightseeing, note: bring a blanket." | `save_trip_plan` |
| 3 | "Is Saturday good for the beach in Batroun? Plan it for me." | `plan_day_trip` |
| 4 | "Remember that I'm visiting the Jeita Grotto on Friday." (indoor; no weather judgement asked) | `save_trip_plan` |
| 5 | "Which trips have I saved?" | no tool: answered from the `trips://plans` list the host put in the instructions |
| 6 | "Weather in Paris tomorrow?" | `get_weather_forecast` → `PlaceNotFound` (Lebanon only) |

These six cases become the first rows of `evals/routing_cases.json` in Stage 6.
