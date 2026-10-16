"use strict";
// The two minds: the synth and its companion. Their state, everything they have made, and the stream of
// what they say and do and what happens around them. Shared by the overlay on the 3D view and the
// Together, Stories and Keepsakes tabs.

const Community = (() => {
  const st = { minds: [], byName: {}, works: new Map(), feed: [], selected: null, filter: "all", author: "",
               onSelect: null, playing: null, stories: [], sort: "new", thumbs: new Map() };
  const NEED_ICON = { energy: "🍞", water: "💧", rest: "😴", warmth: "🔥", company: "🤝", fun: "🎈", clean: "🛁" };
  const KIND_ICON = { painting: "🖼️", music: "💿", sculpture: "🗿", building: "🏠", poem: "📜", writing: "📜" };
  const HAPPEN_ICON = { rainbow: "🌈", weather: "🌦️", egg: "🥚", rooster: "🐓", boiled: "🫖", cooked: "🍲", baked: "🍞",
                        burnt: "💨", ripe: "🌾", plant_died: "🥀", rotted: "🪰", fire_out: "🔥", light_out: "🕯️", cat_ate: "🐈",
                        deer: "🦌", dusk: "🌇", night: "🌙", dawn: "🌅", carried: "🛏️", visitor: "👋", moved: "🏡" };
  const mood = (m) => {
    const f = m.feelings || [];
    if (m.sleeping) return ["😴", "asleep"];
    if (m.talking) return ["💬", "talking"];
    if (f.includes("happy")) return ["😊", "happy"];
    if (f.some((x) => /very/.test(x))) return ["😟", f.join(", ")];
    if (f.length) return ["😐", f.join(", ")];
    return ["🙂", "fine"];
  };
  const color = (m) => m?.color || "#9fb4ff";
  const glyph = (m) => m.glyph || "🙂";
  const e = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  function setMinds(list) {
    st.minds = list || [];
    st.byName = Object.fromEntries(st.minds.map((m) => [m.name, m]));
  }
  function addWorks(list) { for (const c of list || []) st.works.set(c.id, c); }
  function addFeed(ev) {
    st.feed.push(ev); if (st.feed.length > 400) st.feed.shift();
  }
  function addStories(list) {
    const seen = new Set(st.stories.map((s) => s.t));
    for (const s of list || []) if (!seen.has(s.t)) { st.stories.push(s); seen.add(s.t); }
    st.stories.sort((a, b) => a.t - b.t);
  }

  // ------------------------------------------------------------------ small pieces
  function needBars(m, compact) {
    return `<div class="nbars${compact ? " compact" : ""}">` + Object.entries(m.needs || {}).map(([k, v]) => {
      const c = v < 25 ? "var(--bad)" : v < 50 ? "var(--warn)" : "var(--good)";
      return `<div class="nb" title="${k}: ${Math.round(v)}"><span>${NEED_ICON[k] || ""}</span><i><b style="width:${v}%;background:${c}"></b></i></div>`;
    }).join("") + "</div>";
  }
  function avatar(m, size = 34) {
    return `<span class="av" style="--c:${color(m)};width:${size}px;height:${size}px;font-size:${size * 0.55}px">${glyph(m)}</span>`;
  }

  // ------------------------------------------------------------------ the strip on the 3D view
  function strip(el) {
    if (!el) return;
    const html = st.minds.map((m) => {
      const [face, why] = mood(m);
      return `<button class="mchip${st.selected === m.name ? " on" : ""}" data-mind="${e(m.name)}" title="${e(m.name)} · ${e(why)}">
        ${avatar(m, 30)}<span class="mc-text"><b>${e(m.name)} <i>${face}</i></b><small>${e((m.activity || m.doing || "").replace(/^I /, "").slice(0, 36))}</small></span></button>`;
    }).join("");
    if (el._h !== html) { el._h = html; el.innerHTML = html; }
  }

  // ------------------------------------------------------------------ one mind, in full
  function card(m, full) {
    if (!m) return '<div class="muted">Choose someone to see their mind.</div>';
    const [face, why] = mood(m);
    const synth = m.kind === "synth";
    const made = [...st.works.values()].filter((c) => c.author === m.name).slice(-6).reverse();
    const src = { self: "own words", needs: "its needs", you: "your idea", companion: "Wren's words" }[m.source] || "";
    const srcLabel = m.source === "companion" ? `${m.companion || "Wren"}'s words` : src;
    return `<div class="mcard" style="--c:${color(m)}">
      <div class="mc-head">${avatar(m, 46)}<div><h3>${e(m.name)} <span class="muted">${synth ? "the synth" : "the companion"}</span></h3>
        <div class="muted">${face} ${e(why)} · ${e(m.place)}${m.wet > 0.4 ? " · 💧 wet" : ""}</div></div></div>
      ${needBars(m)}
      <div class="mc-now"><small>NOW</small><div>${e(m.activity ? m.activity[0].toUpperCase() + m.activity.slice(1) : m.doing || (m.sleeping ? "Sleeping" : "…"))}</div>
        ${m.why ? `<div class="muted">Why: ${e(m.why)}</div>` : ""}${srcLabel ? `<span class="badge ${src === "own words" ? "self" : "needs"}">${e(srcLabel)}</span>` : ""}
        ${m.steps ? `<span class="muted"> · ${m.steps} more step${m.steps === 1 ? "" : "s"} after this</span>` : ""}</div>
      ${m.said ? `<div class="mc-thought">🗨️ “${e(m.said)}”</div>` : ""}
      ${m.thought ? `<div class="mc-thought">💭 ${e(m.thought)}</div>` : ""}
      <div class="mc-row">${synth
        ? `<span title="Share of recent choices made in its own words">🗣️ ${Math.round((m.own_words || 0) * 100)}% own words</span><span>🧠 brain v${m.brain || 0} · ${e(m.stage || "Static")}</span>`
        : `<span title="How Wren looks after the synth right now">🤲 ${e(m.care || "")}</span><span title="Share of Wren's recent choices made by its language model">🪶 ${Math.round((m.own_words || 0) * 100)}% chosen by its model</span>`}
        <span>🎨 ${made.length ? made.length : 0} works</span>${m.carrying?.length ? `<span>🎒 ${e(m.carrying.join(", "))}</span>` : ""}
        <span title="How close they feel">💞 ${Math.round(m.bond || 0)}</span></div>
      ${artSkills(m)}
      ${full && made.length ? `<div class="mc-made"><small>MADE</small>${made.map((c) => `<span class="chip work" data-work="${c.id}">${KIND_ICON[c.kind] || "✨"} ${e(c.title || c.kind)}</span>`).join("")}</div>` : ""}
      ${full && m.diary?.length ? `<div class="mc-diary"><small>LATELY</small>${m.diary.slice(-6).reverse().map((d) => `<div>${e(d)}</div>`).join("")}</div>` : ""}
    </div>`;
  }

  function artSkills(m) {    // how good each mind has become at each art, as four tiny bars
    const a = m.art;
    if (!a || typeof a !== "object") return "";
    const rows = [["painting", "🎨", "Painting"], ["music", "🎵", "Music"], ["sculpture", "🗿", "Sculpture"], ["poem", "📜", "Poems"]];
    return `<div class="mc-art"><small>ART</small>${rows.map(([k, ic, name]) => {
      const v = Math.max(0, Math.min(1, +a[k] || 0));
      return `<span class="ab" title="${name}: ${v.toFixed(2)}"><span>${ic}</span><i><b style="width:${Math.round(v * 100)}%"></b></i></span>`;
    }).join("")}</div>`;
  }

  function grid(el) {
    if (!el) return;
    const html = st.minds.map((m) => card(m, true)).join("");
    if (el._h !== html) { el._h = html; el.innerHTML = html; }
  }

  // ------------------------------------------------------------------ the stream of life at the homestead
  function feedItem(ev) {
    const who = (n) => `<b style="color:${color(st.byName[n] || {})}">${e(n)}</b>`;
    switch (ev.kind) {
      case "wren_says": case "ada_says": case "npc": {
        if (!ev.text || ev.text === "…") return "";
        const name = ev.kind === "ada_says" ? ev.who || st.minds[0]?.name : ev.name || st.minds[1]?.name;
        return `<div class="fi talk">${who(name)}${ev.to ? ` <span class="muted">→ ${e(ev.to)}</span>` : ""}<div>${e(ev.text)}</div></div>`;
      }
      case "talk":
        if (!ev.text || ev.text === "…") return "";
        return `<div class="fi talk">💬 ${who(ev.name)}<div>${e(ev.text)}</div></div>`;
      case "answer": return `<div class="fi talk">❓ ${e(ev.question)}<div>${e(ev.text)}</div></div>`;
      case "wren_thought": return `<div class="fi thought">💭 ${who(st.minds[1]?.name || "Wren")} <i>${e(ev.text)}</i></div>`;
      case "created": { const c = ev.creation || {}; return `<div class="fi made">${KIND_ICON[c.kind] || "✨"} ${who(c.author)} made <span class="chip work" data-work="${c.id}">${e(c.title || c.kind)}</span></div>`; }
      case "wren_did": return ev.ok === false ? "" : `<div class="fi did">${who(st.minds[1]?.name || "Wren")} <span class="muted">${e(ev.text)}</span></div>`;
      case "happening": return `<div class="fi happen">${HAPPEN_ICON[ev.what] || "•"} ${e(ev.text)}</div>`;
      case "story": return `<div class="fi made">📖 Bedtime story: <b>${e(ev.title)}</b></div>`;
      case "milestone": return `<div class="fi made">🌱 ${e(ev.title)}</div>`;
      default: return "";
    }
  }
  function feed(el, kinds, n = 80) {
    if (!el) return;
    const items = st.feed.filter((x) => !kinds || kinds.includes(x.kind)).slice(-n).reverse().map(feedItem).filter(Boolean).join("");
    if (el._h !== items) { el._h = items; el.innerHTML = items || '<div class="muted">Nothing yet. The hollow is waking up.</div>'; }
  }

  // ------------------------------------------------------------------ bedtime stories
  function stories(el) {
    if (!el) return;
    const key = st.stories.length + ":" + (st.stories.at(-1)?.t || 0);
    if (el._key === key) return;
    el._key = key;
    el.innerHTML = st.stories.length ? st.stories.slice().reverse().map((s) => `<article class="story">
      <div class="muted">Day ${s.day}${s.season ? ", " + e(s.season) : ""}</div><h3>${e(s.title)}</h3><p>${e(s.text)}</p></article>`).join("")
      : '<div class="card muted">No stories yet. The first one is told at the end of the first day.</div>';
  }

  // ------------------------------------------------------------------ keepsakes
  const KIND_NAME = { painting: "Paintings", music: "Songs", sculpture: "Sculptures", building: "Buildings", poem: "Poems" };
  const skillOf = (c) => { const s = c?.data?.skill; return typeof s === "number" ? s : null; };
  function skillPill(c, long) {
    const s = skillOf(c);
    if (s === null) return "";
    const lvl = s < 0.25 ? "first tries" : s < 0.45 ? "learning" : s < 0.65 ? "getting good" : s < 0.85 ? "skilled" : "masterful";
    return long
      ? `<div class="wskill" title="${e(lvl)}"><span>${e(c.author)}'s skill: <b>${s.toFixed(2)}</b> <i class="muted">${lvl}</i></span><i><b style="width:${Math.round(s * 100)}%"></b></i></div>`
      : `<span class="spill" title="${e(c.author)}'s skill when this was made: ${s.toFixed(2)} (${lvl})"><i style="width:${Math.round(s * 100)}%"></i></span>`;
  }
  const poemLines = (c) => (c.data?.lines?.length ? c.data.lines : String(c.text || "").split(/\n/)).filter((l) => l.trim());
  function workBody(c) {
    switch (c.kind) {
      case "painting": return `<div class="frame"><div class="mat"><canvas width="320" height="240" data-art="paint"></canvas></div></div>`;
      case "sculpture": return `<div class="plinthbox"><canvas width="400" height="300" data-art="sculpt"></canvas></div>`;
      case "music": return `<div class="roll"><canvas width="400" height="300" data-roll="${c.id}"></canvas>
        <button class="play" data-play="${c.id}" aria-label="Play">${st.playing === c.id ? "■" : "▶"}</button>
        <span class="mtag">${e(c.data?.instruments?.melody || c.data?.instrument || "piano")} · ${e(c.data?.mode || c.data?.scale || "")} · ${c.data?.tempo || ""} bpm</span></div>`;
      case "poem": case "writing": {
        const lines = poemLines(c);
        return `<div class="poemcard"><div class="pform">${e(c.data?.form || "poem")}</div>${lines.length ? lines.slice(0, 8).map((l) => `<p>${e(l)}</p>`).join("") : `<p class="muted">(still writing…)</p>`}${lines.length > 8 ? "<p>…</p>" : ""}</div>`;
      }
      case "building": return `<div class="built">${(st.kinds?.[c.data?.what]?.glyph) || "🏠"}<small>${e(c.data?.what || "")} · ${e(c.data?.place || "")}</small></div>`;
      default: return `<div class="built">${KIND_ICON[c.kind] || "✨"}</div>`;
    }
  }
  function gallery(el, chips) {
    if (!el) return;
    commissionForm();
    const all = [...st.works.values()];
    const authors = [...new Set(all.map((c) => c.author))];
    if (chips) {
      const count = (k) => all.filter((c) => k === "all" || c.kind === k || (k === "poem" && c.kind === "writing")).length;
      const ch = ["all", "painting", "music", "sculpture", "poem", "building"].map((k) =>
        `<button class="${st.filter === k ? "on" : ""}" data-gfilter="${k}">${k === "all" ? "All" : `${KIND_ICON[k]} ${KIND_NAME[k]}`} <small>${count(k)}</small></button>`).join("")
        + `<span class="gsp"></span><select data-gauthor aria-label="Maker"><option value="">Everyone</option>${authors.map((a) => `<option ${st.author === a ? "selected" : ""}>${e(a)}</option>`).join("")}</select>`
        + `<select data-gsort aria-label="Sort"><option value="new" ${st.sort !== "best" ? "selected" : ""}>Newest first</option><option value="best" ${st.sort === "best" ? "selected" : ""}>Best first</option></select>`;
      if (chips._h !== ch) { chips._h = ch; chips.innerHTML = ch; }
    }
    const works = all.filter((c) => (st.filter === "all" || c.kind === st.filter || (st.filter === "poem" && c.kind === "writing"))
      && (!st.author || c.author === st.author))
      .sort((a, b) => st.sort === "best" ? (skillOf(b) ?? -1) - (skillOf(a) ?? -1) || b.t - a.t : b.t - a.t).slice(0, 160);
    st.shown = works.map((c) => c.id);
    const key = works.map((c) => c.id + ":" + c.title + ":" + (c.text || "").length + ":" + (c.comments?.length || 0)).join("|") + st.filter + st.author + st.sort;
    if (el._key === key) return;
    el._key = key;
    el.innerHTML = works.length ? works.map((c) => `<figure class="work ${e(c.kind)}" data-work="${c.id}" tabindex="0">
      <div class="wmedia">${workBody(c)}</div>
      <figcaption><b>${e(c.title || "Untitled")}</b>
        <span class="wmeta"><span class="who" style="--c:${color(st.byName[c.author] || {})}">${e(c.author)}</span> · day ${c.day}${c.season ? ", " + e(c.season) : ""}${c.comments?.length ? ` · 💬 ${c.comments.length}` : ""}${skillPill(c)}</span></figcaption></figure>`).join("")
      : '<div class="muted gempty">Nothing here yet: paintings at the easel, songs at the piano, sculptures in clay, poems and birdhouses. Or ask Wren to make something above.</div>';
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

  // ---- ask Wren to make something
  function commissionForm() {
    const box = document.getElementById("commission");
    if (!box || box._ready) return;
    box._ready = true;
    box.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const kind = box.querySelector("[name=kind]").value, about = box.querySelector("[name=about]").value.trim(), btn = box.querySelector("button");
      btn.disabled = true; const was = btn.textContent; btn.textContent = "Asking…";
      try {
        const r = await fetch("/api/commission", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ kind, about }) });
        const j = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(j.detail || r.statusText);
        say(j.result || "Wren will make it soon.");
        box.querySelector("[name=about]").value = "";
      } catch (err) { say(err.message || "Wren couldn't hear that just now."); }
      finally { btn.disabled = false; btn.textContent = was; }
    });
  }
  const say = (t) => (typeof window.toast === "function" ? window.toast(t, 5000) : alert(t));

  // ---- songs
  function play(id, btn) {
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
  function animate(c) {     // the playhead on every roll of this song, and the visualizer
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
  function idleViz(cv, d) {   // before it plays: the melody's contour as a soft line, waiting
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
      g.fillStyle = `hsla(${210 + i * 2.2},85%,${55 + v / 12}%,.85)`;
      g.fillRect(x + 1, H - h, W / bars - 2, h);
    }
    g.strokeStyle = "rgba(255,230,170,.75)"; g.lineWidth = 1.5; g.beginPath();
    for (let i = 0; i < w.length; i += 4) { const x = i / w.length * W, y = H * 0.4 + (w[i] - 128) / 128 * H * 0.35; i ? g.lineTo(x, y) : g.moveTo(x, y); }
    g.stroke();
  }

  // ------------------------------------------------------------------ a single work, large
  let orbit = null;
  function closeViewer() {
    if (orbit) { try { orbit.dispose(); } catch { /* gone */ } orbit = null; }
  }
  function download(blob, name) {
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name; document.body.append(a); a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 2000);
  }
  const fileName = (c, ext) => `${String(c.title || c.kind).replace(/[^\w\- ]+/g, "").trim().replace(/\s+/g, "-").toLowerCase() || "keepsake"}-${String(c.author || "").toLowerCase()}.${ext}`;
  function showWork(id) {
    const c = st.works.get(+id);
    if (!c) return;
    closeViewer();
    let dlg = document.getElementById("workDlg");
    if (!dlg) {
      dlg = document.createElement("dialog"); dlg.id = "workDlg"; document.body.append(dlg);
      dlg.addEventListener("click", (ev) => { if (ev.target === dlg) dlg.close(); });
      dlg.addEventListener("close", () => { closeViewer(); if (st.playing && dlg.dataset.work == st.playing) Art.stop(); });
      dlg.addEventListener("keydown", (ev) => { if (ev.key === "ArrowRight" || ev.key === "ArrowLeft") { const n = step(ev.key === "ArrowRight" ? 1 : -1); if (n) showWork(n); } });
    }
    dlg.dataset.work = c.id;
    const d = c.data || {}, maker = st.byName[c.author] || {};
    let art = "", actions = "";
    if (c.kind === "painting") {
      art = `<div class="frame big"><div class="mat"><canvas width="1200" height="900" data-big></canvas></div></div>`;
      actions = `<button data-dl="png">⬇ Download PNG</button>`;
    } else if (c.kind === "sculpture") {
      art = `<div class="orbitbox" data-orbit><canvas width="640" height="640" data-still></canvas><span class="hint">Drag to turn · scroll to come closer</span></div>`;
      actions = `<button data-dl="spng">⬇ Download PNG</button>`;
    } else if (c.kind === "music") {
      art = `<div class="songbox"><canvas width="1100" height="200" data-viz="${c.id}" class="viz"></canvas><canvas width="1100" height="190" data-roll="${c.id}" class="bigroll"></canvas>
        <div class="songmeta">${e(d.instruments ? `${d.instruments.melody}${d.instruments.harmony && d.instruments.harmony !== "none" ? " with " + d.instruments.harmony : ""}${d.instruments.bass !== "none" && d.instruments.bass ? ", bass" : ""}${d.instruments.percussion !== "none" && d.instruments.percussion ? ", soft drums" : ""}` : d.instrument || "piano")}
        · ${e(d.mode || d.scale || "")} · ${d.tempo || 100} bpm${d.meter ? ` · ${d.meter}/4` : ""}${d.form ? ` · ${e(d.form.join("-"))}` : ""}</div></div>`;
      actions = `<button class="primary big" data-play="${c.id}">${st.playing === c.id ? "■ Stop" : "▶ Play"}</button><button data-dl="wav">⬇ Download WAV</button>`;
    } else if (c.kind === "poem" || c.kind === "writing") {
      art = `<div class="poemcard big"><div class="pform">${e(d.form || "poem")}</div>${poemLines(c).map((l) => `<p>${e(l)}</p>`).join("")}</div>`;
      actions = `<button data-dl="txt">⬇ Download text</button>`;
    } else art = `<div class="built big">${(st.kinds?.[d.what]?.glyph) || "🏠"}<small>${e(d.what || "")} · ${e(d.place || "")}</small></div>`;
    const comments = (c.comments || []).map((k) => `<div class="wcomment"><b style="color:${color(st.byName[k.by] || {})}">${e(k.by || "Wren")}</b><p>${e(k.text)}</p></div>`).join("");
    const nav = st.shown?.length > 1 ? `<button class="wnav prev" data-wstep="-1" aria-label="Previous">‹</button><button class="wnav next" data-wstep="1" aria-label="Next">›</button>` : "";
    dlg.innerHTML = `<div class="wd wd-${e(c.kind)}">${nav}<div class="wd-art">${art}</div>
      <aside class="wd-info"><div class="wkind">${KIND_ICON[c.kind] || ""} ${e(c.kind === "music" ? "song" : c.kind)}</div>
        <h2>${e(c.title || "Untitled")}</h2>
        <div class="wby">${avatar(maker, 26)} <span>by <b style="color:${color(maker)}">${e(c.author)}</b></span></div>
        <div class="muted">Day ${c.day}${c.season ? ", " + e(c.season) : ""}${d.place ? " · " + e(d.place) : ""}</div>
        ${c.description ? `<p class="wdesc">${e(c.description)}</p>` : ""}
        ${c.text && c.kind !== "poem" && c.kind !== "writing" ? `<p class="wtext">“${e(c.text)}”</p>` : ""}
        ${skillPill(c, true)}
        ${comments ? `<div class="wcomments"><small>WHAT ${e((c.comments[0]?.by || "Wren").toUpperCase())} SAID</small>${comments}</div>` : ""}
        <div class="wactions">${actions}<form method="dialog"><button>Close</button></form></div>
      </aside></div>`;
    if (!dlg.open) dlg.showModal();
    // fill in the art once the dialog is on screen
    setTimeout(() => {
      if (dlg.dataset.work != c.id) return;
      const big = dlg.querySelector("canvas[data-big]");
      if (big) Art.paint(big, d);
      const roll = dlg.querySelector("canvas[data-roll]");
      if (roll) Art.roll(roll, d, st.playing === c.id ? Art.audioTime() : -1);
      const viz = dlg.querySelector("canvas[data-viz]");
      if (viz) idleViz(viz, d);
      const ob = dlg.querySelector("[data-orbit]");
      if (ob) {
        const still = ob.querySelector("canvas[data-still]");
        Art.sculpt2d(still, d);
        Art.load3d().then((m) => {
          if (!m || dlg.dataset.work != c.id || !dlg.open) return;
          try { orbit = m.mountOrbit(ob, d); still.remove(); } catch (err) { console.warn(err); m.renderTo(still, d); }
        });
      }
    }, 30);
    dlg.querySelectorAll("[data-dl]").forEach((b) => b.addEventListener("click", async () => {
      const kind = b.dataset.dl;
      if (kind === "png") dlg.querySelector("canvas[data-big]").toBlob((bl) => download(bl, fileName(c, "png")));
      else if (kind === "spng") {
        const cv = document.createElement("canvas"); cv.width = cv.height = 1024;
        const m = await Art.load3d(); if (m) await m.renderTo(cv, d); else Art.sculpt2d(cv, d);
        cv.toBlob((bl) => download(bl, fileName(c, "png")));
      } else if (kind === "txt") download(new Blob([`${c.title || "Untitled"}\nby ${c.author}\n\n${poemLines(c).join("\n")}\n`], { type: "text/plain" }), fileName(c, "txt"));
      else if (kind === "wav") {
        const was = b.textContent; b.disabled = true; b.textContent = "Recording…";
        try { download(await Art.render(d), fileName(c, "wav")); } catch (err) { say("Couldn't record: " + err.message); }
        finally { b.disabled = false; b.textContent = was; }
      }
    }));
  }
  function step(dir) {
    const list = st.shown || [], dlg = document.getElementById("workDlg"), i = list.indexOf(+dlg?.dataset.work);
    if (i < 0 || !list.length) return null;
    return list[(i + dir + list.length) % list.length];
  }

  document.addEventListener("click", (ev) => {
    const t = ev.target.closest("[data-mind],[data-play],[data-work],[data-gfilter],[data-wstep]");
    if (!t) return;
    if (t.dataset.wstep) { const n = step(+t.dataset.wstep); if (n) showWork(n); return; }
    if (t.dataset.play) { ev.stopPropagation(); play(t.dataset.play, t); return; }
    if (t.dataset.gfilter) { st.filter = t.dataset.gfilter; return Community.onChange && Community.onChange(); }
    if (t.dataset.mind) { st.selected = t.dataset.mind; st.onSelect && st.onSelect(t.dataset.mind); return Community.onChange && Community.onChange(); }
    if (t.dataset.work && !t.closest("dialog")) showWork(t.dataset.work);
  });
  document.addEventListener("keydown", (ev) => {
    const f = ev.target.closest?.("figure.work[data-work]");
    if (f && (ev.key === "Enter" || ev.key === " ")) { ev.preventDefault(); showWork(f.dataset.work); }
  });
  document.addEventListener("change", (ev) => {
    if (ev.target.matches("[data-gauthor]")) { st.author = ev.target.value; Community.onChange && Community.onChange(); }
    if (ev.target.matches("[data-gsort]")) { st.sort = ev.target.value; Community.onChange && Community.onChange(); }
  });

  return { st, setMinds, addWorks, addFeed, addStories, strip, card, grid, feed, stories, gallery, showWork, mood, color, onChange: null };
})();
window.Community = Community;
