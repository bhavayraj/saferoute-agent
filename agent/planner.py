"""SafeRoute agent: understands a trip request and orchestrates the MCP tools.

Two ways to run the reasoning step:
  * "planner" (default, no API key needed): a deterministic plan
      geocode -> get_routes -> get_weather -> analyze_route (each) -> rank & explain
  * "llm" (optional): an LLM chooses which MCP tools to call (see agent/llm_agent.py)

Both modes reach every capability ONLY through MCP tool calls, and both return
the same JSON shape so the web app and CLI can render either.
"""

from __future__ import annotations

import re
from datetime import datetime

from agent.mcp_host import MCPHost

TRIP_RE = re.compile(r"\bfrom\s+(?P<origin>.+?)\s+to\s+(?P<dest>.+?)(?=\s+(?:at|by|around|tonight|now|on foot|walking|by car|in a cab)\b|[.?!,]|$)", re.I)
TIME_RE = re.compile(r"\b(?:at|around|by)\s+(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ampm>a\.?m\.?|p\.?m\.?)?", re.I)
CAR_WORDS = ("by car", "drive", "driving", "cab", "taxi", "auto", "bike")


class TripRequestError(ValueError):
    pass


def parse_request(text: str, now: datetime | None = None) -> dict:
    """Extract origin, destination, hour (0-23) and travel profile from free text."""
    now = now or datetime.now()
    m = TRIP_RE.search(text)
    if not m:
        raise TripRequestError("Please say where you are going, e.g. 'from MSRIT to Majestic at 10 PM'.")
    origin = m.group("origin").strip(" .,'\"")
    dest = m.group("dest").strip(" .,'\"")
    hour = now.hour
    t = TIME_RE.search(text[m.start():]) or TIME_RE.search(text)
    if t:
        h = int(t.group("h"))
        ampm = (t.group("ampm") or "").lower().replace(".", "")
        if ampm == "pm" and h < 12:
            h += 12
        elif ampm == "am" and h == 12:
            h = 0
        if 0 <= h <= 23:
            hour = h
    elif re.search(r"\btonight\b", text, re.I):
        hour = 21
    profile = "car" if any(w in text.lower() for w in CAR_WORDS) else "foot"
    return {"origin": origin, "destination": dest, "hour": hour, "profile": profile}


def label_routes(routes: list[dict]) -> None:
    """Attach human labels: Safest / Fastest / Balanced (a route can carry two)."""
    if not routes:
        return
    safest = max(routes, key=lambda r: (r["safety"]["safety_score"], -r["duration_min"]))
    fastest = min(routes, key=lambda r: r["duration_min"])
    for r in routes:
        tags = []
        if r is safest:
            tags.append("Safest")
        if r is fastest:
            tags.append("Fastest")
        r["labels"] = tags or ["Alternative"]
    others = [r for r in routes if r["labels"] == ["Alternative"]]
    if others:
        others[0]["labels"] = ["Balanced"]


def recommend(routes: list[dict], hour: int) -> dict:
    safest = next(r for r in routes if "Safest" in r["labels"])
    fastest = next(r for r in routes if "Fastest" in r["labels"])
    s = safest["safety"]
    when = f"{hour:02d}:00"
    if safest is fastest:
        summary = (f"Route {safest['id']} is both the safest ({s['safety_score']}/10) and the fastest "
                   f"({safest['duration_min']:.0f} min) option for {when}.")
    else:
        extra = safest["duration_min"] - fastest["duration_min"]
        f = fastest["safety"]
        summary = (f"Take route {safest['id']}: safety {s['safety_score']}/10 vs {f['safety_score']}/10 for the "
                   f"fastest route {fastest['id']}, for about {extra:.0f} extra minutes at {when}.")
        if fastest["safety"]["caution_segments"]:
            reasons = sorted({c["reason"] for c in fastest["safety"]["caution_segments"]})
            summary += f" Route {fastest['id']} has stretches flagged as: {', '.join(reasons)}."
    if s["confidence"] != "high":
        summary += f" Data coverage on this route is {s['data_coverage_pct']}%, so use the score as a rough guide."
    return {"route_id": safest["id"], "summary": summary, "why": s["explanation"]}


async def plan_trip(host: MCPHost, query: str | None = None, *, origin: str | None = None,
                    destination: str | None = None, hour: int | None = None, profile: str | None = None) -> dict:
    """Run the deterministic agent plan through MCP tools and return a full result."""
    req = parse_request(query) if query else {}
    origin = origin or req.get("origin")
    destination = destination or req.get("destination")
    hour = req.get("hour", datetime.now().hour) if hour is None else int(hour)
    profile = profile or req.get("profile", "foot")
    if not origin or not destination:
        raise TripRequestError("Both a start point and a destination are needed.")

    o = await host.call("geocode", {"place": origin})
    d = await host.call("geocode", {"place": destination})
    for g in (o, d):
        if "error" in g:
            raise TripRequestError(g["error"])

    routes_res = await host.call("get_routes", {"origin_lat": o["lat"], "origin_lon": o["lon"],
                                                "dest_lat": d["lat"], "dest_lon": d["lon"], "profile": profile})
    weather = await host.call("get_weather", {"latitude": o["lat"], "longitude": o["lon"]})

    routes = []
    for r in routes_res.get("routes", []):
        safety = await host.call("analyze_route", {"route_id": r["id"], "coordinates": r["geometry"],
                                                   "hour": hour, "weather": weather.get("condition", "unknown")})
        if "error" in safety:
            continue
        routes.append({**r, "safety": safety})
    if not routes:
        raise TripRequestError("No routes could be analysed for this trip.")
    label_routes(routes)
    routes.sort(key=lambda r: -r["safety"]["safety_score"])
    return {
        "mode": "planner",
        "query": query,
        "origin": o, "destination": d, "hour": hour, "profile": profile,
        "weather": weather,
        "routes_warning": routes_res.get("warning"),
        "routes": routes,
        "recommendation": recommend(routes, hour),
        "trace": list(host.trace),
    }
