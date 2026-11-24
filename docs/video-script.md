# SafeRoute Agent: Video Pitch Script (target 4:15, limit 3–5 min)

**Team:** Bhavayraj Singhal (Lead), Avi Sinha, Akshit Singh · Track 1

**Format:** screen recording with voice-over. Show the PPT for the pitch parts and the running app for the demo.
**Upload:** YouTube → Visibility **Unlisted** (or Public). Unlisted is allowed by the guidelines and anyone with the link can watch.

## Before you record (5 minutes of setup)

1. Open the PPT in slideshow mode.
2. Start the app in **offline mode** so the demo is identical to the slides and doesn't depend on Wi-Fi:
   - Windows PowerShell: `$env:SAFEROUTE_DATA_MODE="offline"; python -m web.app`
   - macOS/Linux: `SAFEROUTE_DATA_MODE=offline python -m web.app`
3. Open **http://127.0.0.1:8000** in the browser, zoom to 100%, and close other tabs.
4. Keep a terminal window ready in the project folder for the CLI shot.
5. Record with OBS / Xbox Game Bar (Win + Alt + R) / QuickTime, or Loom. Speak slowly; total 4–4.5 minutes.

> Wording rule: everything below describes only what the prototype really does. Where something is planned, the script says "planned".

---

## 0:00 – 0:20 · Title slide (Slide 1)

**On screen:** Slide 1.

> "Hi, we're Bhavayraj, Avi and Akshit from Ramaiah Institute of Technology. This is **SafeRoute Agent**, our entry for **Track 1, Make MCP Matter**. It's an AI agent, built on the Model Context Protocol, that finds the *safest* way home, not just the fastest."

## 0:20 – 0:55 · Problem (Slide 2)

**On screen:** Slide 2. Point to the 52% card.

> "Map apps are great at time and distance. But when you leave college at 10 PM, the real question is: *which way is safe right now?* A YouGov survey found that **52% of urban Indian women** always or often feel unsafe walking alone at night, and **56%** avoid going out alone at night.
> Today the options are navigation apps that ignore safety, SOS apps that only help after something goes wrong, or texting friends and guessing."

## 0:55 – 1:25 · Solution (Slide 3)

**On screen:** Slide 3.

> "SafeRoute Agent takes a plain-English request, compares alternative routes on a **safety score out of 10**, explains *why*, and marks caution spots on the map. Users can report unsafe spots, and SOS to trusted contacts is always one tap away, but **only after the user confirms**."

## 1:25 – 2:00 · Architecture & tech (Slides 5 and 4)

**On screen:** Slide 5 (architecture), then a quick flash of Slide 4.

> "Here's how it works. The agent is an **MCP host**. It talks to three MCP servers over stdio, eleven tools in total.
> A **Routes and Weather server** wraps OpenStreetMap routing, geocoding and Open-Meteo weather.
> Our custom **Safety Analysis server** is the core. It samples each route every 50 metres and scores lighting, how busy the area is at that hour, nearby help points, CCTV and reported incidents.
> Our custom **Emergency server** handles contacts and SOS.
> Everything is Python with the official MCP SDK, a Starlette backend and a Leaflet front end. The agent runs in planner mode with no API key, or in LLM mode, where any OpenAI-compatible model like Gemini chooses the tools."

## 2:00 – 3:30 · Live demo (running app)

**On screen:** browser at http://127.0.0.1:8000

1. **(2:00)** Show the request box. Click **Find safest route**.
   > "I'll ask: *find me the safest route from MSRIT to Majestic at 10 PM*."
2. **(2:10)** Point to the three route cards and the recommendation.
   > "The agent found three routes. Route **B** scores **7.2 out of 10**: 98% well-lit, 7 CCTV cameras, 4 help points. The fastest route, **A**, scores only **2.7**. The agent recommends B for about **6 extra minutes**, and tells me why."
3. **(2:30)** Click the **Route A** card.
   > "If I select the fastest route, you can see the caution spot: a poorly lit stretch. Every score also shows its **data coverage** and confidence, so it never pretends to be 100% sure."
4. **(2:45)** Expand **Agent trace: MCP tool calls**.
   > "This is the part that makes it MCP: every step is a real tool call. Geocode twice, get routes, get weather, then analyze_route once per route."
5. **(3:00)** Click **SOS**. Click **Prepare SOS to all contacts**.
   > "In an emergency, I press SOS. The agent prepares the message with a Google Maps link to my location, but **nothing is sent yet**."
6. **(3:12)** Click **Confirm & send**.
   > "Only when I confirm does it go out. In this prototype, delivery is **simulated** and logged. Real SMS is on our hack-day list. In LLM mode these SOS tools aren't even offered to the model, so an AI can never send an alert on its own."
7. **(3:22)** *(optional, 8 s)* Switch to the terminal and run:
   `python -m agent.cli "Find me the safest route from MSRIT to Majestic at 10 PM"`
   > "The same agent also runs from the command line."

## 3:30 – 3:55 · Novelty & impact (Slides 6 and 7)

**On screen:** Slide 6, then Slide 7.

> "What's new: safety exposed as **reusable MCP tools** that any AI assistant can call, **honest, explainable scoring**, and **controlled actions** that need the user's consent.
> The prototype already runs end to end, with three MCP servers, eleven tools, thirteen automated tests and zero API cost. To be clear, the safety data in this demo is a **synthetic sample dataset**; plugging in real city data is our next step."

## 3:55 – 4:15 · Business model & close (Slide 8)

**On screen:** Slide 8.

> "We'll start with a pilot at our own campus: free safe routing and SOS for everyone, a premium tier for live trip sharing, and dashboards for colleges and companies with late-night commutes. On hack day we plan to add real data, real SMS alerts, ElevenLabs voice guidance and AWS hosting.
> SafeRoute Agent: less magic, more utility, and a safer way home. Thank you!"

---

### Checklist after recording

- [ ] Length between 3:00 and 5:00
- [ ] YouTube visibility set to **Unlisted** or **Public** (not Private)
- [ ] Open the link in a private/incognito window to confirm it plays without signing in
