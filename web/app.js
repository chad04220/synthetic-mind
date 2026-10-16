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
function setHTML(el, html) { if (el && el._h !== html) { el._h = html; el.innerHTML = html; } }
function setText(el, t) { if (el && el.textContent !== t) el.textContent = t; }

const S = { view: "world", pane: "talk", settings: {}, academy: {}, metrics: [], assessments: [], concepts: {}, oracle: {},
            feeds: {}, mode: "watch", tool: null, pendingChat: null };

async function api(name, body = {}) {
  const r = await fetch(`/api/${name}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || r.statusText);
  return j.result;
}
let toastTimer;
function toast(text, ms = 2800) {
  if (!text) return;
  let t = $(".toast"); if (!t) { t = document.createElement("div"); t.className = "toast"; document.body.append(t); }
  t.textContent = text; t.classList.add("show"); clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove("show"), ms);
}
function banner(text) { const b = $("#banner"); b.hidden = !text; if (text) b.textContent = text; }

// ================================================================== connection
// ================================================================== the page's own health
const P = { t0: performance.now(), msgs: 0, bytes: 0, msgMs: 0, msgMax: 0, long: 0, longMs: 0, longMax: 0, errors: 0 };
try {
  new PerformanceObserver((list) => {
    for (const e of list.getEntries()) { P.long++; P.longMs += e.duration; P.longMax = Math.max(P.longMax, e.duration); }
  }).observe({ type: "longtask", buffered: false });
} catch { /* not every browser reports long tasks */ }
addEventListener("error", (e) => { P.errors++; report("error", `${e.message} (${e.filename}:${e.lineno})`); });
addEventListener("unhandledrejection", (e) => { P.errors++; report("error", String(e.reason)); });
function report(level, text) { P.lastError = `${level}: ${text}`.slice(0, 300); }
setInterval(() => {
  const now = performance.now(), secs = (now - P.t0) / 1000, mp = MapView.st.perf;
  const body = {
    window_s: Math.round(secs), visible: !document.hidden, view: S.view,
    // frames the 3D view really drew (capped at 60), else the minimap's pace
    fps: W3.api && S.view === "world" ? (W3.api.stats().fps || 0) : Math.round(mp.frames / secs), fps_cap: 60,
    worst_frame_gap_ms: Math.round(mp.gapMax),
    draws_per_s: +(mp.draws / secs).toFixed(1), draw_avg_ms: +(mp.drawMs / Math.max(1, mp.draws)).toFixed(1), draw_max_ms: Math.round(mp.drawMax),
    msgs_per_s: +(P.msgs / secs).toFixed(1), kb_per_s: +(P.bytes / 1024 / secs).toFixed(1),
    msg_avg_ms: +(P.msgMs / Math.max(1, P.msgs)).toFixed(1), msg_max_ms: Math.round(P.msgMax),
    longtasks: P.long, longtask_ms: Math.round(P.longMs), longtask_max_ms: Math.round(P.longMax), js_errors: P.errors,
    last_error: P.lastError || "", dpr: devicePixelRatio, canvas: `${MapView.canvas.width}x${MapView.canvas.height}`,
    window: `${innerWidth}x${innerHeight}`, browser: navigator.userAgent.slice(0, 160),
    memory_mb: performance.memory ? Math.round(performance.memory.usedJSHeapSize / 2 ** 20) : -1,
  };
  fetch("/api/client_perf", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).catch(() => {});
  S.clientPerf = body;
  Object.assign(P, { t0: now, msgs: 0, bytes: 0, msgMs: 0, msgMax: 0, long: 0, longMs: 0, longMax: 0, errors: 0 });
  Object.assign(mp, { frames: 0, draws: 0, drawMs: 0, drawMax: 0, gapMax: 0 });
}, 15000);

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
  S.settings = m.settings; S.academy = m.academy || {}; S.metrics = m.metrics || []; S.assessments = m.assessments || [];
  S.concepts = m.concepts || {}; S.oracle = m.oracle || {}; S.feeds = m.feeds || {};
  setText($("#name"), m.name); document.title = `${m.name} · Synthetic Mind`; S.name = m.name;
  S.companion = m.oracle?.companion || "Wren";
  $$(".wrenname").forEach((el) => el.textContent = S.companion);
  setTalkTarget(null);
  $("#chatText").placeholder = `Say something to ${m.name}…`;
  S.journey = m.journey || [];
  $$(".synthname").forEach((el) => el.textContent = m.name);
  try { if (!localStorage.getItem("welcomed")) { $("#welcome").showModal(); localStorage.setItem("welcomed", "1"); } } catch { /* private window */ }
  MapView.setWorld(m.world);
  worldIn(m.world, true);
  for (const k of ["npc", "ada_says", "wren_says", "wren_did", "wren_thought", "talk", "happening", "story", "answer"])
    for (const e of S.feeds[k] || []) Community.st.feed.push(e);
  Community.st.feed.sort((a, b) => a.t - b.t);
  Community.addStories(m.stories || []);
  $("#chat").innerHTML = ""; $("#thoughts").innerHTML = ""; $("#diary").innerHTML = ""; $("#dialogue").innerHTML = ""; $("#wthoughts").innerHTML = "";
  $("#lessons").innerHTML = ""; $("#qa").innerHTML = "";
  for (const c of S.feeds.chat || []) {
    if (c.kind === "chatline") chatLine(c);
    else if (c.kind === "chat") { chatLine({ role: "user", text: c.user }); chatLine({ role: "mind", text: c.text, tokens: c.tokens, asleep: c.asleep }); }
    else if (c.kind === "tutor") tutorLine(c);
  }
  for (const e of S.feeds.thought || []) addThought(e);
  const byTime = (...ks) => ks.flatMap((k) => S.feeds[k] || []).sort((a, b) => a.t - b.t);
  for (const e of byTime("deed", "wren_did")) addDeed(e);
  for (const e of byTime("talk_start", "talk", "wren_says", "ada_says", "answer")) addDialogue(e);
  for (const e of byTime("wren_thought", "wren_intent")) addWrenMind(e);
  for (const e of S.feeds.lesson || []) addLesson(e);
  for (const e of S.feeds.answer || []) addQA(e);
  for (const e of S.feeds.wren_thought || []) addWrenThought(e);
  for (const e of m.events || []) if (e.kind === "error") banner(e.text);
  syncSettings(); renderAll(); drawCharts();
}

function worldIn(w, full) {
  if (!w) return;
  if (w.creations) Community.addWorks(w.creations);
  if (w.stories) Community.addStories(w.stories);
  if (w.kinds) Community.st.kinds = w.kinds;
  Community.setMinds(buildMinds(MapView.st.world || w));
  if (W3.api) { try { full ? W3.api.full(w) : W3.api.delta(w); } catch (e) { console.error(e); report("error", "3D: " + e.message); } }
}

// The two minds as the overlay and the Together tab show them, from the latest world picture.
function buildMinds(w) {
  if (!w?.ada) return Community.st.minds;
  const a = w.ada, m = w.mind || {}, c = w.companion || {}, wr = w.wren || {};
  const lastThought = (S.lastThought || {}).text || "";
  const zen = { name: a.name, kind: "synth", color: "#9fb4ff", glyph: "✨", needs: a.needs, feelings: a.feelings, sleeping: a.sleeping,
    talking: a.talking, place: placeWords(a.place), activity: a.activity, wet: a.wet, carrying: a.carrying,
    doing: m.plan || m.intent?.text || "", why: m.intent?.reason, source: m.intent?.source, companion: c.name, steps: m.steps_left,
    said: m.said, thought: lastThought.trim().slice(0, 140), own_words: m.self_rate, brain: m.brain, bond: w.bond,
    stage: S.academy.stage_name, art: (w.skills || {})[a.name] };
  const wren = c.name ? { name: c.name, kind: "companion", color: "#7fb3a6", glyph: "🧑‍🌾", needs: c.needs, feelings: c.feelings,
    sleeping: c.sleeping, talking: c.talking, place: placeWords(c.place), activity: c.activity, wet: c.wet, carrying: c.carrying,
    doing: wr.plan || wr.intent?.text || "", thought: (wr.thoughts || []).at(-1)?.text, own_words: wr.model_share, care: wr.care,
    bond: w.bond, diary: (wr.diary || []).map((d) => `${d.time}: ${d.text}`), art: (w.skills || {})[c.name] } : null;
  return wren ? [zen, wren] : [zen];
}
function placeWords(p) { return !p ? "" : /bedroom|room|kitchen|washroom/.test(p) ? `in the ${p}` : `${["porch", "lookout"].includes(p) ? "on the" : "in the"} ${p}`.replace("in the pond", "by the pond").replace("in the stream", "by the stream"); }

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
    case "talk_end": Journal.live("conversations", e); break;
    case "intent": case "did": addDeed(e); break;
    case "wren_intent": addWrenMind(e); break;
    case "talk_start": addDialogue(e); break;
    case "tried": S.tried = e; break;
    case "chat": if (S.pendingChat) { S.pendingChat.remove(); S.pendingChat = null; }
      chatLine({ role: "user", text: e.user }); chatLine({ role: "mind", text: e.text, tokens: e.tokens, asleep: e.asleep });
      Journal.live("conversations", e); break;
    case "tutor": tutorLine(e); break;
    case "npc": if (e.to === "you") chatLine({ role: "mind", who: e.name, text: e.text }); break;
    case "wren_says": addDialogue(e); Community.addFeed(e); break;
    case "wren_did": addDeed(e); Community.addFeed(e); break;
    case "wren_thought": addWrenThought(e); addWrenMind(e); Community.addFeed(e); break;
    case "ada_says": case "talk": addDialogue(e); Community.addFeed(e); break;
    case "happening": Community.addFeed(e);
      if (e.kind === "happening" && e.what === "rainbow") toast("🌈 A rainbow!"); break;
    case "story": Community.addStories([e]); Community.addFeed(e); toast(`📖 ${S.companion} tells ${SYNTH()} a bedtime story: “${e.title}”`, 6000); break;
    case "answer": addQA(e); addDialogue(e); Community.addFeed(e); Journal.live("conversations", e); break;
    case "created": Community.addFeed(e); if (e.creation) Community.addWorks([e.creation]); break;
    case "milestone": S.journey = [...(S.journey || []), e]; Community.addFeed(e); toast(`🌱 ${e.title}`, 6000); break;
    case "read": break;
    case "lesson": addLesson(e); break;
    case "metric": S.metrics.push(e.point); if (S.metrics.length > 20000) S.metrics.shift(); chartsDue(); break;
    case "assessment": S.assessments.push(e); chartsDue(); break;
    case "concepts": chartsDue(); break;
    case "published": toast(`🎓 ${SYNTH()} has a new brain (v${e.meta.version}, step ${big(e.meta.step)}).`); break;
    case "brain": toast(`🌍 ${SYNTH()} is now living with brain v${e.meta.version}.`); break;
    case "grew": toast(`🧠 ${SYNTH()}'s brain grew to ${e.layers} layers.`, 5000); break;
    case "phase": toast(e.phase === "night" ? `🌙 Night: ${SYNTH()} sleeps.` : `☀️ Day ${e.day}: ${SYNTH()} wakes up.`); break;
    case "error": banner(e.text); setTimeout(() => banner(""), 15000); break;
  }
}

// ================================================================== header
function renderHeader() {
  const w = MapView.st.world, a = S.academy, mind = w?.mind || {};
  if (w) {
    const sky = { clear: "☀️", cloudy: "☁️", rain: "🌧️", snow: "❄️" }[w.weather] || "";
    setText($("#clock"), `Day ${w.day} · ${w.season} · ${w.time} · ${sky} ${w.weather} ${Math.round(w.temperature)}°C`);
    const night = w.phase === "night", sc = S.settings["schedule.mode"];
    const left = dur(mind.phase_left);
    const txt = sc === "academy" ? "🎓 Study only: the world is paused" : sc === "world" ? (night ? `🌙 Asleep · wakes in ${left}` : `☀️ Awake · sleeps in ${left}`)
      : night ? `🌙 Asleep, studying · wakes in ${left}` : `☀️ Awake · sleeps in ${left}`;
    setText($("#sched"), txt); $("#sched").classList.toggle("night", night);
    setText($("#btnSleep"), night ? "Wake up" : "Go to sleep");
    $("#orb").classList.toggle("asleep", night);
    setText($("#kSelf"), pct(mind.self_rate));
  }
  setText($("#sub"), a.version ? `brain v${a.version} · ${a.layers} layers · ${big(a.params)} parameters · ${a.device || ""}` : "starting the Academy…");
  setText($("#kStage"), a.stage_name || "–");
  setText($("#kTokens"), a.tokens != null ? big(a.tokens) + " tokens" : "–");
  setText($("#kConcepts"), a.concepts?.accuracy != null ? pct(a.concepts.accuracy) : "–");
}
$("#btnHelp").onclick = () => $("#welcome").showModal();
$("#btnSleep").onclick = () => api(MapView.st.world?.phase === "night" ? "wake_now" : "sleep_now").catch((e) => toast(e.message));

$$("#nav button").forEach((b) => b.onclick = () => {
  S.view = b.dataset.view;
  $$("#nav button").forEach((x) => x.classList.toggle("on", x === b));
  $$(".view").forEach((v) => v.classList.toggle("on", v.id === `view-${S.view}`));
  renderAll(); if (S.view === "academy") drawCharts(); if (S.view === "health") pollHealth(true);
  MapView.st.dirty = true;
  if (W3.api) W3.api.pause(S.view !== "world" || document.hidden);
});

function renderAll() {
  renderHeader();
  if (S.view === "world") renderWorld();
  else if (S.view === "minds") renderMinds();
  else if (S.view === "thoughts") Journal.open("thoughts");
  else if (S.view === "talks") Journal.open("conversations");
  else if (S.view === "stories") Community.stories($("#stories"));
  else if (S.view === "gallery") renderGallery();
  else if (S.view === "academy") renderAcademy();
  else if (S.view === "concepts") renderConcepts();
  else if (S.view === "oracle") renderOracle();
  else if (S.view === "health") pollHealth();
}

// ================================================================== health view
let healthAt = 0;
async function pollHealth(force) {
  if (!force && performance.now() - healthAt < 4000) return;
  healthAt = performance.now();
  try { renderHealth(await (await fetch("/api/health")).json()); } catch (e) { /* the Hub will be back */ }
}
function perfTable(p, keep = 8) {
  if (!p || !p.timings) return '<div class="muted">No measurements yet.</div>';
  const rows = Object.entries(p.timings).sort((a, b) => b[1].share - a[1].share).slice(0, keep);
  return `<div class="muted" style="margin-bottom:6px">CPU ${p.cpu_percent}% of a core${p.gauges?.memory_mb ? ` · ${Math.round(p.gauges.memory_mb)} MB` : ""}</div>`
    + `<table class="perf"><tr><th>Activity</th><th>time share</th><th>avg ms</th><th>max ms</th><th>/s</th></tr>`
    + rows.map(([k, v]) => `<tr><td>${esc(k)}</td><td><span class="share" style="width:${Math.round(Math.min(1, v.share) * 40)}px"></span>${pct(v.share)}</td><td>${v.avg_ms}</td><td>${v.max_ms}</td><td>${v.per_s}</td></tr>`).join("")
    + `</table>` + (p.gauges ? `<div class="muted" style="margin-top:6px">${Object.entries(p.gauges).filter(([k]) => k !== "memory_mb").map(([k, v]) => `${esc(k.replace(/_/g, " "))}: <b>${esc(v)}</b>`).join(" · ")}</div>` : "");
}
function renderHealth(h) {
  setText($("#logPath"), `minds/${$("#name").textContent}/logs/`);
  const f = h.findings || [];
  setHTML($("#findings"), f.length ? f.map((x) => `<div class="finding ${x.level}"><b>${esc(x.where)}</b> · ${esc(x.text)}</div>`).join("")
    : '<div class="finding ok">Nothing looks wrong right now.</div>');
  const proc = (n) => { const p = h.processes?.[n]; return p ? `<div class="muted" style="margin-bottom:4px">${p.alive ? "running" : "stopped"} · pid ${p.pid}${p.restarts ? ` · <b style="color:var(--bad)">restarted ${p.restarts}×</b>` : ""}</div>` : ""; };
  setHTML($("#hAcademy"), proc("academy") + perfTable(h.perf?.academy));
  setHTML($("#hWorld"), proc("world") + perfTable(h.perf?.world));
  setHTML($("#hHub"), `<div class="muted" style="margin-bottom:4px">up ${dur(h.uptime_s)}</div>` + perfTable(h.perf?.hub));
  const g = (h.gpu || [])[0];
  setHTML($("#hGpu"), g ? dl([["Card", esc(g.name)], ["Busy", `${g.util_percent}%`], ["Memory", `${Math.round(g.mem_used_mb)} / ${Math.round(g.mem_total_mb)} MB`],
    ["Temperature", `${g.temp_c}°C`], ["Power", `${g.power_w} W`], ["Clock", `${g.sm_clock_mhz} MHz`], ["Driver", esc(g.driver)]])
    : '<dd class="muted">No NVIDIA GPU readings (nvidia-smi not found).</dd>');
  const b = S.clientPerf || h.browser || {};
  setHTML($("#hBrowser"), b.fps != null ? dl([["Frames per second", `${b.fps} <span class="muted">(worst gap ${b.worst_frame_gap_ms} ms)</span>`],
    ["Map drawing", `${b.draws_per_s}/s, ${b.draw_avg_ms} ms avg, ${b.draw_max_ms} ms max`],
    ["Frozen moments", `${b.longtasks} (${b.longtask_ms} ms total, longest ${b.longtask_max_ms} ms)`],
    ["Updates", `${b.msgs_per_s}/s, ${b.kb_per_s} KB/s, ${b.msg_avg_ms} ms each (max ${b.msg_max_ms})`],
    ["Screen", `${b.window} window, map ${b.canvas}, scale ${b.dpr}`], ["Script errors", `${b.js_errors}${b.last_error ? ` · ${esc(b.last_error)}` : ""}`]])
    : '<dd class="muted">Measuring… (the first numbers arrive after 15 seconds)</dd>');
  const box = $("#hLog"), stick = box.scrollTop + box.clientHeight >= box.scrollHeight - 20;
  setText(box, (h.log || []).join("\n") || "No warnings or errors so far.");
  if (stick) box.scrollTop = box.scrollHeight;
}

// ================================================================== world view
const NEED_LABEL = { energy: "Food", water: "Water", rest: "Rest", warmth: "Warmth", company: "Company", fun: "Fun", clean: "Clean" };
const SYNTH = () => S.name || "Zen";
const W3 = { api: null, ready: false };          // the 3D valley (world3d.js), when WebGL is available

function renderWorld() {
  const w = MapView.st.world; if (!w || !w.ada) return;   // before the World's first snapshot
  const a = w.ada, m = w.mind || {}, n = SYNTH();
  // the overlay
  const sky = { clear: "☀️", cloudy: "☁️", rain: "🌧️", storm: "⛈️", snow: "❄️", windy: "🌬️", fog: "🌫️" }[w.weather] || "";
  const house = w.env?.rooms?.house;
  setText($("#ovClock"), `Day ${w.day} · ${w.season} · ${w.time} · ${sky} ${Math.round(w.temperature)}°C${house != null ? ` · 🏠 ${Math.round(house)}°C` : ""}`);
  const sel = Community.st.byName[Community.st.selected];
  setText($("#ovPlace"), sel ? `${sel.name}: ${sel.place}` : `${n}: ${placeWords(a.place)}${a.dark ? " · dark" : ""}`);
  const sounds = w.env?.sounds || [];
  $("#ovHear").hidden = !sounds.length; setText($("#ovHear"), sounds.length ? "🔊 " + sounds.slice(0, 3).join(" · ") : "");
  Community.strip($("#mindStrip"));
  setHTML($("#mindCard"), sel ? Community.card(sel, false) : "");
  Community.feed($("#liveFeed"), ["wren_says", "ada_says", "talk", "answer", "created", "happening", "story", "milestone"], 40);
  renderHotbar(w);
  // the synth's own card below
  setText($("#adaTitle"), n);
  setText($("#adaWhere"), a.sleeping ? "asleep" : `${placeWords(a.place)}${a.carrying?.length ? " · carrying " + a.carrying.join(", ") : ""}${a.wet > 0.4 ? " · wet" : ""}`);
  setHTML($("#needs"), Object.entries(a.needs || {}).map(([k, v]) => {
    const c = v < 25 ? "var(--bad)" : v < 50 ? "var(--warn)" : "var(--good)";
    return `<div class="need"><span>${NEED_LABEL[k] || k}</span><div><i style="width:${Math.round(v)}%;background:${c}"></i></div><b>${Math.round(v)}</b></div>`;
  }).join(""));
  const it = m.intent || {};
  const badge = { self: '<span class="badge self">its own words</span>', needs: '<span class="badge needs">its needs</span>', you: '<span class="badge you">your idea</span>',
    companion: `<span class="badge you">${esc(S.companion)}'s words</span>` }[it.source] || "";
  setHTML($("#intent"), a.engaged || a.talking ? "💬 Talking" : a.sleeping ? "💤 Sleeping" : (m.plan ? badge + esc(m.plan) : esc(it.text || "…")));
  setText($("#intentWhy"), !a.sleeping && it.reason ? "Why: " + it.reason : "");
  setText($("#tried"), S.tried && it.source !== "self" && !a.sleeping ? `It tried to say: “${S.tried.text}”` : "");
  setText($("#selfPct"), `· ${pct(m.self_rate)} of its last ${m.decisions || 0} choices`);
  $("#selfBar").style.width = `${Math.round((m.self_rate || 0) * 100)}%`;
  setHTML($("#log"), (w.log || []).slice().reverse().map((l) => `<li>${esc(l)}</li>`).join(""));
}

function renderMinds() {
  Community.grid($("#mindsGrid"));
  Community.feed($("#communityFeed"));
  const wr = MapView.st.world?.wren || {};
  const words = wr.words_heard || [];
  setHTML($("#zenWords"), words.length ? words.map(([wd, n]) => `<span class="chip" title="${n}×">${esc(wd)}</span>`).join("")
    : `<span class="muted">None yet. ${esc(S.companion)} listens for real words in everything ${esc(SYNTH())} says.</span>`);
  setText($("#careNow"), { caretaker: `As a caretaker: ${S.companion} feeds ${SYNTH()}, brings water, dries it, puts it to bed, and talks it through everything.`,
    guide: `As a guide: ${S.companion} tells ${SYNTH()} what it needs and lets it do it ("You look thirsty. The sink is in the kitchen.").`,
    friend: `As a friend: ${SYNTH()} looks after itself; ${S.companion} helps when asked.` }[wr.care] || "");
  setHTML($("#wrenDiary"), (wr.diary || []).slice().reverse().map((d) => `<div class="item"><b class="t">Day ${d.day} · ${esc(d.time)}</b>${esc(d.text)}</div>`).join("")
    || '<div class="muted">Nothing yet.</div>');
  setText($("#jName"), SYNTH());
  const done = S.journey || [];
  const next = ["first word", "first phrase", "first sentence", "acts in its own words", "first conversation", "first painting", "first song"]
    .filter((x) => !done.some((m) => m.title.toLowerCase().includes(x.replace("acts in its own words", "chose in its own words"))));
  setHTML($("#journey"), done.map((m) => `<div class="ms"><b>${esc(m.title)}</b><span>${m.day ? "Day " + m.day + " · " : ""}${esc(m.detail)}</span></div>`).join("")
    + next.slice(0, 3).map((x) => `<div class="ms next"><b>Next: ${esc(x)}</b><span>not yet</span></div>`).join(""));
}
function renderGallery() { Community.gallery($("#gallery"), $("#galleryChips")); }
Community.onChange = () => { renderAll(); };
Community.st.onSelect = (name) => {
  if (W3.api && S.mode === "watch") W3.api.focusOn(name === SYNTH() ? "synth" : name);
  MapView.setFollow(name === SYNTH() ? "ada" : name); $("#follow").value = "all";
  if (S.mode === "you") setTalkTarget(name);
};

function renderHotbar(w) {
  const v = w.visitor;
  if (!v || S.mode !== "you") return;
  const slots = Array.from({ length: 6 }, (_, i) => v.carrying[i]);
  setHTML($("#hotbar"), slots.map((k, i) => `<div class="slot" title="${k || "empty"}"><small>${i + 1}</small>${k ? (GLYPH[k] || "❔") : ""}</div>`).join(""));
}

function tokHTML(tokens) {
  if (!tokens || !tokens.length) return '<span class="muted">(silence)</span>';
  return tokens.map(([s, p]) => `<span class="tk c${p < .05 ? 0 : p < .2 ? 1 : p < .45 ? 2 : p < .75 ? 3 : 4}" title="${(p * 100).toFixed(1)}%">${esc(s)}</span>`).join("");
}
function prepend(box, html, max = 120) {
  const d = document.createElement("div"); d.className = "item"; d.innerHTML = html; box.prepend(d);
  while (box.children.length > max) box.lastChild.remove();
}
function addThought(e) { prepend($("#thoughts"), `${tokHTML(e.tokens)}<div class="meta">brain v${e.brain ?? "?"} · ${new Date(e.t * 1000).toLocaleTimeString()}</div>`); }
function addDeed(e) {
  const when = `<span class="when">${new Date(e.t * 1000).toLocaleTimeString()}</span>`;
  if (e.kind === "wren_did") {
    prepend($("#diary"), `<span class="who wren">🪶 ${esc(S.companion)}</span>${e.ok === false ? "⚠️ " : ""}${esc(e.text)}${when}`, 200);
    $("#diary").firstChild.classList.add("wren");
    return;
  }
  if (e.kind === "intent") {
    const who = { self: "🗣️ its own words", needs: "🧭 its needs", you: "🙋 your idea", companion: `🪶 ${esc(S.companion)}'s words` }[e.source] || "";
    prepend($("#diary"), `<span class="who zen">✨ ${esc(SYNTH())}</span><b class="t">${who}</b>${esc(e.text)}${e.reason ? `<div class="meta">${esc(e.reason)}</div>` : ""}`, 200);
  } else prepend($("#diary"), `<span class="who zen">✨ ${esc(SYNTH())}</span>${e.ok ? "✅" : "⚠️"} ${esc(e.text)}${when}`, 200);
  $("#diary").firstChild.classList.add("zen");
}

// ------------------------------------------------------------------ Zen & Wren: only what they say to each other
function bubble(who, text, note = "") {
  const zen = who === SYNTH(), d = document.createElement("div");
  d.className = `bub ${zen ? "zen" : "wren"}${!text || text === "…" ? " quiet" : ""}`;
  d.innerHTML = `<b>${esc(who)}</b>${note ? `<span class="note">${esc(note)}</span>` : ""}<div>${!text || text === "…" ? "…" : esc(text)}</div>`;
  return d;
}
function addDialogue(e) {
  const box = $("#dialogue"), stick = box.scrollTop + box.clientHeight >= box.scrollHeight - 30, add = [];
  if (e.kind === "talk_start") {
    const d = document.createElement("div"); d.className = "sep";
    d.textContent = `💬 ${e.members?.[0] || ""} starts a conversation${e.topic ? ` · ${e.topic}` : ""} · ${new Date((e.t || Date.now() / 1000) * 1000).toLocaleTimeString()}`;
    add.push(d);
  } else if (e.kind === "talk") add.push(bubble(e.name, e.text));
  else if (e.kind === "ada_says") { if (e.text) add.push(bubble(SYNTH(), e.text, e.to && e.to !== S.companion ? `to ${e.to}` : "")); }
  else if (e.kind === "answer") { if (e.by === "you") return; add.push(bubble(SYNTH(), e.question, "asks"), bubble(S.companion, e.text, "answers")); }
  else if (e.kind === "wren_says") {
    if (!e.heard || ["talk", "answer", "visitor"].includes(e.why) || !e.text) return;   // talk lines arrive as "talk"
    add.push(bubble(S.companion, e.text, { name: "names something", narrate: "talks it through", care: "looks after Zen".replace("Zen", SYNTH()),
      fact: "tells", say: "" }[e.why] ?? ""));
  }
  for (const d of add) box.append(d);
  while (box.children.length > 300) box.firstChild.remove();
  if (stick) box.scrollTop = box.scrollHeight;
}
// ------------------------------------------------------------------ Wren's own mind: thoughts and decisions
function addWrenMind(e) {
  const when = `<div class="meta">${new Date(e.t * 1000).toLocaleTimeString()}</div>`;
  if (e.kind === "wren_thought") prepend($("#wthoughts"), `💭 <i>${esc(e.text)}</i>${when}`, 150);
  else if (e.kind === "wren_intent") prepend($("#wthoughts"), `<b class="t">➡️ decides: ${esc(e.text)}</b>${e.reason ? esc(e.reason) : ""}${when}`, 150);
}
function addWrenThought(e) { prepend($("#wrenThoughts"), `💭 ${esc(e.text)}<div class="meta">${new Date(e.t * 1000).toLocaleTimeString()}</div>`, 60); }
function chatLine(c) {
  const d = document.createElement("div");
  d.className = `msg ${c.role === "user" ? "user" : "mind"}`;
  d.innerHTML = c.role === "user" ? esc(c.text) : c.asleep ? `<span class="muted">💤 ${esc(SYNTH())} is asleep.</span>`
    : c.who ? `<b>${esc(c.who)}:</b> ${esc(c.text)}` : tokHTML(c.tokens || [[c.text, .5]]);
  $("#chat").append(d); while ($("#chat").children.length > 150) $("#chat").firstChild.remove();
  $("#chat").scrollTop = $("#chat").scrollHeight;
}
function tutorLine(e) {
  const last = [...$$(".msg.mind", $("#chat"))].reverse().find((m) => !m.querySelector(".tutor"));
  if (!last) return;
  const t = document.createElement("div"); t.className = "tutor"; t.innerHTML = `<b>${esc(S.companion)} suggests:</b> ${esc(e.text)}`;
  last.append(t); $("#chat").scrollTop = $("#chat").scrollHeight;
}
$("#deedsZen").onchange = (e) => $("#diary").classList.toggle("hide-zen", !e.target.checked);
$("#deedsWren").onchange = (e) => $("#diary").classList.toggle("hide-wren", !e.target.checked);
$$("#adaTabs button").forEach((b) => b.onclick = () => {
  $$("#adaTabs button").forEach((x) => x.classList.toggle("on", x === b));
  $$(".below .pane").forEach((p) => p.classList.toggle("on", p.id === `pane-${b.dataset.pane}`));
});

// ------------------------------------------------------------------ talking: to the synth, or to a villager you're near
S.talkTo = null;
function setTalkTarget(name) {
  S.talkTo = name && name !== SYNTH() ? name : null;
  setText($("#sayTo"), `to ${S.talkTo || SYNTH()}`);
}
async function sayToSynth(text) {
  S.pendingChat = document.createElement("div"); S.pendingChat.className = "msg mind pending"; S.pendingChat.textContent = "…";
  $("#chat").append(S.pendingChat);
  try { await api("chat", { text }); } catch (e) { toast(e.message); if (S.pendingChat) { S.pendingChat.remove(); S.pendingChat = null; } }
}
$("#sayForm").onsubmit = async (ev) => {
  ev.preventDefault();
  const text = $("#sayText").value.trim(); if (!text) return;
  $("#sayText").value = "";
  if (S.talkTo) {
    chatLine({ role: "user", text: `(to ${S.talkTo}) ${text}` });
    try { const r = await api("visitor", { action: "say", to: S.talkTo, text }); if (r && !/listening/.test(r)) toast(r); } catch (e) { toast(e.message); }
  } else sayToSynth(text);
  $("#sayText").blur();
};
$("#chatForm").onsubmit = async (ev) => {
  ev.preventDefault();
  const text = $("#chatText").value.trim(); if (!text) return;
  $("#chatText").value = "";
  sayToSynth(text);
};
$("#suggestForm").onsubmit = async (ev) => {
  ev.preventDefault();
  const text = $("#suggestText").value.trim(); if (!text) return;
  $("#suggestText").value = "";
  try { toast(await api("suggest", { text })); } catch (e) { toast(e.message); }
};

// ------------------------------------------------------------------ modes: watch, visit, add things
async function setMode(mode) {
  const was = S.mode;
  S.mode = mode;
  $$("#modes button[data-mode]").forEach((x) => x.classList.toggle("on", x.dataset.mode === mode));
  $("#mode-add").hidden = mode !== "add"; $("#mode-you").hidden = mode !== "you";
  $("#stage").classList.toggle("bigmap", mode === "add");
  if (mode !== "add") setTool(null);
  if (mode === "you" && !MapView.st.world?.visitor) { try { toast(await api("visitor", { action: "join" })); } catch (e) { toast(e.message); } }
  if (was === "you" && mode !== "you" && MapView.st.world?.visitor) { try { await api("visitor", { action: "leave" }); } catch { /* fine */ } setTalkTarget(null); }
  if (W3.api) { W3.api.setMode(mode === "you" ? "visit" : "watch"); if (mode !== "you") W3.api.focusOn("synth"); }
  MapView.setFollow(mode === "you" ? "you" : "all"); $("#follow").value = mode === "you" ? "you" : "all";
}
$$("#modes button[data-mode]").forEach((b) => b.onclick = () => setMode(b.dataset.mode));
$("#uiToggle").onclick = () => $("#stage").classList.toggle("bare");
$("#mapBig").onclick = () => $("#stage").classList.toggle("bigmap");
$("#follow").onchange = (e) => MapView.setFollow(e.target.value);
MapView.setFollow("all");
function setTool(t) {
  S.tool = t; MapView.setTool(t);
  $$("#palette button").forEach((b) => b.classList.toggle("on", b.dataset.kind === t));
  setText($("#addHint"), t ? (t === "erase" ? "Click things on the map to remove them." : `Click open ground on the map to place the ${t}. Click it again to stop.`)
    : "Choose something, then click the map to put it there. Books and signs ask what they should say.");
}
for (const k of [...PLACEABLE, "erase"]) {
  const b = document.createElement("button"); b.dataset.kind = k;
  b.textContent = k === "erase" ? "🧽" : GLYPH[k]; b.title = k === "erase" ? "Erase" : k;
  b.onclick = () => setTool(S.tool === k ? null : k);
  $("#palette").append(b);
}
for (const k of PORTABLE) {
  const b = document.createElement("button"); b.textContent = GLYPH[k]; b.title = `Take a new ${k}`;
  b.onclick = async () => {
    if (!MapView.st.world?.visitor) await api("visitor", { action: "join" });
    const text = k === "book" || k === "picture book" ? (prompt(`Write the book's words (${SYNTH()} will read and study them):`) || "") : "";
    try { toast(await api("visitor", { action: "hold", kind: k, text })); } catch (e) { toast(e.message); }
  };
  $("#holdPalette").append(b);
}
MapView.st.onClick = async ({ x, y }) => {
  if (S.mode === "add" && S.tool) {
    let text = "";
    if (S.tool === "sign") { text = prompt("What should the sign say?") || ""; if (!text) return; }
    if (S.tool === "book" || S.tool === "picture book") text = prompt(`Write the book's words (empty: ${S.companion} writes one when it is read):`) || "";
    try { toast(await api("place", { kind: S.tool, x, y, text })); } catch (e) { toast(e.message); }
    return;
  }
  const w = MapView.st.world; if (!w) return;
  const who = [w.ada, ...(w.people || [])].find((b) => b && Math.abs(b.x - x) + Math.abs(b.y - y) <= 1);
  if (who) { Community.st.selected = who.name; Community.st.onSelect(who.name); renderAll(); return; }
  if (W3.api && S.mode === "watch") W3.api.focusOn("overview");
  const here = MapView.entitiesAt(x, y).map((e) => GLYPH[e.kind] + " " + (e.kind === "plant" ? `${e.crop} plant (${["seed", "sprout", "young", "flowering", "ripe"][Math.min(4, Math.floor(e.stage || 0))]})` : e.kind)
    + (e.contents?.length ? `: ${e.contents.join(", ")}` : "") + (e.lit ? " (lit)" : ""));
  const names = w.region_names || [], place = names[w.regions?.[y]?.[x]] ?? w.regions?.[y]?.[x];
  toast([place && `The ${place}`, ...here].filter(Boolean).join(" · ") || "Nothing here.");
};
// the 2D map keeps keyboard walking when there is no 3D view
const KEYS = { ArrowUp: "north", w: "north", ArrowDown: "south", s: "south", ArrowLeft: "west", a: "west", ArrowRight: "east", d: "east",
               f: "take", r: "drop", g: "give", h: "hug" };
MapView.canvas.addEventListener("keydown", async (e) => {
  if (W3.api) return;
  const k = e.key.length === 1 ? e.key.toLowerCase() : e.key, act = KEYS[k];
  if (!act || !MapView.st.world?.visitor) return;
  e.preventDefault();
  try { const r = await api("visitor", { action: act }); if (r) toast(r); } catch (err) { toast(err.message); }
});

// ------------------------------------------------------------------ the 3D valley
let moveBusy = false;
window.addEventListener("world3d", (ev) => {
  const api3 = ev.detail;
  if (!api3) { $("#stage").classList.add("no3d"); return; }
  try {
    api3.init($("#stage3d"), { quality: localStorage.getItem("quality3d") || "high" });
  } catch (e) { console.warn("3D view failed:", e); $("#stage").classList.add("no3d"); return; }
  W3.api = api3; W3.ready = true;
  if (MapView.st.world?.terrain) api3.full(MapView.st.world.full ? MapView.st.world : { ...MapView.st.world, full: true, ents: [...MapView.st.ents.values()] });
  api3.setMode(S.mode === "you" ? "visit" : "watch");
  api3.onMove = (fx, fy, facing) => {
    if (moveBusy) return;
    moveBusy = true;
    api("visitor", { action: "pos", fx, fy, facing }).catch(() => {}).finally(() => { moveBusy = false; });
  };
  api3.onAction = async (a) => {
    try {
      if (a.type === "interact") {
        const r = await api("visitor", { action: "interact", target: a.target });
        if (r && r.talk_to) { setTalkTarget(r.talk_to); $("#sayText").focus(); }
        else if (r) toast(r, 4200);
      } else if (a.type === "talk") { $("#sayText").focus(); }
      else if (a.type === "give" || a.type === "hug" || a.type === "drop") { const r = await api("visitor", { action: a.type }); if (r) toast(r); }
      else if (a.type === "slot") { toast(`Slot ${a.index + 1}`); }
    } catch (e) { toast(e.message); }
  };
  api3.onPick = (info) => {
    if (info.kind === "person" || info.kind === "synth") {
      const name = info.kind === "synth" ? SYNTH() : info.name;
      Community.st.selected = name; renderAll();
    } else if (info.kind === "entity") {
      const e = MapView.st.ents.get(info.id);
      if (e?.work) Community.showWork(e.work);
      else if (e) toast(`${GLYPH[e.kind] || ""} ${e.kind === "plant" ? e.crop + " plant" : e.kind}${e.lit ? " (lit)" : ""}${e.temp != null && e.temp > 35 ? ` · ${Math.round(e.temp)}°C` : ""}`
        + `${e.contents?.length ? ": " + e.contents.join(", ") : ""}${e.text ? ": " + e.text : ""}`, 4200);
    }
  };
  document.addEventListener("visibilitychange", () => api3.pause(document.hidden || S.view !== "world"));
});

// ================================================================== academy view
function dl(rows) { return rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join(""); }
function renderAcademy() {
  const a = S.academy;
  if (!a.stages) { setHTML($("#acStatus"), "The Academy is starting…"); return; }
  const st = $("#acStatus"); st.className = "status " + (a.paused ? "off" : "on");
  setText(st, a.paused ? `Resting: ${a.pause_reason}` : `Studying (${a.intensity}) · ${big(a.tps)} tokens/s`);
  setHTML($("#ladder"), a.stages.map((n, i) => `<span class="${i < a.stage ? "done" : i === a.stage ? "now" : ""}">${n}</span>`).join(""));
  setText($("#stageBlurb"), a.stage_blurb);
  setHTML($("#acFacts"), dl([
    ["Brain", `${big(a.params)} parameters (${big(a.trunk_params)} outside the word table) · ${a.layers} layers × ${a.d_model} wide · ${a.seq_len}-token memory${a.growths ? ` · grew ${a.growths}×` : ""}`],
    ["Device", `${esc(a.device)} · ${a.precision} · ${a.tokenizer} tokens`],
    ["Progress", `step ${big(a.step)} · ${big(a.tokens)} tokens studied`],
    ["Loss", `${a.loss?.toFixed(3) ?? "–"} training · ${a.val?.toFixed(3) ?? "–"} held-out · ${a.bpb?.toFixed(3) ?? "–"} bits per byte`],
    ["Concepts", a.concepts?.accuracy != null ? `${pct(a.concepts.accuracy)} of ${a.concepts.n} facts (chance 25%)` : "not tested yet"],
    ["Published", a.last_publish ? `brain v${a.version}, ${ago(a.last_publish)}` : `brain v${a.version}`],
    ["Stability", a.skipped ? `${a.skipped} unstable steps skipped` : "no unstable steps"],
  ]));
  const mix = a.mix || {}, names = { fineweb: "Web text (FineWeb)", lessons: `${S.companion}'s lessons`, journal: "Its life (journal)", concepts: "Concept drills" };
  setHTML($("#mix"), Object.keys(names).map((k) => `<div class="bar"><span>${names[k]}</span><div><i style="width:${Math.round((mix[k] || 0) * 100)}%"></i></div><b>${pct(mix[k] || 0)}</b></div>`).join("")
    + `<div class="muted" style="margin-top:4px">${big(a.pools?.lessons_added)} lessons and ${big(a.pools?.journal_added)} journal entries received · ${a.pools?.facts ?? "–"} facts known to the graph</div>`);
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

// charts
let chartTimer;
function chartsDue() { if (!chartTimer) chartTimer = setTimeout(() => { chartTimer = null; drawCharts(); }, 1500); }
function series(key) {
  const out = []; for (const p of S.metrics) if (p[key] != null) out.push([p.step, p[key]]);
  if (out.length > 600) { const k = Math.ceil(out.length / 600); return out.filter((_, i) => i % k === 0 || i === out.length - 1); }
  return out;
}
function chart(cv, lines, opt = {}) {
  const dpr = devicePixelRatio || 1, W = cv.clientWidth * dpr, H = cv.clientHeight * dpr; if (!W) return;
  cv.width = W; cv.height = H; const g = cv.getContext("2d"), pts = lines.flatMap((l) => l.data);
  g.font = `${10 * dpr}px system-ui`; g.fillStyle = css("--muted");
  if (pts.length < 2) { g.fillText(`waiting for ${SYNTH()} to study…`, 8 * dpr, H / 2); return; }
  let x0 = Math.min(...pts.map((p) => p[0])), x1 = Math.max(...pts.map((p) => p[0]));
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
  const c = (k) => $(`canvas[data-chart=${k}]`), A = css("--accent"), B = css("--warn"), G = css("--good"), P = css("--accent-2");
  chart(c("loss"), [{ data: series("loss_ema"), color: A }, { data: series("val"), color: B, dots: true }]);
  chart(c("concepts"), [{ data: series("concepts"), color: G, dots: true }], { min: 0, max: 1, chance: .25, fmt: (v) => pct(v) });
  chart(c("bpb"), [{ data: series("bpb"), color: P }]);
  chart(c("tps"), [{ data: series("tps"), color: A }], { min: 0 });
  const as = S.assessments;
  chart(c("assess"), ["spelling", "grammar", "coherence", "meaning"].map((k, i) => ({ data: as.map((a) => [a.step, a[k]]), color: [A, B, G, P][i], dots: true })), { min: 0, max: 10, fmt: (v) => v.toFixed(0) });
  const last = as[as.length - 1];
  setText($("#assessNote"), last?.note ? `${S.companion} (spelling · grammar · coherence · meaning): “${last.note}”` : "");
}
addEventListener("resize", () => drawCharts());

// ================================================================== concepts view
const REL = { "is a": "What it is", color: "Colors", is: "What it's like", "made of": "What it's made of", "used for": "What it's for", "found in": "Where it is", can: "What it can do" };
function renderConcepts() {
  const c = S.concepts || {};
  const bars = (obj, label) => Object.entries(obj || {}).map(([k, v]) => `<div class="bar"><span>${esc(label(k))}</span><div><i style="width:${Math.round(v * 100)}%;background:${v > .5 ? "var(--good)" : v > .3 ? "var(--accent)" : "var(--warn)"}"></i></div><b>${pct(v)}</b></div>`).join("");
  setHTML($("#byRel"), bars(c.by_relation, (k) => REL[k] || k) || '<div class="muted">Not tested yet.</div>');
  setHTML($("#bySrc"), bars(c.by_source, (k) => k === "built-in" ? "Facts of the homestead" : `Taught by ${S.companion}`));
  const q = S.oracle.queued || [];
  setText($("#teachQueue"), q.length ? `Waiting to be taught: ${q.join(", ")}` : S.oracle.teaching ? `${S.companion} is writing a lesson…` : "");
  const filter = $("#factFilter").value, term = $("#factSearch").value.toLowerCase();
  const rows = (c.results || []).filter((r) => (filter === "all" || (filter === "wrong" && !r.ok) || (filter === "right" && r.ok) || (filter === "oracle" && r.src === "oracle"))
    && (!term || `${r.s} ${r.r} ${r.o}`.includes(term)));
  setHTML($("#factRows"), rows.slice(0, 400).map((r) => `<tr><td class="${r.ok ? "ok" : "no"}">${r.ok ? "✓" : "✗"}</td><td>${esc(r.s)} <span class="muted">${esc(r.r)}</span> ${esc(r.o)}</td><td>${r.ok ? "" : esc(r.chose)}</td><td class="muted">${esc(r.src)}</td></tr>`).join(""));
}
$("#factFilter").onchange = renderConcepts; $("#factSearch").oninput = renderConcepts;
$("#teachForm").onsubmit = async (ev) => {
  ev.preventDefault(); const topic = $("#teachText").value.trim(); if (!topic) return;
  try { toast(await api("oracle_teach", { topic })); $("#teachText").value = ""; } catch (e) { toast(e.message); }
};

// ================================================================== oracle view
function renderOracle() {
  const o = S.oracle, st = $("#orStatus"), b = o.builtin || {}, builtin = (o.backend || S.settings["oracle.backend"]) === "builtin";
  $("#orBuiltinRow").hidden = !builtin; $("#orOllamaRow").hidden = builtin;
  const setup = builtin && (b.status === "downloading" || b.status === "starting");
  $("#orMeter").hidden = !setup; $("#orBar").style.width = `${Math.round((b.progress || 0) * 100)}%`;
  const ok = o.enabled && !!o.active;
  st.className = "status " + (ok ? "on" : "off");
  const W = S.companion;
  setText(st, !o.enabled ? `${W}'s language model is switched off (Settings); ${W} lives by simple rules.`
    : setup ? `${b.detail || `Getting ${W}'s mind ready`}…`
    : o.error ? o.error
    : ok ? `${o.active} · ${o.lessons} lesson${o.lessons === 1 ? "" : "s"} written this session${o.teaching ? " · writing one now" : ""}`
    : builtin ? `${W}'s mind is getting ready…` : "No Ollama model chosen.");
  const sel = $("#orModel"), sig = (o.models || []).map((m) => m.name).join("|") + o.model;
  if (sel._sig !== sig && document.activeElement !== sel) {
    sel._sig = sig;
    sel.innerHTML = (o.models || []).length ? o.models.map((m) => `<option value="${esc(m.name)}">${esc(m.name)}${m.parameter_size ? " · " + esc(m.parameter_size) : ""}</option>`).join("") : "<option value=''>No Ollama models found</option>";
    sel.value = o.model || "";
  }
}
$("#orModel").onchange = (e) => api("set", { key: "oracle.model", value: e.target.value }).catch((er) => toast(er.message));
$("#btnModels").onclick = async () => { try { S.oracle = await api("models"); renderOracle(); } catch (e) { toast(e.message); } };
$("#askForm").onsubmit = async (ev) => {
  ev.preventDefault(); const q = $("#askText").value.trim(); if (!q) return;
  setHTML($("#askOut"), `<div class="item muted">${esc(S.companion)} is thinking…</div>`);
  try {
    const a = await api("oracle_ask", { question: q });
    setHTML($("#askOut"), `<div class="item">${esc(a)}<div class="row" style="margin-top:6px"><button id="learnIt">🎓 Let ${esc(SYNTH())} study this</button></div></div>`);
    $("#learnIt").onclick = async () => { toast(await api("oracle_learn", { question: q, answer: a })); $("#learnIt").disabled = true; };
  } catch (e) { setHTML($("#askOut"), `<div class="item">${esc(e.message)}</div>`); }
};
function addLesson(e) {
  const qa = (e.qa || []).map(([q, a]) => `\n<b>Q:</b> ${esc(q)}\n<b>A:</b> ${esc(a)}`).join("");
  const facts = (e.facts || []).length ? `<div class="meta">facts: ${e.facts.map((f) => esc(`${f.s} ${f.r} ${f.o}`)).join(" · ")}${e.new_facts ? ` (${e.new_facts} new)` : ""}</div>` : "";
  prepend($("#lessons"), `<b class="t">${e.priority ? "⭐ " : ""}${esc(e.topic)}</b>${esc(e.text)}${qa}${facts}`, 60);
}
function addQA(e) { prepend($("#qa"), `<b class="t">${e.by === "you" ? "You asked" : esc(SYNTH()) + " asked"}</b><i>${esc(e.question)}</i>\n${esc(e.text)}`, 60); }

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
    try { await api("set", { key: el.dataset.set, value: v }); } catch (e) { toast(e.message); }
    setTimeout(() => delete el._busy, 500);
  });
}
for (const r of $$("input[name=schedule]")) r.onchange = () => api("set", { key: "schedule.mode", value: r.value }).then(() => toast("Schedule changed.")).catch((e) => toast(e.message));
$("#dayGentle").onchange = (e) => api("set", { key: "schedule.day_training", value: e.target.checked ? "gentle" : "pause" }).catch((er) => toast(er.message));

connect();


// ================================================================== Thoughts and Conversations: everything, whole
// The Hub keeps every thought and conversation of the synth on disk; these tabs read it a page at a time
// (newest first) and add new ones as they happen.
const Journal = (() => {
  const K = {
    thoughts: { list: "#thList", more: "#thMore", end: "#thEnd", search: "#thSearch", noun: "thoughts" },
    conversations: { list: "#tkList", more: "#tkMore", end: "#tkEnd", search: "#tkSearch", noun: "conversations" },
  };
  const st = { thoughts: { loaded: false, oldest: null, busy: false, q: "" }, conversations: { loaded: false, oldest: null, busy: false, q: "", who: "" } };
  const clock = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const dayKey = (e) => `Day ${e.day ?? "?"}`;
  const whoName = (w) => w === "you" ? "you" : w === "companion" ? S.companion : w;
  const CHAT_GAP = 600;                                   // your messages this close together are one conversation

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

  // ---- thoughts
  function thoughtEl(e) {
    const d = document.createElement("article"); d.className = "arch-item thought";
    const shade = $("#thShade").checked && e.tokens?.length;
    d.innerHTML = `<div class="arch-text">${shade ? tokHTML(e.tokens) : esc(e.text || "") || '<span class="muted">(silence)</span>'}</div>
      <div class="arch-meta">${esc(e.time || "")}${e.time ? " · " : ""}${clock(e.t)} · brain v${e.brain ?? "?"}</div>`;
    d._e = e;
    return d;
  }

  // ---- conversations
  function lineEl(who, text) {
    const zen = who === SYNTH(), quiet = !text || text === "…";
    const d = document.createElement("div");
    d.className = `bub ${zen ? "zen" : who === "you" ? "you" : "wren"}${quiet ? " quiet" : ""}`;
    d.innerHTML = `<b>${esc(who === "you" ? "You" : who)}</b><div>${quiet ? "…" : esc(text)}</div>`;
    return d;
  }
  function talkEl(e) {
    const d = document.createElement("article"); d.className = `arch-item talk with-${e.with === "you" ? "you" : "wren"}`;
    const what = e.kind === "question" ? `${esc(SYNTH())} asks ${esc(S.companion)}` : e.with === "you" ? `With you` : `With ${esc(whoName(e.with))}`;
    const topic = (e.topic || "").replace(/^(talk|chat) (with|to) \S+ (about )?/i, "").replace(/^about /i, "");
    d.innerHTML = `<header><b>${what}</b>${topic ? `<span class="muted"> · about ${esc(topic)}</span>` : ""}
      <span class="arch-meta">${esc(e.time || "")}${e.time ? " · " : ""}${clock(e.t)}</span></header><div class="dialogue"></div>`;
    const box = d.querySelector(".dialogue");
    for (const [who, text] of e.lines || []) box.append(lineEl(who, text));
    d._e = e;
    return d;
  }

  const make = (kind, e) => kind === "thoughts" ? thoughtEl(e) : talkEl(e);
  const matches = (kind, e) => {
    const s = st[kind];
    if (kind === "conversations" && s.who && e.with !== s.who) return false;
    if (!s.q) return true;
    const text = kind === "thoughts" ? e.text || "" : (e.lines || []).map((l) => l[1] || "").join(" ");
    return text.toLowerCase().includes(s.q.toLowerCase());
  };

  // your messages a few minutes apart read as one conversation
  function mergeChat(box, e, atTop) {
    if (e.with !== "you") return false;
    const items = [...box.querySelectorAll(".arch-item.talk")];
    const near = atTop ? items[0] : items.at(-1);
    if (!near || near._e.with !== "you") return false;
    const gap = atTop ? e.t - near._e.t : (near._e.t0 ?? near._e.t) - e.t;
    if (gap < 0 || gap > CHAT_GAP || dayKey(near._e) !== dayKey(e)) return false;
    const dl = near.querySelector(".dialogue"), els = (e.lines || []).map(([w, t]) => lineEl(w, t));
    if (atTop) { dl.append(...els); near._e = { ...near._e, t: e.t, lines: [...near._e.lines, ...e.lines] }; }
    else { dl.prepend(...els); near._e = { ...near._e, t0: e.t, lines: [...e.lines, ...near._e.lines] }; }
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
    const p = new URLSearchParams({ limit: kind === "thoughts" ? 120 : 40 });
    if (s.oldest != null) p.set("before", s.oldest);
    if (s.q) p.set("q", s.q);
    if (s.who) p.set("who", s.who);
    try {
      const r = await fetch(`/api/archive/${kind}?${p}`).then((x) => x.json());
      for (const e of r.items || []) { add(kind, e, false); s.oldest = e.t; }
      $(k.more).hidden = !r.more;
      const n = $(k.list).querySelectorAll(".arch-item").length;
      setText($(k.end), r.more ? "" : n ? `That's all of them${s.q ? ` with “${s.q}”` : ""}.` :
        s.q ? `None with “${s.q}”.` : kind === "thoughts" ? `No thoughts yet. They start once ${SYNTH()} is awake.` : `No conversations yet.`);
      s.loaded = true;
    } catch (err) { setText($(k.end), `Couldn't load: ${err.message}`); }
    s.busy = false;
  }

  function open(kind) { if (!st[kind].loaded) load(kind, true); }

  function live(kind, ev) {
    if (!st[kind].loaded) return;                         // loaded with everything when the tab opens
    let e;
    const ws = MapView.st.world || {}, when = { t: ev.t || Date.now() / 1000, day: ws.day, time: ws.time };
    if (kind === "thoughts") { if (!(ev.text || "").trim()) return; e = { ...when, text: ev.text, tokens: ev.tokens, brain: ev.brain }; }
    else if (ev.kind === "talk_end") {
      if (!ev.lines?.length) return;
      const other = (ev.members || []).find((m) => m !== SYNTH()) || S.companion;
      e = { ...when, with: other === S.companion ? "companion" : other, kind: "talk", topic: ev.topic || "", lines: ev.lines };
    } else if (ev.kind === "chat") {
      if (ev.asleep || !(ev.user || ev.text)) return;
      e = { ...when, with: "you", kind: "chat", lines: [["you", ev.user || ""], [SYNTH(), ev.text || ""]] };
    } else if (ev.kind === "answer" && ev.by === SYNTH()) {
      e = { ...when, with: "companion", kind: "question", lines: [[SYNTH(), ev.question || ""], [S.companion, ev.text || ""]] };
    } else return;
    if (!matches(kind, e)) return;
    const box = $(K[kind].list);
    const stick = box.getBoundingClientRect().top > -40;  // reading older entries further down: don't jump
    add(kind, e, true);
    if (!stick) window.scrollBy(0, box.firstElementChild?.nextElementSibling?.offsetHeight || 0);
    setText($(K[kind].end), $(K[kind].more).hidden ? "That's all of them." : "");
  }

  // controls
  let timers = {};
  for (const kind of ["thoughts", "conversations"]) {
    const k = K[kind];
    $(k.more).onclick = () => load(kind, false);
    $(k.search).oninput = (ev) => { clearTimeout(timers[kind]); timers[kind] = setTimeout(() => { st[kind].q = ev.target.value.trim(); load(kind, true); }, 300); };
  }
  $("#thShade").onchange = () => { for (const el of $$("#thList .arch-item")) { const n = thoughtEl(el._e); n.dataset.day = el.dataset.day; el.replaceWith(n); } };
  $$("#tkWho button").forEach((b) => b.onclick = () => {
    $$("#tkWho button").forEach((x) => x.classList.toggle("on", x === b));
    st.conversations.who = b.dataset.who; load("conversations", true);
  });
  return { open, live, load, st };
})();
