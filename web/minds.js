"use strict";
// The two minds: the synth and its companion. Their state, everything they have made, and the stream of
// what they say and do and what happens around them. Shared by the overlay on the 3D view and the
// Together, Stories and Keepsakes tabs.

const Community = (() => {
  const st = { minds: [], byName: {}, works: new Map(), feed: [], selected: null, filter: "all", author: "",
               onSelect: null, playing: null, stories: [] };
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
      ${full && made.length ? `<div class="mc-made"><small>MADE</small>${made.map((c) => `<span class="chip work" data-work="${c.id}">${KIND_ICON[c.kind] || "✨"} ${e(c.title || c.kind)}</span>`).join("")}</div>` : ""}
      ${full && m.diary?.length ? `<div class="mc-diary"><small>LATELY</small>${m.diary.slice(-6).reverse().map((d) => `<div>${e(d)}</div>`).join("")}</div>` : ""}
    </div>`;
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
  function gallery(el, chips) {
    if (!el) return;
    const authors = [...new Set([...st.works.values()].map((c) => c.author))];
    if (chips) {
      const ch = ["all", "painting", "music", "sculpture", "building", "poem"].map((k) =>
        `<button class="${st.filter === k ? "on" : ""}" data-gfilter="${k}">${k === "all" ? "All" : (KIND_ICON[k] + " " + k[0].toUpperCase() + k.slice(1) + (k === "music" ? "" : "s"))}</button>`).join("")
        + `<select data-gauthor><option value="">Everyone</option>${authors.map((a) => `<option ${st.author === a ? "selected" : ""}>${e(a)}</option>`).join("")}</select>`;
      if (chips._h !== ch) { chips._h = ch; chips.innerHTML = ch; }
    }
    const works = [...st.works.values()].filter((c) => (st.filter === "all" || c.kind === st.filter || (st.filter === "poem" && c.kind === "writing"))
      && (!st.author || c.author === st.author)).sort((a, b) => b.t - a.t).slice(0, 120);
    const key = works.map((c) => c.id + ":" + c.title + ":" + (c.text || "").length).join("|") + st.filter + st.author;
    if (el._key === key) return;
    el._key = key;
    el.innerHTML = works.length ? works.map((c) => `<figure class="work ${c.kind}" data-work="${c.id}">
      ${c.kind === "painting" || c.kind === "sculpture" ? `<canvas width="320" height="${c.kind === "painting" ? 220 : 260}"></canvas>` : ""}
      ${c.kind === "music" ? `<div class="roll"><canvas width="320" height="90"></canvas><button class="play" data-play="${c.id}">▶ Play</button></div>` : ""}
      ${c.kind === "poem" || c.kind === "writing" ? `<blockquote>${e(c.text || "(still writing…)").replace(/\n/g, "<br>")}</blockquote>` : ""}
      ${c.kind === "building" ? `<div class="built">${(st.kinds?.[c.data?.what]?.glyph) || "🏠"}<small>${e(c.data?.what || "")} · ${e(c.data?.place || "")}</small></div>` : ""}
      <figcaption><b>${e(c.title || "Untitled")}</b><span class="muted">${KIND_ICON[c.kind] || ""} by ${e(c.author)} · day ${c.day}, ${e(c.season || "")}</span></figcaption></figure>`).join("")
      : '<div class="muted" style="padding:20px">Nothing has been made yet: paintings at the easel, songs at the piano, sculptures in clay, poems and birdhouses.</div>';
    for (const fig of el.querySelectorAll("figure.work")) {
      const c = st.works.get(+fig.dataset.work), cv = fig.querySelector("canvas");
      if (!c || !cv) continue;
      if (c.kind === "painting") Art.paint(cv, c.data || {});
      else if (c.kind === "sculpture") Art.sculpt(cv, c.data || {});
      else if (c.kind === "music") roll(cv, c.data || {});
    }
  }
  function roll(cv, d) {             // a little piano roll of the melody
    const g = cv.getContext("2d"), W = cv.width, H = cv.height, notes = d.notes || [];
    g.fillStyle = "#0f172a"; g.fillRect(0, 0, W, H);
    const total = notes.reduce((s, n) => s + n[1], 0) || 1, ps = notes.filter((n) => n[0] > 0).map((n) => n[0]);
    const lo = Math.min(...ps, 60) - 2, hi = Math.max(...ps, 72) + 2;
    let x = 0;
    for (const [p, b] of notes) {
      const w = b / total * W;
      if (p > 0) { const y = H - (p - lo) / (hi - lo) * H; g.fillStyle = `hsl(${200 + (p % 12) * 12},80%,65%)`; g.fillRect(x + 1, y - 4, Math.max(2, w - 2), 7); }
      x += w;
    }
  }
  function play(id, btn) {
    const c = st.works.get(+id);
    if (!c) return;
    if (st.playing === c.id) { Art.stop(); return; }
    st.playing = c.id;
    btn && (btn.textContent = "■ Stop");
    Art.play(c.data || {}, () => { st.playing = null; document.querySelectorAll(`[data-play="${c.id}"]`).forEach((b) => b.textContent = "▶ Play"); });
  }

  // ------------------------------------------------------------------ a single work, large
  function showWork(id) {
    const c = st.works.get(+id);
    if (!c) return;
    let dlg = document.getElementById("workDlg");
    if (!dlg) { dlg = document.createElement("dialog"); dlg.id = "workDlg"; document.body.append(dlg); dlg.addEventListener("click", (ev) => { if (ev.target === dlg) dlg.close(); }); }
    dlg.innerHTML = `<div class="wd">${c.kind === "painting" || c.kind === "sculpture" ? `<canvas width="720" height="${c.kind === "painting" ? 480 : 520}"></canvas>` : ""}
      ${c.kind === "music" ? `<canvas width="720" height="160"></canvas><button class="primary" data-play="${c.id}">▶ Play</button>` : ""}
      ${c.kind === "poem" || c.kind === "writing" ? `<blockquote class="big">${e(c.text || "").replace(/\n/g, "<br>")}</blockquote>` : ""}
      <h2>${e(c.title || "Untitled")}</h2><div class="muted">${KIND_ICON[c.kind] || ""} ${e(c.kind)} by ${e(c.author)} · day ${c.day}, ${e(c.season || "")}</div>
      <form method="dialog"><button>Close</button></form></div>`;
    const cv = dlg.querySelector("canvas");
    if (cv && c.kind === "painting") Art.paint(cv, c.data || {});
    if (cv && c.kind === "sculpture") Art.sculpt(cv, c.data || {});
    if (cv && c.kind === "music") roll(cv, c.data || {});
    dlg.showModal();
  }

  document.addEventListener("click", (ev) => {
    const t = ev.target.closest("[data-mind],[data-play],[data-work],[data-gfilter]");
    if (!t) return;
    if (t.dataset.play) { ev.stopPropagation(); play(t.dataset.play, t); return; }
    if (t.dataset.gfilter) { st.filter = t.dataset.gfilter; return Community.onChange && Community.onChange(); }
    if (t.dataset.mind) { st.selected = t.dataset.mind; st.onSelect && st.onSelect(t.dataset.mind); return Community.onChange && Community.onChange(); }
    if (t.dataset.work) showWork(t.dataset.work);
  });
  document.addEventListener("change", (ev) => {
    if (ev.target.matches("[data-gauthor]")) { st.author = ev.target.value; Community.onChange && Community.onChange(); }
  });

  return { st, setMinds, addWorks, addFeed, addStories, strip, card, grid, feed, stories, gallery, showWork, mood, color, onChange: null };
})();
window.Community = Community;
