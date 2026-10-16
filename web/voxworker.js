// voxworker.js — inflates chunk columns, keeps the voxels the page has loaded, lights them and builds their
// meshes off the main thread. One chunk column is 16×16×256 uint16 voxels, index x + 16*(z + 16*y).
//
// Meshes: per-face quads with face culling, per-vertex ambient occlusion and smooth lighting (sky + block
// light, 0–15). Three parts per chunk: opaque, cutout (alpha-tested: leaves, glass, plants, torches) and
// translucent (water, lava, ice). Vertex format: position f32×3 (chunk-local), uvl f32×3 (u, v, texture
// layer), lt u8×4 (ao·face shade, sky light, block light, flags: 1 sway, 2 sway leaves, 3 water, 4 lava).
//
// Light: when the server sends it (the inflated payload carries 65536 more bytes, sky<<4 | block), it is used
// as is until a block in that chunk changes; otherwise sky light is a column pass plus a flood fill inside
// the chunk, and block light a flood fill from emitters in the chunk and its 8 neighbours.
"use strict";

const K = { AIR: 0, OPAQUE: 1, CUTOUT: 2, TRANSLUCENT: 3, LIQUID: 4, CROSS: 5, TORCH: 6, POST: 7, FLAT: 8, SLAB: 9 };
let T = null, LUT = null;        // block tables and the raw-value lookup (see blocks.js workerTables)
const chunks = new Map();        // key "cx,cz" -> {cx, cz, b, sky, blk, maxY, emit: Int32Array, serverLight}
const meshable = new Set();      // keys the page asked meshes for (re-meshed after edits)
const queue = new Map();         // key -> true, waiting to be meshed
let center = [0, 0], running = false, pendingEdits = [];
const kk = (cx, cz) => cx + "," + cz;

// ───────────────────────────────────────────── inflate
async function inflate(buf) {
  if (typeof DecompressionStream === "function") {
    try {
      const ds = new DecompressionStream("deflate");
      const out = await new Response(new Blob([buf]).stream().pipeThrough(ds)).arrayBuffer();
      return new Uint8Array(out);
    } catch (e) { /* fall back to the small inflater */ }
  }
  return tinyInflate(new Uint8Array(buf));
}
// A compact RFC 1950/1951 inflater (used only where DecompressionStream is missing).
function tinyInflate(src) {
  let pos = (src[0] & 0x0f) === 8 && ((src[0] << 8) | src[1]) % 31 === 0 ? 2 : 0, bit = 0, out = new Uint8Array(1 << 18), n = 0;
  const need = (k) => { if (n + k > out.length) { const o = new Uint8Array(Math.max(out.length * 2, n + k)); o.set(out); out = o; } };
  const bits = (k) => { let v = 0; for (let i = 0; i < k; i++) { v |= ((src[pos] >> bit) & 1) << i; if (++bit === 8) { bit = 0; pos++; } } return v; };
  const build = (lens) => {
    const counts = new Uint16Array(16), offs = new Uint16Array(16), syms = new Uint16Array(lens.length);
    for (const l of lens) counts[l]++; counts[0] = 0;
    for (let i = 1; i < 16; i++) offs[i] = offs[i - 1] + counts[i - 1];
    for (let i = 0; i < lens.length; i++) if (lens[i]) syms[offs[lens[i]]++] = i;
    return { counts, syms };
  };
  const decode = (h) => { let code = 0, first = 0, idx = 0; for (let l = 1; l < 16; l++) { code |= bits(1); const c = h.counts[l]; if (code - c < first) return h.syms[idx + code - first]; idx += c; first += c; first <<= 1; code <<= 1; } return -1; };
  const LB = [3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258], LE = [0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0];
  const DB = [1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577], DE = [0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13];
  let fixedL = null, fixedD = null, last = 0;
  while (!last) {
    last = bits(1); const type = bits(2);
    if (type === 0) {
      if (bit) { bit = 0; pos++; }
      const len = src[pos] | (src[pos + 1] << 8); pos += 4; need(len); out.set(src.subarray(pos, pos + len), n); n += len; pos += len; continue;
    }
    let lh, dh;
    if (type === 1) {
      if (!fixedL) { const l = new Uint8Array(288); l.fill(8, 0, 144); l.fill(9, 144, 256); l.fill(7, 256, 280); l.fill(8, 280, 288); fixedL = build(l); fixedD = build(new Uint8Array(30).fill(5)); }
      lh = fixedL; dh = fixedD;
    } else {
      const hl = bits(5) + 257, hd = bits(5) + 1, hc = bits(4) + 4, ord = [16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15];
      const cl = new Uint8Array(19); for (let i = 0; i < hc; i++) cl[ord[i]] = bits(3);
      const ch = build(cl), lens = new Uint8Array(hl + hd);
      for (let i = 0; i < hl + hd;) {
        const s = decode(ch);
        if (s < 16) lens[i++] = s;
        else if (s === 16) { const p = lens[i - 1]; for (let r = 3 + bits(2); r--;) lens[i++] = p; }
        else if (s === 17) i += 3 + bits(3); else i += 11 + bits(7);
      }
      lh = build(lens.subarray(0, hl)); dh = build(lens.subarray(hl));
    }
    for (;;) {
      const s = decode(lh);
      if (s < 256) { need(1); out[n++] = s; } else if (s === 256) break;
      else { const li = s - 257, len = LB[li] + bits(LE[li]), ds = decode(dh), d = DB[ds] + bits(DE[ds]); need(len); for (let i = 0; i < len; i++, n++) out[n] = out[n - d]; }
    }
  }
  return out.subarray(0, n);
}

// ───────────────────────────────────────────── per-chunk data
function scan(c) {
  const b = c.b; let maxY = 0; const emit = [];
  for (let i = 65535; i >= 0; i--) if (b[i]) { maxY = i >> 8; break; }
  for (let i = 0, e = (maxY + 1) << 8; i < e; i++) { const v = b[i]; if (v && T.emit[LUT[v] === 0xffff ? 0 : LUT[v]]) emit.push(i); }
  c.maxY = maxY; c.emit = emit;
}
const idOf = (v) => { const r = LUT[v]; return r === 0xffff ? 0 : r; };
const unknownOf = (v) => v !== 0 && LUT[v] === 0xffff;
const RING = 1 << 18, Q = new Int32Array(RING);
function computeSky(c) {
  const b = c.b, sky = c.sky || (c.sky = new Uint8Array(65536)), top = c.maxY;
  sky.fill(15, (top + 1) << 8);
  for (let col = 0; col < 256; col++) {
    let l = 15;
    for (let y = top; y >= 0; y--) {
      const i = col + (y << 8), v = b[i];
      if (v) { const a = unknownOf(v) ? 15 : T.atten[idOf(v)]; if (a >= 15) l = 0; else if (a) l = Math.max(0, l - a); }
      sky[i] = v && (unknownOf(v) || T.opaque[idOf(v)]) ? 0 : l;
    }
  }
  // flood: light spills sideways and down under overhangs, into doorways and caves near openings
  let qh = 0, qt = 0;
  for (let y = 0; y <= Math.min(255, top + 1); y++) for (let z = 0; z < 16; z++) for (let x = 0; x < 16; x++) {
    const i = x + (z << 4) + (y << 8), l = sky[i]; if (l < 2) continue;
    if ((x > 0 && sky[i - 1] < l - 1) || (x < 15 && sky[i + 1] < l - 1) || (z > 0 && sky[i - 16] < l - 1) || (z < 15 && sky[i + 16] < l - 1) || (y > 0 && sky[i - 256] < l - 1)) { Q[qt] = i; qt = (qt + 1) & (RING - 1); }
  }
  while (qh !== qt) {
    const i = Q[qh]; qh = (qh + 1) & (RING - 1);
    const l = sky[i]; if (l < 2) continue;
    const x = i & 15, z = (i >> 4) & 15, y = i >> 8;
    for (let d = 0; d < 6; d++) {
      let j;
      if (d === 0) { if (x === 15) continue; j = i + 1; } else if (d === 1) { if (x === 0) continue; j = i - 1; }
      else if (d === 2) { if (z === 15) continue; j = i + 16; } else if (d === 3) { if (z === 0) continue; j = i - 16; }
      else if (d === 4) { if (y === 0) continue; j = i - 256; } else { if (y >= 255) continue; j = i + 256; }
      const v = b[j]; if (v && (unknownOf(v) || T.opaque[idOf(v)])) continue;
      const a = v ? T.atten[idOf(v)] : 0, nl = l - 1 - (a ? 1 : 0);
      if (sky[j] < nl) { sky[j] = nl; Q[qt] = j; qt = (qt + 1) & (RING - 1); }
    }
  }
}

// ───────────────────────────────────────────── block light over a 3×3 neighbourhood
const BL_W = 46, BL_OFF = 15;             // region x,z ∈ [-15, 31) around the chunk
let blVol = new Uint8Array(BL_W * BL_W * 256);
function blockLight(cx, cz, ymin, ymax) {
  const nb = [];
  for (let dz = -1; dz <= 1; dz++) for (let dx = -1; dx <= 1; dx++) nb.push(chunks.get(kk(cx + dx, cz + dz)) || null);
  const y0 = Math.max(0, ymin - 15), y1 = Math.min(255, ymax + 15), H = y1 - y0 + 1, S = BL_W * BL_W;
  const vol = blVol; vol.fill(0, 0, S * H);
  const rawAt = (rx, y, rz) => {       // region coords
    const lx = rx - BL_OFF, lz = rz - BL_OFF, ci = (lx < 0 ? 0 : lx < 16 ? 1 : 2) + 3 * (lz < 0 ? 0 : lz < 16 ? 1 : 2), c = nb[ci];
    if (!c) return 0; return c.b[(lx & 15) + ((lz & 15) << 4) + (y << 8)];
  };
  let qh = 0, qt = 0, any = false;
  for (let ci = 0; ci < 9; ci++) {
    const c = nb[ci]; if (!c || !c.emit.length) continue;
    const ox = ((ci % 3) - 1) * 16 + BL_OFF, oz = (((ci / 3) | 0) - 1) * 16 + BL_OFF;
    for (const i of c.emit) {
      const x = (i & 15) + ox, z = ((i >> 4) & 15) + oz, y = i >> 8;
      if (x < 0 || z < 0 || x >= BL_W || z >= BL_W || y < y0 || y > y1) continue;
      const e = T.emit[idOf(c.b[i])]; if (!e) continue;
      const j = x + z * BL_W + (y - y0) * S;
      if (vol[j] < e) { vol[j] = e; Q[qt] = j; qt = (qt + 1) & (RING - 1); any = true; }
    }
  }
  if (!any) return null;
  while (qh !== qt) {
    const j = Q[qh]; qh = (qh + 1) & (RING - 1);
    const l = vol[j]; if (l < 2) continue;
    const x = j % BL_W, z = ((j / BL_W) | 0) % BL_W, yy = (j / S) | 0;
    for (let d = 0; d < 6; d++) {
      let nx = x, nz = z, ny = yy;
      if (d === 0) nx++; else if (d === 1) nx--; else if (d === 2) nz++; else if (d === 3) nz--; else if (d === 4) ny--; else ny++;
      if (nx < 0 || nz < 0 || nx >= BL_W || nz >= BL_W || ny < 0 || ny >= H) continue;
      const k = nx + nz * BL_W + ny * S;
      if (vol[k] >= l - 1) continue;
      const v = rawAt(nx, ny + y0, nz); if (v && (unknownOf(v) || T.opaque[idOf(v)])) continue;
      vol[k] = l - 1; Q[qt] = k; qt = (qt + 1) & (RING - 1);
    }
  }
  return { vol, y0, y1, S };
}

// ───────────────────────────────────────────── meshing
// padded volume: x,z ∈ [-1, 16], y ∈ [-1, top+1]; strides 1, 18, 324
const PX = 18, PS = 324;
let pid = new Uint16Array(PS * 258), psky = new Uint8Array(PS * 258), pblk = new Uint8Array(PS * 258);
// faces: normal, origin, du, dv (corners o, o+du, o+du+dv, o+dv; CCW from outside)
const FACES = [
  { n: [1, 0, 0], o: [1, 0, 1], du: [0, 0, -1], dv: [0, 1, 0], tex: 1, shade: 0.76 },
  { n: [-1, 0, 0], o: [0, 0, 0], du: [0, 0, 1], dv: [0, 1, 0], tex: 1, shade: 0.76 },
  { n: [0, 1, 0], o: [0, 1, 1], du: [1, 0, 0], dv: [0, 0, -1], tex: 0, shade: 1.0 },
  { n: [0, -1, 0], o: [0, 0, 0], du: [1, 0, 0], dv: [0, 0, 1], tex: 2, shade: 0.55 },
  { n: [0, 0, 1], o: [0, 0, 1], du: [1, 0, 0], dv: [0, 1, 0], tex: 1, shade: 0.88 },
  { n: [0, 0, -1], o: [1, 0, 0], du: [-1, 0, 0], dv: [0, 1, 0], tex: 1, shade: 0.88 },
];
const off = (v) => v[0] + v[1] * PS + v[2] * PX;
for (const f of FACES) {
  f.no = off(f.n);
  f.corner = [[0, 0], [1, 0], [1, 1], [0, 1]].map(([a, b]) => {
    const p = [f.o[0] + a * f.du[0] + b * f.dv[0], f.o[1] + a * f.du[1] + b * f.dv[1], f.o[2] + a * f.du[2] + b * f.dv[2]];
    const s1 = f.du.map((d) => d * (2 * a - 1)), s2 = f.dv.map((d) => d * (2 * b - 1));
    return { p, s1: f.no + off(s1), s2: f.no + off(s2), c: f.no + off(s1) + off(s2) };
  });
  // uv from position inside the block: axis + sign of du and dv
  f.uax = f.du.findIndex((d) => d !== 0); f.usg = f.du[f.uax];
  f.vax = f.dv.findIndex((d) => d !== 0); f.vsg = f.dv[f.vax];
}
const AO = [0.42, 0.6, 0.8, 1.0];

class Part {
  constructor() { this.pos = new Float32Array(1 << 16); this.uvl = new Float32Array(1 << 16); this.lt = new Uint8Array(1 << 16); this.idx = new Uint32Array(1 << 15); this.nv = 0; this.ni = 0; }
  reset() { this.nv = 0; this.ni = 0; }
  grow(nv, ni) {
    if ((this.nv + nv) * 3 > this.pos.length) { const g = (a, n) => { const b = new a.constructor(n); b.set(a); return b; }; const n = Math.max(this.pos.length * 2, (this.nv + nv) * 3); this.pos = g(this.pos, n); this.uvl = g(this.uvl, n); this.lt = g(this.lt, (n / 3) * 4); }
    if (this.ni + ni > this.idx.length) { const b = new Uint32Array(Math.max(this.idx.length * 2, this.ni + ni)); b.set(this.idx); this.idx = b; }
  }
  vert(x, y, z, u, v, layer, a, s, bl, fl) {
    const i = this.nv++, o3 = i * 3, o4 = i * 4;
    this.pos[o3] = x; this.pos[o3 + 1] = y; this.pos[o3 + 2] = z;
    this.uvl[o3] = u; this.uvl[o3 + 1] = v; this.uvl[o3 + 2] = layer;
    this.lt[o4] = a; this.lt[o4 + 1] = s; this.lt[o4 + 2] = bl; this.lt[o4 + 3] = fl;
  }
  quad(flip) {
    const b = this.nv - 4, i = this.ni;
    if (flip) { this.idx[i] = b + 1; this.idx[i + 1] = b + 2; this.idx[i + 2] = b + 3; this.idx[i + 3] = b + 1; this.idx[i + 4] = b + 3; this.idx[i + 5] = b; }
    else { this.idx[i] = b; this.idx[i + 1] = b + 1; this.idx[i + 2] = b + 2; this.idx[i + 3] = b; this.idx[i + 4] = b + 2; this.idx[i + 5] = b + 3; }
    this.ni += 6;
  }
  out() {
    if (!this.nv) return null;
    const big = this.nv > 65535, idx = big ? this.idx.slice(0, this.ni) : Uint16Array.from(this.idx.subarray(0, this.ni));
    return { pos: this.pos.slice(0, this.nv * 3), uvl: this.uvl.slice(0, this.nv * 3), lt: this.lt.slice(0, this.nv * 4), idx };
  }
}
const parts = [new Part(), new Part(), new Part()];   // opaque, cutout, translucent

function buildPadded(c) {
  const nbs = [];
  let top = c.maxY;
  for (let dz = -1; dz <= 1; dz++) for (let dx = -1; dx <= 1; dx++) { const n = chunks.get(kk(c.cx + dx, c.cz + dz)) || null; nbs.push(n); if (n && n.maxY > top) top = n.maxY; }
  top = Math.min(254, top + 1);
  const H = top + 3;
  if (pid.length < PS * H) { pid = new Uint16Array(PS * H); psky = new Uint8Array(PS * H); pblk = new Uint8Array(PS * H); }
  // block light (server-provided or flooded here)
  let bl = null;
  if (!c.serverLight) {
    let ymin = 255, ymax = 0, any = false;
    for (const n of nbs) if (n && n.emit.length) for (const i of n.emit) { const y = i >> 8; if (y < ymin) ymin = y; if (y > ymax) ymax = y; any = true; }
    if (any) bl = blockLight(c.cx, c.cz, ymin, ymax);
  }
  for (let py = 0; py < H; py++) {
    const y = py - 1;
    for (let pz = 0; pz < PX; pz++) {
      const z = pz - 1, ci = 3 * (z < 0 ? 0 : z < 16 ? 1 : 2), lz = z & 15;
      for (let px = 0; px < PX; px++) {
        const x = px - 1, n = nbs[ci + (x < 0 ? 0 : x < 16 ? 1 : 2)], p = px + pz * PX + py * PS;
        if (y < 0) { pid[p] = 0xfffe; psky[p] = 0; pblk[p] = 0; continue; }       // below the world: solid
        if (!n || y > 255) { pid[p] = 0; psky[p] = 15; pblk[p] = 0; continue; }
        const i = (x & 15) + (lz << 4) + (y << 8), v = n.b[i];
        pid[p] = v === 0 ? 0 : LUT[v] === 0xffff ? 0xfffe : LUT[v];
        if (n.serverLight) { psky[p] = n.slight[i] >> 4; pblk[p] = n.slight[i] & 15; }
        else {
          psky[p] = n.sky ? n.sky[i] : 15;
          pblk[p] = bl && y >= bl.y0 && y <= bl.y1 ? bl.vol[(x + BL_OFF) + (z + BL_OFF) * BL_W + (y - bl.y0) * bl.S] : 0;
        }
      }
    }
  }
  return H;
}
const isOpq = (id) => id === 0xfffe || (id !== 0 && T.opaque[id] === 1);
const kindOf = (id) => (id === 0xfffe ? K.OPAQUE : T.kind[id]);

function meshChunk(c) {
  const t0 = performance.now();
  buildPadded(c);
  for (const p of parts) p.reset();
  const top = c.maxY;
  for (let y = 0; y <= top; y++) for (let z = 0; z < 16; z++) for (let x = 0; x < 16; x++) {
    const p = (x + 1) + (z + 1) * PX + (y + 1) * PS, id = pid[p];
    if (id === 0) continue;
    const kind = kindOf(id);
    if (kind === K.OPAQUE || kind === K.CUTOUT || kind === K.TRANSLUCENT) cube(x, y, z, p, id, kind);
    else if (kind === K.LIQUID) liquid(x, y, z, p, id, T.lvl[id] || (c.b[x + (z << 4) + (y << 8)] >> 12));
    else if (kind === K.CROSS) cross(x, y, z, p, id);
    else if (kind === K.TORCH) { if (T.layer[id * 3 + 1] && T.h[id] < 1) box(x, y, z, p, id, 5 / 16, 0, 5 / 16, 11 / 16, T.h[id], 11 / 16, 1); else box(x, y, z, p, id, 7 / 16, 0, 7 / 16, 9 / 16, 10 / 16, 9 / 16, 1); }
    else if (kind === K.POST) box(x, y, z, p, id, 6 / 16, 0, 6 / 16, 10 / 16, 1, 10 / 16, 0);
    else if (kind === K.FLAT) box(x, y, z, p, id, 0, 0, 0, 1, 1 / 16, 1, 1);
    else if (kind === K.SLAB) box(x, y, z, p, id, 0, 0, 0, 1, T.h[id], 1, 0);
  }
  const res = parts.map((pt) => pt.out());
  return { res, ms: performance.now() - t0 };
}
function layerOf(id, f) { return id === 0xfffe ? 0 : T.layer[id * 3 + FACES[f].tex]; }

function cube(x, y, z, p, id, kind) {
  const part = parts[kind === K.OPAQUE ? 0 : kind === K.CUTOUT ? 1 : 2];
  const sway = T.sway[id] === 2 ? 2 : 0;
  for (let f = 0; f < 6; f++) {
    const F = FACES[f], q = p + F.no, nid = pid[q];
    if (nid !== 0) {
      if (isOpq(nid)) continue;
      if (kind !== K.OPAQUE && nid === id && T.cullSame[id]) continue;
      if (kind === K.TRANSLUCENT && kindOf(nid) === K.TRANSLUCENT) continue;
    }
    part.grow(4, 6);
    const layer = layerOf(id, f);
    let a0 = 0, a1 = 0, a2 = 0, a3 = 0;
    for (let k = 0; k < 4; k++) {
      const C = F.corner[k];
      const o1 = isOpq(pid[p + C.s1]) ? 1 : 0, o2 = isOpq(pid[p + C.s2]) ? 1 : 0, oc = isOpq(pid[p + C.c]) ? 1 : 0;
      const ao = o1 && o2 ? 0 : 3 - (o1 + o2 + oc);
      let ss = psky[q], bb = pblk[q], n = 1;
      if (!o1) { ss += psky[p + C.s1]; bb += pblk[p + C.s1]; n++; }
      if (!o2) { ss += psky[p + C.s2]; bb += pblk[p + C.s2]; n++; }
      if (!oc && !(o1 && o2)) { ss += psky[p + C.c]; bb += pblk[p + C.c]; n++; }
      const px = x + C.p[0], py = y + C.p[1], pz = z + C.p[2];
      const u = F.usg > 0 ? C.p[F.uax] : 1 - C.p[F.uax], v = F.vsg > 0 ? C.p[F.vax] : 1 - C.p[F.vax];
      part.vert(px, py, pz, u, v, layer, Math.round(AO[ao] * F.shade * 255), Math.round((ss / n) * 17), Math.round((bb / n) * 17), sway);
      if (k === 0) a0 = ao; else if (k === 1) a1 = ao; else if (k === 2) a2 = ao; else a3 = ao;
    }
    part.quad(a0 + a2 < a1 + a3);
  }
}

function liquid(x, y, z, p, id, lvl) {
  const part = parts[2], lava = T.lava[id], flag = lava ? 4 : 3;
  const above = pid[p + PS], aboveSame = above !== 0 && above !== 0xfffe && T.kind[above] === K.LIQUID && T.lava[above] === lava;
  const h = aboveSame ? 1 : lvl === 0 ? 0.875 : Math.max(0.12, (8 - Math.min(7, lvl)) / 9);
  for (let f = 0; f < 6; f++) {
    const F = FACES[f], q = p + F.no, nid = pid[q];
    if (isOpq(nid)) continue;
    if (nid !== 0 && nid !== 0xfffe && T.kind[nid] === K.LIQUID && T.lava[nid] === lava) continue;
    if (f === 2 && aboveSame) continue;
    part.grow(4, 6);
    const layer = layerOf(id, f), s = Math.max(psky[q], psky[p]) * 17, b = Math.max(pblk[q], pblk[p], lava ? 15 : 0) * 17;
    for (let k = 0; k < 4; k++) {
      const C = F.corner[k], cy = C.p[1] * h;
      const u = F.usg > 0 ? C.p[F.uax] : 1 - C.p[F.uax], v = F.vax === 1 ? cy : F.vsg > 0 ? C.p[F.vax] : 1 - C.p[F.vax];
      part.vert(x + C.p[0], y + cy, z + C.p[2], u, v, layer, Math.round(F.shade * 255), s, b, flag);
    }
    part.quad(false);
  }
}

function cross(x, y, z, p, id) {
  const part = parts[1], layer = T.layer[id * 3 + 1], s = psky[p] * 17, b = Math.max(pblk[p], T.emit[id]) * 17, sw = T.sway[id] ? 1 : 0;
  const e = 0.15, lo = e, hi = 1 - e;
  const quads = [[[lo, lo], [hi, hi]], [[hi, lo], [lo, hi]]];
  for (const [[ax, az], [bx, bz]] of quads) {
    part.grow(4, 6);
    part.vert(x + ax, y, z + az, 0, 0, layer, 230, s, b, 0);
    part.vert(x + bx, y, z + bz, 1, 0, layer, 230, s, b, 0);
    part.vert(x + bx, y + 1, z + bz, 1, 1, layer, 255, s, b, sw);
    part.vert(x + ax, y + 1, z + az, 0, 1, layer, 255, s, b, sw);
    part.quad(false);
  }
}

// a small box inside the cell (torches, fence posts, slabs, carpets); `cut` puts it in the cutout part
function box(x, y, z, p, id, x0, y0, z0, x1, y1, z1, cut) {
  const part = parts[cut || T.kind[id] === K.TORCH ? 1 : 0], s = psky[p] * 17, b = Math.max(pblk[p], T.emit[id]) * 17;
  const lo = [x0, y0, z0], hi = [x1, y1, z1];
  for (let f = 0; f < 6; f++) {
    const F = FACES[f], ax = F.n[0] ? 0 : F.n[1] ? 1 : 2, atEdge = F.n[ax] > 0 ? hi[ax] >= 1 : lo[ax] <= 0;
    if (atEdge && isOpq(pid[p + F.no])) continue;
    part.grow(4, 6);
    const layer = T.layer[id * 3 + F.tex];
    const ls = atEdge ? psky[p + F.no] * 17 : s, lb = atEdge ? Math.max(pblk[p + F.no], T.emit[id]) * 17 : b;
    for (let k = 0; k < 4; k++) {
      const C = F.corner[k], q = [C.p[0] ? hi[0] : lo[0], C.p[1] ? hi[1] : lo[1], C.p[2] ? hi[2] : lo[2]];
      const u = F.usg > 0 ? q[F.uax] : 1 - q[F.uax], v = F.vsg > 0 ? q[F.vax] : 1 - q[F.vax];
      part.vert(x + q[0], y + q[1], z + q[2], u, v, layer, Math.round(F.shade * 255), ls, lb, 0);
    }
    part.quad(false);
  }
}

// ───────────────────────────────────────────── the top of each column (for the minimap)
function columns(c) {
  const hmap = new Uint8Array(256), top = new Uint16Array(256), depth = new Uint8Array(256);
  for (let col = 0; col < 256; col++) colInfo(c, col, hmap, top, depth);
  return { hmap, top, depth };
}
function colInfo(c, col, hmap, top, depth) {
  let y = c.maxY;
  for (; y >= 0; y--) { const v = c.b[col + (y << 8)]; if (v && T.kind[idOf(v)] !== K.AIR) break; }
  if (y < 0) { hmap[col] = 0; top[col] = 0; depth[col] = 0; return; }
  const id = idOf(c.b[col + (y << 8)]); hmap[col] = y; top[col] = id;
  let d = 0; if (T.kind[id] === K.LIQUID) { let yy = y; while (yy > 0 && T.kind[idOf(c.b[col + (yy << 8)])] === K.LIQUID) { yy--; d++; } }
  depth[col] = Math.min(255, d);
}

// ───────────────────────────────────────────── the job loop
function post(c, kind) {
  const { res, ms } = meshChunk(c);
  const transfer = [];
  for (const r of res) if (r) transfer.push(r.pos.buffer, r.uvl.buffer, r.lt.buffer, r.idx.buffer);
  self.postMessage({ type: "mesh", key: kk(c.cx, c.cz), cx: c.cx, cz: c.cz, parts: res, ms, why: kind }, transfer);
}
function pump() {
  if (running) return;
  running = true;
  setTimeout(function step() {
    if (pendingEdits.length) { const e = pendingEdits; pendingEdits = []; applyEdits(e); }
    let best = null, bd = Infinity;
    for (const key of queue.keys()) {
      const c = chunks.get(key); if (!c) { queue.delete(key); continue; }
      const d = (c.cx * 16 + 8 - center[0]) ** 2 + (c.cz * 16 + 8 - center[1]) ** 2; if (d < bd) { bd = d; best = key; }
    }
    if (best) { queue.delete(best); post(chunks.get(best), "load"); }
    if (queue.size || pendingEdits.length) setTimeout(step, 0); else running = false;
  }, 0);
}
function applyEdits(list) {
  const dirty = new Set(), relight = new Set();
  for (const [x, y, z, v] of list) {
    if (y < 0 || y > 255) continue;
    const cx = Math.floor(x / 16), cz = Math.floor(z / 16), c = chunks.get(kk(cx, cz)); if (!c) continue;
    const lx = x - cx * 16, lz = z - cz * 16, i = lx + (lz << 4) + (y << 8), old = c.b[i];
    if (old === v) continue;
    c.b[i] = v; relight.add(c);
    const key = kk(cx, cz); dirty.add(key);
    const emits = T.emit[idOf(old)] || T.emit[idOf(v)];
    for (let dz = -1; dz <= 1; dz++) for (let dx = -1; dx <= 1; dx++) {
      if (!dx && !dz) continue;
      const nearX = dx === 0 || (dx < 0 ? lx <= (emits ? 14 : 0) : lx >= (emits ? 1 : 15)), nearZ = dz === 0 || (dz < 0 ? lz <= (emits ? 14 : 0) : lz >= (emits ? 1 : 15));
      if (nearX && nearZ) dirty.add(kk(cx + dx, cz + dz));
    }
  }
  for (const c of relight) { c.serverLight = false; scan(c); computeSky(c); }
  for (const key of dirty) if (meshable.has(key) && chunks.has(key)) { queue.delete(key); post(chunks.get(key), "edit"); }
}

self.onmessage = async (ev) => {
  const m = ev.data;
  if (m.type === "init") { T = m.tables; LUT = m.lut; return; }
  if (m.type === "center") { center = [m.x, m.z]; return; }
  if (m.type === "chunk") {
    try {
      const raw = await inflate(m.buf);
      if (raw.length < 131072) throw new Error(`chunk ${m.key}: ${raw.length} bytes after inflating, expected 131072`);
      const b = new Uint16Array(65536);
      const dv = new DataView(raw.buffer, raw.byteOffset, 131072);
      for (let i = 0; i < 65536; i++) b[i] = dv.getUint16(i * 2, true);
      const c = { cx: m.cx, cz: m.cz, b, sky: null, maxY: 0, emit: [], serverLight: raw.length >= 196608 };
      if (c.serverLight) c.slight = raw.slice(131072, 196608);
      scan(c); if (!c.serverLight) computeSky(c);
      chunks.set(m.key, c);
      const cols = columns(c), copy = b.slice();
      self.postMessage({ type: "data", key: m.key, cx: m.cx, cz: m.cz, blocks: copy, ...cols, maxY: c.maxY }, [copy.buffer, cols.hmap.buffer, cols.top.buffer, cols.depth.buffer]);
    } catch (e) { self.postMessage({ type: "error", key: m.key, msg: String(e.message || e) }); }
    return;
  }
  if (m.type === "mesh") { for (const key of m.keys) { meshable.add(key); queue.set(key, true); } pump(); return; }
  if (m.type === "edits") { pendingEdits.push(...m.list); if (!running) { const e = pendingEdits; pendingEdits = []; applyEdits(e); } return; }
  if (m.type === "unload") { for (const key of m.keys) { chunks.delete(key); meshable.delete(key); queue.delete(key); } return; }
  if (m.type === "bench") {     // mesh a loaded chunk n times and report the times (for the Health tab / tests)
    const c = chunks.get(m.key); if (!c) { self.postMessage({ type: "bench", key: m.key, times: [] }); return; }
    const times = []; for (let i = 0; i < (m.n || 5); i++) times.push(meshChunk(c).ms);
    self.postMessage({ type: "bench", key: m.key, times });
  }
};
