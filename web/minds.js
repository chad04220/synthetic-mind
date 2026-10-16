"use strict";
// Zen (and the Sprite beside it): their state, everything Zen has made, and the stream of what happens.
// Shared by the overlay on the 3D view, the Zen tab and the Keepsakes tab.

const Community = (() => {
  const st = { minds: [], byName: {}, works: new Map(), feed: [], selected: null, filter: "all",
               onSelect: null, playing: null, sort: "new", thumbs: new Map(), sprite: null, loved: new Set() };
  const NEED_ICON = { energy: "🍞", water: "💧", rest: "😴", warmth: "🔥", health: "❤️", boredom: "🥱" };
  const NEED_NAME = { energy: "Food", water: "Water", rest: "Rest", warmth: "Warmth", health: "Health", boredom: "Boredom (higher is worse)" };
  const KIND_ICON = { painting: "🖼️", music: "💿", sculpture: "🗿", building: "🏠", poem: "📜", writing: "📜" };
  const HAPPEN_ICON = { rainbow: "🌈", weather: "🌦️", dusk: "🌇", night: "🌙", dawn: "🌅", visitor: "👋", found: "📍", fainted: "😵", season: "🍂" };
  const mood = (m) => {
    const f = m.feelings || [];
    if (m.sleeping) return ["😴", "asleep"];
    if (m.waiting) return ["🤔", "waiting for an answer"];
    if (f.some((x) => /happy|content|good|well/.test(x))) return ["😊", f.join(", ")];
    if (f.some((x) => /very|hurt|faint|freezing|starving/.test(x))) return ["😟", f.join(", ")];
    if (f.some((x) => /bored/.test(x))) return ["🥱", f.join(", ")];
    if (f.length) return ["😐", f.join(", ")];
    return ["🙂", "fine"];
  };
  const color = (m) => m?.color || "#9fb4ff";
  const e = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const place = (m) => [m.place, m.biome ? (window.Chunks ? Chunks.label(m.biome) : m.biome) : ""].filter(Boolean).join(" · ");

  function setMinds(list) { st.minds = list || []; st.byName = Object.fromEntries(st.minds.map((m) => [m.name, m])); }
  function setSprite(s) { st.sprite = s; }
  function addWorks(list) { for (const c of list || []) if (c && c.id != null) st.works.set(c.id, Object.assign({}, st.works.get(c.id) || {}, c)); }
  function addFeed(ev) { st.feed.push(ev); if (st.feed.length > 400) st.feed.shift(); }

  // ------------------------------------------------------------------ small pieces
  function needBars(m, compact) {
    return `<div class="nbars${compact ? " compact" : ""}">` + Object.entries(m.needs || {}).map(([k, v]) => {
      const c = k === "boredom" ? (v > 60 ? "var(--bad)" : v > 35 ? "var(--warn)" : "color-mix(in srgb, var(--warn) 55%, var(--muted))") : v < 25 ? "var(--bad)" : v < 50 ? "var(--warn)" : "var(--good)";
      return `<div class="nb" title="${e(NEED_NAME[k] || k)}: ${Math.round(v)}"><span>${NEED_ICON[k] || k[0]}</span><i><b style="width:${v}%;background:${c}"></b></i></div>`;
    }).join("") + "</div>";
  }
  const avatar = (m, size = 34) => `<span class="av" style="--c:${color(m)};width:${size}px;height:${size}px;font-size:${size * 0.55}px">${m.glyph || "✨"}</span>`;
  const spriteAv = (size = 30) => `<span class="av sprite-av" style="width:${size}px;height:${size}px"></span>`;
  function spriteWords(s) {
    if (!s) return "";
    return s.state === "listening" ? "is listening…" : s.state === "answering" ? (s.said ? "is answering" : "is thinking…") : "floats nearby";
  }

  // ------------------------------------------------------------------ the strip on the 3D view: Zen and the Sprite
  function strip(el) {
    if (!el) return;
    const m = st.minds[0], s = st.sprite;
    if (!m) { if (el._h !== "") { el._h = ""; el.innerHTML = ""; } return; }
    const [face, why] = mood(m);
    const html = `<button class="mchip${st.selected === m.name ? " on" : ""}" data-mind="${e(m.name)}" title="${e(m.name)} · ${e(why)}">
        ${avatar(m, 30)}<span class="mc-text"><b>${e(m.name)} <i>${face}</i></b><small>${e(m.doing || m.activity || why)}</small></span></button>
      <button class="mchip sprite-chip state-${e(s?.state || "idle")}" data-mind="sprite" title="The Sprite of All Knowing">
        ${spriteAv(30)}<span class="mc-text"><b>The Sprite</b><small>${e(spriteWords(s))}</small></span></button>`;
    if (el._h !== html) { el._h = html; el.innerHTML = html; }
  }

  // ------------------------------------------------------------------ Zen, in full (the overlay card)
  function card(m) {
    if (!m) return '<div class="muted">Waiting for Zen…</div>';
    const [face, why] = mood(m);
    return `<div class="mcard" style="--c:${color(m)}">
      <div class="mc-head">${avatar(m, 42)}<div><h3>${e(m.name)}</h3>
        <div class="muted">${face} ${e(why)}${m.wet > 0.4 ? " · 💧 wet" : ""}</div></div></div>
      ${needBars(m)}
      <div class="mc-now"><small>NOW</small><div>${e(m.doing ? m.doing[0].toUpperCase() + m.doing.slice(1) : m.sleeping ? "Sleeping" : "…")}</div>
        ${m.last ? `<div class="muted">last deed: <b>${e(m.last)}</b>${m.lastText ? ` · ${e(m.lastText)}` : ""}</div>` : ""}</div>
      ${m.said ? `<div class="mc-thought">🗨️ “${e(m.said)}”</div>` : ""}
      ${m.thought ? `<div class="mc-thought">💭 ${e(m.thought)}</div>` : ""}
      <div class="mc-row"><span>📍 ${e(place(m) || "somewhere")}</span>${m.hands?.length ? `<span>✋ ${e(m.hands.join(", "))}</span>` : ""}<span>🧠 brain v${m.brain || 0} · ${e(m.stage || "Static")}</span></div>
    </div>`;
  }
  function artSkills(a) {    // how good Zen has become at each art (running scores), as tiny bars
    if (!a || typeof a !== "object") return '<div class="muted">Nothing made yet.</div>';
    const rows = [["painting", "🎨", "Painting"], ["music", "🎵", "Music"], ["sculpture", "🗿", "Sculpture"], ["poem", "📜", "Writing"]];
    return `<div class="art-skills">${rows.map(([k, ic, name]) => {
      const raw = a[k] ?? a[{ painting: "paint", music: "compose", sculpture: "sculpt", poem: "write" }[k]];
      const v = Math.max(0, Math.min(1, +raw || 0));
      return `<div class="bar"><span>${ic} ${name}</span><div><i style="width:${Math.round(v * 100)}%;background:linear-gradient(90deg,#e9a944,#f6d77a)"></i></div><b>${raw == null ? "–" : v.toFixed(2)}</b></div>`;
    }).join("")}</div>`;
  }

  // ------------------------------------------------------------------ the stream of what happens
  function feedItem(ev) {
    const zen = st.minds[0]?.name || "Zen", who = `<b style="color:${color(st.minds[0])}">${e(zen)}</b>`;
    switch (ev.kind) {
      case "ada_says": return !ev.text || ev.text === "…" ? "" : `<div class="fi talk">${who}${ev.to === "sprite" ? ' <span class="muted">→ the Sprite</span>' : ""}<div>“${e(ev.text)}”</div></div>`;
      case "chat": return ev.asleep ? "" : `<div class="fi talk">💬 <b>You</b> <span class="muted">${e(ev.user)}</span><div>${who}: ${e(ev.text)}</div></div>`;
      case "answer":
        if (ev.by === "critique") return `<div class="fi sprite">🌟 <b class="spr">The Sprite</b> <span class="muted">${e(ev.question || "looks at Zen's work")}</span><div>${e(ev.text)}</div></div>`;
        return `<div class="fi sprite">❓ ${ev.by === "you" ? "<b>You</b>" : who} <span class="muted">ask${ev.by === "you" ? "" : "s"}</span> ${e(ev.question)}<div>🌟 ${e(ev.text)}</div></div>`;
      case "created": { const c = ev.creation || {}; return `<div class="fi made">${KIND_ICON[c.kind] || "✨"} ${who} made <span class="chip work" data-work="${c.id}">${e(c.title || (c.kind === "music" ? "a song" : `a ${c.kind}`))}</span></div>`; }
      case "happening": return `<div class="fi happen">${HAPPEN_ICON[ev.what] || "•"} ${e(ev.text)}</div>`;
      case "milestone": return `<div class="fi made">🌱 ${e(ev.title)}</div>`;
      default: return "";
    }
  }
  function feed(el, kinds, n = 80) {
    if (!el) return;
    const items = st.feed.filter((x) => !kinds || kinds.includes(x.kind)).slice(-n).reverse().map(feedItem).filter(Boolean).join("");
    if (el._h !== items) { el._h = items; el.innerHTML = items || '<div class="muted">Nothing yet. The world is waking up.</div>'; }
  }

  // ------------------------------------------------------------------ keepsakes
  const KIND_NAME = { painting: "Paintings", music: "Songs", sculpture: "Sculptures", poem: "Writing" };
  const isV3 = (c) => c?.data?.v === 3;
  const skillOf = (c) => { const s = c?.data?.skill; return typeof s === "number" && !isV3(c) ? s : null; };
  const crit = (c) => (c?.critique && typeof c.critique === "object" ? c.critique : null);
  const totalOf = (c) => { const s = c?.data?.score; return typeof s === "number" ? s : typeof s?.total === "number" ? s.total : null; };
  const rank = (c) => crit(c)?.score != null ? crit(c).score / 10 : totalOf(c) ?? skillOf(c) ?? -1;
  const marksOf = (c) => c?.data?.marks ?? (c?.data?.ops ? String(c.data.ops).length : null);
  const titleOf = (c) => c.title || (c.kind === "music" ? "Untitled song" : "Untitled");
  function skillPill(c, long) {
    const s = skillOf(c); if (s === null) return "";
    const lvl = s < 0.25 ? "first tries" : s < 0.45 ? "learning" : s < 0.65 ? "getting good" : s < 0.85 ? "skilled" : "masterful";
    return long ? `<div class="wskill" title="${e(lvl)}"><span>${e(c.author)}'s skill: <b>${s.toFixed(2)}</b> <i class="muted">${lvl}</i></span><i><b style="width:${Math.round(s * 100)}%"></b></i></div>`
      : `<span class="spill" title="skill when this was made: ${s.toFixed(2)} (${lvl})"><i style="width:${Math.round(s * 100)}%"></i></span>`;
  }
  function scoreBars(c) {
    const s = c?.data?.score; if (!s || typeof s !== "object") return "";
    const parts = Object.entries(s).filter(([k, v]) => k !== "total" && typeof v === "number");
    if (!parts.length) return "";
    return `<div class="wscore"><small>HOW IT MEASURES UP${totalOf(c) != null ? ` · ${Math.round(totalOf(c) * 100)}%` : ""}</small>${parts.map(([k, v]) =>
      `<div class="sb"><span>${e(k.replace(/_/g, " "))}</span><i><b style="width:${Math.round(Math.max(0, Math.min(1, v)) * 100)}%"></b></i><em>${v.toFixed(2)}</em></div>`).join("")}</div>`;
  }
  const loveBtn = (c, big) => `<button class="love${st.loved.has(c.id) ? " on" : ""}${big ? " big" : ""}" data-love="${c.id}" title="Love it: Zen feels it, and learns your taste" aria-label="Love this piece">♥ <span>${c.loves || 0}</span></button>`;
  const poemLines = (c) => (c.data?.lines?.length ? c.data.lines : String(c.text || c.data?.text || "").split(/\n/)).filter((l) => l.trim());
  function workBody(c) {
    switch (c.kind) {
      case "painting": return `<div class="frame"><div class="mat"><canvas width="${isV3(c) ? 384 : 320}" height="${isV3(c) ? 288 : 240}" data-art="paint"></canvas></div></div>`;
      case "sculpture": return `<div class="plinthbox"><canvas width="400" height="300" data-art="sculpt"></canvas></div>`;
      case "music": return `<div class="roll"><canvas width="400" height="300" data-roll="${c.id}"></canvas>
        <button class="play" data-play="${c.id}" aria-label="Play">${st.playing === c.id ? "■" : "▶"}</button>
        <span class="mtag">piano · ${(c.data?.notes || []).filter((n) => n[0] > 0).length} notes · ${c.data?.tempo || 100} bpm</span></div>`;
      case "poem": case "writing": {
        const lines = poemLines(c);
        return `<div class="poemcard"><div class="pform">${e(c.data?.form || "words at the desk")}</div>${lines.length ? lines.slice(0, 8).map((l) => `<p>${e(l)}</p>`).join("") : `<p class="muted">(still writing…)</p>`}${lines.length > 8 ? "<p>…</p>" : ""}</div>`;
      }
      default: return `<div class="built">${KIND_ICON[c.kind] || "✨"}</div>`;
    }
  }
  function gallery(el, chips) {
    if (!el) return;
    const all = [...st.works.values()];
    if (chips) {
      const count = (k) => all.filter((c) => k === "all" || c.kind === k || (k === "poem" && c.kind === "writing")).length;
      const ch = ["all", "painting", "music", "sculpture", "poem"].map((k) =>
        `<button class="${st.filter === k ? "on" : ""}" data-gfilter="${k}">${k === "all" ? "All" : `${KIND_ICON[k]} ${KIND_NAME[k]}`} <small>${count(k)}</small></button>`).join("")
        + `<span class="gsp"></span><select data-gsort aria-label="Sort"><option value="new" ${st.sort === "new" ? "selected" : ""}>Newest first</option><option value="best" ${st.sort === "best" ? "selected" : ""}>The Sprite liked best</option><option value="loved" ${st.sort === "loved" ? "selected" : ""}>Most loved</option></select>`;
      if (chips._h !== ch) { chips._h = ch; chips.innerHTML = ch; }
    }
    const works = all.filter((c) => st.filter === "all" || c.kind === st.filter || (st.filter === "poem" && c.kind === "writing"))
      .sort((a, b) => st.sort === "best" ? rank(b) - rank(a) || b.t - a.t : st.sort === "loved" ? (b.loves || 0) - (a.loves || 0) || b.t - a.t : (b.t || b.id) - (a.t || a.id)).slice(0, 160);
    st.shown = works.map((c) => c.id);
    const key = works.map((c) => `${c.id}:${c.title}:${(c.text || "").length}:${crit(c)?.score}:${c.loves || 0}:${st.loved.has(c.id)}`).join("|") + st.filter + st.sort;
    if (el._key === key) return;
    el._key = key;
    el.innerHTML = works.length ? works.map((c) => {
      const cr = crit(c), m = marksOf(c);
      return `<figure class="work ${e(c.kind)}" data-work="${c.id}" tabindex="0">
      <div class="wmedia">${workBody(c)}</div>
      <figcaption><div class="wtitle"><b>${e(titleOf(c))}</b>${loveBtn(c)}</div>
        <span class="wmeta">day ${c.day ?? "?"}${c.season ? ", " + e(c.season) : ""}${m ? ` · ${m} marks` : ""}${skillPill(c)}</span>
        ${cr ? `<div class="wcrit"><span class="cscore" title="The Sprite's score">🌟 ${(+cr.score).toFixed(1)}<small>/10</small></span><span class="csee">${e(cr.see || cr.say || "")}</span></div>`
          : isV3(c) ? '<div class="wcrit pending"><span class="muted">The Sprite hasn\'t looked yet…</span></div>' : ""}
      </figcaption></figure>`;
    }).join("")
      : '<div class="muted gempty">Nothing here yet. When Zen paints at the easel, plays the piano, shapes clay or writes at the desk, what it makes stays here.</div>';
    for (const fig of el.querySelectorAll("figure.work")) {
      const c = st.works.get(+fig.dataset.work), cv = fig.querySelector("canvas[data-art], canvas[data-roll]");
      if (!c || !cv) continue;
      const cached = st.thumbs.get(c.id);
      if (cached && cv.dataset.art) { cv.width = cached.width; cv.height = cached.height; cv.getContext("2d").drawImage(cached, 0, 0); continue; }
      const keep = () => { const k = document.createElement("canvas"); k.width = cv.width; k.height = cv.height; k.getContext("2d").drawImage(cv, 0, 0); st.thumbs.set(c.id, k); };
      if (cv.dataset.art === "paint") Art.paintLater(cv, c.data || {}, Art.paint, keep);
      else if (cv.dataset.art === "sculpt") Art.paintLater(cv, c.data || {}, (x, d) => Art.sculpt(x, d).then(keep));
      else Art.roll(cv, c.data || {});
    }
  }
  const say = (t) => (typeof window.toast === "function" ? window.toast(t, 5000) : alert(t));
  async function love(id) {
    const c = st.works.get(+id); if (!c) return;
    st.loved.add(c.id); c.loves = (c.loves || 0) + 1;
    document.querySelectorAll(`[data-love="${c.id}"]`).forEach((b) => { b.classList.add("on", "pop"); b.querySelector("span").textContent = c.loves; setTimeout(() => b.classList.remove("pop"), 400); });
    try {
      const r = await fetch("/api/love", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id: c.id }) });
      const j = await r.json().catch(() => ({})); if (!r.ok) throw new Error(j.detail || r.statusText);
      say(typeof j.result === "string" && j.result ? j.result : `♥ ${st.minds[0]?.name || "Zen"} feels that you love it.`);
    } catch (err) { c.loves = Math.max(0, c.loves - 1); say(err.message); }
    Community.onChange && Community.onChange();
  }

  // ---- songs
  function play(id) {
    const c = st.works.get(+id);
    if (!c) return;
    if (st.playing === c.id) { Art.stop(); return; }
    Art.stop();
    st.playing = c.id;
    const set = (on) => document.querySelectorAll(`[data-play="${c.id}"]`).forEach((b) => { b.textContent = b.classList.contains("big") ? (on ? "■ Stop" : "▶ Play") : (on ? "■" : "▶"); b.classList.toggle("on", on); });
    set(true);
    Art.play(c.data || {}, () => {
      if (st.playing === c.id) st.playing = null;
      set(false);
      document.querySelectorAll(`canvas[data-roll="${c.id}"]`).forEach((cv) => Art.roll(cv, c.data || {}));
    });
    animate(c);
  }
  function animate(c) {
    const tick = () => {
      if (st.playing !== c.id) return;
      const at = Art.audioTime();
      document.querySelectorAll(`canvas[data-roll="${c.id}"]`).forEach((cv) => Art.roll(cv, c.data || {}, at));
      const viz = document.querySelector(`canvas[data-viz="${c.id}"]`);
      if (viz) visualize(viz);
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }
  function idleViz(cv, d) {
    const g = cv.getContext("2d"), W = cv.width, H = cv.height;
    g.fillStyle = "#0d1120"; g.fillRect(0, 0, W, H);
    const ns = (d.notes || []).filter((n) => n[0] > 0);
    if (ns.length > 1) {
      const lo = Math.min(...ns.map((n) => n[0])), hi = Math.max(...ns.map((n) => n[0])) + 1;
      g.strokeStyle = "rgba(246,215,122,.35)"; g.lineWidth = 2; g.beginPath();
      ns.forEach((n, i) => { const x = 20 + i / (ns.length - 1) * (W - 40), y = H * 0.8 - (n[0] - lo) / (hi - lo) * H * 0.6; i ? g.lineTo(x, y) : g.moveTo(x, y); });
      g.stroke();
    }
    g.fillStyle = "rgba(220,228,255,.6)"; g.font = "16px system-ui, sans-serif"; g.textAlign = "center"; g.fillText("▶  press play to listen", W / 2, H / 2 + 5);
  }
  function visualize(cv) {
    const p = Art.playing(), g = cv.getContext("2d"), W = cv.width, H = cv.height;
    g.fillStyle = "rgba(13,17,32,.35)"; g.fillRect(0, 0, W, H);
    if (!p) return;
    const an = p.G.analyser, n = an.frequencyBinCount, f = new Uint8Array(n), w = new Uint8Array(an.fftSize);
    an.getByteFrequencyData(f); an.getByteTimeDomainData(w);
    const bars = 64;
    for (let i = 0; i < bars; i++) {
      const lo = Math.floor(Math.pow(i / bars, 2) * n * 0.5), hi = Math.max(lo + 1, Math.floor(Math.pow((i + 1) / bars, 2) * n * 0.5));
      let v = 0; for (let k = lo; k < hi; k++) v = Math.max(v, f[k]);
      const h = (v / 255) * H * 0.9, x = i / bars * W;
      g.fillStyle = `hsla(${210 + i * 2.2},85%,${55 + v / 12}%,.85)`; g.fillRect(x + 1, H - h, W / bars - 2, h);
    }
    g.strokeStyle = "rgba(255,230,170,.75)"; g.lineWidth = 1.5; g.beginPath();
    for (let i = 0; i < w.length; i += 4) { const x = i / w.length * W, y = H * 0.4 + (w[i] - 128) / 128 * H * 0.35; i ? g.lineTo(x, y) : g.moveTo(x, y); }
    g.stroke();
  }

  // ------------------------------------------------------------------ a single work, large
  let orbit = null, lapse = null;
  function closeViewer() {
    if (orbit) { try { orbit.dispose(); } catch { /* gone */ } orbit = null; }
    if (lapse) { try { lapse.dispose(); } catch { /* gone */ } lapse = null; }
  }
  function download(blob, name) {
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name; document.body.append(a); a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 2000);
  }
  const fileName = (c, ext) => `${String(c.title || c.kind).replace(/[^\w\- ]+/g, "").trim().replace(/\s+/g, "-").toLowerCase() || "keepsake"}-${String(c.author || "zen").toLowerCase()}.${ext}`;
  function critBlock(c) {
    const cr = crit(c);
    if (!cr) return isV3(c) ? `<div class="wverdict pending"><span class="sprite-av sm"></span><div><b>The Sprite hasn't looked yet</b><p class="muted">When its mind is ready it looks at each piece and tells Zen what it sees.</p></div></div>` : "";
    const v = Math.max(0, Math.min(10, +cr.score || 0));
    return `<div class="wverdict"><div class="vscore"><b>${v.toFixed(1)}</b><small>/10</small><i><u style="width:${v * 10}%"></u></i></div>
      <div class="vwords">${cr.see ? `<p><small>THE SPRITE SAW</small>${e(cr.see)}</p>` : ""}${cr.say ? `<p class="vsay"><small>IT TOLD ${e((c.author || "Zen").toUpperCase())}</small>“${e(cr.say)}”</p>` : ""}</div></div>`;
  }
  function showWork(id) {
    const c = st.works.get(+id);
    if (!c) return;
    closeViewer();
    let dlg = document.getElementById("workDlg");
    if (!dlg) {
      dlg = document.createElement("dialog"); dlg.id = "workDlg"; document.body.append(dlg);
      dlg.addEventListener("click", (ev) => { if (ev.target === dlg) dlg.close(); });
      dlg.addEventListener("close", () => { closeViewer(); if (st.playing && dlg.dataset.work == st.playing) Art.stop(); });
      dlg.addEventListener("keydown", (ev) => { if (ev.target.matches("input")) return; if (ev.key === "ArrowRight" || ev.key === "ArrowLeft") { const n = step(ev.key === "ArrowRight" ? 1 : -1); if (n) showWork(n); } });
    }
    dlg.dataset.work = c.id;
    const d = c.data || {}, v3 = isV3(c) && !!d.ops;
    let art = "", actions = "";
    if (c.kind === "painting") { art = `<div class="frame big"><div class="mat"><canvas width="1280" height="960" data-big></canvas></div></div>`; actions = `<button data-dl="png">⬇ PNG</button>`; }
    else if (c.kind === "sculpture") { art = `<div class="orbitbox" data-orbit><canvas width="640" height="640" data-still></canvas><span class="hint">Drag to turn · scroll to come closer</span></div>`; actions = `<button data-dl="spng">⬇ PNG</button>`; }
    else if (c.kind === "music") {
      art = `<div class="songbox"><canvas width="1100" height="200" data-viz="${c.id}" class="viz"></canvas><canvas width="1100" height="190" data-roll="${c.id}" class="bigroll"></canvas>
        <div class="songmeta">piano · ${(d.notes || []).filter((n) => n[0] > 0).length} notes · ${d.tempo || 100} bpm${d.tempo_changes?.length ? ` · ${d.tempo_changes.length} tempo change${d.tempo_changes.length > 1 ? "s" : ""}` : ""}</div></div>`;
      actions = `<button class="primary big" data-play="${c.id}">${st.playing === c.id ? "■ Stop" : "▶ Play"}</button><button data-dl="wav">⬇ WAV</button>`;
    } else if (c.kind === "poem" || c.kind === "writing") { art = `<div class="poemcard big"><div class="pform">${e(d.form || "words at the desk")}</div>${poemLines(c).map((l) => `<p>${e(l)}</p>`).join("")}</div>`; actions = `<button data-dl="txt">⬇ Text</button>`; }
    else art = `<div class="built big">${KIND_ICON[c.kind] || "✨"}</div>`;
    if (v3) actions = `<button data-lapse="${c.id}" title="Watch it being made, mark by mark">⏱ Time-lapse</button>` + actions;
    const nav = st.shown?.length > 1 ? `<button class="wnav prev" data-wstep="-1" aria-label="Previous">‹</button><button class="wnav next" data-wstep="1" aria-label="Next">›</button>` : "";
    const m = marksOf(c);
    dlg.innerHTML = `<div class="wd wd-${e(c.kind)}">${nav}<div class="wd-art"><div class="wd-main">${art}</div><div class="wd-lapse" hidden></div></div>
      <aside class="wd-info"><div class="wkind">${KIND_ICON[c.kind] || ""} ${e(c.kind === "music" ? "song" : c.kind)}</div>
        <h2>${e(titleOf(c))}</h2>
        <div class="wby">${avatar(st.minds[0] || {}, 26)} <span>by <b>${e(c.author || "Zen")}</b></span>${loveBtn(c, true)}</div>
        <div class="muted">Day ${c.day ?? "?"}${c.season ? ", " + e(c.season) : ""}${d.place ? " · " + e(d.place) : ""}${m ? ` · made in ${m} marks` : ""}${d.seconds ? ` over ${Math.round(d.seconds / 60) || "<1"} min` : ""}</div>
        ${critBlock(c)}
        ${c.description ? `<p class="wdesc">${e(c.description)}</p>` : ""}
        ${scoreBars(c)}
        ${skillPill(c, true)}
        <div class="wactions">${actions}<form method="dialog"><button>Close</button></form></div>
      </aside></div>`;
    if (!dlg.open) dlg.showModal();
    setTimeout(() => {
      if (dlg.dataset.work != c.id) return;
      const big = dlg.querySelector("canvas[data-big]"); if (big) Art.paint(big, d);
      const roll = dlg.querySelector("canvas[data-roll]"); if (roll) Art.roll(roll, d, st.playing === c.id ? Art.audioTime() : -1);
      const viz = dlg.querySelector("canvas[data-viz]"); if (viz) idleViz(viz, d);
      const ob = dlg.querySelector("[data-orbit]");
      if (ob) {
        const still = ob.querySelector("canvas[data-still]");
        if (isV3(c) && d.voxels != null) { Studio.sculpt(still, d); Studio.mountOrbit(ob, d).then((o) => { if (dlg.dataset.work != c.id || !dlg.open) { o.dispose(); return; } orbit = o; still.remove(); }).catch((err) => console.warn(err)); }
        else {
          Art.sculpt2d(still, d);
          Art.load3d().then((mod) => { if (!mod || dlg.dataset.work != c.id || !dlg.open) return; try { orbit = mod.mountOrbit(ob, d); still.remove(); } catch (err) { console.warn(err); mod.renderTo(still, d); } });
        }
      }
    }, 30);
    dlg.querySelectorAll("[data-dl]").forEach((b) => b.addEventListener("click", async () => {
      const kind = b.dataset.dl;
      if (kind === "png") dlg.querySelector("canvas[data-big]").toBlob((bl) => download(bl, fileName(c, "png")));
      else if (kind === "spng") {
        const cv = document.createElement("canvas"); cv.width = cv.height = 1024;
        if (isV3(c)) Studio.sculpt(cv, d); else { const mod = await Art.load3d(); if (mod) await mod.renderTo(cv, d); else Art.sculpt2d(cv, d); }
        cv.toBlob((bl) => download(bl, fileName(c, "png")));
      } else if (kind === "txt") download(new Blob([`${titleOf(c)}\nby ${c.author || "Zen"}\n\n${poemLines(c).join("\n")}\n`], { type: "text/plain" }), fileName(c, "txt"));
      else if (kind === "wav") {
        const was = b.textContent; b.disabled = true; b.textContent = "Recording…";
        try { download(await Art.render(d), fileName(c, "wav")); } catch (err) { say("Couldn't record: " + err.message); }
        finally { b.disabled = false; b.textContent = was; }
      }
    }));
    const lb = dlg.querySelector("[data-lapse]");
    if (lb) lb.addEventListener("click", () => {
      const box = dlg.querySelector(".wd-lapse"), main = dlg.querySelector(".wd-main"), on = box.hidden;
      box.hidden = !on; main.hidden = on; lb.classList.toggle("on", on); lb.textContent = on ? "✕ Finished piece" : "⏱ Time-lapse";
      if (on) { lapse = Studio.player(box, c); box.querySelector(".tl-play")?.click(); }
      else if (lapse) { lapse.dispose(); lapse = null; }
    });
  }
  function step(dir) {
    const list = st.shown || [], dlg = document.getElementById("workDlg"), i = list.indexOf(+dlg?.dataset.work);
    if (i < 0 || !list.length) return null;
    return list[(i + dir + list.length) % list.length];
  }
  function refreshViewer(id) {      // a title or the Sprite's verdict arrived for the piece on screen
    const dlg = document.getElementById("workDlg");
    if (dlg?.open && dlg.dataset.work == id && !dlg.querySelector(".wd-lapse:not([hidden])")) showWork(id);
  }

  document.addEventListener("click", (ev) => {
    const t = ev.target.closest("[data-mind],[data-play],[data-work],[data-gfilter],[data-wstep],[data-love]");
    if (!t) return;
    if (t.dataset.love) { ev.stopPropagation(); love(t.dataset.love); return; }
    if (t.dataset.wstep) { const n = step(+t.dataset.wstep); if (n) showWork(n); return; }
    if (t.dataset.play) { ev.stopPropagation(); play(t.dataset.play); return; }
    if (t.dataset.gfilter) { st.filter = t.dataset.gfilter; return Community.onChange && Community.onChange(); }
    if (t.dataset.mind) { st.selected = t.dataset.mind; st.onSelect && st.onSelect(t.dataset.mind); return Community.onChange && Community.onChange(); }
    if (t.dataset.work && !t.closest("dialog")) showWork(t.dataset.work);
  });
  document.addEventListener("keydown", (ev) => {
    const f = ev.target.closest?.("figure.work[data-work]");
    if (f && ev.target === f && (ev.key === "Enter" || ev.key === " ")) { ev.preventDefault(); showWork(f.dataset.work); }
  });
  document.addEventListener("change", (ev) => {
    if (ev.target.matches("[data-gsort]")) { st.sort = ev.target.value; Community.onChange && Community.onChange(); }
  });

  return { st, setMinds, setSprite, addWorks, addFeed, strip, card, artSkills, needBars, feed, gallery, showWork, refreshViewer, mood, color, KIND_ICON, onChange: null };
})();
window.Community = Community;
