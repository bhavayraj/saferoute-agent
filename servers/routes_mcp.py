"""Routes & Weather MCP server.

Exposes three tools to the agent:
  * geocode(place)                -> coordinates for a place name
  * get_routes(origin, destination) -> up to 3 alternative routes with geometry
  * get_weather(lat, lon)         -> current weather near a point

Data sources
------------
* Live mode (default, needs internet):
    - Routing: public OSRM servers at routing.openstreetmap.de (OpenStreetMap data)
    - Geocoding: Nominatim (OpenStreetMap)
    - Weather: Open-Meteo (no API key)
* Offline mode (SAFEROUTE_DATA_MODE=offline, or automatic fallback when the
  live service cannot be reached): places come from data/places_bengaluru.json
  and routes are *approximate* straight-segment paths (clearly labelled as such).
  Weather is reported as "unknown" in offline mode; it is never invented.

Run standalone:  python -m servers.routes_mcp
"""

from __future__ import annotations

import difflib
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as MCPServer

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from servers.geo import haversine_m, offset_point, path_length_m  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PLACES_FILE = ROOT / "data" / "places_bengaluru.json"
USER_AGENT = "SafeRouteAgent/1.0 (hackathon project; https://github.com)"
HTTP_TIMEOUT_S = float(os.environ.get("SAFEROUTE_HTTP_TIMEOUT", "8"))

# Average speeds used only for offline approximate routes.
OFFLINE_SPEED_KMH = {"foot": 4.8, "car": 20.0}
OFFLINE_ROAD_FACTOR = 1.25  # straight line -> road distance

mcp = MCPServer("saferoute-routes")


def _mode() -> str:
    return os.environ.get("SAFEROUTE_DATA_MODE", "auto").strip().lower()


def _http_json(url: str) -> dict | list:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:  # noqa: S310 (fixed https hosts)
        return json.loads(resp.read().decode("utf-8"))


def _load_places() -> list[dict]:
    with open(PLACES_FILE, encoding="utf-8") as f:
        return json.load(f)["places"]


def _gazetteer_lookup(place: str) -> dict | None:
    q = place.strip().lower()
    places = _load_places()
    for p in places:
        names = [p["name"].lower(), *[a.lower() for a in p["aliases"]]]
        if q in names:
            return p
    for p in places:  # substring match either way
        names = [p["name"].lower(), *[a.lower() for a in p["aliases"]]]
        if any(q in n or n in q for n in names if len(n) >= 4):
            return p
    all_names = {n: p for p in places for n in [p["name"].lower(), *[a.lower() for a in p["aliases"]]]}
    close = difflib.get_close_matches(q, list(all_names), n=1, cutoff=0.75)
    return all_names[close[0]] if close else None


def geocode_place(place: str) -> dict:
    hit = _gazetteer_lookup(place)
    if hit:
        return {"query": place, "name": hit["name"], "lat": hit["lat"], "lon": hit["lon"], "source": "offline-gazetteer"}
    if _mode() == "offline":
        return {"query": place, "error": f"'{place}' is not in the offline place list. Add it to data/places_bengaluru.json or use live mode."}
    try:
        url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
            {"q": f"{place}, Bengaluru, India", "format": "json", "limit": 1}
        )
        res = _http_json(url)
        if res:
            r = res[0]
            return {"query": place, "name": r.get("display_name", place), "lat": float(r["lat"]), "lon": float(r["lon"]), "source": "nominatim"}
        return {"query": place, "error": f"No match found for '{place}'."}
    except Exception as exc:  # network or parsing problem
        return {"query": place, "error": f"Live geocoding unavailable ({type(exc).__name__}) and place not in offline list."}


def _offline_routes(o: tuple[float, float], d: tuple[float, float], profile: str) -> list[dict]:
    """Three approximate alternatives: direct, left detour and right detour."""
    speed = OFFLINE_SPEED_KMH.get(profile, OFFLINE_SPEED_KMH["foot"])
    shapes = {
        "A": [o, offset_point(o, d, 0.5, 0.0), d],
        "B": [o, offset_point(o, d, 0.35, 0.16), offset_point(o, d, 0.7, 0.14), d],
        "C": [o, offset_point(o, d, 0.35, -0.16), offset_point(o, d, 0.7, -0.14), d],
    }
    routes = []
    for rid, pts in shapes.items():
        dist_m = path_length_m(pts) * OFFLINE_ROAD_FACTOR
        routes.append({
            "id": rid,
            "distance_km": round(dist_m / 1000, 2),
            "duration_min": round(dist_m / 1000 / speed * 60, 1),
            "geometry": [[round(p[0], 6), round(p[1], 6)] for p in pts],
            "source": "offline-approximate",
        })
    return routes


def _osrm_routes(o: tuple[float, float], d: tuple[float, float], profile: str) -> list[dict]:
    service = "routed-foot" if profile == "foot" else "routed-car"
    coords = f"{o[1]},{o[0]};{d[1]},{d[0]}"  # OSRM wants lon,lat
    url = (
        f"https://routing.openstreetmap.de/{service}/route/v1/driving/{coords}"
        "?alternatives=3&overview=full&geometries=geojson&steps=false"
    )
    data = _http_json(url)
    if data.get("code") != "Ok" or not data.get("routes"):
        raise RuntimeError(f"OSRM returned {data.get('code')}")
    routes = []
    for i, r in enumerate(data["routes"][:3]):
        geometry = [[round(lat, 6), round(lon, 6)] for lon, lat in r["geometry"]["coordinates"]]
        routes.append({
            "id": "ABC"[i],
            "distance_km": round(r["distance"] / 1000, 2),
            "duration_min": round(r["duration"] / 60, 1),
            "geometry": geometry,
            "source": "osrm-openstreetmap",
        })
    return routes


def find_routes(origin_lat: float, origin_lon: float, dest_lat: float, dest_lon: float, profile: str = "foot") -> dict:
    profile = "car" if profile.lower() in {"car", "drive", "driving", "cab", "auto"} else "foot"
    o, d = (origin_lat, origin_lon), (dest_lat, dest_lon)
    straight_km = round(haversine_m(o, d) / 1000, 2)
    warning = None
    if _mode() != "offline":
        try:
            return {"profile": profile, "straight_line_km": straight_km, "routes": _osrm_routes(o, d, profile)}
        except Exception as exc:
            warning = f"Live routing unavailable ({type(exc).__name__}); showing approximate offline routes."
    result = {"profile": profile, "straight_line_km": straight_km, "routes": _offline_routes(o, d, profile)}
    result["warning"] = warning or "Offline mode: routes are approximate straight-segment paths, not turn-by-turn road geometry."
    return result


WEATHER_CODES = {
    0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "fog",
    51: "drizzle", 53: "drizzle", 55: "drizzle", 61: "rain", 63: "rain", 65: "heavy rain",
    80: "rain showers", 81: "rain showers", 82: "heavy rain showers", 95: "thunderstorm",
    96: "thunderstorm", 99: "thunderstorm",
}


def current_weather(latitude: float, longitude: float) -> dict:
    if _mode() == "offline":
        return {"condition": "unknown", "source": "offline", "note": "Weather is not available offline; it is not factored in."}
    try:
        url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({
            "latitude": latitude, "longitude": longitude,
            "current": "temperature_2m,precipitation,weather_code,is_day", "timezone": "auto",
        })
        cur = _http_json(url)["current"]
        code = int(cur.get("weather_code", -1))
        return {
            "condition": WEATHER_CODES.get(code, "unknown"),
            "temperature_c": cur.get("temperature_2m"),
            "precipitation_mm": cur.get("precipitation"),
            "is_day": bool(cur.get("is_day")),
            "source": "open-meteo",
        }
    except Exception as exc:
        return {"condition": "unknown", "source": "unavailable", "note": f"Weather service unreachable ({type(exc).__name__})."}


# ---------------------------------------------------------------- MCP tools

@mcp.tool()
def geocode(place: str) -> str:
    """Convert a place name in Bengaluru (e.g. 'MSRIT', 'Majestic') into latitude/longitude."""
    return json.dumps(geocode_place(place))


@mcp.tool()
def get_routes(origin_lat: float, origin_lon: float, dest_lat: float, dest_lon: float, profile: str = "foot") -> str:
    """Get up to 3 alternative routes between two points. profile is 'foot' or 'car'.
    Each route has an id, distance_km, duration_min and geometry as [[lat, lon], ...]."""
    return json.dumps(find_routes(origin_lat, origin_lon, dest_lat, dest_lon, profile))


@mcp.tool()
def get_weather(latitude: float, longitude: float) -> str:
    """Get current weather near a point (condition, temperature, precipitation, day/night)."""
    return json.dumps(current_weather(latitude, longitude))


if __name__ == "__main__":
    mcp.run()
