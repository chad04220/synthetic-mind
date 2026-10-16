"use strict";
// The valley's art, shown and played in the browser. Every work arrives as a small recipe (a scene, a
// palette and a seed; a melody; a stack of shapes) and is painted, played or drawn the same way every
// time, so a work lasts exactly as its maker left it.

const Art = (() => {
  function rng(seed) {             // mulberry32: the same seed paints the same picture
    let a = seed >>> 0;
    return () => { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
  }
  const mix = (a, b, f) => {
    const p = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
    const [x, y] = [p(a), p(b)];
    return `rgb(${x.map((v, i) => Math.round(v + (y[i] - v) * f)).join(",")})`;
  };

  // ------------------------------------------------------------------ paintings
  function paint(cv, d) {
    const g = cv.getContext("2d"), W = cv.width, H = cv.height, r = rng(d.seed || 1), pal = d.palette || [];
    const [s0, s1, s2, l0, l1, l2] = [...pal, "#8ecae6", "#ffffff", "#219ebc", "#55a630", "#ffd166", "#2d6a4f"].slice(0, 6);
    const style = d.style || "calm", el = new Set(d.elements || []);
    const brush = { calm: 1, gentle: 0.8, bold: 1.8, bright: 1.2, dreamy: 1.4, stormy: 1.6, playful: 1.1 }[style] || 1;
    const night = el.has("stars") && /night|evening/.test(d.subject || "");
    // sky
    const sky = g.createLinearGradient(0, 0, 0, H * 0.65);
    sky.addColorStop(0, s2); sky.addColorStop(0.55, s0); sky.addColorStop(1, s1);
    g.fillStyle = sky; g.fillRect(0, 0, W, H);
    const horizon = H * (0.48 + r() * 0.12);
    // sun or moon
    const cx = W * (0.15 + r() * 0.7), cy = horizon * (0.25 + r() * 0.35), cr = W * (0.05 + r() * 0.04);
    const glow = g.createRadialGradient(cx, cy, cr * 0.2, cx, cy, cr * 4);
    glow.addColorStop(0, night ? "rgba(255,255,230,.55)" : "rgba(255,240,200,.75)"); glow.addColorStop(1, "rgba(255,240,200,0)");
    g.fillStyle = glow; g.fillRect(0, 0, W, H);
    g.fillStyle = night ? "#fffbe6" : "#fff4c2"; g.beginPath(); g.arc(cx, cy, cr, 0, 7); g.fill();
    if (el.has("stars")) for (let i = 0; i < 90; i++) { g.fillStyle = `rgba(255,255,255,${0.3 + r() * 0.7})`; g.fillRect(r() * W, r() * horizon * 0.8, 1 + r() * 1.5, 1 + r() * 1.5); }
    // clouds / weather
    for (let i = 0; i < 4 + r() * 4; i++) {
      const x = r() * W, y = r() * horizon * 0.6, w = W * (0.12 + r() * 0.2);
      g.fillStyle = style === "stormy" ? "rgba(70,70,90,.45)" : "rgba(255,255,255,.35)";
      for (let k = 0; k < 5; k++) { g.beginPath(); g.ellipse(x + (k - 2) * w * 0.22, y + Math.sin(k) * 6, w * 0.25, w * 0.12, 0, 0, 7); g.fill(); }
    }
    // distant land
    const ridge = (base, amp, col, rough) => {
      g.fillStyle = col; g.beginPath(); g.moveTo(0, H);
      let y = base;
      for (let x = 0; x <= W; x += W / 40) { y = base - amp * (0.5 + 0.5 * Math.sin(x / W * 6 + r() * rough)) - r() * amp * 0.3; g.lineTo(x, y); }
      g.lineTo(W, H); g.fill();
    };
    if (el.has("peaks") || el.has("snow")) {
      g.fillStyle = mix(s2, "#5c677d", 0.6); g.beginPath(); g.moveTo(0, horizon);
      for (let x = 0; x <= W; x += W / 7) g.lineTo(x + W / 14, horizon - H * (0.18 + r() * 0.2)), g.lineTo(x + W / 7, horizon - H * 0.04);
      g.lineTo(W, H); g.lineTo(0, H); g.fill();
      g.fillStyle = "rgba(255,255,255,.8)";
      for (let x = 0; x <= W; x += W / 7) { const px = x + W / 14, py = horizon - H * (0.18 + r() * 0.2); g.beginPath(); g.moveTo(px, py); g.lineTo(px - W * 0.03, py + H * 0.06); g.lineTo(px + W * 0.03, py + H * 0.06); g.fill(); }
    }
    if (el.has("hills") || el.has("fields") || el.has("trees") || el.has("flowers")) ridge(horizon, H * 0.08, mix(l2, s2, 0.35), 2);
    // water
    const water = el.has("water") || el.has("pond");
    if (water) {
      const wy = horizon + H * 0.05, wg = g.createLinearGradient(0, wy, 0, H);
      wg.addColorStop(0, mix(s0, "#1d3557", 0.25)); wg.addColorStop(1, mix(s2, "#1d3557", 0.6));
      g.fillStyle = wg; g.fillRect(0, wy, W, H - wy);
      for (let i = 0; i < 60; i++) { g.strokeStyle = `rgba(255,255,255,${0.1 + r() * 0.25})`; g.lineWidth = 1 + r() * 2; const y = wy + r() * (H - wy); const x = r() * W; g.beginPath(); g.moveTo(x, y); g.lineTo(x + 10 + r() * 30, y); g.stroke(); }
      g.fillStyle = "rgba(255,244,194,.35)"; g.fillRect(cx - cr, wy, cr * 2, H - wy);   // the sun's path on the water
      if (el.has("boat")) { const bx = W * (0.2 + r() * 0.6), by = wy + (H - wy) * 0.4; g.fillStyle = "#6b4226"; g.beginPath(); g.moveTo(bx - 30, by); g.lineTo(bx + 30, by); g.lineTo(bx + 20, by + 10); g.lineTo(bx - 20, by + 10); g.fill(); g.fillStyle = "#f8f9fa"; g.beginPath(); g.moveTo(bx, by - 40); g.lineTo(bx, by - 2); g.lineTo(bx + 22, by - 4); g.fill(); }
    } else {
      const lg = g.createLinearGradient(0, horizon, 0, H);
      lg.addColorStop(0, l0); lg.addColorStop(1, l2);
      g.fillStyle = lg; g.fillRect(0, horizon + H * 0.04, W, H);
    }
    if (el.has("fields")) for (let i = 0; i < 8; i++) { g.strokeStyle = `rgba(0,0,0,.12)`; g.lineWidth = 3; g.beginPath(); g.moveTo(W * 0.5, horizon + 10); g.lineTo(i * W / 7, H); g.stroke(); }
    // things in the scene
    const tree = (x, y, s) => { g.fillStyle = "#5b3a1e"; g.fillRect(x - s * 0.08, y - s * 0.4, s * 0.16, s * 0.45); g.fillStyle = mix(l2, "#1b4332", r() * 0.5); g.beginPath(); g.arc(x, y - s * 0.55, s * 0.32, 0, 7); g.arc(x - s * 0.2, y - s * 0.42, s * 0.24, 0, 7); g.arc(x + s * 0.2, y - s * 0.42, s * 0.24, 0, 7); g.fill(); if (el.has("apples")) for (let k = 0; k < 4; k++) { g.fillStyle = "#d62828"; g.beginPath(); g.arc(x + (r() - 0.5) * s * 0.5, y - s * (0.4 + r() * 0.3), s * 0.04, 0, 7); g.fill(); } };
    if (el.has("trees")) for (let i = 0; i < 4 + r() * 6; i++) tree(r() * W, horizon + H * (0.12 + r() * 0.35), H * (0.18 + r() * 0.2));
    if (el.has("houses") || el.has("barn") || el.has("stalls")) for (let i = 0; i < 3 + r() * 3; i++) {
      const x = W * (0.08 + r() * 0.8), y = horizon + H * (0.1 + r() * 0.2), s = H * (0.12 + r() * 0.08);
      g.fillStyle = el.has("barn") && i === 0 ? "#9d0208" : ["#f2d0a4", "#cdb4db", "#ffe5a0", "#bde0fe"][i % 4]; g.fillRect(x, y - s, s * 1.2, s);
      g.fillStyle = ["#9c4a3a", "#5e548e", "#3d5a80", "#2a6f97"][i % 4]; g.beginPath(); g.moveTo(x - s * 0.1, y - s); g.lineTo(x + s * 0.6, y - s * 1.6); g.lineTo(x + s * 1.3, y - s); g.fill();
      g.fillStyle = night ? "#ffd166" : "#4a4e69"; g.fillRect(x + s * 0.2, y - s * 0.7, s * 0.25, s * 0.25);
    }
    if (el.has("flowers") || el.has("butterflies")) for (let i = 0; i < 70; i++) { g.fillStyle = ["#ff70a6", "#ffd670", "#ffffff", "#c77dff", "#ff9770"][Math.floor(r() * 5)]; g.beginPath(); g.arc(r() * W, horizon + H * 0.1 + r() * H * 0.45, 2 + r() * 4, 0, 7); g.fill(); }
    if (el.has("crystals")) { g.fillStyle = "#14213d"; g.fillRect(0, 0, W, H); for (let i = 0; i < 18; i++) { const x = r() * W, y = H * (0.4 + r() * 0.6), h = 20 + r() * 60; g.fillStyle = `hsla(${180 + r() * 60},90%,${60 + r() * 20}%,.85)`; g.beginPath(); g.moveTo(x, y); g.lineTo(x + 8, y - h); g.lineTo(x + 16, y); g.fill(); } }
    if (el.has("window")) { g.fillStyle = "#7f5539"; g.fillRect(0, 0, W, H); g.fillStyle = sky; g.fillRect(W * 0.25, H * 0.15, W * 0.5, H * 0.45); g.strokeStyle = "#5b3a1e"; g.lineWidth = 8; g.strokeRect(W * 0.25, H * 0.15, W * 0.5, H * 0.45); g.beginPath(); g.moveTo(W * 0.5, H * 0.15); g.lineTo(W * 0.5, H * 0.6); g.stroke(); g.fillStyle = "#ffd166"; g.beginPath(); g.arc(W * 0.82, H * 0.7, 18, 0, 7); g.fill(); }
    if (el.has("glow")) { const gg = g.createRadialGradient(W / 2, horizon, 10, W / 2, horizon, W * 0.4); gg.addColorStop(0, "rgba(199,125,255,.7)"); gg.addColorStop(1, "rgba(199,125,255,0)"); g.fillStyle = gg; g.fillRect(0, 0, W, H); }
    if (el.has("rain")) for (let i = 0; i < 160; i++) { g.strokeStyle = "rgba(200,220,255,.35)"; g.lineWidth = 1; const x = r() * W, y = r() * H; g.beginPath(); g.moveTo(x, y); g.lineTo(x - 4, y + 14); g.stroke(); }
    if (el.has("snow")) for (let i = 0; i < 120; i++) { g.fillStyle = "rgba(255,255,255,.85)"; g.beginPath(); g.arc(r() * W, r() * H, 1 + r() * 2.5, 0, 7); g.fill(); }
    // brushwork over everything: the painter's hand
    const img = g.getImageData(0, 0, W, H).data;          // sample the picture once, then stroke over it
    for (let i = 0; i < 900 * brush; i++) {
      const x = r() * W, y = r() * H, o = ((Math.min(H - 1, y | 0) * W) + Math.min(W - 1, x | 0)) * 4;
      g.strokeStyle = `rgba(${img[o]},${img[o + 1]},${img[o + 2]},${0.25 + r() * 0.35})`; g.lineWidth = (1.5 + r() * 4) * brush;
      const a = (style === "stormy" ? 0.8 : style === "dreamy" ? 2.4 : 0) + r() * 0.8, len = (6 + r() * 14) * brush;
      g.beginPath(); g.moveTo(x, y); g.lineTo(x + Math.cos(a) * len, y + Math.sin(a) * len); g.stroke();
    }
    if (style === "dreamy") { g.fillStyle = "rgba(255,200,255,.12)"; g.fillRect(0, 0, W, H); }
    const vg = g.createRadialGradient(W / 2, H / 2, W * 0.3, W / 2, H / 2, W * 0.75);
    vg.addColorStop(0, "rgba(0,0,0,0)"); vg.addColorStop(1, "rgba(0,0,0,.28)"); g.fillStyle = vg; g.fillRect(0, 0, W, H);
  }

  // ------------------------------------------------------------------ music
  let ctx = null, playing = null;
  function play(d, onEnd) {
    stop();
    ctx = ctx || new (window.AudioContext || window.webkitAudioContext)();
    const beat = 60 / (d.tempo || 108), master = ctx.createGain();
    master.gain.value = 0.22; master.connect(ctx.destination);
    const verb = ctx.createDelay(); verb.delayTime.value = 0.18; const fb = ctx.createGain(); fb.gain.value = 0.25;
    verb.connect(fb); fb.connect(verb); verb.connect(master);
    let t = ctx.currentTime + 0.05;
    const nodes = [];
    for (const [pitch, beats] of d.notes || []) {
      const len = beats * beat;
      if (pitch > 0) {
        const f = 440 * 2 ** ((pitch - 69) / 12), env = ctx.createGain();
        env.gain.setValueAtTime(0, t); env.gain.linearRampToValueAtTime(1, t + 0.01); env.gain.exponentialRampToValueAtTime(0.25, t + 0.25);
        env.gain.exponentialRampToValueAtTime(0.001, t + len + 0.4);
        for (const [type, mult, vol] of [["triangle", 1, 0.7], ["sine", 2, 0.25], ["sine", 3, 0.08]]) {
          const o = ctx.createOscillator(), v = ctx.createGain(); o.type = type; o.frequency.value = f * mult; v.gain.value = vol;
          o.connect(v); v.connect(env); o.start(t); o.stop(t + len + 0.5); nodes.push(o);
        }
        env.connect(master); env.connect(verb);
      }
      t += len;
    }
    const end = setTimeout(() => { playing = null; onEnd && onEnd(); }, (t - ctx.currentTime) * 1000 + 600);
    playing = { nodes, end, master, onEnd };
    return playing;
  }
  function stop() {
    if (!playing) return;
    clearTimeout(playing.end);
    for (const n of playing.nodes) try { n.stop(); } catch { /* already stopped */ }
    playing.master.disconnect();
    const cb = playing.onEnd; playing = null; cb && cb();
  }

  // ------------------------------------------------------------------ sculptures
  function sculpt(cv, d) {
    const g = cv.getContext("2d"), W = cv.width, H = cv.height, cols = d.colors || ["#a8a29e", "#d6d3d1", "#78716c"];
    const bg = g.createLinearGradient(0, 0, 0, H); bg.addColorStop(0, "#1f2937"); bg.addColorStop(1, "#111827");
    g.fillStyle = bg; g.fillRect(0, 0, W, H);
    const scale = H * 0.62 / Math.max(0.6, d.height || 1), base = H * 0.86, cx = W / 2;
    g.fillStyle = "#374151"; g.fillRect(cx - W * 0.22, base, W * 0.44, H * 0.06);
    g.fillStyle = "rgba(0,0,0,.35)"; g.beginPath(); g.ellipse(cx, base, W * 0.2, H * 0.03, 0, 0, 7); g.fill();
    for (const p of d.parts || []) {
      const w = p.w * scale, h = p.h * scale, y = base - p.y * scale, x = cx + (p.x || 0) * scale;
      const grad = g.createLinearGradient(x - w / 2, 0, x + w / 2, 0);
      grad.addColorStop(0, cols[1]); grad.addColorStop(0.55, cols[0]); grad.addColorStop(1, cols[2]);
      g.fillStyle = grad; g.save(); g.translate(x, y); g.rotate(Math.sin(p.rot || 0) * 0.12); g.beginPath();
      if (p.shape === "sphere") g.ellipse(0, 0, w / 2, h / 2, 0, 0, 7);
      else if (p.shape === "cone") { g.moveTo(-w / 2, h / 2); g.lineTo(0, -h / 2); g.lineTo(w / 2, h / 2); }
      else if (p.shape === "torus") { g.ellipse(0, 0, w / 2, h / 2, 0, 0, 7); g.ellipse(0, 0, w / 4, h / 4, 0, 0, 7, true); }
      else if (p.shape === "octahedron") { g.moveTo(0, -h / 2); g.lineTo(w / 2, 0); g.lineTo(0, h / 2); g.lineTo(-w / 2, 0); }
      else if (p.shape === "cylinder") { g.ellipse(0, -h / 2, w / 2, w / 8, 0, Math.PI, 0); g.lineTo(w / 2, h / 2); g.ellipse(0, h / 2, w / 2, w / 8, 0, 0, Math.PI); }
      else g.rect(-w / 2, -h / 2, w, h);
      g.fill("evenodd"); g.strokeStyle = "rgba(0,0,0,.25)"; g.lineWidth = 1.5; g.stroke(); g.restore();
    }
    const hl = g.createRadialGradient(cx - W * 0.1, H * 0.25, 5, cx, H * 0.4, W * 0.5);
    hl.addColorStop(0, "rgba(255,255,255,.12)"); hl.addColorStop(1, "rgba(255,255,255,0)"); g.fillStyle = hl; g.fillRect(0, 0, W, H);
  }

  return { paint, play, stop, sculpt, isPlaying: () => !!playing };
})();
window.Art = Art;
