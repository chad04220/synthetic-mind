// app.js — the page: one WebSocket brings an init snapshot and then small ticks (~10 a second, only when
// something changed); the 3D world (vox.js) draws the land, the panels draw the mind. Only the visible tab
// is redrawn, and only the parts that changed.
import { Reg, loadRegistry, buildTextures, iconURL, itemName, findBlock, normName, label, K, clearIcons } from "./blocks.js";

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const big = (n) => n == null ? "–" : n >= 1e9 ? (n / 1e9).toFixed(1) + "B" : n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e4 ? (n / 1e3).toFixed(1) + "k" : String(Math.round(n));
const pct = (v) => v == null ? "–" : `${Math.round(v * 100)}%`;
const dur = (s) => { s = Math.max(0, Math.round(s || 0)); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60); return h ? `${h}h ${m}m` : m ? `${m}m ${s % 60}s` : `${s}s`; };
const clock = (t) => new Date((t || Date.now() / 1000) * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
const ago = (t) => { const s = Date.now() / 1000 - t; return s < 60 ? "just now" : s < 3600 ? `${Math.round(s / 60)} min ago` : s < 86400 ? `${Math.round(s / 3600)} h ago` : `${Math.round(s / 86400)} d ago`; };
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const clamp = (v, a, b) => (v < a ? a : v > b ? b : v);
function setHTML(el, html) { if (el && el._h !== html) { el._h = html; el.innerHTML = html; } }
function setText(el, t) { if (el && el.textContent !== t) el.textContent = t; }
const store = { get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } }, set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private window */ } } };

async function api(name, body = {}) {
  const r = await fetch(`/api/${name}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || r.statusText);
  return j.result;
}
let toastTimer;
function toast(text, ms = 2800) {
  if (!text || typeof text !== "string") return;
  let t = $(".toast"); if (!t) { t = document.createElement("div"); t.className = "toast"; t.setAttribute("role", "status"); document.body.append(t); }
  t.textContent = text; t.classList.add("show"); clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove("show"), ms);
}
let stageTimer;
function stageToast(text, ms = 2600) {   // a short note over the 3D view (visible while the pointer is locked)
  const el = $("#stageToast"); if (!text) return; el.textContent = text; el.hidden = false;
  clearTimeout(stageTimer); stageTimer = setTimeout(() => { el.hidden = true; }, ms);
}
function banner(text) { const b = $("#banner"); b.hidden = !text; if (text) b.textContent = text; }
{ const th = store.get("theme", ""); if (th) document.documentElement.dataset.theme = th; }

// ================================================================== state
const S = {
  view: "home", name: "", settings: {}, model: {}, world: {}, agent: {}, mind: {}, visitor: null,
  decisions: new Map(), events: [], blocksChanged: 0, goals: [], pendingChat: [], thinkingSince: 0,
  creative: store.get("creative", false), creativeBar: store.get("creativeBar", null), sel: 0, mode: "watch",
  mapView: { x: 0, z: 0, s: 3, init: false }, mini: { s: 2 },
};
const NAME = () => S.name || S.agent?.name || "it";
let vox = null;

// ================================================================== the page's own health
const P = { t0: performance.now(), msgs: 0, bytes: 0, msgMs: 0, msgMax: 0, long: 0, longMs: 0, longMax: 0, errors: 0 };
try { new PerformanceObserver((l) => { for (const e of l.getEntries()) { P.long++; P.longMs += e.duration; P.longMax = Math.max(P.longMax, e.duration); } }).observe({ type: "longtask", buffered: false }); } catch { /* not everywhere */ }
addEventListener("error", (e) => { P.errors++; P.lastError = `${e.message} (${e.filename}:${e.lineno})`.slice(0, 300); });
addEventListener("unhandledrejection", (e) => { P.errors++; P.lastError = String(e.reason).slice(0, 300); });
setInterval(() => {
  const now = performance.now(), secs = (now - P.t0) / 1000, v = vox && S.view === "home" ? vox.stats() : null;
  const body = {
    window_s: Math.round(secs), visible: !document.hidden, view: S.view, fps: v ? v.fps : 0, fps_cap: 60,
    draw_ms_3d: v ? v.ms : -1, draw_max_ms_3d: v ? v.frameMax : -1, chunks_3d: v ? v.chunks : -1, draw_calls: v ? v.calls : -1, triangles: v ? v.triangles : -1,
    mesh_avg_ms: v ? v.meshAvg : -1, mesh_max_ms: v ? v.meshMax : -1, edit_visible_ms: v?.editLatLast ?? -1,
    msgs_per_s: +(P.msgs / secs).toFixed(1), kb_per_s: +(P.bytes / 1024 / secs).toFixed(1), msg_avg_ms: +(P.msgMs / Math.max(1, P.msgs)).toFixed(1), msg_max_ms: Math.round(P.msgMax),
    longtasks: P.long, longtask_ms: Math.round(P.longMs), longtask_max_ms: Math.round(P.longMax), js_errors: P.errors, last_error: P.lastError || "",
    dpr: devicePixelRatio, window: `${innerWidth}x${innerHeight}`, browser: navigator.userAgent.slice(0, 160),
    memory_mb: performance.memory ? Math.round(performance.memory.usedJSHeapSize / 2 ** 20) : -1,
  };
  fetch("/api/client_perf", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).catch(() => {});
  S.clientPerf = body;
  Object.assign(P, { t0: now, msgs: 0, bytes: 0, msgMs: 0, msgMax: 0, long: 0, longMs: 0, longMax: 0, errors: 0 });
}, 15000);

// ================================================================== connection
function connect() {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  ws.onmessage = (m) => {
    const t0 = performance.now(); let msg; try { msg = JSON.parse(m.data); } catch { return; }
    try { msg.type === "init" ? init(msg) : tick(msg); } catch (e) { console.error(e); P.errors++; P.lastError = e.message; }
    const dt = performance.now() - t0; P.msgs++; P.bytes += m.data.length; P.msgMs += dt; P.msgMax = Math.max(P.msgMax, dt);
  };
  ws.onopen = () => banner("");
  ws.onclose = () => { banner("Lost contact with the program. Reconnecting…"); setTimeout(connect, 1500); };
}

function init(m) {
  S.settings = m.settings || {}; S.model = m.model || {};
  S.world = {}; S.agent = {}; S.mind = {}; S.decisions.clear(); S.events = []; S.goals = [];
  $("#chat").innerHTML = ""; $("#events").innerHTML = "";
  worldIn(m.world || {}, true);
  S.name = m.name || S.agent.name || "";
  setText($("#name"), S.name || "…"); document.title = S.name ? `${S.name} · Synthetic Mind` : "Synthetic Mind";
  $$(".synthname").forEach((el) => el.textContent = S.name || "it");
  $("#chatText").placeholder = `Say something to ${NAME()}…`;
  const f = m.feeds || {};
  for (const d of f.decision || []) addDecision(d.decision || d);
  const chats = [...(f.chat || [])].sort((a, b) => (a.t || 0) - (b.t || 0));
  for (const e of chats) chatFromEvent(e, true);
  for (const e of [...(f.happening || []), ...chats].sort((a, b) => (a.t || 0) - (b.t || 0))) feedEvent(e);
  for (const e of m.events || []) if (e.kind === "error") banner(e.text);
  if (S.agent.inventory) renderAgentInv(true);
  loadDecisions();
  syncSettings(); renderAll();
  if (store.get("welcomed5", false) === false) { try { $("#welcome").showModal(); } catch { /* old browser */ } store.set("welcomed5", true); }
}
async function loadDecisions() {
  try { const r = await fetch("/api/decisions?limit=100").then((x) => x.json()); for (const d of r.items || r.decisions || r || []) addDecision(d); renderAll(); }
  catch { /* the tick brings the recent ones anyway */ }
}

function worldIn(w, full) {
  if (!w) return;
  for (const k of ["t", "day", "time", "clock", "weather", "light", "places", "spawn"]) if (k in w) S.world[k] = w[k];
  if (w.agent) { Object.assign(S.agent, w.agent); if (w.agent.name && !S.name) S.name = w.agent.name; if ("inventory" in w.agent) S.invDirty = true; }
  if (w.mind) {
    const m = w.mind, oldGoal = S.mind.goal;
    for (const k in m) if (k !== "decisions") S.mind[k] = m[k];
    for (const d of m.decisions || []) addDecision(d);
    if (m.goal && m.goal !== oldGoal) { S.goals.push({ t: S.world.t || Date.now() / 1000, goal: m.goal }); if (S.goals.length > 60) S.goals.shift(); }
    if ("thinking" in m) { if (m.thinking && !S.thinkingSince) S.thinkingSince = performance.now(); if (!m.thinking) S.thinkingSince = 0; }
  }
  if ("visitor" in w) { S.visitor = w.visitor; renderHotbar(); if (!$("#invPanel").hidden) renderInvPanel(); }
  if (w.blocks?.length) S.blocksChanged += w.blocks.length;
  if (vox) {
    try {
      const pass = { ...w };
      if (pass.agent || pass.mind) pass.agent = { ...(pass.agent || {}), ...(pass.mind ? { thinking: pass.mind.thinking } : {}) };
      if (full) pass.full = true;
      vox.update(pass);
    } catch (e) { console.error(e); }
  } else if (w.blocks?.length || w.entities) { (S.voxBacklog ||= []).push({ ...w, full }); if (S.voxBacklog.length > 300) S.voxBacklog.shift(); }
  for (const e of w.events || []) onEvent(e);
}

function tick(m) {
  if (m.settings) { Object.assign(S.settings, m.settings); syncSettings(); }
  if (m.model) { S.model = { ...S.model, ...m.model }; }
  if (m.world) worldIn(m.world, !!m.world.full);
  for (const e of m.events || []) onEvent(e);
  renderAll();
}

function onEvent(e) {
  if (e && !e.kind && e.type) e = { ...e, kind: e.type };
  if (!e || !e.kind) return;
  if (e.id != null) { S.seenEv ||= new Set(); if (S.seenEv.has(e.id)) return; S.seenEv.add(e.id); if (S.seenEv.size > 3000) S.seenEv = new Set([...S.seenEv].slice(-1500)); }
  switch (e.kind) {
    case "decision": { const d = addDecision(e.decision || e); Journal.live("thoughts", { t: d.t, kind: "thought", id: d.id, text: d.thought, action: d.action, reason: d.reason, ms: d.ms }); if (d.say) { /* said arrives as its own event */ } break; }
    case "reflection": feedEvent(e); Journal.live("thoughts", { t: e.t, kind: "reflection", text: e.text }); break;
    case "said": chatFromEvent(e); feedEvent(e); Journal.live("conversations", { t: e.t, with: e.to === "you" ? "you" : "world", kind: "said", lines: [[NAME(), e.text]] }); break;
    case "chat": chatFromEvent(e); Journal.live("conversations", { t: e.t, with: "you", kind: "chat", lines: [[e.who || "you", e.text]] }); break;
    case "practice_started": toast(`🎓 ${NAME()} started practising${e.name ? ` (${e.name})` : ""}.`); feedEvent(e); break;
    case "practice_done": toast(`🎓 Practice finished: ${e.name || "a new adapter"} is ready.`, 5000); feedEvent(e); break;
    case "practice_failed": toast(`Practice failed: ${e.error || "unknown error"}`, 6000); feedEvent(e); break;
    case "error": banner(e.text); setTimeout(() => banner(""), 15000); feedEvent(e); break;
    case "log": break;
    default: feedEvent(e);
  }
}

// ================================================================== decisions
function normDecision(d) {
  const ms = d.ms && typeof d.ms === "object" ? d.ms : { total_ms: d.ms ?? d.latency_ms };
  return { ...d, ms, latency: ms.total_ms ?? ms.action_ms ?? ms.first_ms ?? null, firstMs: ms.first_ms ?? null };
}
function addDecision(raw) {
  if (!raw || raw.id == null) return raw;
  const d = normDecision(raw), old = S.decisions.get(d.id);
  const merged = old ? { ...old, ...d } : d;
  S.decisions.set(d.id, merged);
  if (S.decisions.size > 400) S.decisions.delete(S.decisions.keys().next().value);
  return merged;
}
const decList = () => [...S.decisions.values()].sort((a, b) => (a.t || 0) - (b.t || 0));
const SKILL_ICON = { go_to: "🚶", walk: "🚶", look_at: "👀", mine: "⛏️", mine_nearest: "⛏️", dig: "⛏️", place: "🧱", build: "🏗️", craft: "🛠️", smelt: "🔥", use: "✋",
  put: "📦", take: "📦", eat: "🍽️", attack: "⚔️", follow: "👣", give: "🎁", plant: "🌱", till: "🪏", harvest: "🌾", sleep: "😴", say: "💬", wait: "⏳", stop: "⏹️",
  explore: "🧭", name_place: "📍", note: "📝", collect: "🧺", chop: "🪓" };
function argText(v) {
  if (v == null) return "";
  if (Array.isArray(v)) return v.length <= 3 && v.every((x) => typeof x === "number") ? v.map((x) => Math.round(x)).join(", ") : `${v.length} items`;
  if (typeof v === "object") return Object.entries(v).slice(0, 3).map(([k, x]) => `${k}=${argText(x)}`).join(" ");
  return String(v).length > 40 ? String(v).slice(0, 38) + "…" : String(v);
}
function actionText(a) {
  if (!a) return "–";
  if (typeof a === "string") return a;
  const sk = a.skill || a.name || "?", args = { ...(a.args || {}) };
  let at = "";
  if (!Array.isArray(args) && args.x != null && args.z != null) { at = ` at ${Math.round(args.x)}, ${args.y != null ? Math.round(args.y) + ", " : ""}${Math.round(args.z)}`; delete args.x; delete args.y; delete args.z; }
  const parts =Array.isArray(args) ? args.map(argText) : Object.entries(args).map(([k, v]) => ["block", "item", "x", "target", "text", "name", "what"].includes(k) || Object.keys(args).length === 1 ? argText(v) : `${k}: ${argText(v)}`);
  return `${sk.replace(/_/g, " ")}${parts.length ? " · " + parts.filter(Boolean).join(", ").replace(/_/g, " ") : ""}${at}`;
}
const skillIcon = (a) => SKILL_ICON[(typeof a === "string" ? a : a?.skill || "").split(/[\s(]/)[0]] || "▸";
const msTxt = (v) => v == null ? "–" : v >= 10000 ? `${(v / 1000).toFixed(1)} s` : `${Math.round(v)} ms`;
function latClass(v) { return v == null ? "" : v <= 250 ? "fast" : v <= 800 ? "ok" : "slow"; }
function decSig(d) { return JSON.stringify([d.rating ?? 0, d.correction || "", d.outcome?.ok, d.outcome?.text, d.self?.value, d.latency]); }
function decHTML(d, compact = false) {
  const out = d.outcome, okc = out ? (out.ok === false ? "fail" : "ok") : "run";
  const r = d.rating ?? 0;
  const rate = `<span class="rate" role="group" aria-label="Rate this decision">
    <button class="rb up${r === 1 ? " on" : ""}" data-rate="1" data-id="${esc(d.id)}" title="A good decision" aria-pressed="${r === 1}">👍</button>
    <button class="rb down${r === -1 ? " on" : ""}" data-rate="-1" data-id="${esc(d.id)}" title="A poor decision" aria-pressed="${r === -1}">👎</button></span>`;
  const self = d.self && d.self.value != null ? `<span class="selfj ${d.self.value > 0 ? "pos" : d.self.value < 0 ? "neg" : ""}" title="${esc(d.self.why || "its own judgement, looking back")}">self ${d.self.value > 0 ? "👍" : d.self.value < 0 ? "👎" : "·"}</span>` : "";
  const corr = d.correction ? `<div class="dec-corr">✏️ <b>You showed it:</b> ${esc(d.correction)}</div>`
    : `<details class="dec-fix"><summary>Show it what it should have done</summary><form class="inline" data-correct="${esc(d.id)}"><input name="text" placeholder="e.g. craft planks first" autocomplete="off" aria-label="What it should have done"><button>Save</button></form></details>`;
  return `<div class="dec-top"><span class="dec-time">${clock(d.t)}</span><span class="actk ${okc}" title="${esc(JSON.stringify(d.action || {}))}">${skillIcon(d.action)} ${esc(actionText(d.action))}</span>
      <span class="lat ${latClass(d.latency)}" title="${d.firstMs != null ? `first token ${msTxt(d.firstMs)} · ` : ""}${d.ms?.cached ? "prompt cached · " : ""}${d.ms?.tokens ? d.ms.tokens + " tokens" : ""}">${msTxt(d.latency)}</span>
      ${d.obs_chars ? `<span class="obs" title="Size of what it saw">👁 ${big(d.obs_chars)} ch</span>` : ""}${d.adapter ? `<span class="obs" title="Practised adapter used">🎓 ${esc(d.adapter)}</span>` : ""}${self}<span class="grow"></span>${rate}</div>
    ${d.thought ? `<div class="dec-thought">${esc(d.thought)}</div>` : ""}
    ${d.say ? `<div class="dec-say">💬 “${esc(d.say)}”</div>` : ""}
    ${!compact && d.reason ? `<div class="dec-why">because ${esc(d.reason)}</div>` : ""}
    ${out ? `<div class="dec-out ${okc}">${out.ok === false ? "✗" : "✓"} ${esc(out.text || (out.ok === false ? "failed" : "done"))}</div>` : `<div class="dec-out run">… under way</div>`}
    ${compact ? "" : corr}`;
}
document.addEventListener("click", async (ev) => {
  const b = ev.target.closest("[data-rate]"); if (!b) return;
  const id = b.dataset.id, d = S.decisions.get(id) || [...S.decisions.values()].find((x) => String(x.id) === id); if (!d) return;
  const want = +b.dataset.rate, value = d.rating === want ? 0 : want, was = d.rating;
  d.rating = value || null; renderAll();
  try { await api("agent", { action: "rate", id: d.id, value }); } catch (e) { d.rating = was; renderAll(); toast(e.message); }
});
document.addEventListener("submit", async (ev) => {
  const f = ev.target.closest("[data-correct]"); if (!f) return;
  ev.preventDefault();
  const id = f.dataset.correct, text = f.text.value.trim(); if (!text) return;
  const d = [...S.decisions.values()].find((x) => String(x.id) === id); if (!d) return;
  try { await api("agent", { action: "correct", id: d.id, text }); d.correction = text; toast("Thanks: it will practise with that."); renderAll(); } catch (e) { toast(e.message); }
});

// ================================================================== header
const SKY = { clear: "☀️", cloudy: "☁️", overcast: "☁️", rain: "🌧️", storm: "⛈️", thunder: "⛈️", snow: "❄️", fog: "🌫️" };
function timeText() {
  const w = S.world; let f = w.time;
  if (typeof f === "string") return `Day ${w.day ?? "?"} · ${f}`;
  f = typeof f === "number" && w.clock != null ? (f + 0.25) % 1 : w.clock != null ? (([h, m]) => (+h + +m / 60) / 24)(String(w.clock).split(":")) : f == null ? null : f <= 1 ? f : f <= 24 ? f / 24 : (f % 24000) / 24000;
  const hm = f == null ? "" : `${String(Math.floor(f * 24)).padStart(2, "0")}:${String(Math.floor((f * 24 % 1) * 60)).padStart(2, "0")}`;
  const ic = f == null ? "" : f < 0.23 || f > 0.79 ? "🌙" : f < 0.3 || f > 0.72 ? "🌅" : "";
  const wx = String(w.weather || "clear").toLowerCase(), night = f != null && (f < 0.25 || f > 0.77);
  return `Day ${w.day ?? "?"} · ${ic}${hm} · ${night && wx === "clear" ? "✨" : SKY[wx] || ""} ${wx}`;
}
function medianLatency() {
  const v = decList().map((d) => d.latency).filter((x) => x != null).slice(-60).sort((a, b) => a - b);
  return v.length ? v[Math.floor(v.length / 2)] : null;
}
function deviceText(m) {
  const d = String(m.device || "").toLowerCase();
  if (!d) return "";
  return d === "cpu" ? "on CPU" : `on GPU${d !== "cuda" ? ` (${d})` : ""}`;
}
function renderHeader() {
  const m = S.model, st = S.mind.stats || {};
  setText($("#clock"), S.world.day != null || S.world.time != null ? timeText() : "…");
  const name = m.label || m.model || m.choice || "";
  setText($("#sub"), m.status === "ready" ? `${name} · ${deviceText(m)}${m.adapter ? ` · 🎓 ${m.adapter}` : ""}` : m.status ? `model ${m.status}${m.progress ? " " + pct(m.progress) : ""}${m.detail ? ` · ${m.detail}` : ""}` : "connecting…");
  setText($("#kLatency"), msTxt(st.last_ms ?? decList().at(-1)?.latency));
  setText($("#kMedian"), msTxt(medianLatency()));
  setText($("#kDecisions"), big(st.decisions ?? S.decisions.size));
  setText($("#kBlocks"), big(S.blocksChanged));
  $("#orb").classList.toggle("thinking", !!S.mind.thinking);
  $("#orb").classList.toggle("asleep", !!S.mind.paused);
}
$("#btnHelp").onclick = () => $("#welcome").showModal();

// ================================================================== views
function showView(v) {
  S.view = v;
  $$("#nav button").forEach((x) => x.classList.toggle("on", x.dataset.view === v));
  $$(".view").forEach((el) => el.classList.toggle("on", el.id === `view-${v}`));
  if (vox) vox.pause(v !== "home" || document.hidden);
  if (v === "map") { S.mapDirty = true; requestAnimationFrame(drawBigMap); }
  if (v === "health") pollHealth(true);
  renderAll();
  history.replaceState(null, "", v === "home" ? location.pathname : `#${v}`);
}
$$("#nav button").forEach((b) => b.onclick = () => showView(b.dataset.view));
document.addEventListener("visibilitychange", () => vox?.pause(document.hidden || S.view !== "home"));

let renderQueued = false;
function renderAll() {
  if (renderQueued) return; renderQueued = true;
  requestAnimationFrame(() => {
    renderQueued = false;
    renderHeader();
    if (S.view === "home") renderHome();
    else if (S.view === "mind") renderMind();
    else if (S.view === "thoughts") Journal.open("thoughts");
    else if (S.view === "talks") Journal.open("conversations");
    else if (S.view === "map") { renderMapSide(); drawBigMap(); }
    else if (S.view === "settings") renderSettings();
    else if (S.view === "health") pollHealth();
  });
}

// ================================================================== home
const HEART = (v) => v == null ? null : clamp(v / 20, 0, 1);
function heldHTML(h) {
  if (h == null || h === "" || (typeof h === "object" && !h.item && !h.name && h.id == null)) return '<span class="muted">empty hand</span>';
  const n = typeof h === "object" ? h.item ?? h.name ?? h.id : h;
  return `<img src="${iconURL(n, 32)}" alt=""><span>${esc(itemName(n))}${typeof h === "object" && h.count > 1 ? ` ×${h.count}` : ""}</span>`;
}
function skillText(a) {
  const s = a.skill;
  if (!s) return S.mind.busy_with ? `${S.mind.busy_with}…` : "idle";
  if (typeof s === "string") return s.replace(/_/g, " ");
  return actionText(s);
}
function renderHome() {
  const a = S.agent, m = S.mind, w = S.world;
  setText($("#ovClock"), timeText());
  const pos = a.x != null ? `📍 ${Math.round(a.x)}, ${Math.round(a.y)}, ${Math.round(a.z)}` : "";
  setText($("#ovWhere"), pos);
  setText($("#mcName"), NAME());
  const state = m.paused ? "⏸ paused" : m.thinking ? "💭 thinking…" : m.busy_with === "practising" ? "🎓 practising" : m.busy_with === "reflecting" ? "🪞 reflecting" : a.skill ? "acting" : "idle";
  setText($("#mcState"), state);
  $("#mindCard").classList.toggle("thinking", !!m.thinking);
  setHTML($("#mcHeld"), heldHTML(a.held));
  const thought = m.thought ?? a.thought;
  setHTML($("#mcThought"), thought ? `“${esc(thought)}”` : '<span class="muted">No thoughts yet.</span>');
  setText($("#mcGoal"), m.goal || a.goal || "–");
  setText($("#mcSkill"), skillText(a));
  $("#mcProgress").style.width = `${Math.round(clamp(+a.progress || 0, 0, 1) * 100)}%`;
  const hp = HEART(a.health), fd = HEART(a.food);
  $("#mcHealth").style.width = `${Math.round((hp ?? 0) * 100)}%`; setText($("#mcHealthN"), a.health != null ? `${Math.round(a.health)}/20` : "–");
  $("#mcFood").style.width = `${Math.round((fd ?? 0) * 100)}%`; setText($("#mcFoodN"), a.food != null ? `${Math.round(a.food)}/20` : "–");
  const last = decList().at(-1);
  const box = $("#mcDecision");
  if (last && !box.contains(document.activeElement)) { const sig = last.id + decSig(last); if (box._sig !== sig) { box._sig = sig; box.innerHTML = `<div class="ld-label">Last decision</div><div class="dec compact">${decHTML(last, true)}</div>`; } }
  // chat: thinking indicator
  const ind = $("#chat .typing");
  if (m.thinking && !ind) { const d = document.createElement("div"); d.className = "msg mind typing"; d.innerHTML = '<span class="vx-dots"><i></i><i></i><i></i></span>'; $("#chat").append(d); $("#chat").scrollTop = 1e9; }
  else if (!m.thinking && ind) ind.remove();
  setText($("#chatHint"), S.settings["mind.radio"] === false && S.mode !== "visit" ? "radio off: it hears you only nearby" : "");
  if (S.invDirty) renderAgentInv();
  drawMini();
}
const normSlot = (s) => Array.isArray(s) ? (s[0] == null ? null : { item: s[0], count: s[1] ?? 1 }) : s || null;
function slotHTML(s, i, sel) {
  s = normSlot(s);
  if (!s || (!s.item && !s.name && s.id == null)) return `<div class="slot${sel ? " sel" : ""}" data-slot="${i}"></div>`;
  const n = s.item ?? s.name ?? s.id;
  return `<div class="slot${sel ? " sel" : ""}" data-slot="${i}" title="${esc(itemName(n))}${s.count > 1 ? ` ×${s.count}` : ""}"><img src="${iconURL(n, 40)}" alt="">${s.count > 1 ? `<b>${s.count}</b>` : ""}</div>`;
}
function renderAgentInv(force) {
  S.invDirty = false;
  if (!Reg.ready && !force) return;
  const inv = S.agent.inventory || [];
  const slots = Array.isArray(inv) ? inv.map(normSlot) : Object.entries(inv).map(([item, count]) => ({ item, count }));
  const n = Math.max(36, slots.length);
  setHTML($("#agentInv"), Array.from({ length: n }, (_, i) => slotHTML(slots[i], i, false)).join(""));
  const filled = slots.filter((s) => s && (s.item || s.name || s.id != null)).length;
  setText($("#invCount"), `${filled} of ${n} slots`);
}

// chat
function chatLine(who, text, cls = "", t) {
  const d = document.createElement("div"); d.className = `msg ${cls}`;
  d.innerHTML = `${cls.includes("mind") ? `<b>${esc(who)}</b>` : ""}<span>${esc(text)}</span>${t ? `<small>${clock(t)}</small>` : ""}`;
  const box = $("#chat"), ind = box.querySelector(".typing");
  ind ? box.insertBefore(d, ind) : box.append(d);
  while (box.children.length > 150) box.firstChild.remove();
  box.scrollTop = box.scrollHeight;
  return d;
}
function chatFromEvent(e, initial) {
  if (e.kind === "said" || (e.kind !== "chat" && e.text && !e.who)) {
    if (!e.text) return;
    chatLine(NAME(), e.text, `mind${e.to === "you" ? " to-you" : ""}`, e.t);
  } else if (e.kind === "chat") {
    const who = e.who || "you";
    if (who === "you") {
      const i = S.pendingChat.findIndex((p) => p.text === e.text);
      if (i >= 0) { S.pendingChat[i].el.classList.remove("pending"); S.pendingChat.splice(i, 1); return; }
      chatLine("you", e.text, "user", e.t);
    } else chatLine(who, e.text, "mind other", e.t);
  }
}
async function sendChat(text) {
  const el = chatLine("you", text, "user pending", Date.now() / 1000);
  S.pendingChat.push({ text, el }); if (S.pendingChat.length > 10) S.pendingChat.shift();
  try { const r = await api("chat", { text }); el.classList.remove("pending"); if (typeof r === "string" && r) toast(r); }
  catch (e) { el.classList.add("failed"); toast(e.message); }
}
$("#chatForm").onsubmit = (ev) => { ev.preventDefault(); const t = $("#chatText").value.trim(); if (!t) return; $("#chatText").value = ""; sendChat(t); };

// the live events feed
const EV_ICON = { said: "💬", chat: "🗨️", happening: "✨", reflection: "🪞", practice_started: "🎓", practice_done: "🎓", practice_failed: "⚠️", error: "⚠️", system: "ℹ️", decision: "🧠" };
function evText(e) {
  if (e.kind === "said") return `${NAME()}: “${e.text}”${e.to && e.to !== "all" ? ` (to ${e.to})` : ""}`;
  if (e.kind === "chat") return `${e.who === "you" || !e.who ? "You" : e.who}: “${e.text}”`;
  if (e.kind === "practice_started") return `Practice started${e.by ? ` (by ${e.by})` : ""}${e.name ? `: ${e.name}` : ""}`;
  if (e.kind === "practice_done") return `Practice done: ${e.name || ""}${e.info?.loss != null ? ` · loss ${(+e.info.loss).toFixed(3)}` : ""}`;
  if (e.kind === "practice_failed") return `Practice failed: ${e.error || ""}`;
  if (e.kind === "reflection") return `Looking back: ${e.text}`;
  if (e.kind === "gave") return `${e.name || "Someone"} gave ${e.to === 1 || e.to === S.agent.id ? NAME() : "someone"} ${e.count || ""} ${itemName(e.item)}`.replace(/\s+/g, " ");
  if (e.kind === "joined") return `${e.name || "A visitor"} walked into the world.`;
  if (e.kind === "left") return `${e.name || "The visitor"} left.`;
  if (e.kind === "weather") return `The weather turns: ${e.weather}.`;
  if (e.kind === "death" || e.kind === "died") return `${e.name || "Someone"} died${e.cause ? ` (${e.cause})` : ""}.`;
  if (e.kind === "practice_started" || e.kind === "practice_done" || e.kind === "practice_failed") return "";
  return e.text || (QUIET.has(e.kind) ? "" : e.what || e.title || "");
}
const QUIET = new Set(["decision", "skill_start", "skill_end", "block", "blocks", "log", "tick", "set", "hurt", "pickup", "picked_up", "move"]);
function feedEvent(e) {
  const text = evText(e); if (!text) return;
  S.events.push(e); if (S.events.length > 200) S.events.shift();
  const box = $("#events"), d = document.createElement("div");
  d.className = `ev k-${esc(e.kind)}`;
  d.innerHTML = `<span class="ev-ic">${EV_ICON[e.kind] || e.icon || "•"}</span><span class="ev-t">${esc(text)}</span><span class="ev-when">${clock(e.t)}</span>`;
  box.prepend(d); while (box.children.length > 120) box.lastChild.remove();
}

// ------------------------------------------------------------------ visiting: modes, hotbar, inventory
// the block an item places (items.json `place`), else a block of the same name
function blockForItem(n) { const it = Reg.items.get(normName(n)); return findBlock(it?.place ?? it?.block ?? n); }
const DEFAULT_BAR = [["grass_block", "grass"], ["dirt"], ["cobblestone"], ["oak_planks", "planks"], ["stone_bricks", "bricks"], ["glass"], ["oak_log", "log"], ["torch"], ["bricks", "white_wool"]];
function creativeSlots() {
  if (!Reg.ready) return Array(9).fill(null);
  if (!S.creativeBar) S.creativeBar = DEFAULT_BAR.map((alts) => alts.map((n) => findBlock(n)?.id).find((x) => x != null) ?? null);
  return S.creativeBar.map((id) => id == null ? null : { id, item: findBlock(id)?.key, count: 1 });
}
function hotSlots() {
  if (S.creative) return creativeSlots();
  const inv = S.visitor?.inventory || [];
  return Array.from({ length: 9 }, (_, i) => normSlot(inv[i])).map((s) => s && (s.item || s.name || s.id != null) ? { ...s, id: blockForItem(s.item ?? s.name ?? s.id)?.id } : null);
}
function renderHotbar() {
  const visiting = S.mode === "visit";
  $("#hotbar").hidden = !visiting; $("#btnInv").hidden = !visiting; $("#btnCam").hidden = !visiting;
  if (!visiting) return;
  const slots = hotSlots();
  setHTML($("#hotbar"), slots.map((s, i) => slotHTML(s, i, i === S.sel).replace('class="slot', `data-key="${i + 1}" class="slot`)).join(""));
  vox?.setHotbar({ slots, selected: S.sel, creative: S.creative });
}
$("#hotbar").addEventListener("click", (e) => { const s = e.target.closest("[data-slot]"); if (s) selectSlot(+s.dataset.slot); });
function selectSlot(i) {
  S.sel = i; renderHotbar();
  if (!S.creative) api("visitor", { action: "select", slot: i }).catch(() => {});
}
let moveBusy = false, moveNext = null;
function sendMove(body) {
  if (moveBusy) { moveNext = body; return; }
  moveBusy = true;
  api("visitor", body).catch(() => {}).finally(() => { moveBusy = false; if (moveNext) { const n = moveNext; moveNext = null; sendMove(n); } });
}
function voxCommand(body, quiet) {
  if (S.creative) body.creative = true;
  if (body.action === "move") { sendMove(body); return Promise.resolve(); }
  return api("visitor", body).then((r) => {
    if (r && typeof r === "object" && r.ok === false) { const err = new Error(r.text || "That didn't work."); throw err; }
    const t = typeof r === "string" ? r : r?.text; if (t && !quiet) stageToast(t); return r;
  })
    .catch((e) => { if (!quiet) stageToast(e.message); throw e; });
}
async function setMode(mode) {
  if (mode === S.mode) return;
  const was = S.mode; S.mode = mode;
  $$("#modes [data-mode]").forEach((x) => x.classList.toggle("on", x.dataset.mode === mode));
  $("#stage").classList.toggle("visiting", mode === "visit");
  if (mode === "visit") {
    try {
      const r = await api("visitor", { action: "join", creative: S.creative || undefined }), v = r?.visitor || (r?.x != null ? r : null);
      if (v) S.visitor = { ...(S.visitor || {}), ...v }; else if (typeof r === "string") stageToast(r); else if (r?.ok === false) toast(r.text || "Couldn't join.");
    }
    catch (e) { toast(e.message); }
  } else if (was === "visit") { api("visitor", { action: "leave" }).catch(() => {}); $("#invPanel").hidden = true; }
  if (vox) { if (mode === "visit" && S.visitor) vox.update({ visitor: S.visitor }); vox.setMode(mode); }
  renderHotbar();
}
$$("#modes [data-mode]").forEach((b) => b.onclick = () => setMode(b.dataset.mode));
$("#btnCam").onclick = () => { const d = vox?.debug; if (d) d.third(!d.S.cam.third); };
$("#btnInv").onclick = () => toggleInv();
function toggleInv(open) {
  const p = $("#invPanel"); p.hidden = open == null ? !p.hidden : !open;
  if (!p.hidden) { if (document.pointerLockElement) document.exitPointerLock(); renderInvPanel(); }
}
$("#invClose").onclick = () => toggleInv(false);
addEventListener("keydown", (e) => {
  if (e.code === "Escape" && !$("#invPanel").hidden) toggleInv(false);
  if (e.code === "KeyE" && !$("#invPanel").hidden && document.activeElement?.tagName !== "INPUT") { e.preventDefault(); toggleInv(false); }
});
function renderInvPanel() {
  const inv = S.creative ? creativeSlots() : (S.visitor?.inventory || []);
  const n = S.creative ? 9 : Math.max(36, inv.length);
  setText($("#invNote"), S.creative ? "Creative: click a block below to put it in the selected slot" : S.visitor ? "the first row is your hotbar" : "join the world to carry things");
  setHTML($("#invGrid"), Array.from({ length: n }, (_, i) => slotHTML(inv[i], i, i === S.sel)).join(""));
  $("#creativeBox").hidden = !S.creative;
  if (S.creative) renderPalette();
}
function renderPalette() {
  const q = normName($("#palSearch").value || "");
  const list = Reg.list.filter((b) => b.kind !== K.AIR && b.id !== 0 && (!q || b.key.includes(q)));
  setHTML($("#palette"), list.map((b) => `<button class="pal" data-block="${b.id}" title="${esc(b.label)}"><img src="${iconURL(b.id, 36)}" alt="${esc(b.label)}"></button>`).join(""));
}
$("#palSearch").oninput = renderPalette;
$("#invGrid").addEventListener("click", (e) => { const s = e.target.closest("[data-slot]"); if (s && +s.dataset.slot < 9) selectSlot(+s.dataset.slot); });
$("#palette").addEventListener("click", (e) => {
  const b = e.target.closest("[data-block]"); if (!b) return;
  creativeSlots(); S.creativeBar[S.sel] = +b.dataset.block; store.set("creativeBar", S.creativeBar);
  renderHotbar(); renderInvPanel();
});

// ------------------------------------------------------------------ minimap
function drawTiles(g, W, H, cx, cz, s) {
  g.imageSmoothingEnabled = false;
  const tiles = vox?.tiles; if (!tiles) return 0;
  let n = 0;
  const x0 = cx - W / 2 / s, z0 = cz - H / 2 / s, x1 = cx + W / 2 / s, z1 = cz + H / 2 / s;
  for (const t of tiles.values()) {
    const bx = t.cx * 16, bz = t.cz * 16;
    if (bx + 16 < x0 || bx > x1 || bz + 16 < z0 || bz > z1) continue;
    g.drawImage(t.canvas, Math.floor((bx - cx) * s + W / 2), Math.floor((bz - cz) * s + H / 2), Math.ceil(16 * s), Math.ceil(16 * s)); n++;
  }
  return n;
}
function marker(g, x, y, yaw, col, r, dpr) {
  g.save(); g.translate(x, y);
  if (yaw != null) { g.rotate(Math.atan2(Math.cos(yaw), -Math.sin(yaw)) - Math.PI / 2); g.fillStyle = col; g.beginPath(); g.moveTo(0, -r * 2.1); g.lineTo(r * 0.9, -r * 0.6); g.lineTo(-r * 0.9, -r * 0.6); g.closePath(); g.fill(); g.rotate(0); }
  g.restore();
  g.beginPath(); g.arc(x, y, r, 0, 7); g.fillStyle = col; g.fill(); g.lineWidth = 2 * dpr; g.strokeStyle = "#fff"; g.stroke();
}
function placesList() { const p = S.mind.places || S.world.places || {}; return Array.isArray(p) ? p.map((x) => ({ name: x.name, x: x.x ?? x[0], y: x.y ?? x[1], z: x.z ?? x[2] })) : Object.entries(p).map(([name, v]) => ({ name, x: Array.isArray(v) ? v[0] : v.x, y: Array.isArray(v) ? v[1] : v.y, z: Array.isArray(v) ? v[2] : v.z })); }
function drawMarkers(g, W, H, cx, cz, s, dpr, labels) {
  const P = (x, z) => [(x - cx) * s + W / 2, (z - cz) * s + H / 2];
  for (const p of placesList()) {
    if (p.x == null) continue; const [x, y] = P(p.x + 0.5, p.z + 0.5); if (x < -40 || y < -40 || x > W + 40 || y > H + 40) continue;
    g.fillStyle = "#ffd166"; g.strokeStyle = "#5a3d00"; g.lineWidth = 1.5 * dpr; g.beginPath(); g.arc(x, y - 6 * dpr, 4.5 * dpr, 0, 7); g.fill(); g.stroke();
    g.beginPath(); g.moveTo(x - 3 * dpr, y - 4 * dpr); g.lineTo(x, y); g.lineTo(x + 3 * dpr, y - 4 * dpr); g.fill();
    if (labels) { g.font = `600 ${11 * dpr}px system-ui`; g.textAlign = "center"; g.lineWidth = 3 * dpr; g.strokeStyle = "rgba(0,0,0,.7)"; g.strokeText(p.name, x, y - 14 * dpr); g.fillStyle = "#fff"; g.fillText(p.name, x, y - 14 * dpr); }
  }
  const ci = vox?.camInfo();
  if (ci?.me) { const [x, y] = P(ci.me.x, ci.me.z); marker(g, x, y, ci.me.yaw, "#f08a3c", 4.5 * dpr, dpr); }
  const a = vox?.agentPos() || (S.agent.x != null ? S.agent : null);
  if (a) { const [x, y] = P(a.x, a.z); marker(g, x, y, S.agent.yaw ?? null, "#1fb3a4", 5 * dpr, dpr); if (labels) { g.font = `700 ${12 * dpr}px system-ui`; g.textAlign = "left"; g.lineWidth = 3 * dpr; g.strokeStyle = "rgba(0,0,0,.7)"; g.strokeText(NAME(), x + 9 * dpr, y + 4 * dpr); g.fillStyle = "#c8fff8"; g.fillText(NAME(), x + 9 * dpr, y + 4 * dpr); } }
}
let miniAt = 0;
function drawMini() {
  const now = performance.now(); if (now - miniAt < 200) return; miniAt = now;
  const cv = $("#mini"), dpr = Math.min(2, devicePixelRatio || 1), W = Math.round(cv.clientWidth * dpr), H = Math.round(cv.clientHeight * dpr); if (!W) return;
  if (cv.width !== W || cv.height !== H) { cv.width = W; cv.height = H; }
  const g = cv.getContext("2d"); g.fillStyle = "#0e1420"; g.fillRect(0, 0, W, H);
  const ci = vox?.camInfo(), a = vox?.agentPos() || (S.agent.x != null ? S.agent : null);
  const c = S.mode === "visit" && ci?.me ? ci.me : a || ci || { x: 0, z: 0 };
  const s = S.mini.s * dpr;
  drawTiles(g, W, H, c.x, c.z, s);
  drawMarkers(g, W, H, c.x, c.z, s, dpr, false);
  g.fillStyle = "rgba(255,255,255,.85)"; g.font = `700 ${10 * dpr}px system-ui`; g.textAlign = "center"; g.fillText("N", W / 2, 12 * dpr);
  setText($("#mmCoords"), `${Math.round(c.x)}, ${Math.round(c.z)}`);
}
$$("[data-mm]").forEach((b) => b.onclick = () => { const k = b.dataset.mm; if (k === "map") showView("map"); else { S.mini.s = clamp(S.mini.s * (k === "in" ? 1.5 : 1 / 1.5), 0.5, 8); miniAt = 0; drawMini(); } });
setInterval(() => { if (S.view === "home" && !document.hidden) drawMini(); }, 250);

// ================================================================== Mind tab
function percentile(arr, p) { if (!arr.length) return null; const a = [...arr].sort((x, y) => x - y); return a[Math.min(a.length - 1, Math.floor(a.length * p))]; }
function renderMind() {
  const m = S.mind, st = m.stats || {}, ds = decList(), lat = ds.map((d) => d.latency).filter((x) => x != null);
  const obs = ds.map((d) => d.obs_chars).filter(Boolean), L = m.learning || {}, rate = L.rate;
  const rated = ds.filter((d) => d.rating).length;
  setHTML($("#mindTiles"), [
    ["Decisions", big(st.decisions ?? ds.length), st.errors ? `${st.errors} errors` : "since it started"],
    ["Median latency", msTxt(percentile(lat, 0.5)), `p95 ${msTxt(percentile(lat, 0.95))}`],
    ["To first action", msTxt(st.action_ms ?? percentile(ds.map((d) => d.ms?.action_ms).filter((x) => x != null), 0.5)), "streamed: it starts acting early"],
    ["It sees", obs.length ? `${big(obs.reduce((a, b) => a + b, 0) / obs.length)} ch` : "–", "average observation"],
    ["Judged good", rate != null ? pct(rate) : "–", `${rated} rated by you · ${L.judged_since ?? 0} by itself`],
  ].map(([k, v, n]) => `<div class="tile"><span>${k}</span><b>${v}</b><small>${esc(n)}</small></div>`).join(""));
  setText($("#btnPause"), m.paused ? "▶ Resume" : "⏸ Pause"); $("#btnPause").dataset.agent = m.paused ? "resume" : "pause";
  drawLatency(lat.slice(-120));
  renderPractice($("#practiceMini"), false);
  renderDecLog();
  const notes = m.notes || [];
  setHTML($("#notes"), notes.length ? notes.map((n) => `<li>${esc(typeof n === "string" ? n : n.text)}</li>`).join("") : '<li class="muted empty">No notes yet. It writes its own when something is worth remembering.</li>');
  const lessons = m.lessons || [];
  setHTML($("#lessons"), lessons.length ? lessons.slice().reverse().map((l) => `<div class="lesson ${l.by === "visitor" ? "you" : ""}"><span>${l.by === "visitor" ? "🧍 from you" : "🪞 its own"}${l.t ? ` · ${ago(l.t)}` : ""}</span>${esc(l.text)}</div>`).join("") : '<div class="muted">Nothing learned by looking back yet.</div>');
  const pl = placesList();
  setHTML($("#places"), pl.length ? pl.map((p) => `<button class="place" data-goto="${p.x},${p.z}"><span>📍</span><b>${esc(p.name)}</b><small>${Math.round(p.x)}, ${Math.round(p.y)}, ${Math.round(p.z)}</small></button>`).join("") : '<div class="muted">It hasn\'t named a place yet.</div>');
  setHTML($("#goals"), S.goals.length ? S.goals.slice().reverse().slice(0, 12).map((g, i) => `<div class="goal${i === 0 ? " now" : ""}"><b>${esc(g.goal)}</b><small>${i === 0 ? "now" : clock(g.t)}</small></div>`).join("") : `<div class="muted">${esc(m.goal || "No goal yet.")}</div>`);
}
$$("[data-agent]").forEach((b) => b.onclick = async () => {
  const action = b.dataset.agent;
  try { const r = await api("agent", { action }); toast(typeof r === "string" && r ? r : { pause: "Paused.", resume: "Resumed.", stop: "Stopped its skill.", reflect: "It is looking back…" }[action] || "Done."); } catch (e) { toast(e.message); }
});
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-goto]"); if (!b) return;
  const [x, z] = b.dataset.goto.split(",").map(Number); S.mapView.x = x; S.mapView.z = z; S.mapView.init = true; showView("map");
});
function decFilterOK(d) {
  const f = S.decFilter || "";
  return !f || (f === "said" && d.say) || (f === "failed" && d.outcome?.ok === false) || (f === "rated" && (d.rating || d.correction));
}
$$("#decFilter button").forEach((b) => b.onclick = () => { $$("#decFilter button").forEach((x) => x.classList.toggle("on", x === b)); S.decFilter = b.dataset.f; $("#decLog").innerHTML = ""; renderDecLog(); });
function renderDecLog() {
  const box = $("#decLog"), list = decList().filter(decFilterOK).reverse().slice(0, 150);
  if (!list.length) { setHTML(box, '<div class="muted empty">No decisions yet.</div>'); return; }
  if (box.querySelector(".empty")) box.innerHTML = "";
  box._h = null;
  const have = new Map([...box.children].map((el) => [el.dataset.id, el]));
  let prev = null;
  for (const d of list) {
    const id = String(d.id); let el = have.get(id); const sig = decSig(d);
    if (!el) { el = document.createElement("article"); el.className = "dec"; el.dataset.id = id; }
    if (el._sig !== sig && !el.contains(document.activeElement) && !el.querySelector("details[open]")) { el._sig = sig; el.innerHTML = decHTML(d); el.classList.toggle("failed", d.outcome?.ok === false); }
    if (prev ? prev.nextSibling !== el : box.firstChild !== el) prev ? prev.after(el) : box.prepend(el);
    prev = el; have.delete(id);
  }
  for (const el of have.values()) el.remove();
}
function drawLatency(vals) {
  const cv = $("#latChart"), dpr = devicePixelRatio || 1, W = Math.round(cv.clientWidth * dpr), H = Math.round(cv.clientHeight * dpr); if (!W || !H) return;
  if (cv.width !== W || cv.height !== H) { cv.width = W; cv.height = H; }
  const g = cv.getContext("2d"); g.clearRect(0, 0, W, H);
  g.font = `${11 * dpr}px system-ui`; g.fillStyle = css("--muted");
  if (vals.length < 2) { g.fillText("Waiting for its first decisions…", 8 * dpr, H / 2); return; }
  const mx = Math.max(300, percentile(vals, 0.97) * 1.15), L = 44 * dpr, R = 8 * dpr, T = 8 * dpr, B = 18 * dpr;
  const X = (i) => L + (i / Math.max(1, vals.length - 1)) * (W - L - R), Y = (v) => H - B - (Math.min(v, mx) / mx) * (H - T - B);
  g.strokeStyle = css("--line"); g.lineWidth = 1;
  const step = mx > 2000 ? 1000 : mx > 800 ? 250 : 100;
  for (let v = 0; v <= mx; v += step) { g.beginPath(); g.moveTo(L, Y(v)); g.lineTo(W - R, Y(v)); g.stroke(); g.fillText(v >= 1000 ? `${v / 1000}s` : `${v}`, 4 * dpr, Y(v) + 4 * dpr); }
  g.setLineDash([5 * dpr, 4 * dpr]); g.strokeStyle = css("--good"); g.beginPath(); g.moveTo(L, Y(250)); g.lineTo(W - R, Y(250)); g.stroke(); g.setLineDash([]);
  const med = percentile(vals, 0.5); g.strokeStyle = css("--warm"); g.lineWidth = 1.5 * dpr; g.beginPath(); g.moveTo(L, Y(med)); g.lineTo(W - R, Y(med)); g.stroke();
  g.strokeStyle = css("--accent"); g.lineWidth = 1.6 * dpr; g.beginPath(); vals.forEach((v, i) => i ? g.lineTo(X(i), Y(v)) : g.moveTo(X(i), Y(v))); g.stroke();
  g.fillStyle = css("--accent"); vals.forEach((v, i) => { g.beginPath(); g.arc(X(i), Y(v), (v > mx ? 3 : 2) * dpr, 0, 7); g.fill(); });
  g.fillStyle = css("--muted"); g.textAlign = "right"; g.fillText(`median ${msTxt(med)}`, W - R, T + 10 * dpr); g.textAlign = "left";
}
addEventListener("resize", () => { if (S.view === "mind") renderMind(); if (S.view === "map") drawBigMap(); });

// ------------------------------------------------------------------ practice (Mind tab card and Settings)
const PR_STATE = { off: "Not started", needs_tools: "Needs its training tools", installing: "Installing the training tools…", ready: "Ready", preparing: "Preparing examples…", training: "Practising…", exporting: "Saving the new adapter…", error: "Something went wrong", done: "Done" };
function renderPractice(el, full) {
  const pr = S.model.practice || {}, L = S.mind.learning || {}, cnt = L.counts || {};
  const state = pr.state || "off", busy = ["preparing", "training", "exporting", "installing"].includes(state);
  const ex = pr.examples ?? cnt.examples, good = pr.good ?? cnt.good ?? L.good, bad = pr.bad ?? cnt.bad ?? L.bad;
  const ads = pr.adapters || [], active = pr.active ?? S.model.adapter ?? ads.find((a) => a.active)?.name ?? null;
  const prog = clamp(+pr.progress || (pr.steps ? (pr.step || 0) / pr.steps : 0), 0, 1);
  const html = `<div class="row"><h2 style="margin:0">🎓 Practice</h2><span class="badge st-${esc(state)}">${esc(PR_STATE[state] || state)}</span></div>
    <p class="muted pr-line">Teaches its model from its own best decisions and your feedback; runs on the GPU while it rests.</p>
    <div class="pr-counts"><div><b>${ex ?? "–"}</b><span>examples</span></div><div><b>${good ?? "–"}</b><span>👍 good</span></div><div><b>${bad ?? "–"}</b><span>👎 poor</span></div>${full && L.practices != null ? `<div><b>${L.practices}</b><span>practices</span></div>` : ""}</div>
    ${L.need && !busy ? `<div class="pr-need">⏳ ${esc(L.need)}</div>` : ""}
    ${pr.detail || pr.error ? `<div class="pr-detail ${state === "error" ? "bad" : ""}">${esc(pr.error || pr.detail)}</div>` : ""}
    ${busy ? `<div class="pr-prog"><div class="meter big"><i style="width:${Math.round(prog * 100)}%"></i></div>
      <div class="muted">${pr.steps ? `step ${pr.step || 0} of ${pr.steps}` : pct(prog)}${pr.loss != null ? ` · loss ${(+pr.loss).toFixed(3)}` : ""}${pr.eta ? ` · about ${dur(pr.eta)} left` : ""}</div></div>` : ""}
    <div class="row pr-actions">
      ${state === "needs_tools" ? `<button class="primary" data-practice="install">⬇️ Install training tools</button>` : ""}
      ${busy && state !== "installing" ? `<button data-practice="stop">⏹ Stop</button>` : ""}
      ${!busy && state !== "needs_tools" ? `<button class="primary" data-practice="start">▶ Start practice</button>` : ""}
      <label class="switch"><input type="checkbox" data-practice-auto ${pr.auto ?? S.settings["mind.practice_auto"] ? "checked" : ""}><span></span><span class="sw-text">Practise automatically each night</span></label>
    </div>
    ${full || ads.length ? `<h3>Adapters</h3><div class="adapters">
      <div class="adapter${!active ? " on" : ""}"><div><b>Base model</b><small>as downloaded, no practice</small></div>${!active ? '<span class="badge on">in use</span>' : '<button data-practice="use" data-name="">Use the base model</button>'}</div>
      ${ads.slice().reverse().slice(0, full ? 20 : 3).map((a) => `<div class="adapter${a.name === active ? " on" : ""}"><div><b>${esc(a.name)}</b><small>${a.created ? ago(a.created) + " · " : ""}${a.examples ?? "?"} examples${a.loss != null ? ` · loss ${(+a.loss).toFixed(3)}` : ""}${a.liked ? ` · ${a.liked} 👍` : ""}${a.corrected ? ` · ${a.corrected} ✏️` : ""}</small></div>${a.name === active ? '<span class="badge on">in use</span>' : `<button data-practice="use" data-name="${esc(a.name)}">Use</button>`}</div>`).join("")}</div>` : ""}
    ${full && (L.history || []).length ? `<h3>What practice changed</h3><div class="pr-hist">${L.history.slice().reverse().slice(0, 6).map((h) => `<div><b>${esc(h.adapter)}</b> <span class="muted">${h.t ? ago(h.t) : ""} · ${h.examples ?? "?"} examples</span>${h.before != null ? `<span>judged good ${pct(h.before)} → ${h.after != null ? pct(h.after) : "measuring…"}</span>` : ""}${h.rolled_back ? '<span class="bad">rolled back</span>' : ""}</div>`).join("")}</div>` : ""}
    ${full ? `<details class="pr-adv"><summary>Practice settings</summary><div class="sliders">
      <label>Examples needed before practising <input type="range" min="10" max="400" step="10" data-set="mind.practice_min"><output></output></label>
      <label>Steps per practice <input type="range" min="50" max="2000" step="50" data-set="mind.practice_steps"><output></output></label>
      <label>Adapter rank <select data-set="mind.practice_rank"><option value="8">8</option><option value="16">16</option><option value="32">32</option><option value="64">64</option></select><output></output></label>
      </div></details>` : ""}`;
  if (el._h === html || el.contains(document.activeElement) && document.activeElement.tagName !== "BUTTON") return;
  const open = el.querySelector("details[open]");
  setHTML(el, html);
  if (open) el.querySelector("details")?.setAttribute("open", "");
  bindSettings(el); syncSettings();
}
document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-practice]"); if (!b) return;
  const action = b.dataset.practice, body = { action };
  if (action === "use") body.name = b.dataset.name || null;
  b.disabled = true;
  try { const r = await api("practice", body); toast(typeof r === "string" && r ? r : action === "use" ? (body.name ? `Using ${body.name}.` : "Using the base model.") : action === "start" ? "Practice will start." : action === "install" ? "Installing the training tools…" : "Stopping."); }
  catch (er) { toast(er.message); }
  b.disabled = false;
});
document.addEventListener("change", async (e) => {
  const c = e.target.closest("[data-practice-auto]"); if (!c) return;
  try { await api("practice", { action: "auto", value: c.checked }); } catch (er) { toast(er.message); c.checked = !c.checked; }
});

// ================================================================== Map tab
function drawBigMap() {
  if (S.view !== "map") return;
  const cv = $("#bigMap"), dpr = Math.min(2, devicePixelRatio || 1), W = Math.round(cv.clientWidth * dpr), H = Math.round(cv.clientHeight * dpr); if (!W || !H) return;
  if (cv.width !== W || cv.height !== H) { cv.width = W; cv.height = H; }
  const mv = S.mapView;
  if (!mv.init) { const a = vox?.agentPos() || (S.agent.x != null ? S.agent : null); if (a) { mv.x = a.x; mv.z = a.z; mv.init = true; } }
  const g = cv.getContext("2d"); g.fillStyle = css("--map-fog") || "#1a2030"; g.fillRect(0, 0, W, H);
  const s = mv.s * dpr;
  // a faint grid of chunks for orientation
  const n = drawTiles(g, W, H, mv.x, mv.z, s);
  g.strokeStyle = "rgba(255,255,255,.06)"; g.lineWidth = 1;
  if (s >= 2) { const x0 = Math.floor((mv.x - W / 2 / s) / 16) * 16; for (let x = x0; x < mv.x + W / 2 / s; x += 16) { const px = (x - mv.x) * s + W / 2; g.beginPath(); g.moveTo(px, 0); g.lineTo(px, H); g.stroke(); } const z0 = Math.floor((mv.z - H / 2 / s) / 16) * 16; for (let z = z0; z < mv.z + H / 2 / s; z += 16) { const py = (z - mv.z) * s + H / 2; g.beginPath(); g.moveTo(0, py); g.lineTo(W, py); g.stroke(); } }
  drawMarkers(g, W, H, mv.x, mv.z, s, dpr, true);
  if (!vox?.tiles?.size) { g.fillStyle = "#cfd6e4"; g.font = `${13 * dpr}px system-ui`; g.textAlign = "center"; g.fillText("Nothing explored yet: the map fills in as the world loads on Home.", W / 2, H / 2); g.textAlign = "left"; }
  S.mapTiles = vox?.tiles?.size || 0;
}
function renderMapSide() {
  const tiles = vox?.tiles; let minX = Infinity, maxX = -Infinity, minZ = Infinity, maxZ = -Infinity;
  if (tiles) for (const t of tiles.values()) { minX = Math.min(minX, t.cx); maxX = Math.max(maxX, t.cx); minZ = Math.min(minZ, t.cz); maxZ = Math.max(maxZ, t.cz); }
  const a = vox?.agentPos() || S.agent;
  setHTML($("#mapStats"), [
    ["Chunks seen", tiles ? big(tiles.size) : "–", tiles?.size ? `${(maxX - minX + 1) * 16} × ${(maxZ - minZ + 1) * 16} blocks` : "load the world on Home"],
    [NAME(), a?.x != null ? `${Math.round(a.x)}, ${Math.round(a.z)}` : "–", a?.y != null ? `height ${Math.round(a.y)}` : ""],
    ["Places named", String(placesList().length), ""],
    ["Zoom", `${S.mapView.s.toFixed(1)} px/block`, ""],
  ].map(([k, v, n]) => `<div class="tile"><span>${esc(k)}</span><b>${esc(v)}</b><small>${esc(n)}</small></div>`).join(""));
  const pl = placesList();
  setHTML($("#mapPlaces"), pl.length ? pl.map((p) => `<button class="place" data-goto="${p.x},${p.z}"><span>📍</span><b>${esc(p.name)}</b><small>${Math.round(p.x)}, ${Math.round(p.y)}, ${Math.round(p.z)}</small></button>`).join("") : '<div class="muted">No named places yet.</div>');
}
{
  const cv = $("#bigMap"); let drag = null;
  cv.addEventListener("pointerdown", (e) => { drag = { x: e.clientX, y: e.clientY }; cv.setPointerCapture(e.pointerId); });
  cv.addEventListener("pointermove", (e) => {
    const r = cv.getBoundingClientRect(), mv = S.mapView;
    if (drag) { mv.x -= (e.clientX - drag.x) / mv.s; mv.z -= (e.clientY - drag.y) / mv.s; drag = { x: e.clientX, y: e.clientY }; mv.init = true; drawBigMap(); }
    const wx = mv.x + (e.clientX - r.left - r.width / 2) / mv.s, wz = mv.z + (e.clientY - r.top - r.height / 2) / mv.s, tip = $("#mapTip");
    tip.hidden = false; tip.style.transform = `translate(${e.clientX - r.left + 12}px, ${e.clientY - r.top + 12}px)`; tip.textContent = `${Math.floor(wx)}, ${Math.floor(wz)}`;
  });
  cv.addEventListener("pointerup", () => { drag = null; });
  cv.addEventListener("pointerleave", () => { $("#mapTip").hidden = true; });
  cv.addEventListener("wheel", (e) => { e.preventDefault(); S.mapView.s = clamp(S.mapView.s * (e.deltaY > 0 ? 0.85 : 1.18), 0.5, 16); drawBigMap(); renderMapSide(); }, { passive: false });
  $$("[data-map]").forEach((b) => b.onclick = () => {
    const k = b.dataset.map, mv = S.mapView;
    if (k === "in" || k === "out") mv.s = clamp(mv.s * (k === "in" ? 1.4 : 1 / 1.4), 0.5, 16);
    else { const p = k === "agent" ? vox?.agentPos() || S.agent : vox?.camInfo()?.me || S.visitor; if (p?.x != null) { mv.x = p.x; mv.z = p.z; } else toast(k === "you" ? "You aren't in the world: Visit from Home." : "Not seen yet."); }
    drawBigMap(); renderMapSide();
  });
  setInterval(() => { if (S.view === "map" && !document.hidden) drawBigMap(); }, 1000);
}

// ================================================================== settings
function renderSettings() {
  const m = S.model, st = $("#modelStatus"), busy = m.status === "downloading" || m.status === "starting";
  st.className = "status " + (m.status === "ready" ? "on" : m.status === "error" ? "bad" : "off");
  setHTML(st, `${m.status === "ready" ? `<b>${esc(m.label || m.model || "ready")}</b> is ready` : m.status === "error" ? esc(m.error || "error") : esc(m.status ? `${m.status}${m.detail ? ": " + m.detail : ""}` : "…")}
    ${m.device ? ` <span class="badge dev ${m.device === "cpu" ? "cpu" : "gpu"}">${deviceText(m)}</span>` : ""}${m.gpu?.name ? ` <span class="muted">${esc(m.gpu.name)}${m.gpu.memory ? ` · ${(m.gpu.memory / 1024).toFixed(0)} GB` : ""}</span>` : ""}${m.threads ? ` <span class="muted">· ${m.threads} threads</span>` : ""}`);
  $("#modelMeter").hidden = !busy; $("#modelBar").style.width = `${Math.round((m.progress || 0) * 100)}%`;
  const cat = m.catalog || [], choice = m.choice || S.settings["mind.model"];
  setHTML($("#models"), cat.length ? cat.map((c) => `<button class="model${c.name === choice ? " on" : ""}" data-model="${esc(c.name)}" aria-pressed="${c.name === choice}">
      <b>${esc(c.label || c.name)}</b>${c.family ? `<span class="fam">${esc(c.family)}</span>` : ""}<small>${c.size ? (c.size / 1e9).toFixed(1) + " GB" : ""}${c.downloaded ? " · downloaded" : " · downloads when chosen"}</small>
      ${c.name === choice && busy ? `<div class="meter"><i style="width:${Math.round((m.progress || 0) * 100)}%"></i></div>` : ""}</button>`).join("") : '<div class="muted">No models listed.</div>');
  renderPractice($("#practiceCard"), true);
}
document.addEventListener("click", async (ev) => {
  const b = ev.target.closest("[data-model]"); if (!b) return;
  try { await api("set", { key: "mind.model", value: b.dataset.model }); S.settings["mind.model"] = b.dataset.model; S.model.choice = b.dataset.model; renderSettings(); toast("It will think with that model."); }
  catch (e) { toast(e.message); }
});
function syncSettings() {
  const s = S.settings;
  for (const el of $$("[data-set]")) {
    const k = el.dataset.set; if (!(k in s) || el === document.activeElement || el._busy) continue;
    const v = el.dataset.invert ? !s[k] : s[k];
    if (el.type === "checkbox") el.checked = !!v; else el.value = v;
    const out = el.parentElement.querySelector("output"); if (out) out.textContent = el.type === "range" ? el.value : "";
  }
  if (vox && s["world.view_chunks"] && !store.get("renderDist", null)) vox.setRenderDistance(+s["world.view_chunks"]);
}
function bindSettings(root = document) {
  for (const el of $$("[data-set]", root)) {
    if (el._bound) continue; el._bound = true;
    el.addEventListener("input", () => { const o = el.parentElement.querySelector("output"); if (o && el.type === "range") o.textContent = el.value; el._busy = 1; });
    el.addEventListener("change", async () => {
      const key = el.dataset.set;
      let v = el.type === "checkbox" ? el.checked : el.type === "range" ? parseFloat(el.value) : /^\d+$/.test(el.value) ? +el.value : el.value;
      if (el.dataset.invert) v = !v;
      try { await api("set", { key, value: v }); S.settings[key] = v; if (key === "world.view_chunks") { vox?.setRenderDistance(v); store.set("renderDist", null); } syncSettings(); }
      catch (e) { toast(e.message); }
      setTimeout(() => delete el._busy, 500);
    });
  }
}
bindSettings();
$("#creative").checked = S.creative;
$("#creative").onchange = (e) => { S.creative = e.target.checked; store.set("creative", S.creative); renderHotbar(); if (!$("#invPanel").hidden) renderInvPanel(); toast(S.creative ? "Creative: any block, instant digging." : "Creative off: you carry what you gather."); };
{
  const ms = $("#mouseSens"); ms.value = store.get("mouseSens", 1); ms.nextElementSibling.textContent = ms.value;
  ms.oninput = () => { ms.nextElementSibling.textContent = ms.value; store.set("mouseSens", +ms.value); vox?.setSensitivity(+ms.value); };
}
$("#themeSel").value = store.get("theme", "");
$("#themeSel").onchange = (e) => { const v = e.target.value; store.set("theme", v); if (v) document.documentElement.dataset.theme = v; else delete document.documentElement.dataset.theme; renderAll(); };

// ================================================================== health
let healthAt = 0;
async function pollHealth(force) {
  if (!force && performance.now() - healthAt < 4000) return; healthAt = performance.now();
  try { renderHealth(await (await fetch("/api/health")).json()); } catch { /* back soon */ }
}
function perfTable(p, keep = 8) {
  if (!p || !p.timings) return '<div class="muted">No measurements yet.</div>';
  const rows = Object.entries(p.timings).sort((a, b) => b[1].share - a[1].share).slice(0, keep);
  return `<div class="muted" style="margin-bottom:6px">CPU ${p.cpu_percent ?? "–"}% of a core${p.gauges?.memory_mb ? ` · ${Math.round(p.gauges.memory_mb)} MB` : ""}</div>`
    + `<div class="scroll-x"><table class="perf"><tr><th>Activity</th><th>share</th><th>avg ms</th><th>max ms</th><th>/s</th></tr>`
    + rows.map(([k, v]) => `<tr><td>${esc(k)}</td><td><span class="share" style="width:${Math.round(Math.min(1, v.share) * 40)}px"></span>${pct(v.share)}</td><td>${v.avg_ms}</td><td>${v.max_ms}</td><td>${v.per_s}</td></tr>`).join("")
    + `</table></div>` + (p.gauges ? `<div class="muted" style="margin-top:6px">${Object.entries(p.gauges).filter(([k]) => k !== "memory_mb").map(([k, v]) => `${esc(k.replace(/_/g, " "))}: <b>${esc(v)}</b>`).join(" · ")}</div>` : "");
}
const dl = (rows) => rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join("");
const PROC_ICON = { hub: "🧭", world: "🌍", model: "🧩", mind: "🧠", practice: "🎓" };
function renderHealth(h) {
  setText($("#logPath"), `minds/${NAME()}/logs/`);
  const f = h.findings || [];
  setHTML($("#findings"), f.length ? f.map((x) => `<div class="finding ${esc(x.level)}"><b>${esc(x.where)}</b> · ${esc(x.text)}</div>`).join("") : '<div class="finding ok">Nothing looks wrong right now.</div>');
  const names = [...new Set([...Object.keys(h.processes || {}), ...Object.keys(h.perf || {})])];
  setHTML($("#hProcs"), names.map((n) => { const p = h.processes?.[n];
    return `<div class="card"><h2>${PROC_ICON[n] || "⚙️"} ${esc(label(n))}</h2>${p ? `<div class="muted" style="margin-bottom:4px">${p.alive ? "running" : "stopped"}${p.pid ? ` · pid ${p.pid}` : ""}${p.restarts ? ` · <b class="bad">restarted ${p.restarts}×</b>` : ""}</div>` : n === "hub" && h.uptime_s ? `<div class="muted">up ${dur(h.uptime_s)}</div>` : ""}${perfTable(h.perf?.[n])}</div>`; }).join(""));
  const g = (h.gpu || [])[0];
  setHTML($("#hGpu"), g ? dl([["Card", esc(g.name)], ["Busy", `${g.util_percent}%`], ["Memory", `${Math.round(g.mem_used_mb)} / ${Math.round(g.mem_total_mb)} MB`], ["Temperature", `${g.temp_c}°C`], ["Power", `${g.power_w} W`], ["Driver", esc(g.driver)]]) : '<dd class="muted">No GPU readings.</dd>');
  const v = vox ? vox.stats() : null, b = S.clientPerf || {};
  setHTML($("#hBrowser"), dl([
    ["Frames per second", v ? `${v.fps} <span class="muted">(capped at 60, ${v.ms} ms a frame, max ${v.frameMax})</span>` : b.fps != null ? String(b.fps) : "–"],
    ["3D world", v ? `${v.chunks} chunks drawn, ${big(v.triangles)} triangles, ${v.calls} draw calls` : "not running"],
    ["Chunk meshing", v?.meshCount ? `${v.meshAvg} ms average, ${v.meshMax} ms at most (in a worker)` : "–"],
    ["Block edit to screen", v?.editLatLast != null ? `${v.editLatLast} ms (max ${v.editLatMax})` : "no edits yet"],
    ["Frozen moments", b.longtasks != null ? `${b.longtasks} (${b.longtask_ms} ms, longest ${b.longtask_max_ms} ms)` : "measuring…"],
    ["Updates", b.msgs_per_s != null ? `${b.msgs_per_s}/s, ${b.kb_per_s} KB/s, ${b.msg_avg_ms} ms each` : "measuring…"],
    ["Screen", `${innerWidth}×${innerHeight}, scale ${devicePixelRatio}`], ["Script errors", `${b.js_errors ?? 0}${b.last_error ? ` · ${esc(b.last_error)}` : ""}`]]));
  const box = $("#hLog"), stick = box.scrollTop + box.clientHeight >= box.scrollHeight - 20;
  setText(box, (h.log || []).join("\n") || "No warnings or errors so far."); if (stick) box.scrollTop = box.scrollHeight;
}

// ================================================================== Thoughts and Conversations: the archives
const Journal = (() => {
  const K2 = { thoughts: { list: "#thList", more: "#thMore", end: "#thEnd", search: "#thSearch" }, conversations: { list: "#tkList", more: "#tkMore", end: "#tkEnd", search: "#tkSearch" } };
  const st = { thoughts: { loaded: false, oldest: null, busy: false, q: "", who: "" }, conversations: { loaded: false, oldest: null, busy: false, q: "", who: "" } };
  const dayKey = (e) => e.day != null ? `Day ${e.day}` : new Date((e.t || 0) * 1000).toLocaleDateString();
  function place(box, el, e, atTop) {
    el.dataset.day = dayKey(e);
    const mk = () => { const h = document.createElement("div"); h.className = "arch-day"; h.dataset.day = dayKey(e); h.textContent = dayKey(e); return h; };
    if (atTop) { const top = box.firstElementChild; if (top?.classList.contains("arch-day") && top.dataset.day === dayKey(e)) top.after(el); else { const h = mk(); box.prepend(h); h.after(el); } }
    else { const last = box.lastElementChild; if (!last || last.dataset.day !== dayKey(e)) box.append(mk()); box.append(el); }
  }
  function thoughtEl(e) {
    const d = document.createElement("article"), ms = typeof e.ms === "object" && e.ms ? e.ms.total_ms ?? e.ms.action_ms : e.ms;
    d.className = `arch-item thought k-${esc(e.kind || "thought")}`;
    const act = e.action ? `<div class="arch-act">${skillIcon(e.action)} ${esc(actionText(e.action))}</div>` : "";
    d.innerHTML = `${e.kind === "reflection" ? '<div class="arch-kind">🪞 Looking back</div>' : ""}<div class="arch-text">${esc(e.text || "") || '<span class="muted">(no words)</span>'}</div>${act}
      <div class="arch-meta">${e.time ? esc(typeof e.time === "number" ? "" : e.time) + " · " : ""}${clock(e.t)}${ms != null ? ` · ${msTxt(ms)}` : ""}${e.reason ? ` · because ${esc(e.reason)}` : ""}${e.adapter ? ` · 🎓 ${esc(e.adapter)}` : ""}</div>`;
    d._e = e; return d;
  }
  function lineEl(who, text) {
    const me = who === "you", d = document.createElement("div");
    d.className = `bub ${me ? "you" : who === NAME() || who === "it" ? "zen" : "other"}`;
    d.innerHTML = `<b>${esc(me ? "You" : who)}</b><div>${esc(text || "…")}</div>`; return d;
  }
  function talkEl(e) {
    const d = document.createElement("article"); d.className = `arch-item talk with-${esc(e.with || "you")}`;
    const what = e.kind === "said" ? (e.with === "you" ? `${esc(NAME())} to you` : `${esc(NAME())} says aloud`) : e.with === "you" ? "With you" : `With ${esc(e.with)}`;
    d.innerHTML = `<header><b>${what}</b><span class="arch-meta">${clock(e.t)}</span></header><div class="dialogue"></div>`;
    const box = d.querySelector(".dialogue"); for (const [who, text] of e.lines || []) box.append(lineEl(who, text));
    d._e = e; return d;
  }
  const make = (kind, e) => kind === "thoughts" ? thoughtEl(e) : talkEl(e);
  const matches = (kind, e) => {
    const s = st[kind];
    if (s.who && (kind === "thoughts" ? e.kind || "thought" : e.with) !== s.who) return false;
    if (!s.q) return true;
    const text = kind === "thoughts" ? `${e.text || ""} ${actionText(e.action)}` : (e.lines || []).map((l) => l[1] || "").join(" ");
    return text.toLowerCase().includes(s.q.toLowerCase());
  };
  function mergeChat(box, e, atTop) {     // lines with you a few minutes apart read as one conversation
    if (e.with !== "you") return false;
    const items = [...box.querySelectorAll(".arch-item.talk")], near = atTop ? items[0] : items.at(-1);
    if (!near || near._e.with !== "you") return false;
    const gap = atTop ? e.t - near._e.t : (near._e.t0 ?? near._e.t) - e.t;
    if (gap < 0 || gap > 600 || dayKey(near._e) !== dayKey(e)) return false;
    const dlg = near.querySelector(".dialogue"), els = (e.lines || []).map(([w, t]) => lineEl(w, t));
    if (atTop) { dlg.append(...els); near._e = { ...near._e, t: e.t, lines: [...near._e.lines, ...e.lines] }; }
    else { dlg.prepend(...els); near._e = { ...near._e, t0: e.t, lines: [...e.lines, ...near._e.lines] }; }
    return true;
  }
  function add(kind, e, atTop) { const box = $(K2[kind].list); if (kind === "conversations" && mergeChat(box, e, atTop)) return; place(box, make(kind, e), e, atTop); }
  async function load(kind, reset) {
    const s = st[kind], k = K2[kind]; if (s.busy) return; s.busy = true;
    if (reset) { $(k.list).innerHTML = ""; s.oldest = null; }
    const p = new URLSearchParams({ limit: kind === "thoughts" ? 120 : 40 });
    if (s.oldest != null) p.set("before", s.oldest); if (s.q) p.set("q", s.q); if (s.who) p.set("who", s.who);
    try {
      const r = await fetch(`/api/archive/${kind}?${p}`).then((x) => x.json());
      for (const e of r.items || []) { add(kind, e, false); s.oldest = e.t; }
      $(k.more).hidden = !r.more;
      const n = $(k.list).querySelectorAll(".arch-item").length;
      setText($(k.end), r.more ? "" : n ? `That's all of them${s.q ? ` with “${s.q}”` : ""}.` : s.q ? `None with “${s.q}”.` : kind === "thoughts" ? "No thoughts yet." : "No conversations yet.");
      s.loaded = true;
    } catch (err) { setText($(k.end), `Couldn't load: ${err.message}`); }
    s.busy = false;
  }
  function open(kind) { if (!st[kind].loaded) load(kind, true); }
  function live(kind, ev) {
    if (!st[kind].loaded) return;
    const e = { day: S.world.day, ...ev, t: ev.t || Date.now() / 1000 };
    if (kind === "thoughts" && !(e.text || "").trim() && !e.action) return;
    if (!matches(kind, e)) return;
    add(kind, e, true);
    const box = $(K2[kind].list); while (box.children.length > 1500) box.lastChild.remove();
  }
  for (const kind of ["thoughts", "conversations"]) {
    const k = K2[kind]; let tmr;
    $(k.more).onclick = () => load(kind, false);
    $(k.search).oninput = (ev) => { clearTimeout(tmr); tmr = setTimeout(() => { st[kind].q = ev.target.value.trim(); load(kind, true); }, 300); };
  }
  $$("#thKind button").forEach((b) => b.onclick = () => { $$("#thKind button").forEach((x) => x.classList.toggle("on", x === b)); st.thoughts.who = b.dataset.kind; load("thoughts", true); });
  $$("#tkWho button").forEach((b) => b.onclick = () => { $$("#tkWho button").forEach((x) => x.classList.toggle("on", x === b)); st.conversations.who = b.dataset.who; load("conversations", true); });
  return { open, live, load };
})();

// ================================================================== the 3D world
async function startWorld() {
  try {
    const [blocks, items] = await Promise.all([fetch("/api/blocks").then((r) => r.json()), fetch("/api/items").then((r) => r.ok ? r.json() : null).catch(() => null)]);
    loadRegistry(blocks, items); buildTextures(); clearIcons(); $("#agentInv")._h = null;
    renderAgentInv(true); renderHotbar();
  } catch (e) { console.error(e); banner("Couldn't load the block registry: " + e.message); return; }
  try {
    const mod = await import("./vox.js");
    const rd = store.get("renderDist", null) ?? S.settings["world.view_chunks"] ?? 6;
    vox = await mod.createVox($("#world3d"), {
      renderDistance: rd,
      onCommand: voxCommand,
      onSelect: (i) => selectSlot(i),
      onStatus: (t) => stageToast(t),
      onKey: (k) => { if (k === "inventory") toggleInv(true); else if (k === "talk") $("#chatText").focus(); else if (k === "hud") $("#stage").classList.toggle("locked", vox.isLocked()); },
    });
    window.vox = vox;
    vox.setSensitivity(store.get("mouseSens", 1));
    for (const w of S.voxBacklog || []) vox.update(w);
    S.voxBacklog = null;
    vox.update({ agent: { ...S.agent, thinking: S.mind.thinking }, visitor: S.visitor, time: S.world.time, day: S.world.day, weather: S.world.weather });
    vox.pause(S.view !== "home" || document.hidden);
    renderHotbar();
  } catch (e) {
    console.warn("3D view unavailable:", e);
    $("#stage").classList.add("no3d"); setHTML($("#world3d"), `<div class="no3d-note">The 3D world needs WebGL 2, which this browser can't provide here (${esc(e.message)}). The panels still work.</div>`);
  }
}
window.addEventListener("hashchange", () => { const v = location.hash.slice(1); if (v && $(`#view-${v}`)) showView(v); });
{ const v = location.hash.slice(1); if (v && $(`#view-${v}`)) showView(v); }
connect();
startWorld();
window.__app = { S, api, showView, setMode, toggleInv };
