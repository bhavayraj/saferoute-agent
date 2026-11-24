"""Command-line interface for the SafeRoute agent.

Examples:
    python -m agent.cli "Find the safest route from MSRIT to Majestic at 10 PM"
    python -m agent.cli --llm "I'm walking from MSRIT to Majestic at 10 PM, which way is safest?"
    python -m agent.cli --tools          # list every tool the MCP servers expose
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from agent.llm_agent import llm_configured, run_llm_agent
from agent.mcp_host import MCPHost
from agent.planner import TripRequestError, plan_trip


def render(result: dict) -> str:
    lines = []
    o, d = result.get("origin") or {}, result.get("destination") or {}
    lines.append(f"\nTrip: {o.get('name', '?')} -> {d.get('name', '?')} at {result['hour']:02d}:00 "
                 f"({result.get('profile', 'foot')})  [mode: {result['mode']}]")
    w = result.get("weather") or {}
    lines.append(f"Weather: {w.get('condition', 'unknown')} (source: {w.get('source', '-')})")
    if result.get("routes_warning"):
        lines.append(f"Note: {result['routes_warning']}")
    lines.append("")
    lines.append(f"{'Route':<7}{'Label':<18}{'Time':>8}{'Dist':>9}{'Safety':>9}{'Bright':>8}{'CCTV':>6}  Confidence")
    for r in result["routes"]:
        s = r["safety"]
        lines.append(f"{r['id']:<7}{' & '.join(r['labels']):<18}{r['duration_min']:>6.0f} m{r['distance_km']:>7.2f}km"
                     f"{s['safety_score']:>6.1f}/10{s['bright_path_pct']:>7}%{s['cctv_count']:>6}  {s['confidence']} ({s['data_coverage_pct']}% data)")
    rec = result.get("recommendation")
    if rec:
        lines.append("\nRecommendation: " + rec["summary"])
        lines.append("Why:")
        lines += [f"  - {x}" for x in rec["why"]]
    lines.append("\nMCP tool calls:")
    for t in result["trace"]:
        lines.append(f"  [{t['server']}] {t['tool']}({', '.join(f'{k}={v}' for k, v in t['args'].items())})  {t['ms']} ms")
    lines.append("\nScores are guidance from limited demo data, never a guarantee of safety.")
    return "\n".join(lines)


async def main_async(args: argparse.Namespace) -> int:
    async with MCPHost() as host:
        if args.tools:
            for name, t in host.tools.items():
                print(f"[{t['server']}] {name}: {t['description'].splitlines()[0] if t['description'] else ''}")
            return 0
        query = " ".join(args.query) or "Find the safest route from MSRIT to Majestic at 10 PM"
        try:
            if args.llm:
                if not llm_configured():
                    print("LLM mode needs LLM_BASE_URL and LLM_MODEL (and usually LLM_API_KEY). See README.", file=sys.stderr)
                    return 2
                result = await run_llm_agent(host, query)
            else:
                result = await plan_trip(host, query)
        except TripRequestError as exc:
            print(f"Sorry: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(result, indent=2) if args.json else render(result))
        return 0


def main() -> None:
    p = argparse.ArgumentParser(description="SafeRoute Agent: safest-route recommendations via MCP tools.")
    p.add_argument("query", nargs="*", help="Trip request in plain English")
    p.add_argument("--llm", action="store_true", help="Let an LLM choose the MCP tool calls")
    p.add_argument("--json", action="store_true", help="Print the raw JSON result")
    p.add_argument("--tools", action="store_true", help="List the MCP tools and exit")
    sys.exit(asyncio.run(main_async(p.parse_args())))


if __name__ == "__main__":
    main()
