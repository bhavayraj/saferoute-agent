"""Safety Analysis MCP server (custom-built — the core of SafeRoute Agent).

Tools exposed to the agent:
  * analyze_route(route_id, coordinates, hour, weather)  -> explainable safety score for one route
  * get_safety_score(latitude, longitude, hour)          -> safety snapshot around a single point
  * check_unsafe_zones(coordinates, hour)                 -> stretches of a route that need caution
  * report_unsafe_location(latitude, longitude, category, description) -> community report
  * list_reports_near(latitude, longitude, radius_m)     -> community reports around a point

The score is deliberately *explainable*: every number comes with the reasons
behind it and a data-coverage figure, so the app never claims a route is
"100% safe" when data is missing.

IMPORTANT: data/safety_data_bengaluru_sample.json is a SYNTHETIC demo dataset
created for this hackathon. It is not real crime, lighting or CCTV data.

Run standalone:  python -m servers.safety_mcp
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as MCPServer

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from servers.geo import haversine_m, path_length_m, sample_path  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "safety_data_bengaluru_sample.json"
REPORTS_FILE = ROOT / "data" / "community_reports.json"  # created at runtime (git-ignored)

SAMPLE_STEP_M = 50.0
HELP_RADIUS_M = 250.0
CCTV_RADIUS_M = 60.0
INCIDENT_RADIUS_M = 80.0
REPORT_CATEGORIES = {"poor_lighting", "isolated", "harassment", "theft", "accident_prone", "other"}

mcp = MCPServer("saferoute-safety")


# ------------------------------------------------------------------ data

def load_data() -> dict:
    with open(DATA_FILE, encoding="utf-8") as f:
        data = json.load(f)
    reports = load_reports()
    # Community reports count as incidents (severity 1 = lower weight than verified data).
    data["incidents"] = list(data.get("incidents", [])) + [
        {"id": r["id"], "category": r["category"], "severity": 1, "lat": r["lat"], "lon": r["lon"],
         "reported": r["reported"], "source": "community"}
        for r in reports
    ]
    return data


def load_reports() -> list[dict]:
    if not REPORTS_FILE.exists():
        return []
    try:
        with open(REPORTS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def is_night(hour: int) -> bool:
    return hour >= 19 or hour < 6


def _in_hours(hours: list[int] | None, hour: int) -> bool:
    """True if ``hour`` is inside [start, end) — supports ranges that wrap midnight."""
    if not hours:
        return True
    start, end = hours
    return start <= hour < end if start <= end else (hour >= start or hour < end)


def _zone_hits(point: tuple[float, float], zones: list[dict], hour: int | None = None) -> list[dict]:
    hits = []
    for z in zones:
        if hour is not None and not _in_hours(z.get("hours"), hour):
            continue
        if haversine_m(point, (z["lat"], z["lon"])) <= z["radius_m"]:
            hits.append(z)
    return hits


# ------------------------------------------------------------------ scoring

def score_route(coordinates: list[list[float]], hour: int, weather: str = "unknown", route_id: str = "route") -> dict:
    """Explainable safety score (0-10) for a route given as [[lat, lon], ...]."""
    if len(coordinates) < 2:
        raise ValueError("A route needs at least two coordinates.")
    hour = int(hour) % 24
    data = load_data()
    pts = [(float(c[0]), float(c[1])) for c in coordinates]
    samples = sample_path(pts, SAMPLE_STEP_M)
    n = len(samples)
    length_km = max(path_length_m(pts) / 1000, 0.3)
    night = is_night(hour)

    lit = dark = busy = isolated = covered = 0
    flags: list[str | None] = []  # per-sample caution reason
    for s in samples:
        light = _zone_hits(s, data["lighting"])
        act = _zone_hits(s, data["activity"], hour)
        poorly = any(z["type"] == "poorly_lit" for z in light)
        well = any(z["type"] == "well_lit" for z in light) and not poorly
        is_busy = any(z["type"] == "busy" for z in act)
        is_iso = any(z["type"] == "isolated" for z in act) and not is_busy
        lit += well
        dark += poorly
        busy += is_busy
        isolated += is_iso
        covered += bool(light or act)
        reason = None
        if poorly and night:
            reason = "poorly lit"
        elif is_iso:
            reason = "isolated stretch"
        flags.append(reason)

    def near(items: list[dict], radius: float) -> list[dict]:
        return [it for it in items if any(haversine_m((it["lat"], it["lon"]), s) <= radius for s in samples)]

    help_pts = near(data["help_points"], HELP_RADIUS_M)
    cctv = near(data["cctv"], CCTV_RADIUS_M)
    incidents = near(data["incidents"], INCIDENT_RADIUS_M)
    severity = sum(int(i.get("severity", 1)) for i in incidents)

    # Mark samples close to incidents as caution points too.
    for idx, s in enumerate(samples):
        if flags[idx] is None and any(haversine_m(s, (i["lat"], i["lon"])) <= INCIDENT_RADIUS_M for i in incidents):
            flags[idx] = "reported incident nearby"

    # Factor scores in [0, 1]; unknown lighting/activity counts as neutral (0.5).
    unknown_light = n - lit - dark
    unknown_act = n - busy - isolated
    # In daylight, street lighting does not matter, so the lighting factor is full.
    f_light = (lit + 0.5 * unknown_light) / n if night else 1.0
    f_activity = (busy + 0.5 * unknown_act) / n
    f_help = min(len(help_pts) / (length_km * 1.5), 1.0)
    f_cctv = min(len(cctv) / (length_km * 3.0), 1.0)
    incident_penalty = min(severity / length_km / 3.0, 1.0)

    weights = ({"lighting": 0.35, "activity": 0.25, "help_points": 0.20, "cctv": 0.20} if night
               else {"lighting": 0.25, "activity": 0.30, "help_points": 0.25, "cctv": 0.20})
    factors = {"lighting": f_light, "activity": f_activity, "help_points": f_help, "cctv": f_cctv}
    base = 10 * sum(weights[k] * factors[k] for k in weights)
    penalty_incidents = (3.0 if night else 2.0) * incident_penalty
    wet = any(w in (weather or "").lower() for w in ("rain", "drizzle", "thunder", "fog"))
    penalty_weather = (0.5 if night else 0.3) if wet else 0.0
    score = max(0.0, min(10.0, base - penalty_incidents - penalty_weather))

    coverage = covered / n
    confidence = "high" if coverage >= 0.6 else "medium" if coverage >= 0.3 else "low"
    bright_pct = round(100 * lit / n)

    reasons: list[str] = []
    if night:
        reasons.append(f"{bright_pct}% of the route is on well-lit stretches" + (f"; {round(100 * dark / n)}% is poorly lit" if dark else "") + ".")
    else:
        reasons.append(f"Daytime travel at {hour:02d}:00, so street lighting is not a factor ({bright_pct}% of the route is well lit after dark).")
    if busy:
        reasons.append(f"{round(100 * busy / n)}% passes busy, active areas at {hour:02d}:00.")
    if isolated:
        reasons.append(f"{round(100 * isolated / n)}% goes through isolated stretches at {hour:02d}:00.")
    reasons.append(f"{len(help_pts)} help point(s) (police, hospital, 24x7 store, metro) within {int(HELP_RADIUS_M)} m.")
    reasons.append(f"{len(cctv)} known CCTV camera(s) along the way.")
    if incidents:
        n_comm = sum(1 for i in incidents if i.get("source") == "community")
        reasons.append(f"{len(incidents)} reported incident(s) within {int(INCIDENT_RADIUS_M)} m" + (f" ({n_comm} from community reports)" if n_comm else "") + ".")
    else:
        reasons.append("No reported incidents near this route in the dataset.")
    if wet:
        reasons.append(f"Weather is '{weather}', so visibility is lower.")
    if confidence != "high":
        reasons.append(f"Data covers only {round(coverage * 100)}% of this route, so treat the score as a rough guide.")

    return {
        "route_id": route_id,
        "safety_score": round(score, 1),
        "out_of": 10,
        "confidence": confidence,
        "data_coverage_pct": round(coverage * 100),
        "time_context": "night" if night else "day",
        "bright_path_pct": bright_pct,
        "cctv_count": len(cctv),
        "help_points": [{"kind": h["kind"], "name": h["name"]} for h in help_pts],
        "incident_count": len(incidents),
        "factor_scores": {k: round(v, 2) for k, v in factors.items()},
        "penalties": {"incidents": round(penalty_incidents, 2), "weather": penalty_weather},
        "caution_segments": _segments(samples, flags),
        "explanation": reasons,
        "disclaimer": "Scores are guidance from limited (demo) data, never a guarantee of safety.",
    }


def _segments(samples: list[tuple[float, float]], flags: list[str | None]) -> list[dict]:
    """Group consecutive flagged samples into caution segments."""
    segs: list[dict] = []
    cur = None
    for s, f in zip(samples, flags):
        if f and cur and cur["reason"] == f:
            cur["end"] = [round(s[0], 6), round(s[1], 6)]
            cur["points"] += 1
        elif f:
            cur = {"reason": f, "start": [round(s[0], 6), round(s[1], 6)], "end": [round(s[0], 6), round(s[1], 6)], "points": 1}
            segs.append(cur)
        else:
            cur = None
    for seg in segs:
        seg["approx_length_m"] = int(seg.pop("points") * SAMPLE_STEP_M)
    return segs


def point_snapshot(latitude: float, longitude: float, hour: int) -> dict:
    data = load_data()
    p = (latitude, longitude)
    hour = int(hour) % 24
    light = _zone_hits(p, data["lighting"])
    act = _zone_hits(p, data["activity"], hour)
    help_pts = [h for h in data["help_points"] if haversine_m(p, (h["lat"], h["lon"])) <= HELP_RADIUS_M]
    incidents = [i for i in data["incidents"] if haversine_m(p, (i["lat"], i["lon"])) <= 150]
    # A tiny 2-point "route" around the point reuses the same scoring logic.
    d = 0.0004
    snap = score_route([[latitude - d, longitude], [latitude + d, longitude]], hour, route_id="point")
    return {
        "latitude": latitude, "longitude": longitude, "hour": hour,
        "safety_score": snap["safety_score"], "confidence": snap["confidence"],
        "lighting": sorted({z["type"] for z in light}) or ["unknown"],
        "activity": sorted({z["type"] for z in act}) or ["unknown"],
        "help_points_nearby": [h["name"] for h in help_pts],
        "incidents_within_150m": len(incidents),
        "disclaimer": snap["disclaimer"],
    }


def add_report(latitude: float, longitude: float, category: str, description: str) -> dict:
    category = category.strip().lower().replace(" ", "_")
    if category not in REPORT_CATEGORIES:
        return {"status": "rejected", "error": f"category must be one of {sorted(REPORT_CATEGORIES)}"}
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return {"status": "rejected", "error": "invalid coordinates"}
    reports = load_reports()
    report = {
        "id": f"CR-{len(reports) + 1:04d}",
        "lat": round(latitude, 6), "lon": round(longitude, 6),
        "category": category, "description": description.strip()[:280],
        "reported": datetime.now().isoformat(timespec="seconds"),
    }
    reports.append(report)
    REPORTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORTS_FILE, "w", encoding="utf-8") as f:
        json.dump(reports, f, indent=2)
    return {"status": "saved", "report": report, "note": "This report now lowers safety scores for routes passing within 80 m."}


# ------------------------------------------------------------------ MCP tools

@mcp.tool()
def analyze_route(route_id: str, coordinates: list[list[float]], hour: int, weather: str = "unknown") -> str:
    """Score one route for safety (0-10) with an explanation.
    coordinates: [[lat, lon], ...] along the route. hour: 0-23 local time of travel.
    weather: condition text such as 'clear' or 'rain' ('unknown' if not known)."""
    try:
        return json.dumps(score_route(coordinates, hour, weather, route_id))
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        return json.dumps({"route_id": route_id, "error": str(exc)})


@mcp.tool()
def get_safety_score(latitude: float, longitude: float, hour: int) -> str:
    """Safety snapshot around a single point at a given hour (0-23)."""
    return json.dumps(point_snapshot(latitude, longitude, hour))


@mcp.tool()
def check_unsafe_zones(coordinates: list[list[float]], hour: int) -> str:
    """List the stretches of a route ([[lat, lon], ...]) that need caution at the given hour."""
    try:
        res = score_route(coordinates, hour)
        return json.dumps({"caution_segments": res["caution_segments"], "incident_count": res["incident_count"]})
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
def report_unsafe_location(latitude: float, longitude: float, category: str, description: str = "") -> str:
    """Save a community report about an unsafe spot. category: poor_lighting, isolated,
    harassment, theft, accident_prone or other."""
    return json.dumps(add_report(latitude, longitude, category, description))


@mcp.tool()
def list_reports_near(latitude: float, longitude: float, radius_m: float = 500) -> str:
    """List community reports within radius_m metres of a point."""
    p = (latitude, longitude)
    hits = [r for r in load_reports() if haversine_m(p, (r["lat"], r["lon"])) <= radius_m]
    return json.dumps({"count": len(hits), "reports": hits})


if __name__ == "__main__":
    mcp.run()
