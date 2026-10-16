"use strict";
// The Atlas: everything Zen has explored of its endless world, as a map. The explored chunks come from
// /api/atlas (refreshed every 5 s while the tab is open); close up, each explored chunk is drawn tile by
// tile from its chunk payload (fetched once, cached in window.Chunks). Pan with the mouse or a finger,
// zoom with the wheel or a pinch.

const Atlas = (() => {
  const N = 32;
  const st = { data: null, view: { x: 0, y: 0, s: 2 }, fitted: false, timer: null, open: false, ptrs: new Map(), drag: null, pinch: null,
               hover: null, dirty: true, raf: 0, fog: null, follow: true, loading: false, err: "" };
  const $ = (s) => document.querySelector(s);
  const cv = $("#atlasCanvas"), g = cv.getContext("2d");
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  async function refresh() {
    if (st.loading) return;
    st.loading = true;
    try {
      const r = await fetch("/api/atlas"); if (!r.ok) throw new Error(r.statusText);
      st.data = await r.json(); st.err = "";
      if (!st.fitted) fit();
      else if (st.follow && st.data.zen) { st.view.x = st.data.zen.x + 0.5; st.view.y = st.data.zen.y + 0.5; }
      await Chunks.meta().catch(() => null);
      st.dirty = true; panel();
    } catch (e) { st.err = `Couldn't load the atlas: ${e.message}`; panel(); }
    st.loading = false;
  }
  function fit() {
    const d = st.data; if (!d || !cv.clientWidth) return;
    const ex = d.explored || [];
    let x0 = d.zen?.x ?? 0, x1 = x0, y0 = d.zen?.y ?? 0, y1 = y0;
    for (const [cx, cy] of ex) { x0 = Math.min(x0, cx * N); x1 = Math.max(x1, cx * N + N); y0 = Math.min(y0, cy * N); y1 = Math.max(y1, cy * N + N); }
    const pad = N;
    st.view.x = (x0 + x1) / 2; st.view.y = (y0 + y1) / 2;
    st.view.s = Math.max(0.25, Math.min(8, Math.min(cv.clientWidth / (x1 - x0 + pad * 2), cv.clientHeight / (y1 - y0 + pad * 2))));
    st.fitted = true; st.follow = false;
  }
  // the fog of the unknown: a soft cloudy texture, made once
  function fogPattern(dark) {
    if (st.fog && st.fog.dark === dark) return st.fog.pat;
    const c = document.createElement("canvas"); c.width = c.height = 256;
    const x = c.getContext("2d"), im = x.createImageData(256, 256), D = im.data;
    const h = (i, j) => { let k = Math.imul(i & 255, 374761393) ^ Math.imul(j & 255, 668265263); k = Math.imul(k ^ (k >>> 13), 1274126177); return ((k ^ (k >>> 16)) >>> 0) / 4294967296; };
    const vn = (u, v, f) => { const i = Math.floor(u * f), j = Math.floor(v * f), a = u * f - i, b = v * f - j, s = (t) => t * t * (3 - 2 * t);
      const m = f; const q = (ii, jj) => h(((ii % m) + m) % m * 7 + 3, ((jj % m) + m) % m * 13 + 5);
      return q(i, j) * (1 - s(a)) * (1 - s(b)) + q(i + 1, j) * s(a) * (1 - s(b)) + q(i, j + 1) * (1 - s(a)) * s(b) + q(i + 1, j + 1) * s(a) * s(b); };
    for (let j = 0; j < 256; j++) for (let i = 0; i < 256; i++) {
      const u = i / 256, v = j / 256, n = vn(u, v, 4) * 0.5 + vn(u, v, 8) * 0.3 + vn(u, v, 16) * 0.2, o = (j * 256 + i) * 4;
      const base = dark ? [22, 28, 42] : [222, 226, 232], k = dark ? 26 : 20;
      D[o] = base[0] + n * k; D[o + 1] = base[1] + n * k; D[o + 2] = base[2] + n * k * 1.2; D[o + 3] = 255;
    }
    x.putImageData(im, 0, 0);
    st.fog = { dark, pat: g.createPattern(c, "repeat") };
    return st.fog.pat;
  }
  const isDark = () => getComputedStyle(document.documentElement).getPropertyValue("color-scheme").trim() !== "light";

  function draw() {
    const dpr = devicePixelRatio || 1, W = Math.round(cv.clientWidth * dpr), H = Math.round(cv.clientHeight * dpr);
    if (!W || !H) return;
    if (cv.width !== W || cv.height !== H) { cv.width = W; cv.height = H; }
    const d = st.data, v = st.view, s = v.s * dpr, dark = isDark();
    const X = (x) => (x - v.x) * s + W / 2, Y = (y) => (y - v.y) * s + H / 2;
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.fillStyle = fogPattern(dark); g.fillRect(0, 0, W, H);
    if (!d) return;
    const B = Chunks.st.meta?.BIOMES || [];
    const ex = d.explored || [], set = new Set(ex.map(([cx, cy]) => cx + "," + cy));
    const tilesOk = v.s >= 1.2;          // close enough to see tiles: draw chunk pictures
    g.imageSmoothingEnabled = v.s < 3;
    let wanted = 0;
    for (const [cx, cy, bi] of ex) {
      const x = X(cx * N), y = Y(cy * N), w = N * s;
      if (x > W || y > H || x + w < 0 || y + w < 0) continue;
      const im = tilesOk ? Chunks.image(cx, cy) : null;
      if (im) g.drawImage(im, x, y, w + 0.6, w + 0.6);
      else {
        g.fillStyle = Chunks.hex(B[bi] || ""); g.fillRect(x, y, w + 0.6, w + 0.6);
        if (tilesOk && wanted < 24) { wanted++; Chunks.get(cx, cy).then(() => { st.dirty = true; }).catch(() => {}); }
      }
    }
    // soft edges where the known meets the unknown
    g.save(); g.filter = `blur(${Math.max(2, Math.min(14, N * s * 0.12))}px)`; g.fillStyle = fogPattern(dark); g.globalAlpha = 0.85;
    for (const [cx, cy] of ex) for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
      if (set.has(cx + dx + "," + (cy + dy))) continue;
      const x = X((cx + dx) * N), y = Y((cy + dy) * N), w = N * s;
      if (x > W + w || y > H + w || x + 2 * w < 0 || y + 2 * w < 0) continue;
      g.fillRect(x - (dx < 0 ? 0 : 0), y, w, w);
    }
    g.restore();
    // a faint chunk grid when close
    if (v.s > 2.5) {
      g.strokeStyle = dark ? "rgba(255,255,255,.06)" : "rgba(0,0,0,.06)"; g.lineWidth = 1; g.beginPath();
      const gx0 = Math.floor((v.x - W / 2 / s) / N), gx1 = Math.ceil((v.x + W / 2 / s) / N), gy0 = Math.floor((v.y - H / 2 / s) / N), gy1 = Math.ceil((v.y + H / 2 / s) / N);
      for (let i = gx0; i <= gx1; i++) { g.moveTo(X(i * N), 0); g.lineTo(X(i * N), H); }
      for (let j = gy0; j <= gy1; j++) { g.moveTo(0, Y(j * N)); g.lineTo(W, Y(j * N)); }
      g.stroke();
    }
    // Zen's trail
    const tr = d.trail || [];
    if (tr.length > 1) {
      g.lineJoin = "round"; g.lineCap = "round";
      g.strokeStyle = "rgba(20,16,40,.35)"; g.lineWidth = Math.max(2, Math.min(5, s * 0.5)) + 2 * dpr; g.beginPath();
      tr.forEach(([x, y], i) => i ? g.lineTo(X(x + 0.5), Y(y + 0.5)) : g.moveTo(X(x + 0.5), Y(y + 0.5))); g.stroke();
      const grd = g.createLinearGradient(X(tr[0][0]), Y(tr[0][1]), X(tr.at(-1)[0]), Y(tr.at(-1)[1]));
      grd.addColorStop(0, "rgba(255,214,140,.35)"); grd.addColorStop(1, "rgba(255,230,170,.95)");
      g.strokeStyle = grd; g.lineWidth = Math.max(1.5, Math.min(4, s * 0.4)) * dpr; g.setLineDash([6 * dpr, 4 * dpr]); g.beginPath();
      tr.forEach(([x, y], i) => i ? g.lineTo(X(x + 0.5), Y(y + 0.5)) : g.moveTo(X(x + 0.5), Y(y + 0.5))); g.stroke(); g.setLineDash([]);
    }
    // places
    g.textAlign = "center"; g.textBaseline = "middle";
    const places = (d.places || []).slice();
    if (d.home && !places.some((p) => p.kind === "home")) places.push({ kind: "home", name: "Home", x: d.home.x, y: d.home.y });
    const placed = [];
    for (const p of places) {
      const x = X(p.x + 0.5), y = Y(p.y + 0.5); if (x < -60 || y < -30 || x > W + 60 || y > H + 30) continue;
      const home = p.kind === "home", r = (home ? 13 : 10) * dpr;
      g.fillStyle = home ? "rgba(255,240,220,.95)" : "rgba(255,255,255,.88)"; g.strokeStyle = "rgba(0,0,0,.35)"; g.lineWidth = 1.5 * dpr;
      g.beginPath(); g.arc(x, y, r, 0, 7); g.fill(); g.stroke();
      g.font = `${Math.round(r * 1.15)}px ${EMOJI_FONT}`; g.fillStyle = "#000"; g.fillText(PLACE_ICON[p.kind] || "📍", x, y + dpr);
      if (v.s > 0.6 || home) {
        const label = home ? "Home" : p.name;
        g.font = `650 ${Math.round(11.5 * dpr)}px system-ui, sans-serif`;
        const tw = g.measureText(label).width + 10 * dpr, ly = y + r + 10 * dpr;
        if (!placed.some((q) => Math.abs(q[0] - x) < (q[2] + tw) / 2 && Math.abs(q[1] - ly) < 16 * dpr)) {
          placed.push([x, ly, tw]);
          g.fillStyle = dark ? "rgba(14,20,34,.78)" : "rgba(255,255,255,.85)"; g.beginPath(); g.roundRect(x - tw / 2, ly - 9 * dpr, tw, 18 * dpr, 9 * dpr); g.fill();
          g.fillStyle = dark ? "#e7ecf5" : "#19212f"; g.fillText(label, x, ly + 0.5 * dpr);
        }
      }
    }
    // Zen, now
    if (d.zen) {
      const x = X(d.zen.x + 0.5), y = Y(d.zen.y + 0.5), t = performance.now() / 1000, r = 7 * dpr;
      const pr = r * (2.2 + 0.8 * Math.sin(t * 2.5));
      const gl = g.createRadialGradient(x, y, 0, x, y, pr * 1.6); gl.addColorStop(0, "rgba(160,150,255,.6)"); gl.addColorStop(1, "rgba(124,156,255,0)");
      g.fillStyle = gl; g.beginPath(); g.arc(x, y, pr * 1.6, 0, 7); g.fill();
      const og = g.createRadialGradient(x - r * 0.3, y - r * 0.3, r * 0.1, x, y, r); og.addColorStop(0, "#fff"); og.addColorStop(0.45, "#9fb4ff"); og.addColorStop(1, "#7a52e0");
      g.fillStyle = og; g.beginPath(); g.arc(x, y, r, 0, 7); g.fill(); g.strokeStyle = "#fff"; g.lineWidth = 2 * dpr; g.stroke();
    }
    // scale bar
    const tiles = [8, 16, 32, 64, 128, 256, 512, 1024].find((n) => n * s > 70 * dpr) || 1024;
    g.fillStyle = dark ? "rgba(231,236,245,.85)" : "rgba(25,33,47,.85)"; g.fillRect(14 * dpr, H - 18 * dpr, tiles * s, 3 * dpr);
    g.font = `600 ${Math.round(11 * dpr)}px system-ui`; g.textAlign = "left"; g.fillText(`${tiles} tiles`, 14 * dpr, H - 28 * dpr);
  }
  function loop() {
    st.raf = 0;
    if (!st.open) return;
    if (st.dirty || st.data?.zen) { draw(); st.dirty = false; }
    st.raf = setTimeout(() => requestAnimationFrame(loop), st.dirty ? 16 : 120);
  }

  function panel() {
    const d = st.data;
    const box = $("#atlasStats"); if (!box) return;
    if (st.err) { box.innerHTML = `<div class="muted">${esc(st.err)}</div>`; return; }
    if (!d) { box.innerHTML = `<div class="muted">Loading the map…</div>`; return; }
    const ex = d.explored || [], home = d.home || { x: 0, y: 0 }, far = d.zen ? Math.round(Math.hypot(d.zen.x - home.x, d.zen.y - home.y)) : 0;
    const places = (d.places || []).filter((p) => p.kind !== "home");
    box.innerHTML = `<div class="astat"><b>${ex.length}</b><span>chunks explored</span></div>
      <div class="astat"><b>${places.length}</b><span>places found</span></div>
      <div class="astat"><b>${far}</b><span>tiles from home</span></div>
      <div class="astat"><b>${(d.trail || []).length}</b><span>steps on the trail</span></div>`;
    const B = Chunks.st.meta?.BIOMES || [], counts = new Map();
    for (const [, , b] of ex) counts.set(b, (counts.get(b) || 0) + 1);
    const leg = [...counts].sort((a, b) => b[1] - a[1]).map(([b, n]) => `<span class="lg"><i style="background:${Chunks.hex(B[b] || "")}"></i>${esc(Chunks.label(B[b] || "?"))} <small>${n}</small></span>`).join("");
    const lg = $("#atlasLegend"); if (lg && lg._h !== leg) { lg._h = leg; lg.innerHTML = leg || '<span class="muted">Nothing explored yet.</span>'; }
    const pl = $("#atlasPlaces");
    if (pl) {
      const html = places.length ? places.slice().reverse().map((p) => `<button class="aplace" data-ax="${p.x}" data-ay="${p.y}"><span>${PLACE_ICON[p.kind] || "📍"}</span><b>${esc(p.name)}</b><small>${Math.round(Math.hypot(p.x - home.x, p.y - home.y))} tiles from home</small></button>`).join("")
        : '<div class="muted">No named places yet. Ruins, caves, springs and standing stones appear here once Zen comes upon them.</div>';
      if (pl._h !== html) { pl._h = html; pl.innerHTML = html; }
    }
  }

  // ---- input: pan, zoom, pinch, hover
  const toWorld = (px, py) => { const r = cv.getBoundingClientRect(), v = st.view; return [v.x + (px - r.left - r.width / 2) / v.s, v.y + (py - r.top - r.height / 2) / v.s]; };
  function zoomAt(f, px, py) {
    const [wx, wy] = toWorld(px, py), v = st.view, ns = Math.max(0.12, Math.min(24, v.s * f)), r = cv.getBoundingClientRect();
    v.s = ns; v.x = wx - (px - r.left - r.width / 2) / ns; v.y = wy - (py - r.top - r.height / 2) / ns; st.dirty = true; st.follow = false;
  }
  cv.addEventListener("wheel", (e) => { e.preventDefault(); zoomAt(Math.pow(1.0018, -e.deltaY * (e.deltaMode === 1 ? 30 : 1)), e.clientX, e.clientY); }, { passive: false });
  cv.addEventListener("pointerdown", (e) => {
    st.ptrs.set(e.pointerId, [e.clientX, e.clientY]); cv.setPointerCapture(e.pointerId);
    if (st.ptrs.size === 2) { const [a, b] = [...st.ptrs.values()]; st.pinch = { d: Math.hypot(a[0] - b[0], a[1] - b[1]), s: st.view.s }; st.drag = null; }
    else st.drag = [e.clientX, e.clientY];
  });
  cv.addEventListener("pointermove", (e) => {
    if (st.ptrs.has(e.pointerId)) st.ptrs.set(e.pointerId, [e.clientX, e.clientY]);
    if (st.pinch && st.ptrs.size === 2) { const [a, b] = [...st.ptrs.values()], d = Math.hypot(a[0] - b[0], a[1] - b[1]);
      zoomAt(st.pinch.s * d / st.pinch.d / st.view.s, (a[0] + b[0]) / 2, (a[1] + b[1]) / 2); return; }
    if (st.drag) { st.view.x -= (e.clientX - st.drag[0]) / st.view.s; st.view.y -= (e.clientY - st.drag[1]) / st.view.s; st.drag = [e.clientX, e.clientY]; st.dirty = true; st.follow = false; return; }
    hover(e);
  });
  const end = (e) => { st.ptrs.delete(e.pointerId); if (st.ptrs.size < 2) st.pinch = null; if (!st.ptrs.size) st.drag = null; };
  cv.addEventListener("pointerup", end); cv.addEventListener("pointercancel", end);
  cv.addEventListener("pointerleave", () => { const t = $("#atlasTip"); if (t) t.hidden = true; });
  function hover(e) {
    const t = $("#atlasTip"); if (!t || !st.data) return;
    const [wx, wy] = toWorld(e.clientX, e.clientY), x = Math.floor(wx), y = Math.floor(wy), cx = Math.floor(x / N), cy = Math.floor(y / N);
    const ex = (st.data.explored || []).find((c) => c[0] === cx && c[1] === cy);
    const place = (st.data.places || []).find((p) => Math.abs(p.x - x) <= Math.max(2, 6 / st.view.s) && Math.abs(p.y - y) <= Math.max(2, 6 / st.view.s));
    let html = "";
    if (place) html = `<b>${PLACE_ICON[place.kind] || "📍"} ${esc(place.name)}</b>`;
    if (ex) { const ti = Chunks.tile(x, y), B = Chunks.st.meta?.BIOMES || [], F = Chunks.st.meta?.FEATURES || [];
      const bn = ti ? B[ti.biome] : B[ex[2]];
      html += `${html ? "<br>" : ""}${esc(Chunks.label(bn || ""))}${ti?.water ? ` · ${["", "shallow water", "deep water", "a river"][ti.water]}` : ""}${ti?.feat ? ` · ${esc(String(F[ti.feat] || "").replace(/_/g, " "))}` : ""}${ti ? ` · ${(ti.h / 10).toFixed(0)} m` : ""}`; }
    else if (!html) html = '<span class="muted">unexplored</span>';
    t.innerHTML = html + `<small>${x}, ${y}</small>`; t.hidden = false;
    const r = cv.parentElement.getBoundingClientRect();
    t.style.transform = `translate(${Math.min(r.width - 180, e.clientX - r.left + 14)}px, ${e.clientY - r.top + 14}px)`;
  }
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-atlas],[data-ax]"); if (!b) return;
    if (b.dataset.ax) { st.view.x = +b.dataset.ax + 0.5; st.view.y = +b.dataset.ay + 0.5; st.view.s = Math.max(st.view.s, 3); st.follow = false; }
    else if (b.dataset.atlas === "zen" && st.data?.zen) { st.view.x = st.data.zen.x + 0.5; st.view.y = st.data.zen.y + 0.5; st.view.s = Math.max(st.view.s, 3); st.follow = true; }
    else if (b.dataset.atlas === "home") { const h = st.data?.home || { x: 0, y: 0 }; st.view.x = h.x + 0.5; st.view.y = h.y + 0.5; st.follow = false; }
    else if (b.dataset.atlas === "fit") fit();
    else if (b.dataset.atlas === "in") { const r = cv.getBoundingClientRect(); zoomAt(1.5, r.left + r.width / 2, r.top + r.height / 2); }
    else if (b.dataset.atlas === "out") { const r = cv.getBoundingClientRect(); zoomAt(1 / 1.5, r.left + r.width / 2, r.top + r.height / 2); }
    st.dirty = true;
  });
  addEventListener("resize", () => { st.dirty = true; });

  function open() {
    if (st.open) return;
    st.open = true; refresh(); panel();
    st.timer = setInterval(() => { if (!document.hidden) refresh(); }, 5000);
    loop();
  }
  function close() { st.open = false; clearInterval(st.timer); st.timer = null; }
  return { open, close, refresh, st };
})();
window.Atlas = Atlas;
