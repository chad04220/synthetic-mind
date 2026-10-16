// blocks.js — the block registry as the page sees it, the procedural textures every face is drawn with,
// and small item icons. Shared by the 3D view (vox.js), its meshing worker (via the tables it builds)
// and the panels (app.js). No three.js here, so the panels work without WebGL.
//
// Registry entries follow DESIGN-v5 §2.1: {id, name, color, colors?: {top, side, bottom}, solid, transparent,
// liquid, light, hardness, tool, tool_level, plant, climbable, ...}. Optional page hints: `shape`
// ("cube" | "cross" | "torch" | "post" | "flat" | "slab"), `height` (0–1, for slabs), `use` (right-click uses it).
// A voxel's uint16 value is looked up in the registry as is; if no entry has that id, the low 12 bits are the id
// and the high 4 bits a state (a liquid's level, 0 = source).

export const TILE = 16;                       // texture pixels per block face

// ───────────────────────────────────────────── helpers
const clamp = (v, a, b) => (v < a ? a : v > b ? b : v);
export function normName(s) { return String(s ?? "").trim().toLowerCase().replace(/[\s-]+/g, "_"); }
export function label(s) { const t = String(s ?? "").replace(/_/g, " ").trim(); return t ? t[0].toUpperCase() + t.slice(1) : ""; }
export function hexRGB(c, fb = [200, 0, 200]) {
  if (c == null) return fb.slice();
  if (Array.isArray(c)) return [c[0] | 0, c[1] | 0, c[2] | 0];
  if (typeof c === "number") return [(c >> 16) & 255, (c >> 8) & 255, c & 255];
  let s = String(c).replace("#", "").trim();
  if (s.length === 3) s = s.split("").map((x) => x + x).join("");
  const n = parseInt(s.slice(0, 6), 16);
  return Number.isFinite(n) ? [(n >> 16) & 255, (n >> 8) & 255, n & 255] : fb.slice();
}
function hash(a, b, c = 0, d = 0) {
  let h = (Math.imul(a | 0, 374761393) + Math.imul(b | 0, 668265263) + Math.imul(c | 0, 982451653) + Math.imul(d | 0, 2246822519)) | 0;
  h = Math.imul(h ^ (h >>> 13), 1274126177); h ^= h >>> 16; return (h >>> 0) / 4294967296;
}
function strHash(s) { let h = 2166136261; for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619); return h >>> 0; }

// ───────────────────────────────────────────── classification
// render kinds shared with the worker
export const K = { AIR: 0, OPAQUE: 1, CUTOUT: 2, TRANSLUCENT: 3, LIQUID: 4, CROSS: 5, TORCH: 6, POST: 7, FLAT: 8, SLAB: 9 };
const RX = {
  cross: /(^|_)(tall_?grass|grass_plant|short_grass|fern|flower|sapling|mushroom|rose|tulip|dandelion|poppy|daisy|orchid|lily(?!_pad)|wheat|carrots?|potato(es)?|crop|sugar_?cane|cane|kelp|berry_bush|bush|reed|seagrass|vine|cobweb|fire|dead_bush|coral|bluebell|cornflower|allium|blossom)/,
  torch: /torch/,
  post: /fence|wall$/,
  flat: /lily_pad|pressure_plate|wire|dust|carpet|rail|snow_layer|button/,
  slab: /slab|(^|_)bed($|_)|farmland|(^|_)path|cake/,
  translucent: /ice/,
  usable: /door|lever|button|chest|crafting|furnace|(^|_)bed($|_)|bell|trapdoor|gate|anvil|barrel|lamp|note|campfire|sign/,
};
function classify(b) {
  const n = b.key;
  if (b.id === 0 || n === "air" || n === "void" || n === "cave_air") return K.AIR;
  if (b.shape) {
    const cube = b.transparent ? (RX.translucent.test(n) ? K.TRANSLUCENT : K.CUTOUT) : K.OPAQUE;
    const k = { none: K.AIR, cube, liquid: K.LIQUID, cross: K.CROSS, crop: K.CROSS, fire: K.CROSS, torch: K.TORCH, lever: K.TORCH,
      post: K.POST, fence: K.POST, flat: K.FLAT, wire: K.FLAT, plate: K.FLAT, button: K.FLAT, slab: K.SLAB, bed: K.SLAB,
      door: K.CUTOUT, ladder: K.CUTOUT, pane: K.CUTOUT }[b.shape];
    if (k != null) return k === K.SLAB && b.height != null && +b.height >= 1 ? cube : k;
  }
  if (b.liquid || n === "steam") return n === "steam" ? K.CROSS : K.LIQUID;
  if (RX.torch.test(n)) return K.TORCH;
  if (RX.flat.test(n)) return K.FLAT;
  if (RX.post.test(n)) return K.POST;
  if (RX.slab.test(n) && b.solid !== false) return K.SLAB;
  if (b.solid === false && !b.climbable && (b.plant || RX.cross.test(n) || b.transparent)) return K.CROSS;
  if (RX.cross.test(n) && b.solid === false) return K.CROSS;
  if (b.transparent) return RX.translucent.test(n) ? K.TRANSLUCENT : K.CUTOUT;
  return K.OPAQUE;
}
function slabHeight(b) {
  if (b.height != null) return clamp(+b.height, 0.05, 1);
  if (/farmland|path/.test(b.key)) return 15 / 16;
  if (/bed/.test(b.key)) return 9 / 16;
  if (/cake/.test(b.key)) return 0.5;
  return 0.5;
}

// ───────────────────────────────────────────── the registry
export const Reg = {
  list: [], byId: new Map(), byName: new Map(), items: new Map(), ready: false, maxId: 0,
  lut: null,        // Uint16Array(65536): raw voxel value -> block id
};

export function loadRegistry(json, itemsJson) {
  let arr = json;
  if (arr && !Array.isArray(arr)) arr = arr.blocks || arr.items || Object.entries(arr).map(([k, v]) => ({ id: +k, ...v }));
  arr = (arr || []).filter((b) => b && b.id != null);
  Reg.list = []; Reg.byId.clear(); Reg.byName.clear();
  for (const raw of arr) {
    const b = { ...raw, id: +raw.id, key: normName(raw.name ?? `block_${raw.id}`) };
    b.rgb = hexRGB(b.color, [190, 60, 190]);
    const cs = b.colors || {};
    b.top = hexRGB(cs.top ?? b.color, b.rgb); b.side = hexRGB(cs.side ?? b.color, b.rgb); b.bottom = hexRGB(cs.bottom ?? cs.side ?? b.color, b.rgb);
    b.kind = classify(b);
    if (b.solid == null) b.solid = b.kind === K.OPAQUE || b.kind === K.CUTOUT || b.kind === K.TRANSLUCENT || b.kind === K.SLAB || b.kind === K.POST;
    b.opaque = b.kind === K.OPAQUE;
    b.emit = clamp(+b.light || 0, 0, 15) | 0;
    b.isLava = b.kind === K.LIQUID && /lava/.test(b.key);
    b.usable = b.use != null ? !!b.use : RX.usable.test(b.key);
    b.h = b.kind === K.SLAB ? slabHeight(b) : b.kind === K.TORCH && /lantern/.test(b.key) ? 0.5625 : 1;
    b.label = label(b.label || b.name || b.key);
    Reg.list.push(b); Reg.byId.set(b.id, b); Reg.byName.set(b.key, b);
  }
  Reg.maxId = Math.max(0, ...Reg.list.map((b) => b.id));
  const lut = new Uint16Array(65536);
  for (let v = 1; v < 65536; v++) lut[v] = Reg.byId.has(v) ? v : Reg.byId.has(v & 0xfff) ? v & 0xfff : (v & 0xfff ? 0xffff : 0);
  Reg.lut = lut;
  Reg.items.clear();
  let items = itemsJson;
  if (items && !Array.isArray(items)) items = items.items || Object.entries(items).map(([k, v]) => ({ name: k, ...v }));
  for (const it of items || []) if (it && it.name) Reg.items.set(normName(it.name), { ...it, key: normName(it.name) });
  Reg.ready = true;
  return Reg;
}
export const blockOf = (raw) => Reg.byId.get(Reg.lut ? Reg.lut[raw & 0xffff] : raw);
export function findBlock(ref) {
  if (ref == null) return null;
  if (typeof ref === "number") return Reg.byId.get(ref) || null;
  if (typeof ref === "object") return findBlock(ref.block ?? ref.id ?? ref.item ?? ref.name);
  const k = normName(ref);
  if (/^\d+$/.test(k)) return Reg.byId.get(+k) || null;
  return Reg.byName.get(k) || Reg.byName.get(k.replace(/^block_/, "")) || null;
}
export function itemName(ref) {
  if (ref == null) return "";
  if (typeof ref === "object") return itemName(ref.item ?? ref.name ?? ref.id ?? ref.block);
  const b = typeof ref === "number" ? Reg.byId.get(ref) : null;
  if (b) return b.label;
  const it = Reg.items.get(normName(ref));
  return it?.label || label(ref);
}

// ───────────────────────────────────────────── worker tables
export function workerTables() {
  const n = Reg.maxId + 1;
  const t = { n, kind: new Uint8Array(n), opaque: new Uint8Array(n), emit: new Uint8Array(n), layer: new Uint16Array(n * 3),
    h: new Float32Array(n).fill(1), atten: new Uint8Array(n), cullSame: new Uint8Array(n), lava: new Uint8Array(n), sway: new Uint8Array(n), lvl: new Uint8Array(n) };
  for (const b of Reg.list) {
    const i = b.id; t.lvl[i] = b.kind === K.LIQUID ? clamp(+b.state || 0, 0, 7) : 0; t.kind[i] = b.kind; t.opaque[i] = b.opaque ? 1 : 0; t.emit[i] = b.emit; t.h[i] = b.h; t.lava[i] = b.isLava ? 1 : 0;
    const L = Tex.layerOf.get(b.id) || [0, 0, 0];
    t.layer[i * 3] = L[0]; t.layer[i * 3 + 1] = L[1]; t.layer[i * 3 + 2] = L[2];
    // sky light dims a little through leaves and water, fully through other non-opaque blocks
    t.atten[i] = b.kind === K.LIQUID || /leaves|leaf/.test(b.key) || b.kind === K.TRANSLUCENT ? 2 : b.opaque ? 15 : 0;
    t.cullSame[i] = b.kind === K.CUTOUT || b.kind === K.TRANSLUCENT || b.kind === K.LIQUID ? 1 : 0;
    t.sway[i] = /leaves|leaf/.test(b.key) ? 2 : b.kind === K.CROSS && !/mushroom|fire|cobweb|steam/.test(b.key) ? 1 : 0;
  }
  return { tables: t, lut: Reg.lut };
}

// ───────────────────────────────────────────── procedural textures
// Every block gets three 16×16 RGBA layers (top, side, bottom; shared when identical). Layer 0 is a
// magenta "unknown" checker. Patterns are chosen from the block's name.
export const Tex = { layers: 0, data: null, layerOf: new Map(), keyOf: [] };

function px(img, x, y, c, a = 255) {   // y from the top of the picture
  if (x < 0 || y < 0 || x >= TILE || y >= TILE) return;
  const o = ((TILE - 1 - y) * TILE + x) * 4;   // stored bottom row first (v = 0 at the bottom of a face)
  img[o] = clamp(c[0], 0, 255) | 0; img[o + 1] = clamp(c[1], 0, 255) | 0; img[o + 2] = clamp(c[2], 0, 255) | 0; img[o + 3] = a;
}
const mul = (c, f) => [c[0] * f, c[1] * f, c[2] * f];
const add = (c, d) => [c[0] + d, c[1] + d, c[2] + d];
const mix = (a, b, t) => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
const lum = (c) => (c[0] * 0.3 + c[1] * 0.59 + c[2] * 0.11) / 255;

function noiseFill(img, base, seed, amt = 0.12, chunky = 1) {
  for (let y = 0; y < TILE; y++) for (let x = 0; x < TILE; x++) {
    const r = hash(Math.floor(x / chunky), Math.floor(y / chunky), seed);
    px(img, x, y, mul(base, 1 + (r - 0.5) * 2 * amt));
  }
}
function speckle(img, col, seed, n, size = 1) {
  for (let i = 0; i < n; i++) {
    const x = Math.floor(hash(i, 1, seed) * TILE), y = Math.floor(hash(i, 2, seed) * TILE);
    for (let dy = 0; dy < size; dy++) for (let dx = 0; dx < size; dx++) if (hash(i, dx + dy * 3, seed + 7) > 0.25 || (dx === 0 && dy === 0)) px(img, x + dx, y + dy, mul(col, 0.9 + hash(i, dx, seed + 3) * 0.2));
  }
}
const PAT = {
  stone(img, c, s) { noiseFill(img, c, s, 0.1, 1); speckle(img, mul(c, 0.78), s + 1, 10, 2); speckle(img, mul(c, 1.12), s + 2, 6, 1); },
  cobble(img, c, s) {
    // irregular stones with dark mortar: a jittered grid of cells
    const pts = []; for (let gy = 0; gy < 4; gy++) for (let gx = 0; gx < 4; gx++) pts.push([gx * 4 + 1 + hash(gx, gy, s) * 2.5, gy * 4 + 1 + hash(gx, gy, s + 1) * 2.5, 0.8 + hash(gx, gy, s + 2) * 0.35]);
    for (let y = 0; y < TILE; y++) for (let x = 0; x < TILE; x++) {
      let d1 = 1e9, d2 = 1e9, k = 0;
      for (let i = 0; i < pts.length; i++) for (const ox of [-16, 0, 16]) for (const oy of [-16, 0, 16]) {
        const d = (x - pts[i][0] - ox) ** 2 + (y - pts[i][1] - oy) ** 2; if (d < d1) { d2 = d1; d1 = d; k = i; } else if (d < d2) d2 = d;
      }
      const edge = Math.sqrt(d2) - Math.sqrt(d1) < 1.1;
      px(img, x, y, edge ? mul(c, 0.55) : mul(c, pts[k][2] * (0.95 + hash(x, y, s) * 0.1)));
    }
  },
  dirt(img, c, s) { noiseFill(img, c, s, 0.14); speckle(img, mul(c, 0.7), s + 1, 12, 1); speckle(img, mul(c, 1.25), s + 2, 7, 1); },
  sand(img, c, s) { noiseFill(img, c, s, 0.07); speckle(img, mul(c, 0.86), s + 1, 14, 1); speckle(img, mul(c, 1.08), s + 2, 10, 1); },
  gravel(img, c, s) { noiseFill(img, c, s, 0.08); for (let i = 0; i < 14; i++) speckle(img, mul(c, 0.6 + hash(i, 9, s) * 0.8), s + 10 + i, 1, 2 + (hash(i, 3, s) > 0.6)); },
  grassTop(img, c, s) { noiseFill(img, c, s, 0.12); speckle(img, mul(c, 0.8), s + 1, 18, 1); speckle(img, mul(c, 1.15), s + 2, 12, 1); },
  grassSide(img, c, s, b) {
    const dirt = b.dirtRGB || [134, 96, 67]; PAT.dirt(img, dirt, s);
    for (let x = 0; x < TILE; x++) { const h = 3 + Math.floor(hash(x, 0, s) * 2.6); for (let y = 0; y < h; y++) px(img, x, y, mul(c, 0.92 + hash(x, y, s + 4) * 0.18)); }
  },
  snowSide(img, c, s, b) {
    const dirt = [134, 96, 67]; PAT.dirt(img, dirt, s);
    for (let x = 0; x < TILE; x++) { const h = 3 + Math.floor(hash(x, 0, s) * 2.6); for (let y = 0; y < h; y++) px(img, x, y, mul(c, 0.96 + hash(x, y, s + 4) * 0.06)); }
  },
  logSide(img, c, s) {
    for (let x = 0; x < TILE; x++) { const st = 0.82 + hash(x, 0, s) * 0.3; for (let y = 0; y < TILE; y++) px(img, x, y, mul(c, st * (0.93 + hash(x, y >> 1, s) * 0.12) * (x % 4 === 0 ? 0.8 : 1))); }
  },
  logTop(img, c, s, b) {
    const bark = b.side || c, inner = mix(c, [220, 190, 140], 0.25);
    for (let y = 0; y < TILE; y++) for (let x = 0; x < TILE; x++) {
      const d = Math.max(Math.abs(x - 7.5), Math.abs(y - 7.5));
      if (d > 6.5) px(img, x, y, mul(bark, 0.9 + hash(x, y, s) * 0.15));
      else px(img, x, y, mul(inner, Math.round(d) % 2 ? 0.86 : 1.02));
    }
  },
  planks(img, c, s) {
    for (let y = 0; y < TILE; y++) {
      const row = y >> 2, off = (row % 2) * 8 + Math.floor(hash(row, 0, s) * 4), tone = 0.9 + hash(row, 1, s) * 0.16;
      for (let x = 0; x < TILE; x++) {
        let f = tone * (0.95 + hash(x >> 1, y, s + 2) * 0.08);
        if (y % 4 === 3) f *= 0.62; if ((x + off) % 16 === 0) f *= 0.7;
        px(img, x, y, mul(c, f));
      }
    }
  },
  leaves(img, c, s) {
    for (let y = 0; y < TILE; y++) for (let x = 0; x < TILE; x++) {
      const r = hash(x, y, s);
      if (r < 0.17) px(img, x, y, [0, 0, 0], 0);
      else px(img, x, y, mul(c, 0.72 + hash(x >> 1, y >> 1, s + 1) * 0.5));
    }
  },
  ore(img, c, s, b) {
    const base = b.oreBase || [125, 125, 125]; PAT.stone(img, base, s + 31);
    for (let i = 0; i < 5; i++) {
      const cx = 2 + Math.floor(hash(i, 0, s) * 11), cy = 2 + Math.floor(hash(i, 1, s) * 11);
      for (let dy = 0; dy < 3; dy++) for (let dx = 0; dx < 3; dx++) if (hash(i, dx * 3 + dy, s + 5) > 0.35) px(img, cx + dx, cy + dy, mul(c, 0.8 + hash(dx, dy, s + i) * 0.45));
    }
  },
  glass(img, c, s) {
    for (let y = 0; y < TILE; y++) for (let x = 0; x < TILE; x++) {
      const edge = x === 0 || y === 0 || x === 15 || y === 15;
      const streak = (x - y === 4 || x - y === 5 || x - y === -6) && x > 2 && x < 13;
      if (edge) px(img, x, y, mix(c, [255, 255, 255], 0.35), 235); else if (streak) px(img, x, y, [255, 255, 255], 120); else px(img, x, y, c, 0);
    }
  },
  ice(img, c, s) { noiseFill(img, c, s, 0.05, 2); for (let i = 0; i < 4; i++) { const y0 = Math.floor(hash(i, 0, s) * 16); for (let x = 0; x < 6; x++) px(img, Math.floor(hash(i, 1, s) * 10) + x, y0 + (x >> 1), mix(c, [255, 255, 255], 0.5)); } },
  wool(img, c, s) { for (let y = 0; y < TILE; y++) for (let x = 0; x < TILE; x++) px(img, x, y, mul(c, ((x + (y >> 1)) % 3 === 0 ? 0.88 : 1) * (0.95 + hash(x, y, s) * 0.08))); },
  bricks(img, c, s) {
    const mortar = [200, 196, 188];
    for (let y = 0; y < TILE; y++) for (let x = 0; x < TILE; x++) {
      const row = y >> 2, off = row % 2 ? 4 : 0;
      if (y % 4 === 3 || (x + off) % 8 === 7) px(img, x, y, mul(mortar, 0.9 + hash(x, y, s) * 0.1));
      else px(img, x, y, mul(c, (0.86 + hash((x + off) >> 3, row, s) * 0.22) * (0.96 + hash(x, y, s + 1) * 0.08)));
    }
  },
  stoneBricks(img, c, s) {
    for (let y = 0; y < TILE; y++) for (let x = 0; x < TILE; x++) {
      const row = y >> 3, off = row % 2 ? 4 : 0;
      if (y % 8 === 7 || (x + off) % 8 === 7) px(img, x, y, mul(c, 0.6)); else if (y % 8 === 0 || (x + off) % 8 === 0) px(img, x, y, mul(c, 1.12));
      else px(img, x, y, mul(c, 0.93 + hash(x, y, s) * 0.12));
    }
  },
  water(img, c, s) { for (let y = 0; y < TILE; y++) for (let x = 0; x < TILE; x++) px(img, x, y, mul(c, 0.88 + 0.16 * Math.sin((x + y * 0.5) * 0.8 + hash(x >> 2, y >> 2, s) * 3) * 0.6 + hash(x, y, s) * 0.08), 255); },
  lava(img, c, s) { for (let y = 0; y < TILE; y++) for (let x = 0; x < TILE; x++) { const v = 0.5 + 0.5 * Math.sin(x * 0.7 + Math.sin(y * 0.6) * 2 + hash(x >> 2, y >> 2, s) * 4); px(img, x, y, mix(mul(c, 0.75), [255, 230, 120], v * 0.65)); } },
  snow(img, c, s) { noiseFill(img, c, s, 0.04); speckle(img, mul(c, 0.94), s, 8, 1); },
  cross(img, c, s, b) {        // a generic plant: blades or a stem with a flower
    for (let i = 0; i < TILE * TILE * 4; i++) img[i] = 0;
    const flower = /flower|rose|tulip|dandelion|poppy|daisy|orchid|bluebell|cornflower|allium|blossom/.test(b.key);
    const mush = /mushroom/.test(b.key), sap = /sapling/.test(b.key), crop = /wheat|carrot|potato|crop/.test(b.key), cane = /cane|reed|kelp/.test(b.key), bush = /bush|berry/.test(b.key);
    const green = flower || mush ? [72, 140, 52] : c;
    if (mush) {
      for (let y = 9; y < 16; y++) { px(img, 7, y, [225, 215, 190]); px(img, 8, y, [210, 200, 175]); }
      for (let y = 5; y < 10; y++) for (let x = 3; x < 13; x++) if (Math.abs(x - 7.5) < 2 + (y - 4) * 0.9) px(img, x, y, mul(c, (y === 5 ? 1.1 : 1) * (hash(x, y, s) > 0.8 ? 1.35 : 1)));
      return;
    }
    if (flower) {
      for (let y = 6; y < 16; y++) px(img, 7 + (y > 11 ? 1 : 0), y, green);
      px(img, 6, 11, green); px(img, 5, 10, green); px(img, 9, 13, green); px(img, 10, 12, green);
      for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) if (Math.abs(dx) + Math.abs(dy) <= 2 + (hash(dx, dy, s) > 0.6)) px(img, 7 + dx, 4 + dy, mul(c, 0.9 + hash(dx, dy, s) * 0.25));
      px(img, 7, 4, [250, 220, 90]); return;
    }
    if (cane) { for (const x of [3, 8, 12]) for (let y = 0; y < 16; y++) px(img, x, y, mul(c, y % 5 === 0 ? 0.7 : 0.95 + hash(x, y, s) * 0.1)); return; }
    if (crop) { for (let x = 1; x < 16; x += 3) { const h = 5 + Math.floor(hash(x, 0, s) * 6); for (let y = 16 - h - 4; y < 16; y++) px(img, x + (y < 8 ? 1 : 0), y, mul(c, 0.8 + hash(x, y, s) * 0.3)); } return; }
    if (sap || bush) {
      for (let y = 9; y < 16; y++) px(img, 7, y, [110, 80, 50]);
      for (let y = 2; y < 12; y++) for (let x = 2; x < 14; x++) if ((x - 7.5) ** 2 + (y - 7) ** 2 < 22 && hash(x, y, s) > 0.25) px(img, x, y, mul(green, 0.75 + hash(x, y, s + 1) * 0.45));
      if (bush) for (let i = 0; i < 6; i++) px(img, 3 + Math.floor(hash(i, 0, s) * 10), 3 + Math.floor(hash(i, 1, s) * 8), [200, 40, 70]);
      return;
    }
    for (let x = 0; x < TILE; x++) {      // grass blades
      if (hash(x, 1, s) < 0.25) continue;
      const h = 6 + Math.floor(hash(x, 2, s) * 9), lean = hash(x, 3, s) > 0.5 ? 1 : -1;
      for (let y = 0; y < h; y++) px(img, x + (y > h * 0.7 ? lean : 0), 15 - y, mul(c, 0.7 + y / h * 0.45));
    }
  },
  torch(img, c, s) {
    for (let i = 0; i < TILE * TILE * 4; i++) img[i] = 0;
    for (let y = 6; y < 16; y++) for (let x = 7; x < 9; x++) px(img, x, y, [120, 86, 50]);
    px(img, 7, 5, [255, 220, 120]); px(img, 8, 5, [255, 240, 170]); px(img, 7, 4, [255, 200, 80]); px(img, 8, 4, [255, 160, 60]);
    px(img, 7, 6, [255, 190, 90]); px(img, 8, 6, [250, 150, 60]);
  },
  table(img, c, s) { PAT.planks(img, c, s); for (let i = 1; i < 15; i++) { px(img, i, 1, mul(c, 0.5)); px(img, i, 14, mul(c, 0.5)); px(img, 1, i, mul(c, 0.5)); px(img, 14, i, mul(c, 0.5)); px(img, 7, i, mul(c, 0.55)); px(img, i, 7, mul(c, 0.55)); } },
  books(img, c, s) {
    PAT.planks(img, c, s);
    for (const y0 of [1, 9]) for (let x = 1; x < 15; x++) { const bc = [[160, 50, 50], [60, 90, 160], [70, 130, 70], [190, 160, 70], [120, 70, 140]][Math.floor(hash(x, y0, s) * 5)]; for (let y = y0; y < y0 + 6; y++) px(img, x, y, mul(bc, x % 3 === 0 ? 0.8 : 1)); }
  },
  furnace(img, c, s, b) { PAT.stone(img, c, s); for (let y = 8; y < 14; y++) for (let x = 4; x < 12; x++) px(img, x, y, /lit|on/.test(b.key) ? [255, 160 + hash(x, y, s) * 60, 60] : [30, 30, 30]); for (let x = 3; x < 13; x++) px(img, x, 7, mul(c, 0.6)); },
  chest(img, c, s) { PAT.planks(img, c, s); for (let x = 0; x < 16; x++) px(img, x, 5, mul(c, 0.45)); for (let y = 4; y < 8; y++) for (let x = 7; x < 9; x++) px(img, x, y, [200, 200, 210]); },
  tnt(img, c, s) { noiseFill(img, c, s, 0.08); for (let y = 5; y < 11; y++) for (let x = 0; x < 16; x++) px(img, x, y, [235, 230, 220]); for (const x of [2, 3, 4, 7, 8, 11, 12, 13]) px(img, x, 7, [30, 30, 30]); },
  lamp(img, c, s, b) { const on = !/off/.test(b.key); for (let y = 0; y < TILE; y++) for (let x = 0; x < TILE; x++) { const e = x === 0 || y === 0 || x === 15 || y === 15 || x === 7 || y === 7; px(img, x, y, e ? [90, 70, 50] : on ? mix(c, [255, 250, 200], hash(x, y, s) * 0.5) : mul(c, 0.45 + hash(x, y, s) * 0.1)); } },
  door(img, c, s) { PAT.planks(img, c, s); for (let y = 2; y < 7; y++) for (let x = 3; x < 13; x++) if (x !== 7 && x !== 8) px(img, x, y, [180, 210, 230], 140); px(img, 12, 10, [50, 50, 50]); },
  ladder(img, c, s) { for (let i = 0; i < TILE * TILE * 4; i++) img[i] = 0; for (let y = 0; y < 16; y++) { px(img, 2, y, c); px(img, 13, y, c); } for (const y of [2, 6, 10, 14]) for (let x = 2; x < 14; x++) px(img, x, y, mul(c, 0.85)); },
  hay(img, c, s) { for (let y = 0; y < TILE; y++) for (let x = 0; x < TILE; x++) px(img, x, y, mul(c, (y % 6 === 2 ? 0.7 : 0.95) * (0.92 + hash(x, y >> 1, s) * 0.15))); },
  crystal(img, c, s) { noiseFill(img, c, s, 0.1); for (let i = 0; i < 6; i++) { const x = Math.floor(hash(i, 0, s) * 14), y = Math.floor(hash(i, 1, s) * 14); px(img, x, y, [255, 255, 255]); px(img, x + 1, y + 1, mix(c, [255, 255, 255], 0.6)); } },
  obsidian(img, c, s) { noiseFill(img, c, s, 0.2, 2); speckle(img, [110, 70, 160], s, 6, 1); },
  bedrock(img, c, s) { for (let y = 0; y < TILE; y++) for (let x = 0; x < TILE; x++) px(img, x, y, mul(c, 0.5 + hash(x >> 1, y >> 1, s) * 0.9)); },
  cactus(img, c, s) { for (let y = 0; y < TILE; y++) for (let x = 0; x < TILE; x++) px(img, x, y, mul(c, (x % 4 === 1 ? 0.75 : 1) * (0.94 + hash(x, y, s) * 0.1))); for (let i = 0; i < 6; i++) px(img, Math.floor(hash(i, 0, s) * 16), Math.floor(hash(i, 1, s) * 16), [235, 230, 180]); },
  melon(img, c, s) { for (let y = 0; y < TILE; y++) for (let x = 0; x < TILE; x++) px(img, x, y, mul(c, (x % 4 < 2 ? 0.8 : 1.05) * (0.94 + hash(x, y, s) * 0.1))); },
  farmland(img, c, s) { PAT.dirt(img, c, s); for (let y = 0; y < 16; y++) for (let x = 0; x < 16; x++) if (y % 4 === 0) px(img, x, y, mul(c, 0.65)); },
  plain(img, c, s) { noiseFill(img, c, s, 0.07); },
};
function patternFor(b, face) {
  const n = b.key;
  if (b.kind === K.TORCH) return /lantern/.test(n) ? "lamp" : /lever/.test(n) ? "planks" : "torch";
  if (/vine/.test(n)) return "leaves";
  if (/wire/.test(n)) return "plain";
  if (b.kind === K.CROSS) return "cross";
  if (b.kind === K.LIQUID) return b.isLava ? "lava" : "water";
  if (/ladder|scaffold/.test(n)) return "ladder";
  if (/^grass(_block)?$|grass_block|^grass$/.test(n) || (n.includes("grass") && b.solid !== false)) return face === "top" ? "grassTop" : face === "side" ? "grassSide" : "dirt";
  if (/mycelium|podzol/.test(n)) return face === "top" ? "grassTop" : face === "side" ? "grassSide" : "dirt";
  if (/snowy_grass|snow_grass/.test(n)) return face === "top" ? "snow" : face === "side" ? "snowSide" : "dirt";
  if (/ore$|_ore|ore_/.test(n)) return "ore";
  if (/log|wood$|stem$|trunk/.test(n)) return face === "side" ? "logSide" : "logTop";
  if (/leaves|leaf/.test(n)) return "leaves";
  if (/plank/.test(n)) return "planks";
  if (/glass/.test(n)) return "glass";
  if (/ice/.test(n)) return "ice";
  if (/wool|carpet/.test(n)) return "wool";
  if (/stone_?brick|tile/.test(n)) return "stoneBricks";
  if (/brick/.test(n)) return "bricks";
  if (/cobble|mossy/.test(n)) return "cobble";
  if (/crafting/.test(n)) return face === "top" ? "table" : "planks";
  if (/bookshelf/.test(n)) return face === "side" ? "books" : "planks";
  if (/furnace/.test(n)) return face === "side" ? "furnace" : "stone";
  if (/chest|barrel/.test(n)) return "chest";
  if (/tnt/.test(n)) return face === "side" ? "tnt" : "plain";
  if (/lamp|lantern|glow/.test(n)) return "lamp";
  if (/door|trapdoor/.test(n)) return "door";
  if (/hay/.test(n)) return "hay";
  if (/crystal|diamond|emerald|amethyst/.test(n)) return "crystal";
  if (/obsidian/.test(n)) return "obsidian";
  if (/bedrock/.test(n)) return "bedrock";
  if (/cactus/.test(n)) return "cactus";
  if (/melon|pumpkin/.test(n)) return face === "side" ? "melon" : "plain";
  if (/farmland/.test(n)) return face === "top" ? "farmland" : "dirt";
  if (/snow/.test(n)) return "snow";
  if (/sand(?!stone)/.test(n)) return "sand";
  if (/gravel|clay/.test(n)) return n.includes("gravel") ? "gravel" : "sand";
  if (/dirt|mud|soil|path/.test(n)) return "dirt";
  if (/sandstone/.test(n)) return face === "side" ? "stoneBricks" : "sand";
  if (/stone|granite|basalt|andesite|diorite|slate|rock|deep/.test(n)) return "stone";
  if (/plank|wood|fence|table|bed/.test(n)) return "planks";
  return "plain";
}

export function buildTextures() {
  const faces = [];            // [blockId, face, pattern, rgb]
  const seen = new Map();      // dedupe identical layers
  const unknown = new Uint8Array(TILE * TILE * 4);
  for (let y = 0; y < TILE; y++) for (let x = 0; x < TILE; x++) px(unknown, x, y, ((x >> 2) + (y >> 2)) % 2 ? [255, 0, 220] : [40, 0, 40]);
  const imgs = [unknown];
  Tex.layerOf.clear(); Tex.keyOf = ["unknown"];
  for (const b of Reg.list) {
    if (b.kind === K.AIR) continue;
    if (/ore/.test(b.key)) b.oreBase = /deep/.test(b.key) ? [80, 80, 86] : [125, 125, 125];
    const L = [];
    for (const face of ["top", "side", "bottom"]) {
      const pat = patternFor(b, face);
      let col = face === "top" ? b.top : face === "side" ? b.side : b.bottom;
      if (pat === "grassSide") { col = b.top; b.dirtRGB = hexRGB(b.colors?.bottom, [134, 96, 67]); }
      if (pat === "dirt" && face === "bottom" && /grass|mycelium|podzol/.test(b.key)) col = hexRGB(b.colors?.bottom, [134, 96, 67]);
      const key = `${pat}|${col.join(",")}|${pat === "logTop" ? b.side.join(",") : ""}|${pat === "cross" || pat === "furnace" || pat === "lamp" ? b.key : ""}`;
      if (seen.has(key)) { L.push(seen.get(key)); continue; }
      const img = new Uint8Array(TILE * TILE * 4);
      PAT[pat](img, col, strHash(key) % 100000, b);
      seen.set(key, imgs.length); L.push(imgs.length); imgs.push(img); Tex.keyOf.push(key);
    }
    Tex.layerOf.set(b.id, L);
  }
  const data = new Uint8Array(TILE * TILE * 4 * imgs.length);
  imgs.forEach((im, i) => data.set(im, i * TILE * TILE * 4));
  Tex.layers = imgs.length; Tex.data = data; Tex.imgs = imgs;
  return Tex;
}

// ───────────────────────────────────────────── icons (for the hotbar, inventory, palette)
const iconCache = new Map();
function layerCanvas(layer) {
  const c = document.createElement("canvas"); c.width = c.height = TILE;
  const g = c.getContext("2d"), im = g.createImageData(TILE, TILE), src = Tex.imgs[layer];
  for (let y = 0; y < TILE; y++) for (let x = 0; x < TILE; x++) {   // rows are stored bottom first
    const s = ((TILE - 1 - y) * TILE + x) * 4, d = (y * TILE + x) * 4;
    im.data[d] = src[s]; im.data[d + 1] = src[s + 1]; im.data[d + 2] = src[s + 2]; im.data[d + 3] = src[s + 3];
  }
  g.putImageData(im, 0, 0); return c;
}
const GLYPH = {
  stick: "🥢", coal: "⚫", charcoal: "⚫", iron_ingot: "🔩", copper_ingot: "🟠", gold_ingot: "🟡", diamond: "💎", raw_iron: "🪨", raw_copper: "🪨",
  raw_gold: "🪨", string: "🧵", leather: "🟫", feather: "🪶", bone: "🦴", wheat: "🌾", seeds: "🌱", wheat_seeds: "🌱", flour: "🥡", apple: "🍎",
  bread: "🍞", berries: "🫐", sweet_berries: "🫐", carrot: "🥕", potato: "🥔", baked_potato: "🥔", cooked_meat: "🍖", raw_meat: "🥩", beef: "🥩",
  cooked_beef: "🍖", raw_fish: "🐟", cooked_fish: "🍣", fish: "🐟", pumpkin_pie: "🥧", mushroom_stew: "🍲", egg: "🥚", book: "📕", bucket: "🪣",
  water_bucket: "🪣", lava_bucket: "🪣", flint_and_steel: "🔥", shears: "✂️", sword: "🗡️", spark_dust: "✨", clay_ball: "🟤", brick_item: "🧱",
};
const TOOL = /(wood(en)?|stone|iron|gold(en)?|diamond)?_?(pickaxe|axe|shovel|hoe|sword)/;
export const TOOL_TIER = { wood: 1, wooden: 1, stone: 2, iron: 3, gold: 2, golden: 2, diamond: 4 };
export function toolInfo(name) {
  const m = normName(name).match(TOOL); if (!m) return null;
  return { tier: TOOL_TIER[m[1]] || 1, kind: m[3], material: (m[1] || "wood").replace(/en$/, "") };
}
const TOOL_COL = { wood: "#a07848", stone: "#8a8a8a", iron: "#d8d8d8", gold: "#f2cf4a", diamond: "#5fe0d6" };
function toolIcon(t, size) {
  const c = document.createElement("canvas"); c.width = c.height = size; const g = c.getContext("2d"), u = size / 16;
  g.lineCap = "round"; g.strokeStyle = "#6b4a2a"; g.lineWidth = 2.2 * u; g.beginPath(); g.moveTo(3 * u, 13 * u); g.lineTo(11 * u, 5 * u); g.stroke();
  g.strokeStyle = TOOL_COL[t.material] || "#aaa"; g.fillStyle = g.strokeStyle; g.lineWidth = 2.6 * u; g.beginPath();
  if (t.kind === "pickaxe") { g.moveTo(5 * u, 3 * u); g.quadraticCurveTo(11 * u, 2 * u, 13 * u, 9 * u); g.stroke(); }
  else if (t.kind === "axe") { g.moveTo(9 * u, 3 * u); g.lineTo(13 * u, 7 * u); g.lineTo(11 * u, 9 * u); g.lineTo(8 * u, 5 * u); g.closePath(); g.fill(); }
  else if (t.kind === "shovel") { g.arc(12 * u, 4 * u, 2.6 * u, 0, 7); g.fill(); }
  else if (t.kind === "hoe") { g.moveTo(8 * u, 3 * u); g.lineTo(13 * u, 3 * u); g.lineTo(13 * u, 6 * u); g.stroke(); }
  else { g.lineWidth = 2.2 * u; g.moveTo(6 * u, 10 * u); g.lineTo(14 * u, 2 * u); g.stroke(); }
  return c;
}
/** A data-URL icon for an item (block name/id or item name). Blocks are drawn as small isometric cubes. */
export function iconURL(ref, size = 40) {
  const key = `${typeof ref === "object" ? JSON.stringify(ref) : ref}|${size}`;
  if (iconCache.has(key)) return iconCache.get(key);
  let url = "";
  const b = findBlock(ref);
  if (b && Tex.imgs && b.kind !== K.AIR) {
    const L = Tex.layerOf.get(b.id) || [0, 0, 0];
    const c = document.createElement("canvas"); c.width = c.height = size; const g = c.getContext("2d"); g.imageSmoothingEnabled = false;
    if (b.kind === K.CROSS || b.kind === K.TORCH || /ladder/.test(b.key)) g.drawImage(layerCanvas(L[1]), size * 0.1, size * 0.1, size * 0.8, size * 0.8);
    else {
      const top = layerCanvas(L[0]), side = layerCanvas(L[1]), s = size / 2, h = size * 0.25;
      const hgt = b.kind === K.SLAB ? b.h : 1;
      // top: a rhombus
      g.save(); g.translate(s, size * 0.06 + (1 - hgt) * s); g.transform(s / TILE, h / TILE, -s / TILE, h / TILE, 0, 0); g.drawImage(top, 0, 0); g.restore();
      // left
      g.save(); g.translate(0, h + size * 0.06 + (1 - hgt) * s); g.transform(s / TILE, h / TILE, 0, (s * hgt) / TILE, 0, 0); g.drawImage(side, 0, 0); g.fillStyle = "rgba(0,0,0,.22)"; g.fillRect(0, 0, TILE, TILE); g.restore();
      // right
      g.save(); g.translate(s, 2 * h + size * 0.06 + (1 - hgt) * s); g.transform(s / TILE, -h / TILE, 0, (s * hgt) / TILE, 0, 0); g.drawImage(side, 0, 0); g.fillStyle = "rgba(0,0,0,.4)"; g.fillRect(0, 0, TILE, TILE); g.restore();
    }
    url = c.toDataURL();
  } else {
    const name = normName(typeof ref === "object" ? ref.item ?? ref.name : ref), t = toolInfo(name);
    const c = document.createElement("canvas"); c.width = c.height = size; const g = c.getContext("2d");
    if (t) g.drawImage(toolIcon(t, size), 0, 0);
    else {
      const gl = GLYPH[name] || Object.entries(GLYPH).find(([k]) => name.endsWith(k))?.[1];
      if (gl) { g.font = `${size * 0.72}px "Segoe UI Emoji","Apple Color Emoji","Noto Color Emoji",sans-serif`; g.textAlign = "center"; g.textBaseline = "middle"; g.fillText(gl, size / 2, size * 0.56); }
      else {
        const hue = strHash(name) % 360; g.fillStyle = `hsl(${hue} 45% 55%)`; g.beginPath(); g.arc(size / 2, size / 2, size * 0.34, 0, 7); g.fill();
        g.fillStyle = "#fff"; g.font = `700 ${size * 0.36}px system-ui`; g.textAlign = "center"; g.textBaseline = "middle"; g.fillText((name[0] || "?").toUpperCase(), size / 2, size / 2 + 1);
      }
    }
    url = c.toDataURL();
  }
  iconCache.set(key, url);
  return url;
}
export function clearIcons() { iconCache.clear(); }

/** Seconds to break a block with the held item (hardness is seconds by hand). Infinity = unbreakable. */
export function breakTime(b, held, creative) {
  if (!b) return Infinity;
  if (creative) return 0.12;
  const hd = b.hardness == null ? 1 : +b.hardness;
  if (hd < 0 || !Number.isFinite(hd)) return Infinity;
  const t = held ? toolInfo(typeof held === "object" ? held.item ?? held.name : held) : null;
  let speed = 1;
  if (t && b.tool && b.tool !== "none" && t.kind === b.tool) speed = [1, 2, 4, 6, 8][t.tier] || 2;
  return Math.max(0.05, hd / speed);
}
