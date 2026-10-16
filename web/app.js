"use strict";
// The dashboard. One WebSocket brings an initial picture and then small updates 4 times a second;
// only the visible view is redrawn, and only the parts that changed.

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const big = (n) => n == null ? "–" : n >= 1e9 ? (n / 1e9).toFixed(2) + "B" : n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e3 ? (n / 1e3).toFixed(1) + "k" : String(Math.round(n));
const pct = (v) => v == null ? "–" : `${Math.round(v * 100)}%`;
const dur = (s) => { s = Math.max(0, Math.round(s || 0)); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60); return h ? `${h}h ${m}m` : m ? `${m}m` : `${s}s`; };
const ago = (t) => dur(Date.now() / 1000 - t) + " ago";
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const clock = (t) => new Date((t || Date.now() / 1000) * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
function setHTML(el, html) { if (el && el._h !== html) { el._h = html; el.innerHTML = html; } }
function setText(el, t) { if (el && el.textContent !== t) el.textContent = t; }

const MOTOR = ["forward", "back", "left", "right", "wait", "take", "drop", "eat", "drink", "use", "sleep", "look", "speak", "ask"];
const MOTOR_ICON = { forward: "⬆️", back: "⬇️", left: "↶", right: "↷", wait: "⏸", take: "✋", drop: "🫳", eat: "🍽️", drink: "💧", use: "🛠️", sleep: "😴", look: "👀", speak: "🗣️", ask: "❓" };
const NEED_LABEL = { energy: "Food", water: "Water", rest: "Rest", warmth: "Warmth", health: "Health" };

const S = { view: "world", settings: {}, academy: {}, metrics: [], concepts: {}, oracle: {}, feeds: {}, mode: "watch",
            pendingChat: null, dids: [], rewards: [], lastDid: null, lastThought: null, studioKey: "" };
const SYNTH = () => S.name || "Zen";
const W3 = { api: null, ready: false };          // the 3D world (world3d.js), when WebGL is available

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
window.toast = toast;
function banner(text) { const b = $("#banner"); b.hidden = !text; if (text) b.textContent = text; }
try { const th = localStorage.getItem("theme"); if (th) document.documentElement.dataset.theme = th; } catch { /* private window */ }

// ================================================================== the page's own health
const P = { t0: performance.now(), msgs: 0, bytes: 0, msgMs: 0, msgMax: 0, long: 0, longMs: 0, longMax: 0, errors: 0 };
try {
  new PerformanceObserver((list) => { for (const e of list.getEntries()) { P.long++; P.longMs += e.duration; P.longMax = Math.max(P.longMax, e.duration); } })
    .observe({ type: "longtask", buffered: false });
} catch { /* not every browser reports long tasks */ }
addEventListener("error", (e) => { P.errors++; report("error", `${e.message} (${e.filename}:${e.lineno})`); });
addEventListener("unhandledrejection", (e) => { P.errors++; report("error", String(e.reason)); });
function report(level, text) { P.lastError = `${level}: ${text}`.slice(0, 300); }
setInterval(() => {
  const now = performance.now(), secs = (now - P.t0) / 1000, mp = MapView.st.perf, w3 = W3.api && S.view === "world" ? W3.api.stats() : null;
  const body = {
    window_s: Math.round(secs), visible: !document.hidden, view: S.view,
    fps: w3 ? w3.fps || 0 : Math.round(mp.frames / secs), fps_cap: 60, worst_frame_gap_ms: Math.round(mp.gapMax),
    draw_ms_3d: w3 ? w3.ms : -1, draw_max_ms_3d: w3 ? w3.frameMax : -1, chunks_3d: w3 ? w3.chunks : -1, chunk_build_max_ms: w3 ? w3.jobMax : -1,
    draws_per_s: +(mp.draws / secs).toFixed(1), draw_avg_ms: +(mp.drawMs / Math.max(1, mp.draws)).toFixed(1), draw_max_ms: Math.round(mp.drawMax),
    msgs_per_s: +(P.msgs / secs).toFixed(1), kb_per_s: +(P.bytes / 1024 / secs).toFixed(1),
    msg_avg_ms: +(P.msgMs / Math.max(1, P.msgs)).toFixed(1), msg_max_ms: Math.round(P.msgMax),
    longtasks: P.long, longtask_ms: Math.round(P.longMs), longtask_max_ms: Math.round(P.longMax), js_errors: P.errors,
    last_error: P.lastError || "", dpr: devicePixelRatio, window: `${innerWidth}x${innerHeight}`, browser: navigator.userAgent.slice(0, 160),
    memory_mb: performance.memory ? Math.round(performance.memory.usedJSHeapSize / 2 ** 20) : -1,
  };
  fetch("/api/client_perf", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).catch(() => {});
  S.clientPerf = body;
  Object.assign(P, { t0: now, msgs: 0, bytes: 0, msgMs: 0, msgMax: 0, long: 0, longMs: 0, longMax: 0, errors: 0 });
  Object.assign(mp, { frames: 0, draws: 0, drawMs: 0, drawMax: 0, gapMax: 0 });
}, 15000);

// ================================================================== connection
function connect() {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  ws.onmessage = (m) => {
    const t0 = performance.now();
    let msg; try { msg = JSON.parse(m.data); } catch { return; }
    try { msg.type === "init" ? init(msg) : tick(msg); } catch (e) { console.error(e); report("error", e.message); P.errors++; }
    const dt = performance.now() - t0;
    P.msgs++; P.bytes += m.data.length; P.msgMs += dt; P.msgMax = Math.max(P.msgMax, dt);
  };
  ws.onopen = () => banner("");
  ws.onclose = () => { banner("Lost contact with the Hub. Reconnecting…"); setTimeout(connect, 1500); };
}

function init(m) {
  S.settings = m.settings || {}; S.academy = m.academy || {}; S.metrics = m.metrics || [];
  S.concepts = m.concepts || {}; S.oracle = m.oracle || {}; S.feeds = m.feeds || {};
  S.name = m.name || "Zen"; setText($("#name"), S.name); document.title = `${S.name} · Synthetic Mind`;
  $$(".synthname").forEach((el) => el.textContent = S.name);
  $("#chatText").placeholder = `Say something to ${S.name}…`; setText($("#sayTo"), `to ${S.name}`);
  S.journey = m.journey || [];
  try { if (!localStorage.getItem("welcomed4")) { $("#welcome").showModal(); localStorage.setItem("welcomed4", "1"); } } catch { /* private window */ }
  MapView.setWorld(m.world || {});
  worldIn(m.world, true);
  Community.st.feed = [];
  for (const k of ["ada_says", "answer", "happening", "chat"]) for (const e of S.feeds[k] || []) Community.st.feed.push(Object.assign({ kind: k === "ada_says" ? "ada_says" : k }, e));
  Community.st.feed.sort((a, b) => (a.t || 0) - (b.t || 0));
  for (const id of ["#chat", "#thoughts", "#diary", "#dialogue", "#qa", "#actionStream"]) $(id).innerHTML = "";
  S.dids = []; S.rewards = [];
  for (const c of S.feeds.chat || []) {
    if (c.kind === "chatline") chatLine(c);
    else { chatLine({ role: "user", text: c.user }); chatLine({ role: "mind", text: c.text, tokens: c.tokens, asleep: c.asleep }); }
  }
  for (const e of S.feeds.thought || []) addThought(e);
  for (const e of (S.feeds.did || S.feeds.deed || []).slice().sort((a, b) => (a.t || 0) - (b.t || 0))) addDeed(e);
  const talk = [...(S.feeds.answer || []), ...(S.feeds.ada_says || []).filter((e) => e.to === "sprite")].sort((a, b) => (a.t || 0) - (b.t || 0));
  for (const e of talk) addDialogue(Object.assign({ kind: e.question != null ? "answer" : "ada_says" }, e));
  for (const e of (S.feeds.answer || []).slice().sort((a, b) => (a.t || 0) - (b.t || 0))) addQA(e);
  for (const e of m.events || []) if (e.kind === "error") banner(e.text);
  syncSettings(); renderAll(); drawCharts();
}

function worldIn(w, full) {
  if (!w) return;
  if (w.creations) { Community.addWorks(w.creations); for (const c of w.creations) Community.refreshViewer(c.id); }
  const ws = MapView.st.world || w;
  Community.setMinds(buildMinds(ws)); Community.setSprite(ws.sprite);
  if ("studio" in w) Studio.setLive(w.studio);
  if (W3.api) { try { full ? W3.api.full(w) : W3.api.delta(w); } catch (e) { console.error(e); report("error", "3D: " + e.message); } }
}

// Zen as the overlay and the Zen tab show it, from the latest world picture
function buildMinds(w) {
  const z = w?.zen; if (!z) return Community.st.minds;
  const m = w.mind || {}, motor = m.motor || {};
  const doing = z.sleeping ? "sleeping" : z.waiting || m.waiting ? "waiting for the Sprite's answer" : m.creating ? { paint: "painting", compose: "playing the piano", sculpt: "shaping clay", write: "writing" }[m.creating] || m.creating : z.activity || "";
  return [{ name: S.name || "Zen", kind: "synth", color: "#9fb4ff", glyph: "✨", needs: z.needs, feelings: z.feelings, sleeping: z.sleeping, waiting: z.waiting || m.waiting,
    place: z.place, biome: z.biome, wet: z.wet, hands: z.hands, doing, said: z.said, thought: (S.lastThought?.text || "").trim().slice(0, 140),
    last: motor.last || S.lastDid?.action, lastText: S.lastDid?.text, brain: m.brain, stage: S.academy.stage_name }];
}

function tick(m) {
  if (m.world) { m.world.full ? MapView.setWorld(m.world) : MapView.applyDelta(m.world); worldIn(m.world, !!m.world.full); }
  if (m.academy) S.academy = m.academy;
  if (m.settings) { S.settings = m.settings; syncSettings(); }
  if (m.oracle) S.oracle = m.oracle;
  if (m.concepts) S.concepts = m.concepts;
  for (const e of m.events || []) onEvent(e);
  renderAll();
}

function onEvent(e) {
  switch (e.kind) {
    case "thought": addThought(e); S.lastThought = e; Journal.live("thoughts", e); break;
    case "did": addDeed(e); Journal.live("thoughts", e); break;
    case "ada_says":
      Community.addFeed(e); Journal.live("conversations", e);
      if (e.to === "sprite") addDialogue(e);
      break;
    case "chat": if (S.pendingChat) { S.pendingChat.remove(); S.pendingChat = null; }
      chatLine({ role: "user", text: e.user }); chatLine({ role: "mind", text: e.text, tokens: e.tokens, asleep: e.asleep });
      Journal.live("conversations", e); break;
    case "answer": addQA(e); addDialogue(e); Community.addFeed(e); Journal.live("conversations", e);
      if (e.by === "critique") toast(`🌟 The Sprite: ${e.text}`.slice(0, 180), 6000); break;
    case "happening": Community.addFeed(e); if (e.what === "rainbow") toast("🌈 A rainbow!"); break;
    case "created": Community.addFeed(e); if (e.creation) { const was = Community.st.works.has(e.creation.id); Community.addWorks([e.creation]); Community.refreshViewer(e.creation.id);
      if (!was) toast(`${Community.KIND_ICON[e.creation.kind] || "✨"} ${SYNTH()} made ${e.creation.kind === "music" ? "a song" : "a " + e.creation.kind}!`, 5000); } break;
    case "milestone": S.journey = [...(S.journey || []), e]; Community.addFeed(e); toast(`🌱 ${e.title}`, 6000); break;
    case "metric": S.metrics.push(e.point || e); if (S.metrics.length > 20000) S.metrics.shift(); chartsDue(); break;
    case "concepts": chartsDue(); break;
    case "published": toast(`🎓 ${SYNTH()} has a new brain (v${e.meta?.version}, step ${big(e.meta?.step)}).`); break;
    case "brain": toast(`🌍 ${SYNTH()} is now living with brain v${e.meta?.version}.`); break;
    case "grew": toast(`🧠 ${SYNTH()}'s brain grew to ${e.layers} layers.`, 5000); break;
    case "phase": toast(e.phase === "night" ? `🌙 Night falls.` : `☀️ Day ${e.day}: morning comes.`); break;
    case "error": banner(e.text); setTimeout(() => banner(""), 15000); break;
  }
}

// ================================================================== header
const SKY = { clear: "☀️", cloudy: "☁️", rain: "🌧️", storm: "⛈️", snow: "❄️", wind: "🌬️", windy: "🌬️", fog: "🌫️" };
function renderHeader() {
  const w = MapView.st.world, a = S.academy, mind = w?.mind || {};
  if (w?.zen) {
    setText($("#clock"), `Day ${w.day} · ${w.season} · ${w.time} · ${SKY[w.weather] || ""} ${w.weather} ${Math.round(w.temperature)}°C`);
    const night = w.phase === "night", sc = S.settings["schedule.mode"], left = dur(mind.phase_left);
    const txt = sc === "academy" ? "🎓 Study only: the world is paused" : mind.phase_left == null ? (night ? "🌙 Night" : "☀️ Day")
      : sc === "world" ? (night ? `🌙 Night · morning in ${left}` : `☀️ Day · night in ${left}`)
      : night ? `🌙 Night, studying · morning in ${left}` : `☀️ Day · night in ${left}`;
    setText($("#sched"), txt); $("#sched").classList.toggle("night", night);
    setText($("#btnSleep"), w.zen.sleeping ? "Wake up" : "Go to sleep");
    $("#orb").classList.toggle("asleep", !!w.zen.sleeping);
    setText($("#kDeeds"), big(mind.motor?.steps));
  }
  setText($("#sub"), a.version ? `brain v${a.version} · ${a.layers} layers · ${big(a.params)} parameters · ${a.device || ""}` : "starting the Academy…");
  setText($("#kStage"), a.stage_name || "–");
  setText($("#kTokens"), a.tokens != null ? big(a.tokens) + " tokens" : "–");
  setText($("#kConcepts"), a.concepts?.accuracy != null ? pct(a.concepts.accuracy) : "–");
}
$("#btnHelp").onclick = () => $("#welcome").showModal();
$("#btnSleep").onclick = () => api(MapView.st.world?.zen?.sleeping ? "wake_now" : "sleep_now").catch((e) => toast(e.message));

function showView(v) {
  S.view = v;
  $$("#nav button").forEach((x) => x.classList.toggle("on", x.dataset.view === v));
  $$(".view").forEach((el) => el.classList.toggle("on", el.id === `view-${v}`));
  if (v === "atlas") Atlas.open(); else Atlas.close();
  renderAll(); if (v === "academy") drawCharts(); if (v === "health") pollHealth(true);
  MapView.st.dirty = true;
  if (W3.api) W3.api.pause(v !== "world" || document.hidden);
}
$$("#nav button").forEach((b) => b.onclick = () => showView(b.dataset.view));

function renderAll() {
  renderHeader();
  if (S.view === "world") renderWorld();
  else if (S.view === "zen") renderZen();
  else if (S.view === "thoughts") Journal.open("thoughts");
  else if (S.view === "talks") Journal.open("conversations");
  else if (S.view === "gallery") Community.gallery($("#gallery"), $("#galleryChips"));
  else if (S.view === "academy") renderAcademy();
  else if (S.view === "concepts") renderConcepts();
  else if (S.view === "sprite") renderSprite();
  else if (S.view === "health") pollHealth();
}
Community.onChange = () => renderAll();

// ================================================================== home
function needsHTML(needs) {
  return Object.entries(needs || {}).map(([k, v]) => {
    const c = v < 25 ? "var(--bad)" : v < 50 ? "var(--warn)" : "var(--good)";
    return `<div class="need"><span>${NEED_LABEL[k] || k}</span><div><i style="width:${Math.round(v)}%;background:${c}"></i></div><b>${Math.round(v)}</b></div>`;
  }).join("");
}
const whereWords = (z) => [z.place, z.biome ? Chunks.label(z.biome) : ""].filter(Boolean).join(" · ");
function renderWorld() {
  const w = MapView.st.world; if (!w?.zen) return;
  const z = w.zen, m = w.mind || {}, n = SYNTH(), me = Community.st.minds[0];
  setText($("#ovClock"), `Day ${w.day} · ${w.season} · ${w.time} · ${SKY[w.weather] || ""} ${Math.round(w.temperature)}°C`);
  setText($("#ovPlace"), `📍 ${whereWords(z) || "somewhere"}`);
  Community.strip($("#mindStrip"));
  setHTML($("#mindCard"), Community.card(me));
  Community.feed($("#liveFeed"), ["ada_says", "answer", "created", "happening", "milestone", "chat"], 40);
  renderStudio(w);
  renderHotbar(w);
  setText($("#adaTitle"), n);
  setText($("#adaWhere"), z.sleeping ? "asleep" : `${whereWords(z)}${z.hands?.length ? " · holding " + z.hands.join(", ") : ""}${z.wet > 0.4 ? " · wet" : ""}`);
  setHTML($("#needs"), needsHTML(z.needs));
  setHTML($("#intent"), z.sleeping ? "💤 Sleeping" : esc(me?.doing ? me.doing[0].toUpperCase() + me.doing.slice(1) : "…"));
  setText($("#intentWhy"), (z.feelings || []).length ? `Feels ${z.feelings.join(", ")}.` : "");
  const mo = m.motor || {};
  setText($("#motorMini"), mo.steps != null ? `· ${big(mo.steps)} so far · reward ${fmtR(mo.reward_rate)}/min` : "");
  spark($("#sparkHome"), S.rewards.slice(-80));
  setHTML($("#log"), (w.log || []).slice().reverse().map((l) => `<li>${esc(l)}</li>`).join(""));
}
const fmtR = (v) => v == null ? "–" : (v >= 0 ? "+" : "") + (+v).toFixed(2);
// the piece Zen is making right now
function renderStudio(w) {
  const st = w.studio, box = $("#studioInset");
  box.hidden = !st;
  if (!st) return;
  const med = Studio.normMedium(st.medium);
  setText($("#studioTitle"), `${SYNTH()} is ${Studio.mediumName(st.medium)}…`);
  setText($("#studioSteps"), `${st.steps || 0} marks`);
  const cv = $("#studioCanvas"), want = med === "music" ? [512, 200] : [512, 384];
  if (cv.width !== want[0] || cv.height !== want[1]) { cv.width = want[0]; cv.height = want[1]; }
  Studio.drawLive(cv);
}
setInterval(() => { if (S.view === "world" && MapView.st.world?.studio && Studio.normMedium(MapView.st.world.studio.medium) === "sculpt") Studio.drawLive($("#studioCanvas")); }, 120);

function renderHotbar(w) {
  const v = w.visitor; if (!v || S.mode !== "you") return;
  const hands = v.hands || v.carrying || [];
  const slots = Array.from({ length: 4 }, (_, i) => hands[i]);
  setHTML($("#hotbar"), slots.map((k, i) => `<div class="slot" title="${esc(k || "empty")}"><small>${i + 1}</small>${k ? (GLYPH[k] || "❔") : ""}</div>`).join(""));
}

// a little bar chart of rewards: green for good deeds, red for bad, with a running average
function spark(cv, vals) {
  if (!cv) return;
  const dpr = devicePixelRatio || 1, W = Math.round(cv.clientWidth * dpr), H = Math.round(cv.clientHeight * dpr); if (!W || !H) return;
  if (cv.width !== W || cv.height !== H) { cv.width = W; cv.height = H; }
  const g = cv.getContext("2d"); g.clearRect(0, 0, W, H);
  if (!vals.length) { g.fillStyle = css("--muted"); g.font = `${11 * dpr}px system-ui`; g.fillText("no deeds yet", 4 * dpr, H / 2); return; }
  const mx = Math.max(0.05, ...vals.map(Math.abs)), mid = H / 2, bw = W / Math.max(40, vals.length);
  g.fillStyle = css("--line"); g.fillRect(0, mid, W, Math.max(1, dpr * 0.6));
  const good = css("--good"), bad = css("--bad");
  vals.forEach((v, i) => { const h = Math.max(1, Math.abs(v) / mx * (H / 2 - 2 * dpr)); g.fillStyle = v >= 0 ? good : bad; g.globalAlpha = 0.75; g.fillRect(W - (vals.length - i) * bw, v >= 0 ? mid - h : mid, Math.max(1, bw - dpr), h); });
  g.globalAlpha = 1; g.strokeStyle = css("--accent"); g.lineWidth = 1.6 * dpr; g.beginPath();
  let ema = 0; vals.forEach((v, i) => { ema = i ? ema * 0.9 + v * 0.1 : v; const x = W - (vals.length - i - 0.5) * bw, y = mid - ema / mx * (H / 2 - 2 * dpr); i ? g.lineTo(x, y) : g.moveTo(x, y); }); g.stroke();
}

function tokHTML(tokens) {
  if (!tokens || !tokens.length) return '<span class="muted">(silence)</span>';
  return tokens.map(([s, p]) => `<span class="tk c${p < .05 ? 0 : p < .2 ? 1 : p < .45 ? 2 : p < .75 ? 3 : 4}" title="${(p * 100).toFixed(1)}%">${esc(s)}</span>`).join("");
}
function prepend(box, html, max = 120, cls = "") {
  const d = document.createElement("div"); d.className = "item" + (cls ? " " + cls : ""); d.innerHTML = html; box.prepend(d);
  while (box.children.length > max) box.lastChild.remove();
  return d;
}
function addThought(e) { prepend($("#thoughts"), `${tokHTML(e.tokens || (e.text ? [[e.text, 0.5]] : null))}<div class="meta">brain v${e.brain ?? "?"} · ${clock(e.t)}</div>`); }
function deedHTML(e) {
  const r = +e.reward || 0, rc = r > 0.005 ? "pos" : r < -0.005 ? "neg" : "zero";
  return `<span class="act ${e.ok === false ? "fail" : ""}" title="${esc(e.action)}">${MOTOR_ICON[e.action] || "•"} ${esc(e.action || "")}</span><span class="dtext">${esc(e.text || "")}</span><span class="rw ${rc}" title="reward">${fmtR(r)}</span>`;
}
function addDeed(e) {
  S.lastDid = e; S.dids.push(e); if (S.dids.length > 200) S.dids.shift();
  S.rewards.push(+e.reward || 0); if (S.rewards.length > 200) S.rewards.shift();
  prepend($("#diary"), deedHTML(e) + `<span class="when">${clock(e.t)}</span>`, 200, "deed");
  if (S.view === "zen") prepend($("#actionStream"), deedHTML(e), 40, "deed");
}
// Zen & the Sprite: only what they say to each other
function bubble(who, text, cls, note = "") {
  const d = document.createElement("div");
  d.className = `bub ${cls}${!text || text === "…" ? " quiet" : ""}`;
  d.innerHTML = `<b>${esc(who)}</b>${note ? `<span class="note">${esc(note)}</span>` : ""}<div>${!text || text === "…" ? "…" : esc(text)}</div>`;
  return d;
}
function addDialogue(e) {
  const box = $("#dialogue"), stick = box.scrollTop + box.clientHeight >= box.scrollHeight - 30, add = [];
  if (e.kind === "answer" || e.question != null) {
    if (e.by === "you") return;
    if (e.by === "critique") add.push(bubble("The Sprite", e.text, "sprite", e.question || "about Zen's work"));
    else add.push(bubble(SYNTH(), e.question, "zen", "asks"), bubble("The Sprite", e.text, "sprite", "answers"));
  } else if (e.kind === "ada_says" && e.text) add.push(bubble(SYNTH(), e.text, "zen", "to the Sprite"));
  for (const d of add) box.append(d);
  while (box.children.length > 300) box.firstChild.remove();
  if (stick) box.scrollTop = box.scrollHeight;
}
function chatLine(c) {
  const d = document.createElement("div");
  d.className = `msg ${c.role === "user" ? "user" : "mind"}`;
  d.innerHTML = c.role === "user" ? esc(c.text) : c.asleep ? `<span class="muted">💤 ${esc(SYNTH())} is asleep.</span>` : tokHTML(c.tokens || [[c.text, .5]]);
  $("#chat").append(d); while ($("#chat").children.length > 150) $("#chat").firstChild.remove();
  $("#chat").scrollTop = $("#chat").scrollHeight;
}
$$("#adaTabs button").forEach((b) => b.onclick = () => {
  $$("#adaTabs button").forEach((x) => x.classList.toggle("on", x === b));
  $$(".below .pane").forEach((p) => p.classList.toggle("on", p.id === `pane-${b.dataset.pane}`));
});
async function sayToSynth(text) {
  S.pendingChat = document.createElement("div"); S.pendingChat.className = "msg mind pending"; S.pendingChat.textContent = "…";
  $("#chat").append(S.pendingChat);
  try { await api("chat", { text }); } catch (e) { toast(e.message); if (S.pendingChat) { S.pendingChat.remove(); S.pendingChat = null; } }
}
$("#sayForm").onsubmit = async (ev) => {
  ev.preventDefault();
  const text = $("#sayText").value.trim(); if (!text) return;
  $("#sayText").value = "";
  if (S.mode === "you" && MapView.st.world?.visitor) { try { const r = await api("visitor", { action: "say", text }); if (typeof r === "string" && r) toast(r); } catch (e) { toast(e.message); } }
  sayToSynth(text);
  $("#sayText").blur();
};
$("#chatForm").onsubmit = (ev) => { ev.preventDefault(); const text = $("#chatText").value.trim(); if (!text) return; $("#chatText").value = ""; sayToSynth(text); };

// ------------------------------------------------------------------ modes: follow, free, visit
async function setMode(mode) {
  const was = S.mode;
  S.mode = mode;
  $$("#modes button[data-mode]").forEach((x) => x.classList.toggle("on", x.dataset.mode === mode));
  $("#mode-you").hidden = mode !== "you";
  if (mode === "you" && !MapView.st.world?.visitor) { try { toast(await api("visitor", { action: "join" })); } catch (e) { toast(e.message); } }
  if (was === "you" && mode !== "you" && MapView.st.world?.visitor) { try { await api("visitor", { action: "leave" }); } catch { /* fine */ } }
  if (W3.api) { W3.api.setMode(mode === "you" ? "visit" : mode === "free" ? "free" : "watch"); if (mode === "watch") W3.api.focusOn("synth"); }
}
$$("#modes button[data-mode]").forEach((b) => b.onclick = () => setMode(b.dataset.mode));
$("#uiToggle").onclick = () => $("#stage").classList.toggle("bare");
$$("[data-mm]").forEach((b) => b.onclick = () => { const k = b.dataset.mm; if (k === "atlas") showView("atlas"); else MapView.zoom(k === "in" ? 1.4 : 1 / 1.4); });
for (const k of PORTABLE) {
  const b = document.createElement("button"); b.textContent = GLYPH[k] || "❔"; b.title = `Put down ${k}`; b.setAttribute("aria-label", `Put down ${k}`);
  b.onclick = async () => {
    const v = MapView.st.world?.visitor; if (!v) return;
    const f = [[0, -1], [1, 0], [0, 1], [-1, 0]][(typeof v.facing === "number" ? v.facing : { north: 0, east: 1, south: 2, west: 3 }[v.facing] ?? 2) % 4];
    try { toast(await api("visitor", { action: "place", kind: k, x: v.x + f[0], y: v.y + f[1] })); } catch (e) { toast(e.message); }
  };
  $("#placePalette").append(b);
}
function tileWords(x, y) {
  const t = Chunks.tile(x, y); if (!t) return "";
  const B = Chunks.st.meta?.BIOMES || [], F = Chunks.st.meta?.FEATURES || [];
  return [Chunks.label(B[t.biome]), t.water ? ["", "shallow water", "deep water", "a river"][t.water] : "", t.feat ? String(F[t.feat] || "").replace(/_/g, " ") : "", `${(t.h / 10).toFixed(0)} m`].filter(Boolean).join(" · ");
}
MapView.st.onClick = ({ x, y }) => {
  if (W3.api) { W3.api.flyTo(x, y); S.mode = "free"; $$("#modes button[data-mode]").forEach((b) => b.classList.toggle("on", b.dataset.mode === "free")); $("#mode-you").hidden = true; }
  const place = (MapView.st.world?.places || []).find((p) => Math.abs(p.x - x) <= 3 && Math.abs(p.y - y) <= 3);
  toast([place?.name, tileWords(x, y)].filter(Boolean).join(" · ") || "Not seen yet.");
};
Community.st.onSelect = (name) => {
  if (!W3.api) return;
  if (S.mode === "free") setMode("watch");
  W3.api.focusOn(name === "sprite" ? "sprite" : "synth");
};

// ------------------------------------------------------------------ the 3D world
let moveBusy = false;
window.addEventListener("world3d", (ev) => {
  const api3 = ev.detail;
  if (!api3) { $("#stage").classList.add("no3d"); return; }
  let q = "high"; try { q = localStorage.getItem("quality3d") || "high"; } catch { /* fine */ }
  try { api3.init($("#stage3d"), { quality: q }); } catch (e) { console.warn("3D view failed:", e); $("#stage").classList.add("no3d"); return; }
  W3.api = api3; W3.ready = true;
  api3.setName?.(SYNTH());
  if (MapView.st.world?.zen) api3.full({ ...MapView.st.world, full: true, ents: [...MapView.st.ents.values()] });
  api3.setMode(S.mode === "you" ? "visit" : S.mode === "free" ? "free" : "watch");
  api3.pause(S.view !== "world" || document.hidden);
  api3.onMove = (fx, fy, facing) => {
    if (moveBusy) return;
    moveBusy = true;
    api("visitor", { action: "move", fx, fy, facing }).catch(() => {}).finally(() => { moveBusy = false; });
  };
  api3.onAction = async (a) => {
    try {
      if (a.type === "take") { const r = await api("visitor", { action: "take", id: a.id }); if (r) toast(r); }
      else if (a.type === "give") { const r = await api("visitor", { action: "give" }); if (r) toast(r); }
      else if (a.type === "talk") $("#sayText").focus();
    } catch (e) { toast(e.message); }
  };
  api3.onPick = (info) => {
    if (info.kind === "synth") { Community.st.selected = SYNTH(); if (S.mode === "free") setMode("watch"); api3.focusOn("synth"); renderAll(); }
    else if (info.kind === "sprite") { api3.focusOn("sprite"); const s = MapView.st.world?.sprite; toast(`🌟 The Sprite of All Knowing ${s?.state === "listening" ? "is listening" : s?.state === "answering" ? "is answering" : "floats beside " + SYNTH()}.${s?.said ? ` “${s.said}”` : ""}`, 4200); }
    else if (info.kind === "animal") toast(`${GLYPH[info.animal] || "🐾"} a ${info.animal}`);
    else if (info.kind === "entity") {
      const e = MapView.st.ents.get(info.id);
      if (e) toast(`${GLYPH[e.kind] || ""} ${e.title ? `“${e.title}”` : e.kind}${e.lit ? " (lit)" : ""}${e.contents?.length ? ": " + e.contents.join(", ") : ""}`, 4200);
    } else if (info.kind === "tile") {
      const place = (MapView.st.world?.places || []).find((p) => Math.abs(p.x - info.x) <= 4 && Math.abs(p.y - info.y) <= 4);
      toast([place?.name, tileWords(info.x, info.y)].filter(Boolean).join(" · "));
    }
  };
  document.addEventListener("visibilitychange", () => api3.pause(document.hidden || S.view !== "world"));
});

// ================================================================== Zen tab
function renderZen() {
  const w = MapView.st.world; if (!w?.zen) return;
  const z = w.zen, m = w.mind || {}, mo = m.motor || {}, me = Community.st.minds[0] || {};
  setText($("#jName"), SYNTH());
  const done = S.journey || [];
  const next = ["first word", "first question to the Sprite", "first sentence", "first painting", "first song", "first sculpture", "found a named place"]
    .filter((x) => !done.some((ms) => String(ms.title).toLowerCase().includes(x.replace("found a named place", "found"))));
  setHTML($("#journey"), done.map((ms) => `<div class="ms"><b>${esc(ms.title)}</b><span>${ms.day ? "Day " + ms.day + " · " : ""}${esc(ms.detail || "")}</span></div>`).join("")
    + next.slice(0, 3).map((x) => `<div class="ms next"><b>Next: ${esc(x)}</b><span>not yet</span></div>`).join(""));
  const [face, why] = Community.mood(me);
  setHTML($("#zenBody"), `<div class="body-head"><span class="big-face">${face}</span><div><b>${esc(why)}</b><div class="muted">${esc(me.doing || "")}</div></div></div>
    <div class="needs">${needsHTML(z.needs)}</div>
    <dl class="facts" style="margin-top:12px">
      <dt>Where</dt><dd>${esc(whereWords(z) || "–")} <span class="muted">(${z.x}, ${z.y})</span></dd>
      <dt>Holds</dt><dd>${z.hands?.length ? z.hands.map((k) => `${GLYPH[k] || ""} ${esc(k)}`).join(", ") : '<span class="muted">nothing</span>'}</dd>
      <dt>Feels</dt><dd>${(z.feelings || []).map(esc).join(", ") || "–"}${z.wet > 0.4 ? " · wet" : ""}</dd>
      <dt>Wellbeing</dt><dd>${z.wellbeing != null ? pct(z.wellbeing / (z.wellbeing > 1 ? 100 : 1)) : "–"}</dd>
      <dt>Air</dt><dd>${Math.round(w.temperature)}°C · ${esc(w.weather)} · ${esc(w.time)}</dd></dl>`);
  const ent = mo.entropy != null ? (+mo.entropy).toFixed(2) : "–";
  setHTML($("#motorStats"), `<div class="mstats">
    <div><small>Last deed</small><b>${MOTOR_ICON[mo.last] || ""} ${esc(mo.last || "–")}</b></div>
    <div title="How spread out its choices are: high = trying many things, low = sure of itself (max ${Math.log(14).toFixed(2)})"><small>Choice entropy</small><b>${ent}</b></div>
    <div title="Average reward of its recent deeds, per minute"><small>Reward rate</small><b class="${(mo.reward_rate || 0) >= 0 ? "pos" : "neg"}">${fmtR(mo.reward_rate)}</b></div>
    <div><small>Deeds</small><b>${big(mo.steps)}</b></div></div>`);
  spark($("#sparkZen"), S.rewards);
  const share = mo.share || (() => { const c = {}; for (const d of S.dids) c[d.action] = (c[d.action] || 0) + 1; for (const k in c) c[k] /= S.dids.length; return c; })();
  const probs = S.lastDid?.probs;
  setHTML($("#motorShare"), MOTOR.map((k, i) => { const v = share[k] || 0, p = probs?.[i];
    return `<div class="bar${S.lastDid?.action === k ? " chosen" : ""}"><span>${MOTOR_ICON[k]} ${k}</span><div><i style="width:${Math.round(v * 100)}%"></i>${p != null ? `<u title="its last choice: ${(p * 100).toFixed(1)}% sure" style="left:${Math.min(99, p * 100)}%"></u>` : ""}</div><b>${pct(v)}</b></div>`; }).join("")
    + (probs ? '<div class="muted" style="margin-top:4px">The thin marks show how likely each word was at its last deed.</div>' : ""));
  const as = $("#actionStream");
  if (!as.children.length) for (const d of S.dids.slice(-40)) prepend(as, deedHTML(d), 40, "deed");
  setHTML($("#zenArt"), Community.artSkills(m.art || (w.skills || {})[SYNTH()] || w.skills?.Zen));
  const made = [...Community.st.works.values()].sort((a, b) => (b.t || b.id) - (a.t || a.id)).slice(0, 6);
  setHTML($("#zenMade"), made.length ? made.map((c) => `<span class="chip work" data-work="${c.id}">${Community.KIND_ICON[c.kind] || "✨"} ${esc(c.title || c.kind)}${c.critique?.score != null ? ` · 🌟 ${(+c.critique.score).toFixed(1)}` : ""}</span>`).join("") : '<span class="muted">Nothing yet.</span>');
}

// ================================================================== health view
let healthAt = 0;
async function pollHealth(force) {
  if (!force && performance.now() - healthAt < 4000) return;
  healthAt = performance.now();
  try { renderHealth(await (await fetch("/api/health")).json()); } catch { /* the Hub will be back */ }
}
function perfTable(p, keep = 8) {
  if (!p || !p.timings) return '<div class="muted">No measurements yet.</div>';
  const rows = Object.entries(p.timings).sort((a, b) => b[1].share - a[1].share).slice(0, keep);
  return `<div class="muted" style="margin-bottom:6px">CPU ${p.cpu_percent}% of a core${p.gauges?.memory_mb ? ` · ${Math.round(p.gauges.memory_mb)} MB` : ""}</div>`
    + `<div class="scroll-x"><table class="perf"><tr><th>Activity</th><th>time share</th><th>avg ms</th><th>max ms</th><th>/s</th></tr>`
    + rows.map(([k, v]) => `<tr><td>${esc(k)}</td><td><span class="share" style="width:${Math.round(Math.min(1, v.share) * 40)}px"></span>${pct(v.share)}</td><td>${v.avg_ms}</td><td>${v.max_ms}</td><td>${v.per_s}</td></tr>`).join("")
    + `</table></div>` + (p.gauges ? `<div class="muted" style="margin-top:6px">${Object.entries(p.gauges).filter(([k]) => k !== "memory_mb").map(([k, v]) => `${esc(k.replace(/_/g, " "))}: <b>${esc(v)}</b>`).join(" · ")}</div>` : "");
}
function dl(rows) { return rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join(""); }
function renderHealth(h) {
  setText($("#logPath"), `minds/${SYNTH()}/logs/`);
  const f = h.findings || [];
  setHTML($("#findings"), f.length ? f.map((x) => `<div class="finding ${x.level}"><b>${esc(x.where)}</b> · ${esc(x.text)}</div>`).join("") : '<div class="finding ok">Nothing looks wrong right now.</div>');
  const proc = (n) => { const p = h.processes?.[n]; return p ? `<div class="muted" style="margin-bottom:4px">${p.alive ? "running" : "stopped"} · pid ${p.pid}${p.restarts ? ` · <b style="color:var(--bad)">restarted ${p.restarts}×</b>` : ""}</div>` : ""; };
  setHTML($("#hAcademy"), proc("academy") + perfTable(h.perf?.academy));
  setHTML($("#hWorld"), proc("world") + perfTable(h.perf?.world));
  setHTML($("#hHub"), `<div class="muted" style="margin-bottom:4px">up ${dur(h.uptime_s)}</div>` + perfTable(h.perf?.hub));
  const g = (h.gpu || [])[0];
  setHTML($("#hGpu"), g ? dl([["Card", esc(g.name)], ["Busy", `${g.util_percent}%`], ["Memory", `${Math.round(g.mem_used_mb)} / ${Math.round(g.mem_total_mb)} MB`],
    ["Temperature", `${g.temp_c}°C`], ["Power", `${g.power_w} W`], ["Clock", `${g.sm_clock_mhz} MHz`], ["Driver", esc(g.driver)]]) : '<dd class="muted">No NVIDIA GPU readings (nvidia-smi not found).</dd>');
  const b = S.clientPerf || h.browser || {};
  setHTML($("#hBrowser"), b.fps != null ? dl([["Frames per second", `${b.fps} <span class="muted">(capped at 60; worst gap ${b.worst_frame_gap_ms} ms)</span>`],
    ["3D world", b.chunks_3d >= 0 ? `${b.chunks_3d} chunks, ${b.draw_ms_3d} ms a frame (max ${b.draw_max_ms_3d}), building ≤ ${b.chunk_build_max_ms} ms` : "not on screen"],
    ["Frozen moments", `${b.longtasks} (${b.longtask_ms} ms total, longest ${b.longtask_max_ms} ms)`],
    ["Updates", `${b.msgs_per_s}/s, ${b.kb_per_s} KB/s, ${b.msg_avg_ms} ms each (max ${b.msg_max_ms})`],
    ["Screen", `${b.window} window, scale ${b.dpr}`], ["Script errors", `${b.js_errors}${b.last_error ? ` · ${esc(b.last_error)}` : ""}`]])
    : '<dd class="muted">Measuring… (the first numbers arrive after 15 seconds)</dd>');
  const box = $("#hLog"), stick = box.scrollTop + box.clientHeight >= box.scrollHeight - 20;
  setText(box, (h.log || []).join("\n") || "No warnings or errors so far.");
  if (stick) box.scrollTop = box.scrollHeight;
}

// ================================================================== academy view
function renderAcademy() {
  const a = S.academy;
  if (!a.stages) { setHTML($("#acStatus"), "The Academy is starting…"); return; }
  const st = $("#acStatus"); st.className = "status " + (a.paused ? "off" : "on");
  setText(st, a.paused ? `Resting: ${a.pause_reason}` : `Studying (${a.intensity}) · ${big(a.tps)} tokens/s`);
  setHTML($("#ladder"), a.stages.map((n, i) => `<span class="${i < a.stage ? "done" : i === a.stage ? "now" : ""}">${esc(n)}</span>`).join(""));
  setText($("#stageBlurb"), a.stage_blurb || "");
  setHTML($("#acFacts"), dl([
    ["Brain", `${big(a.params)} parameters (${big(a.trunk_params)} outside the word table) · ${a.layers} layers × ${a.d_model} wide · ${a.seq_len}-token memory${a.growths ? ` · grew ${a.growths}×` : ""}`],
    ["Device", `${esc(a.device)} · ${esc(a.precision)} · ${esc(a.tokenizer)} tokens`],
    ["Progress", `step ${big(a.step)} · ${big(a.tokens)} tokens studied`],
    ["Loss", `${a.loss?.toFixed(3) ?? "–"} training · ${a.val?.toFixed(3) ?? "–"} held-out · ${a.bpb?.toFixed(3) ?? "–"} bits per byte`],
    ["Concepts", a.concepts?.accuracy != null ? `${pct(a.concepts.accuracy)} of ${a.concepts.n} facts (chance 25%)` : "not tested yet"],
    ["Published", a.last_publish ? `brain v${a.version}, ${ago(a.last_publish)}` : `brain v${a.version}`],
    ["Stability", a.skipped ? `${a.skipped} unstable steps skipped` : "no unstable steps"],
  ]));
  const mix = a.mix || {}, names = { fineweb: "Web text (FineWeb)", experience: "Its experience (deeds)", journal: "Its journal", concepts: "Concept drills" };
  setHTML($("#mix"), Object.keys(names).map((k) => `<div class="bar"><span>${names[k]}</span><div><i style="width:${Math.round((mix[k] || 0) * 100)}%"></i></div><b>${pct(mix[k] || 0)}</b></div>`).join("")
    + `<div class="muted" style="margin-top:4px">${big(a.pools?.journal_added)} journal entries · ${big(a.pools?.experience ?? a.pools?.experience_added)} experience segments · ${a.pools?.facts ?? "–"} facts known to the graph</div>`);
  const mo = a.motor || {}, n = (v, d = 3) => v == null ? "–" : (+v).toFixed(d);
  setHTML($("#lifeFacts"), dl([["Policy loss", n(mo.pg_loss)], ["Choice entropy", `${n(mo.entropy, 2)} <span class="muted">(of ${Math.log(14).toFixed(2)} at most)</span>`],
    ["Mean return", n(mo.return)], ["Windows studied", big(mo.windows)], ["Experience kept", big(a.pools?.experience)]]));
  const f = a.fineweb || {};
  setHTML($("#fwFacts"), dl([["Status", esc(f.status) + (f.error ? ` <span class="muted">(${esc(f.error)})</span>` : "")],
    ["Reading", `<span class="muted">${esc(f.source || "–")}</span>`], ["Documents", big(f.docs)], ["Bytes per token", f.bytes_per_token ?? "–"]]));
}
$$("[data-ac]").forEach((b) => b.onclick = async () => {
  if (b.dataset.ac === "grow" && !confirm(`Add a layer to ${SYNTH()}'s brain? What it knows is kept; it gains room to learn more.`)) return;
  try { await api(b.dataset.ac); toast("Done."); } catch (e) { toast(e.message); }
});
$("#probeForm").onsubmit = async (ev) => {
  ev.preventDefault();
  try {
    const r = await api("probe", { text: $("#probeText").value });
    const mx = r.next[0]?.[1] || 1;
    setHTML($("#probeOut"), `<div style="line-height:1.9">${r.tokens.map(([s, b]) => `<span class="tk" style="background:rgba(255,107,122,${Math.min(.7, b / 20)})" title="${b} bits of surprise">${esc(s)}</span>`).join("")}</div>`
      + `<div class="bars" style="margin-top:6px">${r.next.map(([s, p]) => `<div class="bar"><span class="tk">${esc(JSON.stringify(s).slice(1, -1))}</span><div><i style="width:${p / mx * 100}%"></i></div><b>${(p * 100).toFixed(1)}%</b></div>`).join("")}</div>`);
  } catch (e) { toast(e.message); }
};
let chartTimer;
function chartsDue() { if (!chartTimer) chartTimer = setTimeout(() => { chartTimer = null; drawCharts(); }, 1500); }
function series(...keys) {
  const out = []; for (const p of S.metrics) { const k = keys.find((x) => p[x] != null); if (k) out.push([p.step, p[k]]); }
  if (out.length > 600) { const k = Math.ceil(out.length / 600); return out.filter((_, i) => i % k === 0 || i === out.length - 1); }
  return out;
}
function chart(cv, lines, opt = {}) {
  const dpr = devicePixelRatio || 1, W = cv.clientWidth * dpr, H = cv.clientHeight * dpr; if (!W) return;
  cv.width = W; cv.height = H; const g = cv.getContext("2d"), pts = lines.flatMap((l) => l.data);
  g.font = `${10 * dpr}px system-ui`; g.fillStyle = css("--muted");
  if (pts.length < 2) { g.fillText(opt.empty || `waiting for ${SYNTH()} to study…`, 8 * dpr, H / 2); return; }
  const x0 = Math.min(...pts.map((p) => p[0])), x1 = Math.max(...pts.map((p) => p[0]));
  let y0 = opt.min ?? Math.min(...pts.map((p) => p[1])), y1 = opt.max ?? Math.max(...pts.map((p) => p[1]));
  if (y1 - y0 < 1e-9) { y1 += 1; if (opt.min == null) y0 -= 1; }
  const L = 42 * dpr, R = 6 * dpr, T = 6 * dpr, B = 16 * dpr, X = (x) => L + (x - x0) / (x1 - x0 || 1) * (W - L - R), Y = (y) => H - B - (y - y0) / (y1 - y0) * (H - T - B);
  g.strokeStyle = css("--line"); g.lineWidth = 1;
  for (let i = 0; i <= 3; i++) { const y = y0 + (y1 - y0) * i / 3; g.beginPath(); g.moveTo(L, Y(y)); g.lineTo(W - R, Y(y)); g.stroke();
    g.fillText(opt.fmt ? opt.fmt(y) : Math.abs(y) >= 100 ? big(y) : y.toFixed(2), 2 * dpr, Y(y) + 3 * dpr); }
  g.fillText(`step ${big(x1)}`, W - R - 62 * dpr, H - 3 * dpr);
  if (opt.chance != null) { g.setLineDash([4 * dpr, 4 * dpr]); g.beginPath(); g.moveTo(L, Y(opt.chance)); g.lineTo(W - R, Y(opt.chance)); g.stroke(); g.setLineDash([]); }
  for (const l of lines) {
    if (!l.data.length) continue;
    g.strokeStyle = l.color; g.lineWidth = 1.6 * dpr; g.beginPath();
    l.data.forEach(([x, y], i) => i ? g.lineTo(X(x), Y(y)) : g.moveTo(X(x), Y(y))); g.stroke();
    if (l.dots) { g.fillStyle = l.color; for (const [x, y] of l.data) { g.beginPath(); g.arc(X(x), Y(y), 2.4 * dpr, 0, 7); g.fill(); } }
  }
}
function drawCharts() {
  if (S.view !== "academy") return;
  const c = (k) => $(`canvas[data-chart=${k}]`), A = css("--accent"), B = css("--warn"), G = css("--good"), P2 = css("--accent-2");
  chart(c("loss"), [{ data: series("loss_ema"), color: A }, { data: series("val"), color: B, dots: true }]);
  chart(c("concepts"), [{ data: series("concepts"), color: G, dots: true }], { min: 0, max: 1, chance: .25, fmt: (v) => pct(v) });
  chart(c("bpb"), [{ data: series("bpb"), color: P2 }]);
  chart(c("tps"), [{ data: series("tps"), color: A }], { min: 0 });
  chart(c("policy"), [{ data: series("pg", "policy_loss"), color: P2 }, { data: series("ent", "entropy"), color: G }, { data: series("ret", "return"), color: B }],
    { empty: "waiting for its first deeds to be studied…" });
}
addEventListener("resize", () => drawCharts());

// ================================================================== concepts view
const REL = { "is a": "What it is", color: "Colors", is: "What it's like", "made of": "What it's made of", "used for": "What it's for", "found in": "Where it is", can: "What it can do" };
function renderConcepts() {
  const c = S.concepts || {};
  const bars = (obj, label) => Object.entries(obj || {}).map(([k, v]) => `<div class="bar"><span>${esc(label(k))}</span><div><i style="width:${Math.round(v * 100)}%;background:${v > .5 ? "var(--good)" : v > .3 ? "var(--accent)" : "var(--warn)"}"></i></div><b>${pct(v)}</b></div>`).join("");
  setHTML($("#byRel"), bars(c.by_relation, (k) => REL[k] || k) || '<div class="muted">Not tested yet.</div>');
  setHTML($("#bySrc"), bars(c.by_source, (k) => k === "built-in" ? "Facts of the world" : k === "oracle" ? "Told by the Sprite" : k) || '<div class="muted">Not tested yet.</div>');
  const filter = $("#factFilter").value, term = $("#factSearch").value.toLowerCase();
  const rows = (c.results || []).filter((r) => (filter === "all" || (filter === "wrong" && !r.ok) || (filter === "right" && r.ok)) && (!term || `${r.s} ${r.r} ${r.o}`.includes(term)));
  setHTML($("#factRows"), rows.slice(0, 400).map((r) => `<tr><td class="${r.ok ? "ok" : "no"}">${r.ok ? "✓" : "✗"}</td><td>${esc(r.s)} <span class="muted">${esc(r.r)}</span> ${esc(r.o)}</td><td>${r.ok ? "" : esc(r.chose)}</td><td class="muted">${esc(r.src)}</td></tr>`).join(""));
}
$("#factFilter").onchange = renderConcepts; $("#factSearch").oninput = renderConcepts;

// ================================================================== the Sprite
const gb = (n) => n ? `${(n / 1e9).toFixed(1)} GB` : "";
function renderSprite() {
  const o = S.oracle, st = $("#orStatus"), b = o.builtin || {}, builtin = (o.backend || S.settings["oracle.backend"] || "builtin") === "builtin";
  const setup = builtin && (b.status === "downloading" || b.status === "starting");
  $("#orMeter").hidden = !setup; $("#orBar").style.width = `${Math.round((b.progress || 0) * 100)}%`;
  const ok = o.enabled && !!o.active;
  st.className = "status " + (ok ? "on" : "off");
  setText(st, !o.enabled ? "The Sprite's mind is switched off: Zen's questions go unanswered."
    : setup ? `${b.detail || "Getting the Sprite's mind ready"}… ${b.progress ? pct(b.progress) : ""}`
    : o.error ? o.error
    : ok ? `${o.active} · ${o.answers ?? o.answered ?? 0} answer${(o.answers ?? o.answered) === 1 ? "" : "s"} given this session` : "The Sprite's mind is getting ready…");
  $("#orOllamaRow").hidden = builtin;
  const cat = b.catalog || [], choice = b.choice || S.settings["oracle.builtin_model"];
  setHTML($("#orModels"), builtin ? cat.map((m) => `<button class="model${m.name === choice ? " on" : ""}" data-model="${esc(m.name)}" aria-pressed="${m.name === choice}">
      <b>${esc(m.label || m.name)}</b>${m.senses ? '<span class="senses">👁️ 👂 sees and hears</span>' : ""}
      <small>${gb(m.size)}${m.downloaded ? " · downloaded" : " · downloads when chosen"}</small></button>`).join("") || '<div class="muted">No models listed.</div>'
    : '<div class="muted">Using a model from Ollama.</div>');
  if (!builtin) {
    const sel = $("#orModel"), sig = (o.models || []).map((m) => m.name).join("|") + o.model;
    if (sel._sig !== sig && document.activeElement !== sel) {
      sel._sig = sig;
      sel.innerHTML = (o.models || []).length ? o.models.map((m) => `<option value="${esc(m.name)}">${esc(m.name)}</option>`).join("") : "<option value=''>No Ollama models found</option>";
      sel.value = o.model || "";
    }
  }
}
document.addEventListener("click", async (ev) => {
  const b = ev.target.closest("[data-model]"); if (!b) return;
  try { await api("set", { key: "oracle.builtin_model", value: b.dataset.model }); S.settings["oracle.builtin_model"] = b.dataset.model; if (S.oracle.builtin) S.oracle.builtin.choice = b.dataset.model; renderSprite(); toast("The Sprite will use that model."); }
  catch (e) { toast(e.message); }
});
$("#orModel").onchange = (e) => api("set", { key: "oracle.model", value: e.target.value }).catch((er) => toast(er.message));
$("#btnModels").onclick = async () => { try { S.oracle = await api("models"); renderSprite(); } catch (e) { toast(e.message); } };
$("#askForm").onsubmit = async (ev) => {
  ev.preventDefault(); const q = $("#askText").value.trim(); if (!q) return;
  setHTML($("#askOut"), `<div class="item muted sprite-thinking">🌟 The Sprite is thinking…</div>`);
  try { const a = await api("oracle_ask", { question: q }); setHTML($("#askOut"), `<div class="item sprite-answer"><b class="t">The Sprite answers</b>${esc(a)}</div>`); $("#askText").value = ""; }
  catch (e) { setHTML($("#askOut"), `<div class="item">${esc(e.message)}</div>`); }
};
function addQA(e) {
  const who = e.by === "critique" ? "🌟 On Zen's work" : e.by === "you" ? "You asked" : `${esc(SYNTH())} asked`;
  prepend($("#qa"), `<b class="t">${who}</b>${e.question ? `<i>${esc(e.question)}</i>\n` : ""}${esc(e.text)}<div class="meta">${clock(e.t)}</div>`, 80, e.by === "critique" ? "crit" : "");
}

// ================================================================== settings
function syncSettings() {
  const s = S.settings;
  for (const el of $$("[data-set]")) {
    const k = el.dataset.set; if (!(k in s) || el === document.activeElement || el._busy) continue;
    if (el.type === "checkbox") el.checked = !!s[k]; else el.value = s[k];
    const out = el.parentElement.querySelector("output"); if (out) out.textContent = el.type === "range" ? el.value : "";
  }
  for (const r of $$("input[name=schedule]")) r.checked = r.value === s["schedule.mode"];
  $("#dayGentle").checked = s["schedule.day_training"] === "gentle";
}
for (const el of $$("[data-set]")) {
  el.addEventListener("input", () => { const o = el.parentElement.querySelector("output"); if (o && el.type === "range") o.textContent = el.value; el._busy = 1; });
  el.addEventListener("change", async () => {
    const v = el.type === "checkbox" ? el.checked : el.type === "range" ? parseFloat(el.value) : el.value;
    try { await api("set", { key: el.dataset.set, value: v }); S.settings[el.dataset.set] = v; syncSettings(); } catch (e) { toast(e.message); }
    setTimeout(() => delete el._busy, 500);
  });
}
for (const r of $$("input[name=schedule]")) r.onchange = () => api("set", { key: "schedule.mode", value: r.value }).then(() => toast("Schedule changed.")).catch((e) => toast(e.message));
$("#dayGentle").onchange = (e) => api("set", { key: "schedule.day_training", value: e.target.checked ? "gentle" : "pause" }).catch((er) => toast(er.message));
try { $("#quality3d").value = localStorage.getItem("quality3d") || "high"; $("#themeSel").value = localStorage.getItem("theme") || ""; } catch { /* fine */ }
$("#quality3d").onchange = (e) => { try { localStorage.setItem("quality3d", e.target.value); } catch { /* fine */ } if (W3.api) W3.api.setQuality(e.target.value); toast(`3D quality: ${e.target.value}.`); };
$("#themeSel").onchange = (e) => {
  const v = e.target.value; try { localStorage.setItem("theme", v); } catch { /* fine */ }
  if (v) document.documentElement.dataset.theme = v; else delete document.documentElement.dataset.theme;
  drawCharts(); Atlas.st.dirty = true;
};

connect();

// ================================================================== Thoughts and Conversations: everything, whole
// The Hub keeps every thought, deed and conversation of Zen on disk; these tabs read it a page at a time
// (newest first) and add new ones as they happen.
const Journal = (() => {
  const K = {
    thoughts: { list: "#thList", more: "#thMore", end: "#thEnd", search: "#thSearch" },
    conversations: { list: "#tkList", more: "#tkMore", end: "#tkEnd", search: "#tkSearch" },
  };
  const st = { thoughts: { loaded: false, oldest: null, busy: false, q: "", who: "" }, conversations: { loaded: false, oldest: null, busy: false, q: "", who: "" } };
  const dayKey = (e) => `Day ${e.day ?? "?"}`;
  const CHAT_GAP = 600;

  function place(box, el, e, atTop) {
    el.dataset.day = dayKey(e);
    if (atTop) {
      const top = box.firstElementChild;
      if (top?.classList.contains("arch-day") && top.dataset.day === dayKey(e)) top.after(el);
      else { const h = document.createElement("div"); h.className = "arch-day"; h.dataset.day = dayKey(e); h.textContent = dayKey(e); box.prepend(h); h.after(el); }
    } else {
      const last = box.lastElementChild;
      if (!last || last.dataset.day !== dayKey(e)) { const h = document.createElement("div"); h.className = "arch-day"; h.dataset.day = dayKey(e); h.textContent = dayKey(e); box.append(h); }
      box.append(el);
    }
  }
  function thoughtEl(e) {
    const d = document.createElement("article");
    if (e.kind === "act") {       // a deed: one compact line
      const r = +e.reward || 0;
      d.className = `arch-item act${e.ok === false ? " fail" : ""}`;
      d.innerHTML = `<span class="arr">→</span><b>${MOTOR_ICON[e.action] || ""} ${esc(e.action || "")}</b><span class="atext">${esc(e.text || "")}</span><span class="rw ${r > 0.005 ? "pos" : r < -0.005 ? "neg" : "zero"}">${fmtR(r)}</span><span class="arch-meta">${esc(e.time || "")}</span>`;
    } else {
      d.className = "arch-item thought";
      const shade = $("#thShade").checked && e.tokens?.length;
      d.innerHTML = `<div class="arch-text">${shade ? tokHTML(e.tokens) : esc(e.text || "") || '<span class="muted">(silence)</span>'}</div>
        <div class="arch-meta">its own words · ${esc(e.time || "")}${e.time ? " · " : ""}${clock(e.t)} · brain v${e.brain ?? "?"}</div>`;
    }
    d._e = e;
    return d;
  }
  function lineEl(who, text) {
    const zen = who === SYNTH(), spr = /sprite/i.test(who), quiet = !text || text === "…";
    const d = document.createElement("div");
    d.className = `bub ${zen ? "zen" : who === "you" ? "you" : spr ? "sprite" : "other"}${quiet ? " quiet" : ""}`;
    d.innerHTML = `<b>${esc(who === "you" ? "You" : spr ? "The Sprite" : who)}</b><div>${quiet ? "…" : esc(text)}</div>`;
    return d;
  }
  function talkEl(e) {
    const d = document.createElement("article"); d.className = `arch-item talk with-${esc(e.with || "you")} k-${esc(e.kind || "")}`;
    const what = e.kind === "question" ? (e.asker === "you" ? "You ask the Sprite" : `${esc(SYNTH())} asks the Sprite`)
      : e.kind === "critique" ? `🌟 The Sprite on ${esc(SYNTH())}'s work` : e.kind === "said" ? `${esc(SYNTH())} says aloud` : e.with === "you" ? "With you" : `With ${esc(e.with)}`;
    const about = e.kind === "critique" ? String(e.about || "").replace(/^\(|\)$/g, "") : (e.topic || "").replace(/^(talk|chat) (with|to) \S+ (about )?/i, "").replace(/^about /i, "");
    d.innerHTML = `<header><b>${what}</b>${about ? `<span class="muted"> · ${esc(about)}</span>` : ""}
      <span class="arch-meta">${esc(e.time || "")}${e.time ? " · " : ""}${clock(e.t)}</span></header><div class="dialogue"></div>`;
    const box = d.querySelector(".dialogue");
    for (const [who, text] of e.lines || []) box.append(lineEl(who, text));
    d._e = e;
    return d;
  }
  const make = (kind, e) => kind === "thoughts" ? thoughtEl(e) : talkEl(e);
  const matches = (kind, e) => {
    const s = st[kind];
    if (s.who && (kind === "thoughts" ? e.kind || "thought" : e.with) !== s.who) return false;
    if (!s.q) return true;
    const text = kind === "thoughts" ? `${e.text || ""} ${e.action || ""}` : (e.lines || []).map((l) => l[1] || "").join(" ");
    return text.toLowerCase().includes(s.q.toLowerCase());
  };
  function mergeChat(box, e, atTop) {
    if (e.with !== "you") return false;
    const items = [...box.querySelectorAll(".arch-item.talk")];
    const near = atTop ? items[0] : items.at(-1);
    if (!near || near._e.with !== "you") return false;
    const gap = atTop ? e.t - near._e.t : (near._e.t0 ?? near._e.t) - e.t;
    if (gap < 0 || gap > CHAT_GAP || dayKey(near._e) !== dayKey(e)) return false;
    const dlg = near.querySelector(".dialogue"), els = (e.lines || []).map(([w, t]) => lineEl(w, t));
    if (atTop) { dlg.append(...els); near._e = { ...near._e, t: e.t, lines: [...near._e.lines, ...e.lines] }; }
    else { dlg.prepend(...els); near._e = { ...near._e, t0: e.t, lines: [...e.lines, ...near._e.lines] }; }
    return true;
  }
  function add(kind, e, atTop) {
    const box = $(K[kind].list);
    if (kind === "conversations" && mergeChat(box, e, atTop)) return;
    place(box, make(kind, e), e, atTop);
  }
  async function load(kind, reset) {
    const s = st[kind], k = K[kind];
    if (s.busy) return;
    s.busy = true;
    if (reset) { $(k.list).innerHTML = ""; s.oldest = null; }
    const p = new URLSearchParams({ limit: kind === "thoughts" ? 150 : 40 });
    if (s.oldest != null) p.set("before", s.oldest);
    if (s.q) p.set("q", s.q);
    if (s.who) p.set("who", s.who);
    try {
      const r = await fetch(`/api/archive/${kind}?${p}`).then((x) => x.json());
      for (const e of r.items || []) { add(kind, e, false); s.oldest = e.t; }
      $(k.more).hidden = !r.more;
      const n = $(k.list).querySelectorAll(".arch-item").length;
      setText($(k.end), r.more ? "" : n ? `That's all of them${s.q ? ` with “${s.q}”` : ""}.` :
        s.q ? `None with “${s.q}”.` : kind === "thoughts" ? (s.who === "thought" ? `No words of its own yet: while its brain is new, ${SYNTH()}'s monologue is mostly silence.` : `Nothing yet. ${SYNTH()}'s thoughts start once it is awake.`) : `No conversations yet.`);
      s.loaded = true;
    } catch (err) { setText($(k.end), `Couldn't load: ${err.message}`); }
    s.busy = false;
  }
  function open(kind) { if (!st[kind].loaded) load(kind, true); }
  function live(kind, ev) {
    if (!st[kind].loaded) return;
    let e;
    const ws = MapView.st.world || {}, when = { t: ev.t || Date.now() / 1000, day: ws.day, time: ws.time };
    if (kind === "thoughts") {
      if (ev.kind === "did") e = { ...when, kind: "act", action: ev.action, text: ev.text, ok: ev.ok, reward: ev.reward };
      else { if (!(ev.text || "").trim()) return; e = { ...when, kind: "thought", text: ev.text, tokens: ev.tokens, brain: ev.brain }; }
    } else if (ev.kind === "chat") {
      if (ev.asleep || !(ev.user || ev.text)) return;
      e = { ...when, with: "you", kind: "chat", lines: [["you", ev.user || ""], [SYNTH(), ev.text || ""]] };
    } else if (ev.kind === "answer") {
      e = ev.by === "critique" ? { ...when, with: "sprite", kind: "critique", about: ev.question || "", lines: [["Sprite", ev.text || ""]] }
        : { ...when, with: "sprite", kind: "question", asker: ev.by === "you" ? "you" : SYNTH(), lines: [[ev.by === "you" ? "you" : SYNTH(), ev.question || ""], ["Sprite", ev.text || ""]] };
    } else if (ev.kind === "ada_says" && ev.to !== "sprite" && (ev.text || "").trim()) {
      e = { ...when, with: "world", kind: "said", lines: [[SYNTH(), ev.text]] };
    } else return;
    if (!matches(kind, e)) return;
    const box = $(K[kind].list);
    const stick = box.getBoundingClientRect().top > -40;
    add(kind, e, true);
    if (!stick) window.scrollBy(0, box.firstElementChild?.nextElementSibling?.offsetHeight || 0);
    while (kind === "thoughts" && box.children.length > 1500) box.lastChild.remove();
  }
  const timers = {};
  for (const kind of ["thoughts", "conversations"]) {
    const k = K[kind];
    $(k.more).onclick = () => load(kind, false);
    $(k.search).oninput = (ev) => { clearTimeout(timers[kind]); timers[kind] = setTimeout(() => { st[kind].q = ev.target.value.trim(); load(kind, true); }, 300); };
  }
  $("#thShade").onchange = () => { for (const el of $$("#thList .arch-item.thought")) { const n = thoughtEl(el._e); n.dataset.day = el.dataset.day; el.replaceWith(n); } };
  $$("#thKind button").forEach((b) => b.onclick = () => { $$("#thKind button").forEach((x) => x.classList.toggle("on", x === b)); st.thoughts.who = b.dataset.kind; load("thoughts", true); });
  $$("#tkWho button").forEach((b) => b.onclick = () => { $$("#tkWho button").forEach((x) => x.classList.toggle("on", x === b)); st.conversations.who = b.dataset.who; load("conversations", true); });
  return { open, live, load, st };
})();
