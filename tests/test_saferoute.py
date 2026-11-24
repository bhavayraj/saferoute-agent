"""Tests for SafeRoute Agent. Run:  python -m unittest discover -s tests -v"""

import asyncio
import json
import os
import unittest
from datetime import datetime

os.environ["SAFEROUTE_DATA_MODE"] = "offline"  # tests never need the internet

from agent.mcp_host import MCPHost  # noqa: E402
from agent.planner import parse_request, plan_trip  # noqa: E402
from servers import emergency_mcp, safety_mcp  # noqa: E402
from servers.geo import haversine_m, sample_path  # noqa: E402
from servers.routes_mcp import find_routes, geocode_place  # noqa: E402

MSRIT, MAJESTIC = (13.0306, 77.5649), (12.9774, 77.5713)


class GeoTests(unittest.TestCase):
    def test_haversine_known_distance(self):
        # MSRIT -> Majestic is roughly 5.9 km in a straight line.
        self.assertAlmostEqual(haversine_m(MSRIT, MAJESTIC) / 1000, 5.97, delta=0.1)

    def test_sample_path_spacing(self):
        s = sample_path([MSRIT, MAJESTIC], 50)
        self.assertEqual(s[0], MSRIT)
        self.assertEqual(s[-1], MAJESTIC)
        self.assertTrue(115 <= len(s) <= 125)


class ParserTests(unittest.TestCase):
    def test_parse_pm_time_and_places(self):
        r = parse_request("Find me the safest route from MSRIT to Majestic at 10 PM")
        self.assertEqual((r["origin"], r["destination"], r["hour"], r["profile"]), ("MSRIT", "Majestic", 22, "foot"))

    def test_parse_car_and_minutes(self):
        r = parse_request("from Yeshwanthpur to Malleshwaram at 9:30 pm by cab")
        self.assertEqual((r["hour"], r["profile"]), (21, "car"))

    def test_default_hour_is_now(self):
        r = parse_request("from MSRIT to Hebbal", now=datetime(2026, 11, 24, 7, 0))
        self.assertEqual(r["hour"], 7)


class SafetyScoringTests(unittest.TestCase):
    def setUp(self):
        self.routes = {r["id"]: r for r in find_routes(*MSRIT, *MAJESTIC)["routes"]}

    def test_three_offline_routes(self):
        self.assertEqual(sorted(self.routes), ["A", "B", "C"])

    def test_well_lit_route_beats_dark_route_at_night(self):
        a = safety_mcp.score_route(self.routes["A"]["geometry"], 22)
        b = safety_mcp.score_route(self.routes["B"]["geometry"], 22)
        self.assertGreater(b["safety_score"], a["safety_score"])
        self.assertTrue(any(s["reason"] == "poorly lit" for s in a["caution_segments"]))

    def test_score_has_explanation_and_bounds(self):
        r = safety_mcp.score_route(self.routes["C"]["geometry"], 23, "rain")
        self.assertTrue(0 <= r["safety_score"] <= 10)
        self.assertIn("confidence", r)
        self.assertTrue(any("rain" in e for e in r["explanation"]))

    def test_unknown_area_reports_low_confidence(self):
        r = safety_mcp.score_route([[12.85, 77.40], [12.86, 77.41]], 22)
        self.assertEqual(r["confidence"], "low")
        self.assertEqual(r["data_coverage_pct"], 0)


class EmergencyTests(unittest.TestCase):
    def test_sos_requires_confirmation(self):
        res = emergency_mcp.notify_all(13.03, 77.56, "help", confirm=False)
        self.assertEqual(res["status"], "confirmation_required")


class GeocodeTests(unittest.TestCase):
    def test_alias(self):
        self.assertEqual(geocode_place("majestic")["name"], "Majestic (Kempegowda Bus Station)")

    def test_unknown_offline(self):
        self.assertIn("error", geocode_place("Some Unknown Place XYZ"))


class EndToEndMCPTests(unittest.TestCase):
    """Starts the three real MCP servers over stdio and runs the agent through them."""

    def test_agent_through_mcp(self):
        async def run():
            async with MCPHost() as host:
                self.assertGreaterEqual(len(host.tools), 11)
                result = await plan_trip(host, "from MSRIT to Majestic at 10 PM")
                blocked = await host.call("notify_emergency_contacts", {"latitude": 13.03, "longitude": 77.56})
                return result, blocked
        result, blocked = asyncio.run(run())
        self.assertEqual(result["recommendation"]["route_id"], "B")
        tools_called = [t["tool"] for t in result["trace"]]
        self.assertEqual(tools_called.count("analyze_route"), 3)
        self.assertEqual(blocked["status"], "confirmation_required")


if __name__ == "__main__":
    unittest.main()
