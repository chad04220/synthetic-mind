"use strict";
// The community: every mind's state (the synth's and each villager's), the gallery of everything they
// have made, and the stream of what they say and do. Shared by the overlay on the valley and the
// Minds and Gallery tabs.

const Community = (() => {
  const st = { minds: [], byName: {}, works: new Map(), feed: [], selected: null, filter: "all", author: "",
               voices: {}, onSelect: null, playing: null };
  const NEED_ICON = { energy: "🍞", water: "💧", rest: "😴", warmth: "🔥", company: "🤝", fun: "🎈" };
  const KIND_ICON = { painting: "🖼️", music: "💿", sculpture: "🗿", building: "🏗️", writing: "📜" };
  const mood = (m) => {
    const f = m.feelings || [];
    if (m.sleeping) return ["😴", "asleep"];
    if (m.talking_with) return ["💬", `talking with ${m.talking_with}`];
    if (f.includes("happy")) return ["😊", "happy"];
    if (f.some((x) => /very/.test(x))) return ["😟", f.join(", ")];
    if (f.length) return ["😐", f.join(", ")];
    return ["🙂", "fine"];
  };
  const color = (m) => m.color || "#9fb4ff";
  const glyph = (m) => m.kind === "synth" ? "✨" : (m.glyph || "🙂");
  const e = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  function setMinds(list) {
    st.minds = list || [];
    st.byName = Object.fromEntries(st.minds.map((m) => [m.name, m]));
  }
  function addWorks(list) { for (const c of list || []) st.works.set(c.id, c); }
  function addFeed(ev) {
    st.feed.push(ev); if (st.feed.length > 300) st.feed.shift();
  }

  // ------------------------------------------------------------------ small pieces
  function needBars(m, compact) {
    return `<div class="nbars${compact ? " compact" : ""}">` + Object.entries(m.needs || {}).map(([k, v]) => {
      const c = v < 25 ? "var(--bad)" : v < 50 ? "var(--warn)" : "var(--good)";
      return `<div class="nb" title="${k}: ${v}"><span>${NEED_ICON[k] || ""}</span><i><b style="width:${v}%;background:${c}"></b></i></div>`;
    }).join("") + "</div>";
  }
  function avatar(m, size = 34) {
    return `<span class="av" style="--c:${color(m)};width:${size}px;height:${size}px;font-size:${size * 0.55}px">${glyph(m)}</span>`;
  }

  // ------------------------------------------------------------------ the strip on the valley
  function strip(el) {
    if (!el) return;
    const html = st.minds.map((m) => {
      const [face, why] = mood(m);
      return `<button class="mchip${st.selected === m.name ? " on" : ""}" data-mind="${e(m.name)}" title="${e(m.name)} · ${e(why)}">
        ${avatar(m, 30)}<span class="mc-text"><b>${e(m.name)} <i>${face}</i></b><small>${e((m.doing || "").replace(/^I /, "").slice(0, 34))}</small></span></button>`;
    }).join("");
    if (el._h !== html) { el._h = html; el.innerHTML = html; }
  }

  // ------------------------------------------------------------------ one mind, in full
  function card(m, full) {
    if (!m) return '<div class="muted">Choose someone to see their mind.</div>';
    const [face, why] = mood(m);
    const voice = st.voices[m.name];
    const friends = Object.entries(m.friends || {}).slice(0, full ? 8 : 3)
      .map(([n, v]) => `<span class="friend" title="${v}/100">${e(n)} <i style="width:${v}%"></i></span>`).join("");
    const made = [...st.works.values()].filter((c) => c.author === m.name).slice(-6).reverse();
    const src = { self: "own words", "own words": "own words", needs: "needs", you: "your idea" }[m.source] || m.source || "";
    return `<div class="mcard" style="--c:${color(m)}">
      <div class="mc-head">${avatar(m, 46)}<div><h3>${e(m.name)} <span class="muted">${m.kind === "synth" ? "the synth" : "the " + e(m.role)}</span></h3>
        <div class="muted">${face} ${e(why)} · ${e(m.place)}${m.coins != null ? ` · 🪙 ${m.coins}` : ""}</div></div></div>
      ${needBars(m)}
      <div class="mc-now"><small>NOW</small><div>${e(m.doing || (m.sleeping ? "Sleeping" : "…"))}</div>
        ${m.why ? `<div class="muted">Why: ${e(m.why)}</div>` : ""}${src ? `<span class="badge ${src === "own words" ? "self" : "needs"}">${e(src)}</span>` : ""}</div>
      ${m.thought ? `<div class="mc-thought">💭 ${e(m.thought)}</div>` : ""}
      <div class="mc-row"><span title="Share of recent choices made in its own words">🗣️ ${Math.round((m.own_words || 0) * 100)}% own words</span>
        <span>🎨 ${m.made || 0} works</span>${m.carrying?.length ? `<span>🎒 ${e(m.carrying.join(", "))}</span>` : ""}
        ${m.kind === "synth" ? `<span>🧠 brain v${m.brain || 0}</span>` : voice ? `<span class="voice ${voice.status}">🎙️ ${e(voice.status)}${voice.model ? " · " + e(voice.model) : ""}</span>` : ""}</div>
      ${friends ? `<div class="mc-friends"><small>FRIENDS</small>${friends}</div>` : ""}
      ${full && made.length ? `<div class="mc-made"><small>MADE</small>${made.map((c) => `<span class="chip work" data-work="${c.id}">${KIND_ICON[c.kind] || "✨"} ${e(c.title || c.kind)}</span>`).join("")}</div>` : ""}
      ${full && m.diary?.length ? `<div class="mc-diary"><small>DIARY</small>${m.diary.slice().reverse().map((d) => `<div>${e(d)}</div>`).join("")}</div>` : ""}
    </div>`;
  }

  function grid(el) {
    if (!el) return;
    const html = st.minds.map((m) => card(m, true)).join("");
    if (el._h !== html) { el._h = html; el.innerHTML = html; }
  }

  // ------------------------------------------------------------------ the stream of community life
  function feedItem(ev) {
    const who = (n) => `<b style="color:${color(st.byName[n] || {})}">${e(n)}</b>`;
    switch (ev.kind) {
      case "npc": case "ada_says":
        if (ev.text === "…") return "";
        return `<div class="fi talk">${who(ev.name)}${ev.to ? ` <span class="muted">→ ${e(ev.to)}</span>` : ""}<div>${e(ev.text)}</div></div>`;
      case "vthought": return `<div class="fi thought">💭 ${who(ev.name)} <i>${e(ev.text)}</i></div>`;
      case "created": { const c = ev.creation || {}; return `<div class="fi made">${KIND_ICON[c.kind] || "✨"} ${who(c.author)} made <span class="chip work" data-work="${c.id}">${e(c.title || c.kind)}</span></div>`; }
      case "vdid": return ev.ok === false ? "" : `<div class="fi did">${who(ev.name)} <span class="muted">${e(ev.text)}</span></div>`;
      case "talk": return `<div class="fi muted">💬 ${e(ev.members.join(" & "))} talked about ${e(ev.topic)}</div>`;
      case "quest": return `<div class="fi made">🏅 ${e(ev.text)}</div>`;
      default: return "";
    }
  }
  function feed(el, kinds) {
    if (!el) return;
    const items = st.feed.filter((x) => !kinds || kinds.includes(x.kind)).slice(-80).reverse().map(feedItem).filter(Boolean).join("");
    if (el._h !== items) { el._h = items; el.innerHTML = items || '<div class="muted">Nothing yet. The valley is waking up.</div>'; }
  }

  // ------------------------------------------------------------------ the gallery
  function gallery(el, chips) {
    if (!el) return;
    const authors = [...new Set([...st.works.values()].map((c) => c.author))];
    if (chips) {
      const ch = ["all", "painting", "music", "sculpture", "building", "writing"].map((k) =>
        `<button class="${st.filter === k ? "on" : ""}" data-gfilter="${k}">${k === "all" ? "All" : (KIND_ICON[k] + " " + k[0].toUpperCase() + k.slice(1) + (k === "music" ? "" : "s"))}</button>`).join("")
        + `<select data-gauthor><option value="">Everyone</option>${authors.map((a) => `<option ${st.author === a ? "selected" : ""}>${e(a)}</option>`).join("")}</select>`;
      if (chips._h !== ch) { chips._h = ch; chips.innerHTML = ch; }
    }
    const works = [...st.works.values()].filter((c) => (st.filter === "all" || c.kind === st.filter) && (!st.author || c.author === st.author))
      .sort((a, b) => b.t - a.t).slice(0, 120);
    const key = works.map((c) => c.id + ":" + c.title + ":" + (c.text || "").length).join("|") + st.filter + st.author;
    if (el._key === key) return;
    el._key = key;
    el.innerHTML = works.length ? works.map((c) => `<figure class="work ${c.kind}" data-work="${c.id}">
      ${c.kind === "painting" || c.kind === "sculpture" ? `<canvas width="320" height="${c.kind === "painting" ? 220 : 260}"></canvas>` : ""}
      ${c.kind === "music" ? `<div class="roll"><canvas width="320" height="90"></canvas><button class="play" data-play="${c.id}">▶ Play</button></div>` : ""}
      ${c.kind === "writing" ? `<blockquote>${e(c.text || "(still writing…)").replace(/\n/g, "<br>")}</blockquote>` : ""}
      ${c.kind === "building" ? `<div class="built">${(st.kinds?.[c.data?.what]?.glyph) || "🏗️"}<small>${e(c.data?.what || "")} · ${e(c.data?.place || "")}</small></div>` : ""}
      <figcaption><b>${e(c.title || "Untitled")}</b><span class="muted">${KIND_ICON[c.kind] || ""} by ${e(c.author)} · day ${c.day}, ${e(c.season || "")}</span></figcaption></figure>`).join("")
      : '<div class="muted" style="padding:20px">Nothing has been made yet. Give them time, materials and tools.</div>';
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
      ${c.kind === "writing" ? `<blockquote class="big">${e(c.text || "").replace(/\n/g, "<br>")}</blockquote>` : ""}
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

  return { st, setMinds, addWorks, addFeed, strip, card, grid, feed, gallery, showWork, mood, color, onChange: null };
})();
window.Community = Community;
