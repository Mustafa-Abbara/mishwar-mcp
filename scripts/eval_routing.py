"""Stage 6: measure tool routing and failure handling with the real LLM.

    python scripts/eval_routing.py              # every case in evals/routing_cases.json, twice
    python scripts/eval_routing.py R4 R5        # only some cases
    python scripts/eval_routing.py --chaining   # orchestration tool vs LLM chaining experiment

Each run gets a fresh temporary data folder and its own server process, so runs
never see each other's plans. Results go to evals/results/ (JSONL + a Markdown table).
"""
import asyncio
import datetime as dt
import json
import os
import re
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from agents import ModelBehaviorError  # noqa: E402
from agents.mcp import create_static_tool_filter  # noqa: E402

from agent.host import CHAINING_PLAN_RULE, PLAN_RULE, Turn, ask, build_agent, make_mcp_client, read_plans  # noqa: E402
from agent.llm import model_name  # noqa: E402
from mishwar import planner, plans_store  # noqa: E402
from mishwar.models import DayForecast  # noqa: E402
from mishwar.validation import today_beirut  # noqa: E402

CASES = ROOT / "evals" / "routing_cases.json"
RESULTS = ROOT / "evals" / "results"
RUNS = 2

CHAINING_QUERIES = [
    "Is Batroun beach a good idea on Friday? Save it if so.",
    "Plan a hike in Faraya next Sunday.",
    "Should I go hiking in Ehden next Saturday? Plan it if it's fine.",
]


def fill_dates(text: str) -> str:
    """Replace {+N} with the ISO date N days from today (Beirut)."""
    return re.sub(r"\{\+(\d+)\}", lambda m: (today_beirut() + dt.timedelta(days=int(m.group(1)))).isoformat(), text)


async def run_once(query: str, env: dict | None = None, seed: list | None = None, tool_filter=None,
                   plan_rule: str = PLAN_RULE) -> dict:
    """One query on a fresh data folder and a fresh server process."""
    with tempfile.TemporaryDirectory() as tmp:
        saved_env = {k: os.environ.get(k) for k in ["MISHWAR_DATA_DIR", *(env or {})]}
        os.environ["MISHWAR_DATA_DIR"] = tmp
        os.environ.update(env or {})
        try:
            for plan in seed or []:
                plans_store.save(**{k: fill_dates(v) for k, v in plan.items()})
            async with make_mcp_client("stdio", tool_filter=tool_filter) as server:
                agent = build_agent(server, plan_rule)
                start = time.perf_counter()
                try:
                    turn, _ = await ask(agent, [], fill_dates(query), verbose=False)
                except ModelBehaviorError as e:  # e.g. the model calls a tool that is not offered
                    turn = Turn(f"[model error] {e}")
                latency = time.perf_counter() - start
                plans = await read_plans(server)
        finally:
            for k, v in saved_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    return {"query": fill_dates(query), "tools": turn.tools_called, "arguments": turn.tool_arguments,
            "outputs": turn.tool_outputs, "answer": turn.answer, "latency_s": round(latency, 2),
            "llm_calls": turn.llm_calls, "plans_after": len(plans), "plans": plans}


def check(case: dict, run: dict) -> tuple[bool, bool, list[str]]:
    """Returns (routing_ok, answer_ok, problems)."""
    problems = []
    routing_ok = run["tools"] in case["accept"]
    if not routing_ok:
        problems.append(f"tools {run['tools']} not in {case['accept']}")
    answer = run["answer"].lower()
    if case.get("contains_any") and not any(w.lower() in answer for w in case["contains_any"]):
        problems.append(f"answer lacks any of {case['contains_any']}")
    for w in case.get("not_contains", []):
        if w.lower() in answer:
            problems.append(f"answer contains {w!r}")
    if "plans_after" in case and run["plans_after"] != case["plans_after"]:
        problems.append(f"{run['plans_after']} plans saved, expected {case['plans_after']}")
    return routing_ok, routing_ok and not problems, problems


async def evaluate(ids: list[str]) -> None:
    cases = [c for c in json.loads(CASES.read_text(encoding="utf-8")) if not ids or c["id"] in ids]
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M")
    RESULTS.mkdir(parents=True, exist_ok=True)
    log = (RESULTS / f"routing_{stamp}.jsonl").open("w", encoding="utf-8")  # row by row: a crash keeps finished runs
    rows = []
    for case in cases:
        for n in range(1, RUNS + 1):
            run = await run_once(case["query"], case.get("env"), case.get("seed"))
            routing_ok, ok, problems = check(case, run)
            rows.append({"id": case["id"], "category": case["category"], "run": n, "routing_ok": routing_ok,
                         "ok": ok, "problems": problems, **run})
            log.write(json.dumps(rows[-1], ensure_ascii=False) + "\n")
            log.flush()
            mark = "PASS" if ok else "FAIL"
            print(f"{case['id']:<4} run {n}  {mark}  tools={run['tools']}  llm={run['llm_calls']}  {run['latency_s']}s"
                  + (f"  <- {'; '.join(problems)}" if problems else ""))

    log.close()

    def pct(xs):
        return f"{100 * sum(xs) / len(xs):.0f}% ({sum(xs)}/{len(xs)})" if xs else "n/a"

    routing = [r["routing_ok"] for r in rows]
    failures = [r["ok"] for r in rows if r["category"] == "failure"]
    overall = [r["ok"] for r in rows]
    lines = [
        f"# Routing evaluation {stamp}", "",
        f"Model `{model_name()}`, {RUNS} runs per case, fresh data folder and server per run.", "",
        "| Metric | Result |", "|---|---|",
        f"| Routing accuracy (right tools called) | {pct(routing)} |",
        f"| Failure cases handled (right tools + clear answer) | {pct(failures)} |",
        f"| All checks passed | {pct(overall)} |",
        f"| Mean latency per query | {statistics.mean(r['latency_s'] for r in rows):.1f} s |",
        f"| Mean LLM calls per query | {statistics.mean(r['llm_calls'] for r in rows):.1f} |", "",
        "| Case | Run | Tools called | LLM calls | Latency | Result |", "|---|---|---|---|---|---|",
    ]
    for r in rows:
        result = "pass" if r["ok"] else "FAIL: " + "; ".join(r["problems"])
        lines.append(f"| {r['id']} | {r['run']} | {', '.join(r['tools']) or '(none)'} | {r['llm_calls']} | {r['latency_s']} s | {result} |")
    (RESULTS / f"routing_{stamp}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n" + "\n".join(lines[4:10]))
    print(f"\nSaved evals/results/routing_{stamp}.jsonl and .md")


def rule_verdict(outputs: list[str], activity: str) -> str | None:
    """What the fixed rules would say about the forecast the LLM fetched."""
    for text in outputs:
        try:
            return planner.assess(DayForecast.model_validate_json(text), activity)[0]
        except ValueError:
            continue
    return None


async def chaining() -> None:
    """Same planning requests with plan_day_trip available vs hidden (the LLM must chain the other two)."""
    hide = create_static_tool_filter(blocked_tool_names=["plan_day_trip"])
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M")
    rows = []
    for query in CHAINING_QUERIES:
        activity = "beach" if "beach" in query else "hike"
        for mode, tool_filter, rule in (("orchestrator", None, PLAN_RULE), ("chaining", hide, CHAINING_PLAN_RULE)):
            for n in range(1, RUNS + 1):
                run = await run_once(query, tool_filter=tool_filter, plan_rule=rule)
                if mode == "orchestrator":
                    trip = json.loads(run["outputs"][0]) if run["tools"] == ["plan_day_trip"] else {}
                    verdict = trip.get("verdict")
                    rules_followed = bool(trip) and (run["plans_after"] == 1) == (verdict != "not_recommended")
                    saved_before_forecast = False
                else:
                    verdict = rule_verdict(run["outputs"], activity)
                    rules_followed = verdict is not None and (run["plans_after"] == 1) == (verdict != "not_recommended")
                    tools = run["tools"]
                    saved_before_forecast = "save_trip_plan" in tools and (
                        "get_weather_forecast" not in tools or tools.index("save_trip_plan") < tools.index("get_weather_forecast"))
                rows.append({"query": query, "mode": mode, "run": n, "rule_verdict": verdict, "saved": run["plans_after"],
                             "rules_followed": rules_followed, "saved_before_forecast": saved_before_forecast, **run})
                print(f"{mode:<12} run {n}  tools={run['tools']}  llm={run['llm_calls']}  {run['latency_s']}s  "
                      f"rule verdict={verdict}  saved={run['plans_after']}  follows rules={rules_followed}")

    RESULTS.mkdir(parents=True, exist_ok=True)
    with (RESULTS / f"chaining_{stamp}.jsonl").open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    lines = [f"# Orchestration tool vs LLM chaining {stamp}", "",
             f"Model `{model_name()}`. Same {len(CHAINING_QUERIES)} planning requests, {RUNS} runs each. "
             "\"Follows rules\" = a plan was saved exactly when the fixed rule table says the trip is not `not_recommended`.", "",
             "| Mode | Mean LLM calls | Mean tool calls | Mean latency | Follows rules | Saved before checking weather |",
             "|---|---|---|---|---|---|"]
    for mode in ("orchestrator", "chaining"):
        rs = [r for r in rows if r["mode"] == mode]
        lines.append(f"| {mode} | {statistics.mean(r['llm_calls'] for r in rs):.1f} | "
                     f"{statistics.mean(len(r['tools']) for r in rs):.1f} | {statistics.mean(r['latency_s'] for r in rs):.1f} s | "
                     f"{sum(r['rules_followed'] for r in rs)}/{len(rs)} | {sum(r['saved_before_forecast'] for r in rs)}/{len(rs)} |")
    lines += ["", "| Query | Mode | Run | Tools called | Rule verdict | Plans saved |", "|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['query']} | {r['mode']} | {r['run']} | {', '.join(r['tools']) or '(none)'} | {r['rule_verdict']} | {r['saved']} |")
    (RESULTS / f"chaining_{stamp}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n" + "\n".join(lines[4:8]))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    asyncio.run(chaining() if "--chaining" in args else evaluate([a for a in args if not a.startswith("--")]))
