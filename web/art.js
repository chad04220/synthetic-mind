"use strict";
// The homestead's art, shown and played in the browser. Every work arrives as an exact recipe (a "spec": a scene
// graph for a painting, a composition for a song, shaped parts for a sculpture) and is painted, played or modelled
// the same way every time, so a work lasts exactly as its maker left it.
//
// Paintings: the scene is built as a list of marks (shapes with a fill, a material and an outline), then a style
// renders those marks: flat colour and outlines (naive), layered wet washes (watercolor), ink line and wash (ink),
// or brush dabs sampled from a clean render (impressionist, oil, pastel, pointillist). The maker's skill decides
// the craft: wobbly lines, scribbled fills and smudges at first; depth, light and confident strokes later.

const Art = (() => {
  const SCRIPT_URL = (document.currentScript && document.currentScript.src) || location.href;
  // ================================================================== small helpers
  function rng(seed) {             // mulberry32: the same seed paints the same picture
    let a = (seed >>> 0) || 1;
    return () => { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
  }
  const clamp = (v, a, b) => (v < a ? a : v > b ? b : v);
  const lerp = (a, b, t) => a + (b - a) * t;
  const smooth = (e0, e1, x) => { const t = clamp((x - e0) / (e1 - e0), 0, 1); return t * t * (3 - 2 * t); };
  const TAU = Math.PI * 2;
  function rgb(h) {
    if (Array.isArray(h)) return h;
    h = String(h || "").trim();
    if (/^#[0-9a-f]{3}$/i.test(h)) h = "#" + h.slice(1).split("").map((c) => c + c).join("");
    if (!/^#[0-9a-f]{6}$/i.test(h)) return [140, 140, 140];
    return [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  }
  const css = (c, a = 1) => (a >= 1 ? `rgb(${c[0] | 0},${c[1] | 0},${c[2] | 0})` : `rgba(${c[0] | 0},${c[1] | 0},${c[2] | 0},${Math.max(0, a).toFixed(3)})`);
  const mix = (a, b, t) => { a = rgb(a); b = rgb(b); return [lerp(a[0], b[0], t), lerp(a[1], b[1], t), lerp(a[2], b[2], t)]; };
  const lighten = (c, t) => mix(c, [255, 252, 240], t);
  const darken = (c, t) => mix(c, [28, 30, 52], t);
  const lum = (c) => (0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]) / 255;
  function toHsl([r, g, b]) {
    r /= 255; g /= 255; b /= 255;
    const mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2;
    if (mx === mn) return [0, 0, l];
    const d = mx - mn, s = l > 0.5 ? d / (2 - mx - mn) : d / (mx + mn);
    const h = mx === r ? (g - b) / d + (g < b ? 6 : 0) : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
    return [h * 60, s, l];
  }
  function fromHsl(h, s, l) {
    h = ((h % 360) + 360) % 360 / 360; s = clamp(s, 0, 1); l = clamp(l, 0, 1);
    if (!s) return [l * 255, l * 255, l * 255];
    const q = l < 0.5 ? l * (1 + s) : l + s - l * s, p = 2 * l - q;
    const f = (t) => { t = (t + 1) % 1; return 255 * (t < 1 / 6 ? p + (q - p) * 6 * t : t < 0.5 ? q : t < 2 / 3 ? p + (q - p) * (2 / 3 - t) * 6 : p); };
    return [f(h + 1 / 3), f(h), f(h - 1 / 3)];
  }
  function hash(x, y, s) { let h = Math.imul(x | 0, 374761393) + Math.imul(y | 0, 668265263) + Math.imul(s | 0, 2147483647); h = Math.imul(h ^ (h >>> 13), 1274126177); return ((h ^ (h >>> 16)) >>> 0) / 4294967296; }
  function vnoise(x, y, s = 0) {
    const xi = Math.floor(x), yi = Math.floor(y), xf = x - xi, yf = y - yi, u = xf * xf * (3 - 2 * xf), v = yf * yf * (3 - 2 * yf);
    const a = hash(xi, yi, s), b = hash(xi + 1, yi, s), c = hash(xi, yi + 1, s), d = hash(xi + 1, yi + 1, s);
    return a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v;
  }
  const fbm = (x, y, s, o = 4) => { let t = 0, a = 0.5, f = 1; for (let i = 0; i < o; i++) { t += a * vnoise(x * f, y * f, s + i * 17); a *= 0.5; f *= 2; } return t / (1 - Math.pow(0.5, o)); };
  function mkCanvas(w, h) { const c = document.createElement("canvas"); c.width = Math.max(1, w | 0); c.height = Math.max(1, h | 0); return c; }
  // CPU-backed contexts: thousands of small strokes and read-backs are far quicker off the GPU
  const ctx2d = (c) => c.getContext("2d", { willReadFrequently: true });

  // a tile of paper grain, made once
  let GRAIN = null;
  function grain() {
    if (GRAIN) return GRAIN;
    const N = 192, c = mkCanvas(N, N), g = ctx2d(c), im = g.createImageData(N, N);
    for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
      const n = 0.55 * vnoise(x / 3, y / 3, 5) + 0.3 * vnoise(x / 9, y / 9, 7) + 0.15 * hash(x, y, 3);
      const v = 255 * n, o = (y * N + x) * 4;
      im.data[o] = im.data[o + 1] = im.data[o + 2] = v; im.data[o + 3] = 255;
    }
    // make it tile: blend edges
    g.putImageData(im, 0, 0);
    GRAIN = c; return c;
  }
  let WEAVE = null;
  function weave() {
    if (WEAVE) return WEAVE;
    const N = 8, c = mkCanvas(N, N), g = c.getContext("2d");
    g.fillStyle = "#808080"; g.fillRect(0, 0, N, N);
    for (let i = 0; i < N; i += 2) { g.fillStyle = "rgba(255,255,255,.35)"; g.fillRect(i, 0, 1, N); g.fillStyle = "rgba(0,0,0,.25)"; g.fillRect(0, i + 1, N, 1); }
    WEAVE = c; return c;
  }

  // ================================================================== marks
  const M = { SKY: 1, CLOUD: 2, WATER: 3, MOUNT: 4, HILL: 5, GROUND: 6, FOLIAGE: 7, OBJ: 8, LIGHT: 9, WALL: 10, FLOOR: 11, SNOW: 12, RAIN: 13, FINE: 14 };

  // densify a closed or open polyline so wobble bends long straight edges too
  function densify(p, closed, step) {
    const out = [], n = p.length / 2, m = closed ? n : n - 1;
    for (let i = 0; i < m; i++) {
      const x0 = p[i * 2], y0 = p[i * 2 + 1], j = (i + 1) % n, x1 = p[j * 2], y1 = p[j * 2 + 1];
      const k = Math.max(1, Math.ceil(Math.hypot(x1 - x0, y1 - y0) / step));
      for (let s = 0; s < k; s++) out.push(x0 + (x1 - x0) * s / k, y0 + (y1 - y0) * s / k);
    }
    if (!closed) out.push(p[p.length - 2], p[p.length - 1]);
    return out;
  }
  function wobble(p, amp, seed, freq) {
    if (amp <= 0.05) return p;
    const out = new Array(p.length);
    for (let i = 0; i < p.length; i += 2) {
      const x = p[i], y = p[i + 1];
      out[i] = x + (vnoise(x * freq, y * freq, seed) - 0.5) * 2 * amp + (hash(i, seed, 1) - 0.5) * amp * 0.35;
      out[i + 1] = y + (vnoise(x * freq + 31.7, y * freq - 12.1, seed + 3) - 0.5) * 2 * amp + (hash(i, seed, 2) - 0.5) * amp * 0.35;
    }
    return out;
  }

  class Pen {
    constructor(S) { this.S = S; this.marks = []; this.tf = null; this.amul = 1; this.mat = M.OBJ; this.n = 0; this.grp = 0; }
    _pts(p) {
      if (!this.tf) return p;
      const o = new Array(p.length);
      for (let i = 0; i < p.length; i += 2) { const q = this.tf(p[i], p[i + 1]); o[i] = q[0]; o[i + 1] = q[1]; }
      return o;
    }
    _fill(f) {
      if (!f || Array.isArray(f) || !this.tf) return f;
      const g = Object.assign({}, f);
      if (f.g === "lin") { const a = this.tf(f.x0, f.y0), b = this.tf(f.x1, f.y1); g.x0 = a[0]; g.y0 = a[1]; g.x1 = b[0]; g.y1 = b[1]; }
      else { const a = this.tf(f.x, f.y); g.x = a[0]; g.y = a[1]; }
      return g;
    }
    poly(p, fill, o = {}) {
      const S = this.S, seed = (S.seed + (++this.n) * 7919) >>> 0;
      let pts = this._pts(p);
      const amp = (o.wob ?? 1) * S.wob;
      if (amp > 0.05 && o.wob !== 0) pts = wobble(densify(pts, !o.open, Math.max(2, 5 * S.u)), amp, seed, 0.045 / S.u);
      let edge = o.edge === undefined ? null : o.edge;
      if (edge) { edge = this._pts(edge); if (amp > 0.05) edge = wobble(densify(edge, false, Math.max(2, 5 * S.u)), amp, seed, 0.045 / S.u); }
      this.marks.push({ t: o.open ? "line" : "poly", p: pts, fill: this._fill(fill), mat: o.mat || this.mat, a: (o.a ?? 1) * this.amul,
        edge, line: o.line, lw: o.lw, smooth: o.smooth, emit: o.emit, seed, grp: this.grp, noOutline: o.noOutline, w: o.w, soft: o.soft, refl: !!this.tf });
      return this;
    }
    ell(cx, cy, rx, ry, fill, o = {}) {
      const n = clamp(Math.round(Math.sqrt(Math.abs(rx) + Math.abs(ry)) * 4), 12, 48), p = [], r = o.rot || 0, a0 = o.a0 ?? 0, a1 = o.a1 ?? TAU;
      const part = a1 - a0 < TAU - 1e-3;
      for (let i = 0; i < n + (part ? 1 : 0); i++) {
        const a = a0 + (a1 - a0) * i / n, x = Math.cos(a) * rx, y = Math.sin(a) * ry;
        p.push(cx + x * Math.cos(r) - y * Math.sin(r), cy + x * Math.sin(r) + y * Math.cos(r));
      }
      return this.poly(p, fill, o);
    }
    circ(cx, cy, r, fill, o) { return this.ell(cx, cy, r, r, fill, o); }
    rect(x, y, w, h, fill, o) { return this.poly([x, y, x + w, y, x + w, y + h, x, y + h], fill, o); }
    line(p, w, col, o = {}) { return this.poly(p, col, Object.assign({}, o, { open: true, w })); }
    glow(x, y, r, col, a = 1, o = {}) {
      const q = this.tf ? this.tf(x, y) : [x, y];
      this.marks.push({ t: "glow", x: q[0], y: q[1], r, c: rgb(col), a: a * this.amul, mat: M.LIGHT, emit: o.emit ?? true, under: o.under });
      return this;
    }
    fn(f, o = {}) { this.marks.push({ t: "fn", f, mat: o.mat || M.OBJ, emit: o.emit }); return this; }
    // draw something mirrored about a water line, faded (reflections)
    mirror(y0, alpha, fn) {
      const tf = this.tf, am = this.amul;
      this.tf = (x, y) => [x, 2 * y0 - y]; this.amul = am * alpha; fn(); this.tf = tf; this.amul = am;
    }
  }

  // ================================================================== v1 → v2
  function fromV1(d) {
    const el = new Set(d.elements || []), subj = String(d.subject || "");
    const time = /night/.test(subj) ? "night" : /evening|dusk|sunset/.test(subj) ? "evening" : /dawn|sunrise/.test(subj) ? "dawn" : /morning/.test(subj) ? "morning" : "afternoon";
    const style = { calm: "watercolor", gentle: "pastel", bold: "oil", bright: "impressionist", dreamy: "watercolor", stormy: "oil", playful: "naive" }[d.style] || "impressionist";
    const SKY = { dawn: ["#f6b7a3", "#ffd6a5"], morning: ["#9ecbea", "#e8f4fa"], afternoon: ["#7ab8e0", "#fbe5b6"], evening: ["#5c4b8a", "#f4a261"], night: ["#0b1630", "#2a3a68"] }[time];
    const r = rng(d.seed || 7), hor = 0.5 + r() * 0.1, layers = [], objects = [];
    const L = (type, y, height, color) => layers.push({ type, y, height, color, detail: 0.7, seed: (r() * 1e6) | 0 });
    const pal = d.palette || [];
    if (el.has("crystals")) {
      L("mountains", hor, 0.25, "#3a3f6b"); L("snowfield", hor + 0.05, 0, "#cfd8f0");
      for (let i = 0; i < 6; i++) objects.push({ type: "rock", x: 0.1 + r() * 0.8, y: hor + 0.1 + r() * 0.3, size: 0.08 + r() * 0.08, color: "#9ad1f5" });
    } else if (el.has("window")) {
      L("room", 0.64, 0, "#d9c3a5");
      objects.push({ type: "window", x: 0.5, y: 0.45, size: 0.32 }, { type: "table", x: 0.5, y: 0.72, size: 0.2 }, { type: "candle", x: 0.7, y: 0.72, size: 0.12 }, { type: "vase", x: 0.4, y: 0.72, size: 0.16 });
    } else {
      if (el.has("peaks") || el.has("snow")) L("mountains", hor - 0.02, 0.24, "#7d8aa5");
      if (el.has("hills") || el.has("fields") || el.has("trees") || el.has("flowers") || !layers.length) L("hills", hor, 0.12, pal[3] || "#5d8f3d");
      if (el.has("water") || el.has("pond")) L("water", hor + 0.04, 0, "#4a86b5");
      else if (el.has("fields")) L("field", hor + 0.05, 0, pal[5] || "#a7cf6e");
      else L(el.has("snow") ? "snowfield" : "meadow", hor + 0.05, 0, pal[5] || "#86b84a");
    }
    const sun = time === "night" ? "moon" : "sun";
    if (!el.has("window")) objects.push({ type: sun, x: 0.15 + r() * 0.7, y: hor * (0.3 + r() * 0.3), size: 0.1 });
    if (el.has("stars")) objects.push({ type: "star", x: 0.2 + r() * 0.6, y: 0.12, size: 0.04 });
    if (el.has("boat")) objects.push({ type: "boat", x: 0.3 + r() * 0.4, y: hor + 0.15, size: 0.16 });
    if (el.has("trees")) for (let i = 0; i < 3; i++) objects.push({ type: el.has("apples") ? "apple tree" : "tree", x: 0.1 + r() * 0.8, y: hor + 0.1 + r() * 0.25, size: 0.25 + r() * 0.12 });
    if (el.has("houses") || el.has("stalls")) for (let i = 0; i < 2; i++) objects.push({ type: "house", x: 0.15 + r() * 0.7, y: hor + 0.06 + r() * 0.08, size: 0.2 });
    if (el.has("barn")) objects.push({ type: "barn", x: 0.2 + r() * 0.6, y: hor + 0.08, size: 0.24 });
    if (el.has("flowers")) for (let i = 0; i < 5; i++) objects.push({ type: "flower", x: 0.1 + r() * 0.8, y: hor + 0.25 + r() * 0.2, size: 0.08 });
    if (el.has("butterflies")) objects.push({ type: "butterfly", x: 0.3 + r() * 0.4, y: hor + 0.05, size: 0.06 });
    objects.sort((a, b) => a.y - b.y);
    return { v: 2, subject: subj, style, canvas: [4, 3], palette: pal, mood: d.style === "stormy" ? "stormy" : "calm",
      weather: el.has("rain") ? "rain" : el.has("snow") ? "snow" : d.style === "stormy" ? "storm" : "clear", season: el.has("snow") ? "winter" : "summer",
      light: { time, glow: el.has("glow") ? 0.8 : time === "evening" ? 0.7 : 0.2 }, sky: { top: SKY[0], bottom: SKY[1], clouds: 0.3, stars: el.has("stars") ? 0.8 : 0 },
      horizon: hor, layers, objects, skill: 0.6, seed: d.seed || 7 };
  }

  // ================================================================== the scene
  const MOOD_TINT = { calm: "#7fa7c9", joyful: "#f2c14e", lonely: "#6c7a99", dreamy: "#b39ddb", stormy: "#4a5568", cosy: "#e08e45", playful: "#ef6f6c", peaceful: "#8fbf9f" };
  const SEASON_LEAF = { spring: ["#7dbb4c", "#a9d36b", "#4f8a33"], summer: ["#3f8a35", "#6fae45", "#2a5f28"], autumn: ["#d0782f", "#e9a940", "#9c4a22"], winter: ["#6d7f78", "#9aa9a3", "#4d5a55"] };

  function sceneOf(d, W, H) {
    const skill = clamp(+d.skill || 0, 0, 1), u = Math.min(W, H) / 300;
    const S = {
      d, W, H, u, skill, seed: (d.seed >>> 0) || 1, style: d.style || "naive",
      time: d.light?.time || "noon", glowAmt: +(d.light?.glow ?? 0.2), season: d.season || "summer", weather: d.weather || "clear", mood: d.mood || "calm",
      kid: clamp((0.42 - skill) / 0.27, 0, 1), shade: smooth(0.25, 0.85, skill), hor: (d.horizon ?? 0.55) * H,
      pal: (d.palette || []).map(rgb), lights: [],
    };
    S.wob = u * (0.25 + 5.2 * Math.pow(1 - skill, 2.2));
    S.night = S.time === "night" ? 1 : S.time === "evening" ? 0.25 : 0;
    S.indoor = (d.layers || []).some((l) => l.type === "room");
    S.r = rng(S.seed ^ 0x51ed27);
    S.leaf = SEASON_LEAF[S.season] || SEASON_LEAF.summer;
    const sun = (d.objects || []).find((o) => o.type === "sun" || o.type === "moon");
    S.lx = sun ? (sun.x < 0.5 ? -1 : 1) : -1;                 // which side the light comes from
    S.sunPos = sun ? [sun.x * W, sun.y * H] : [W * (S.lx < 0 ? 0.2 : 0.8), S.hor * 0.5];
    S.warm = { dawn: "#ffc9a0", evening: "#ffb36b", night: "#a9b8ff", morning: "#fff1d6", afternoon: "#ffe2b0" }[S.time] || "#fff6e0";
    // pick a colour: a child grabs crayons from its palette, a practised hand uses the true colour
    S.col = (natural, k) => {
      if (S.kid > 0.35 && S.pal.length && hash(k | 0, S.seed, 9) < 0.55 * S.kid) return S.pal[Math.floor(hash(k | 0, S.seed, 11) * S.pal.length)];
      return mix(rgb(natural), rgb(MOOD_TINT[S.mood] || "#888"), 0.06);
    };
    // a lit fill: light side to shadow side, as far as skill can see light
    S.lit = (c, x0, y0, x1, y1, k = 1) => {
      c = rgb(c);
      if (S.shade * k < 0.1) return c;
      const s = S.shade * k, a = S.lx < 0 ? [x0, y0, x1, y1] : [x1, y0, x0, y1];
      return { g: "lin", x0: a[0], y0: a[1], x1: a[2], y1: a[3], s: [[0, mix(lighten(c, 0.22 * s), S.warm, 0.12 * s)], [0.55, c], [1, darken(c, 0.32 * s)]] };
    };
    return S;
  }

  // ------------------------------------------------------------------ sky
  function drawSky(P, S) {
    const { W, H, d } = S, sky = d.sky || {}, top = rgb(sky.top || "#7ab8e0"), bot = rgb(sky.bottom || "#e8f4fa"), hor = S.hor;
    P.mat = M.SKY;
    if (S.indoor) return;
    if (S.kid > 0.55 && S.style !== "watercolor") {
      // a child's sky: a band of blue at the top of the page, white paper between it and the ground
      const band = H * lerp(0.26, 0.2, S.kid), p = [0, 0, W, 0, W, band];
      for (let i = 10; i >= 0; i--) p.push(W * i / 10, band + Math.sin(i * 1.7 + S.seed) * H * 0.012);
      P.poly(p, S.time === "night" ? [30, 40, 90] : mix(top, [70, 130, 230], 0.5), { wob: 1.2, edge: null, noOutline: true });
      S.skyBand = band;
    } else {
      const g = { g: "lin", x0: 0, y0: 0, x1: 0, y1: hor + H * 0.02, s: [[0, top], [0.62, mix(top, bot, 0.6)], [1, bot]] };
      P.poly([0, 0, W, 0, W, hor + H * 0.03, 0, hor + H * 0.03], g, { wob: 0, noOutline: true });
      // light near the horizon at dawn and dusk
      if (S.glowAmt > 0.3 && S.kid < 0.6) {
        const gx = S.sunPos[0], c = S.time === "night" ? [120, 140, 220] : mix(bot, [255, 190, 120], 0.5);
        P.glow(gx, hor, W * (0.35 + S.glowAmt * 0.35), c, 0.35 * S.glowAmt, { emit: false });
      }
    }
    // stars
    const stars = +sky.stars || 0;
    if (stars > 0) {
      const r = rng(S.seed ^ 0x5717), n = Math.round(stars * 70 * (W * H) / (400 * 300) * (S.kid > 0.5 ? 0.2 : 1)), lim = S.skyBand || hor * 0.85;
      for (let i = 0; i < n; i++) {
        const x = r() * W, y = r() * lim, b = r();
        if (S.kid > 0.5) star(P, S, x, y, S.u * (4 + b * 3), [255, 230, 120]);
        else P.glow(x, y, S.u * (0.8 + b * b * 2.4), [255, 250, 230], 0.5 + b * 0.5);
      }
    }
    // clouds
    const nc = Math.round((+sky.clouds || 0) * 7 * (W / H > 1.5 ? 1.3 : 1));
    if (nc) {
      const r = rng(S.seed ^ 0xc10d);
      for (let i = 0; i < nc; i++) {
        const x = (i + 0.2 + r() * 0.6) / nc * W, y = (S.skyBand ? S.skyBand * (0.3 + r() * 0.5) : hor * (0.12 + r() * 0.55)), w = W * (0.12 + r() * 0.14) * (S.skyBand ? 0.8 : 1 - 0.3 * (y / hor));
        cloud(P, S, x, y, w, r);
      }
    }
  }
  function cloud(P, S, x, y, w, r) {
    const dark = S.weather === "storm" || S.weather === "rain";
    const base = S.time === "night" ? [70, 80, 120] : dark ? [150, 156, 170] : S.time === "evening" ? [250, 205, 190] : S.time === "dawn" ? [255, 222, 210] : [255, 255, 255];
    const shadowC = mix(base, S.time === "night" ? [30, 36, 70] : dark ? [80, 86, 104] : [170, 180, 210], 0.6);
    P.mat = M.CLOUD;
    const n = 4 + Math.floor(r() * 3), h = w * 0.32;
    if (S.kid > 0.5) {   // a bumpy cloud outline, coloured in
      const p = [];
      for (let i = 0; i <= n; i++) { const a0 = Math.PI + i / n * Math.PI; p.push(x + Math.cos(a0) * w / 2, y + Math.sin(a0) * h * 0.9 - Math.abs(Math.sin(i * 1.3)) * h * 0.3); }
      p.push(x + w / 2, y + h * 0.25, x - w / 2, y + h * 0.25);
      P.poly(p, base, { smooth: true, line: [80, 110, 170] });
      return;
    }
    const g = { g: "lin", x0: 0, y0: y - h, x1: 0, y1: y + h * 0.4, s: [[0, lighten(base, 0.3)], [0.6, base], [1, mix(base, shadowC, S.shade)]] };
    for (let i = 0; i < n; i++) {
      const t = i / (n - 1) - 0.5, cx = x + t * w * 0.8, rr = h * (0.55 + (1 - Math.abs(t) * 1.4) * 0.5) * (0.85 + r() * 0.3);
      P.ell(cx, y - rr * 0.35 + h * 0.2, rr * 1.15, rr * 0.85, g, { wob: 0.6, smooth: true, noOutline: true });
    }
    P.ell(x, y + h * 0.18, w * 0.5, h * 0.3, g, { wob: 0.5, noOutline: true });
  }

  // ------------------------------------------------------------------ landscape layers
  function ridge(S, seed, x0, x1, base, height, rough, n = 64) {
    const pts = [];
    for (let i = 0; i <= n; i++) {
      const t = i / n, x = lerp(x0, x1, t);
      const v = fbm(t * rough, 0.5, seed, 5);
      pts.push(x, base - height * clamp(v * 1.5 - 0.25, 0.04, 1));
    }
    return pts;
  }
  function rolling(S, seed, base, amp, waves) {
    const pts = [], n = 48, r = rng(seed);
    const ph = [r() * 6, r() * 6, r() * 6];
    for (let i = 0; i <= n; i++) {
      const t = i / n;
      const v = 0.55 * Math.sin(t * waves * 3.1 + ph[0]) + 0.3 * Math.sin(t * waves * 7.3 + ph[1]) + 0.15 * Math.sin(t * waves * 13.7 + ph[2]);
      pts.push(t * S.W, base - amp * (0.5 + 0.5 * v));
    }
    return pts;
  }
  function closeDown(top, S) { const p = top.slice(), b = S.layerBottom ?? S.H + 2; p.push(S.W + 2, b, -2, b); return p; }

  function drawLayers(P, S) {
    const { W, H, d } = S, layers = d.layers || [];
    let hazeDone = false;
    S.waterY = null;
    layers.forEach((L, i) => {
      const y = clamp(+L.y || S.hor / H, 0, 1) * H, c = rgb(L.color || "#7a9a5a"), det = +(L.detail ?? 0.5), r = rng(L.seed || i + 1);
      const isFar = L.type === "mountains" || L.type === "hills" || L.type === "forest";
      if (!isFar && !hazeDone) { hazeDone = true; haze(P, S); }
      const fn = LAYER[L.type] || LAYER.meadow, nxt = layers.slice(i + 1).find((q) => q.type !== "path");
      S.layerBottom = nxt && L.type !== "water" ? Math.min(H + 2, clamp(+nxt.y || 1, 0, 1) * H + H * 0.04) : H + 2;
      fn(P, S, L, y, c, det, r, i);
    });
    if (!hazeDone) haze(P, S);
    S.layerBottom = S.H + 2;
  }
  function haze(P, S) {   // aerial perspective: air between us and the distance
    if (S.shade < 0.2 || S.indoor || S.style === "naive") return;
    const { W, H, hor } = S, c = mix(rgb(S.d.sky?.bottom || "#dde"), [255, 255, 255], 0.3);
    P.mat = M.SKY;
    P.rect(0, hor - H * 0.16, W, H * 0.2, { g: "lin", x0: 0, y0: hor - H * 0.16, x1: 0, y1: hor + H * 0.04, s: [[0, css0(c)], [0.75, c], [1, css0(c)]] },
      { a: 0.28 * S.shade, wob: 0, noOutline: true, soft: true });
  }
  const css0 = (c) => [c[0], c[1], c[2], 0];

  const LAYER = {
    mountains(P, S, L, y, c, det, r) {
      P.mat = M.MOUNT;
      const h = (+L.height || 0.2) * S.H, sky = rgb(S.d.sky?.bottom || "#ccd");
      // a farther, paler range first when there is detail
      if (det > 0.5) {
        const back = ridge(S, (L.seed || 1) + 9, -10, S.W + 10, y - h * 0.15, h * 0.8, 3.2);
        P.poly(closeDown(back, S), mix(c, sky, 0.45), { edge: back, smooth: false });
      }
      const top = S.kid > 0.5 ? zigzag(S, y, h, r) : ridge(S, L.seed || 1, -10, S.W + 10, y, h, 2.6);
      const peakY = Math.min(...top.filter((_, i) => i % 2));
      P.poly(closeDown(top, S), S.lit(c, 0, peakY, 0, y + h * 0.1, 0.0) === c ? c : { g: "lin", x0: 0, y0: peakY, x1: 0, y1: y + S.H * 0.05, s: [[0, mix(c, [255, 255, 255], 0.08)], [1, mix(c, sky, 0.3 * S.shade)]] }, { edge: top });
      // light and shadow faces on the slopes
      if (S.shade > 0.3) {
        for (let i = 2; i < top.length - 4; i += 2) {
          const yy = top[i + 1], prev = top[i - 1], next = top[i + 3];
          if (yy < prev && yy < next && y - yy > h * 0.35) {   // a peak: shade the far-from-light side
            const px = top[i], w = (y - yy) * 0.9, side = -S.lx;
            P.poly([px, yy, px + side * w, y + 2, px + side * w * 0.15, y + 2], darken(c, 0.18), { a: 0.45 * S.shade, noOutline: true, wob: 0.6 });
          }
        }
      }
      // snow on the high ground
      if (S.season === "winter" || h > S.H * 0.18 || S.weather === "snow") {
        const line = y - h * (S.season === "winter" ? 0.45 : 0.68);
        for (let i = 2; i < top.length - 4; i += 2) {
          const yy = top[i + 1];
          if (yy < line && yy <= top[i - 1] && yy <= top[i + 3]) {
            const px = top[i], dh = line - yy, w = dh * 0.85;
            const p = [px, yy - 1, px + w, line];
            for (let k = 4; k >= 0; k--) p.push(px + w * (k / 4 * 2 - 1), line - dh * 0.25 * ((k % 2) ? 1 : 0.2));
            p.push(px - w, line);
            P.poly(p, [244, 248, 255], { a: 0.95, edge: null, mat: M.SNOW });
          }
        }
      }
    },
    hills(P, S, L, y, c, det, r, i) {
      P.mat = M.HILL;
      const h = (+L.height || 0.15) * S.H, waves = 1.2 + r() * 1.2;
      if (det > 0.55 && S.kid < 0.5) {   // a paler fold behind
        const back = rolling(S, (L.seed || 1) + 5, y - h * 0.35, h * 0.7, waves * 1.3);
        P.poly(closeDown(back, S), mix(S.season === "winter" ? [226, 234, 244] : c, rgb(S.d.sky?.bottom || "#ccd"), 0.4), { edge: back, smooth: true });
      }
      const top = rolling(S, L.seed || 1, y, h, waves);
      const lc = S.season === "winter" ? [236, 242, 247] : c;
      P.poly(closeDown(top, S), { g: "lin", x0: 0, y0: y - h, x1: 0, y1: y + S.H * 0.15, s: [[0, mix(lighten(lc, 0.15 * S.shade), S.warm, 0.1 * S.shade)], [1, darken(lc, 0.15 * S.shade)]] }, { edge: top, smooth: true });
      // patchwork fields and hedgerows on the hills, little trees on the crest
      if (det > 0.6 && S.season !== "winter") {
        const rr = rng((L.seed || 1) + 77);
        for (let k = 0; k < 5; k++) {
          const x = rr() * S.W, t = Math.round(x / S.W * 48) * 2, ty = top[t + 1] + h * (0.25 + rr() * 0.4);
          const w = S.W * (0.08 + rr() * 0.1), hh = h * (0.12 + rr() * 0.1);
          P.poly([x - w, ty, x + w * 0.2, ty - hh, x + w, ty - hh * 0.4, x, ty + hh * 0.6], mix(c, k % 2 ? [220, 200, 120] : [90, 130, 60], 0.3), { a: 0.6, wob: 0.5, noOutline: true });
        }
      }
      if (det > 0.45) {
        const rr = rng((L.seed || 1) + 99), n = Math.round(det * 9);
        for (let k = 0; k < n; k++) {
          const t = Math.floor(rr() * 48) * 2, x = top[t], ty = top[t + 1] + 2, s = S.H * (0.018 + rr() * 0.014);
          tinyTree(P, S, x, ty, s, rr);
        }
      }
    },
    forest(P, S, L, y, c, det, r) {
      P.mat = M.FOLIAGE;
      const n = Math.round(lerp(10, 46, det) * S.W / S.H * 0.75), rows = det > 0.5 ? 2 : 1;
      for (let row = 0; row < rows; row++) {
        const rr = rng((L.seed || 1) + row * 13), by = y + row * S.H * 0.035, cc = row === 0 && rows > 1 ? mix(c, rgb(S.d.sky?.bottom || "#ccd"), 0.3) : c;
        // the mass of the wood, then trees standing out of its top
        const top = rolling(S, (L.seed || 1) + row, by - S.H * 0.03, S.H * 0.03, 4);
        P.poly(closeDown(top, S), S.season === "winter" ? mix(cc, [235, 240, 248], 0.55) : darken(cc, 0.1), { edge: top, smooth: true });
        for (let k = 0; k < n; k++) {
          const x = (k + rr()) / n * S.W, s = S.H * (0.06 + rr() * 0.05) * (row ? 1.15 : 1);
          if (S.season === "winter" || rr() < 0.5) pineShape(P, S, x, by + S.H * 0.01, s, cc);
          else blobTree(P, S, x, by + S.H * 0.01, s, cc);
        }
      }
    },
    water(P, S, L, y, c, det, r) {
      const { W, H } = S, sky = S.d.sky || {};
      P.mat = M.WATER;
      S.waterY = y;
      const top = rgb(sky.top || "#7ab8e0"), bot = rgb(sky.bottom || "#e8f4fa");
      const wc = S.kid > 0.5 ? mix(c, [40, 110, 220], 0.4) : c;
      const fill = S.kid > 0.5 ? wc : { g: "lin", x0: 0, y0: y, x1: 0, y1: H, s: [[0, mix(bot, wc, 0.45)], [0.35, mix(mix(top, bot, 0.5), wc, 0.55)], [1, darken(mix(top, wc, 0.6), 0.25)]] };
      const shore = [];
      for (let i = 0; i <= 24; i++) shore.push(i / 24 * W, y + Math.sin(i * 1.3 + r() * 0.5) * H * 0.004);
      P.poly(closeDown(shore, S), fill, { edge: shore });
      // the reflection of everything drawn so far, broken by ripples
      if (S.kid < 0.6) {
        const amp = S.u * (1 + 2 * (S.weather === "windy" || S.weather === "storm" ? 2 : 1)), alpha = 0.25 + 0.35 * S.shade;
        P.fn((g, R) => {
          const h = Math.min(y, H - y), tmp = mkCanvas(W, Math.ceil(h) + 2), tg = ctx2d(tmp);
          tg.drawImage(g.canvas, 0, y - h, W, h, 0, 0, W, h);
          g.save(); g.globalAlpha = alpha * (R.alpha || 1);
          const sh = Math.max(1, Math.round(S.u * 1.5));
          for (let s = 0; s < h; s += sh) {
            const off = Math.sin(s * 0.35 / S.u + S.seed) * amp * (0.3 + s / h), src = h - s - sh;
            if (src < 0) break;
            g.globalAlpha = alpha * (R.alpha || 1) * (1 - Math.pow(s / h, 1.5));
            g.drawImage(tmp, 0, src, W, sh, off, y + s, W, sh);
          }
          g.restore();
        }, { mat: M.WATER });
      }
      // a dark line where the far bank meets the water, ripples and glitter
      if (S.kid < 0.6) P.line([0, y + 0.5, W, y + 0.5], S.u * 1.2, darken(c, 0.4), { a: 0.35, wob: 0.4, mat: M.WATER });
      const rr = rng((L.seed || 1) + 3), n = Math.round(lerp(8, 50, det));
      for (let k = 0; k < n; k++) {
        const yy = y + Math.pow(rr(), 1.4) * (H - y), len = S.W * (0.02 + rr() * 0.06) * (0.4 + (yy - y) / (H - y + 1));
        const x = rr() * W;
        P.line([x, yy, x + len, yy], S.u * (0.6 + (yy - y) / H * 2), S.kid > 0.5 ? [255, 255, 255] : lighten(bot, 0.4), { a: 0.25 + rr() * 0.35, mat: M.WATER, wob: 0.4 });
      }
      // the sun's or moon's path on the water
      const sun = (S.d.objects || []).find((o) => o.type === "sun" || o.type === "moon");
      if (sun && S.kid < 0.6) {
        const sx = sun.x * W, cc = sun.type === "moon" ? [235, 238, 255] : mix([255, 240, 200], S.warm, 0.5), rr2 = rng(7);
        for (let k = 0; k < 26; k++) {
          const t = rr2(), yy = y + S.u * 2 + t * (H - y) * 0.85, w = S.W * 0.015 * (1 + t * 4) * (0.5 + rr2());
          P.line([sx - w + (rr2() - 0.5) * w * 2, yy, sx + w + (rr2() - 0.5) * w * 2, yy], S.u * (0.8 + t * 1.6), cc, { a: 0.55 * (1 - t * 0.6), mat: M.LIGHT, wob: 0.3, emit: sun.type === "moon" });
        }
      }
    },
    field(P, S, L, y, c, det, r) {
      P.mat = M.GROUND;
      const { W, H } = S, top = rolling(S, L.seed || 3, y + H * 0.01, H * 0.015, 1.4);
      const sc = S.season === "autumn" ? mix(c, [214, 170, 80], 0.45) : S.season === "winter" ? [236, 241, 246] : c;
      P.poly(closeDown(top, S), { g: "lin", x0: 0, y0: y, x1: 0, y1: H, s: [[0, mix(sc, rgb(S.d.sky?.bottom || "#ccd"), 0.15 * S.shade)], [1, darken(sc, 0.12 * S.shade)]] }, { edge: top });
      // crop rows running toward a point on the horizon
      if (S.kid < 0.8) {
        const vx = W * (0.3 + r() * 0.4), n = Math.round(lerp(6, 18, det)), rc = darken(sc, 0.22), lc = lighten(sc, 0.18);
        for (let k = 0; k <= n; k++) {
          const bx = (k / n - 0.5) * W * 2.6 + W / 2;
          P.line([vx + (bx - vx) * 0.02, y + H * 0.02, bx, H + 4], S.u * (1 + det), k % 2 ? rc : lc, { a: 0.45, wob: 0.6, mat: M.GROUND });
        }
      } else {
        for (let k = 0; k < 6; k++) { const yy = y + (k + 1) / 7 * (H - y); P.line([0, yy, W, yy + (r() - 0.5) * 8], S.u * 2, darken(sc, 0.25), { a: 0.6 }); }
      }
      if (det > 0.5) hedge(P, S, top, c, r);
    },
    meadow(P, S, L, y, c, det, r) {
      P.mat = M.GROUND;
      const { W, H } = S, top = rolling(S, L.seed || 4, y + H * 0.01, H * 0.02, 1.1);
      const sc = S.season === "winter" ? [236, 241, 246] : c;
      P.poly(closeDown(top, S), { g: "lin", x0: 0, y0: y, x1: 0, y1: H, s: [[0, mix(lighten(sc, 0.1), rgb(S.d.sky?.bottom || "#ccd"), 0.18 * S.shade)], [1, darken(sc, 0.18 * S.shade)]] }, { edge: top });
      grassTufts(P, S, y, sc, det, r);
      if (S.season !== "winter") wildflowers(P, S, y, det, r);
    },
    garden(P, S, L, y, c, det, r) {
      P.mat = M.GROUND;
      const { W, H } = S, soil = S.season === "winter" ? [230, 236, 242] : rgb(L.color || "#6b4a2f"), grass = rgb(S.leaf[0]);
      const top = rolling(S, L.seed || 5, y + H * 0.01, H * 0.01, 1.2);
      P.poly(closeDown(top, S), mix(grass, soil, 0.25), { edge: top });
      const rows = Math.round(lerp(3, 6, det)), vx = W * 0.5;
      for (let k = 0; k < rows; k++) {
        const t0 = (k + 0.2) / rows, t1 = (k + 0.75) / rows, y0 = y + (H - y) * t0 * t0 + H * 0.02, y1 = y + (H - y) * t1 * t1 + H * 0.02;
        P.poly([-5, y0, W + 5, y0, W + 5, y1, -5, y1], { g: "lin", x0: 0, y0, x1: 0, y1, s: [[0, lighten(soil, 0.1)], [1, darken(soil, 0.2)]] }, { wob: 0.7, edge: [-5, y0, W + 5, y0] });
        if (S.season !== "winter") {
          const n = Math.round(lerp(5, 14, det) * (0.6 + t0)), s = (y1 - y0) * 0.9;
          for (let i = 0; i < n; i++) {
            const x = (i + 0.5 + (r() - 0.5) * 0.3) / n * W;
            P.mat = M.FOLIAGE;
            const cc = k % 2 ? rgb(S.leaf[1]) : rgb(S.leaf[0]);
            for (let j = 0; j < 4; j++) P.ell(x + (j - 1.5) * s * 0.18, (y0 + y1) / 2 - s * 0.15, s * 0.32, s * 0.4, S.lit(cc, x - s / 2, y0, x + s / 2, y1), { rot: (j - 1.5) * 0.5, wob: 0.6 });
            P.mat = M.GROUND;
          }
        }
      }
    },
    path(P, S, L, y, c, det, r) {
      P.mat = M.GROUND;
      const { W, H } = S, pc = S.season === "winter" ? [226, 232, 240] : rgb(L.color || "#c9a77a");
      const x0 = W * (0.35 + r() * 0.3), bend = (r() - 0.5) * W * 0.4, left = [], right = [];
      for (let i = 0; i <= 16; i++) {
        const t = i / 16, yy = lerp(y + H * 0.01, H + 4, t), cx = x0 + Math.sin(t * 2.4) * bend * t, w = lerp(W * 0.012, W * 0.22, t * t);
        left.push(cx - w, yy); right.unshift(cx + w, yy);
      }
      P.poly(left.concat(right), { g: "lin", x0: 0, y0: y, x1: 0, y1: H, s: [[0, mix(pc, rgb(S.d.sky?.bottom || "#ccd"), 0.2 * S.shade)], [1, darken(pc, 0.1 * S.shade)]] }, { edge: left, smooth: true });
      if (det > 0.4) for (let k = 0; k < det * 20; k++) {
        const t = Math.sqrt(r()), i = Math.floor(t * 16), lx = left[i * 2], rx = right[(16 - i) * 2], yy = left[i * 2 + 1];
        const x = lerp(lx, rx, 0.15 + r() * 0.7), s = S.u * (0.6 + t * 2.5);
        P.ell(x, yy, s * 1.4, s, darken(pc, 0.2), { a: 0.6, wob: 0.3, noOutline: true });
      }
    },
    snowfield(P, S, L, y, c, det, r) {
      P.mat = M.SNOW;
      const { W, H } = S, top = rolling(S, L.seed || 6, y + H * 0.01, H * 0.025, 1.3);
      P.poly(closeDown(top, S), { g: "lin", x0: 0, y0: y, x1: 0, y1: H, s: [[0, [246, 249, 253]], [1, [214, 226, 240]]] }, { edge: top, smooth: true });
      if (S.kid < 0.7) for (let k = 0; k < 3 + det * 4; k++) {   // blue drifts
        const yy = y + (H - y) * (0.2 + r() * 0.8), x = r() * W, w = W * (0.15 + r() * 0.25);
        P.line([x - w, yy, x - w * 0.3, yy - H * 0.012, x + w * 0.4, yy - H * 0.004, x + w, yy + H * 0.01], S.u * 2.2, [178, 196, 226], { a: 0.5, smooth: true, wob: 0.5 });
      }
    },
    beach(P, S, L, y, c, det, r) {
      P.mat = M.GROUND;
      const { W, H } = S, top = rolling(S, L.seed || 7, y + H * 0.01, H * 0.012, 1.1);
      P.poly(closeDown(top, S), { g: "lin", x0: 0, y0: y, x1: 0, y1: H, s: [[0, lighten(c, 0.1)], [1, darken(c, 0.1)]] }, { edge: top });
      P.line(top.map((v, i) => (i % 2 ? v + S.u * 2 : v)), S.u * 2, [255, 255, 255], { a: 0.7, smooth: true });
    },
    room(P, S, L, y, c) {
      const { W, H } = S;
      P.mat = M.WALL;
      const wall = S.season === "winter" ? mix(c, [200, 210, 230], 0.2) : c;
      P.rect(-2, -2, W + 4, y + 2, { g: "lin", x0: 0, y0: 0, x1: W, y1: 0, s: [[0, darken(wall, 0.12 * S.shade)], [0.5, lighten(wall, 0.05)], [1, darken(wall, 0.08 * S.shade)]] }, { wob: 0.4, edge: null, noOutline: true });
      if (S.kid < 0.5) {     // wallpaper sprigs and a wainscot rail
        const rr = rng((L.seed || 1) + 1), n = Math.round(W / (S.u * 26));
        for (let i = 0; i < n; i++) for (let j = 0; j < Math.ceil(y / (S.u * 26)); j++) {
          const x = (i + (j % 2) * 0.5) * S.u * 26, yy = j * S.u * 26 + S.u * 10;
          if (yy > y - S.u * 30) continue;
          P.ell(x, yy, S.u * 1.6, S.u * 2.4, darken(wall, 0.12), { a: 0.45, wob: 0.2, noOutline: true });
        }
        P.rect(-2, y - H * 0.13, W + 4, H * 0.13, darken(wall, 0.12), { a: 0.9, edge: [-2, y - H * 0.13, W + 2, y - H * 0.13] });
        const win = (S.d.objects || []).find((o) => o.type === "window"), px = win && win.x > 0.5 ? W * 0.22 : W * 0.72, pw = W * 0.2, ph = pw * 0.75, py = y * 0.32;
        P.mat = M.OBJ;
        P.rect(px - pw / 2 - S.u * 3, py - S.u * 3, pw + S.u * 6, ph + S.u * 6, [120, 80, 45]);
        P.rect(px - pw / 2, py, pw, ph, { g: "lin", x0: 0, y0: py, x1: 0, y1: py + ph, s: [[0, [150, 190, 220]], [1, [240, 220, 180]]] }, { noOutline: true });
        P.poly([px - pw / 2, py + ph * 0.65, px - pw * 0.1, py + ph * 0.45, px + pw * 0.2, py + ph * 0.58, px + pw / 2, py + ph * 0.5, px + pw / 2, py + ph, px - pw / 2, py + ph], [96, 140, 80], { noOutline: true });
        P.circ(px + pw * 0.25, py + ph * 0.25, pw * 0.07, [255, 230, 160], { noOutline: true });
        P.mat = M.WALL;
        P.rect(-2, y - H * 0.135, W + 4, S.u * 2.5, lighten(wall, 0.2), { noOutline: true });
      }
      P.mat = M.FLOOR;
      const fl = [150, 100, 62];
      P.rect(-2, y, W + 4, H - y + 2, { g: "lin", x0: 0, y0: y, x1: 0, y1: H, s: [[0, darken(fl, 0.2)], [1, lighten(fl, 0.08)]] }, { edge: [-2, y, W + 2, y] });
      const n = S.kid > 0.5 ? 4 : 9;
      for (let k = 0; k <= n; k++) {   // floorboards in perspective
        const bx = (k / n - 0.5) * W * 2 + W / 2;
        P.line([W / 2 + (bx - W / 2) * 0.55, y, bx, H + 4], S.u * 0.8, darken(fl, 0.35), { a: 0.5, wob: 0.4 });
      }
      if (S.shade > 0.3) {   // a rug
        P.ell(W * 0.5, y + (H - y) * 0.62, W * 0.34, (H - y) * 0.26, [158, 64, 58], { a: 0.85, wob: 0.4 });
        P.ell(W * 0.5, y + (H - y) * 0.62, W * 0.28, (H - y) * 0.2, [205, 160, 90], { a: 0.7, wob: 0.4, noOutline: true });
      }
    },
  };
  function zigzag(S, y, h, r) { const p = [-5, y]; const n = 3 + Math.floor(r() * 3); for (let i = 0; i < n; i++) p.push((i + 0.5) / n * S.W, y - h * (0.6 + r() * 0.4), (i + 1) / n * S.W, y - h * 0.1); p.push(S.W + 5, y); return p; }
  function hedge(P, S, top, c, r) {
    P.mat = M.FOLIAGE;
    const hc = darken(rgb(S.leaf[2]), 0.1);
    for (let i = 0; i < top.length; i += 4) P.ell(top[i], top[i + 1] - S.u, S.u * (4 + r() * 3), S.u * (2.5 + r() * 2), hc, { wob: 0.4, noOutline: true });
  }
  function grassTufts(P, S, y, c, det, r) {
    if (S.kid > 0.6) {   // a child's grass: a row of spikes along the bottom
      for (let i = 0; i < 26; i++) { const x = i / 25 * S.W, yy = S.H - S.u * 2; P.line([x - S.u * 3, yy, x, yy - S.u * (10 + r() * 6), x + S.u * 3, yy], S.u * 1.8, [40, 140, 50], { a: 0.9 }); }
      return;
    }
    P.mat = M.GROUND;
    const n = Math.round(det * 140 * S.W / S.H), dark = darken(c, 0.3), light = lighten(c, 0.25);
    for (let k = 0; k < n; k++) {
      const t = Math.pow(r(), 0.7), yy = y + S.H * 0.02 + t * (S.H - y), x = r() * S.W, h = S.u * (2 + t * 9);
      P.line([x - h * 0.3, yy - h, x, yy, x + h * 0.25, yy - h * 0.8], S.u * (0.5 + t * 0.8), r() < 0.5 ? dark : light, { a: 0.5, wob: 0.2 });
    }
  }
  function wildflowers(P, S, y, det, r) {
    P.mat = M.FINE;
    const acc = S.pal[5] || S.pal[3] || [240, 160, 190];
    const cols = [acc, [255, 255, 255], [250, 210, 80], [210, 120, 220], [235, 90, 90]];
    const n = Math.round(det * det * 120 * S.W / S.H);
    for (let k = 0; k < n; k++) {
      const t = Math.pow(r(), 0.8), yy = y + S.H * 0.02 + t * (S.H - y), x = r() * S.W, s = S.u * (0.7 + t * 2.2);
      P.circ(x, yy, s, cols[Math.floor(r() * cols.length)], { a: 0.9, wob: 0.2, noOutline: true });
    }
  }
  function tinyTree(P, S, x, y, s, r) {
    P.mat = M.FOLIAGE;
    const c = mix(rgb(S.leaf[2]), rgb(S.d.sky?.bottom || "#ccd"), 0.25);
    if (r() < 0.5) P.poly([x, y - s * 1.6, x + s * 0.5, y, x - s * 0.5, y], c, { wob: 0.3 });
    else { P.line([x, y, x, y - s * 0.5], Math.max(S.u * 0.6, s * 0.12), darken(c, 0.3), { wob: 0.2, noOutline: true }); P.ell(x, y - s * 0.75, s * 0.42, s * 0.5, c, { wob: 0.3 }); }
  }

  // ------------------------------------------------------------------ trees
  function blobTree(P, S, x, y, s, c) {
    P.mat = M.FOLIAGE;
    P.rect(x - s * 0.03, y - s * 0.4, s * 0.06, s * 0.4, [80, 58, 40], { wob: 0.3, noOutline: true });
    P.ell(x, y - s * 0.55, s * 0.24, s * 0.32, S.lit(c, x - s * 0.24, y - s * 0.8, x + s * 0.24, y - s * 0.3, 0.8), { wob: 0.5, smooth: true });
  }
  function pineShape(P, S, x, y, s, c, snow) {
    P.mat = M.FOLIAGE;
    const tiers = 3;
    P.rect(x - s * 0.03, y - s * 0.15, s * 0.06, s * 0.15, [80, 58, 40], { wob: 0.3, noOutline: true });
    for (let i = 0; i < tiers; i++) {
      const by = y - s * 0.1 - i * s * 0.26, w = s * (0.3 - i * 0.07), ty = by - s * 0.42;
      P.poly([x, ty, x + w, by, x - w, by], S.lit(c, x - w, ty, x + w, by, 0.8), { wob: 0.4 });
      if (snow || S.season === "winter") P.poly([x, ty, x + w * 0.45, ty + (by - ty) * 0.45, x, ty + (by - ty) * 0.38, x - w * 0.45, ty + (by - ty) * 0.45], [245, 248, 255], { wob: 0.3, noOutline: true });
    }
  }

  // ------------------------------------------------------------------ objects
  function star(P, S, x, y, r, c) {
    const p = [];
    for (let i = 0; i < 10; i++) { const a = -Math.PI / 2 + i * Math.PI / 5, rr = i % 2 ? r * 0.42 : r; p.push(x + Math.cos(a) * rr, y + Math.sin(a) * rr); }
    P.poly(p, c, { mat: M.LIGHT, wob: 0.4, emit: S.time === "night" });
  }
  const OBJ = {
    sun(P, S, x, y, s) {
      const r = s / 2, c = S.time === "evening" ? [255, 170, 90] : S.time === "dawn" ? [255, 196, 140] : [255, 236, 160];
      P.mat = M.LIGHT;
      if (S.kid > 0.5) {
        for (let i = 0; i < 10; i++) { const a = i / 10 * TAU + 0.2; P.line([x + Math.cos(a) * r * 1.25, y + Math.sin(a) * r * 1.25, x + Math.cos(a) * r * 1.9, y + Math.sin(a) * r * 1.9], S.u * 2.2, [250, 180, 30]); }
        P.circ(x, y, r, [255, 214, 40], { line: [235, 140, 20] });
        if (S.kid > 0.8) {   // a smiling sun
          P.circ(x - r * 0.35, y - r * 0.15, r * 0.09, [60, 40, 20], { wob: 0.2, noOutline: true });
          P.circ(x + r * 0.35, y - r * 0.15, r * 0.09, [60, 40, 20], { wob: 0.2, noOutline: true });
          P.ell(x, y + r * 0.2, r * 0.42, r * 0.3, [60, 40, 20], { a0: 0.3, a1: Math.PI - 0.3, open: true, w: S.u * 1.5 });
        }
        return;
      }
      P.glow(x, y, r * 7, c, 0.55, { emit: false });
      P.glow(x, y, r * 2.4, [255, 250, 230], 0.6, { emit: false });
      P.circ(x, y, r, { g: "rad", x, y, r0: 0, r1: r, s: [[0, [255, 255, 245]], [0.7, lighten(c, 0.5)], [1, c]] }, { wob: 0.3, noOutline: true });
    },
    moon(P, S, x, y, s) {
      const r = s / 2;
      P.mat = M.LIGHT;
      if (S.kid < 0.5) P.glow(x, y, r * 5, [200, 215, 255], 0.5);
      // a crescent: the outer circle minus an offset one
      const outer = [], inner = [];
      for (let i = 0; i <= 24; i++) { const a = Math.PI / 2 + i / 24 * Math.PI; outer.push(x + Math.cos(a) * r, y + Math.sin(a) * r); }
      for (let i = 23; i >= 1; i--) { const a = Math.PI / 2 + i / 24 * Math.PI; inner.push(x + Math.cos(a) * r * 0.5, y + Math.sin(a) * r * 0.96); }
      if (S.kid > 0.5) P.poly(outer.concat(inner), [255, 230, 120], { line: [200, 160, 40], emit: true });
      else {
        P.circ(x, y, r, [70, 80, 120], { a: 0.25, noOutline: true, emit: true, wob: 0.2 });
        P.poly(outer.concat(inner), { g: "rad", x: x - r * 0.4, y, r0: 0, r1: r * 1.2, s: [[0, [255, 252, 235]], [1, [228, 230, 245]]] }, { emit: true, wob: 0.3 });
      }
    },
    star(P, S, x, y, s) {
      const r = Math.max(S.u * 3, s * S.H * 0 + s / 2);
      if (S.kid > 0.5) return star(P, S, x, y, r, [255, 222, 70]);
      P.glow(x, y, r * 2.5, [255, 250, 220], 0.7);
      const p = [];
      for (let i = 0; i < 8; i++) { const a = i * Math.PI / 4, rr = i % 2 ? r * 0.18 : r; p.push(x + Math.cos(a) * rr, y + Math.sin(a) * rr); }
      P.poly(p, [255, 252, 235], { mat: M.LIGHT, emit: true, wob: 0.2, noOutline: true });
    },
    cloud(P, S, x, y, s) { cloud(P, S, x, y, s * 3, rng(Math.round(x * 13 + y))); },
    rainbow(P, S, x, y, s) {
      const cols = [[230, 70, 70], [245, 150, 60], [245, 220, 80], [90, 190, 90], [70, 140, 220], [140, 90, 200]];
      const R = s * S.W / 2, w = R * 0.045;
      P.mat = M.SKY;
      cols.forEach((c, i) => P.ell(x, y, R - i * w, R - i * w, c, { a0: Math.PI, a1: TAU, open: true, w: w * 1.1, a: S.kid > 0.5 ? 1 : 0.42, wob: 0.4 }));
    },
    bird(P, S, x, y, s) {
      const w = s * 0.5;
      P.mat = M.FINE;
      P.line([x - w, y - w * 0.3, x - w * 0.45, y - w * 0.55, x, y, x + w * 0.45, y - w * 0.55, x + w, y - w * 0.3], S.u * (1 + w / 30), S.time === "night" ? [30, 30, 50] : [50, 45, 60], { smooth: true, wob: 0.5 });
    },
    kite(P, S, x, y, s, o) {
      const w = s * 0.35, h = s * 0.5, c = o.color ? rgb(o.color) : S.col([230, 80, 90], 21);
      P.mat = M.OBJ;
      P.line([x, y + h * 0.6, x + w * 0.5, y + h * 1.2, x - w * 0.2, y + h * 1.8, x + w * 0.3, y + h * 2.6], S.u * 0.8, [80, 70, 60], { smooth: true });
      [0.9, 1.5, 2.1].forEach((t, i) => P.poly([x + Math.sin(t * 3) * w * 0.3 - w * 0.12, y + h * t - w * 0.08, x + Math.sin(t * 3) * w * 0.3 + w * 0.12, y + h * t + w * 0.08, x + Math.sin(t * 3) * w * 0.3 + w * 0.12, y + h * t - w * 0.08, x + Math.sin(t * 3) * w * 0.3 - w * 0.12, y + h * t + w * 0.08], i % 2 ? [250, 210, 80] : [80, 160, 230]));
      P.poly([x, y - h * 0.6, x + w, y, x, y + h * 0.6, x - w, y], S.lit(c, x - w, y, x + w, y));
      P.line([x, y - h * 0.6, x, y + h * 0.6], S.u * 0.6, darken(c, 0.4), { a: 0.6 });
      P.line([x - w, y, x + w, y], S.u * 0.6, darken(c, 0.4), { a: 0.6 });
    },
    butterfly(P, S, x, y, s, o) {
      const w = s * 0.32, c = o.color ? rgb(o.color) : S.col([240, 150, 60], 23);
      P.mat = M.FINE;
      P.ell(x - w * 0.55, y - w * 0.35, w * 0.55, w * 0.42, c, { rot: -0.5 });
      P.ell(x + w * 0.55, y - w * 0.35, w * 0.55, w * 0.42, c, { rot: 0.5 });
      P.ell(x - w * 0.4, y + w * 0.3, w * 0.35, w * 0.3, lighten(c, 0.2), { rot: 0.4 });
      P.ell(x + w * 0.4, y + w * 0.3, w * 0.35, w * 0.3, lighten(c, 0.2), { rot: -0.4 });
      P.ell(x, y, w * 0.1, w * 0.55, [50, 40, 40], { noOutline: true });
      P.line([x, y - w * 0.5, x - w * 0.3, y - w * 1.0], S.u * 0.5, [50, 40, 40]);
      P.line([x, y - w * 0.5, x + w * 0.3, y - w * 1.0], S.u * 0.5, [50, 40, 40]);
    },
    fireflies(P, S, x, y, s) {
      const r = rng(Math.round(x * 7 + y * 3));
      for (let i = 0; i < 14; i++) {
        const px = x + (r() - 0.5) * s * 2.5, py = y - r() * s * 1.5;
        P.glow(px, py, S.u * (3 + r() * 4), [230, 255, 120], 0.8);
        P.circ(px, py, S.u * 0.9, [250, 255, 190], { mat: M.LIGHT, emit: true, noOutline: true, wob: 0.1 });
      }
    },
    bee(P, S, x, y, s) {
      const w = s * 0.3;
      P.mat = M.FINE;
      P.ell(x - w * 0.15, y - w * 0.55, w * 0.35, w * 0.45, [235, 245, 255], { a: 0.75, rot: -0.4 });
      P.ell(x + w * 0.2, y - w * 0.5, w * 0.3, w * 0.4, [235, 245, 255], { a: 0.75, rot: 0.4 });
      P.ell(x, y, w * 0.55, w * 0.38, [245, 190, 40]);
      P.line([x - w * 0.12, y - w * 0.36, x - w * 0.12, y + w * 0.36], w * 0.16, [40, 30, 20], { noOutline: true });
      P.line([x + w * 0.2, y - w * 0.32, x + w * 0.2, y + w * 0.32], w * 0.16, [40, 30, 20], { noOutline: true });
    },
    tree(P, S, x, y, s, o, apples) {
      const leaf = o.color ? rgb(o.color) : S.col(S.leaf[0], 31), dark = rgb(S.leaf[2]), trunk = S.col([110, 76, 48], 32);
      P.mat = M.OBJ;
      shadow(P, S, x, y, s * 0.32);
      if (S.kid > 0.5) {   // a lollipop tree
        P.rect(x - s * 0.07, y - s * 0.55, s * 0.14, s * 0.55, trunk);
        P.mat = M.FOLIAGE;
        P.circ(x, y - s * 0.68, s * 0.3, leaf);
        if (apples) for (let i = 0; i < 5; i++) P.circ(x + Math.cos(i * 2.1) * s * 0.17, y - s * 0.68 + Math.sin(i * 2.1) * s * 0.15, s * 0.045, [220, 40, 40]);
        return;
      }
      // trunk and a few branches
      P.poly([x - s * 0.05, y, x - s * 0.03, y - s * 0.5, x + s * 0.03, y - s * 0.5, x + s * 0.06, y], S.lit(trunk, x - s * 0.05, y, x + s * 0.06, y), { wob: 0.4 });
      P.line([x, y - s * 0.42, x - s * 0.15, y - s * 0.62], s * 0.025, trunk, { wob: 0.4 });
      P.line([x, y - s * 0.38, x + s * 0.16, y - s * 0.58], s * 0.025, trunk, { wob: 0.4 });
      if (S.season === "winter") {   // bare branches, a little snow
        const r = rng(Math.round(x * 3 + y));
        for (let i = 0; i < 9; i++) { const a = -Math.PI / 2 + (r() - 0.5) * 2.2, l = s * (0.18 + r() * 0.25), bx = x + (r() - 0.5) * s * 0.06, by = y - s * (0.45 + r() * 0.1); P.line([bx, by, bx + Math.cos(a) * l, by + Math.sin(a) * l], S.u * 0.8, trunk, { wob: 0.3 }); }
        return;
      }
      P.mat = M.FOLIAGE;
      const r = rng(Math.round(x * 7 + y * 13)), blobs = S.shade > 0.4 ? 7 : 4, cy = y - s * 0.68;
      if (S.season === "spring" && S.shade > 0.3) leafCanopy(P, S, x, cy, s, blossomMix(leaf), dark, r, blobs);
      else leafCanopy(P, S, x, cy, s, leaf, dark, r, blobs);
      if (apples) {
        const ar = rng(Math.round(x * 11));
        for (let i = 0; i < 9; i++) { const a = ar() * TAU, d = Math.sqrt(ar()) * s * 0.24; P.circ(x + Math.cos(a) * d, cy + Math.sin(a) * d * 0.8, s * 0.035, S.lit([214, 40, 40], 0, 0, 1, 1, 0.2), { mat: M.FINE, wob: 0.2 }); }
      }
    },
    pine(P, S, x, y, s, o) {
      shadow(P, S, x, y, s * 0.25);
      const c = o.color ? rgb(o.color) : S.col([46, 104, 70], 33);
      if (S.kid > 0.5) { P.mat = M.OBJ; P.rect(x - s * 0.05, y - s * 0.2, s * 0.1, s * 0.2, [110, 76, 48]); P.mat = M.FOLIAGE; P.poly([x, y - s, x + s * 0.28, y - s * 0.2, x - s * 0.28, y - s * 0.2], c); return; }
      pineShape(P, S, x, y, s, c);
    },
    "apple tree"(P, S, x, y, s, o) { OBJ.tree(P, S, x, y, s, o, true); },
    house(P, S, x, y, s, o) {
      const wall = o.color ? rgb(o.color) : S.col([236, 220, 190], 41), roof = S.col([168, 78, 58], 42), w = s * 0.85, h = s * 0.5;
      const x0 = x - w / 2, y0 = y - h;
      P.mat = M.OBJ;
      shadow(P, S, x, y, w * 0.6);
      if (S.kid > 0.5) {   // a square with a triangle on top
        P.rect(x0, y0, w, h, wall);
        P.poly([x0 - w * 0.08, y0, x, y0 - h * 0.75, x0 + w * 1.08, y0], roof);
        P.rect(x - w * 0.1, y - h * 0.5, w * 0.2, h * 0.5, [120, 70, 40]);
        winCross(P, S, x0 + w * 0.12, y0 + h * 0.18, w * 0.2, h * 0.25);
        winCross(P, S, x0 + w * 0.68, y0 + h * 0.18, w * 0.2, h * 0.25);
        P.rect(x0 + w * 0.68, y0 - h * 0.6, w * 0.1, h * 0.35, [200, 80, 60]);
        return;
      }
      // a cottage seen a little from the side: front gable and a side wall
      const side = S.lx < 0 ? 1 : -1, sw = w * 0.45, gx0 = side > 0 ? x0 : x0 + sw, gw = w - sw;
      const sx0 = side > 0 ? gx0 + gw : x0;
      // chimney
      P.rect(sx0 + sw * 0.6, y0 - h * 0.75, w * 0.08, h * 0.5, darken(roof, 0.25));
      if (S.shade > 0.5 && S.weather !== "storm") P.line([sx0 + sw * 0.64, y0 - h * 0.8, sx0 + sw * 0.5, y0 - h * 1.3, sx0 + sw * 0.8, y0 - h * 1.8, sx0 + sw * 0.55, y0 - h * 2.3], S.u * 3, [220, 220, 225], { a: 0.35, smooth: true, noOutline: true, mat: M.SKY });
      P.rect(sx0, y0, sw, h, darken(wall, 0.18 * S.shade + 0.03), { wob: 0.5 });
      P.poly([gx0, y0, gx0 + gw / 2, y0 - h * 0.62, gx0 + gw, y0, gx0 + gw, y, gx0, y], S.lit(wall, gx0, y0, gx0 + gw, y), { wob: 0.5 });
      // roof over the side wall
      const rx = gx0 + gw / 2, ry = y0 - h * 0.62;
      P.poly(side > 0 ? [rx, ry, rx + sw + gw * 0.05, ry, gx0 + gw + sw + gw * 0.08, y0 + h * 0.04, gx0 + gw + gw * 0.04, y0 + h * 0.04] :
        [rx, ry, rx - sw - gw * 0.05, ry, gx0 - sw - gw * 0.08, y0 + h * 0.04, gx0 - gw * 0.04, y0 + h * 0.04], S.lit(roof, sx0, ry, sx0 + sw, y0, 0.6), { wob: 0.5 });
      P.line([gx0 - gw * 0.06, y0 + h * 0.05, rx, ry - h * 0.02, gx0 + gw * 1.06, y0 + h * 0.05], S.u * 2.2, darken(roof, 0.2), { wob: 0.4 });
      // door, windows
      P.rect(rx - gw * 0.12, y - h * 0.55, gw * 0.24, h * 0.55, S.col([110, 70, 50], 43), { wob: 0.4 });
      P.circ(rx + gw * 0.07, y - h * 0.27, S.u * 0.9, [230, 200, 120], { noOutline: true, wob: 0.1 });
      winLit(P, S, rx - gw * 0.07, y0 - h * 0.25, gw * 0.14, h * 0.18);
      winLit(P, S, sx0 + sw * 0.25, y0 + h * 0.25, sw * 0.22, h * 0.26);
      winLit(P, S, sx0 + sw * 0.6, y0 + h * 0.25, sw * 0.22, h * 0.26);
    },
    barn(P, S, x, y, s, o) {
      const red = o.color ? rgb(o.color) : S.col([168, 48, 40], 51), w = s * 0.95, h = s * 0.55, x0 = x - w / 2, y0 = y - h;
      P.mat = M.OBJ;
      shadow(P, S, x, y, w * 0.6);
      // a gambrel roof
      P.poly([x0, y0, x0 + w * 0.12, y0 - h * 0.45, x, y0 - h * 0.7, x0 + w * 0.88, y0 - h * 0.45, x0 + w, y0, x0 + w, y, x0, y], S.lit(red, x0, y0, x0 + w, y), { wob: 0.5 });
      P.line([x0 - w * 0.03, y0 + h * 0.02, x0 + w * 0.12, y0 - h * 0.45, x, y0 - h * 0.72, x0 + w * 0.88, y0 - h * 0.45, x0 + w * 1.03, y0 + h * 0.02], S.u * 2.5, [70, 60, 60], { wob: 0.4 });
      const dw = w * 0.36, dx = x - dw / 2, dy = y - h * 0.7;
      P.rect(dx, dy, dw, h * 0.7, darken(red, 0.2), { wob: 0.4 });
      P.line([dx, dy, dx + dw, y], S.u * 1.6, [245, 240, 230], { wob: 0.3 });
      P.line([dx + dw, dy, dx, y], S.u * 1.6, [245, 240, 230], { wob: 0.3 });
      P.line([dx, dy, dx + dw, dy, dx + dw, y, dx, y, dx, dy], S.u * 1.6, [245, 240, 230], { wob: 0.3 });
      winLit(P, S, x - w * 0.08, y0 - h * 0.35, w * 0.16, h * 0.18);
    },
    greenhouse(P, S, x, y, s) {
      const w = s * 0.9, h = s * 0.42, x0 = x - w / 2, y0 = y - h, ry = y0 - h * 0.45;
      P.mat = M.OBJ;
      shadow(P, S, x, y, w * 0.6);
      const glass = mix(rgb(S.d.sky?.top || "#9cf"), [200, 235, 230], 0.45), frame = [250, 250, 246];
      P.rect(x0, y - h * 0.18, w, h * 0.18, S.lit([170, 96, 70], x0, 0, x0 + w, 0));   // a brick curb
      P.poly([x0, y - h * 0.18, x0, y0, x, ry, x0 + w, y0, x0 + w, y - h * 0.18], { g: "lin", x0, y0: ry, x1: x0 + w, y1: y, s: [[0, lighten(glass, 0.55)], [0.45, glass], [1, mix(glass, [70, 120, 90], 0.45)]] }, { a: 0.92, wob: 0.4 });
      P.mat = M.FOLIAGE;
      for (let i = 0; i < 6; i++) P.circ(x0 + w * (0.12 + i * 0.15), y - h * 0.3, h * 0.17, rgb(S.leaf[i % 2]), { a: 0.75, wob: 0.4, noOutline: true });
      P.mat = M.OBJ;
      if (S.shade > 0.3) P.poly([x0 + w * 0.08, y0 + h * 0.05, x0 + w * 0.35, ry + h * 0.2, x0 + w * 0.42, ry + h * 0.25, x0 + w * 0.16, y0 + h * 0.3], [255, 255, 255], { a: 0.45, noOutline: true });
      for (let i = 1; i < 6; i++) P.line([x0 + w * i / 6, y - h * 0.18, x0 + w * i / 6, y0 - h * 0.45 * (1 - Math.abs(i / 6 - 0.5) * 2)], S.u * 1.1, frame, { wob: 0.3 });
      P.line([x0, y - h * 0.18, x0, y0, x, ry, x0 + w, y0, x0 + w, y - h * 0.18], S.u * 1.6, frame, { wob: 0.3 });
      P.line([x0, y0, x0 + w, y0], S.u * 1.1, frame, { wob: 0.3 });
    },
    fence(P, S, x, y, s, o) {
      const c = o.color ? rgb(o.color) : S.col([196, 168, 130], 61), w = s * 2.6, n = 7, h = s * 0.4;
      P.mat = M.OBJ;
      for (let i = 0; i < 2; i++) P.line([x - w / 2, y - h * (0.35 + i * 0.4), x + w / 2, y - h * (0.3 + i * 0.4)], S.u * 1.2 + s * 0.025, darken(c, 0.1), { wob: 0.6 });
      for (let i = 0; i < n; i++) { const px = x - w / 2 + w * i / (n - 1); P.poly([px - s * 0.03, y, px - s * 0.03, y - h, px, y - h * 1.12, px + s * 0.03, y - h, px + s * 0.03, y], S.lit(c, px - s * 0.03, y, px + s * 0.03, y), { wob: 0.4 }); }
    },
    bench(P, S, x, y, s, o) {
      const c = o.color ? rgb(o.color) : S.col([140, 96, 60], 62), w = s * 0.8, h = s * 0.32;
      P.mat = M.OBJ;
      shadow(P, S, x, y, w * 0.5);
      P.rect(x - w * 0.42, y - h, s * 0.04, h, darken(c, 0.3)); P.rect(x + w * 0.38, y - h, s * 0.04, h, darken(c, 0.3));
      P.rect(x - w / 2, y - h * 1.05, w, h * 0.16, S.lit(c, x - w / 2, y, x + w / 2, y));
      P.rect(x - w / 2, y - h * 1.9, w, h * 0.14, c); P.rect(x - w / 2, y - h * 1.6, w, h * 0.14, c);
      P.rect(x - w * 0.44, y - h * 1.95, s * 0.035, h * 0.95, darken(c, 0.25)); P.rect(x + w * 0.41, y - h * 1.95, s * 0.035, h * 0.95, darken(c, 0.25));
    },
    lamp(P, S, x, y, s) {
      P.mat = M.OBJ;
      P.rect(x - s * 0.025, y - s * 0.8, s * 0.05, s * 0.8, [50, 52, 58]);
      P.rect(x - s * 0.07, y - s * 0.02, s * 0.14, s * 0.03, [50, 52, 58]);
      const on = S.night > 0 || S.time === "dawn" || S.weather === "fog" || S.weather === "storm";
      if (on) P.glow(x, y - s * 0.9, s * 0.8, [255, 200, 110], 0.7);
      P.poly([x - s * 0.08, y - s * 0.82, x + s * 0.08, y - s * 0.82, x + s * 0.06, y - s * 0.98, x - s * 0.06, y - s * 0.98], on ? [255, 214, 130] : [220, 225, 225], { mat: M.LIGHT, emit: on });
      P.poly([x - s * 0.1, y - s * 0.98, x + s * 0.1, y - s * 0.98, x, y - s * 1.08], [50, 52, 58]);
    },
    beehive(P, S, x, y, s) {   // a straw skep
      const w = s * 0.45, h = s * 0.5, c = [214, 170, 80];
      P.mat = M.OBJ;
      shadow(P, S, x, y, w * 0.8);
      P.rect(x - w * 0.7, y - h * 0.12, w * 1.4, h * 0.12, [130, 96, 60]);
      P.ell(x, y - h * 0.12, w * 0.62, h, S.lit(c, x - w, y - h, x + w, y), { a0: Math.PI, a1: TAU });
      for (let i = 1; i < 5; i++) { const yy = y - h * 0.12 - h * i / 5.5, ww = w * 0.62 * Math.sqrt(1 - Math.pow(i / 5.5, 2)); P.line([x - ww, yy, x + ww, yy], S.u * 0.9, darken(c, 0.35), { a: 0.7 }); }
      P.ell(x, y - h * 0.2, w * 0.1, h * 0.07, [60, 40, 20], { noOutline: true });
    },
    scarecrow(P, S, x, y, s, o) {
      const c = o.color ? rgb(o.color) : S.col([90, 120, 170], 71);
      P.mat = M.OBJ;
      P.rect(x - s * 0.02, y - s * 0.85, s * 0.04, s * 0.85, [120, 86, 52]);
      P.line([x - s * 0.32, y - s * 0.6, x + s * 0.32, y - s * 0.6], s * 0.035, [120, 86, 52]);
      P.poly([x - s * 0.14, y - s * 0.66, x + s * 0.14, y - s * 0.66, x + s * 0.18, y - s * 0.3, x - s * 0.18, y - s * 0.3], S.lit(c, x - s * 0.18, 0, x + s * 0.18, 0));
      P.line([x - s * 0.3, y - s * 0.6, x - s * 0.38, y - s * 0.56], s * 0.03, [230, 196, 90]); P.line([x + s * 0.3, y - s * 0.6, x + s * 0.38, y - s * 0.56], s * 0.03, [230, 196, 90]);
      P.circ(x, y - s * 0.76, s * 0.1, [236, 214, 160]);
      P.poly([x - s * 0.18, y - s * 0.82, x + s * 0.18, y - s * 0.82, x + s * 0.08, y - s * 0.86, x + s * 0.06, y - s * 1.0, x - s * 0.06, y - s * 1.0, x - s * 0.08, y - s * 0.86], [110, 80, 50]);
      P.line([x - s * 0.04, y - s * 0.72, x + s * 0.04, y - s * 0.72], S.u * 0.7, [60, 40, 30]);
    },
    flower(P, S, x, y, s, o) {
      const c = o.color ? rgb(o.color) : S.col(S.pal[5] || [236, 110, 150], 81 + Math.round(x));
      P.mat = M.FINE;
      P.line([x, y, x + s * 0.03, y - s * 0.5, x, y - s * 0.75], Math.max(S.u * 0.8, s * 0.035), [70, 140, 60], { smooth: true });
      P.ell(x + s * 0.1, y - s * 0.32, s * 0.11, s * 0.05, [90, 160, 70], { rot: -0.6 });
      const r = s * 0.13, cy = y - s * 0.8;
      for (let i = 0; i < 6; i++) { const a = i / 6 * TAU; P.ell(x + Math.cos(a) * r, cy + Math.sin(a) * r, r * 0.75, r * 0.5, S.lit(c, x - r * 2, cy, x + r * 2, cy, 0.5), { rot: a }); }
      P.circ(x, cy, r * 0.55, [250, 205, 60]);
    },
    sunflower(P, S, x, y, s) {
      P.mat = M.OBJ;
      P.line([x, y, x - s * 0.03, y - s * 0.5, x, y - s * 0.85], Math.max(S.u, s * 0.04), [80, 140, 60], { smooth: true });
      P.ell(x - s * 0.12, y - s * 0.45, s * 0.14, s * 0.06, [80, 150, 60], { rot: 0.5 });
      P.ell(x + s * 0.12, y - s * 0.3, s * 0.14, s * 0.06, [80, 150, 60], { rot: -0.5 });
      const r = s * 0.17, cy = y - s * 0.88;
      for (let i = 0; i < 14; i++) { const a = i / 14 * TAU; P.ell(x + Math.cos(a) * r * 1.05, cy + Math.sin(a) * r * 1.05, r * 0.55, r * 0.2, S.lit([250, 196, 30], x - r, cy, x + r, cy, 0.5), { rot: a, mat: M.FINE }); }
      P.circ(x, cy, r * 0.62, { g: "rad", x: x - r * 0.2, y: cy - r * 0.2, r0: 0, r1: r * 0.7, s: [[0, [140, 90, 40]], [1, [80, 50, 25]]] });
    },
    pumpkin(P, S, x, y, s, o) {
      const c = o.color ? rgb(o.color) : S.col([232, 120, 30], 91), w = s * 0.42, h = s * 0.3;
      P.mat = M.OBJ;
      shadow(P, S, x, y, w);
      for (let i = -2; i <= 2; i++) P.ell(x + i * w * 0.32, y - h * 0.55, w * (0.42 - Math.abs(i) * 0.06), h * 0.55, S.lit(c, x - w, y - h, x + w, y), { smooth: true });
      P.line([x, y - h * 1.0, x + w * 0.08, y - h * 1.35], s * 0.05, [100, 110, 50]);
    },
    mushroom(P, S, x, y, s, o) {
      const c = o.color ? rgb(o.color) : S.col([200, 50, 40], 92), w = s * 0.35;
      P.mat = M.OBJ;
      shadow(P, S, x, y, w * 0.6);
      P.poly([x - w * 0.2, y, x - w * 0.15, y - s * 0.4, x + w * 0.15, y - s * 0.4, x + w * 0.22, y], S.lit([245, 238, 220], x - w * 0.2, 0, x + w * 0.2, 0));
      P.ell(x, y - s * 0.4, w * 0.75, s * 0.32, S.lit(c, x - w, y - s * 0.7, x + w, y - s * 0.3), { a0: Math.PI, a1: TAU });
      for (let i = 0; i < 5; i++) P.circ(x + (i - 2) * w * 0.28, y - s * (0.52 + (i % 2) * 0.1), w * 0.08, [255, 250, 240], { noOutline: true, mat: M.FINE });
    },
    rock(P, S, x, y, s, o) {
      const c = o.color ? rgb(o.color) : S.col([140, 138, 132], 93), w = s * 0.5, h = s * 0.35, r = rng(Math.round(x * 5 + y));
      P.mat = M.OBJ;
      shadow(P, S, x, y, w);
      const p = [];
      for (let i = 0; i <= 10; i++) { const a = Math.PI + i / 10 * Math.PI; p.push(x + Math.cos(a) * w * (0.85 + r() * 0.2), y + Math.sin(a) * h * (0.8 + r() * 0.35)); }
      P.poly(p, S.lit(c, x - w, y - h, x + w, y));
      if (S.season === "winter") P.ell(x, y - h * 0.85, w * 0.55, h * 0.18, [245, 248, 255], { noOutline: true });
      else if (S.shade > 0.5) P.ell(x - w * 0.3, y - h * 0.3, w * 0.25, h * 0.15, [110, 140, 70], { a: 0.6, noOutline: true });
    },
    snowman(P, S, x, y, s) {
      P.mat = M.OBJ;
      shadow(P, S, x, y, s * 0.3);
      const white = { g: "rad", x: x - s * 0.08, y: y - s * 0.5, r0: 0, r1: s * 0.5, s: [[0, [255, 255, 255]], [1, [200, 214, 236]]] };
      P.circ(x, y - s * 0.2, s * 0.21, S.shade > 0.2 ? white : [250, 250, 255]);
      P.circ(x, y - s * 0.53, s * 0.15, S.shade > 0.2 ? white : [250, 250, 255]);
      P.circ(x, y - s * 0.76, s * 0.11, S.shade > 0.2 ? white : [250, 250, 255]);
      P.rect(x - s * 0.09, y - s * 0.98, s * 0.18, s * 0.13, [40, 40, 50]); P.rect(x - s * 0.13, y - s * 0.86, s * 0.26, s * 0.03, [40, 40, 50]);
      P.circ(x - s * 0.04, y - s * 0.79, s * 0.015, [20, 20, 20], { noOutline: true }); P.circ(x + s * 0.04, y - s * 0.79, s * 0.015, [20, 20, 20], { noOutline: true });
      P.poly([x, y - s * 0.76, x + s * 0.12, y - s * 0.74, x, y - s * 0.73], [240, 130, 40], { noOutline: true });
      P.rect(x - s * 0.13, y - s * 0.66, s * 0.26, s * 0.05, [200, 60, 60]);
      P.line([x - s * 0.14, y - s * 0.55, x - s * 0.32, y - s * 0.68], S.u * 1.2, [100, 70, 40]); P.line([x + s * 0.14, y - s * 0.55, x + s * 0.32, y - s * 0.7], S.u * 1.2, [100, 70, 40]);
    },
    cat(P, S, x, y, s, o) {   // Moss, sitting, seen from behind-ish
      const c = o.color ? rgb(o.color) : S.col([96, 96, 104], 101), w = s * 0.32;
      P.mat = M.OBJ;
      shadow(P, S, x, y, w * 1.1);
      P.line([x + w * 0.6, y - s * 0.05, x + w * 1.3, y - s * 0.1, x + w * 1.25, y - s * 0.4], s * 0.06, c, { smooth: true });
      P.ell(x, y - s * 0.3, w, s * 0.31, S.lit(c, x - w, y - s * 0.6, x + w, y), { smooth: true });
      const hy = y - s * 0.7, hr = w * 0.62;
      P.poly([x - hr * 0.95, hy - hr * 0.2, x - hr * 0.75, hy - hr * 1.25, x - hr * 0.15, hy - hr * 0.7], c);
      P.poly([x + hr * 0.95, hy - hr * 0.2, x + hr * 0.75, hy - hr * 1.25, x + hr * 0.15, hy - hr * 0.7], c);
      P.circ(x, hy, hr, S.lit(c, x - hr, hy - hr, x + hr, hy + hr));
      P.ell(x - hr * 0.38, hy - hr * 0.05, hr * 0.17, hr * 0.22, [190, 210, 90], { noOutline: true });
      P.ell(x + hr * 0.38, hy - hr * 0.05, hr * 0.17, hr * 0.22, [190, 210, 90], { noOutline: true });
      P.ell(x - hr * 0.38, hy - hr * 0.05, hr * 0.06, hr * 0.18, [20, 20, 20], { noOutline: true, wob: 0 });
      P.ell(x + hr * 0.38, hy - hr * 0.05, hr * 0.06, hr * 0.18, [20, 20, 20], { noOutline: true, wob: 0 });
      P.poly([x - hr * 0.1, hy + hr * 0.25, x + hr * 0.1, hy + hr * 0.25, x, hy + hr * 0.38], [230, 150, 150], { noOutline: true });
    },
    hen(P, S, x, y, s, o) {
      const c = o.color ? rgb(o.color) : S.col([180, 110, 60], 102), w = s * 0.36;
      P.mat = M.OBJ;
      shadow(P, S, x, y, w);
      P.line([x - w * 0.15, y - s * 0.25, x - w * 0.2, y], S.u * 1, [220, 160, 40]); P.line([x + w * 0.15, y - s * 0.25, x + w * 0.1, y], S.u * 1, [220, 160, 40]);
      P.poly([x - w * 1.0, y - s * 0.55, x - w * 0.75, y - s * 0.75, x - w * 0.6, y - s * 0.45], darken(c, 0.25));
      P.ell(x - w * 0.05, y - s * 0.42, w * 0.85, s * 0.22, S.lit(c, x - w, y - s * 0.6, x + w, y - s * 0.2), { smooth: true });
      P.circ(x + w * 0.6, y - s * 0.66, w * 0.33, c);
      P.poly([x + w * 0.45, y - s * 0.8, x + w * 0.55, y - s * 0.92, x + w * 0.65, y - s * 0.84, x + w * 0.75, y - s * 0.93, x + w * 0.8, y - s * 0.78], [220, 40, 40]);
      P.poly([x + w * 0.9, y - s * 0.68, x + w * 1.12, y - s * 0.64, x + w * 0.9, y - s * 0.6], [240, 180, 40], { noOutline: true });
      P.circ(x + w * 0.7, y - s * 0.7, S.u * 0.9 + w * 0.04, [20, 20, 20], { noOutline: true, wob: 0 });
      P.ell(x - w * 0.15, y - s * 0.44, w * 0.45, s * 0.1, darken(c, 0.15), { rot: 0.2 });
    },
    deer(P, S, x, y, s, o) {
      const c = o.color ? rgb(o.color) : S.col([160, 104, 60], 103), w = s * 0.5;
      P.mat = M.OBJ;
      shadow(P, S, x, y, w * 0.9);
      const leg = (lx, a) => P.line([lx, y - s * 0.42, lx + a, y - s * 0.2, lx, y], S.u * 0.8 + s * 0.03, darken(c, 0.15));
      leg(x - w * 0.6, -s * 0.02); leg(x - w * 0.42, s * 0.02); leg(x + w * 0.4, -s * 0.02); leg(x + w * 0.56, s * 0.02);
      P.ell(x, y - s * 0.48, w * 0.72, s * 0.15, S.lit(c, x - w, y - s * 0.6, x + w, y - s * 0.35), { smooth: true });
      P.poly([x + w * 0.45, y - s * 0.55, x + w * 0.6, y - s * 0.85, x + w * 0.75, y - s * 0.82, x + w * 0.68, y - s * 0.5], c);
      P.ell(x + w * 0.78, y - s * 0.86, w * 0.2, s * 0.07, c, { rot: 0.3 });
      P.ell(x + w * 0.6, y - s * 0.95, w * 0.07, s * 0.05, c, { rot: -0.6 });
      P.line([x + w * 0.66, y - s * 0.93, x + w * 0.6, y - s * 1.1, x + w * 0.5, y - s * 1.16], S.u * 0.7 + s * 0.012, [90, 64, 40]);
      P.line([x + w * 0.61, y - s * 1.04, x + w * 0.72, y - s * 1.12], S.u * 0.7 + s * 0.012, [90, 64, 40]);
      P.circ(x + w * 0.83, y - s * 0.88, S.u * 0.6 + s * 0.012, [20, 20, 20], { noOutline: true, wob: 0 });
      P.ell(x - w * 0.72, y - s * 0.52, w * 0.08, s * 0.05, [245, 240, 230], { noOutline: true });
    },
    figure(P, S, x, y, s, o) {
      const label = String(o.label || "").toLowerCase();
      P.mat = M.OBJ;
      shadow(P, S, x, y, s * 0.18);
      if (/zen|synth|me|ada/.test(label)) {   // the synth: a glowing little orb with eyes
        const r = s * 0.22, cy = y - s * 0.4;
        P.glow(x, cy, r * 3, [140, 170, 255], 0.6);
        P.circ(x, cy, r, { g: "rad", x: x - r * 0.3, y: cy - r * 0.3, r0: 0, r1: r * 1.2, s: [[0, [235, 245, 255]], [0.5, [140, 170, 255]], [1, [110, 90, 220]]] }, { emit: S.night > 0.5 });
        P.ell(x - r * 0.33, cy, r * 0.1, r * 0.17, [24, 32, 58], { noOutline: true, wob: 0 });
        P.ell(x + r * 0.33, cy, r * 0.1, r * 0.17, [24, 32, 58], { noOutline: true, wob: 0 });
        return;
      }
      const body = o.color ? rgb(o.color) : S.col(/wren/.test(label) ? [110, 160, 140] : [200, 90, 80], 111), skin = [236, 196, 160];
      P.line([x - s * 0.06, y - s * 0.35, x - s * 0.07, y], S.u * 0.8 + s * 0.04, [70, 60, 70]);
      P.line([x + s * 0.06, y - s * 0.35, x + s * 0.07, y], S.u * 0.8 + s * 0.04, [70, 60, 70]);
      P.poly([x - s * 0.12, y - s * 0.72, x + s * 0.12, y - s * 0.72, x + s * 0.19, y - s * 0.3, x - s * 0.19, y - s * 0.3], S.lit(body, x - s * 0.2, 0, x + s * 0.2, 0));
      P.line([x - s * 0.12, y - s * 0.68, x - s * 0.22, y - s * 0.42], S.u * 0.8 + s * 0.04, body); P.line([x + s * 0.12, y - s * 0.68, x + s * 0.23, y - s * 0.45], S.u * 0.8 + s * 0.04, body);
      P.circ(x, y - s * 0.84, s * 0.12, S.lit(skin, x - s * 0.12, 0, x + s * 0.12, 0, 0.5));
      P.ell(x, y - s * 0.92, s * 0.13, s * 0.07, /wren/.test(label) ? [110, 70, 40] : [60, 40, 30], { a0: Math.PI, a1: TAU });
    },
    path(P, S, x, y, s) {
      P.mat = M.GROUND;
      const c = S.season === "winter" ? [228, 234, 240] : [200, 170, 120], w = s * 0.8;
      P.poly([x - w * 0.1, y - s * 0.3, x + w * 0.1, y - s * 0.3, x + w * 0.5, y + s * 0.3, x - w * 0.5, y + s * 0.3], c, { a: 0.85, smooth: true, noOutline: S.kid < 0.5 });
    },
    duck(P, S, x, y, s, o) {
      const c = o.color ? rgb(o.color) : [245, 242, 232], w = s * 0.42;
      P.mat = M.OBJ;
      const draw = () => {
        P.poly([x - w, y - s * 0.3, x - w * 1.15, y - s * 0.45, x - w * 0.7, y - s * 0.38], c);
        P.ell(x - w * 0.1, y - s * 0.24, w * 0.9, s * 0.2, S.lit(c, x - w, y - s * 0.4, x + w, y), { a0: Math.PI - 0.2, a1: TAU + 0.2 });
        P.poly([x - w * 0.95, y - s * 0.22, x + w * 0.8, y - s * 0.22, x + w * 0.6, y - s * 0.04, x - w * 0.7, y - s * 0.04], S.lit(c, x - w, y - s * 0.4, x + w, y));
        P.ell(x + w * 0.55, y - s * 0.62, w * 0.3, w * 0.28, o.color ? c : [40, 110, 70]);
        P.line([x + w * 0.45, y - s * 0.38, x + w * 0.5, y - s * 0.55], w * 0.22, o.color ? c : [40, 110, 70]);
        P.poly([x + w * 0.8, y - s * 0.66, x + w * 1.1, y - s * 0.6, x + w * 0.8, y - s * 0.56], [240, 160, 40], { noOutline: true });
        P.circ(x + w * 0.62, y - s * 0.66, S.u * 0.5 + w * 0.04, [15, 15, 15], { noOutline: true, wob: 0 });
      };
      draw();
      if (S.waterY != null && y > S.waterY) { P.mirror(y - s * 0.04, 0.3, draw); P.ell(x, y - s * 0.04, w * 1.3, s * 0.05, [255, 255, 255], { a: 0.4, open: true, w: S.u * 0.8, a0: 0.2, a1: Math.PI - 0.2 }); }
    },
    boat(P, S, x, y, s, o) {
      const c = o.color ? rgb(o.color) : S.col([150, 90, 50], 121), w = s * 0.6, h = s * 0.16;
      P.mat = M.OBJ;
      const draw = () => {
        P.line([x, y - h, x, y - s * 0.95], S.u * 0.8 + s * 0.015, [80, 60, 40]);
        P.poly([x + s * 0.02, y - s * 0.92, x + s * 0.02, y - h * 1.4, x + w * 0.7, y - h * 1.5], S.lit([248, 244, 232], x, 0, x + w * 0.7, 0, 0.6));
        P.poly([x - s * 0.02, y - s * 0.75, x - s * 0.02, y - h * 1.4, x - w * 0.45, y - h * 1.5], [236, 226, 210]);
        P.poly([x - w, y - h, x + w, y - h, x + w * 0.7, y, x - w * 0.75, y], S.lit(c, x - w, 0, x + w, 0));
        P.line([x - w, y - h, x + w, y - h], S.u * 1.2, lighten(c, 0.3), { noOutline: true });
      };
      draw();
      if (S.waterY != null && y > S.waterY) P.mirror(y, 0.28, draw);
    },
    jetty(P, S, x, y, s) {
      const c = S.col([150, 116, 80], 122), w = s * 1.4, h = s * 0.06, x0 = x - w * 0.5, top = y - s * 0.22;
      P.mat = M.OBJ;
      const draw = () => {
        for (let i = 0; i < 5; i++) P.rect(x0 + w * i / 4 - s * 0.015, top, s * 0.03, s * 0.24, darken(c, 0.35));
        P.poly([x0 - w * 0.1, top, x0 + w + w * 0.1, top, x0 + w + w * 0.05, top - h, x0 - w * 0.05, top - h], S.lit(c, x0, 0, x0 + w, 0));
        for (let i = 1; i < 10; i++) P.line([x0 - w * 0.05 + w * 1.1 * i / 10, top - h, x0 - w * 0.08 + w * 1.15 * i / 10, top], S.u * 0.5, darken(c, 0.3), { a: 0.5 });
      };
      draw();
      if (S.waterY != null && y > S.waterY) P.mirror(y, 0.3, draw);
    },
    reeds(P, S, x, y, s) {
      P.mat = M.FOLIAGE;
      const r = rng(Math.round(x * 9 + y));
      for (let i = 0; i < 9; i++) {
        const bx = x + (r() - 0.5) * s * 0.5, h = s * (0.5 + r() * 0.5), lean = (r() - 0.5) * s * 0.2;
        P.line([bx, y, bx + lean * 0.4, y - h * 0.5, bx + lean, y - h], S.u * 0.6 + s * 0.012, mix(rgb(S.leaf[2]), [120, 140, 60], r()), { smooth: true });
        if (i % 3 === 0) P.ell(bx + lean * 0.9, y - h * 0.88, s * 0.025, s * 0.08, [110, 70, 40], { rot: lean / h, noOutline: true });
      }
    },
    // ---- still life
    table(P, S, x, y, s, o) {
      const items = (S.d.objects || []).filter((q) => TABLE_ITEMS.includes(q.type));
      if (items.length) { const xs = items.map((q) => q.x * S.W); x = (Math.min(...xs) + Math.max(...xs)) / 2; s = Math.max(s, (Math.max(...xs) - Math.min(...xs) + S.W * 0.2) / 2.6); }
      const c = o.color ? rgb(o.color) : S.col([150, 100, 60], 131), W = S.W, w = Math.max(W * 0.55, s * 2.6), x0 = clamp(x - w / 2, -W * 0.1, W * 1.1 - w), th = S.H * 0.035;
      P.mat = M.OBJ;
      const cloth = S.shade > 0.4 ? [240, 236, 226] : null;
      P.rect(x0 + w * 0.06, y + th, w * 0.04, S.H - y, darken(c, 0.3)); P.rect(x0 + w * 0.9, y + th, w * 0.04, S.H - y, darken(c, 0.3));
      P.poly([x0 + w * 0.04, y - th * 0.8, x0 + w * 0.96, y - th * 0.8, x0 + w, y + th * 0.4, x0, y + th * 0.4], S.lit(lighten(c, 0.1), x0, 0, x0 + w, 0));
      P.rect(x0, y + th * 0.4, w, th * 0.8, darken(c, 0.15));
      if (cloth) {   // a runner down the middle of the table
        const c0 = x0 + w * 0.36, c1 = x0 + w * 0.64;
        P.poly([c0 + w * 0.01, y - th * 0.8, c1 - w * 0.01, y - th * 0.8, c1, y + th * 0.4, c0, y + th * 0.4], S.lit(cloth, c0, 0, c1, 0), { a: 0.9 });
        P.line([c0, y + th * 0.3, c1, y + th * 0.3], S.u * 0.8, [190, 90, 80], { a: 0.5 });
      }
    },
    vase(P, S, x, y, s, o) {
      const c = o.color ? rgb(o.color) : S.col([70, 110, 170], 132), w = s * 0.2, h = s * 0.45;
      P.mat = M.OBJ;
      const r = rng(Math.round(x * 17));
      for (let i = 0; i < 6; i++) {   // flowers
        const a = -Math.PI / 2 + (i - 2.5) * 0.3, l = s * (0.45 + r() * 0.2), fx = x + Math.cos(a) * l, fy = y - h + Math.sin(a) * l;
        P.line([x, y - h * 0.9, fx, fy], S.u * 0.7, [70, 130, 60], { mat: M.FINE });
        const fc = [S.pal[5] || [240, 120, 160], [250, 220, 90], [255, 255, 255], [220, 90, 90]][i % 4];
        for (let k = 0; k < 5; k++) P.circ(fx + Math.cos(k * 1.26) * s * 0.035, fy + Math.sin(k * 1.26) * s * 0.035, s * 0.03, fc, { mat: M.FINE, noOutline: k > 0 });
        P.circ(fx, fy, s * 0.02, [250, 200, 60], { mat: M.FINE, noOutline: true });
      }
      P.poly([x - w * 0.35, y - h, x + w * 0.35, y - h, x + w * 0.3, y - h * 0.85, x + w, y - h * 0.4, x + w * 0.7, y, x - w * 0.7, y, x - w, y - h * 0.4, x - w * 0.3, y - h * 0.85], S.lit(c, x - w, 0, x + w, 0), { smooth: S.kid < 0.5 });
      if (S.shade > 0.5) P.ell(x - w * 0.45, y - h * 0.45, w * 0.1, h * 0.2, [255, 255, 255], { a: 0.5, noOutline: true });
    },
    teapot(P, S, x, y, s, o) {
      const c = o.color ? rgb(o.color) : S.col([60, 120, 140], 133), w = s * 0.3, h = s * 0.48, cy = y - h * 0.42;
      P.mat = M.OBJ;
      shadow(P, S, x, y, w * 1.2);
      // spout: a tapering curve out of the lower right
      P.poly([x + w * 0.75, cy + h * 0.12, x + w * 1.2, cy - h * 0.05, x + w * 1.45, cy - h * 0.45, x + w * 1.52, cy - h * 0.42, x + w * 1.32, cy - h * 0.02, x + w * 0.85, cy + h * 0.28], S.lit(c, x, 0, x + w * 1.5, 0), { smooth: true });
      P.ell(x - w * 0.95, cy - h * 0.02, w * 0.38, h * 0.27, c, { a0: Math.PI * 0.5, a1: Math.PI * 1.5, open: true, w: S.u + s * 0.045 });
      P.ell(x, cy, w, h * 0.42, S.lit(c, x - w, cy - h * 0.4, x + w, cy + h * 0.4));
      P.ell(x, cy + h * 0.4, w * 0.62, h * 0.05, darken(c, 0.25), { noOutline: true });
      P.ell(x, cy - h * 0.4, w * 0.55, h * 0.1, darken(c, 0.12));
      P.ell(x, cy - h * 0.47, w * 0.4, h * 0.08, S.lit(c, x - w * 0.4, 0, x + w * 0.4, 0), { a0: Math.PI, a1: TAU });
      P.circ(x, cy - h * 0.57, w * 0.1, darken(c, 0.2));
      if (S.shade > 0.4) P.ell(x - w * 0.42 * -S.lx * -1, cy - h * 0.16, w * 0.16, h * 0.08, [255, 255, 255], { a: 0.6, noOutline: true, rot: -0.5 });
      if (S.shade > 0.5 && S.weather !== "storm") P.line([x + w * 1.5, cy - h * 0.5, x + w * 1.35, cy - h * 0.9, x + w * 1.6, cy - h * 1.3], S.u * 2, [255, 255, 255], { a: 0.35, smooth: true, noOutline: true });
    },
    apple(P, S, x, y, s, o) {
      const c = o.color ? rgb(o.color) : S.col([210, 50, 40], 134), r = s * 0.18;
      P.mat = M.OBJ;
      shadow(P, S, x, y, r * 1.2);
      P.circ(x, y - r, r, S.lit(c, x - r, y - r * 2, x + r, y));
      P.line([x, y - r * 1.8, x + r * 0.1, y - r * 2.3], S.u * 0.8, [90, 60, 30]);
      P.ell(x + r * 0.35, y - r * 2.1, r * 0.3, r * 0.14, [80, 150, 60], { rot: -0.4 });
      if (S.shade > 0.4) P.circ(x - r * 0.4, y - r * 1.3, r * 0.15, [255, 255, 255], { a: 0.5, noOutline: true });
    },
    bread(P, S, x, y, s) {
      const c = [205, 150, 80], w = s * 0.42, h = s * 0.22;
      P.mat = M.OBJ;
      shadow(P, S, x, y, w);
      P.ell(x, y - h * 0.1, w, h * 1.05, S.lit(c, x - w, y - h, x + w, y), { a0: Math.PI, a1: TAU });
      P.rect(x - w, y - h * 0.12, w * 2, h * 0.12, darken(c, 0.2));
      for (let i = -1; i <= 1; i++) P.line([x + i * w * 0.4 - w * 0.12, y - h * 0.75, x + i * w * 0.4 + w * 0.12, y - h * 0.5], S.u * 1.1, lighten(c, 0.35));
    },
    candle(P, S, x, y, s) {
      const w = s * 0.07, h = s * 0.5;
      P.mat = M.OBJ;
      P.ell(x, y - S.u, w * 2.2, w * 0.6, [190, 170, 120]);
      P.rect(x - w, y - h, w * 2, h, S.lit([248, 240, 220], x - w, 0, x + w, 0));
      P.line([x, y - h, x, y - h - s * 0.05], S.u * 0.6, [40, 30, 20], { noOutline: true });
      P.glow(x, y - h - s * 0.12, s * 0.9, [255, 190, 90], 0.8);
      P.ell(x, y - h - s * 0.12, w * 0.7, s * 0.09, { g: "rad", x, y: y - h - s * 0.1, r0: 0, r1: s * 0.1, s: [[0, [255, 255, 220]], [1, [255, 170, 40]]] }, { mat: M.LIGHT, emit: true, noOutline: true });
    },
    window(P, S, x, y, s) {
      const ss = Math.max(s, 0.24 * S.H), w = ss * 0.85, h = ss, x0 = x - w / 2, y0 = y - h;
      P.mat = M.WALL;
      const top = rgb(S.d.sky?.top || "#7ab8e0"), bot = rgb(S.d.sky?.bottom || "#e8f4fa");
      P.rect(x0 - ss * 0.06, y0 - ss * 0.06, w + ss * 0.12, h + ss * 0.12, [235, 228, 214]);
      P.mat = M.SKY;
      P.rect(x0, y0, w, h, { g: "lin", x0: 0, y0, x1: 0, y1: y, s: [[0, top], [1, bot]] }, { emit: S.time !== "night" });
      // the view outside: a hill, and the moon or sun
      P.mat = M.HILL;
      P.poly([x0, y - h * 0.22, x0 + w * 0.4, y - h * 0.32, x0 + w, y - h * 0.18, x0 + w, y, x0, y], mix(rgb(S.leaf[2]), top, 0.35), { noOutline: true });
      P.mat = M.LIGHT;
      if (S.time === "night") { P.circ(x0 + w * 0.7, y0 + h * 0.25, ss * 0.06, [250, 248, 225], { emit: true, noOutline: true }); for (let i = 0; i < 5; i++) P.circ(x0 + w * hash(i, 1, S.seed), y0 + h * 0.5 * hash(i, 2, S.seed), S.u * 0.7, [255, 255, 230], { emit: true, noOutline: true }); }
      else if (S.time === "evening" || S.time === "dawn") P.circ(x0 + w * 0.3, y - h * 0.3, ss * 0.07, [255, 190, 110], { emit: true, noOutline: true });
      if (S.weather === "rain" || S.weather === "storm") for (let i = 0; i < 10; i++) { const rx = x0 + w * hash(i, 3, S.seed), ry = y0 + h * hash(i, 4, S.seed); P.line([rx, ry, rx, ry + ss * 0.06], S.u * 0.6, [220, 230, 255], { a: 0.7 }); }
      P.mat = M.WALL;
      const fr = [250, 246, 238];
      P.line([x0 + w / 2, y0, x0 + w / 2, y], S.u * 1.5 + ss * 0.02, fr);
      P.line([x0, y0 + h / 2, x0 + w, y0 + h / 2], S.u * 1.5 + ss * 0.02, fr);
      P.line([x0, y0, x0 + w, y0, x0 + w, y, x0, y, x0, y0], S.u * 1.5 + ss * 0.03, fr);
      P.rect(x0 - ss * 0.1, y, w + ss * 0.2, ss * 0.05, [230, 222, 206]);
      if (S.kid < 0.5) {   // curtains
        const cc = S.col([196, 90, 80], 141);
        P.poly([x0 - ss * 0.12, y0 - ss * 0.1, x0 + w * 0.18, y0 - ss * 0.1, x0 + w * 0.05, y0 + h * 0.5, x0 + w * 0.12, y + ss * 0.04, x0 - ss * 0.12, y + ss * 0.04], S.lit(cc, x0 - ss * 0.1, 0, x0 + w * 0.2, 0), { smooth: false });
        P.poly([x0 + w + ss * 0.12, y0 - ss * 0.1, x0 + w * 0.82, y0 - ss * 0.1, x0 + w * 0.95, y0 + h * 0.5, x0 + w * 0.88, y + ss * 0.04, x0 + w + ss * 0.12, y + ss * 0.04], S.lit(cc, x0 + w * 0.8, 0, x0 + w + ss * 0.1, 0));
      }
      if (S.time !== "night" && S.shade > 0.3) S.lightIn = [x, y - h / 2, ss * 2.5];
    },
    cup(P, S, x, y, s, o) {
      const c = o.color ? rgb(o.color) : S.col([240, 236, 226], 151), w = s * 0.16, h = s * 0.22;
      P.mat = M.OBJ;
      P.ell(x, y - S.u * 0.5, w * 1.8, h * 0.18, S.lit(c, x - w * 2, 0, x + w * 2, 0));
      P.ell(x + w * 1.05, y - h * 0.55, w * 0.38, h * 0.3, c, { open: true, w: S.u + s * 0.02, a0: -Math.PI / 2, a1: Math.PI / 2 });
      P.poly([x - w, y - h, x + w, y - h, x + w * 0.8, y - S.u, x - w * 0.8, y - S.u], S.lit(c, x - w, 0, x + w, 0));
      P.ell(x, y - h, w, h * 0.15, [130, 80, 40]);
      if (S.shade > 0.4) P.line([x, y - h * 1.2, x - w * 0.4, y - h * 1.8, x + w * 0.2, y - h * 2.5], S.u * 1.6, [255, 255, 255], { a: 0.35, smooth: true, noOutline: true });
    },
    book(P, S, x, y, s, o) {
      const c = o.color ? rgb(o.color) : S.col([150, 60, 60], 152), w = s * 0.42, h = s * 0.1;
      P.mat = M.OBJ;
      P.poly([x - w, y, x + w * 0.8, y, x + w, y - h, x - w * 0.8, y - h], [245, 238, 220]);
      P.poly([x - w * 0.85, y - h, x + w, y - h, x + w * 0.95, y - h * 2, x - w * 0.9, y - h * 2], S.lit(c, x - w, 0, x + w, 0));
      P.line([x - w * 0.5, y - h * 1.5, x + w * 0.4, y - h * 1.5], S.u * 0.6, [230, 200, 120], { a: 0.8 });
    },
  };
  function shadow(P, S, x, y, w) {
    if (S.shade < 0.2 || S.indoor && y < S.hor) return;
    const m = P.mat, dx = -S.lx * w * 0.3;
    P.mat = M.GROUND;
    P.ell(x + dx, y, w * 1.1, w * 0.22, [20, 30, 40], { a: 0.22 * S.shade * (S.time === "night" ? 0.4 : 1), wob: 0.3, noOutline: true, soft: true });
    P.mat = m;
  }
  function leafCanopy(P, S, x, cy, s, leaf, dark, r, n) {
    const R = s * 0.32;
    P.circ(x, cy, R * 1.05, S.lit(mix(leaf, dark, 0.35), x - R, cy - R, x + R, cy + R), { smooth: true });
    for (let i = 0; i < n; i++) {
      const a = r() * TAU, d = R * (0.35 + r() * 0.45), bx = x + Math.cos(a) * d, by = cy + Math.sin(a) * d * 0.8, br = R * (0.45 + r() * 0.25);
      const towardLight = (bx - x) * -S.lx < 0 ? 1 : 0, up = by < cy ? 1 : 0;
      const c = mix(leaf, towardLight + up > 0 ? lighten(leaf, 0.25 * S.shade) : dark, towardLight + up > 0 ? 0.3 : 0.25 * S.shade);
      P.circ(bx, by, br, S.lit(c, bx - br, by - br, bx + br, by + br, 0.7), { smooth: true, noOutline: true });
    }
  }
  function blossomMix(leaf) { return mix(leaf, [246, 190, 210], 0.5); }
  function winCross(P, S, x, y, w, h) {
    const lit = S.night > 0.2;
    P.rect(x, y, w, h, lit ? [255, 214, 120] : [150, 200, 240], { mat: M.LIGHT, emit: lit });
    P.line([x + w / 2, y, x + w / 2, y + h], S.u * 1.2, [60, 50, 50]); P.line([x, y + h / 2, x + w, y + h / 2], S.u * 1.2, [60, 50, 50]);
  }
  function winLit(P, S, x, y, w, h) {
    const lit = S.night > 0.2 || S.weather === "storm";
    if (lit) P.glow(x + w / 2, y + h / 2, w * 2.2, [255, 190, 100], 0.55);
    P.rect(x, y, w, h, lit ? { g: "lin", x0: 0, y0: y, x1: 0, y1: y + h, s: [[0, [255, 226, 150]], [1, [250, 170, 80]]] } : { g: "lin", x0: x, y0: y, x1: x + w, y1: y + h, s: [[0, [190, 220, 240]], [1, [80, 100, 130]]] }, { mat: M.LIGHT, emit: lit, wob: 0.3 });
    P.line([x + w / 2, y, x + w / 2, y + h], S.u * 0.6 + w * 0.06, [245, 240, 230], { wob: 0.2 });
    P.line([x, y + h / 2, x + w, y + h / 2], S.u * 0.6 + w * 0.06, [245, 240, 230], { wob: 0.2 });
  }

  function drawObjects(P, S) {
    const { W, H, d } = S, objs = d.objects || [];
    // a child draws things at whatever size feels important; skill draws them in proportion
    const tableItems = objs.filter((o) => TABLE_ITEMS.includes(o.type));
    if (S.indoor && tableItems.length && !objs.some((o) => o.type === "table")) OBJ.table(P, S, W * 0.5, H * 0.72, H * 0.2, {});
    const ordered = objs.slice().sort((a, b) => (a.type === "table" ? -1 : b.type === "table" ? 1 : 0) || (OBJ_ORDER[a.type] ?? 1) - (OBJ_ORDER[b.type] ?? 1) || a.y - b.y);
    for (const o of ordered) {
      const f = OBJ[o.type]; if (!f) continue;
      let s = (+o.size || 0.1) * H;
      if (S.kid > 0.5) s *= 1 + (hash(Math.round(o.x * 100), 3, S.seed) - 0.3) * 0.5 * S.kid;
      let x = (+o.x || 0.5) * W, y = (+o.y || 0.7) * H;
      P.grp++;
      if (S.skyBand && OBJ_ORDER[o.type] === 0 && o.type !== "rainbow") y = Math.min(y, S.skyBand * 0.75);
      // ground things that would stand in open water get a little island under them
      if (S.waterY != null && y > S.waterY + H * 0.01 && ["tree", "pine", "apple tree", "house", "barn", "figure", "deer", "hen", "cat", "scarecrow", "bench", "lamp", "fence", "flower", "sunflower", "pumpkin", "mushroom", "snowman", "beehive", "greenhouse"].includes(o.type)) {
        P.mat = M.GROUND;
        const iw = s * (["house", "barn", "greenhouse", "fence"].includes(o.type) ? 1.0 : 0.55);
        P.ell(x, y, iw, s * 0.08, S.season === "winter" ? [236, 242, 247] : rgb(S.leaf[1]), { a0: Math.PI, a1: TAU });
        P.ell(x, y, iw, s * 0.05, darken(rgb(S.leaf[2]), 0.1), { a0: 0, a1: Math.PI, noOutline: true });
      }
      P.mat = M.OBJ;
      f(P, S, x, y, s, o);
    }
    P.grp = 0;
  }
  const TABLE_ITEMS = ["vase", "teapot", "apple", "bread", "candle", "cup", "book"];
  const OBJ_ORDER = { sun: 0, moon: 0, star: 0, cloud: 0, rainbow: 0, window: 0, bird: 2, kite: 2, butterfly: 2, bee: 2, fireflies: 2 };

  // ------------------------------------------------------------------ weather
  function drawWeather(P, S) {
    const { W, H } = S, r = rng(S.seed ^ 0x3ea7), wx = S.weather;
    if (S.indoor) return;
    if (wx === "rain" || wx === "storm") {
      const n = Math.round((wx === "storm" ? 220 : 140) * W * H / 120000 * (S.kid > 0.5 ? 0.25 : 1)), slant = wx === "storm" ? 0.35 : 0.12;
      for (let i = 0; i < n; i++) {
        const x = r() * W * 1.1, y = r() * H, l = S.u * (S.kid > 0.5 ? 8 : 6 + r() * 10);
        P.line([x, y, x - l * slant, y + l], S.u * (S.kid > 0.5 ? 1.8 : 0.6), S.kid > 0.5 ? [60, 120, 230] : [215, 225, 240], { a: S.kid > 0.5 ? 0.9 : 0.25 + r() * 0.3, mat: M.RAIN, wob: 0.1, noOutline: true });
      }
      if (wx === "storm" && S.shade > 0.5) {   // a lightning fork
        const p = []; let x = W * (0.25 + r() * 0.5), y = 0;
        while (y < S.hor * 0.9) { p.push(x, y); x += (r() - 0.5) * W * 0.06; y += H * (0.04 + r() * 0.05); }
        P.glow(p[p.length - 2], p[p.length - 1], W * 0.15, [200, 210, 255], 0.4);
        P.line(p, S.u * 1.6, [250, 250, 255], { mat: M.LIGHT, emit: true, wob: 0.1 });
      }
    } else if (wx === "snow") {
      const n = Math.round(160 * W * H / 120000 * (S.kid > 0.5 ? 0.35 : 1));
      for (let i = 0; i < n; i++) {
        const x = r() * W, y = r() * H, s = S.u * (S.kid > 0.5 ? 2.2 : 0.6 + r() * 1.6);
        P.circ(x, y, s, [255, 255, 255], { a: 0.85, mat: M.FINE, wob: 0.1, noOutline: true });
      }
    } else if (wx === "windy") {
      const n = 14, cols = [S.leaf[0], S.leaf[1], "#e0a050"].map(rgb);
      for (let i = 0; i < n; i++) {
        const x = r() * W, y = r() * H * 0.8;
        P.ell(x, y, S.u * 2.2, S.u * 1.1, cols[i % 3], { rot: r() * 3, mat: M.FINE });
        if (i % 3 === 0) P.line([x - W * 0.12, y + S.u * 4, x - W * 0.05, y - S.u * 2, x - S.u * 3, y + S.u * 3], S.u * 0.7, [255, 255, 255], { a: 0.5, smooth: true, noOutline: true });
      }
    }
  }

  // ------------------------------------------------------------------ light, mood and air (applied after the marks)
  function grade(g, S) {
    const { W, H } = S, t = S.time, k = 0.4 + 0.6 * S.shade;
    g.save();
    const fill = (op, style, a) => { g.globalCompositeOperation = op; g.globalAlpha = a; g.fillStyle = style; g.fillRect(0, 0, W, H); };
    const vg = (c0, c1) => { const gr = g.createLinearGradient(0, 0, 0, H); gr.addColorStop(0, c0); gr.addColorStop(1, c1); return gr; };
    if (t === "night") { fill("multiply", vg("rgb(70,84,160)", "rgb(128,134,192)"), S.kid > 0.5 ? 0.45 : 0.58); fill("soft-light", "rgb(90,120,220)", 0.3); }
    else if (t === "evening") { fill("multiply", vg("rgb(170,150,210)", "rgb(255,190,140)"), 0.45 * k); fill("soft-light", vg("rgb(120,90,180)", "rgb(255,150,70)"), 0.45 * k); }
    else if (t === "dawn") fill("soft-light", vg("rgb(255,170,170)", "rgb(255,210,150)"), 0.5 * k);
    else if (t === "afternoon") fill("soft-light", "rgb(255,214,150)", 0.25 * k);
    else if (t === "morning") fill("soft-light", "rgb(200,225,255)", 0.2 * k);
    const mt = MOOD_TINT[S.mood];
    if (mt) fill("soft-light", mt, 0.22 * k);
    if (S.weather === "rain" || S.weather === "storm") fill("multiply", "rgb(150,160,180)", S.weather === "storm" ? 0.6 : 0.35);
    if (S.weather === "fog" && !S.indoor) {
      g.globalCompositeOperation = "source-over"; g.globalAlpha = 1;
      const gr = g.createLinearGradient(0, 0, 0, H);
      gr.addColorStop(0, "rgba(230,232,236,.35)"); gr.addColorStop(clamp(S.hor / H, 0.1, 0.9), "rgba(235,237,240,.75)"); gr.addColorStop(1, "rgba(230,232,236,.25)");
      g.fillStyle = gr; g.fillRect(0, 0, W, H);
    }
    if (S.indoor && S.lightIn) {   // the window's light falling into the room
      g.globalCompositeOperation = "soft-light"; g.globalAlpha = 0.5 * S.shade;
      const [x, y, r] = S.lightIn, gr = g.createRadialGradient(x, y, 0, x, y, r);
      gr.addColorStop(0, "rgba(255,240,200,1)"); gr.addColorStop(1, "rgba(255,240,200,0)"); g.fillStyle = gr; g.fillRect(0, 0, W, H);
    }
    g.restore();
  }
  function vignette(g, S, amt) {
    if (amt <= 0) return;
    const { W, H } = S, gr = g.createRadialGradient(W / 2, H * 0.48, Math.min(W, H) * 0.35, W / 2, H / 2, Math.hypot(W, H) * 0.6);
    gr.addColorStop(0, "rgba(0,0,0,0)"); gr.addColorStop(1, `rgba(20,14,30,${amt})`);
    g.save(); g.globalCompositeOperation = "multiply"; g.fillStyle = gr; g.fillRect(0, 0, W, H); g.restore();
  }

  // ================================================================== rendering marks
  function setFill(g, f, a = 1) {
    if (Array.isArray(f)) { g.fillStyle = css(f); g.globalAlpha = a * (f.length > 3 ? f[3] : 1); return; }
    g.globalAlpha = a;
    let gr;
    if (f.g === "lin") gr = g.createLinearGradient(f.x0, f.y0, f.x1, f.y1);
    else gr = g.createRadialGradient(f.x, f.y, f.r0 || 0, f.x, f.y, f.r1);
    for (const [o, c] of f.s) gr.addColorStop(clamp(o, 0, 1), css(c, c.length > 3 ? c[3] : 1));
    g.fillStyle = gr;
  }
  const midColor = (f) => (Array.isArray(f) ? f : f.s[Math.floor(f.s.length / 2)][1]);
  function tracePath(g, p, closed, smoothIt) {
    g.beginPath();
    const n = p.length / 2;
    if (n < 2) return;
    if (smoothIt && n > 3) {
      if (closed) {
        g.moveTo((p[0] + p[2]) / 2, (p[1] + p[3]) / 2);
        for (let i = 1; i <= n; i++) { const a = i % n, b = (i + 1) % n; g.quadraticCurveTo(p[a * 2], p[a * 2 + 1], (p[a * 2] + p[b * 2]) / 2, (p[a * 2 + 1] + p[b * 2 + 1]) / 2); }
      } else {
        g.moveTo(p[0], p[1]);
        for (let i = 1; i < n - 1; i++) g.quadraticCurveTo(p[i * 2], p[i * 2 + 1], (p[i * 2] + p[i * 2 + 2]) / 2, (p[i * 2 + 1] + p[i * 2 + 3]) / 2);
        g.lineTo(p[p.length - 2], p[p.length - 1]);
      }
    } else {
      g.moveTo(p[0], p[1]);
      for (let i = 2; i < p.length; i += 2) g.lineTo(p[i], p[i + 1]);
    }
    if (closed) g.closePath();
  }
  function drawGlow(g, m, S, k = 1) {
    const gr = g.createRadialGradient(m.x, m.y, 0, m.x, m.y, m.r);
    gr.addColorStop(0, css(m.c, 1)); gr.addColorStop(0.3, css(m.c, 0.45)); gr.addColorStop(1, css(m.c, 0));
    g.save(); g.globalCompositeOperation = "screen"; g.globalAlpha = clamp(m.a * k, 0, 1); g.fillStyle = gr;
    g.fillRect(m.x - m.r, m.y - m.r, m.r * 2, m.r * 2); g.restore();
  }
  // the plain render: exact fills (the base for the brush styles, and for naive)
  function renderClean(g, marks, S, opt = {}) {
    for (const m of marks) {
      if (!!m.emit !== !!opt.emit) continue;
      if (m.t === "glow") { drawGlow(g, m, S); continue; }
      if (m.t === "fn") { m.f(g, { alpha: 1 }); continue; }
      if (opt.idMap) { g.globalAlpha = 1; g.fillStyle = g.strokeStyle = `rgb(${m.mat * 16},0,0)`; }
      else if (m.t === "line") { g.strokeStyle = css(midColor(m.fill)); g.globalAlpha = m.a; }
      else setFill(g, m.fill, m.a);
      if (m.t === "line") {
        if (opt.idMap && m.a < 0.4) continue;
        g.lineWidth = m.w || S.u; g.lineCap = "round"; g.lineJoin = "round";
        tracePath(g, m.p, false, m.smooth); g.stroke();
      } else {
        if (opt.idMap && m.a < 0.5) continue;
        tracePath(g, m.p, true, m.smooth); g.fill();
      }
    }
    g.globalAlpha = 1;
  }

  // ---- naive: flat colour, outlines; a child's crayon at first
  function renderNaive(g, marks, S, opt = {}) {
    const r = rng(S.seed ^ 0x1a1e), kid = S.kid, ink = [42, 36, 34];
    for (const m of marks) {
      if (!!m.emit !== !!opt.emit) continue;
      if (m.t === "glow") { if (kid < 0.5) drawGlow(g, m, S, 0.7); continue; }
      if (m.t === "fn") { m.f(g, { alpha: 0.6 }); continue; }
      const flat = kid > 0.3 || m.mat !== M.SKY ? midColor(m.fill) : null;
      if (m.t === "line") {
        g.strokeStyle = css(midColor(m.fill)); g.globalAlpha = m.a; g.lineWidth = (m.w || S.u) * (1 + kid * 0.4); g.lineCap = "round"; g.lineJoin = "round";
        tracePath(g, m.p, false, m.smooth); g.stroke(); continue;
      }
      // fill: crayon scribble for a child; flat colour for a folk painter
      if (kid > 0.25 && m.p.length > 6) {
        const c = flat || midColor(m.fill);
        g.save(); tracePath(g, m.p, true, m.smooth); g.clip();
        setFill(g, c, m.a * (1 - kid * 0.55));
        g.fill();
        let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
        for (let i = 0; i < m.p.length; i += 2) { x0 = Math.min(x0, m.p[i]); x1 = Math.max(x1, m.p[i]); y0 = Math.min(y0, m.p[i + 1]); y1 = Math.max(y1, m.p[i + 1]); }
        const ang = (r() - 0.5) * 1.2 + (m.mat === M.SKY ? 0 : 0.6), ca = Math.cos(ang), sa = Math.sin(ang), step = S.u * (1.6 + kid * 0.6);
        const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2, R = Math.hypot(x1 - x0, y1 - y0) / 2 + step;
        g.strokeStyle = css(c); g.globalAlpha = m.a * 0.85; g.lineWidth = S.u * (2.2 + kid); g.lineCap = "round"; g.lineJoin = "round";
        g.beginPath();
        let flip = 1;
        for (let t = -R; t < R; t += step) {
          if (r() < 0.025 * kid) { flip = -flip; continue; }     // gaps where the crayon skipped
          const ax = cx + ca * t - sa * R * flip, ay = cy + sa * t + ca * R * flip;
          const bx = cx + ca * (t + step * 0.5) + sa * R * flip, by = cy + sa * (t + step * 0.5) - ca * R * flip;
          g.moveTo(ax, ay); g.lineTo(bx, by); flip = -flip;
        }
        g.stroke(); g.restore();
      } else {
        setFill(g, flat || m.fill, m.a); tracePath(g, m.p, true, m.smooth); g.fill();
        if (kid < 0.25 && m.p.length > 8 && S.skill > 0.5 && m.mat === M.OBJ && hash(m.seed, 1, 1) < 0.3) {   // folk art: a little pattern
          g.save(); tracePath(g, m.p, true, m.smooth); g.clip();
          g.fillStyle = css(lighten(midColor(m.fill), 0.35)); g.globalAlpha = 0.5;
          let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
          for (let i = 0; i < m.p.length; i += 2) { x0 = Math.min(x0, m.p[i]); x1 = Math.max(x1, m.p[i]); y0 = Math.min(y0, m.p[i + 1]); y1 = Math.max(y1, m.p[i + 1]); }
          const st = S.u * 5;
          for (let y = y0; y < y1; y += st) for (let x = x0 + ((y / st) % 2) * st / 2; x < x1; x += st) { g.beginPath(); g.arc(x, y, S.u * 0.8, 0, TAU); g.fill(); }
          g.restore();
        }
      }
      // the outline
      if (!m.noOutline && m.a > 0.5 && m.mat !== M.SKY) {
        const pts = m.edge || m.p, closed = !m.edge;
        if (pts && pts.length >= 4) {
          const off = kid * S.u * 2.2;   // a child's outline doesn't quite meet the colour
          g.save(); g.translate((hash(m.seed, 5, 1) - 0.5) * off, (hash(m.seed, 6, 1) - 0.5) * off);
          g.strokeStyle = css(m.line ? rgb(m.line) : kid > 0.5 ? ink : darken(midColor(m.fill), 0.55)); g.globalAlpha = kid > 0.5 ? 0.9 : 0.75;
          g.lineWidth = S.u * (kid > 0.5 ? 1.8 : S.skill > 0.6 ? 0.7 : 1.1); g.lineJoin = "round"; g.lineCap = "round";
          tracePath(g, pts, closed, m.smooth); g.stroke(); g.restore();
        }
      }
    }
    g.globalAlpha = 1;
  }

  // ---- watercolor: layered translucent washes with soft, bleeding edges
  function deform(p, amt, depth, r) {
    let pts = p;
    for (let d = 0; d < depth; d++) {
      const out = [], n = pts.length / 2;
      for (let i = 0; i < n; i++) {
        const ax = pts[i * 2], ay = pts[i * 2 + 1], j = (i + 1) % n, bx = pts[j * 2], by = pts[j * 2 + 1];
        const len = Math.hypot(bx - ax, by - ay), g = (r() + r() + r() - 1.5) * len * amt;
        out.push(ax, ay, (ax + bx) / 2 + (-(by - ay) / (len || 1)) * g, (ay + by) / 2 + ((bx - ax) / (len || 1)) * g);
      }
      pts = out;
    }
    return pts;
  }
  function decimate(p, maxPts) { if (p.length / 2 <= maxPts) return p; const k = Math.ceil(p.length / 2 / maxPts), o = []; for (let i = 0; i < p.length; i += 2 * k) o.push(p[i], p[i + 1]); return o; }
  function bbox(p) { let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity; for (let i = 0; i < p.length; i += 2) { x0 = Math.min(x0, p[i]); x1 = Math.max(x1, p[i]); y0 = Math.min(y0, p[i + 1]); y1 = Math.max(y1, p[i + 1]); } return [x0, y0, x1, y1]; }
  function renderWatercolor(g0, marks, S, opt = {}) {
    const r = rng(S.seed ^ 0x3a7e), loose = 0.35 + (1 - S.skill) * 0.9;
    // each object is washed on its own sheet first, then laid down whole, so its overlapping parts don't pile up into mud
    const tmp = ctx2d(mkCanvas(S.W, S.H));
    let g = g0, cur = 0;
    const flush = () => { if (g !== g0) { g0.save(); g0.globalAlpha = 0.95; g0.drawImage(tmp.canvas, 0, 0); g0.restore(); g = g0; } cur = 0; };
    g0.lineJoin = "round"; g0.lineCap = "round";
    for (const m of marks) {
      if (!!m.emit !== !!opt.emit) continue;
      if (m.t === "glow" || m.t === "fn" || !m.grp) flush();
      else if (m.grp !== cur) { flush(); cur = m.grp; tmp.clearRect(0, 0, S.W, S.H); g = tmp; g.lineJoin = "round"; g.lineCap = "round"; }
      if (m.t === "glow") { drawGlow(g, m, S, 0.8); continue; }
      if (m.t === "fn") { m.f(g, { alpha: 0.75 }); continue; }
      const c = midColor(m.fill);
      if (m.t === "line") {
        g.save(); g.globalCompositeOperation = g === g0 ? "multiply" : "source-over";
        g.strokeStyle = css(c); g.lineWidth = (m.w || S.u) * 1.1;
        for (let k = 0; k < 2; k++) { g.globalAlpha = m.a * 0.5; tracePath(g, wobble(m.p, S.u * 0.8, m.seed + k, 0.1 / S.u), false, m.smooth); g.stroke(); }
        g.restore(); continue;
      }
      const [x0, y0, x1, y1] = bbox(m.p), size = Math.max(x1 - x0, y1 - y0), big = size > S.W * 0.25, light = lum(c) > 0.86;
      const layers = big ? 7 : size > S.u * 18 ? 4 : 2;
      const base = decimate(m.p, big ? 60 : 24);
      g.save();
      // white things are left as paper, lifted with a soft white wash
      const lift = (light || m.mat === M.CLOUD || m.mat === M.SNOW) && m.mat !== M.LIGHT;
      g.globalCompositeOperation = lift || opt.emit || g !== g0 ? "source-over" : "multiply";
      const fillC = light ? c : c;
      for (let k = 0; k < layers; k++) {
        const pts = deform(base, 0.12 * loose * (big ? 0.6 : 1), big ? 3 : 2, r);
        setFill(g, Array.isArray(m.fill) ? fillC : m.fill, m.a * (lift ? (big ? 0.3 : 0.45) : big ? 0.16 : 0.3) * (1 + S.kid * 0.4));
        tracePath(g, pts, true, true); g.fill();
      }
      // the pigment gathers at the edge as it dries
      if (!lift && size > S.u * 6) {
        g.globalAlpha = m.a * 0.22; g.strokeStyle = css(darken(c, 0.25)); g.lineWidth = S.u * (0.6 + S.kid);
        tracePath(g, deform(base, 0.05 * loose, 2, r), true, true); g.stroke();
      }
      g.restore();
      // a child's colour runs over the line; a bloom where water went back into the wash
      if (S.kid > 0.2 && size > S.u * 10 && r() < 0.5 * S.kid) {
        g.save(); g.globalCompositeOperation = "multiply"; g.globalAlpha = 0.18;
        const bx = x0 + r() * (x1 - x0), by = y0 + r() * (y1 - y0), br = size * (0.15 + r() * 0.2);
        setFill(g, c, 0.18); tracePath(g, deform(circlePts(bx, by, br, 12), 0.3, 3, r), true, true); g.fill(); g.restore();
      }
    }
    flush();
    g0.globalAlpha = 1;
  }
  function circlePts(x, y, rad, n) { const p = []; for (let i = 0; i < n; i++) { const a = i / n * TAU; p.push(x + Math.cos(a) * rad, y + Math.sin(a) * rad); } return p; }

  // ---- ink: brush line and pale washes
  function renderInk(g, marks, S, opt = {}) {
    const r = rng(S.seed ^ 0x14c), inkC = [28, 26, 30];
    for (const m of marks) {
      if (!!m.emit !== !!opt.emit) continue;
      if (m.t === "glow") { drawGlow(g, m, S, 0.5); continue; }
      if (m.t === "fn") { m.f(g, { alpha: 0.4 }); continue; }
      const c = midColor(m.fill), hsl = toHsl(c), wash = fromHsl(hsl[0], hsl[1] * 0.55, lerp(hsl[2], 0.92, 0.25));
      if (m.t === "line") {
        g.save(); g.globalCompositeOperation = "multiply"; g.strokeStyle = css(lum(c) > 0.8 ? wash : mix(c, inkC, 0.5)); g.globalAlpha = m.a * 0.8;
        g.lineWidth = (m.w || S.u) * 0.9; g.lineCap = "round"; tracePath(g, m.p, false, m.smooth); g.stroke(); g.restore(); continue;
      }
      // the wash
      g.save(); g.globalCompositeOperation = "multiply";
      const big = m.mat === M.SKY || m.mat === M.WATER || m.mat === M.MOUNT || m.mat === M.HILL;
      if (m.mat === M.CLOUD) {
        g.globalCompositeOperation = "source-over"; setFill(g, lighten(wash, 0.35), 1); tracePath(g, m.p, true, true); g.fill();
      } else if (m.mat === M.MOUNT || m.mat === M.HILL) {   // sumi-e: an ink wash fading downward
        const [x0, y0, x1, y1] = bbox(m.p);
        const gr = g.createLinearGradient(0, y0, 0, Math.min(S.H, y0 + (y1 - y0) * 0.6));
        gr.addColorStop(0, css(mix(wash, [90, 96, 110], 0.55), 0.8)); gr.addColorStop(1, css(wash, 0.1));
        g.fillStyle = gr; g.globalAlpha = m.a; tracePath(g, m.p, true, m.smooth); g.fill();
      } else {
        setFill(g, Array.isArray(m.fill) ? wash : m.fill, m.a * (big ? 0.5 : 0.7));
        tracePath(g, deform(decimate(m.p, 40), 0.03, 1, r), true, m.smooth); g.fill();
      }
      g.restore();
      // the line: a brush that swells and thins, and runs dry
      if (!m.noOutline && m.a > 0.45 && m.mat !== M.SKY) {
        const pts = m.edge || m.p, closed = !m.edge;
        if (!pts || pts.length < 4) continue;
        const q = densify(pts, closed, S.u * 3), n = q.length / 2, base = S.u * (m.mat === M.FINE ? 0.5 : S.skill > 0.6 ? 0.9 : 1.2);
        g.save(); g.strokeStyle = css(inkC); g.lineCap = "round";
        const ph = r() * 6;
        for (let i = 0; i < n - (closed ? 0 : 1); i++) {
          const j = (i + 1) % n;
          const press = 0.5 + 0.5 * Math.sin(i * 0.25 + ph) + (r() - 0.5) * 0.3 * (1 - S.skill);
          if (r() < 0.04 * (1 - S.skill * 0.5)) continue;
          g.globalAlpha = 0.65 + 0.3 * press; g.lineWidth = base * (0.5 + press);
          g.beginPath(); g.moveTo(q[i * 2], q[i * 2 + 1]); g.lineTo(q[j * 2], q[j * 2 + 1]); g.stroke();
        }
        g.restore();
      }
    }
    g.globalAlpha = 1;
  }
  function hatch(g, S, img) {   // cross-hatching where the clean render is dark
    const { W, H } = S, st = Math.max(2, S.u * 3.2), d = img.data, r = rng(S.seed ^ 0x4a7c);
    g.save(); g.strokeStyle = "rgb(30,28,34)"; g.lineCap = "round";
    for (let y = 0; y < H; y += st) for (let x = 0; x < W; x += st) {
      const o = ((Math.min(H - 1, y | 0) * W) + Math.min(W - 1, x | 0)) * 4, L = (0.299 * d[o] + 0.587 * d[o + 1] + 0.114 * d[o + 2]) / 255;
      if (L > 0.45) continue;
      const k = (0.45 - L) / 0.45, l = st * 1.3;
      g.globalAlpha = 0.25 + 0.35 * k; g.lineWidth = S.u * 0.45;
      g.beginPath(); g.moveTo(x - l / 2 + r(), y + l / 2); g.lineTo(x + l / 2, y - l / 2 + r()); g.stroke();
      if (k > 0.5) { g.beginPath(); g.moveTo(x - l / 2, y - l / 2); g.lineTo(x + l / 2, y + l / 2); g.stroke(); }
    }
    g.restore();
  }

  // ---- brush styles: dabs sampled from the clean render
  function brushStyle(g, S, clean, ids, style) {
    const { W, H, u, skill } = S, r = rng(S.seed ^ 0xb2a5), d = clean.data, id = ids.data;
    const px = (x, y) => { const o = ((clamp(y | 0, 0, H - 1) * W) + clamp(x | 0, 0, W - 1)) * 4; return [d[o], d[o + 1], d[o + 2]]; };
    const matAt = (x, y) => Math.round(id[((clamp(y | 0, 0, H - 1) * W) + clamp(x | 0, 0, W - 1)) * 4] / 16);
    const lumAt = (x, y) => { const o = ((clamp(y | 0, 0, H - 1) * W) + clamp(x | 0, 0, W - 1)) * 4; return 0.299 * d[o] + 0.587 * d[o + 1] + 0.114 * d[o + 2]; };
    const sloppy = 1 - skill;
    const dirOf = (x, y, mat, R) => {
      // follow edges where there are edges; otherwise each material has its own grain
      const gx = lumAt(x + R, y) - lumAt(x - R, y), gy = lumAt(x, y + R) - lumAt(x, y - R), mag = Math.hypot(gx, gy);
      if (mag > 30 && mat !== M.WATER) return Math.atan2(gy, gx) + Math.PI / 2;
      switch (mat) {
        case M.SKY: return (vnoise(x / (40 * u), y / (30 * u), S.seed) - 0.5) * 1.4;
        case M.CLOUD: return (vnoise(x / (15 * u), y / (15 * u), 3) - 0.5) * 3;
        case M.WATER: return (r() - 0.5) * 0.15;
        case M.MOUNT: return (r() < 0.5 ? -0.9 : 0.9) + (r() - 0.5) * 0.4;
        case M.HILL: case M.GROUND: case M.FLOOR: case M.SNOW: return (r() - 0.5) * 0.5;
        case M.FOLIAGE: return r() * Math.PI;
        case M.WALL: return (vnoise(x / (25 * u), y / (25 * u), 9) - 0.5) * 2.4;
        case M.RAIN: return Math.PI / 2 - 0.2;
        default: return r() * Math.PI;
      }
    };
    const jitter = (c, amt, lumv) => {
      const h = toHsl(c);
      let hue = h[0] + (r() - 0.5) * 30 * amt, sat = h[1] * (style === "oil" ? 1.12 : 1.18) + (r() - 0.5) * 0.12 * amt, l = h[2] + (r() - 0.5) * 0.1 * amt;
      if (style === "impressionist" || style === "pointillist") {   // broken colour: warm lights, violet shadows
        if (lumv < 0.35 && r() < 0.35) { hue = lerp(hue, 250, 0.35); sat += 0.1; }
        else if (lumv > 0.7 && r() < 0.3) { hue = lerp(hue, 45, 0.3); }
      }
      return fromHsl(hue, sat, l);
    };
    g.lineCap = "round"; g.lineJoin = "round";
    // the ground: toned for oil and pastel, white for pointillism, a thin wash of the scene for impressionism
    if (style === "oil") { g.fillStyle = "#6e5236"; g.fillRect(0, 0, W, H); g.globalAlpha = 0.55; g.putImageData(clean, 0, 0); g.globalAlpha = 1; }
    else if (style === "pastel") { g.fillStyle = S.time === "night" ? "#4a5068" : "#d8cbb3"; g.fillRect(0, 0, W, H); }
    else if (style === "pointillist") { g.fillStyle = "#f6f1e6"; g.fillRect(0, 0, W, H); }
    else {
      g.fillStyle = "#efe6d6"; g.fillRect(0, 0, W, H);
      const t = mkCanvas(W, H); ctx2d(t).putImageData(clean, 0, 0);
      g.globalAlpha = 0.75; g.drawImage(t, 0, 0); g.globalAlpha = 1;
    }
    if (style === "oil") { const t = mkCanvas(W, H); ctx2d(t).putImageData(clean, 0, 0); g.globalAlpha = 0.7; g.drawImage(t, 0, 0); g.globalAlpha = 1; }

    const passes = style === "pointillist"
      ? [{ R: 2.2, gap: 2.0, all: true }, { R: 1.6, gap: 1.7, all: true }].concat(skill > 0.5 ? [{ R: 1.0, gap: 1.2, fine: true }] : [])
      : style === "oil" ? [{ R: 5.5, gap: 4.5, all: true }, { R: 3.2, gap: 2.8, all: true }].concat([{ R: 1.8, gap: 1.6, fine: true }])
        : style === "pastel" ? [{ R: 1.4, gap: 2.4, all: true }, { R: 1.1, gap: 2.0, all: true }].concat(skill > 0.4 ? [{ R: 0.8, gap: 1.6, fine: true }] : [])
          : [{ R: 3.6, gap: 3.4, all: true }, { R: 2.4, gap: 2.4, all: true }].concat([{ R: 1.4, gap: 1.6, fine: true }]);
    const sizeK = 1 + sloppy * 0.35;
    for (const pass of passes) {
      const R = pass.R * u * sizeK, gap = pass.gap * u * sizeK, pts = [];
      for (let y = gap / 2; y < H; y += gap) for (let x = gap / 2; x < W; x += gap) pts.push(x + (r() - 0.5) * gap, y + (r() - 0.5) * gap);
      // shuffle so strokes interleave
      for (let i = pts.length / 2 - 1; i > 0; i--) { const j = Math.floor(r() * (i + 1)); [pts[i * 2], pts[j * 2]] = [pts[j * 2], pts[i * 2]]; [pts[i * 2 + 1], pts[j * 2 + 1]] = [pts[j * 2 + 1], pts[i * 2 + 1]]; }
      for (let i = 0; i < pts.length; i += 2) {
        const x = pts[i], y = pts[i + 1], mat = matAt(x, y);
        if (pass.fine) {   // detail only where there is detail
          const e = Math.abs(lumAt(x + R, y) - lumAt(x - R, y)) + Math.abs(lumAt(x, y + R) - lumAt(x, y - R));
          if (e < 22 && mat !== M.OBJ && mat !== M.FINE && mat !== M.LIGHT) continue;
        }
        let c = px(x, y);
        const L = lum(c);
        c = jitter(c, mat === M.WALL ? 0.12 + sloppy * 0.4 : (mat === M.SKY ? 0.35 : 0.6) + sloppy * 0.8, L);
        const matK = mat === M.WALL ? 1.5 : mat === M.SKY ? 1.35 : mat === M.WATER ? 1.15 : mat === M.FINE || mat === M.LIGHT ? 0.45 : mat === M.OBJ ? 0.75 : 1;
        const a = dirOf(x, y, mat, R * 1.2), ca = Math.cos(a), sa = Math.sin(a);
        if (style === "pointillist") {
          const rad = R * (pass.fine ? 0.8 : matK > 1 ? 1 : 0.85) * (0.8 + r() * 0.35);
          g.fillStyle = css(c); g.globalAlpha = 0.9;
          g.beginPath(); g.arc(x, y, rad, 0, TAU); g.fill();
          if (r() < 0.25) {   // a neighbouring hue beside it, for the eye to mix
            const h = toHsl(c); g.fillStyle = css(fromHsl(h[0] + (r() < 0.5 ? 40 : -40), Math.min(1, h[1] * 1.3), h[2])); g.globalAlpha = 0.6;
            g.beginPath(); g.arc(x + rad * 1.4, y + (r() - 0.5) * rad, rad * 0.7, 0, TAU); g.fill();
          }
          continue;
        }
        if (style === "pastel") {   // a few parallel chalk lines
          const L2 = R * (5 + r() * 4) * matK, ang = mat === M.SKY || mat === M.WATER ? a : -0.95 + (r() - 0.5) * 0.4 + (mat === M.OBJ ? a : 0) * 0.5;
          const cx = Math.cos(ang), sx = Math.sin(ang);
          g.strokeStyle = css(c); g.lineWidth = R * 0.9; g.globalAlpha = 0.55 + r() * 0.3;
          for (let k = 0; k < 3; k++) {
            const ox = -sx * (k - 1) * R * 1.1, oy = cx * (k - 1) * R * 1.1;
            g.beginPath(); g.moveTo(x + ox - cx * L2 / 2, y + oy - sx * L2 / 2); g.lineTo(x + ox + cx * L2 / 2, y + oy + sx * L2 / 2); g.stroke();
          }
          continue;
        }
        const len = R * (style === "oil" ? 3.4 : 2.6) * matK * (0.7 + r() * 0.6), w = R * (style === "oil" ? 1.15 : 0.95) * Math.max(0.6, matK * 0.9);
        const bend = (r() - 0.5) * len * 0.3, x0 = x - ca * len / 2, y0 = y - sa * len / 2, x1 = x + ca * len / 2, y1 = y + sa * len / 2;
        g.strokeStyle = css(c); g.lineWidth = w; g.globalAlpha = style === "oil" ? 0.95 : 0.85;
        g.beginPath(); g.moveTo(x0, y0); g.quadraticCurveTo(x - sa * bend, y + ca * bend, x1, y1); g.stroke();
        if (style === "oil" && w > u * 1.5) {   // impasto: the ridge of paint catches the light
          g.lineWidth = w * 0.22; g.globalAlpha = 0.35; g.strokeStyle = css(lighten(c, 0.45));
          const ox = -sa * w * 0.28 * S.lx * -1, oy = -Math.abs(ca) * w * 0.28;
          g.beginPath(); g.moveTo(x0 + ox, y0 + oy); g.quadraticCurveTo(x - sa * bend + ox, y + ca * bend + oy, x1 + ox, y1 + oy); g.stroke();
          g.globalAlpha = 0.22; g.strokeStyle = css(darken(c, 0.4));
          g.beginPath(); g.moveTo(x0 - ox, y0 - oy); g.quadraticCurveTo(x - sa * bend - ox, y + ca * bend - oy, x1 - ox, y1 - oy); g.stroke();
        }
      }
    }
    g.globalAlpha = 1;
  }

  function paperTexture(g, S, op, alpha, scale = 1) {
    const pat = g.createPattern(grain(), "repeat");
    g.save(); g.globalCompositeOperation = op; g.globalAlpha = alpha;
    if (scale !== 1 && pat.setTransform) pat.setTransform(new DOMMatrix().scaleSelf(scale, scale));
    g.fillStyle = pat; g.fillRect(0, 0, S.W, S.H); g.restore();
  }
  function smudges(g, S) {   // a young painter's thumbs
    const r = rng(S.seed ^ 0x5d6e), n = Math.round(S.kid * 5 + (1 - S.skill) * 2);
    const snap = mkCanvas(S.W, S.H); ctx2d(snap).drawImage(g.canvas, 0, 0);
    for (let i = 0; i < n; i++) {
      const x = r() * S.W, y = r() * S.H, w = S.u * (10 + r() * 22), dx = (r() - 0.5) * S.u * 8, dy = (r() - 0.5) * S.u * 4;
      g.save(); g.beginPath(); g.ellipse(x, y, w, w * 0.6, r() * 3, 0, TAU); g.clip(); g.globalAlpha = 0.35;
      g.drawImage(snap, dx, dy); g.restore();
    }
    // a stray mark or two
    if (S.kid > 0.5) for (let i = 0; i < 2; i++) {
      g.save(); g.strokeStyle = css(S.pal[i % Math.max(1, S.pal.length)] || [60, 60, 60]); g.globalAlpha = 0.6; g.lineWidth = S.u * 1.5; g.lineCap = "round";
      const x = r() * S.W, y = r() * S.H; g.beginPath(); g.moveTo(x, y); g.quadraticCurveTo(x + S.u * 10, y - S.u * 8, x + S.u * 20, y + S.u * 2); g.stroke(); g.restore();
    }
  }
  function deckle(g, S, color, inset) {   // the unpainted edge of a watercolor sheet
    const { W, H } = S, m = inset * Math.min(W, H), r = rng(S.seed ^ 0xdec), p = [];
    const side = (x0, y0, x1, y1, n) => { for (let i = 0; i < n; i++) { const t = i / n; p.push(lerp(x0, x1, t) + (r() - 0.5) * m * 0.5, lerp(y0, y1, t) + (r() - 0.5) * m * 0.5); } };
    side(m, m, W - m, m, 30); side(W - m, m, W - m, H - m, 24); side(W - m, H - m, m, H - m, 30); side(m, H - m, m, m, 24);
    g.save(); g.beginPath(); g.rect(0, 0, W, H); tracePathAppend(g, p); g.fillStyle = color; g.fill("evenodd"); g.restore();
  }
  function tracePathAppend(g, p) { g.moveTo(p[0], p[1]); for (let i = 2; i < p.length; i += 2) g.lineTo(p[i], p[i + 1]); g.closePath(); }
  function seal(g, S) {   // the painter's red seal on an ink painting
    const s = S.u * 13, x = S.W - s * 1.9, y = S.H - s * 2.1;
    g.save(); g.globalAlpha = 0.85; g.fillStyle = "#b8322a"; g.fillRect(x, y, s, s * 1.25);
    g.strokeStyle = "#f3e6d0"; g.lineWidth = S.u * 1.1; g.lineCap = "square";
    g.beginPath(); g.moveTo(x + s * 0.25, y + s * 0.25); g.lineTo(x + s * 0.75, y + s * 0.25); g.moveTo(x + s * 0.5, y + s * 0.25); g.lineTo(x + s * 0.5, y + s * 1.0);
    g.moveTo(x + s * 0.25, y + s * 0.65); g.lineTo(x + s * 0.75, y + s * 0.65); g.moveTo(x + s * 0.25, y + s * 1.0); g.lineTo(x + s * 0.75, y + s * 1.0); g.stroke();
    g.restore();
  }

  // ================================================================== paint
  function fitCanvas(cv, d) {
    const asp = Array.isArray(d.canvas) && d.canvas[0] > 0 && d.canvas[1] > 0 ? d.canvas[0] / d.canvas[1] : 4 / 3;
    const long = Math.max(cv.width, cv.height);
    let W, H;
    if (asp >= 1) { W = long; H = Math.round(long / asp); } else { H = long; W = Math.round(long * asp); }
    if (cv.width !== W || cv.height !== H) { cv.width = W; cv.height = H; }
    return [W, H];
  }
  function paint(cv, spec) {
    let d = spec || {};
    if (d.v !== 2) d = fromV1(d);
    const [W, H] = fitCanvas(cv, d), out = mkCanvas(W, H), g = ctx2d(out);
    const S = sceneOf(d, W, H), P = new Pen(S);
    try {
      drawSky(P, S);
      drawLayers(P, S);
      drawObjects(P, S);
      drawWeather(P, S);
      const marks = P.marks, style = S.style;
      g.save(); g.clearRect(0, 0, W, H);
      const paperC = style === "ink" ? "#f3ead8" : style === "watercolor" ? "#fbf8f1" : "#fdfbf6";
      g.fillStyle = paperC; g.fillRect(0, 0, W, H);
      if (style === "naive" || style === "watercolor" || style === "ink") {
        if (style === "ink") { const bg = ctx2d(mkCanvas(W, H)); renderClean(bg, marks, S); S.cleanImg = bg.getImageData(0, 0, W, H); }
        const fn = style === "naive" ? renderNaive : style === "watercolor" ? renderWatercolor : renderInk;
        fn(g, marks, S);
        if (style !== "ink") grade(g, S); else gradeInk(g, S);
        fn(g, marks, S, { emit: true });
        if (style === "ink" && S.skill > 0.35) hatch(g, S, S.cleanImg);
        if (style === "watercolor") { paperTexture(g, S, "multiply", 0.1 + 0.06 * S.kid, 0.5 * Math.max(1, S.u * 0.8)); granulate(g, S); deckle(g, S, paperC, 0.025 + S.kid * 0.02); }
        if (style === "ink") { paperTexture(g, S, "multiply", 0.15, Math.max(1, S.u)); if (S.skill > 0.55) seal(g, S); }
        if (style === "naive") paperTexture(g, S, "multiply", 0.08 + S.kid * 0.1, Math.max(1, S.u * 0.6));
      } else {
        const bg = ctx2d(mkCanvas(W, H));
        bg.fillStyle = "#fdfbf6"; bg.fillRect(0, 0, W, H);
        const base = S.kid > 0.3 ? renderNaive : renderClean;
        base(bg, marks, S); grade(bg, S); base(bg, marks, S, { emit: true });
        const ig = ctx2d(mkCanvas(W, H));
        ig.imageSmoothingEnabled = false; renderClean(ig, marks.filter((m) => m.t !== "glow" && m.t !== "fn"), S, { idMap: true }); renderClean(ig, marks.filter((m) => m.t !== "glow" && m.t !== "fn"), S, { idMap: true, emit: true });
        brushStyle(g, S, bg.getImageData(0, 0, W, H), ig.getImageData(0, 0, W, H), style);
        if (style === "oil") { const pat = g.createPattern(weave(), "repeat"); g.save(); g.globalCompositeOperation = "overlay"; g.globalAlpha = 0.18; g.fillStyle = pat; g.fillRect(0, 0, W, H); g.restore(); }
        if (style === "pastel") { paperTexture(g, S, "destination-out", 0.22, Math.max(1, S.u * 0.7)); g.save(); g.globalCompositeOperation = "destination-over"; g.fillStyle = S.time === "night" ? "#3e4459" : "#cfc2a9"; g.fillRect(0, 0, W, H); g.restore(); paperTexture(g, S, "multiply", 0.12, Math.max(1, S.u * 0.7)); }
        if (style === "pointillist" && S.skill > 0.6) dotBorder(g, S, bg.getImageData(0, 0, W, H));
      }
      if (S.skill < 0.55) smudges(g, S);
      vignette(g, S, style === "oil" ? 0.35 * S.shade : 0.18 * S.shade);
      g.restore();
      const tg = cv.getContext("2d");
      tg.clearRect(0, 0, W, H); tg.drawImage(out, 0, 0);
    } catch (err) {
      console.error("Art.paint", err);
    }
    return cv;
  }
  function gradeInk(g, S) {   // ink keeps its light: only a breath of the time of day
    g.save();
    if (S.time === "night") { g.globalCompositeOperation = "multiply"; g.fillStyle = "rgb(150,160,200)"; g.globalAlpha = 0.6; g.fillRect(0, 0, S.W, S.H); }
    else if (S.time === "evening" || S.time === "dawn") { g.globalCompositeOperation = "multiply"; g.fillStyle = "rgb(255,220,190)"; g.globalAlpha = 0.5; g.fillRect(0, 0, S.W, S.H); }
    if (S.weather === "fog") { g.globalCompositeOperation = "source-over"; g.fillStyle = "rgba(243,234,216,.5)"; g.globalAlpha = 1; g.fillRect(0, S.hor - S.H * 0.15, S.W, S.H * 0.3); }
    g.restore();
  }
  function granulate(g, S) {   // pigment settling in the paper's tooth
    const r = rng(S.seed ^ 0x6a2), n = Math.round(S.W * S.H / (S.u * S.u * 60));
    g.save(); g.globalCompositeOperation = "multiply"; g.fillStyle = "rgba(90,80,110,.06)";
    for (let i = 0; i < n; i++) { const x = r() * S.W, y = r() * S.H; g.fillRect(x, y, S.u * 0.6, S.u * 0.6); }
    g.restore();
  }
  function dotBorder(g, S, img) {   // a painted border of dots, as the pointillists did
    const { W, H, u } = S, b = u * 6, r = rng(S.seed ^ 0xb0d);
    g.save(); g.fillStyle = "#1d2440"; g.globalAlpha = 0.25;
    g.fillRect(0, 0, W, b); g.fillRect(0, H - b, W, b); g.fillRect(0, 0, b, H); g.fillRect(W - b, 0, b, H); g.globalAlpha = 1;
    const dot = (x, y) => { const o = ((clamp(y | 0, b + 2, H - b - 2) * W) + clamp(x | 0, b + 2, W - b - 2)) * 4; const c = [img.data[o], img.data[o + 1], img.data[o + 2]]; const h = toHsl(c); g.fillStyle = css(fromHsl(h[0] + 180, Math.min(1, h[1] + 0.3), 0.45)); g.beginPath(); g.arc(x, y, u * 1.1, 0, TAU); g.fill(); };
    for (let x = 0; x < W; x += u * 2) for (let k = 0; k < 2; k++) { dot(x + r() * u, b * (0.25 + k * 0.5)); dot(x + r() * u, H - b * (0.25 + k * 0.5)); }
    for (let y = b; y < H - b; y += u * 2) for (let k = 0; k < 2; k++) { dot(b * (0.25 + k * 0.5), y + r() * u); dot(W - b * (0.25 + k * 0.5), y + r() * u); }
    g.restore();
  }

  // paint many canvases without freezing the page: one at a time, when the browser is idle and the canvas is near view
  const queue = [];
  let pumping = false, io = null;
  const idle = window.requestIdleCallback ? (f) => window.requestIdleCallback(f, { timeout: 120 }) : (f) => setTimeout(f, 16);
  function pump() {
    if (pumping) return;
    pumping = true;
    idle(() => {
      pumping = false;
      const job = queue.findIndex((j) => j.visible);
      if (job < 0) return;
      const [j] = queue.splice(job, 1);
      if (j.cv.isConnected !== false) { try { j.fn(j.cv, j.spec); } catch (e) { console.error(e); } j.cv.dataset.painted = "1"; j.done && j.done(); }
      if (io) io.unobserve(j.cv);
      if (queue.some((x) => x.visible)) pump();
    });
  }
  function paintLater(cv, spec, fn = paint, done) {
    for (let i = queue.length - 1; i >= 0; i--) if (queue[i].cv === cv) queue.splice(i, 1);
    const job = { cv, spec, fn, done, visible: !("IntersectionObserver" in window) };
    queue.push(job);
    if (!io && "IntersectionObserver" in window) {
      io = new IntersectionObserver((ents) => {
        for (const e of ents) for (const j of queue) if (j.cv === e.target) j.visible = e.isIntersecting || j.visible;
        pump();
      }, { rootMargin: "300px" });
    }
    if (io) io.observe(cv);
    pump();
  }

  // ================================================================== music
  const SCALES = { major: [0, 2, 4, 5, 7, 9, 11], minor: [0, 2, 3, 5, 7, 8, 10], dorian: [0, 2, 3, 5, 7, 9, 10], mixolydian: [0, 2, 4, 5, 7, 9, 10], lydian: [0, 2, 4, 6, 7, 9, 11], pentatonic: [0, 2, 4, 7, 9] };
  const NUM = { i: 0, ii: 1, iii: 2, iv: 3, v: 4, vi: 5, vii: 6 };
  const mtof = (m) => 440 * Math.pow(2, (m - 69) / 12);
  function degToMidi(deg, root, mode) {
    const st = SCALES[mode] || SCALES.major, n = st.length, oct = Math.floor(deg / n), i = ((deg % n) + n) % n;
    return root + 12 * oct + st[i];
  }
  function chordOf(numeral, root, mode) {
    const s = String(numeral || "I"), base = s.replace(/[^ivIV]/g, ""), deg = NUM[base.toLowerCase()] ?? 0;
    const scale = mode === "pentatonic" ? SCALES.major : (SCALES[mode] || SCALES.major);
    const r = scale[deg], major = base === base.toUpperCase();
    const fifth = (scale[(deg + 4) % 7] + (deg + 4 >= 7 ? 12 : 0)) - r;
    const third = major ? 4 : 3;
    return [r, r + third, r + (fifth === 6 && major ? 7 : fifth)].map((x) => root + x);
  }
  // the whole song as timed events: the same list plays live and renders to a file
  function scoreOf(d) {
    const ev = [], beatS = 60 / (+d.tempo || 100);
    if (d.v !== 2) {
      let t = 0;
      const inst = { piano: "piano", "music box": "music box", flute: "flute", bell: "bell", guitar: "guitar", strings: "strings" }[d.instrument] || "piano";
      for (const [m, b] of d.notes || []) { if (m > 0) ev.push({ t: t * beatS, dur: b * beatS, midi: m, inst, vel: 0.8, part: "melody" }); t += b; }
      return { ev, dur: t * beatS, beat: beatS, beats: t, bars: [] };
    }
    const skill = clamp(+d.skill || 0, 0, 1), r = rng(((d.root || 60) * 7919 + (d.tempo || 1) * 31 + (d.bars || 1)) >>> 0), meter = d.meter === 3 ? 3 : 4;
    const ins = d.instruments || {}, swing = +d.swing || 0, dyn = { soft: 0.6, medium: 0.8, loud: 1 }[d.dynamics] || 0.75;
    const timeOf = (beat) => {    // swing the off-beats; an unsure hand rushes and drags
      let b = beat;
      const f = beat - Math.floor(beat);
      if (swing > 0 && Math.abs(f - 0.5) < 1e-3) b += swing * 0.33;
      return b * beatS + (r() - 0.5) * Math.pow(1 - skill, 2) * 0.12 * beatS;
    };
    let beat = 0;
    const bars = [];
    const mel = ins.melody || "piano", lift = mel === "music box" ? 12 : mel === "bell" ? 12 : 0;
    for (const name of d.form || ["A"]) {
      const sec = (d.sections || {})[name] || { chords: [], melody: [] };
      const start = beat;
      // melody
      let mb = beat;
      for (const [deg, b] of sec.melody || []) {
        if (deg !== null && deg !== undefined) {
          let midi = degToMidi(+deg, d.root || 60, d.mode || "major") + lift;
          if (r() < Math.pow(1 - skill, 2) * 0.12) midi += r() < 0.5 ? 1 : -1;      // a wrong note
          const accent = Math.abs((mb - start) % meter) < 1e-3 ? 1 : 0.85;
          ev.push({ t: timeOf(mb), dur: b * beatS * (mel === "strings" || mel === "flute" || mel === "voice" ? 0.98 : 0.92), midi, inst: mel, vel: dyn * accent * (0.85 + r() * 0.15 * (1 + (1 - skill) * 2)), part: "melody" });
        }
        mb += b;
      }
      // harmony, bass, percussion: one chord per bar
      const chords = sec.chords || [], nb = Math.max(chords.length, Math.ceil((mb - start) / meter));
      for (let i = 0; i < chords.length; i++) {
        const b0 = start + i * meter, ch = chordOf(chords[i], d.root || 60, d.mode || "major");
        bars.push({ beat: b0, chord: chords[i], section: name });
        // voice the chord around middle C
        const voiced = ch.map((m) => { while (m < 55) m += 12; while (m > 67) m -= 12; return m; }).sort((a, b) => a - b);
        const h = ins.harmony;
        if (h && h !== "none") {
          if (h === "strings") voiced.forEach((m) => ev.push({ t: timeOf(b0), dur: meter * beatS * 1.02, midi: m, inst: "strings", vel: dyn * 0.32, part: "harmony" }));
          else {
            // broken chords: root-fifth-third-fifth, gently
            const pat = meter === 3 ? [0, 1, 2] : [0, 2, 1, 2];
            pat.forEach((k, j) => ev.push({ t: timeOf(b0 + j), dur: beatS * 1.6, midi: voiced[k], inst: h, vel: dyn * (j === 0 ? 0.42 : 0.32), part: "harmony" }));
          }
        }
        if (ins.bass && ins.bass !== "none") {
          let bm = ch[0]; while (bm > 50) bm -= 12; while (bm < 36) bm += 12;
          ev.push({ t: timeOf(b0), dur: beatS * (meter === 3 ? 2.6 : 1.8), midi: bm, inst: "bass", vel: dyn * 0.7, part: "bass" });
          if (meter === 4) ev.push({ t: timeOf(b0 + 2), dur: beatS * 1.8, midi: bm + 7 > 52 ? bm + 7 - 12 : bm + 7, inst: "bass", vel: dyn * 0.55, part: "bass" });
        }
        if (ins.percussion && ins.percussion !== "none") {
          for (let j = 0; j < meter; j++) {
            if (j === 0 || (meter === 4 && j === 2)) ev.push({ t: timeOf(b0 + j), dur: 0.3, midi: 0, inst: "kick", vel: dyn * 0.55, part: "drums" });
            ev.push({ t: timeOf(b0 + j + 0.5), dur: 0.08, midi: 0, inst: "shaker", vel: dyn * 0.25, part: "drums" });
            if (meter === 4 && (j === 1 || j === 3)) ev.push({ t: timeOf(b0 + j), dur: 0.1, midi: 0, inst: "rim", vel: dyn * 0.3, part: "drums" });
          }
        }
      }
      const backed = (ins.harmony && ins.harmony !== "none") || (ins.bass && ins.bass !== "none") || (ins.percussion && ins.percussion !== "none");
      beat = start + (backed ? Math.max(mb - start, nb * meter) : mb - start);
    }
    for (const e of ev) e.t = Math.max(0, e.t);
    return { ev: ev.sort((a, b) => a.t - b.t), dur: beat * beatS, beat: beatS, beats: beat, bars };
  }

  // ---- the instruments
  const NOISE = new WeakMap();
  function noiseBuf(ctx) {
    let b = NOISE.get(ctx); if (b) return b;
    b = ctx.createBuffer(1, ctx.sampleRate * 2, ctx.sampleRate);
    const d = b.getChannelData(0); let s = 1;
    for (let i = 0; i < d.length; i++) { s = (s * 16807) % 2147483647; d[i] = (s / 2147483647) * 2 - 1; }
    NOISE.set(ctx, b); return b;
  }
  const KS = new WeakMap();
  function pluckBuf(ctx, midi) {   // Karplus-Strong: a plucked string, worked out once per note
    let m = KS.get(ctx); if (!m) KS.set(ctx, m = new Map());
    if (m.has(midi)) return m.get(midi);
    const sr = ctx.sampleRate, f = mtof(midi), N = Math.max(2, Math.round(sr / f)), len = Math.round(sr * 2.6), b = ctx.createBuffer(1, len, sr), d = b.getChannelData(0);
    const ring = new Float32Array(N); let s = midi * 977 + 1;
    for (let i = 0; i < N; i++) { s = (s * 16807) % 2147483647; ring[i] = (s / 2147483647) * 2 - 1; }
    // soften the pluck
    for (let k = 0; k < 2; k++) for (let i = 0; i < N; i++) ring[i] = 0.5 * (ring[i] + ring[(i + 1) % N]);
    const decay = 0.996 - (midi - 40) * 0.00008;
    let idx = 0, prev = 0;
    for (let i = 0; i < len; i++) { const cur = ring[idx]; const nxt = ring[(idx + 1) % N]; const v = decay * 0.5 * (cur + nxt); d[i] = cur; ring[idx] = v; prev = v; idx = (idx + 1) % N; }
    m.set(midi, b); return b;
  }
  function env(g, t, a, peak, d, sus, end, rel) {
    g.gain.setValueAtTime(0.0001, t);
    g.gain.linearRampToValueAtTime(peak, t + a);
    g.gain.setTargetAtTime(peak * sus, t + a, d);
    g.gain.setValueAtTime(peak * sus, end);       // approximate; setTarget continues toward sus
    g.gain.setTargetAtTime(0.0001, end, rel);
  }
  function voice(ctx, out, e, nodes) {
    const t = e.t0, f = mtof(e.midi), v = e.vel, end = t + e.dur;
    const osc = (type, freq, det = 0) => { const o = ctx.createOscillator(); o.type = type; o.frequency.value = freq; o.detune.value = det; nodes.push(o); return o; };
    const gain = (val = 1) => { const g = ctx.createGain(); g.gain.value = val; return g; };
    const stopAt = (o, tt) => { o.start(t); o.stop(tt); };
    switch (e.inst) {
      case "piano": case "harp": {
        const g = gain(0), lp = ctx.createBiquadFilter(); lp.type = "lowpass"; lp.Q.value = 0.4;
        lp.frequency.setValueAtTime(Math.min(16000, f * 9 + 1800), t); lp.frequency.setTargetAtTime(f * 3 + 500, t, 0.25);
        const decay = clamp(2.6 - (e.midi - 48) * 0.035, 0.8, 3), stop = Math.min(end + 0.6, t + decay * 2.4);
        g.gain.setValueAtTime(0.0001, t); g.gain.linearRampToValueAtTime(v * 0.42, t + 0.005); g.gain.setTargetAtTime(v * 0.42 * 0.3, t + 0.005, decay * 0.25);
        g.gain.setTargetAtTime(0.0001, Math.max(t + 0.02, end), 0.12);
        const parts = [["triangle", 1, 0, 0.7], ["sine", 1, 4, 0.5], ["sine", 2, -3, 0.18], ["sine", 3, 2, 0.06], ["sine", 4.02, 0, 0.03]];
        for (const [ty, mul, det, vol] of parts) { const o = osc(ty, f * mul, det), og = gain(vol); o.connect(og); og.connect(lp); stopAt(o, stop); }
        // the hammer
        const n = ctx.createBufferSource(); n.buffer = noiseBuf(ctx); const nf = ctx.createBiquadFilter(); nf.type = "bandpass"; nf.frequency.value = Math.min(9000, f * 4); nf.Q.value = 1.2;
        const ng = gain(0); ng.gain.setValueAtTime(v * 0.12, t); ng.gain.exponentialRampToValueAtTime(0.0001, t + 0.03);
        n.connect(nf); nf.connect(ng); ng.connect(out); n.start(t, Math.random() * 1.5, 0.05); nodes.push(n);
        lp.connect(g); g.connect(out); return stop;
      }
      case "music box": {
        const g = gain(1), stop = t + 2.2;
        for (const [mul, vol, dec] of [[1, 0.55, 0.9], [2.0, 0.08, 0.4], [3.01, 0.1, 0.3], [5.43, 0.05, 0.15], [8.9, 0.025, 0.08]]) {
          const o = osc("sine", f * mul), og = gain(0);
          og.gain.setValueAtTime(0.0001, t); og.gain.linearRampToValueAtTime(vol * v, t + 0.002); og.gain.exponentialRampToValueAtTime(0.0001, t + dec * 2.2);
          o.connect(og); og.connect(g); stopAt(o, stop);
        }
        g.connect(out); return stop;
      }
      case "bell": {   // FM: a modulator a little off a whole ratio
        const g = gain(0), stop = t + 3.5, car = osc("sine", f), mod = osc("sine", f * 3.5), mg = gain(0);
        mg.gain.setValueAtTime(f * 2.2, t); mg.gain.exponentialRampToValueAtTime(f * 0.05, t + 2.5);
        mod.connect(mg); mg.connect(car.frequency);
        g.gain.setValueAtTime(0.0001, t); g.gain.linearRampToValueAtTime(v * 0.28, t + 0.003); g.gain.exponentialRampToValueAtTime(0.0001, stop);
        car.connect(g); g.connect(out); stopAt(car, stop); stopAt(mod, stop); return stop;
      }
      case "flute": {
        const g = gain(0), stop = end + 0.25, o = osc("sine", f), o2 = osc("triangle", f * 2, 3), o2g = gain(0.08);
        const lfo = osc("sine", 5.2), lg = gain(0); lg.gain.setValueAtTime(0, t); lg.gain.linearRampToValueAtTime(f * 0.006, t + 0.35);
        lfo.connect(lg); lg.connect(o.frequency); lg.connect(o2.frequency);
        g.gain.setValueAtTime(0.0001, t); g.gain.linearRampToValueAtTime(v * 0.3, t + 0.07); g.gain.setTargetAtTime(v * 0.24, t + 0.07, 0.2); g.gain.setTargetAtTime(0.0001, end, 0.06);
        o.connect(g); o2.connect(o2g); o2g.connect(g);
        const n = ctx.createBufferSource(); n.buffer = noiseBuf(ctx); n.loop = true; const bp = ctx.createBiquadFilter(); bp.type = "bandpass"; bp.frequency.value = f * 2; bp.Q.value = 3;
        const ng = gain(0); ng.gain.setValueAtTime(0.0001, t); ng.gain.linearRampToValueAtTime(v * 0.06, t + 0.04); ng.gain.setTargetAtTime(v * 0.02, t + 0.06, 0.1); ng.gain.setTargetAtTime(0.0001, end, 0.05);
        n.connect(bp); bp.connect(ng); ng.connect(out); n.start(t); n.stop(stop); nodes.push(n);
        g.connect(out); stopAt(o, stop); stopAt(o2, stop); stopAt(lfo, stop); return stop;
      }
      case "strings": {
        const g = gain(0), lp = ctx.createBiquadFilter(); lp.type = "lowpass"; lp.frequency.value = Math.min(5000, f * 5 + 600); lp.Q.value = 0.5;
        const stop = end + 0.7, lfo = osc("sine", 5.4), lg = gain(f * 0.004);
        lfo.connect(lg);
        for (const det of [-7, 0, 6]) { const o = osc("sawtooth", f, det); lg.connect(o.frequency); const og = gain(0.33); o.connect(og); og.connect(lp); stopAt(o, stop); }
        g.gain.setValueAtTime(0.0001, t); g.gain.linearRampToValueAtTime(v * (e.part === "melody" ? 0.45 : 0.16), t + 0.28); g.gain.setTargetAtTime(0.0001, end, 0.22);
        lp.connect(g); g.connect(out); stopAt(lfo, stop); return stop;
      }
      case "guitar": {
        const s = ctx.createBufferSource(); s.buffer = pluckBuf(ctx, e.midi); const g = gain(0), lp = ctx.createBiquadFilter(); lp.type = "lowpass"; lp.frequency.value = 3200;
        const stop = Math.min(t + 2.5, end + 0.5);
        g.gain.setValueAtTime(v * 0.55, t); g.gain.setTargetAtTime(0.0001, Math.max(t + 0.05, end + 0.1), 0.15);
        s.connect(lp); lp.connect(g); g.connect(out); s.start(t); s.stop(stop); nodes.push(s); return stop;
      }
      case "voice": {   // a soft "ah" turning to "oo": a buzz through vowel formants
        const g = gain(0), stop = end + 0.35, src = osc("sawtooth", f), lfo = osc("sine", 5), lg = gain(0);
        lg.gain.setValueAtTime(0, t); lg.gain.linearRampToValueAtTime(f * 0.008, t + 0.4); lfo.connect(lg); lg.connect(src.frequency);
        const pre = ctx.createBiquadFilter(); pre.type = "lowpass"; pre.frequency.value = 3000; src.connect(pre);
        for (const [f1, f2, amp] of [[700, 360, 1], [1150, 900, 0.6], [2600, 2300, 0.25]]) {
          const bp = ctx.createBiquadFilter(); bp.type = "bandpass"; bp.Q.value = 8; bp.frequency.setValueAtTime(f1, t); bp.frequency.linearRampToValueAtTime(f2, end);
          const bg = gain(amp); pre.connect(bp); bp.connect(bg); bg.connect(g);
        }
        g.gain.setValueAtTime(0.0001, t); g.gain.linearRampToValueAtTime(v * 0.55, t + 0.12); g.gain.setTargetAtTime(0.0001, end, 0.12);
        g.connect(out); stopAt(src, stop); stopAt(lfo, stop); return stop;
      }
      case "bass": {
        const g = gain(0), lp = ctx.createBiquadFilter(); lp.type = "lowpass"; lp.frequency.value = 520; lp.Q.value = 0.8;
        const stop = end + 0.3, o = osc("triangle", f), o2 = osc("sine", f), o2g = gain(0.7);
        g.gain.setValueAtTime(0.0001, t); g.gain.linearRampToValueAtTime(v * 0.5, t + 0.012); g.gain.setTargetAtTime(v * 0.25, t + 0.02, 0.35); g.gain.setTargetAtTime(0.0001, end, 0.08);
        o.connect(lp); o2.connect(o2g); o2g.connect(lp); lp.connect(g); g.connect(out); stopAt(o, stop); stopAt(o2, stop); return stop;
      }
      case "kick": {
        const g = gain(0), o = osc("sine", 110), stop = t + 0.35;
        o.frequency.setValueAtTime(120, t); o.frequency.exponentialRampToValueAtTime(45, t + 0.12);
        g.gain.setValueAtTime(v * 0.7, t); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.3);
        o.connect(g); g.connect(out); stopAt(o, stop); return stop;
      }
      case "shaker": case "rim": {
        const n = ctx.createBufferSource(); n.buffer = noiseBuf(ctx); const hp = ctx.createBiquadFilter(); hp.type = e.inst === "rim" ? "bandpass" : "highpass"; hp.frequency.value = e.inst === "rim" ? 1800 : 7000; hp.Q.value = e.inst === "rim" ? 4 : 0.7;
        const g = gain(0); g.gain.setValueAtTime(v * (e.inst === "rim" ? 0.5 : 0.3), t); g.gain.exponentialRampToValueAtTime(0.0001, t + (e.inst === "rim" ? 0.06 : 0.05));
        n.connect(hp); hp.connect(g); g.connect(out); n.start(t, (e.midi * 0.13 + t) % 1.5, 0.12); nodes.push(n); return t + 0.12;
      }
      default: return t;
    }
  }
  function impulse(ctx, secs, decay) {
    const sr = ctx.sampleRate, len = Math.round(sr * secs), b = ctx.createBuffer(2, len, sr);
    for (let c = 0; c < 2; c++) {
      const d = b.getChannelData(c); let s = 12345 + c * 999;
      for (let i = 0; i < len; i++) { s = (s * 16807) % 2147483647; const n = (s / 2147483647) * 2 - 1; d[i] = n * Math.pow(1 - i / len, decay) * (i < sr * 0.01 ? i / (sr * 0.01) : 1); }
    }
    return b;
  }
  const PAN = { melody: 0.08, harmony: -0.25, bass: 0, drums: 0.18 };
  function graph(ctx, d) {   // parts → reverb → compressor → out
    const master = ctx.createGain(), comp = ctx.createDynamicsCompressor();
    comp.threshold.value = -16; comp.knee.value = 12; comp.ratio.value = 3; comp.attack.value = 0.01; comp.release.value = 0.25;
    master.gain.value = 0.9;
    const dry = ctx.createGain(), wet = ctx.createGain(), verb = ctx.createConvolver();
    verb.buffer = impulse(ctx, 2.4, 3.2);
    const rv = clamp(d.v === 2 ? +d.reverb || 0.3 : 0.3, 0, 0.9);
    dry.gain.value = 1 - rv * 0.35; wet.gain.value = rv * 0.9;
    const bus = ctx.createGain();
    bus.connect(dry); bus.connect(verb); verb.connect(wet); dry.connect(comp); wet.connect(comp); comp.connect(master);
    const analyser = ctx.createAnalyser(); analyser.fftSize = 2048; analyser.smoothingTimeConstant = 0.7;
    master.connect(analyser);
    const parts = {};
    for (const p of Object.keys(PAN)) {
      const g = ctx.createGain(), pan = ctx.createStereoPanner ? ctx.createStereoPanner() : null;
      g.gain.value = 1;
      if (pan) { pan.pan.value = PAN[p]; g.connect(pan); pan.connect(bus); } else g.connect(bus);
      parts[p] = g;
    }
    return { master, analyser, parts, nodes: [verb, comp, master] };
  }

  let ctx = null, playing = null;
  function play(d, onEnd) {
    stop();
    d = d || {};
    ctx = ctx || new (window.AudioContext || window.webkitAudioContext)();
    if (ctx.state === "suspended") ctx.resume();
    const sc = scoreOf(d), G = graph(ctx, d);
    G.master.connect(ctx.destination);
    G.master.gain.setValueAtTime(0.0001, ctx.currentTime); G.master.gain.linearRampToValueAtTime(0.9, ctx.currentTime + 0.05);
    const t0 = ctx.currentTime + 0.12, nodes = [];
    let i = 0;
    const tick = () => {    // schedule a little ahead of time, so long songs don't build every note at once
      const horizon = ctx.currentTime + 0.6;
      while (i < sc.ev.length && t0 + sc.ev[i].t < horizon) {
        const e = Object.assign({}, sc.ev[i++]); e.t0 = t0 + e.t;
        voice(ctx, G.parts[e.part] || G.parts.melody, e, nodes);
      }
      if (nodes.length > 400) nodes.splice(0, nodes.length - 400);
    };
    tick();
    const timer = setInterval(tick, 150);
    const total = sc.dur + 2.2;
    const end = setTimeout(() => { const cb = playing?.onEnd; cleanup(); cb && cb(); }, total * 1000 + 200);
    playing = { nodes, end, timer, G, onEnd, t0, score: sc, ctx, spec: d };
    return playing;
  }
  function cleanup() {
    if (!playing) return;
    const p = playing; playing = null;
    clearTimeout(p.end); clearInterval(p.timer);
    const now = p.ctx.currentTime;
    try { p.G.master.gain.cancelScheduledValues(now); p.G.master.gain.setValueAtTime(p.G.master.gain.value, now); p.G.master.gain.linearRampToValueAtTime(0.0001, now + 0.12); } catch { /* closing */ }
    setTimeout(() => { for (const n of p.nodes) try { n.stop(); } catch { /* already stopped */ } try { p.G.master.disconnect(); } catch { /* gone */ } }, 180);
  }
  function stop() {
    if (!playing) return;
    const cb = playing.onEnd; cleanup(); cb && cb();
  }
  // render a song to a WAV file
  async function render(d) {
    d = d || {};
    const sc = scoreOf(d), sr = 44100, secs = sc.dur + 2.6;
    const OAC = window.OfflineAudioContext || window.webkitOfflineAudioContext;
    const oc = new OAC(2, Math.ceil(sr * secs), sr), G = graph(oc, d), nodes = [];
    G.master.connect(oc.destination);
    // build the notes a couple of seconds at a time, so the graph stays small however long the song
    const CH = 2, evs = sc.ev.map((e0) => Object.assign({}, e0, { t0: e0.t + 0.05 }));
    let i = 0;
    const upTo = (lim) => { while (i < evs.length && evs[i].t0 < lim) { voice(oc, G.parts[evs[i].part] || G.parts.melody, evs[i], nodes); i++; } nodes.length = 0; };
    upTo(CH);
    for (let k = 1; k * CH < secs - 0.01; k++) {
      const at = Math.round(k * CH * sr / 128) * 128 / sr;
      oc.suspend(at).then(() => { upTo(at + CH + 0.01); oc.resume(); });
    }
    const buf = await oc.startRendering();
    return wav(buf);
  }
  function wav(buf) {
    const ch = buf.numberOfChannels, n = buf.length, sr = buf.sampleRate, bytes = 44 + n * ch * 2, ab = new ArrayBuffer(bytes), v = new DataView(ab);
    const str = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
    str(0, "RIFF"); v.setUint32(4, bytes - 8, true); str(8, "WAVE"); str(12, "fmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, ch, true);
    v.setUint32(24, sr, true); v.setUint32(28, sr * ch * 2, true); v.setUint16(32, ch * 2, true); v.setUint16(34, 16, true); str(36, "data"); v.setUint32(40, n * ch * 2, true);
    const data = []; for (let c = 0; c < ch; c++) data.push(buf.getChannelData(c));
    let o = 44;
    for (let i = 0; i < n; i++) for (let c = 0; c < ch; c++) { const s = clamp(data[c][i], -1, 1); v.setInt16(o, s < 0 ? s * 0x8000 : s * 0x7fff, true); o += 2; }
    return new Blob([ab], { type: "audio/wav" });
  }
  // a piano roll of the whole song, with an optional playhead
  function roll(cv, d, at = -1) {
    const g = cv.getContext("2d"), W = cv.width, H = cv.height, sc = scoreOf(d || {});
    const bg = g.createLinearGradient(0, 0, 0, H); bg.addColorStop(0, "#151b2e"); bg.addColorStop(1, "#0d1120");
    g.fillStyle = bg; g.fillRect(0, 0, W, H);
    const mel = sc.ev.filter((e) => e.midi > 0);
    if (!mel.length) return;
    const lo = Math.min(...mel.map((e) => e.midi)) - 2, hi = Math.max(...mel.map((e) => e.midi)) + 3, dur = Math.max(sc.dur, 0.1);
    const X = (t) => 4 + t / dur * (W - 8), Y = (m) => H - 6 - (m - lo) / (hi - lo) * (H - 12);
    g.fillStyle = "rgba(255,255,255,.05)";
    for (const b of sc.bars) g.fillRect(X(b.beat * sc.beat), 0, 1, H);
    const col = { melody: [255, 214, 120], harmony: [140, 170, 255], bass: [120, 220, 190], drums: [255, 255, 255] };
    for (const e of mel) {
      const c = col[e.part] || col.melody, x = X(e.t), w = Math.max(2, X(e.t + e.dur) - x - 1), y = Y(e.midi), on = at >= e.t && at < e.t + e.dur;
      g.fillStyle = css(on ? lighten(c, 0.6) : c, e.part === "melody" ? 0.95 : 0.35);
      const hh = e.part === "melody" ? Math.max(3, H / 26) : Math.max(2, H / 40);
      g.beginPath(); if (g.roundRect) g.roundRect(x, y - hh / 2, w, hh, hh / 2); else g.rect(x, y - hh / 2, w, hh); g.fill();
    }
    if (at >= 0) { g.fillStyle = "rgba(255,255,255,.8)"; g.fillRect(X(at), 0, 1.5, H); }
  }

  // ================================================================== sculptures
  let S3 = null, s3Queue = Promise.resolve();
  function load3d() {
    if (!S3) S3 = import(new URL("sculpt3d.js", SCRIPT_URL).href).catch((e) => { console.warn("3D sculpture view unavailable:", e); return null; });
    return S3;
  }
  function sculpt(cv, spec) {
    sculpt2d(cv, spec);                      // something to look at straight away
    s3Queue = s3Queue.then(async () => {
      const m = await load3d();
      if (m && cv.isConnected !== false) { try { await m.renderTo(cv, spec || {}); } catch (e) { console.warn(e); } }
    });
    return s3Queue;
  }
  function sculpt2d(cv, d) {    // a drawn fallback (no WebGL): parts seen from the front
    const g = cv.getContext("2d"), W = cv.width, H = cv.height, cols = d.colors || ["#a8a29e", "#d6d3d1", "#78716c"];
    const bg = g.createLinearGradient(0, 0, 0, H); bg.addColorStop(0, "#2a2f3d"); bg.addColorStop(1, "#14171f");
    g.fillStyle = bg; g.fillRect(0, 0, W, H);
    const parts = (d.parts || []).map((p) => p.pos ? { shape: p.shape, x: p.pos[0], y: p.pos[1], w: p.scale[0] * 2, h: (p.shape === "cylinder" || p.shape === "cone" ? p.scale[1] : p.scale[1] * 2), rot: p.rot?.[2] || 0, tone: p.tone || 0, z: p.pos[2] } :
      { shape: p.shape, x: p.x || 0, y: p.y, w: p.w, h: p.h, rot: Math.sin(p.rot || 0) * 0.12, tone: 0, z: 0 });
    parts.sort((a, b) => a.z - b.z);
    const scale = H * 0.62 / Math.max(0.6, d.height || 1), base = H * 0.84, cx = W / 2;
    g.fillStyle = "#3a3f4d"; g.fillRect(cx - W * 0.22, base, W * 0.44, H * 0.06);
    for (const p of parts) {
      const w = p.w * scale, h = p.h * scale, y = base - p.y * scale, x = cx + p.x * scale, c = d.glaze && p.tone !== 2 ? d.glaze : cols[p.tone || 0];
      const grad = g.createLinearGradient(x - w / 2, y - h / 2, x + w / 2, y + h / 2);
      grad.addColorStop(0, css(lighten(rgb(c), 0.3))); grad.addColorStop(0.55, c); grad.addColorStop(1, css(darken(rgb(c), 0.4)));
      g.fillStyle = grad; g.save(); g.translate(x, y); g.rotate(-p.rot); g.beginPath();
      if (p.shape === "sphere" || p.shape === "capsule") g.ellipse(0, 0, Math.max(1, w / 2), Math.max(1, h / 2), 0, 0, TAU);
      else if (p.shape === "cone") { g.moveTo(-w / 2, h / 2); g.lineTo(0, -h / 2); g.lineTo(w / 2, h / 2); }
      else if (p.shape === "torus") { g.ellipse(0, 0, w / 2, h / 2, 0, 0, TAU); g.ellipse(0, 0, w / 4, h / 4, 0, 0, TAU, true); }
      else if (p.shape === "octahedron") { g.moveTo(0, -h / 2); g.lineTo(w / 2, 0); g.lineTo(0, h / 2); g.lineTo(-w / 2, 0); }
      else g.rect(-w / 2, -h / 2, w, h);
      g.fill("evenodd"); g.restore();
    }
  }

  return {
    paint, paintLater, play, stop, render, roll, sculpt, sculpt2d, scoreOf, fromV1,
    isPlaying: () => !!playing, playing: () => playing, audioTime: () => (playing ? playing.ctx.currentTime - playing.t0 : -1),
    load3d, _rng: rng,
  };
})();
window.Art = Art;
