"""SafeRoute web app: map UI + JSON API on top of the MCP agent.

Run:  python -m web.app      then open http://127.0.0.1:8000
"""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from agent.llm_agent import llm_configured, run_llm_agent
from agent.mcp_host import MCPHost
from agent.planner import TripRequestError, plan_trip

STATIC = Path(__file__).resolve().parent / "static"


async def index(_: Request) -> FileResponse:
    return FileResponse(STATIC / "index.html")


async def config(_: Request) -> JSONResponse:
    return JSONResponse({"llm_available": llm_configured(), "llm_model": os.environ.get("LLM_MODEL"),
                         "data_mode": os.environ.get("SAFEROUTE_DATA_MODE", "auto")})


async def plan(request: Request) -> JSONResponse:
    body = await request.json()
    query = (body.get("query") or "").strip()
    if not query:
        return JSONResponse({"error": "Type a trip, e.g. 'from MSRIT to Majestic at 10 PM'."}, status_code=400)
    try:
        async with MCPHost() as host:
            if body.get("mode") == "llm":
                if not llm_configured():
                    return JSONResponse({"error": "LLM mode is not configured on this server (see README)."}, status_code=400)
                result = await run_llm_agent(host, query)
            else:
                result = await plan_trip(host, query)
    except TripRequestError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:  # surface unexpected errors to the UI instead of a blank page
        return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, status_code=500)
    return JSONResponse(result)


async def contacts(_: Request) -> JSONResponse:
    async with MCPHost() as host:
        return JSONResponse(await host.call("get_emergency_contacts", {}))


async def sos(request: Request) -> JSONResponse:
    """SOS / share location. confirm must be true — it is only sent after the user taps Confirm."""
    b = await request.json()
    args = {"latitude": float(b["latitude"]), "longitude": float(b["longitude"]), "confirm": bool(b.get("confirm", False))}
    async with MCPHost() as host:
        if b.get("contact"):
            res = await host.call("share_live_location", {"contact_name": b["contact"], **args})
        else:
            res = await host.call("notify_emergency_contacts", {"message": b.get("message", ""), **args})
        res["trace"] = host.trace
    return JSONResponse(res)


async def report(request: Request) -> JSONResponse:
    b = await request.json()
    async with MCPHost() as host:
        res = await host.call("report_unsafe_location", {
            "latitude": float(b["latitude"]), "longitude": float(b["longitude"]),
            "category": b.get("category", "other"), "description": b.get("description", "")})
    return JSONResponse(res, status_code=200 if res.get("status") == "saved" else 400)


app = Starlette(routes=[
    Route("/", index),
    Route("/api/config", config),
    Route("/api/plan", plan, methods=["POST"]),
    Route("/api/contacts", contacts),
    Route("/api/sos", sos, methods=["POST"]),
    Route("/api/report", report, methods=["POST"]),
    Mount("/static", StaticFiles(directory=STATIC), name="static"),
])


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    print(f"SafeRoute running at http://127.0.0.1:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
