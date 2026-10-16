"use strict";
// The latest picture of the world (snapshot + deltas) and the minimap on the Home overlay: a small top-down
// map of the land around Zen, drawn from the shared chunk cache (window.Chunks).

const GLYPH = {   // filled in from the World's kinds table too
  berries: "🫐", apple: "🍎", mushroom: "🍄", stick: "🥢", stone: "🪨", flint: "🔪", clay: "🟤", feather: "🪶", shell: "🐚",
  egg: "🥚", honey: "🍯", fish: "🐟", book: "📕", paper: "📄", cup: "☕", bucket: "🪣", axe: "🪓", wood: "🪵", woodpile: "🪵",
  flower: "🌼", pinecone: "🌰", lantern: "🏮", nut: "🌰", leaf: "🍂", seed: "🌱", bed: "🛏️", fireplace: "🔥", table: "🪑",
  bookshelf: "📚", easel: "🖼️", piano: "🎹", chest: "🧰", desk: "🗒️", painting: "🖼️", sculpture: "🗿", poem: "📜",
  deer: "🦌", rabbit: "🐇", fox: "🦊", bird: "🐦", frog: "🐸", owl: "🦉", bee: "🐝", bear: "🐻", fireflies: "✨", firefly: "✨",
  "baked apple": "🍎", "roast mushroom": "🍄", toadstool: "🍄", coconut: "🥥", banana: "🍌", "cactus fruit": "🌵", "cooked egg": "🍳",
  "raw fish": "🐟", "cooked fish": "🍢", log: "🪵", crystal: "💎", campfire: "🔥", "rain barrel": "🛢️", beehive: "🐝", nest: "🪺",
  bees: "🐝", lizard: "🦎", goat: "🐐", basket: "🧺", candle: "🕯️", rope: "🪢", bone: "🦴", cactus_fruit: "🌵", acorn: "🌰", water: "💧",
};
const PORTABLE = ["apple", "berries", "mushroom", "stick", "log", "stone", "flint", "clay", "feather", "shell", "flower", "pinecone", "egg", "honey", "paper", "cup", "lantern"];
const EMOJI_FONT = `"Segoe UI Emoji","Apple Color Emoji","Noto Color Emoji",sans-serif`;
const PLACE_ICON = { home: "🏡", ruins: "🏛️", cabin: "🛖", cave: "🕳️", stones: "🗿", standing_stones: "🗿", spring: "💧", lookout: "⛰️",
  beehive: "🐝", nest: "🪺", well: "🪣", pond: "🪷", lake: "🪷" };

const MapView = (() => {
  const cv = document.getElementById("map"), g = cv.getContext("2d");
  const st = { world: null, ents: new Map(), dirty: true, last: 0, zoom: 3, cam: null, onClick: null, view: null,
               perf: { frames: 0, draws: 0, drawMs: 0, drawMax: 0, gapMax: 0, prev: 0 } };

  function draw() {
    const w = st.world, z = w?.zen; if (!z || !window.Chunks) return;
    const dpr = devicePixelRatio || 1, W = Math.round(cv.clientWidth * dpr), H = Math.round(cv.clientHeight * dpr);
    if (!W || !H) return;
    if (cv.width !== W || cv.height !== H) { cv.width = W; cv.height = H; }
    const ts = st.zoom * dpr, zx = (z.fx ?? z.x) + 0.5, zy = (z.fy ?? z.y) + 0.5;
    st.cam = st.cam || [zx, zy];
    st.cam[0] += (zx - st.cam[0]) * 0.25; st.cam[1] += (zy - st.cam[1]) * 0.25;
    st.moving = Math.hypot(zx - st.cam[0], zy - st.cam[1]) > 0.05;
    const vx = st.cam[0] - W / ts / 2, vy = st.cam[1] - H / ts / 2, vw = W / ts, vh = H / ts;
    st.view = { x: vx, y: vy, w: vw, h: vh };
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.fillStyle = "#1b2433"; g.fillRect(0, 0, W, H);
    g.imageSmoothingEnabled = false;
    const N = Chunks.N;
    for (let cy = Math.floor(vy / N); cy <= Math.floor((vy + vh) / N); cy++) for (let cx = Math.floor(vx / N); cx <= Math.floor((vx + vw) / N); cx++) {
      const im = Chunks.image(cx, cy);
      if (im) g.drawImage(im, Math.floor((cx * N - vx) * ts), Math.floor((cy * N - vy) * ts), Math.ceil(N * ts) + 1, Math.ceil(N * ts) + 1);
      else Chunks.get(cx, cy).then(() => { st.dirty = true; }).catch(() => {});
    }
    const X = (x) => (x - vx) * ts, Y = (y) => (y - vy) * ts;
    // places
    g.textAlign = "center"; g.textBaseline = "middle";
    for (const p of w.places || []) {
      const px = X(p.x + 0.5), py = Y(p.y + 0.5); if (px < -20 || py < -20 || px > W + 20 || py > H + 20) continue;
      g.font = `${Math.round(12 * dpr)}px ${EMOJI_FONT}`; g.fillText(PLACE_ICON[p.kind] || "📍", px, py);
    }
    // animals
    for (const a of w.animals || []) {
      const px = X((a.fx ?? a.x) + 0.5), py = Y((a.fy ?? a.y) + 0.5);
      g.fillStyle = a.kind === "bear" ? "#ff6b7a" : a.kind === "bee" || /fire/.test(a.kind) ? "#ffd34a" : "rgba(255,255,255,.85)";
      g.beginPath(); g.arc(px, py, 1.6 * dpr, 0, 7); g.fill();
    }
    // the Sprite, you, Zen
    const s = w.sprite;
    if (s) { const px = X((s.fx ?? s.x) + 0.5), py = Y((s.fy ?? s.y) + 0.5), gr = g.createRadialGradient(px, py, 0, px, py, 6 * dpr);
      gr.addColorStop(0, "rgba(255,236,170,1)"); gr.addColorStop(1, "rgba(255,210,120,0)"); g.fillStyle = gr; g.beginPath(); g.arc(px, py, 6 * dpr, 0, 7); g.fill(); }
    if (w.visitor) { const v = w.visitor; g.fillStyle = "#ffb547"; g.beginPath(); g.arc(X((v.fx ?? v.x) + 0.5), Y((v.fy ?? v.y) + 0.5), 3 * dpr, 0, 7); g.fill(); }
    const px = X(zx), py = Y(zy), r = 4.5 * dpr;
    const glow = g.createRadialGradient(px, py, 0, px, py, r * 3); glow.addColorStop(0, "rgba(160,150,255,.6)"); glow.addColorStop(1, "rgba(124,156,255,0)");
    g.fillStyle = glow; g.beginPath(); g.arc(px, py, r * 3, 0, 7); g.fill();
    const f = [[0, -1], [1, 0], [0, 1], [-1, 0]][(z.facing ?? 2) % 4] || [0, 1];
    g.fillStyle = "#fff"; g.beginPath(); g.moveTo(px + f[0] * r * 2.1, py + f[1] * r * 2.1); g.lineTo(px - f[1] * r * 0.8, py + f[0] * r * 0.8); g.lineTo(px + f[1] * r * 0.8, py - f[0] * r * 0.8); g.fill();
    const og = g.createRadialGradient(px - r * 0.3, py - r * 0.3, r * 0.1, px, py, r);
    og.addColorStop(0, "#fff"); og.addColorStop(0.45, "#9fb4ff"); og.addColorStop(1, "#7a52e0");
    g.fillStyle = og; g.beginPath(); g.arc(px, py, r, 0, 7); g.fill();
    // night
    const dark = 1 - (w.light ?? 1);
    if (dark > 0.05) { g.fillStyle = `rgba(8,12,40,${dark * 0.55})`; g.fillRect(0, 0, W, H); }
    // a north arrow and the scale
    g.fillStyle = "rgba(255,255,255,.75)"; g.font = `600 ${Math.round(10 * dpr)}px system-ui`; g.textAlign = "left";
    g.fillText(`N ↑   ${Math.round(vw)} tiles`, 6 * dpr, 10 * dpr);
  }

  function frame(t) {
    setTimeout(() => requestAnimationFrame(frame), 60);
    const pf = st.perf;
    if (pf.prev && !document.hidden) { pf.frames++; pf.gapMax = Math.max(pf.gapMax, t - pf.prev - 60); }
    pf.prev = document.hidden ? 0 : t;
    if (!st.world || document.hidden || !cv.offsetParent) return;
    const due = st.dirty || st.moving ? 100 : 500;
    if (t - st.last < due) return;
    st.last = t; st.dirty = false;
    const d0 = performance.now();
    draw();
    const dd = performance.now() - d0;
    pf.draws++; pf.drawMs += dd; pf.drawMax = Math.max(pf.drawMax, dd);
  }
  requestAnimationFrame(frame);

  function tileAt(ev) {
    const r = cv.getBoundingClientRect(), v = st.view; if (!v) return null;
    return { x: Math.floor(v.x + (ev.clientX - r.left) / r.width * v.w), y: Math.floor(v.y + (ev.clientY - r.top) / r.height * v.h) };
  }
  cv.addEventListener("click", (e) => { const t = tileAt(e); if (t && st.onClick) st.onClick(t); });
  cv.addEventListener("wheel", (e) => { e.preventDefault(); st.zoom = Math.max(1, Math.min(10, st.zoom * (e.deltaY > 0 ? 0.85 : 1.18))); st.dirty = true; }, { passive: false });
  addEventListener("resize", () => { st.dirty = true; });

  return {
    st, canvas: cv,
    setWorld(full) {
      for (const [k, v] of Object.entries(full.kinds || {})) if (v?.glyph) GLYPH[k] = v.glyph;
      st.world = full; st.ents = new Map((full.ents || []).map((e) => [e.id, e])); st.dirty = true;
    },
    applyDelta(d) {
      if (!st.world) return;
      for (const [k, v] of Object.entries(d.kinds || {})) if (v?.glyph) GLYPH[k] = v.glyph;
      for (const e of d.ents || []) st.ents.set(e.id, Object.assign(st.ents.get(e.id) && e.kind === undefined ? st.ents.get(e.id) : {}, e));
      for (const id of d.removed || []) st.ents.delete(id);
      for (const [k, v] of Object.entries(d)) {
        if (k === "ents" || k === "removed") continue;
        if ((k === "zen" || k === "sprite" || k === "mind") && v && st.world[k]) st.world[k] = Object.assign({}, st.world[k], v);
        else st.world[k] = v;
      }
      st.dirty = true;
    },
    zoom(f) { st.zoom = Math.max(1, Math.min(10, st.zoom * f)); st.dirty = true; },
  };
})();
