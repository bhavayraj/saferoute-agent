// SafeRoute front end: renders agent results on a Leaflet map, or on a built-in
// SVG preview when map tiles/Leaflet cannot load (e.g. offline).
"use strict";

const $ = (id) => document.getElementById(id);
const COLORS = { Safest: "#3fb950", Balanced: "#d29922", Fastest: "#58a6ff", Alternative: "#6e7b8b" };
let lastResult = null;
let activeId = null;
let reportPoint = null;
let leafletMap = null;
let leafletLayers = [];
let svgView = null; // {minLat, maxLat, minLon, maxLon, w, h, pad}

// ---------------------------------------------------------------- helpers
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function scoreClass(s) { return s >= 6.5 ? "score-hi" : s >= 4 ? "score-mid" : "score-lo"; }
function routeColor(r) { return COLORS[r.labels[0]] || COLORS.Alternative; }
function setStatus(msg, isError = false) {
  const el = $("status");
  el.textContent = msg;
  el.classList.toggle("error", isError);
  el.classList.toggle("hidden", !msg);
}
async function api(path, body) {
  const res = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
  const data = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
  if (!res.ok || data.error) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

// ---------------------------------------------------------------- map setup
function initMap() {
  if (window.L) {
    try {
      leafletMap = L.map("map", { zoomControl: true }).setView([12.99, 77.57], 13);
      L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
        maxZoom: 19, attribution: "&copy; OpenStreetMap contributors &copy; CARTO",
      }).addTo(leafletMap);
      leafletMap.on("click", (e) => setReportPoint(e.latlng.lat, e.latlng.lng));
      return;
    } catch (e) { leafletMap = null; }
  }
  $("map").classList.add("hidden");
  $("svgmap").classList.remove("hidden");
  note("Offline map preview: map tiles could not load, so routes are drawn on a plain grid.");
  drawSvg();
}
function note(text) { $("mapNote").textContent = text; $("mapNote").classList.toggle("hidden", !text); }

function setReportPoint(lat, lon) {
  reportPoint = [lat, lon];
  $("reportPos").textContent = `Selected: ${lat.toFixed(5)}, ${lon.toFixed(5)}`;
  if (leafletMap) drawLeaflet(); else drawSvg();
}

// ---------------------------------------------------------------- Leaflet rendering
function drawLeaflet() {
  leafletLayers.forEach((l) => l.remove());
  leafletLayers = [];
  const r = lastResult;
  const bounds = [];
  if (r) {
    const ordered = [...r.routes].sort((a, b) => (a.id === activeId) - (b.id === activeId));
    for (const rt of ordered) {
      const active = rt.id === activeId;
      const line = L.polyline(rt.geometry, { color: routeColor(rt), weight: active ? 7 : 4, opacity: active ? 1 : 0.55 })
        .addTo(leafletMap).bindTooltip(`Route ${rt.id}: ${rt.safety.safety_score}/10`);
      line.on("click", () => selectRoute(rt.id));
      leafletLayers.push(line);
      rt.geometry.forEach((p) => bounds.push(p));
      if (active) {
        for (const seg of rt.safety.caution_segments) {
          leafletLayers.push(L.circleMarker(seg.start, { radius: 7, color: "#f85149", fillOpacity: 0.8 })
            .addTo(leafletMap).bindTooltip(`Caution: ${seg.reason} (~${seg.approx_length_m} m)`));
        }
      }
    }
    if (r.origin) leafletLayers.push(L.circleMarker([r.origin.lat, r.origin.lon], { radius: 8, color: "#fff", fillColor: "#3fb950", fillOpacity: 1 }).addTo(leafletMap).bindTooltip("Start: " + r.origin.name));
    if (r.destination) leafletLayers.push(L.circleMarker([r.destination.lat, r.destination.lon], { radius: 8, color: "#fff", fillColor: "#f5c518", fillOpacity: 1 }).addTo(leafletMap).bindTooltip("Destination: " + r.destination.name));
  }
  if (reportPoint) leafletLayers.push(L.circleMarker(reportPoint, { radius: 6, color: "#ff7b72", dashArray: "3" }).addTo(leafletMap).bindTooltip("Report location"));
  if (bounds.length && r && !r._fitted) { leafletMap.fitBounds(bounds, { padding: [40, 40] }); r._fitted = true; }
}

// ---------------------------------------------------------------- SVG fallback rendering
function project(lat, lon) {
  const v = svgView;
  const x = v.pad + ((lon - v.minLon) / (v.maxLon - v.minLon)) * (v.w - 2 * v.pad);
  const y = v.pad + ((v.maxLat - lat) / (v.maxLat - v.minLat)) * (v.h - 2 * v.pad);
  return [x, y];
}
function unproject(x, y) {
  const v = svgView;
  const lon = v.minLon + ((x - v.pad) / (v.w - 2 * v.pad)) * (v.maxLon - v.minLon);
  const lat = v.maxLat - ((y - v.pad) / (v.h - 2 * v.pad)) * (v.maxLat - v.minLat);
  return [lat, lon];
}
function drawSvg() {
  const box = $("svgmap");
  const w = box.clientWidth || 900, h = box.clientHeight || 700;
  const r = lastResult;
  const pts = r ? r.routes.flatMap((rt) => rt.geometry) : [[12.96, 77.54], [13.04, 77.62]];
  let minLat = Math.min(...pts.map((p) => p[0])), maxLat = Math.max(...pts.map((p) => p[0]));
  let minLon = Math.min(...pts.map((p) => p[1])), maxLon = Math.max(...pts.map((p) => p[1]));
  // Keep aspect ratio roughly true (1 deg lon is shorter than 1 deg lat at this latitude).
  const k = Math.cos((minLat + maxLat) / 2 * Math.PI / 180);
  const spanLat = Math.max(maxLat - minLat, 0.005), spanLon = Math.max((maxLon - minLon) * k, 0.005);
  const scale = Math.max(spanLat / (h - 120), spanLon / (w - 120));
  const cLat = (minLat + maxLat) / 2, cLon = (minLon + maxLon) / 2;
  const halfLat = (scale * (h - 120)) / 2 * 1.1, halfLon = ((scale * (w - 120)) / 2 * 1.1) / k;
  svgView = { minLat: cLat - halfLat, maxLat: cLat + halfLat, minLon: cLon - halfLon, maxLon: cLon + halfLon, w, h, pad: 60 };

  let s = `<svg viewBox="0 0 ${w} ${h}" xmlns="http://www.w3.org/2000/svg">`;
  s += `<defs><pattern id="g" width="40" height="40" patternUnits="userSpaceOnUse"><path d="M40 0H0V40" fill="none" stroke="#1a222c" stroke-width="1"/></pattern></defs>`;
  s += `<rect width="${w}" height="${h}" fill="url(#g)"/>`;
  if (r) {
    const ordered = [...r.routes].sort((a, b) => (a.id === activeId) - (b.id === activeId));
    for (const rt of ordered) {
      const active = rt.id === activeId;
      const d = rt.geometry.map((p, i) => (i ? "L" : "M") + project(p[0], p[1]).map((n) => n.toFixed(1)).join(" ")).join(" ");
      s += `<path d="${d}" fill="none" stroke="${routeColor(rt)}" stroke-width="${active ? 7 : 4}" stroke-linecap="round" stroke-linejoin="round" opacity="${active ? 1 : 0.5}" data-route="${esc(rt.id)}" style="cursor:pointer"/>`;
      const mid = rt.geometry[Math.floor(rt.geometry.length / 2)];
      const [mx, my] = project(mid[0], mid[1]);
      s += `<g data-route="${esc(rt.id)}" style="cursor:pointer"><rect x="${mx + 10}" y="${my - 13}" width="96" height="24" rx="12" fill="#161b22" stroke="${routeColor(rt)}"/>`;
      s += `<text x="${mx + 58}" y="${my + 4}" fill="#e6edf3" font-size="12" text-anchor="middle">Route ${esc(rt.id)} · ${rt.safety.safety_score}/10</text></g>`;
      if (active) {
        for (const seg of rt.safety.caution_segments) {
          const [x1, y1] = project(seg.start[0], seg.start[1]);
          s += `<circle cx="${x1}" cy="${y1}" r="8" fill="#f85149" opacity=".85"><title>Caution: ${esc(seg.reason)}</title></circle>`;
          s += `<text x="${x1 - 12}" y="${y1 + 4}" fill="#ffb3ad" font-size="11" text-anchor="end">⚠ ${esc(seg.reason)}</text>`;
        }
      }
    }
    for (const [pl, color, tag] of [[r.origin, "#3fb950", "Start"], [r.destination, "#f5c518", "Destination"]]) {
      if (!pl) continue;
      const [x, y] = project(pl.lat, pl.lon);
      s += `<circle cx="${x}" cy="${y}" r="9" fill="${color}" stroke="#fff" stroke-width="2"/>`;
      s += `<text x="${x + 14}" y="${y + 4}" fill="#e6edf3" font-size="13" font-weight="600">${tag}: ${esc(pl.name)}</text>`;
    }
  } else {
    s += `<text x="${w / 2}" y="${h / 2}" fill="#8b98a8" font-size="15" text-anchor="middle">Plan a trip to see routes here</text>`;
  }
  if (reportPoint) {
    const [x, y] = project(reportPoint[0], reportPoint[1]);
    s += `<circle cx="${x}" cy="${y}" r="7" fill="none" stroke="#ff7b72" stroke-width="2" stroke-dasharray="3 2"/>`;
  }
  s += "</svg>";
  box.innerHTML = s;
  const svg = box.querySelector("svg");
  svg.addEventListener("click", (e) => {
    const t = e.target.closest("[data-route]");
    if (t) { selectRoute(t.getAttribute("data-route")); return; }
    const rect = svg.getBoundingClientRect();
    const [lat, lon] = unproject((e.clientX - rect.left) * (w / rect.width), (e.clientY - rect.top) * (h / rect.height));
    setReportPoint(lat, lon);
  });
}

function redraw() { if (leafletMap) drawLeaflet(); else drawSvg(); }

// ---------------------------------------------------------------- results panel
function selectRoute(id) {
  activeId = id;
  document.querySelectorAll(".card").forEach((c) => c.classList.toggle("active", c.dataset.id === id));
  const rt = lastResult.routes.find((r) => r.id === id);
  $("why").innerHTML = rt.safety.explanation.map((x) => `<li>${esc(x)}</li>`).join("") +
    `<li class="hint">${esc(rt.safety.disclaimer)}</li>`;
  redraw();
}

function renderResult(r) {
  lastResult = r;
  const rec = r.recommendation;
  activeId = rec ? rec.route_id : r.routes[0]?.id;
  const w = r.weather || {};
  const notes = [];
  if (r.routes_warning) notes.push(r.routes_warning);
  if (w.condition === "unknown") notes.push("Weather unavailable, so it is not factored in.");
  $("recommend").innerHTML = rec
    ? `<b>Recommendation</b><br>${esc(rec.summary)}<div class="meta">Travel time ${String(r.hour).padStart(2, "0")}:00 · ${esc(r.profile || "foot")} · weather: ${esc(w.condition || "unknown")} · agent: ${esc(r.mode)}${r.model ? " (" + esc(r.model) + ")" : ""}</div>`
    : `<b>Agent answer</b><br>${esc(r.answer || "No routes were analysed.")}`;
  $("cards").innerHTML = r.routes.map((rt) => {
    const s = rt.safety;
    const badges = rt.labels.map((l) => `<span class="badge ${l.toLowerCase()}">${esc(l)}</span>`).join("");
    return `<div class="card" data-id="${esc(rt.id)}">
      <div class="card-head"><span class="card-title" style="color:${routeColor(rt)}">Route ${esc(rt.id)}${badges}</span>
      <span>${Math.round(rt.duration_min)} min · ${rt.distance_km} km</span></div>
      <div class="stats">
        <div class="stat"><div class="v">${s.bright_path_pct}%</div><div class="k">Bright path</div></div>
        <div class="stat"><div class="v">${s.cctv_count}</div><div class="k">CCTVs</div></div>
        <div class="stat"><div class="v ${scoreClass(s.safety_score)}">${s.safety_score}/10</div><div class="k">Safety score</div></div>
      </div>
      <div class="meta">Confidence: ${esc(s.confidence)} (${s.data_coverage_pct}% data coverage) · ${s.incident_count} incident(s) · ${s.help_points.length} help point(s)</div>
    </div>`;
  }).join("");
  document.querySelectorAll(".card").forEach((c) => c.addEventListener("click", () => selectRoute(c.dataset.id)));
  $("trace").innerHTML = r.trace.map((t) =>
    `<li><span class="srv">[${esc(t.server)}]</span> ${esc(t.tool)}(${esc(Object.entries(t.args).map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : v}`).join(", "))}) · ${t.ms} ms</li>`).join("");
  $("traceCount").textContent = r.trace.length;
  $("results").classList.remove("hidden");
  setStatus(notes.join(" "));
  if (activeId) selectRoute(activeId); else redraw();
}

$("tripForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("goBtn").disabled = true;
  setStatus("Agent is calling MCP tools…");
  try {
    renderResult(await api("/api/plan", { query: $("query").value, mode: $("mode").value }));
  } catch (err) {
    setStatus(err.message, true);
  } finally {
    $("goBtn").disabled = false;
  }
});

// ---------------------------------------------------------------- community report
$("reportBtn").addEventListener("click", async () => {
  if (!reportPoint) { $("reportMsg").textContent = "Click on the map first to choose the spot."; return; }
  try {
    const res = await api("/api/report", { latitude: reportPoint[0], longitude: reportPoint[1], category: $("reportCat").value, description: $("reportDesc").value });
    $("reportMsg").textContent = `Saved as ${res.report.id}. Plan the trip again to see it reflected in the scores.`;
    $("reportDesc").value = "";
  } catch (err) { $("reportMsg").textContent = err.message; }
});

// ---------------------------------------------------------------- SOS flow (explicit confirmation)
let sosPos = null;
function currentPosition() {
  return new Promise((resolve) => {
    const fallback = () => resolve(lastResult?.origin ? { lat: lastResult.origin.lat, lon: lastResult.origin.lon, src: "trip start point" } : null);
    if (!navigator.geolocation) return fallback();
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ lat: p.coords.latitude, lon: p.coords.longitude, src: "device GPS" }),
      fallback, { timeout: 4000 });
  });
}
$("sosBtn").addEventListener("click", async () => {
  $("modal").classList.remove("hidden");
  $("sosPreview").classList.add("hidden");
  $("sosConfirmBtn").classList.add("hidden");
  $("sosPreviewBtn").classList.remove("hidden");
  $("sosLoc").textContent = "Getting your location…";
  sosPos = await currentPosition();
  $("sosLoc").textContent = sosPos
    ? `Location: ${sosPos.lat.toFixed(5)}, ${sosPos.lon.toFixed(5)} (from ${sosPos.src})`
    : "Location unavailable: allow location access or plan a trip first.";
  try {
    const book = await api("/api/contacts");
    $("sosContacts").innerHTML = book.trusted_contacts.map((c) =>
      `<div class="contact"><span><b>${esc(c.name)}</b> · ${esc(c.relation)} · ${esc(c.phone)}</span>
       <button class="secondary share" data-name="${esc(c.name)}">Share location</button></div>`).join("") +
      (book.national_helpline ? `<p class="hint">National emergency helpline: <b>${esc(book.national_helpline.number)}</b> (${esc(book.national_helpline.name)})</p>` : "");
    document.querySelectorAll(".share").forEach((b) => b.addEventListener("click", () => prepare(b.dataset.name)));
  } catch (err) { $("sosContacts").textContent = err.message; }
});
let pending = null;
async function prepare(contact) {
  if (!sosPos) return;
  pending = { latitude: sosPos.lat, longitude: sosPos.lon, message: $("sosMsg").value, ...(contact ? { contact } : {}) };
  let res;
  try { res = await api("/api/sos", { ...pending, confirm: false }); }
  catch (err) { $("sosPreview").textContent = err.message; $("sosPreview").classList.remove("hidden"); return; }
  $("sosPreview").innerHTML = `<b>Preview (not sent):</b> to ${esc([].concat(res.to).join(", "))}<br>${esc(res.preview)}`;
  $("sosPreview").classList.remove("hidden");
  $("sosConfirmBtn").classList.remove("hidden");
  $("sosPreviewBtn").classList.add("hidden");
}
$("sosPreviewBtn").addEventListener("click", () => prepare(null));
$("sosConfirmBtn").addEventListener("click", async () => {
  if (!pending) return;
  $("sosConfirmBtn").disabled = true;
  $("sosPreview").innerHTML = "Sending…";
  let res;
  try { res = await api("/api/sos", { ...pending, confirm: true }); }
  catch (err) { $("sosPreview").textContent = err.message; return; }
  finally { $("sosConfirmBtn").disabled = false; }
  $("sosPreview").innerHTML = `<b>✓ ${res.status === "sent_simulated" ? "Alert logged (simulated delivery)" : esc(res.status)}</b> to ${esc([].concat(res.to).join(", "))} at ${esc(res.sent_at)}`;
  $("sosConfirmBtn").classList.add("hidden");
  pending = null;
});
$("sosClose").addEventListener("click", () => $("modal").classList.add("hidden"));

// ---------------------------------------------------------------- boot
api("/api/config").then((c) => {
  if (c.llm_available) {
    const opt = $("mode").querySelector('option[value="llm"]');
    opt.disabled = false;
    opt.textContent = `Agent: LLM mode (${c.llm_model})`;
  }
}).catch(() => {});
initMap();
window.addEventListener("resize", () => { if (!leafletMap) drawSvg(); });
