"use strict";
// The studio (DESIGN-v4 §8): Zen's art made one mark at a time. This file re-implements the studio's rules
// so any piece can be replayed as a time-lapse from its `ops`, renders the v3 formats (painting `pixels`,
// music `notes`, sculpture `voxels`), shows a piece growing live from the snapshot's `studio`, and teaches
// Art (art.js) to hand v3 pieces here so the gallery and viewer keep working for every format.

const Studio = (() => {
  const BASE = (document.currentScript && document.currentScript.src) || location.origin + "/static/studio.js";
  const SYM = "0123456789abcdefghijklmnopqrstuvwxyz";
  const PAINT = ["up", "down", "left", "right", "jump", "press", "lift", "dot", "big", "small", "black", "white", "red", "orange",
    "yellow", "green", "blue", "purple", "pink", "brown", "grey", "gold", "done"];
  const MUSIC = ["C", "D", "E", "F", "G", "A", "B", "high", "low", "long", "short", "rest", "fast", "slow", "done"];
  const SCULPT = ["up", "down", "left", "right", "in", "out", "add", "cut", "smooth", "done"];
  const PALETTE = ["#1d1d1f", "#f7f4ec", "#d64545", "#ef8a3a", "#f2c94c", "#4f9a4f", "#3f6fb5", "#8e5bb5", "#ee8fb2", "#8a5a2b", "#8d8d8d", "#d9a93b"];   // studio.PALETTE
  const MATERIAL = { clay: "#b98159", terracotta: "#c46a43", stone: "#9b958b", porcelain: "#ebe5da", bronze: "#a9783a", wax: "#e5cf9a", wood: "#a07548" };
  const MAX = { paint: 900, music: 200, sculpt: 600 };
  const words = (vocab, ops) => [...String(ops || "")].map((ch) => vocab[SYM.indexOf(ch)]).filter(Boolean);
  const clamp = (v, a, b) => (v < a ? a : v > b ? b : v);
  const hash = (i, s = 0) => { let h = Math.imul(i ^ 0x9e3779b9, 2654435761) ^ Math.imul(s + 7, 40503); h = Math.imul(h ^ (h >>> 15), 2246822519); h ^= h >>> 13; return (h >>> 0) / 4294967296; };
  const mediumOf = (c) => { const d = c?.data || c || {}; return d.pixels != null ? "paint" : d.voxels != null ? "sculpt" : Array.isArray(d.notes) && d.v === 3 ? "music" : null; };
  const isV3 = (d) => !!d && d.v === 3;

  // ================================================================== the rules, step by step
  function painter(w = 64, h = 48) {
    const s = { w, h, px: new Int8Array(w * h).fill(-1), x: w >> 1, y: h >> 1, pen: false, color: 0, size: 1, dir: "right", done: false, n: 0 };
    const paint = () => {
      const r = s.size === 3 ? 1 : 0;
      for (let dy = -r; dy <= r; dy++) for (let dx = -r; dx <= r; dx++) {
        const x = s.x + dx, y = s.y + dy;
        if (x >= 0 && y >= 0 && x < w && y < h) s.px[y * w + x] = s.color;
      }
    };
    const move = (d) => {
      const [dx, dy] = { up: [0, -1], down: [0, 1], left: [-1, 0], right: [1, 0] }[d];
      const nx = clamp(s.x + dx, 0, w - 1), ny = clamp(s.y + dy, 0, h - 1);
      const moved = nx !== s.x || ny !== s.y;
      s.x = nx; s.y = ny;
      if (moved && s.pen) paint();
    };
    s.step = (word) => {
      if (s.done || s.n >= MAX.paint) return;
      s.n++;
      switch (word) {
        case "up": case "down": case "left": case "right": s.dir = word; move(word); break;
        case "jump": for (let i = 0; i < 6; i++) move(s.dir); break;
        case "press": s.pen = true; paint(); break;
        case "lift": s.pen = false; break;
        case "dot": paint(); break;
        case "big": s.size = 3; break;
        case "small": s.size = 1; break;
        case "done": s.done = true; break;
        default: { const c = PAINT.indexOf(word) - 10; if (c >= 0 && c < 12) s.color = c; }
      }
    };
    return s;
  }
  function composer() {
    const s = { notes: [], tempo: 100, tempo0: 100, changes: [], octave: 4, len: 1, done: false, n: 0 };
    s.step = (word) => {
      if (s.done || s.n >= MAX.music) return;
      s.n++;
      const k = "CDEFGAB".indexOf(word);
      if (word.length === 1 && k >= 0) { s.notes.push([12 * (s.octave + 1) + [0, 2, 4, 5, 7, 9, 11][k], s.len]); return; }
      switch (word) {
        case "high": s.octave = Math.min(6, s.octave + 1); break;
        case "low": s.octave = Math.max(3, s.octave - 1); break;
        case "long": s.len = 2; break;
        case "short": s.len = 0.5; break;
        case "rest": s.notes.push([-1, s.len]); break;
        case "fast": case "slow": s.tempo = clamp(s.tempo + (word === "fast" ? 12 : -12), 60, 180); s.changes.push([s.notes.length, s.tempo]); break;
        case "done": s.done = true; break;
      }
    };
    return s;
  }
  function sculptor(n = 12) {
    const s = { n, vox: new Uint8Array(n * n * n), x: n >> 1, y: 0, z: n >> 1, done: false, k: 0 };
    const I = (x, y, z) => x + n * (z + n * y);
    const inside = (x, y, z) => x >= 0 && y >= 0 && z >= 0 && x < n && y < n && z < n;
    s.step = (word) => {
      if (s.done || s.k >= MAX.sculpt) return;
      s.k++;
      const mv = { up: [0, 1, 0], down: [0, -1, 0], left: [-1, 0, 0], right: [1, 0, 0], in: [0, 0, -1], out: [0, 0, 1] }[word];
      if (mv) { s.x = clamp(s.x + mv[0], 0, n - 1); s.y = clamp(s.y + mv[1], 0, n - 1); s.z = clamp(s.z + mv[2], 0, n - 1); return; }
      if (word === "add") s.vox[I(s.x, s.y, s.z)] = 1;
      else if (word === "cut") s.vox[I(s.x, s.y, s.z)] = 0;
      else if (word === "smooth") {
        const fill = [];
        for (let y = s.y - 1; y <= s.y + 1; y++) for (let z = s.z - 1; z <= s.z + 1; z++) for (let x = s.x - 1; x <= s.x + 1; x++) {
          if (!inside(x, y, z) || s.vox[I(x, y, z)]) continue;
          let c = 0;
          for (const [a, b, d] of [[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]]) if (inside(x + a, y + b, z + d) && s.vox[I(x + a, y + b, z + d)]) c++;
          if (c >= 4) fill.push(I(x, y, z));
        }
        for (const i of fill) s.vox[i] = 1;
      } else if (word === "done") s.done = true;
    };
    return s;
  }
  // the state after the first `upto` words of a piece
  function replay(medium, d, upto = Infinity) {
    const vocab = medium === "paint" ? PAINT : medium === "music" ? MUSIC : SCULPT;
    const s = medium === "paint" ? painter(d.w || 64, d.h || 48) : medium === "music" ? composer() : sculptor(d.n || 12);
    const ws = words(vocab, d.ops);
    for (let i = 0; i < Math.min(upto, ws.length); i++) s.step(ws[i]);
    s.words = ws; s.word = ws[Math.min(upto, ws.length) - 1] || "";
    return s;
  }

  // ================================================================== painting
  function pixelsOf(d) {
    const w = d.w || 64, h = d.h || 48, px = new Int8Array(w * h).fill(-1), str = String(d.pixels || "");
    for (let i = 0; i < Math.min(str.length, w * h); i++) { const c = str[i]; if (c !== ".") { const k = SYM.indexOf(c); if (k >= 0 && k < 12) px[i] = k; } }
    return px;
  }
  const rgb = (h) => { h = String(h || "#000").replace("#", ""); if (h.length === 3) h = [...h].map((c) => c + c).join(""); return [parseInt(h.slice(0, 2), 16) || 0, parseInt(h.slice(2, 4), 16) || 0, parseInt(h.slice(4, 6), 16) || 0]; };
  const paperCache = new Map();
  function paper(W, H) {
    const k = W + "x" + H; let c = paperCache.get(k); if (c) return c;
    c = document.createElement("canvas"); c.width = W; c.height = H;
    const g = c.getContext("2d");
    g.fillStyle = "#f4eedf"; g.fillRect(0, 0, W, H);
    const im = g.getImageData(0, 0, W, H), D = im.data;
    for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
      const o = (y * W + x) * 4, n = (hash(x * 7 + y * 131, 3) - 0.5) * 10 + (hash((x >> 2) * 31 + (y >> 2) * 977, 5) - 0.5) * 7;
      D[o] += n; D[o + 1] += n; D[o + 2] += n * 0.9;
    }
    g.putImageData(im, 0, 0);
    const vg = g.createRadialGradient(W / 2, H / 2, Math.min(W, H) * 0.35, W / 2, H / 2, Math.max(W, H) * 0.75);
    vg.addColorStop(0, "rgba(120,90,50,0)"); vg.addColorStop(1, "rgba(120,90,50,.12)");
    g.fillStyle = vg; g.fillRect(0, 0, W, H);
    if (paperCache.size > 12) paperCache.clear();
    paperCache.set(k, c); return c;
  }
  // every painted cell is a soft, slightly irregular dab of its colour; blank cells show the paper
  function drawPixels(cv, px, w, h, pal, cursor) {
    const W = cv.width, H = cv.height, g = cv.getContext("2d");
    const cs = Math.min(W / w, H / h), ox = (W - cs * w) / 2, oy = (H - cs * h) / 2;
    g.drawImage(paper(W, H), 0, 0);
    const P = (pal && pal.length >= 12 ? pal : PALETTE).map(rgb);
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      const k = px[y * w + x]; if (k < 0) continue;
      const i = y * w + x, [r, gg, b] = P[k], v = (hash(i, 11) - 0.5) * 16;
      const cx = ox + (x + 0.5) * cs + (hash(i, 1) - 0.5) * cs * 0.16, cy = oy + (y + 0.5) * cs + (hash(i, 2) - 0.5) * cs * 0.16;
      const rx = cs * (0.6 + hash(i, 3) * 0.12), ry = cs * (0.56 + hash(i, 4) * 0.12);
      g.fillStyle = `rgb(${clamp(r + v, 0, 255) | 0},${clamp(gg + v, 0, 255) | 0},${clamp(b + v * 0.8, 0, 255) | 0})`;
      g.beginPath(); g.ellipse(cx, cy, rx, ry, hash(i, 5) * Math.PI, 0, Math.PI * 2); g.fill();
    }
    if (cs >= 4) {     // a little pigment texture on top: lighter flecks inside the dabs
      g.globalAlpha = 0.12; g.fillStyle = "#fff";
      for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
        const i = y * w + x; if (px[i] < 0 || hash(i, 9) < 0.55) continue;
        g.beginPath(); g.ellipse(ox + (x + 0.3 + hash(i, 6) * 0.4) * cs, oy + (y + 0.3 + hash(i, 7) * 0.4) * cs, cs * 0.18, cs * 0.08, hash(i, 8) * 3, 0, 7); g.fill();
      }
      g.globalAlpha = 1;
    }
    if (cursor) {
      const { x, y, size = 1, pen, color = 0 } = cursor, r = (size === 3 ? 1.5 : 0.5) * cs;
      const cx = ox + (x + 0.5) * cs, cy = oy + (y + 0.5) * cs;
      g.lineWidth = Math.max(1.5, cs * 0.18); g.strokeStyle = "rgba(20,24,40,.85)";
      g.beginPath(); g.arc(cx, cy, r + cs * 0.35, 0, 7); g.stroke();
      g.strokeStyle = "#fff"; g.lineWidth = Math.max(1, cs * 0.08); g.beginPath(); g.arc(cx, cy, r + cs * 0.35, 0, 7); g.stroke();
      g.fillStyle = (pal && pal[color]) || PALETTE[color] || "#000"; g.globalAlpha = pen ? 0.95 : 0.45;
      g.beginPath(); g.arc(cx, cy, Math.max(2, cs * 0.28), 0, 7); g.fill(); g.globalAlpha = 1;
    }
  }
  function paint(cv, d) { drawPixels(cv, pixelsOf(d), d.w || 64, d.h || 48, d.palette); }

  // ================================================================== music
  // v3 notes with tempo changes → a plain song for Art's piano (each note's beats scaled to the first tempo)
  function song(d) {
    const t0 = +d.tempo || 100, ch = (d.tempo_changes || []).slice().sort((a, b) => a[0] - b[0]);
    let tempo = t0, ci = 0;
    const notes = (d.notes || []).map(([m, b], i) => {
      while (ci < ch.length && ch[ci][0] <= i) tempo = ch[ci++][1];
      return [m > 0 ? m : -1, b * t0 / tempo];
    });
    return { v: 1, notes, tempo: t0, instrument: "piano", skill: 0.9 };
  }

  // ================================================================== sculpture
  function voxelsOf(d) { const n = d.n || 12, s = String(d.voxels || ""), v = new Uint8Array(n * n * n); for (let i = 0; i < Math.min(s.length, v.length); i++) v[i] = s[i] === "1" ? 1 : 0; return v; }
  const matColor = (d) => (/^#[0-9a-f]{6}$/i.test(d?.material || "") ? d.material : MATERIAL[String(d?.material || "clay").toLowerCase()] || MATERIAL.clay);
  // a drawn still: the clay seen from a three-quarter view, as soft overlapping lumps lit from the upper left
  function drawVoxels(cv, vox, n, color, cursor, yaw = 0.62) {
    const W = cv.width, H = cv.height, g = cv.getContext("2d");
    const bg = g.createRadialGradient(W * 0.5, H * 0.38, 0, W * 0.5, H * 0.45, Math.max(W, H) * 0.75);
    bg.addColorStop(0, "#4a4440"); bg.addColorStop(1, "#18171c"); g.fillStyle = bg; g.fillRect(0, 0, W, H);
    const s = Math.min(W, H) / (n * 1.55), cy = Math.cos(yaw), sy = Math.sin(yaw), tilt = 0.5;
    const proj = (x, y, z) => { const X = x - n / 2 + 0.5, Z = z - n / 2 + 0.5; const rx = X * cy - Z * sy, rz = X * sy + Z * cy;
      return [W / 2 + rx * s, H * 0.78 - y * s * 0.92 + rz * s * tilt, rz]; };
    // plinth
    const [px, py] = proj(n / 2 - 0.5, -0.5, n / 2 - 0.5);
    g.fillStyle = "#2b2830"; g.beginPath(); g.ellipse(px, py + s * 0.4, n * s * 0.62, n * s * 0.62 * tilt, 0, 0, 7); g.fill();
    g.fillStyle = "rgba(0,0,0,.35)"; g.beginPath(); g.ellipse(px, py + s * 0.2, n * s * 0.5, n * s * 0.5 * tilt, 0, 0, 7); g.fill();
    const list = [];
    for (let y = 0; y < n; y++) for (let z = 0; z < n; z++) for (let x = 0; x < n; x++) if (vox[x + n * (z + n * y)]) list.push([x, y, z, ...proj(x, y, z)]);
    list.sort((a, b) => b[5] - a[5] || a[1] - b[1]);
    const [r, gg, b] = rgb(color);
    for (const [x, y, z, sx, sy2] of list) {
      const occl = (vox[x + n * (z + n * Math.min(n - 1, y + 1))] && y < n - 1) ? 0.82 : 1;
      const gr = g.createRadialGradient(sx - s * 0.25, sy2 - s * 0.3, s * 0.05, sx, sy2, s * 0.78);
      const L = (f) => `rgb(${clamp(r * f, 0, 255) | 0},${clamp(gg * f, 0, 255) | 0},${clamp(b * f, 0, 255) | 0})`;
      gr.addColorStop(0, L(1.28 * occl)); gr.addColorStop(0.55, L(0.95 * occl)); gr.addColorStop(1, L(0.62 * occl));
      g.fillStyle = gr; g.beginPath(); g.arc(sx, sy2, s * 0.74, 0, 7); g.fill();
    }
    if (cursor) {
      const [cx, cyy] = proj(cursor.x, cursor.y, cursor.z);
      g.strokeStyle = "rgba(255,255,255,.9)"; g.lineWidth = 2; g.setLineDash([4, 3]);
      g.beginPath(); g.arc(cx, cyy, s * 0.8, 0, 7); g.stroke(); g.setLineDash([]);
    }
    if (!list.length) { g.fillStyle = "rgba(255,255,255,.5)"; g.font = `${Math.max(11, W / 30)}px system-ui`; g.textAlign = "center"; g.fillText("no clay yet", W / 2, H / 2); }
  }
  function sculpt(cv, d) { drawVoxels(cv, voxelsOf(d), d.n || 12, matColor(d)); return Promise.resolve(); }

  // an orbit view in three.js: each voxel a soft lump of clay (overlapping spheres read as one smooth-ish form)
  async function mountOrbit(container, d) {
    const THREE = await import(new URL("vendor/three.module.min.js", BASE).href);
    const cv = document.createElement("canvas"); cv.className = "voxorbit"; container.append(cv);
    const r = new THREE.WebGLRenderer({ canvas: cv, antialias: true }); r.setPixelRatio(Math.min(2, devicePixelRatio || 1));
    r.outputColorSpace = THREE.SRGBColorSpace; r.toneMapping = THREE.ACESFilmicToneMapping;
    const scene = new THREE.Scene(); scene.background = new THREE.Color("#211f24");
    const cam = new THREE.PerspectiveCamera(35, 1, 0.1, 100);
    scene.add(new THREE.HemisphereLight(0xfff2e0, 0x2a2430, 1.4));
    const key = new THREE.DirectionalLight(0xffffff, 2.2); key.position.set(-4, 7, 5); scene.add(key);
    const n = d.n || 12, vox = voxelsOf(d), list = [];
    for (let i = 0; i < vox.length; i++) if (vox[i]) list.push(i);
    const mat = new THREE.MeshStandardMaterial({ color: matColor(d), roughness: 0.85, metalness: 0 });
    const geo = new THREE.SphereGeometry(0.72, 16, 12), m = new THREE.InstancedMesh(geo, mat, Math.max(1, list.length)), M = new THREE.Matrix4();
    list.forEach((i, k) => { const x = i % n, z = Math.floor(i / n) % n, y = Math.floor(i / (n * n));
      const j = (hash(i, 3) - 0.5) * 0.08; M.makeTranslation(x - n / 2 + 0.5 + j, y + 0.5, z - n / 2 + 0.5 - j); m.setMatrixAt(k, M); });
    m.count = list.length; scene.add(m);
    const plinth = new THREE.Mesh(new THREE.CylinderGeometry(n * 0.62, n * 0.66, 0.8, 40), new THREE.MeshStandardMaterial({ color: 0x3a363c, roughness: 0.6 }));
    plinth.position.y = -0.4; scene.add(plinth);
    let yaw = 0.6, pitch = 0.35, dist = n * 2.4, drag = null, raf = 0, dead = false;
    const draw = () => {
      const w = container.clientWidth || 400, h = container.clientHeight || 400;
      if (cv.width !== Math.round(w * r.getPixelRatio())) { r.setSize(w, h, false); cam.aspect = w / h; cam.updateProjectionMatrix(); }
      cam.position.set(Math.sin(yaw) * Math.cos(pitch) * dist, n * 0.45 + Math.sin(pitch) * dist, Math.cos(yaw) * Math.cos(pitch) * dist);
      cam.lookAt(0, n * 0.4, 0); r.render(scene, cam);
    };
    const loop = () => { if (dead) return; if (!drag) yaw += 0.003; draw(); raf = requestAnimationFrame(loop); };
    cv.addEventListener("pointerdown", (e) => { drag = [e.clientX, e.clientY]; cv.setPointerCapture(e.pointerId); });
    cv.addEventListener("pointermove", (e) => { if (!drag) return; yaw -= (e.clientX - drag[0]) * 0.01; pitch = clamp(pitch + (e.clientY - drag[1]) * 0.008, -0.2, 1.3); drag = [e.clientX, e.clientY]; });
    cv.addEventListener("pointerup", () => { drag = null; });
    cv.addEventListener("wheel", (e) => { e.preventDefault(); dist = clamp(dist * Math.pow(1.001, e.deltaY), n * 1.2, n * 5); }, { passive: false });
    loop();
    return { dispose() { dead = true; cancelAnimationFrame(raf); r.dispose(); geo.dispose(); mat.dispose(); cv.remove(); } };
  }

  // ================================================================== a time-lapse player
  // Builds the controls inside `box` for a v3 piece: play/pause, a scrubber over its marks, the word just made.
  function player(box, c) {
    const d = c.data || {}, medium = mediumOf(c);
    if (!medium || !d.ops) return null;
    const total = words(medium === "paint" ? PAINT : medium === "music" ? MUSIC : SCULPT, d.ops).length;
    box.innerHTML = `<div class="tl"><canvas class="tl-cv" width="${medium === "music" ? 1100 : 960}" height="${medium === "music" ? 260 : medium === "paint" ? 720 : 720}"></canvas>
      <div class="tl-bar"><button class="tl-play" aria-label="Play the time-lapse">▶</button>
      <input class="tl-scrub" type="range" min="0" max="${total}" value="0" aria-label="Scrub through the marks">
      <span class="tl-n">0 / ${total}</span><span class="tl-word"></span>
      <select class="tl-speed" aria-label="Speed"><option value="0.5">½×</option><option value="1" selected>1×</option><option value="3">3×</option></select></div></div>`;
    const cv = box.querySelector(".tl-cv"), btn = box.querySelector(".tl-play"), sc = box.querySelector(".tl-scrub"),
      lab = box.querySelector(".tl-n"), wd = box.querySelector(".tl-word"), sp = box.querySelector(".tl-speed");
    let i = 0, playing = false, last = 0, acc = 0, raf = 0, dead = false;
    const rate = medium === "paint" ? 40 : medium === "music" ? 6 : 18;   // words per second at 1×
    const show = () => {
      const s = replay(medium, d, i);
      if (medium === "paint") drawPixels(cv, s.px, s.w, s.h, d.palette, i < total ? { x: s.x, y: s.y, size: s.size, pen: s.pen, color: s.color } : null);
      else if (medium === "music") rollNotes(cv, s.notes, i < total);
      else drawVoxels(cv, s.vox, s.n, matColor(d), i < total ? { x: s.x, y: s.y, z: s.z } : null, 0.62 + i * 0.004);
      sc.value = i; lab.textContent = `${i} / ${total}`; wd.textContent = s.word ? `“${s.word}”` : "";
    };
    const tick = (t) => {
      if (dead) return;
      if (playing) {
        acc += Math.min(0.1, (t - last) / 1000) * rate * +sp.value; last = t;
        const k = Math.floor(acc); if (k > 0) { acc -= k; i = Math.min(total, i + k); show(); }
        if (i >= total) { playing = false; btn.textContent = "↺"; }
      }
      raf = requestAnimationFrame(tick);
    };
    btn.onclick = () => { if (i >= total) i = 0; playing = !playing; btn.textContent = playing ? "❚❚" : "▶"; last = performance.now(); acc = 0; show(); };
    sc.oninput = () => { i = +sc.value; playing = false; btn.textContent = "▶"; show(); };
    show(); raf = requestAnimationFrame(tick);
    return { dispose() { dead = true; cancelAnimationFrame(raf); } };
  }
  // a growing piano roll (for the time-lapse and the live studio)
  function rollNotes(cv, notes, cursor) {
    const g = cv.getContext("2d"), W = cv.width, H = cv.height;
    const bg = g.createLinearGradient(0, 0, 0, H); bg.addColorStop(0, "#151b2e"); bg.addColorStop(1, "#0d1120"); g.fillStyle = bg; g.fillRect(0, 0, W, H);
    const total = Math.max(16, notes.reduce((a, n) => a + n[1], 0) + (cursor ? 2 : 0)), ms = notes.filter((n) => n[0] > 0).map((n) => n[0]);
    const lo = Math.min(55, ...ms) - 2, hi = Math.max(76, ...ms) + 2, X = (b) => 6 + b / total * (W - 12), Y = (m) => H - 8 - (m - lo) / (hi - lo) * (H - 16);
    g.fillStyle = "rgba(255,255,255,.05)"; for (let m = lo; m <= hi; m++) if ([1, 3, 6, 8, 10].includes(m % 12)) g.fillRect(0, Y(m) - (H - 16) / (hi - lo) / 2, W, (H - 16) / (hi - lo));
    let t = 0;
    notes.forEach(([m, b], i) => {
      if (m > 0) { const x = X(t), w = Math.max(3, X(t + b) - x - 2), hh = Math.max(4, (H - 16) / (hi - lo) * 0.85), y = Y(m);
        g.fillStyle = i === notes.length - 1 && cursor ? "#fff3c8" : "#ffd678"; g.beginPath(); g.roundRect ? g.roundRect(x, y - hh / 2, w, hh, hh / 2) : g.rect(x, y - hh / 2, w, hh); g.fill(); }
      t += b;
    });
    if (cursor) { g.fillStyle = "rgba(255,255,255,.7)"; g.fillRect(X(t), 0, 2, H); }
    if (!notes.length) { g.fillStyle = "rgba(220,228,255,.55)"; g.font = `${Math.max(12, H / 12)}px system-ui`; g.textAlign = "center"; g.fillText("listening for the first note…", W / 2, H / 2); }
  }

  // ================================================================== live: the piece growing (snapshot `studio`)
  const live = { s: null, px: null, notes: [], vox: null, at: 0 };
  function setLive(st) {
    if (!st) { live.s = null; return; }
    live.s = Object.assign({}, live.s && live.s.medium === st.medium ? live.s : {}, st);
    if (st.pixels != null) live.px = pixelsOf({ pixels: st.pixels, w: st.w || 64, h: st.h || 48 });
    if (st.notes) live.notes = st.notes;
    if (st.voxels != null) live.vox = voxelsOf({ voxels: st.voxels, n: st.n || 12 });
    live.at = performance.now();
  }
  function mediumName(m) { return { paint: "painting", painting: "painting", compose: "composing", music: "composing", sculpt: "sculpting", sculpture: "sculpting", write: "writing", writing: "writing" }[m] || m; }
  const normMedium = (m) => ({ painting: "paint", compose: "music", music: "music", sculpture: "sculpt", writing: "write" }[m] || m);
  function drawLive(cv) {
    const s = live.s; if (!s) return;
    const m = normMedium(s.medium), cur = s.cursor || [];
    if (m === "paint") drawPixels(cv, live.px || new Int8Array((s.w || 64) * (s.h || 48)).fill(-1), s.w || 64, s.h || 48, s.palette,
      { x: cur[0] ?? 32, y: cur[1] ?? 24, size: s.size || 1, pen: !!s.pen, color: s.color ?? 0 });
    else if (m === "music") rollNotes(cv, live.notes || [], true);
    else if (m === "sculpt") drawVoxels(cv, live.vox || new Uint8Array(1728), s.n || 12, matColor(s), { x: cur[0] ?? 6, y: cur[1] ?? 0, z: cur[2] ?? 6 }, 0.62 + performance.now() / 9000);
    else { const g = cv.getContext("2d"); g.drawImage(paper(cv.width, cv.height), 0, 0); g.fillStyle = "#3a2f1e"; g.font = `italic ${Math.round(cv.height / 12)}px Georgia, serif`; g.fillText("✍️ …", 16, cv.height / 2); }
  }

  // ================================================================== Art learns the v3 formats
  function teach(Art) {
    if (!Art || Art._studio) return;
    Art._studio = true;
    const o = { paint: Art.paint, sculpt: Art.sculpt, sculpt2d: Art.sculpt2d, roll: Art.roll, play: Art.play, render: Art.render, paintLater: Art.paintLater };
    Art.paint = (cv, d) => (isV3(d) && d.pixels != null ? paint(cv, d) : o.paint(cv, d));
    Art.sculpt = (cv, d) => (isV3(d) && d.voxels != null ? sculpt(cv, d) : o.sculpt(cv, d));
    Art.sculpt2d = (cv, d) => (isV3(d) && d.voxels != null ? sculpt(cv, d) : o.sculpt2d(cv, d));
    Art.roll = (cv, d, at) => o.roll(cv, isV3(d) && d.notes ? song(d) : d, at);
    Art.play = (d, onEnd) => o.play(isV3(d) && d.notes ? song(d) : d, onEnd);
    Art.render = (d) => o.render(isV3(d) && d.notes ? song(d) : d);
    Art.paintLater = (cv, d, fn, done) => (isV3(d) ? (requestAnimationFrame(() => { const r = fn === o.paint || fn === Art.paint ? paint(cv, d) : fn(cv, d); Promise.resolve(r).then(() => done && done()); })) : o.paintLater(cv, d, fn, done));
  }
  if (window.Art) teach(window.Art);

  return { PAINT, MUSIC, SCULPT, PALETTE, SYM, words, replay, painter, composer, sculptor, pixelsOf, voxelsOf, drawPixels, drawVoxels, rollNotes,
    paint, sculpt, song, mountOrbit, player, mediumOf, setLive, drawLive, live, mediumName, normMedium, matColor, teach, isV3 };
})();
window.Studio = Studio;
