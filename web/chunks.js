"use strict";
// The endless world's terrain, fetched a chunk (32×32 tiles) at a time from /api/chunk and kept in one
// shared cache for the 3D view, the minimap and the Atlas. Also the shared biome palette.

const Chunks = (() => {
  const N = 32;
  const BIOME_HEX = {
    ocean: "#2f6f9f", lake: "#3f8fb8", beach: "#e6d49c", meadow: "#8fc466", grassland: "#adc46c", forest: "#4f8f41",
    pine_forest: "#3d6b4b", jungle: "#2e8a4c", swamp: "#62785a", desert: "#e2c48a", savanna: "#cbb866", tundra: "#a9b5a3",
    snow: "#eef3f8", mountain: "#8c8780", rock: "#a0978b",
  };
  const BIOME_LABEL = { pine_forest: "Pine forest" };
  const st = { meta: null, metaP: null, cache: new Map(), pending: new Map(), queue: [], inflight: 0, images: new Map(), listeners: new Set(), errors: 0 };
  const key = (cx, cy) => cx + "," + cy;

  function meta() {
    if (st.meta) return Promise.resolve(st.meta);
    if (!st.metaP) {
      st.metaP = fetch("/api/world_meta").then((r) => { if (!r.ok) throw new Error(r.statusText); return r.json(); })
        .then((m) => { st.meta = m; return m; })
        .catch((e) => { st.metaP = null; throw e; });
    }
    return st.metaP;
  }

  function decode(j) {
    const n = (j.size || N) * (j.size || N);
    const c = { cx: j.cx, cy: j.cy, size: j.size || N, h: Int16Array.from(j.h || new Array(n).fill(0)), biome: Uint8Array.from(j.biome || []),
      water: Uint8Array.from(j.water || []), feat: Uint8Array.from(j.feat || []), pois: (j.meta && j.meta.pois) || [], v: 1 };
    return c;
  }

  function pump() {
    while (st.inflight < 4 && st.queue.length) {
      const job = st.queue.shift();
      if (st.cache.has(job.k)) { job.resolve(st.cache.get(job.k)); continue; }
      st.inflight++;
      fetch(`/api/chunk?cx=${job.cx}&cy=${job.cy}`).then((r) => { if (!r.ok) throw new Error(r.statusText); return r.json(); })
        .then((j) => {
          const c = decode(j); st.cache.set(job.k, c); st.images.delete(job.k);
          job.resolve(c);
          for (const f of st.listeners) try { f(c); } catch (e) { console.error(e); }
        })
        .catch((e) => { st.errors++; job.reject(e); })
        .finally(() => { st.inflight--; st.pending.delete(job.k); pump(); });
    }
  }

  // a promise of the chunk; `urgent` puts it at the front of the queue
  function get(cx, cy, urgent = false) {
    const k = key(cx, cy);
    const have = st.cache.get(k); if (have) return Promise.resolve(have);
    let p = st.pending.get(k);
    if (p) {
      if (urgent) { const i = st.queue.findIndex((j) => j.k === k); if (i > 0) st.queue.unshift(st.queue.splice(i, 1)[0]); }
      return p;
    }
    p = new Promise((resolve, reject) => { const job = { k, cx, cy, resolve, reject }; urgent ? st.queue.unshift(job) : st.queue.push(job); });
    p.catch(() => {});
    st.pending.set(k, p); pump();
    return p;
  }
  function peek(cx, cy) { return st.cache.get(key(cx, cy)); }
  function tile(x, y) {
    const cx = Math.floor(x / N), cy = Math.floor(y / N), c = st.cache.get(key(cx, cy));
    if (!c) return null;
    const i = (y - cy * N) * N + (x - cx * N);
    return { h: c.h[i], biome: c.biome[i], water: c.water[i], feat: c.feat[i] };
  }
  // keep the cache small: drop chunks far from every point of interest
  function trim(centres, keep = 9) {
    if (st.cache.size < 420) return;
    for (const [k, c] of st.cache) {
      if (!centres.some(([x, y]) => Math.abs(c.cx - x) <= keep && Math.abs(c.cy - y) <= keep)) { st.cache.delete(k); st.images.delete(k); }
    }
  }
  function biomeName(i) { return st.meta?.BIOMES?.[i] ?? ""; }
  function featName(i) { return st.meta?.FEATURES?.[i] ?? ""; }
  function label(name) { return BIOME_LABEL[name] || (name ? name[0].toUpperCase() + name.slice(1).replace(/_/g, " ") : ""); }
  function hex(name) { return BIOME_HEX[name] || "#8a9a7a"; }
  const rgbOf = new Map();
  function rgb(name) {
    let c = rgbOf.get(name); if (c) return c;
    const h = hex(name).slice(1); c = [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
    rgbOf.set(name, c); return c;
  }

  // a 32×32 picture of a chunk (one pixel a tile): biome colour, hill shading, water by depth, trees darker
  function image(cx, cy) {
    const k = key(cx, cy), c = st.cache.get(k); if (!c) return null;
    let im = st.images.get(k); if (im) return im;
    const n = c.size, cv = document.createElement("canvas"); cv.width = cv.height = n;
    const g = cv.getContext("2d"), d = g.createImageData(n, n), B = st.meta?.BIOMES || [], F = st.meta?.FEATURES || [];
    const hAt = (i, j) => { i = Math.max(0, Math.min(n - 1, i)); j = Math.max(0, Math.min(n - 1, j)); return c.h[j * n + i]; };
    for (let j = 0; j < n; j++) for (let i = 0; i < n; i++) {
      const t = j * n + i, w = c.water[t], bn = B[c.biome[t]] || "";
      let [r, gg, b] = rgb(w ? (bn === "ocean" ? "ocean" : "lake") : bn);
      if (w) {
        const f = w === 2 ? 0.72 : w === 3 ? 1.05 : 1.12; r *= f; gg *= f; b *= f;
        if (w === 1) { r = r * 0.8 + 40; gg = gg * 0.85 + 34; }
      } else {
        const sl = (hAt(i - 1, j) - hAt(i + 1, j)) * 0.9 + (hAt(i, j - 1) - hAt(i, j + 1)) * 0.6;
        const sh = Math.max(0.72, Math.min(1.25, 1 + sl * 0.012));
        r *= sh; gg *= sh; b *= sh;
        const fn = F[c.feat[t]] || "";
        if (/oak|birch|pine|palm|jungle|tree|cactus/.test(fn)) { r *= 0.66; gg *= 0.78; b *= 0.66; }
        else if (/bush/.test(fn)) { r *= 0.8; gg *= 0.88; b *= 0.8; }
        else if (/rock|boulder/.test(fn)) { r = r * 0.6 + 50; gg = gg * 0.6 + 48; b = b * 0.6 + 46; }
        else if (/flower/.test(fn)) { r = r * 0.85 + 30; b = b * 0.9 + 12; }
        if (c.h[t] > 1000 && bn !== "desert") { const s = Math.min(1, (c.h[t] - 1000) / 150); r += (238 - r) * s; gg += (243 - gg) * s; b += (248 - b) * s; }
      }
      const o = t * 4; d.data[o] = r; d.data[o + 1] = gg; d.data[o + 2] = b; d.data[o + 3] = 255;
    }
    g.putImageData(d, 0, 0);
    st.images.set(k, cv);
    return cv;
  }
  function onLoad(f) { st.listeners.add(f); return () => st.listeners.delete(f); }

  return { N, st, meta, get, peek, tile, trim, image, onLoad, biomeName, featName, label, hex, rgb, BIOME_HEX };
})();
window.Chunks = Chunks;
