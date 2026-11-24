"""Emergency Assistance MCP server (custom-built).

Tools exposed to the agent:
  * get_emergency_contacts()                                   -> trusted contacts + national helpline
  * share_live_location(contact_name, latitude, longitude, confirm) -> share location with one contact
  * notify_emergency_contacts(latitude, longitude, message, confirm) -> SOS to every trusted contact

Controlled by design: the sending tools do NOTHING unless confirm=true. Without it
they return a preview and status "confirmation_required". The agent host never
sets confirm=true by itself — only an explicit tap by the user in the app does.

Delivery is SIMULATED in this prototype: confirmed alerts are written to
data/outbox/sent_alerts.jsonl (with a Google Maps link to the location) instead
of being sent as real SMS/WhatsApp messages. A real messaging gateway is future work.

Run standalone:  python -m servers.emergency_mcp
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as MCPServer

ROOT = Path(__file__).resolve().parent.parent
CONTACTS_FILE = ROOT / "data" / "emergency_contacts.json"          # your own (git-ignored)
CONTACTS_EXAMPLE = ROOT / "data" / "emergency_contacts.example.json"
OUTBOX_FILE = ROOT / "data" / "outbox" / "sent_alerts.jsonl"        # simulated delivery log (git-ignored)

mcp = MCPServer("saferoute-emergency")


def load_contacts() -> dict:
    if not CONTACTS_FILE.exists():
        shutil.copyfile(CONTACTS_EXAMPLE, CONTACTS_FILE)
    with open(CONTACTS_FILE, encoding="utf-8") as f:
        return json.load(f)


def maps_link(latitude: float, longitude: float) -> str:
    return f"https://www.google.com/maps?q={latitude:.6f},{longitude:.6f}"


def _log(entry: dict) -> None:
    OUTBOX_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTBOX_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def share_location(contact_name: str, latitude: float, longitude: float, confirm: bool = False) -> dict:
    contacts = load_contacts()["trusted_contacts"]
    match = next((c for c in contacts if c["name"].lower() == contact_name.strip().lower()), None)
    if not match:
        return {"status": "error", "error": f"No trusted contact named '{contact_name}'.",
                "available": [c["name"] for c in contacts]}
    text = f"I'm sharing my live location with you via SafeRoute: {maps_link(latitude, longitude)}"
    if not confirm:
        return {"status": "confirmation_required", "to": match["name"], "preview": text,
                "note": "Nothing was sent. The user must confirm in the app."}
    entry = {"type": "share_location", "to": match["name"], "phone": match["phone"], "message": text,
             "sent_at": datetime.now().isoformat(timespec="seconds"), "delivery": "simulated"}
    _log(entry)
    return {"status": "sent_simulated", **entry}


def notify_all(latitude: float, longitude: float, message: str = "", confirm: bool = False) -> dict:
    book = load_contacts()
    contacts = book["trusted_contacts"]
    body = (message.strip() or "I need help.") + f" My location: {maps_link(latitude, longitude)}"
    if not confirm:
        return {"status": "confirmation_required", "to": [c["name"] for c in contacts], "preview": body,
                "helpline": book.get("national_helpline"),
                "note": "Nothing was sent. The user must confirm in the app."}
    sent_at = datetime.now().isoformat(timespec="seconds")
    for c in contacts:
        _log({"type": "sos", "to": c["name"], "phone": c["phone"], "message": body, "sent_at": sent_at, "delivery": "simulated"})
    return {"status": "sent_simulated", "to": [c["name"] for c in contacts], "message": body, "sent_at": sent_at,
            "helpline": book.get("national_helpline"),
            "note": "Prototype: alerts are logged to data/outbox/sent_alerts.jsonl, not sent as real SMS."}


# ---------------------------------------------------------------- MCP tools

@mcp.tool()
def get_emergency_contacts() -> str:
    """List the user's trusted emergency contacts and the national emergency helpline."""
    return json.dumps(load_contacts())


@mcp.tool()
def share_live_location(contact_name: str, latitude: float, longitude: float, confirm: bool = False) -> str:
    """Share the current location with one trusted contact. Sends nothing unless confirm is true;
    without confirmation it returns a preview for the user to approve."""
    return json.dumps(share_location(contact_name, latitude, longitude, confirm))


@mcp.tool()
def notify_emergency_contacts(latitude: float, longitude: float, message: str = "", confirm: bool = False) -> str:
    """Send an SOS with the location to ALL trusted contacts. Sends nothing unless confirm is true;
    without confirmation it returns a preview for the user to approve."""
    return json.dumps(notify_all(latitude, longitude, message, confirm))


if __name__ == "__main__":
    mcp.run()
