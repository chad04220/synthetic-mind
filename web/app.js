"use strict";
// Ada's dashboard. One WebSocket brings an initial picture and then small updates 4 times a second;
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
function connect() {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  ws.onmessage = (m) => {
    let msg; try { msg = JSON.parse(m.data); } catch { return; }
    try { msg.type === "init" ? init(msg) : tick(msg); } catch (e) { console.error(e); }
  };
  ws.onopen = () => banner("");
  ws.onclose = () => { banner("Lost contact with Ada's Hub. Reconnecting…"); setTimeout(connect, 1500); };
}

function init(m) {
  S.settings = m.settings; S.academy = m.academy || {}; S.metrics = m.metrics || []; S.assessments = m.assessments || [];
  S.concepts = m.concepts || {}; S.oracle = m.oracle || {}; S.feeds = m.feeds || {};
  setText($("#name"), m.name); document.title = m.name;
  MapView.setWorld(m.world);
  $("#chat").innerHTML = ""; $("#thoughts").innerHTML = ""; $("#diary").innerHTML = ""; $("#village").innerHTML = "";
  $("#lessons").innerHTML = ""; $("#qa").innerHTML = "";
  for (const c of S.feeds.chat || []) {
    if (c.kind === "chatline") chatLine(c);
    else if (c.kind === "chat") { chatLine({ role: "user", text: c.user }); chatLine({ role: "mind", text: c.text, tokens: c.tokens, asleep: c.asleep }); }
    else if (c.kind === "tutor") tutorLine(c);
  }
  for (const e of S.feeds.thought || []) addThought(e);
  for (const e of S.feeds.deed || []) addDeed(e);
  for (const e of [...(S.feeds.npc || []), ...(S.feeds.oracle || [])].sort((a, b) => a.t - b.t)) addVillage(e);
  for (const e of S.feeds.lesson || []) addLesson(e);
  for (const e of S.feeds.oracle || []) addQA(e);
  for (const e of m.events || []) if (e.kind === "error") banner(e.text);
  syncSettings(); renderAll(); drawCharts();
}

function tick(m) {
  if (m.world) { m.world.full ? MapView.setWorld(m.world) : MapView.applyDelta(m.world); }
  if (m.academy) S.academy = m.academy;
  if (m.settings) { S.settings = m.settings; syncSettings(); }
  if (m.oracle) S.oracle = m.oracle;
  if (m.concepts) S.concepts = m.concepts;
  for (const e of m.events || []) onEvent(e);
  renderAll();
}

function onEvent(e) {
  switch (e.kind) {
    case "thought": addThought(e); break;
    case "intent": case "did": addDeed(e); break;
    case "tried": S.tried = e; break;
    case "chat": if (S.pendingChat) { S.pendingChat.remove(); S.pendingChat = null; }
      chatLine({ role: "user", text: e.user }); chatLine({ role: "mind", text: e.text, tokens: e.tokens, asleep: e.asleep }); break;
    case "tutor": tutorLine(e); break;
    case "npc": addVillage(e); break;
    case "oracle": addVillage(e); addQA(e); break;
    case "read": case "fact": addVillage(e); break;
    case "lesson": addLesson(e); break;
    case "metric": S.metrics.push(e.point); if (S.metrics.length > 20000) S.metrics.shift(); chartsDue(); break;
    case "assessment": S.assessments.push(e); chartsDue(); break;
    case "concepts": chartsDue(); break;
    case "published": toast(`🎓 Ada has a new brain (v${e.meta.version}, step ${big(e.meta.step)}).`); break;
    case "brain": toast(`🌍 Ada is now living with brain v${e.meta.version}.`); break;
    case "grew": toast(`🧠 Her brain grew to ${e.layers} layers.`, 5000); break;
    case "phase": toast(e.phase === "night" ? "🌙 Night: Ada sleeps and studies." : `☀️ Day ${e.day}: Ada wakes up.`); break;
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
    setText($("#btnSleep"), night ? "Wake her up" : "Put her to bed");
    $("#orb").classList.toggle("asleep", night);
    setText($("#kSelf"), pct(mind.self_rate));
  }
  setText($("#sub"), a.version ? `brain v${a.version} · ${a.layers} layers · ${big(a.params)} parameters · ${a.device || ""}` : "starting the Academy…");
  setText($("#kStage"), a.stage_name || "–");
  setText($("#kTokens"), a.tokens != null ? big(a.tokens) + " tokens" : "–");
  setText($("#kConcepts"), a.concepts?.accuracy != null ? pct(a.concepts.accuracy) : "–");
}
$("#btnSleep").onclick = () => api(MapView.st.world?.phase === "night" ? "wake_now" : "sleep_now").catch((e) => toast(e.message));

$$("#nav button").forEach((b) => b.onclick = () => {
  S.view = b.dataset.view;
  $$("#nav button").forEach((x) => x.classList.toggle("on", x === b));
  $$(".view").forEach((v) => v.classList.toggle("on", v.id === `view-${S.view}`));
  renderAll(); if (S.view === "academy") drawCharts();
  MapView.st.dirty = true;
});

function renderAll() {
  renderHeader();
  if (S.view === "world") renderWorld();
  else if (S.view === "academy") renderAcademy();
  else if (S.view === "concepts") renderConcepts();
  else if (S.view === "oracle") renderOracle();
}

// ================================================================== world view
const NEED_LABEL = { energy: "Food", water: "Water", rest: "Rest", warmth: "Warmth", company: "Company", fun: "Fun" };
function renderWorld() {
  const w = MapView.st.world; if (!w) return;
  const a = w.ada, m = w.mind || {};
  setText($("#adaWhere"), a.sleeping ? "asleep" : `${a.place === "home" ? "at home" : "in the " + a.place}${a.carrying?.length ? " · carrying " + a.carrying.join(", ") : ""}`);
  setHTML($("#needs"), Object.entries(a.needs || {}).map(([k, v]) => {
    const c = v < 25 ? "var(--bad)" : v < 50 ? "var(--warn)" : "var(--good)";
    return `<div class="need"><span>${NEED_LABEL[k] || k}</span><div><i style="width:${Math.round(v)}%;background:${c}"></i></div><b>${Math.round(v)}</b></div>`;
  }).join(""));
  const it = m.intent || {};
  const badge = { self: '<span class="badge self">her own words</span>', needs: '<span class="badge needs">her needs</span>', you: '<span class="badge you">your idea</span>' }[it.source] || "";
  setHTML($("#intent"), a.sleeping ? "💤 Sleeping" : (m.plan ? badge + esc(m.plan) : esc(it.text || "…")));
  setText($("#intentWhy"), !a.sleeping && it.reason ? "Why: " + it.reason : "");
  setText($("#tried"), S.tried && it.source !== "self" && !a.sleeping ? `She tried to say: “${S.tried.text}”` : "");
  setText($("#selfPct"), `· ${pct(m.self_rate)} of her last ${m.decisions || 0} choices`);
  $("#selfBar").style.width = `${Math.round((m.self_rate || 0) * 100)}%`;
  setHTML($("#log"), (w.log || []).slice().reverse().map((l) => `<li>${esc(l)}</li>`).join(""));
  setText($("#mapLabel"), m.brain ? `Ada · brain v${m.brain}` : "Ada");
  const v = w.visitor;
  setText($("#btnJoin"), v ? "Leave the world" : "Join the world");
  $("#btnJoin").classList.toggle("primary", !v);
  setText($("#youCarry"), v ? (v.carrying.length ? v.carrying.join(", ") : "nothing") : "(join first)");
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
  if (e.kind === "intent") {
    const who = { self: "🗣️ her own words", needs: "🧭 her needs", you: "🙋 your idea" }[e.source] || "";
    prepend($("#diary"), `<b class="t">${who}</b>${esc(e.text)}${e.reason ? `<div class="meta">${esc(e.reason)}</div>` : ""}`);
  } else prepend($("#diary"), `${e.ok ? "✅" : "⚠️"} ${esc(e.text)}<div class="meta">${e.reward != null ? "reward " + e.reward : ""}</div>`);
}
function addVillage(e) {
  const html = e.kind === "npc" ? `<b class="t">${esc(e.name)}</b>${esc(e.text)}${e.ada ? `<div class="meta">Ada said: ${esc(e.ada)}</div>` : ""}`
    : e.kind === "oracle" ? `<b class="t">🔮 The Oracle${e.by === "you" ? " (asked by you)" : ""}</b><i>${esc(e.question)}</i>\n${esc(e.text)}`
    : e.kind === "read" ? `<b class="t">📘 Ada read</b>${esc(e.text)}` : `<b class="t">🔭 Ada learned</b>${esc(e.text)}`;
  prepend($("#village"), html, 80);
}
function chatLine(c) {
  const d = document.createElement("div");
  d.className = `msg ${c.role === "user" ? "user" : "mind"}`;
  d.innerHTML = c.role === "user" ? esc(c.text) : c.asleep ? '<span class="muted">💤 Ada is asleep.</span>' : tokHTML(c.tokens || [[c.text, .5]]);
  $("#chat").append(d); while ($("#chat").children.length > 150) $("#chat").firstChild.remove();
  $("#chat").scrollTop = $("#chat").scrollHeight;
}
function tutorLine(e) {
  const last = [...$$(".msg.mind", $("#chat"))].reverse().find((m) => !m.querySelector(".tutor"));
  if (!last) return;
  const t = document.createElement("div"); t.className = "tutor"; t.innerHTML = `<b>The Oracle suggests:</b> ${esc(e.text)}`;
  last.append(t); $("#chat").scrollTop = $("#chat").scrollHeight;
}
$$("#adaTabs button").forEach((b) => b.onclick = () => {
  $$("#adaTabs button").forEach((x) => x.classList.toggle("on", x === b));
  $$("aside .pane").forEach((p) => p.classList.toggle("on", p.id === `pane-${b.dataset.pane}`));
});
$("#chatForm").onsubmit = async (ev) => {
  ev.preventDefault();
  const text = $("#chatText").value.trim(); if (!text) return;
  $("#chatText").value = "";
  S.pendingChat = document.createElement("div"); S.pendingChat.className = "msg mind pending"; S.pendingChat.textContent = "…";
  $("#chat").append(S.pendingChat);
  try { await api("chat", { text }); } catch (e) { toast(e.message); if (S.pendingChat) { S.pendingChat.remove(); S.pendingChat = null; } }
};
$("#suggestForm").onsubmit = async (ev) => {
  ev.preventDefault();
  const text = $("#suggestText").value.trim(); if (!text) return;
  $("#suggestText").value = "";
  try { toast(await api("suggest", { text })); } catch (e) { toast(e.message); }
};

// modes under the map
$$("#modes button").forEach((b) => b.onclick = () => {
  S.mode = b.dataset.mode;
  $$("#modes button").forEach((x) => x.classList.toggle("on", x === b));
  for (const m of ["watch", "add", "you"]) $(`#mode-${m}`).hidden = m !== S.mode;
  if (S.mode !== "add") setTool(null);
});
$("#follow").onchange = (e) => MapView.setFollow(e.target.value);
function setTool(t) {
  S.tool = t; MapView.setTool(t);
  $$("#palette button").forEach((b) => b.classList.toggle("on", b.dataset.kind === t));
  setText($("#addHint"), t ? (t === "erase" ? "Click things on the map to remove them." : `Click open ground to place the ${t}. Click it again to stop.`)
    : "Choose something, then click open ground to put it there. Books and signs ask what they should say.");
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
    const text = k === "book" ? (prompt("Write the book's words (Ada will read and study them):") || "") : "";
    try { toast(await api("visitor", { action: "hold", kind: k, text })); } catch (e) { toast(e.message); }
  };
  $("#holdPalette").append(b);
}
MapView.st.onClick = async ({ x, y }) => {
  if (S.mode === "add" && S.tool) {
    let text = "";
    if (S.tool === "sign") { text = prompt("What should the sign say?") || ""; if (!text) return; }
    if (S.tool === "book") text = prompt("Write the book's words (empty: the Oracle writes one when Ada reads it):") || "";
    try { toast(await api("place", { kind: S.tool, x, y, text })); } catch (e) { toast(e.message); }
    return;
  }
  const w = MapView.st.world; if (!w) return;
  const here = MapView.entitiesAt(x, y).map((e) => GLYPH[e.kind] + " " + e.kind + (e.kind === "sprout" ? ` (${Math.round(e.growth || 0)}% grown${e.watered ? ", watered" : ""})` : ""));
  const who = [w.ada, ...(w.people || []), w.visitor].filter((b) => b && b.x === x && b.y === y).map((b) => b.name === "you" ? "you" : b.name);
  const place = w.regions?.[y]?.[x];
  toast([place && `The ${place}`, ...who, ...here].filter(Boolean).join(" · ") || "Nothing here.");
};
$("#btnJoin").onclick = async () => {
  const joined = !!MapView.st.world?.visitor;
  try { toast(await api("visitor", { action: joined ? "leave" : "join" })); } catch (e) { toast(e.message); }
  if (!joined) { $("#follow").value = "you"; MapView.setFollow("you"); MapView.canvas.focus(); }
  else { $("#follow").value = "ada"; MapView.setFollow("ada"); }
};
$$("[data-you]").forEach((b) => b.onclick = async () => {
  if (!MapView.st.world?.visitor) await api("visitor", { action: "join" });
  try { toast(await api("visitor", { action: b.dataset.you })); } catch (e) { toast(e.message); }
});
const KEYS = { ArrowUp: "north", w: "north", ArrowDown: "south", s: "south", ArrowLeft: "west", a: "west", ArrowRight: "east", d: "east",
               f: "take", r: "drop", g: "give", h: "hug" };
MapView.canvas.addEventListener("keydown", async (e) => {
  const k = e.key.length === 1 ? e.key.toLowerCase() : e.key, act = KEYS[k];
  if (!act || !MapView.st.world?.visitor) return;
  e.preventDefault();
  try { const r = await api("visitor", { action: act }); if (r) toast(r); } catch (err) { toast(err.message); }
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
  const mix = a.mix || {}, names = { fineweb: "Web text", lessons: "Oracle lessons", journal: "Her journal", concepts: "Concept drills" };
  setHTML($("#mix"), Object.keys(names).map((k) => `<div class="bar"><span>${names[k]}</span><div><i style="width:${Math.round((mix[k] || 0) * 100)}%"></i></div><b>${pct(mix[k] || 0)}</b></div>`).join("")
    + `<div class="muted" style="margin-top:4px">${big(a.pools?.lessons_added)} lessons and ${big(a.pools?.journal_added)} journal entries received · ${a.pools?.facts ?? "–"} facts known to the graph</div>`);
  const f = a.fineweb || {};
  setHTML($("#fwFacts"), dl([["Status", esc(f.status) + (f.error ? ` <span class="muted">(${esc(f.error)})</span>` : "")],
    ["Reading", `<span class="muted">${esc(f.source || "–")}</span>`], ["Documents", big(f.docs)], ["Bytes per token", f.bytes_per_token ?? "–"]]));
}
$$("[data-ac]").forEach((b) => b.onclick = async () => {
  if (b.dataset.ac === "grow" && !confirm("Add a layer to Ada's brain? What she knows is kept; she gains room to learn more.")) return;
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
  if (pts.length < 2) { g.fillText("waiting for Ada to study…", 8 * dpr, H / 2); return; }
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
  setText($("#assessNote"), last?.note ? `Oracle (spelling · grammar · coherence · meaning): “${last.note}”` : "");
}
addEventListener("resize", () => drawCharts());

// ================================================================== concepts view
const REL = { "is a": "What it is", color: "Colors", is: "What it's like", "made of": "What it's made of", "used for": "What it's for", "found in": "Where it is", can: "What it can do" };
function renderConcepts() {
  const c = S.concepts || {};
  const bars = (obj, label) => Object.entries(obj || {}).map(([k, v]) => `<div class="bar"><span>${esc(label(k))}</span><div><i style="width:${Math.round(v * 100)}%;background:${v > .5 ? "var(--good)" : v > .3 ? "var(--accent)" : "var(--warn)"}"></i></div><b>${pct(v)}</b></div>`).join("");
  setHTML($("#byRel"), bars(c.by_relation, (k) => REL[k] || k) || '<div class="muted">Not tested yet.</div>');
  setHTML($("#bySrc"), bars(c.by_source, (k) => k === "built-in" ? "Built-in facts" : "Taught by the Oracle"));
  const q = S.oracle.queued || [];
  setText($("#teachQueue"), q.length ? `Waiting to be taught: ${q.join(", ")}` : S.oracle.teaching ? "The Oracle is writing a lesson…" : "");
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
  const o = S.oracle, st = $("#orStatus");
  st.className = "status " + (o.model && o.enabled && !o.error ? "on" : "off");
  setText(st, o.error ? o.error : !o.enabled ? "The Oracle is switched off (Settings)." : o.model ? `${o.model} · ${o.lessons} lessons written this session${o.teaching ? " · writing one now" : ""}` : "No model chosen.");
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
  setHTML($("#askOut"), '<div class="item muted">The Oracle is thinking…</div>');
  try {
    const a = await api("oracle_ask", { question: q });
    setHTML($("#askOut"), `<div class="item">${esc(a)}<div class="row" style="margin-top:6px"><button id="learnIt">🎓 Let Ada study this</button></div></div>`);
    $("#learnIt").onclick = async () => { toast(await api("oracle_learn", { question: q, answer: a })); $("#learnIt").disabled = true; };
  } catch (e) { setHTML($("#askOut"), `<div class="item">${esc(e.message)}</div>`); }
};
function addLesson(e) {
  const qa = (e.qa || []).map(([q, a]) => `\n<b>Q:</b> ${esc(q)}\n<b>A:</b> ${esc(a)}`).join("");
  const facts = (e.facts || []).length ? `<div class="meta">facts: ${e.facts.map((f) => esc(`${f.s} ${f.r} ${f.o}`)).join(" · ")}${e.new_facts ? ` (${e.new_facts} new)` : ""}</div>` : "";
  prepend($("#lessons"), `<b class="t">${e.priority ? "⭐ " : ""}${esc(e.topic)}</b>${esc(e.text)}${qa}${facts}`, 60);
}
function addQA(e) { prepend($("#qa"), `<b class="t">${e.by === "you" ? "You asked" : "Ada asked"}</b><i>${esc(e.question)}</i>\n${esc(e.text)}`, 60); }

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
