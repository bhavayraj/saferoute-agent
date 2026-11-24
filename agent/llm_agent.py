"""Optional LLM mode: a language model decides which MCP tools to call.

Works with any OpenAI-compatible Chat Completions endpoint that supports tool
calling (e.g. Google Gemini's OpenAI-compatible endpoint, Groq, OpenAI, OpenRouter,
or a local Ollama server). Configure with environment variables:

    LLM_API_KEY   your key (not needed for local Ollama)
    LLM_BASE_URL  e.g. https://generativelanguage.googleapis.com/v1beta/openai
    LLM_MODEL     e.g. gemini-2.0-flash

Control rules enforced by the host (not by the model):
  * Emergency tools that send messages are NOT offered to the model at all.
    SOS / location sharing only happens from an explicit user tap in the app.
  * At most MAX_STEPS tool rounds per request.
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.request
from datetime import datetime

from agent.mcp_host import MCPHost
from agent.planner import label_routes, recommend

MAX_STEPS = 10
BLOCKED_TOOLS = {"share_live_location", "notify_emergency_contacts"}

SYSTEM_PROMPT = """You are SafeRoute, a personal safety navigation agent for Bengaluru.
When the user asks for a route:
1. geocode the start and the destination,
2. call get_routes once, and get_weather at the start point,
3. call analyze_route for EVERY route returned (pass its id, geometry as coordinates, the travel hour 0-23 and the weather condition),
4. recommend the route with the best safety score and explain the trade-off against the fastest route in 3-5 short sentences.
Use only facts returned by the tools. Never say a route is guaranteed or completely safe; mention when data coverage is low.
If the user did not give a time, assume the current hour: {hour}."""


def llm_configured() -> bool:
    return bool(os.environ.get("LLM_BASE_URL") and os.environ.get("LLM_MODEL"))


def _tool_specs(host: MCPHost) -> list[dict]:
    specs = []
    for name, t in host.tools.items():
        if name in BLOCKED_TOOLS:
            continue
        specs.append({"type": "function", "function": {
            "name": name, "description": t["description"], "parameters": t["input_schema"] or {"type": "object", "properties": {}},
        }})
    return specs


def _chat(messages: list[dict], tools: list[dict]) -> dict:
    url = os.environ["LLM_BASE_URL"].rstrip("/") + "/chat/completions"
    body = json.dumps({"model": os.environ["LLM_MODEL"], "messages": messages, "tools": tools,
                       "tool_choice": "auto", "temperature": 0.2}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if os.environ.get("LLM_API_KEY"):
        headers["Authorization"] = f"Bearer {os.environ['LLM_API_KEY']}"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 (user-configured endpoint)
        return json.loads(resp.read().decode("utf-8"))


async def run_llm_agent(host: MCPHost, query: str) -> dict:
    hour = datetime.now().hour
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT.format(hour=hour)},
                            {"role": "user", "content": query}]
    tools = _tool_specs(host)
    routes_by_id: dict[str, dict] = {}
    safety_by_id: dict[str, dict] = {}
    places: list[dict] = []
    weather: dict = {}
    used_hour = hour
    final_text = ""

    for _ in range(MAX_STEPS):
        resp = await asyncio.to_thread(_chat, messages, tools)
        msg = resp["choices"][0]["message"]
        calls = msg.get("tool_calls") or []
        messages.append({"role": "assistant", "content": msg.get("content") or "", **({"tool_calls": calls} if calls else {})})
        if not calls:
            final_text = msg.get("content") or ""
            break
        for call in calls:
            name = call["function"]["name"]
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            if name in BLOCKED_TOOLS or name not in host.tools:
                result = {"error": f"Tool '{name}' is not available to the agent."}
            else:
                result = await host.call(name, args)
            if name == "geocode" and "error" not in result:
                places.append(result)
            elif name == "get_routes":
                for r in result.get("routes", []):
                    routes_by_id[r["id"]] = r
            elif name == "get_weather":
                weather = result
            elif name == "analyze_route" and "error" not in result:
                safety_by_id[result["route_id"]] = result
                used_hour = int(args.get("hour", used_hour))
            messages.append({"role": "tool", "tool_call_id": call.get("id", name), "content": json.dumps(result)})

    routes = [{**r, "safety": safety_by_id[rid]} for rid, r in routes_by_id.items() if rid in safety_by_id]
    rec = None
    if routes:
        label_routes(routes)
        routes.sort(key=lambda r: -r["safety"]["safety_score"])
        rec = recommend(routes, used_hour)
        if final_text:
            rec["summary"] = final_text
    return {
        "mode": "llm", "model": os.environ.get("LLM_MODEL"), "query": query,
        "origin": places[0] if places else None, "destination": places[1] if len(places) > 1 else None,
        "hour": used_hour, "weather": weather, "routes": routes, "recommendation": rec,
        "answer": final_text, "trace": list(host.trace),
    }
