"use strict";
// Synthetic Mind dashboard. Everything arrives over one WebSocket: an initial payload, then
// a tick every 250 ms with the latest snapshot and any new events.

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmt = (n, d = 0) => (n == null || !isFinite(n) ? "–" : Number(n).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d }));
const big = (n) => n == null ? "–" : n >= 1e9 ? (n / 1e9).toFixed(2) + "B" : n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e3 ? (n / 1e3).toFixed(1) + "k" : String(n);
const dur = (s) => { s = Math.round(s || 0); const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return h ? `${h}h ${m}m` : m ? `${m}m ${s % 60}s` : `${s}s`; };
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

const S = { snap: null, history: [], assessments: [], chat: new Map(), lastTerrain: "", pendingChat: null };

async function api(name, body = {}) {
  const r = await fetch(`/api/${name}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return (await r.json()).result;
}

// ---------------------------------------------------------------- socket
function connect() {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  ws.onmessage = (m) => {
    // One bad message or rendering bug must never stop the page from updating.
    let msg;
    try { msg = JSON.parse(m.data); } catch (err) { console.error("bad message", err); return; }
    try {
      if (msg.type === "init") init(msg);
      else for (const e of msg.events) { try { onEvent(e); } catch (err) { console.error(e.kind, err); } }
    } catch (err) { console.error(err); }
    try {
      if (msg.snap) {
        if (S.snap) {
          if (msg.snap.world && !msg.snap.world.terrain) msg.snap.world.terrain = S.snap.world.terrain;
          if (!("internals" in msg.snap)) msg.snap.internals = S.snap.internals;
        }
        render(msg.snap);
      }
    } catch (err) { console.error("render", err); }
  };
  ws.onclose = () => { $("#device").textContent = "disconnected, reconnecting…"; setTimeout(connect, 1500); };
}

function init(msg) {
  S.history = msg.history || [];
  S.assessments = msg.assessments || [];
  $("#thoughts").innerHTML = "";
  (msg.thoughts || []).forEach(addThought);
  $("#chat").innerHTML = "";
  S.chat.clear();
  const log = msg.chat || [];
  for (let i = 0; i < log.length; i++) {
    const m = log[i];
    if (m.role === "user") addUserMsg(m.text);
    else addMindMsg(m.text, m.tokens || [], m.index, m.rating);
  }
  $("#teacherFeed").innerHTML = ""; $("#readFeed").innerHTML = "";
  for (const e of msg.events || []) if (["teacher", "tutor", "read", "growth", "assessment"].includes(e.kind)) onEvent(e, true);
  S.lastTerrain = "";
  drawCharts();
}

function onEvent(e, replay = false) {
  switch (e.kind) {
    case "thought": addThought(e); pulse(); break;
    case "chat":
      if (S.pendingChat) { S.pendingChat.remove(); S.pendingChat = null; }
      addMindMsg(e.mind, e.tokens, e.index); break;
    case "tutor": attachTutor(e); feed("#teacherFeed", "Ideal reply", e.text, `You: ${e.user}`); break;
    case "teacher":
      if (e.sub === "review") feed("#teacherFeed", "Rewrote a thought", e.text, e.original, true);
      else feed("#teacherFeed", `${e.sub === "dialogue" ? "Dialogue" : "Lesson"} · ${e.topic || ""}`, e.text);
      break;
    case "metric": if (!replay) { S.history.push(e); if (S.history.length > 8000) S.history.shift(); scheduleCharts(); } break;
    case "assessment": if (!replay) S.assessments.push(e); $("#assessNote").textContent = e.note ? `Teacher: “${e.note}”` : ""; scheduleCharts(); break;
    case "read": feed("#readFeed", "Read a book in the world", e.text); break;
    case "growth": feed("#teacherFeed", "Brain grew", `Now ${e.layers} layers, ${big(e.params)} parameters (${e.why}).`); if (!replay) flash(`The brain grew to ${e.layers} layers.`); break;
    case "speak": break;
    case "saved": if (!replay) flash("Saved.", 1500); break;
    case "error": flash(`Engine error: ${e.text}`, 8000); break;
  }
}
let flashTimer;
function flash(text, ms = 4000) {
  const b = $("#banner"); b.textContent = text; b.hidden = false;
  b.dataset.auto = "";
  clearTimeout(flashTimer); flashTimer = setTimeout(() => { b.hidden = true; }, ms);
}

function pulse() { const o = $("#orb"); o.classList.add("thinking"); setTimeout(() => o.classList.remove("thinking"), 900); }

function feed(sel, title, text, orig, strike) {
  const box = $(sel);
  const d = document.createElement("div");
  d.className = "item";
  d.innerHTML = `<b>${esc(title)}</b>${orig ? `<span class="${strike ? "orig" : "muted"}">${esc(orig)}</span>` : ""}${esc(text)}`;
  box.prepend(d);
  while (box.children.length > 80) box.lastChild.remove();
}

// ---------------------------------------------------------------- tokens
function tokSpan(t, known) {
  const [s, p, ent] = t;
  const c = p < 0.05 ? 0 : p < 0.2 ? 1 : p < 0.45 ? 2 : p < 0.75 ? 3 : 4;
  const w = s.trim().toLowerCase().replace(/[^a-z']/g, "");
  const real = known && w.length > 1 && known.has(w) ? " real-word" : "";
  return `<span class="tk c${c}${real}" title="p=${(p * 100).toFixed(1)}%  entropy=${ent} nats">${esc(s)}</span>`;
}
function tokensHTML(tokens, known) {
  const k = known ? new Set(known) : null;
  return tokens.length ? tokens.map((t) => tokSpan(t, k)).join("") : `<span class="muted">(silence)</span>`;
}

function addThought(t) {
  const box = $("#thoughts");
  const stick = box.scrollTop + box.clientHeight >= box.scrollHeight - 30;
  const d = document.createElement("div");
  d.className = "thought" + (t.grounded ? " grounded" : "");
  d.innerHTML = `<div>${tokensHTML(t.tokens || [], t.known)}</div>
    <div class="meta"><span>step ${fmt(t.step)}</span><span>${Math.round((t.real || 0) * 100)}% real words</span>
    <span>confidence ${(t.confidence * 100 || 0).toFixed(1)}%</span>${t.grounded ? "<span>grounded in senses</span>" : ""}</div>`;
  box.append(d);
  while (box.children.length > 80) box.firstChild.remove();
  if (stick) box.scrollTop = box.scrollHeight;
}

// ---------------------------------------------------------------- chat
function scrollChat() { const c = $("#chat"); c.scrollTop = c.scrollHeight; }
function addUserMsg(text, cls = "user") {
  const d = document.createElement("div"); d.className = `msg ${cls}`; d.textContent = text;
  $("#chat").append(d); scrollChat(); return d;
}
function addMindMsg(text, tokens, index, rating) {
  const d = document.createElement("div"); d.className = "msg mind"; d.dataset.index = index;
  d.innerHTML = `<div>${tokensHTML(tokens)}</div>
    <div class="muted small">${esc(S.snap?.name || "Mind")}<span class="rate">
      <button data-good="1" class="${rating === 1 ? "on" : ""}" title="Good reply: it will study this exchange">👍</button>
      <button data-good="0" class="${rating === -1 ? "on" : ""}" title="Not good">👎</button></span></div>`;
  d.querySelectorAll(".rate button").forEach((b) => b.onclick = async () => {
    await api("feedback", { index: +index, good: b.dataset.good === "1" });
    d.querySelectorAll(".rate button").forEach((x) => x.classList.toggle("on", x === b));
  });
  $("#chat").append(d); S.chat.set(index, d); scrollChat();
}
function attachTutor(e) {
  const msgs = $$(".msg.mind", $("#chat"));
  const d = msgs.reverse().find((m) => !m.querySelector(".tutor"));
  if (!d) return;
  const t = document.createElement("div"); t.className = "tutor";
  t.innerHTML = `<b>Teacher suggests:</b> ${esc(e.text)}`;
  d.append(t); scrollChat();
}

$("#chatForm").onsubmit = async (ev) => {
  ev.preventDefault();
  const inp = $("#chatText"), text = inp.value.trim();
  if (!text) return;
  inp.value = "";
  if ($("#chatMode").value === "teach") {
    addUserMsg("📚 " + text, "taught");
    await api("teach", { text });
    return;
  }
  addUserMsg(text);
  S.pendingChat = addUserMsg("…", "mind pending");
  try { await api("chat", { text }); } catch (err) { flash(err.message); }
};

// ---------------------------------------------------------------- header + panels
// Replace an element's HTML only when it actually changed (avoids needless layout and paint).
function setHTML(el, html) { if (el._html !== html) { el._html = html; el.innerHTML = html; } }
function setText(el, text) { if (el.textContent !== text) el.textContent = text; }
const tabOn = (t) => $(`#tab-${t}`).classList.contains("on");

function render(s) {
  S.snap = s;
  S.worldDirty = true;
  $("#mindName").textContent = s.name;
  $("#device").textContent = `${s.device} · ${s.precision} · ${s.tokenizer} tokens`;
  document.title = `${s.name} · ${s.stage_name}`;
  setHTML($("#ladder"), s.stages.map((n, i) => `<span class="${i < s.stage ? "done" : i === s.stage ? "now" : ""}">${n}</span>`).join(""));
  $("#stageBlurb").textContent = s.stage_blurb;
  $("#kAge").textContent = dur(s.age);
  $("#kTokens").textContent = big(s.tokens);
  $("#kBrain").textContent = `${big(s.params)} · ${s.layers}L`;
  $("#kBpb").textContent = s.bpb ? s.bpb.toFixed(3) : "–";
  const learning = s.train_status === "learning";
  $("#kTps").textContent = !s.settings.training ? "paused" : learning ? `${big(Math.round(s.tps))} tok/s` : "not learning";
  const st = $("#trainStatus");
  st.className = "status " + (learning || !s.settings.training ? "ok" : "warn");
  setHTML(st, `Training: ${esc(s.train_status || "")} · step ${fmt(s.step)}` +
    (s.skipped_steps ? ` · ${fmt(s.skipped_steps)} unstable steps skipped` : "") +
    (s.hitch ? `<span class="err">Pause of ${s.hitch.seconds}s ${dur((Date.now() / 1000) - s.hitch.t)} ago: ${esc(s.hitch.why)}</span>` : "") +
    (s.last_error ? `<span class="err">Last error: ${esc(s.last_error)} (details in minds/${esc(s.name)}/engine.log)</span>` : ""));
  $("#kVocab").textContent = fmt(s.vocab);
  $("#btnTrain").textContent = s.settings.training ? "Pause learning" : "Resume learning";
  $("#btnTrain").classList.toggle("primary", !s.settings.training);
  syncSettings(s.settings);
  renderBody(s);
  if (tabOn("brain")) renderBrain(s);
  if (tabOn("teacher")) renderTeacher(s);
  if (tabOn("data")) renderData(s);
  if (tabOn("growth")) setHTML($("#vocabWords"), (s.vocab_sample || []).map((w) => `<span>${esc(w)}</span>`).join(""));
  const warn = [];
  if (s.fineweb.error && s.settings["data.fineweb_enabled"]) warn.push(`FineWeb: ${s.fineweb.error}`);
  if (s.teacher.error && s.settings.teacher_enabled) warn.push(`Teacher: ${s.teacher.error}`);
  if (warn.length && $("#banner").hidden) { $("#banner").textContent = warn.join("  ·  "); $("#banner").hidden = false; $("#banner").dataset.auto = 1; }
  else if (!warn.length && $("#banner").dataset.auto === "1") { $("#banner").hidden = true; $("#banner").dataset.auto = ""; }
}

function syncSettings(st) {
  for (const el of $$("[data-setting]")) {
    const key = el.dataset.setting, v = st[key];
    if (v === undefined || el === document.activeElement || el.dataset.busy) continue;
    if (el.type === "checkbox") el.checked = !!v;
    else el.value = v;
    const out = el.parentElement.querySelector("output");
    if (out) out.textContent = el.value;
  }
}
for (const el of $$("[data-setting]")) {
  const send = async () => {
    const v = el.type === "checkbox" ? el.checked : el.type === "range" ? parseFloat(el.value) : el.value;
    el.dataset.busy = 1;
    try { await api("set", { key: el.dataset.setting, value: v }); } catch (e) { flash(e.message); }
    setTimeout(() => delete el.dataset.busy, 600);
  };
  el.addEventListener("change", send);
  el.addEventListener("input", () => { const o = el.parentElement.querySelector("output"); if (o) o.textContent = el.value; el.dataset.busy = 1; });
}

$("#btnTrain").onclick = () => api("set", { key: "training", value: !S.snap.settings.training });
$("#btnThink").onclick = () => api("think");
$("#btnGrow").onclick = () => { if (confirm("Add a new layer to the network? What it knows is kept; it gains capacity to learn more.")) api("grow"); };
$("#btnSave").onclick = () => api("save");
$("#btnModels").onclick = () => api("refresh_models");
$("#btnResetWorld").onclick = () => { if (confirm("Replace the world with a freshly generated one?")) api("reset_world"); };
$("#ollamaModel").onchange = (e) => api("set", { key: "ollama_model", value: e.target.value });

$$("#tabs button").forEach((b) => b.onclick = () => {
  $$("#tabs button").forEach((x) => x.classList.toggle("on", x === b));
  $$(".tab").forEach((t) => t.classList.toggle("on", t.id === `tab-${b.dataset.tab}`));
  if (b.dataset.tab === "growth") drawCharts();
  if (b.dataset.tab === "brain") drawAttn(S.snap);
});

function dl(rows) { return rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join(""); }

function renderTeacher(s) {
  const sel = $("#ollamaModel");
  const names = s.teacher.models.map((m) => m.name);
  const sig = names.join("|") + "#" + s.settings.ollama_model;
  if (sel.dataset.sig !== sig && document.activeElement !== sel) {
    sel.innerHTML = names.length
      ? s.teacher.models.map((m) => `<option value="${esc(m.name)}">${esc(m.name)}${m.parameter_size ? ` (${esc(m.parameter_size)})` : ""}</option>`).join("")
      : `<option value="">no Ollama models found</option>`;
    sel.value = s.settings.ollama_model;
    sel.dataset.sig = sig;
  }
  setHTML($("#teacherFacts"), dl([
    ["Status", esc(s.teacher.status) + (s.teacher.error ? ` <span class="muted">(${esc(s.teacher.error)})</span>` : "")],
    ["Server", esc(s.settings.ollama_url)],
    ["Lessons written", fmt(s.teacher.lessons)],
    ["Lesson pool", fmt(s.pools.teacher)],
  ]));
}

function renderData(s) {
  const f = s.fineweb, rf = s.rows_from, tot = Object.values(rf).reduce((a, b) => a + b, 0) || 1;
  const pct = (k) => `${((rf[k] || 0) / tot * 100).toFixed(1)}%`;
  setHTML($("#dataFacts"), dl([
    ["FineWeb", `${esc(f.status)}${f.error ? ` <span class="muted">(${esc(f.error)})</span>` : ""}`],
    ["Now reading", `<span class="muted">${esc(f.source || "–")}</span>`],
    ["Documents streamed", fmt(f.docs)],
    ["Ready buffer", `${fmt(f.buffer)} docs`],
    ["Bytes per token", f.bytes_per_token],
    ["Experience pool", `${fmt(s.pools.experience)} memories`],
    ["Rows trained so far", `web ${pct("fineweb")} · teacher ${pct("teacher")} · experience ${pct("experience")}`],
  ]));
}

function renderBrain(s) {
  setHTML($("#anatomy"), dl([
    ["Parameters", `${fmt(s.params)} <span class="muted">(${fmt(s.trunk_params)} outside the word embedding)</span>`],
    ["Layers", `${s.layers}${s.growths ? ` <span class="muted">(grew ${s.growths}×)</span>` : ""}`],
    ["Width", s.d_model], ["Context", `${s.seq_len} tokens`],
    ["Training step", fmt(s.step)], ["Loss", s.loss ? s.loss.toFixed(4) : "–"],
    ["Held-out loss", s.val ? s.val.toFixed(4) : "–"], ["Learning rate", s.lr ? s.lr.toExponential(2) : "–"],
    ["Gradient norm", s.gnorm ? s.gnorm.toFixed(3) : "–"],
  ]));
  const it = s.internals || {};
  if (it.resid_rms) {
    const mr = Math.max(...it.resid_rms, 1e-6), me = Math.max(...it.attn_entropy, 1e-6);
    setHTML($("#layers"), `<div><span></span><span>activation size</span><span>attention spread</span></div>` +
      it.resid_rms.map((r, i) => `<div><span>layer ${i + 1}</span><i style="width:${r / mr * 100}%"></i><i class="e" style="width:${it.attn_entropy[i] / me * 100}%"></i></div>`).join(""));
  }
  if (it !== S.lastInternals) { S.lastInternals = it; drawAttn(s); }
}

function drawAttn(s) {
  const it = s?.internals; const c = $("#attn");
  if (!it || !it.attn) return;
  const n = it.attn.length, dpr = devicePixelRatio || 1, size = c.clientWidth * dpr;
  if (!n || size < 100) return;  // hidden tab
  c.width = c.height = size;
  const g = c.getContext("2d"), pad = 70 * dpr, cell = (size - pad) / n;
  g.clearRect(0, 0, size, size);
  for (let i = 0; i < n; i++) for (let j = 0; j <= i; j++) {
    const v = Math.sqrt(it.attn[i][j]);
    g.fillStyle = `rgba(124,156,255,${v})`;
    g.fillRect(pad + j * cell, pad + i * cell, cell + 0.5, cell + 0.5);
  }
  g.fillStyle = css("--muted"); g.font = `${Math.max(8, Math.min(11, cell * .9)) * (dpr > 1 ? 1.5 : 1)}px ui-monospace, monospace`;
  g.textAlign = "right"; g.textBaseline = "middle";
  const every = Math.ceil(10 * dpr / cell);
  for (let i = 0; i < n; i += every) {
    const lab = it.tokens[i].replace(/\n/g, "↵").slice(0, 8);
    g.fillText(lab, pad - 4, pad + (i + .5) * cell);
    g.save(); g.translate(pad + (i + .5) * cell, pad - 4); g.rotate(-Math.PI / 2); g.textAlign = "left"; g.fillText(lab, 0, 0); g.restore();
  }
}

$("#probeForm").onsubmit = async (e) => {
  e.preventDefault();
  const r = await api("probe", { text: $("#probeText").value });
  $("#probeTokens").innerHTML = r.tokens.map(([s, bits]) => {
    const a = Math.min(1, bits / 16);
    return `<span class="tk" style="background:rgba(255,107,122,${a * .7})" title="${bits} bits of surprise">${esc(s)}</span>`;
  }).join("");
  const mx = r.next[0]?.[1] || 1;
  $("#probeNext").innerHTML = r.next.map(([s, p]) => `<div><span class="tk">${esc(JSON.stringify(s).slice(1, -1))}</span><i style="width:${p / mx * 100}%"></i><span>${(p * 100).toFixed(1)}%</span></div>`).join("");
};

// ---------------------------------------------------------------- charts
let chartTimer;
function scheduleCharts() { if (!chartTimer) chartTimer = setTimeout(() => { chartTimer = null; drawCharts(); }, 1000); }

function series(key) {
  const out = [];
  for (const p of S.history) if (p[key] != null) out.push([p.step, p[key]]);
  if (out.length > 700) { const k = Math.ceil(out.length / 700); return out.filter((_, i) => i % k === 0 || i === out.length - 1); }
  return out;
}

function drawChart(canvas, lines, opt = {}) {
  const dpr = devicePixelRatio || 1, W = canvas.clientWidth * dpr, H = canvas.clientHeight * dpr;
  if (!W) return;
  canvas.width = W; canvas.height = H;
  const g = canvas.getContext("2d");
  const pts = lines.flatMap((l) => l.data);
  g.font = `${10 * dpr}px system-ui`; g.fillStyle = css("--muted");
  if (pts.length < 2) {
    g.fillText(S.snap && S.snap.step < 20 ? "waiting for the first training steps…" : "no data yet", 8 * dpr, H / 2);
    return;
  }
  let x0 = Math.min(...pts.map((p) => p[0])), x1 = Math.max(...pts.map((p) => p[0]));
  let y0 = opt.min ?? Math.min(...pts.map((p) => p[1])), y1 = opt.max ?? Math.max(...pts.map((p) => p[1]));
  if (y1 - y0 < 1e-9) { y1 += 1; y0 -= opt.min != null ? 0 : 1; }
  const L = 40 * dpr, R = 6 * dpr, T = 6 * dpr, B = 16 * dpr;
  const X = (x) => L + (x - x0) / (x1 - x0 || 1) * (W - L - R);
  const Y = (y) => H - B - (y - y0) / (y1 - y0) * (H - T - B);
  g.strokeStyle = css("--line"); g.lineWidth = 1;
  for (let i = 0; i <= 3; i++) {
    const y = y0 + (y1 - y0) * i / 3, py = Y(y);
    g.beginPath(); g.moveTo(L, py); g.lineTo(W - R, py); g.stroke();
    g.fillText(opt.fmt ? opt.fmt(y) : (Math.abs(y) >= 100 ? big(Math.round(y)) : y.toFixed(Math.abs(y) < 1 ? 3 : 2)), 2 * dpr, py + 3 * dpr);
  }
  g.fillText(`step ${big(x1)}`, W - R - 60 * dpr, H - 3 * dpr);
  for (const l of lines) {
    if (l.data.length < 1) continue;
    g.strokeStyle = l.color; g.lineWidth = 1.6 * dpr; g.beginPath();
    l.data.forEach(([x, y], i) => i ? g.lineTo(X(x), Y(y)) : g.moveTo(X(x), Y(y)));
    g.stroke();
    if (l.dots) { g.fillStyle = l.color; for (const [x, y] of l.data) { g.beginPath(); g.arc(X(x), Y(y), 2.5 * dpr, 0, 7); g.fill(); } }
  }
}

function drawCharts() {
  if (!$("#tab-growth").classList.contains("on")) return;
  const A = css("--accent"), B = css("--warn"), C = css("--good"), D = css("--accent-2");
  const c = (k) => $(`canvas[data-chart=${k}]`);
  drawChart(c("loss"), [{ data: series("loss_ema"), color: A }, { data: series("val"), color: B, dots: true }]);
  drawChart(c("bpb"), [{ data: series("bpb"), color: D }]);
  drawChart(c("real"), [{ data: series("real"), color: C }], { min: 0, max: 1, fmt: (v) => `${Math.round(v * 100)}%` });
  drawChart(c("vocab"), [{ data: series("vocab"), color: A }], { min: 0 });
  drawChart(c("reward"), [{ data: series("reward"), color: C }]);
  drawChart(c("tps"), [{ data: series("tps"), color: D }], { min: 0 });
  const as = S.assessments;
  drawChart(c("assess"), ["spelling", "grammar", "coherence", "meaning"].map((k, i) => ({
    data: as.map((a) => [a.step, a[k]]), color: [A, B, C, D][i], dots: true })), { min: 0, max: 10, fmt: (v) => v.toFixed(0) });
  const last = as[as.length - 1];
  if (last && last.note) $("#assessNote").textContent = `Teacher (spelling · grammar · coherence · meaning): “${last.note}”`;
}
addEventListener("resize", () => { drawCharts(); drawAttn(S.snap); });

// ---------------------------------------------------------------- world
const EMOJI = { apple: "🍎", berry: "🫐", ball: "⚽", book: "📘", block: "🧱", seed: "🌰", lamp: "💡", musicbox: "🎵",
  mirror: "🪞", sign: "🪧", bed: "🛏️", cat: "🐈", flower: "🌷" };
const TERRAIN = ["#3f7d3a", "#2f6fb0", "#d8c48a", "#2d5e2a", "#7d8088", "#4c8a42", "#356b2f", "#b39a6a"];
let tool = null, mode = "add";
const PORTABLE = ["apple", "berry", "ball", "book", "block", "seed"];
const BLOCKED = new Set([1, 3, 4, 6]);  // water, tree, rock, bush

let toastTimer;
function toast(text) {
  if (!text) return;
  let t = $(".toast");
  if (!t) { t = document.createElement("div"); t.className = "toast"; document.body.append(t); }
  t.textContent = text; t.classList.add("show");
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove("show"), 2600);
}

// World edits answer with the new world, so the map updates at once.
async function worldApi(name, body = {}) {
  try {
    const r = await fetch(`/api/${name}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const j = await r.json();
    if (!r.ok) throw new Error(j.detail || r.statusText);
    if (j.world && S.snap) { S.snap.world = j.world; S.worldDirty = true; renderBody(S.snap); }
    return j.result;
  } catch (err) { toast(err.message); }
}

const pal = $("#palette");
for (const k of [...Object.keys(EMOJI), "erase"]) {
  const b = document.createElement("button");
  b.textContent = k === "erase" ? "🧽" : EMOJI[k]; b.title = k === "erase" ? "Erase things" : `Place ${k}`;
  b.onclick = () => {
    tool = tool === k ? null : k;
    $$("button", pal).forEach((x) => x.classList.toggle("on", x === b && !!tool));
    $("#addHint").textContent = tool ? (tool === "erase" ? "Click things on the map to erase them." : `Now click open ground on the map to place the ${tool}. Click it again to stop.`)
      : "Choose an item, then click open ground on the map to put it there. Signs and books ask what they should say. 🧽 erases.";
    wc.style.cursor = tool ? "copy" : "crosshair";
  };
  pal.append(b);
}
const hp = $("#holdPalette");
for (const k of PORTABLE) {
  const b = document.createElement("button");
  b.textContent = EMOJI[k]; b.title = `Hold a new ${k}`;
  b.onclick = async () => {
    if (!S.snap?.world.visitor) await worldApi("join");
    const text = k === "book" ? (prompt("Write the book's text (leave empty for a random FineWeb page):") || "") : "";
    toast(await worldApi("you", { action: "hold", kind: k, text }));
  };
  hp.append(b);
}

function setMode(m) {
  mode = m;
  $$("#worldModes button").forEach((b) => b.classList.toggle("on", b.dataset.mode === m));
  for (const id of ["add", "you", "guide"]) $(`#mode-${id}`).hidden = id !== m;
  if (m !== "add" && tool) $$("button.on", pal).forEach((b) => b.click());
}
$$("#worldModes button").forEach((b) => b.onclick = () => setMode(b.dataset.mode));

$("#btnJoin").onclick = async () => {
  const joined = !!S.snap?.world.visitor;
  toast(await worldApi(joined ? "leave" : "join"));
  if (!joined) wc.focus();
};
$("#btnSay").onclick = () => sayFromWorld();
function sayFromWorld() {
  $("#chatMode").value = "chat";
  const inp = $("#chatText"); inp.placeholder = "Say something (it appears above you in the world)…"; inp.focus();
}
$$("[data-you]").forEach((b) => b.onclick = async () => {
  if (!S.snap?.world.visitor) await worldApi("join");
  toast(await worldApi("you", { action: b.dataset.you }));
});

const wc = $("#world"), wg = wc.getContext("2d");
let terrainCanvas = null, bodyPos = null;

function hash(x, y) { let h = x * 374761393 + y * 668265263; h = (h ^ (h >> 13)) * 1274126177; return ((h ^ (h >> 16)) >>> 0) / 4294967295; }

function buildTerrain(w, ts) {
  const c = document.createElement("canvas"); c.width = w.w * ts; c.height = w.h * ts;
  const g = c.getContext("2d");
  for (let y = 0; y < w.h; y++) for (let x = 0; x < w.w; x++) {
    const t = w.terrain[y][x], r = hash(x, y);
    g.fillStyle = TERRAIN[0]; g.fillRect(x * ts, y * ts, ts, ts);
    g.fillStyle = `rgba(0,0,0,${r * .08})`; g.fillRect(x * ts, y * ts, ts, ts);
    const cx = x * ts + ts / 2, cy = y * ts + ts / 2;
    if (t === 1 || t === 2 || t === 7) { g.fillStyle = TERRAIN[t]; g.fillRect(x * ts, y * ts, ts, ts); }
    if (t === 1) { g.strokeStyle = "rgba(255,255,255,.18)"; g.beginPath(); g.arc(cx - ts * .15, cy, ts * .18, Math.PI * 1.1, Math.PI * 1.9); g.stroke(); }
    if (t === 3) {
      g.fillStyle = "#5b3b22"; g.fillRect(cx - ts * .07, cy, ts * .14, ts * .4);
      g.fillStyle = TERRAIN[3]; g.beginPath(); g.arc(cx, cy - ts * .05, ts * .42, 0, 7); g.fill();
      g.fillStyle = "rgba(255,255,255,.08)"; g.beginPath(); g.arc(cx - ts * .12, cy - ts * .17, ts * .17, 0, 7); g.fill();
    }
    if (t === 4) { g.fillStyle = TERRAIN[4]; g.beginPath(); g.ellipse(cx, cy + ts * .08, ts * .38, ts * .28, 0, 0, 7); g.fill();
      g.fillStyle = "rgba(255,255,255,.15)"; g.beginPath(); g.ellipse(cx - ts * .1, cy - ts * .02, ts * .14, ts * .08, 0, 0, 7); g.fill(); }
    if (t === 5) for (let i = 0; i < 4; i++) { g.fillStyle = ["#ffd166", "#ef476f", "#ffffff", "#c77dff"][(i + x) % 4];
      g.beginPath(); g.arc(x * ts + ts * (.2 + .6 * hash(x + i, y)), y * ts + ts * (.2 + .6 * hash(x, y + i)), ts * .06, 0, 7); g.fill(); }
    if (t === 6) { g.fillStyle = TERRAIN[6]; g.beginPath(); g.arc(cx, cy + ts * .05, ts * .36, 0, 7); g.fill();
      g.fillStyle = "#9b2c4a"; for (let i = 0; i < 3; i++) { g.beginPath(); g.arc(cx + (i - 1) * ts * .15, cy + ts * (.0 + .08 * i % 2), ts * .05, 0, 7); g.fill(); } }
  }
  return c;
}

function drawWorld(now) {
  requestAnimationFrame(drawWorld);
  const s = S.snap; if (!s) return;
  // Redraw when the world changed or something is still gliding; otherwise ~4 times a second
  // for blinking and bobbing. The GPU is busy training, so the page should not repaint needlessly.
  const moving = S.moving || (now - (S.lastDraw || 0)) > 250;
  if (!(S.worldDirty || moving) || now - (S.lastDraw || 0) < 33) return;
  S.lastDraw = now; S.worldDirty = false;
  const w = s.world, dpr = devicePixelRatio || 1;
  // Camera: the whole map, or (zoomed) half of it following you, or the mind when you're away.
  const vw = S.zoom ? w.w / 2 : w.w, vh = S.zoom ? w.h / 2 : w.h;
  const ts = Math.floor(wc.clientWidth * dpr / vw);
  if (!ts) return;
  if (wc.width !== Math.round(ts * vw)) { wc.width = Math.round(ts * vw); wc.height = Math.round(ts * vh); S.lastTerrain = ""; }
  const sig = w.terrain.map((r) => r.join("")).join("") + ts;
  if (sig !== S.lastTerrain) { terrainCanvas = buildTerrain(w, ts); S.lastTerrain = sig; }
  const focus = w.visitor || w.body;
  const camT = [Math.min(Math.max(focus.x + .5 - vw / 2, 0), w.w - vw), Math.min(Math.max(focus.y + .5 - vh / 2, 0), w.h - vh)];
  if (!S.cam || !S.zoom) S.cam = camT.slice();
  S.cam[0] += (camT[0] - S.cam[0]) * .12; S.cam[1] += (camT[1] - S.cam[1]) * .12;
  S.view = { x: S.cam[0], y: S.cam[1], w: vw, h: vh };
  wg.setTransform(1, 0, 0, 1, 0, 0);
  wg.clearRect(0, 0, wc.width, wc.height);
  wg.translate(-S.cam[0] * ts, -S.cam[1] * ts);
  wg.drawImage(terrainCanvas, 0, 0);
  // water shimmer
  const t = now / 1000;
  wg.font = `${ts * .72}px "Segoe UI Emoji","Apple Color Emoji","Noto Color Emoji",sans-serif`;
  wg.textAlign = "center"; wg.textBaseline = "middle";
  const lamps = [];
  for (const e of w.entities) {
    const cx = e.x * ts + ts / 2, cy = e.y * ts + ts / 2;
    if (e.kind === "lamp" && e.on) lamps.push([cx, cy]);
    wg.globalAlpha = e.kind === "lamp" && !e.on ? .55 : 1;
    const bob = e.kind === "cat" ? Math.sin(t * 3 + e.id) * ts * .03 : 0;
    wg.fillText(EMOJI[e.kind] || "?", cx, cy + bob + ts * .04);
  }
  wg.globalAlpha = 1;
  // body (smoothly interpolated)
  const b = w.body, target = [b.x * ts + ts / 2, b.y * ts + ts / 2];
  if (!bodyPos || Math.hypot(bodyPos[0] - target[0], bodyPos[1] - target[1]) > ts * 3) bodyPos = target.slice();
  bodyPos[0] += (target[0] - bodyPos[0]) * .25; bodyPos[1] += (target[1] - bodyPos[1]) * .25;
  S.moving = Math.hypot(target[0] - bodyPos[0], target[1] - bodyPos[1]) > .5 || Math.hypot(camT[0] - S.cam[0], camT[1] - S.cam[1]) > .01;
  const [bx, by] = bodyPos, r = ts * .36 * (1 + Math.sin(t * 2) * .03);
  const glow = wg.createRadialGradient(bx, by, r * .2, bx, by, r * 2.2);
  glow.addColorStop(0, "rgba(180,140,255,.55)"); glow.addColorStop(1, "rgba(124,156,255,0)");
  wg.fillStyle = glow; wg.beginPath(); wg.arc(bx, by, r * 2.2, 0, 7); wg.fill();
  const body = wg.createRadialGradient(bx - r * .3, by - r * .3, r * .1, bx, by, r);
  body.addColorStop(0, "#ffffff"); body.addColorStop(.45, "#9fb4ff"); body.addColorStop(1, "#7a52e0");
  wg.fillStyle = body; wg.beginPath(); wg.arc(bx, by, r, 0, 7); wg.fill();
  const f = { north: [0, -1], south: [0, 1], west: [-1, 0], east: [1, 0] }[b.facing] || [0, 1];
  if (b.sleeping) {
    wg.strokeStyle = "#1a1f3a"; wg.lineWidth = Math.max(1, ts * .05);
    for (const s2 of [-1, 1]) { wg.beginPath(); wg.moveTo(bx + s2 * r * .35 - r * .12, by); wg.lineTo(bx + s2 * r * .35 + r * .12, by); wg.stroke(); }
    wg.fillStyle = "#fff"; wg.font = `${ts * .35}px system-ui`; wg.fillText("z", bx + r, by - r - Math.sin(t * 2) * 4); wg.fillText("Z", bx + r * 1.5, by - r * 1.6 - Math.sin(t * 2 + 1) * 4);
  } else {
    wg.fillStyle = "#1a1f3a";
    const blink = (t % 4) < .12 ? .2 : 1;
    for (const s2 of [-1, 1]) {
      const ex = bx + f[0] * r * .35 + (f[1] !== 0 ? s2 * r * .32 : 0), ey = by + f[1] * r * .3 + (f[0] !== 0 ? s2 * r * .3 : 0) - r * .1;
      wg.beginPath(); wg.ellipse(ex, ey, r * .1, r * .14 * blink, 0, 0, 7); wg.fill();
    }
  }
  if (b.holding) { wg.font = `${ts * .45}px "Segoe UI Emoji","Apple Color Emoji",sans-serif`; wg.fillText(EMOJI[b.holding] || "", bx + r * .9, by + r * .6); }
  // you
  const v = w.visitor;
  let vx = null, vy = null;
  if (v) {
    const vt = [v.x * ts + ts / 2, v.y * ts + ts / 2];
    if (!S.youPos || Math.hypot(S.youPos[0] - vt[0], S.youPos[1] - vt[1]) > ts * 3) S.youPos = vt.slice();
    S.youPos[0] += (vt[0] - S.youPos[0]) * .35; S.youPos[1] += (vt[1] - S.youPos[1]) * .35;
    if (Math.hypot(vt[0] - S.youPos[0], vt[1] - S.youPos[1]) > .5) S.moving = true;
    [vx, vy] = S.youPos;
    const vr = ts * .34;
    const vg = wg.createRadialGradient(vx - vr * .3, vy - vr * .3, vr * .1, vx, vy, vr);
    vg.addColorStop(0, "#fff6e0"); vg.addColorStop(.5, "#ffb547"); vg.addColorStop(1, "#e0702a");
    wg.fillStyle = vg; wg.beginPath(); wg.arc(vx, vy, vr, 0, 7); wg.fill();
    wg.strokeStyle = "rgba(255,255,255,.9)"; wg.lineWidth = Math.max(1, ts * .05); wg.stroke();
    const vf = { north: [0, -1], south: [0, 1], west: [-1, 0], east: [1, 0] }[v.facing] || [0, 1];
    wg.fillStyle = "#3a1d08";
    for (const s2 of [-1, 1]) {
      const ex = vx + vf[0] * vr * .35 + (vf[1] !== 0 ? s2 * vr * .32 : 0), ey = vy + vf[1] * vr * .3 + (vf[0] !== 0 ? s2 * vr * .3 : 0) - vr * .1;
      wg.beginPath(); wg.arc(ex, ey, vr * .11, 0, 7); wg.fill();
    }
    wg.font = `600 ${Math.max(9 * dpr, ts * .3)}px system-ui`; wg.fillStyle = "#fff";
    wg.fillText("you", vx, vy + vr + ts * .22);
    if (v.holding) { wg.font = `${ts * .45}px "Segoe UI Emoji","Apple Color Emoji",sans-serif`; wg.fillText(EMOJI[v.holding] || "", vx + vr * .9, vy + vr * .5); }
  }
  // placement preview
  if (tool && S.hover && mode === "add") {
    const { x: hx, y: hy } = S.hover, blocked = tool !== "erase" && BLOCKED.has(w.terrain[hy]?.[hx]);
    wg.strokeStyle = blocked ? "rgba(255,107,122,.95)" : "rgba(255,255,255,.9)"; wg.lineWidth = Math.max(1, ts * .06);
    wg.strokeRect(hx * ts + 1, hy * ts + 1, ts - 2, ts - 2);
    if (tool !== "erase" && !blocked) {
      wg.globalAlpha = .6; wg.font = `${ts * .72}px "Segoe UI Emoji","Apple Color Emoji","Noto Color Emoji",sans-serif`;
      wg.fillText(EMOJI[tool], hx * ts + ts / 2, hy * ts + ts / 2 + ts * .04); wg.globalAlpha = 1;
    }
  }
  // night
  const dark = 1 - w.light;
  if (dark > .02) {
    wg.save(); wg.fillStyle = `rgba(8,12,40,${dark * .85})`;
    wg.fillRect(0, 0, w.w * ts, w.h * ts);
    wg.globalCompositeOperation = "lighter";
    for (const [lx, ly] of [...lamps, [bx, by]]) {
      const rr = (lx === bx && ly === by ? 1.6 : 4.5) * ts;
      const lg = wg.createRadialGradient(lx, ly, 0, lx, ly, rr);
      lg.addColorStop(0, `rgba(255,220,150,${dark * .45})`); lg.addColorStop(1, "rgba(255,220,150,0)");
      wg.fillStyle = lg; wg.beginPath(); wg.arc(lx, ly, rr, 0, 7); wg.fill();
    }
    wg.restore();
  }
  // speech bubbles
  if (b.said) bubble(b.said, bx, by, r, ts, dpr, "rgba(255,255,255,.95)");
  if (v && v.said) bubble(v.said, vx, vy, ts * .34, ts, dpr, "rgba(255,226,180,.97)");
  wg.setTransform(1, 0, 0, 1, 0, 0);
}

function bubble(said, bx, by, r, ts, dpr, color) {
  const text = said.length > 70 ? said.slice(0, 70) + "…" : said;
  wg.font = `${Math.max(11 * dpr, ts * .38)}px system-ui`;
  const tw = Math.min(wg.measureText(text).width, ts * 10) + ts * .5, th = ts * .7;
  const left = S.view.x * ts, top = S.view.y * ts;
  let x = Math.min(Math.max(bx - tw / 2, left + 4), left + wc.width - tw - 4), y = by - r - th - ts * .3;
  if (y < top + 4) y = by + r + ts * .3;
  wg.fillStyle = color; wg.beginPath(); wg.roundRect(x, y, tw, th, th / 2.5); wg.fill();
  wg.fillStyle = "#1a2233"; wg.textAlign = "left"; wg.fillText(text, x + ts * .25, y + th / 2, ts * 10);
  wg.textAlign = "center";
}
requestAnimationFrame(drawWorld);

function tileAt(e) {
  const rect = wc.getBoundingClientRect(), w = S.snap.world, vw = S.view || { x: 0, y: 0, w: w.w, h: w.h };
  return { x: Math.min(w.w - 1, Math.max(0, Math.floor(vw.x + (e.clientX - rect.left) / rect.width * vw.w))),
           y: Math.min(w.h - 1, Math.max(0, Math.floor(vw.y + (e.clientY - rect.top) / rect.height * vw.h))) };
}
function setZoom(on) { S.zoom = on; S.worldDirty = true; $("#btnZoom").textContent = on ? "🗺️ Whole map" : "🔍 Zoom in"; }
$("#btnZoom").onclick = () => setZoom(!S.zoom);
wc.addEventListener("mousemove", (e) => { if (S.snap) { S.hover = tileAt(e); S.worldDirty = true; } });
wc.addEventListener("mouseleave", () => { S.hover = null; S.worldDirty = true; });
wc.addEventListener("click", async (e) => {
  wc.focus();
  if (!S.snap || mode !== "add") return;
  if (!tool) { toast("Choose an item below the map first, then click where it should go."); return; }
  const { x, y } = tileAt(e);
  let text = "";
  if (tool === "sign") { text = prompt("What should the sign say?") || ""; if (!text) return; }
  if (tool === "book") text = prompt("Write the book's text (leave empty for a random FineWeb page):") || "";
  toast(await worldApi("place", { kind: tool, x, y, text }));
});

// Keys go to whoever you are controlling: the mind (Guide), else your own avatar if you joined.
const MIND_KEYS = { ArrowUp: "north", w: "north", ArrowDown: "south", s: "south", ArrowLeft: "west", a: "west", ArrowRight: "east", d: "east",
  e: "use", f: "take", g: "drop", l: "look", v: "speak", z: "sleep", q: "approach", " ": "rest" };
const YOU_KEYS = { ArrowUp: "north", w: "north", ArrowDown: "south", s: "south", ArrowLeft: "west", a: "west", ArrowRight: "east", d: "east",
  f: "take", g: "give", h: "pet" };
wc.addEventListener("keydown", async (e) => {
  const k = e.key.length === 1 ? e.key.toLowerCase() : e.key;
  if (mode === "guide") {
    const a = MIND_KEYS[k];
    if (a) { e.preventDefault(); api("act", { action: a }); }
    return;
  }
  if (!S.snap?.world.visitor) return;
  if (k === "t") { e.preventDefault(); sayFromWorld(); return; }
  const a = YOU_KEYS[k];
  if (a) { e.preventDefault(); const msg = await worldApi("you", { action: a }); if (msg) toast(msg); }
});
$$("[data-act]").forEach((b) => b.onclick = () => api("act", { action: b.dataset.act }));

function renderBody(s) {
  const w = s.world, b = w.body;
  $("#worldTime").textContent = `${w.time} · day ${Math.floor(w.tick / 720) + 1}`;
  $("#barEnergy").style.width = `${b.energy}%`; $("#valEnergy").textContent = Math.round(b.energy);
  $("#barEnergy").style.background = b.energy < 25 ? css("--bad") : b.energy < 50 ? css("--warn") : css("--good");
  $("#barFun").style.width = `${b.fun}%`; $("#valFun").textContent = Math.round(b.fun);
  setText($("#bodyFacts"), `${b.sleeping ? "Sleeping · " : ""}holding ${b.holding || "nothing"} · ${fmt(b.steps)} steps · ${b.visited} places visited · fainted ${b.faints}× · reward ${b.reward}`);
  const mx = Math.max(...s.policy, 1e-6);
  setHTML($("#policy"), s.actions.map((a, i) => `<div title="${a}: ${(s.policy[i] * 100).toFixed(1)}%"><i style="height:${Math.round(s.policy[i] / mx * 70)}%"></i><span>${a}</span></div>`).join(""));
  $("#policy").style.height = "110px";
  setHTML($("#worldLog"), w.log.slice().reverse().map((l) => `<li>${esc(l)}</li>`).join(""));
  const v = w.visitor, jb = $("#btnJoin");
  if (!!v !== !!S.hadVisitor) { S.hadVisitor = !!v; setZoom(!!v); }   // follow yourself while you're in the world
  jb.textContent = v ? "Leave the world" : "Join the world";
  jb.classList.toggle("primary", !v); jb.classList.toggle("joined", !!v);
  $("#youHolding").textContent = v ? (v.holding ? `${EMOJI[v.holding]} ${v.holding}` : "nothing") : "(join first)";
}

connect();
