"""Generate the SYNTHETIC demo safety dataset (data/safety_data_bengaluru_sample.json).

No real crime, lighting or CCTV records are used. The dataset is built around the
demo scenario "MSRIT -> Majestic" so the three offline route alternatives differ
in a way that shows off the explainable scoring:

* Route A (direct)   - shortest, but has a poorly lit / isolated stretch at night
                       and two synthetic incident reports.
* Route B (east)     - longer, mostly well lit and busy, with help points and CCTV.
* Route C (west)     - in between.

A few extra zones are scattered around central Bengaluru so other queries also
get partial data coverage.

Run:  python scripts/generate_sample_data.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from servers.geo import offset_point  # noqa: E402

MSRIT = (13.0306, 77.5649)
MAJESTIC = (12.9774, 77.5713)


def on_route(fraction: float, side: float, lateral: float = 0.0) -> tuple[float, float]:
    """Point on an offline route shape. side: 0 direct, +0.15 east route, -0.15 west route."""
    o, d = MSRIT, MAJESTIC
    if side == 0:
        p = offset_point(o, d, fraction, lateral)
    else:
        # Offline B/C routes bend through 35% and 70% waypoints; approximate the bend.
        if fraction <= 0.35:
            wp = offset_point(o, d, 0.35, side * 16 / 15)
            t = fraction / 0.35
            p = (o[0] + (wp[0] - o[0]) * t, o[1] + (wp[1] - o[1]) * t)
        elif fraction <= 0.7:
            a = offset_point(o, d, 0.35, side * 16 / 15)
            b = offset_point(o, d, 0.7, side * 14 / 15)
            t = (fraction - 0.35) / 0.35
            p = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        else:
            b = offset_point(o, d, 0.7, side * 14 / 15)
            t = (fraction - 0.7) / 0.3
            p = (b[0] + (d[0] - b[0]) * t, b[1] + (d[1] - b[1]) * t)
    return (round(p[0], 6), round(p[1], 6))


def main() -> None:
    lighting, activity, help_points, cctv, incidents = [], [], [], [], []

    def light(t, f, side, r):
        lat, lon = on_route(f, side)
        lighting.append({"id": f"L{len(lighting) + 1:02d}", "type": t, "lat": lat, "lon": lon, "radius_m": r})

    def act(t, f, side, r, hours):
        lat, lon = on_route(f, side)
        activity.append({"id": f"A{len(activity) + 1:02d}", "type": t, "lat": lat, "lon": lon, "radius_m": r, "hours": hours})

    def helpp(kind, name, f, side, lateral=0.0):
        lat, lon = on_route(f, side, lateral)
        help_points.append({"id": f"H{len(help_points) + 1:02d}", "kind": kind, "name": name, "lat": lat, "lon": lon})

    def cam(f, side):
        lat, lon = on_route(f, side)
        cctv.append({"id": f"C{len(cctv) + 1:02d}", "lat": lat, "lon": lon})

    def incident(cat, sev, f, side, date):
        lat, lon = on_route(f, side)
        incidents.append({"id": f"I{len(incidents) + 1:02d}", "category": cat, "severity": sev, "lat": lat, "lon": lon, "reported": date, "source": "synthetic"})

    # Shared start/end: campus gate and bus station are well lit and busy.
    for side in (0, 0.15, -0.15):
        light("well_lit", 0.03, side, 350)
        light("well_lit", 0.97, side, 350)
    act("busy", 0.02, 0, 400, [7, 23])
    act("busy", 0.98, 0, 500, [5, 24])

    # Route A (direct): dark, isolated middle section with incidents.
    light("well_lit", 0.18, 0, 350)
    light("poorly_lit", 0.45, 0, 700)
    light("poorly_lit", 0.62, 0, 450)
    act("isolated", 0.5, 0, 650, [20, 6])
    incident("harassment", 2, 0.44, 0, "2026-10-18")
    incident("theft", 2, 0.58, 0, "2026-11-02")
    cam(0.1, 0)
    helpp("store_24x7", "24x7 pharmacy (demo)", 0.85, 0)

    # Route B (east): well lit, busy late, help points, CCTV.
    for f in (0.15, 0.3, 0.45, 0.6, 0.75, 0.88):
        light("well_lit", f, 0.15, 450)
    act("busy", 0.3, 0.15, 600, [6, 24])
    act("busy", 0.6, 0.15, 600, [6, 24])
    act("busy", 0.82, 0.15, 450, [6, 24])
    helpp("police", "Police help point (demo)", 0.32, 0.15)
    helpp("hospital", "Hospital (demo)", 0.55, 0.15)
    helpp("metro", "Metro station (demo)", 0.78, 0.15)
    helpp("store_24x7", "24x7 store (demo)", 0.66, 0.15)
    for f in (0.12, 0.25, 0.38, 0.5, 0.62, 0.74, 0.86):
        cam(f, 0.15)

    # Route C (west): mixed.
    light("well_lit", 0.25, -0.15, 450)
    light("poorly_lit", 0.55, -0.15, 400)
    light("well_lit", 0.8, -0.15, 450)
    act("busy", 0.25, -0.15, 450, [7, 22])
    helpp("police", "Police help point (demo)", 0.75, -0.15)
    cam(0.25, -0.15)
    cam(0.8, -0.15)
    incident("accident_prone", 1, 0.55, -0.15, "2026-09-27")

    # A few scattered zones elsewhere in central Bengaluru (partial coverage for other trips).
    extra_light = [((12.9755, 77.6068), "well_lit", 600), ((12.9763, 77.5929), "poorly_lit", 500),
                   ((12.9719, 77.6412), "well_lit", 600), ((12.9352, 77.6245), "well_lit", 600),
                   ((12.9293, 77.5826), "well_lit", 500), ((13.0237, 77.5503), "well_lit", 450)]
    for (lat, lon), t, r in extra_light:
        lighting.append({"id": f"L{len(lighting) + 1:02d}", "type": t, "lat": lat, "lon": lon, "radius_m": r})
    activity.append({"id": f"A{len(activity) + 1:02d}", "type": "busy", "lat": 12.9755, "lon": 77.6068, "radius_m": 600, "hours": [8, 24]})
    activity.append({"id": f"A{len(activity) + 1:02d}", "type": "isolated", "lat": 12.9763, "lon": 77.5929, "radius_m": 500, "hours": [19, 6]})
    help_points.append({"id": f"H{len(help_points) + 1:02d}", "kind": "metro", "name": "Metro station (demo)", "lat": 12.9755, "lon": 77.6068})

    out = {
        "_disclaimer": "SYNTHETIC DEMO DATA generated by scripts/generate_sample_data.py for the wHACKiest 2026 hackathon. "
                       "Not real crime, lighting or CCTV records. Do not use for real-world safety decisions.",
        "lighting": lighting, "activity": activity, "help_points": help_points,
        "cctv": cctv, "incidents": incidents,
    }
    path = ROOT / "data" / "safety_data_bengaluru_sample.json"
    path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {path} ({len(lighting)} lighting, {len(activity)} activity, {len(help_points)} help, "
          f"{len(cctv)} cctv, {len(incidents)} incidents)")


if __name__ == "__main__":
    main()
