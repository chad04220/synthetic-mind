"use strict";
// The minimap of the homestead. Drawn only when something changes or moves (and ~3 times a second for
// blinking and weather), because the GPU the browser uses is busy teaching the synth.

const GLYPH = {   // filled in from the World's kinds table too
  "apple": "🍎", "pear": "🍐", "plum": "🟣", "berries": "🫐", "mushroom": "🍄", "carrot": "🥕", "potato": "🥔",
  "tomato": "🍅", "pumpkin": "🎃", "beans": "🫛", "wheat": "🌾", "mint": "🌿", "flower": "🌼", "egg": "🥚", "honey": "🍯",
  "raw fish": "🐟", "flour": "🥡", "dough": "🫓", "bread": "🍞", "apple pie": "🥧", "baked apple": "🍎",
  "roast potato": "🥔", "baked fish": "🍢", "boiled egg": "🥚", "soup": "🍲", "jam": "🫙", "tea": "🍵",
  "cup of water": "🥛", "burnt food": "⬛", "rotten food": "🤢", "carrot seed": "🌰", "seed potato": "🥔",
  "tomato seed": "🌰", "pumpkin seed": "🌰", "bean seed": "🌰", "wheat seed": "🌰", "mint seed": "🌰", "plant": "🌱",
  "apple tree": "🌳", "pear tree": "🌳", "plum tree": "🌳", "berry bush": "🌿", "pot": "🥘", "kettle": "🫖", "cup": "☕",
  "bowl": "🥣", "bucket": "🪣", "watering can": "🚿", "basket": "🧺", "jar": "🫙", "pantry": "🗄️", "toy chest": "🧰",
  "bookshelf": "📚", "nest box": "🪺", "seed tin": "🥫", "fireplace": "🔥", "stove": "♨️", "oven": "🍞", "lamp": "🪔",
  "candle": "🕯️", "matches": "🧯", "log": "🪵", "stick": "🥢", "ash": "🩶", "woodpile": "🪵", "chopping block": "🪓",
  "bed": "🛏️", "sink": "🚰", "table": "🪑", "sofa": "🛋️", "piano": "🎹", "music box": "🎶", "mirror": "🪞",
  "bathtub": "🛁", "towel": "🧣", "desk": "🗒️", "clock": "🕰️", "rug": "🟫", "window": "🪟", "cat bowl": "🥣",
  "quern": "🪨", "workbench": "🛠️", "easel": "🖼️", "water barrel": "🛢️", "compost bin": "🗑️", "scarecrow": "🧑‍🌾",
  "beehive": "🐝", "bird feeder": "🏠", "swing": "🪢", "bench": "🪑", "telescope": "🔭", "sign": "🪧",
  "stepping stone": "⚪", "ball": "⚽", "blocks": "🧱", "teddy": "🧸", "kite": "🪁", "book": "📕", "picture book": "📗",
  "paper": "📄", "pencil": "✏️", "axe": "🪓", "hammer": "🔨", "chisel": "🪛", "fishing rod": "🎣", "clay": "🟤",
  "stone": "🪨", "feather": "🪶", "leaf": "🍂", "pinecone": "🌰", "bouquet": "💐", "snowman": "⛄", "painting": "🖼️",
  "recording": "📼", "sculpture": "🗿", "poem": "📜", "birdhouse": "🏠", "cat": "🐈", "hen": "🐔", "rooster": "🐓",
  "bee": "🐝", "duck": "🦆", "frog": "🐸", "fish": "🐟", "deer": "🦌", "robin": "🐦", "owl": "🦉", "butterfly": "🦋",
  "hedgehog": "🦔",
};
const PEOPLE = {};      // name -> [glyph, colour], from the World
const PORTABLE = ["apple", "pear", "carrot", "potato", "bread", "honey", "egg", "berries", "mint", "flower", "log", "clay",
                  "carrot seed", "bean seed", "book", "picture book", "ball", "blocks", "teddy", "kite", "candle", "towel"];
const PLACEABLE = [...PORTABLE, "lamp", "sign", "music box", "hen", "robin", "butterfly", "hedgehog"];
const BLOCKED = new Set([1, 3, 4, 8, 13, 15, 18]);
const EMOJI_FONT = `"Segoe UI Emoji","Apple Color Emoji","Noto Color Emoji",sans-serif`;

const MapView = (() => {
  const cv = document.getElementById("map"), g = cv.getContext("2d");
  const st = { world: null, ents: new Map(), follow: "ada", tool: null, hover: null, dirty: true, cam: null,
               pos: {}, last: 0, terrainKey: "", terrainImg: null, ts: 0, onClick: null,
               perf: { frames: 0, draws: 0, drawMs: 0, drawMax: 0, gapMax: 0, prev: 0 } };

  function grassColor(season) {
    return { spring: "#4c8c3f", summer: "#468737", autumn: "#7c8a3a", winter: "#9bb0a2" }[season] || "#4c8c3f";
  }
  const COLORS = ["", "#2f6fb0", "#d8c48a", "", "#7d8088", "", "#b39a6a", "#c4a477", "#6b5545", "#8a5a2b", "#6b4a2f",
                  "#9c6b3c", "#b8b2a7", "#6b6b73", "#eef3f7", "", "#a47148", "", "", "#4a4540"];
  const dims = (w) => [w?.W || 64, w?.H || 40];

  function hash(x, y) { let h = x * 374761393 + y * 668265263; h = (h ^ (h >> 13)) * 1274126177; return ((h ^ (h >> 16)) >>> 0) / 4294967295; }

  function buildTerrain(w, ts) {
    const [MW, MH] = dims(w);
    const c = document.createElement("canvas"); c.width = MW * ts; c.height = MH * ts;
    const t = c.getContext("2d"), grass = grassColor(w.season);
    for (let y = 0; y < MH; y++) for (let x = 0; x < MW; x++) {
      const k = w.terrain[y][x], r = hash(x, y), X = x * ts, Y = y * ts, cx = X + ts / 2, cy = Y + ts / 2;
      t.fillStyle = COLORS[k] || grass; t.fillRect(X, Y, ts, ts);
      t.fillStyle = `rgba(0,0,0,${r * .07})`; t.fillRect(X, Y, ts, ts);
      if (k === 7) { t.strokeStyle = "rgba(0,0,0,.12)"; t.beginPath(); t.moveTo(X, Y + ts / 2); t.lineTo(X + ts, Y + ts / 2); t.stroke(); }
      if (k === 10) { t.strokeStyle = "rgba(0,0,0,.25)"; for (let i = 1; i < 3; i++) { t.beginPath(); t.moveTo(X, Y + i * ts / 3); t.lineTo(X + ts, Y + i * ts / 3); t.stroke(); } }
      if (k === 1) { t.strokeStyle = "rgba(255,255,255,.16)"; t.beginPath(); t.arc(cx - ts * .15, cy, ts * .18, 3.4, 6); t.stroke(); }
      if (k === 15) { t.strokeStyle = "#8b5a2b"; t.lineWidth = Math.max(1, ts * .1); t.beginPath(); t.moveTo(X, cy); t.lineTo(X + ts, cy); t.moveTo(cx, Y + ts * .2); t.lineTo(cx, Y + ts * .8); t.stroke(); }
      if (k === 17) for (let i = 0; i < 3; i++) { t.strokeStyle = "rgba(20,60,20,.5)"; t.beginPath(); const gx = X + ts * (.25 + .25 * i); t.moveTo(gx, Y + ts * .8); t.lineTo(gx + ts * .05, Y + ts * .35); t.stroke(); }
      if (k === 18) { t.fillStyle = w.season === "winter" ? "#dfe9e1" : "#1f4d2b"; t.beginPath(); t.moveTo(cx, Y + ts * .05); t.lineTo(X + ts * .85, Y + ts * .85); t.lineTo(X + ts * .15, Y + ts * .85); t.fill(); }
      if (k === 11 || k === 16) { t.strokeStyle = "rgba(0,0,0,.25)"; for (let i = 1; i < 4; i++) { t.beginPath(); t.moveTo(X + i * ts / 4, Y); t.lineTo(X + i * ts / 4, Y + ts); t.stroke(); } }
      if (k === 3) {
        t.fillStyle = "#5b3b22"; t.fillRect(cx - ts * .07, cy, ts * .14, ts * .42);
        t.fillStyle = w.season === "autumn" ? "#b5651d" : w.season === "winter" ? "#557055" : "#2d5e2a";
        t.beginPath(); t.arc(cx, cy - ts * .06, ts * .44, 0, 7); t.fill();
        t.fillStyle = "rgba(255,255,255,.08)"; t.beginPath(); t.arc(cx - ts * .13, cy - ts * .18, ts * .17, 0, 7); t.fill();
      }
      if (k === 4) { t.fillStyle = "#7d8088"; t.beginPath(); t.ellipse(cx, cy + ts * .08, ts * .38, ts * .28, 0, 0, 7); t.fill(); }
      if (k === 5) for (let i = 0; i < 4; i++) { t.fillStyle = ["#ffd166", "#ef476f", "#fff", "#c77dff"][(i + x) % 4];
        t.beginPath(); t.arc(X + ts * (.2 + .6 * hash(x + i, y)), Y + ts * (.2 + .6 * hash(x, y + i)), ts * .06, 0, 7); t.fill(); }
    }
    // place names
    t.font = `600 ${Math.max(10, ts * .42)}px system-ui`; t.textAlign = "center"; t.fillStyle = "rgba(255,255,255,.75)";
    t.shadowColor = "rgba(0,0,0,.6)"; t.shadowBlur = 3;
    for (const [name, [x, y]] of Object.entries(w.places || {})) t.fillText(name, x * ts + ts / 2, y * ts - ts * .25);
    return c;
  }

  function view() {
    const [MW, MH] = dims(st.world);
    if (st.follow === "all" || !st.world?.ada) return { x: 0, y: 0, w: MW, h: MH };
    const w = st.world, f = st.follow === "you" && w.visitor ? w.visitor
      : st.follow !== "ada" && (w.people || []).find((p) => p.name === st.follow) || w.ada;
    return { x: Math.min(Math.max(f.x + .5 - 16, 0), MW - 32), y: Math.min(Math.max(f.y + .5 - 10, 0), MH - 20), w: 32, h: 20 };
  }

  function glide(key, tx, ty) {
    const p = st.pos[key] || (st.pos[key] = [tx, ty]);
    if (Math.hypot(p[0] - tx, p[1] - ty) > 4) { p[0] = tx; p[1] = ty; }
    p[0] += (tx - p[0]) * .3; p[1] += (ty - p[1]) * .3;
    if (Math.hypot(p[0] - tx, p[1] - ty) > .02) st.moving = true;
    return p;
  }

  function orb(x, y, r, inner, outer, eyes, facing, sleeping, t) {
    const grad = g.createRadialGradient(x - r * .3, y - r * .3, r * .1, x, y, r);
    grad.addColorStop(0, "#fff"); grad.addColorStop(.45, inner); grad.addColorStop(1, outer);
    g.fillStyle = grad; g.beginPath(); g.arc(x, y, r, 0, 7); g.fill();
    const f = { north: [0, -1], south: [0, 1], west: [-1, 0], east: [1, 0] }[facing] || [0, 1];
    g.fillStyle = eyes; g.strokeStyle = eyes; g.lineWidth = Math.max(1, r * .12);
    for (const s of [-1, 1]) {
      const ex = x + f[0] * r * .35 + (f[1] ? s * r * .32 : 0), ey = y + f[1] * r * .3 + (f[0] ? s * r * .3 : 0) - r * .1;
      if (sleeping) { g.beginPath(); g.moveTo(ex - r * .12, ey); g.lineTo(ex + r * .12, ey); g.stroke(); }
      else { g.beginPath(); g.ellipse(ex, ey, r * .1, r * .14 * (((t / 1000) % 4) < .15 ? .2 : 1), 0, 0, 7); g.fill(); }
    }
  }

  function bubble(text, x, y, r, ts, color, vw) {
    if (!text) return;
    text = text.length > 70 ? text.slice(0, 70) + "…" : text;
    g.font = `${Math.max(11, ts * .42)}px system-ui`;
    const w = Math.min(g.measureText(text).width, ts * 12) + ts * .6, h = ts * .8;
    let bx = Math.min(Math.max(x - w / 2, vw.x * ts + 4), (vw.x + vw.w) * ts - w - 4), by = y - r - h - ts * .25;
    if (by < vw.y * ts + 4) by = y + r + ts * .25;
    g.fillStyle = color; g.beginPath(); g.roundRect(bx, by, w, h, h / 2.5); g.fill();
    g.fillStyle = "#1a2233"; g.textAlign = "left"; g.textBaseline = "middle"; g.fillText(text, bx + ts * .3, by + h / 2, ts * 12);
  }

  function draw(t) {
    const w = st.world; if (!w || !w.terrain || !w.ada) return;
    const vw = view(), dpr = devicePixelRatio || 1;
    const ts = Math.max(4, Math.floor(cv.clientWidth * dpr / vw.w));
    if (cv.width !== Math.round(ts * vw.w)) { cv.width = Math.round(ts * vw.w); cv.height = Math.round(ts * vw.h); }
    const key = w.terrain_v + ":" + ts + ":" + w.season;
    if (key !== st.terrainKey) { st.terrainImg = buildTerrain(w, ts); st.terrainKey = key; }
    st.ts = ts;
    st.cam = st.cam || [vw.x, vw.y];
    st.cam[0] += (vw.x - st.cam[0]) * .2; st.cam[1] += (vw.y - st.cam[1]) * .2;
    st.moving = Math.hypot(vw.x - st.cam[0], vw.y - st.cam[1]) > .01;
    const cam = { x: st.cam[0], y: st.cam[1], w: vw.w, h: vw.h };
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.translate(-cam.x * ts, -cam.y * ts);
    g.drawImage(st.terrainImg, 0, 0);
    g.textAlign = "center"; g.textBaseline = "middle";
    const lights = [];
    g.font = `${ts * .7}px ${EMOJI_FONT}`;
    for (const e of st.ents.values()) {
      if (e.x < cam.x - 1 || e.x > cam.x + cam.w + 1 || e.y < cam.y - 1 || e.y > cam.y + cam.h + 1) continue;
      const p = glide("e" + e.id, e.x, e.y), cx = p[0] * ts + ts / 2, cy = p[1] * ts + ts / 2;
      if (e.kind === "fire pit") { if (e.lit) lights.push([cx, cy, 4]); g.globalAlpha = e.lit ? 1 : .35; }
      else if (e.kind === "lamp") { lights.push([cx, cy, 3]); g.globalAlpha = 1; }
      else g.globalAlpha = e.kind === "fish" ? .8 : 1;
      if (e.kind === "sprout" && e.growth != null) {
        g.fillStyle = "rgba(0,0,0,.35)"; g.fillRect(cx - ts * .35, cy + ts * .38, ts * .7, ts * .08);
        g.fillStyle = e.watered ? "#4fd18b" : "#d6c36b"; g.fillRect(cx - ts * .35, cy + ts * .38, ts * .7 * Math.min(1, e.growth / 100), ts * .08);
      }
      g.fillText(GLYPH[e.kind] || "❔", cx, cy + ts * .04);
    }
    g.globalAlpha = 1;
    // the companion
    for (const p of w.people || []) {
      const [glyph, color] = [p.glyph || PEOPLE[p.name]?.[0] || "🙂", p.color || PEOPLE[p.name]?.[1] || "#ccc"];
      const q = glide("p" + p.name, p.x, p.y), cx = q[0] * ts + ts / 2, cy = q[1] * ts + ts / 2;
      g.fillStyle = color; g.beginPath(); g.arc(cx, cy, ts * .42, 0, 7); g.fill();
      g.font = `${ts * .6}px ${EMOJI_FONT}`; g.fillText(p.sleeping ? "😴" : glyph, cx, cy + ts * .04);
      g.font = `600 ${Math.max(9, ts * .3)}px system-ui`; g.fillStyle = "#fff"; g.fillText(p.name, cx, cy + ts * .68);
    }
    // you
    let you = null;
    if (w.visitor) {
      const v = w.visitor, q = glide("you", v.x, v.y);
      you = [q[0] * ts + ts / 2, q[1] * ts + ts / 2];
      orb(you[0], you[1], ts * .36, "#ffcf7a", "#e0702a", "#3a1d08", v.facing, false, t);
      g.font = `600 ${Math.max(9, ts * .3)}px system-ui`; g.fillStyle = "#fff"; g.fillText("you", you[0], you[1] + ts * .66);
      if (v.carrying && v.carrying.length) { g.font = `${ts * .42}px ${EMOJI_FONT}`; g.fillText(GLYPH[v.carrying.at(-1)] || "", you[0] + ts * .38, you[1] + ts * .3); }
    }
    // Ada
    const a = w.ada, q = glide("ada", a.x, a.y), ax = q[0] * ts + ts / 2, ay = q[1] * ts + ts / 2, r = ts * .4;
    const glow = g.createRadialGradient(ax, ay, r * .2, ax, ay, r * 2.3);
    glow.addColorStop(0, "rgba(180,140,255,.55)"); glow.addColorStop(1, "rgba(124,156,255,0)");
    g.fillStyle = glow; g.beginPath(); g.arc(ax, ay, r * 2.3, 0, 7); g.fill();
    orb(ax, ay, r, "#9fb4ff", "#7a52e0", "#1a1f3a", a.facing, a.sleeping, t);
    if (a.carrying && a.carrying.length) { g.font = `${ts * .42}px ${EMOJI_FONT}`; g.fillText(GLYPH[a.carrying.at(-1)] || "", ax + r, ay + r * .7); }
    if (a.sleeping) { g.font = `600 ${ts * .4}px system-ui`; g.fillStyle = "#fff"; g.fillText("z z", ax + r * 1.2, ay - r * 1.3); }
    lights.push([ax, ay, 1.6]);
    // placement preview
    if (st.tool && st.hover) {
      const { x, y } = st.hover, bad = st.tool !== "erase" && BLOCKED.has(w.terrain[y]?.[x]);
      g.strokeStyle = bad ? "rgba(255,107,122,.95)" : "rgba(255,255,255,.9)"; g.lineWidth = Math.max(1, ts * .07);
      g.strokeRect(x * ts + 1, y * ts + 1, ts - 2, ts - 2);
      if (!bad && st.tool !== "erase") { g.globalAlpha = .55; g.font = `${ts * .7}px ${EMOJI_FONT}`; g.fillText(GLYPH[st.tool], x * ts + ts / 2, y * ts + ts / 2); g.globalAlpha = 1; }
    }
    // weather and night
    if (w.weather === "rain" || w.weather === "snow") {
      g.strokeStyle = w.weather === "rain" ? "rgba(180,210,255,.35)" : "rgba(255,255,255,.7)"; g.lineWidth = Math.max(1, ts * .04);
      const off = (t / 40) % ts;
      for (let i = 0; i < 160; i++) {
        const x = (cam.x + hash(i, 1) * cam.w) * ts, y = ((cam.y + hash(i, 2) * cam.h) * ts + off * (i % 3 + 1)) % ((cam.y + cam.h) * ts);
        g.beginPath();
        if (w.weather === "rain") { g.moveTo(x, y); g.lineTo(x - ts * .1, y + ts * .35); g.stroke(); }
        else { g.arc(x, y, ts * .05, 0, 7); g.fillStyle = g.strokeStyle; g.fill(); }
      }
    }
    const dark = 1 - (w.light ?? 1);
    if (dark > .02) {
      g.save(); g.fillStyle = `rgba(8,12,40,${dark * .9})`; g.fillRect(cam.x * ts, cam.y * ts, cam.w * ts, cam.h * ts);
      g.globalCompositeOperation = "lighter";
      for (const [lx, ly, rr] of lights) {
        const lg = g.createRadialGradient(lx, ly, 0, lx, ly, rr * ts);
        lg.addColorStop(0, `rgba(255,214,140,${dark * .5})`); lg.addColorStop(1, "rgba(255,214,140,0)");
        g.fillStyle = lg; g.beginPath(); g.arc(lx, ly, rr * ts, 0, 7); g.fill();
      }
      g.restore();
    }
    // speech
    bubble(a.said, ax, ay, r, ts, "rgba(255,255,255,.95)", cam);
    if (w.visitor) bubble(w.visitor.said, you[0], you[1], ts * .36, ts, "rgba(255,226,180,.97)", cam);
    for (const p of w.people || []) { const qq = st.pos["p" + p.name]; if (qq && p.said) bubble(p.said, qq[0] * ts + ts / 2, qq[1] * ts + ts / 2, ts * .42, ts, "rgba(220,240,255,.96)", cam); }
    st.view = cam;
  }

  function frame(t) {
    requestAnimationFrame(frame);
    const pf = st.perf;           // how often the browser gives us a frame: the page's real smoothness
    if (pf.prev && !document.hidden) { pf.frames++; pf.gapMax = Math.max(pf.gapMax, t - pf.prev); }
    pf.prev = document.hidden ? 0 : t;
    if (!st.world || document.hidden) return;
    const weather = st.world.weather === "rain" || st.world.weather === "snow";
    const due = st.dirty || st.moving ? 50 : weather ? 100 : 330;
    if (t - st.last < due) return;
    st.last = t; st.dirty = false;
    const d0 = performance.now();
    draw(t);
    const dd = performance.now() - d0;
    pf.draws++; pf.drawMs += dd; pf.drawMax = Math.max(pf.drawMax, dd);
  }
  requestAnimationFrame(frame);

  function tileAt(ev) {
    const r = cv.getBoundingClientRect(), v = st.view || view();
    return { x: Math.floor(v.x + (ev.clientX - r.left) / r.width * v.w), y: Math.floor(v.y + (ev.clientY - r.top) / r.height * v.h) };
  }
  cv.addEventListener("mousemove", (e) => { if (st.tool) { st.hover = tileAt(e); st.dirty = true; } });
  cv.addEventListener("mouseleave", () => { st.hover = null; st.dirty = true; });
  cv.addEventListener("click", (e) => { cv.focus(); if (st.onClick) st.onClick(tileAt(e)); });
  addEventListener("resize", () => { st.dirty = true; });

  return {
    st,
    setWorld(full) {
      for (const [k, v] of Object.entries(full.kinds || {})) GLYPH[k] = v.glyph;
      st.world = full; st.ents = new Map((full.ents || []).map((e) => [e.id, e])); st.dirty = true;
    },
    applyDelta(d) {
      if (!st.world) return;
      for (const e of d.ents || []) st.ents.set(e.id, e);
      for (const id of d.removed || []) st.ents.delete(id);
      for (const [k, v] of Object.entries(d)) if (k !== "ents" && k !== "removed") st.world[k] = v;
      st.dirty = true;
    },
    entitiesAt(x, y) { return [...st.ents.values()].filter((e) => e.x === x && e.y === y); },
    setFollow(f) { st.follow = f; st.dirty = true; },
    setTool(t) { st.tool = t; st.dirty = true; cv.style.cursor = t ? "copy" : "crosshair"; },
    canvas: cv,
  };
})();
