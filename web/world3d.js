// world3d.js — the 3D view of Zen's endless world (three.js, vendored).
// One self-contained ES module. Exposes window.World3D and `export default World3D`.
// The terrain streams in chunks of 32×32 tiles from /api/chunk (through window.Chunks, shared with the
// minimap and the Atlas) around the camera's focus; meshes are built a little at a time so no frame waits.
// Coordinates: tile (x, y) occupies world X x..x+1 and world Z y..y+1; height is world Y (decimetres × VS).
// Continuous positions (fx, fy, onMove) are in tile units where an integer value is the tile centre.
import * as THREE from "./vendor/three.module.min.js";

// ───────────────────────────────────────────────────────────── constants
const N = 32;                 // tiles per chunk side
const VS = 0.016;             // world units per decimetre of height
const RADIUS = 2;             // meshes for a (2R+1)² square of chunks around the focus
const SNOWLINE = 1050 * VS;   // world height where peaks turn white
const EMOJI_FONT = `"Segoe UI Emoji","Apple Color Emoji","Noto Color Emoji","Twemoji Mozilla",sans-serif`;
const DIR4 = [[0, -1], [1, 0], [0, 1], [-1, 0]];        // facing 0=N 1=E 2=S 3=W
const FACING_STR = { north: 0, east: 1, south: 2, west: 3 };
const DPR_CAP = { high: 1.5, low: 1 };
const BUDGET_MS = 6;          // mesh building per frame
const GLYPH = {
  berries: "🫐", apple: "🍎", mushroom: "🍄", stick: "🥢", stone: "🪨", flint: "🔪", clay: "🟤", feather: "🪶", shell: "🐚",
  egg: "🥚", honey: "🍯", fish: "🐟", book: "📕", paper: "📄", cup: "☕", bucket: "🪣", axe: "🪓", wood: "🪵", flower: "🌼",
  pinecone: "🌰", lantern: "🏮", nut: "🌰", leaf: "🍂", seed: "🌱", bone: "🦴", rope: "🪢", torch: "🔥", water: "💧",
  "baked apple": "🍎", "roast mushroom": "🍄", toadstool: "🍄", coconut: "🥥", banana: "🍌", "cactus fruit": "🌵", "cooked egg": "🍳",
  "raw fish": "🐟", "cooked fish": "🍢", log: "🪵", crystal: "💎", campfire: "🔥", "rain barrel": "🛢️", bees: "🐝",
  painting: "🖼️", sculpture: "🗿", poem: "📜", recording: "📼", basket: "🧺", candle: "🕯️", bowl: "🥣", ball: "⚽", teddy: "🧸",
};

// ───────────────────────────────────────────────────────────── small utils
const clamp = (v, a, b) => (v < a ? a : v > b ? b : v);
const lerp = (a, b, t) => a + (b - a) * t;
const smooth = (e0, e1, x) => { const t = clamp((x - e0) / (e1 - e0), 0, 1); return t * t * (3 - 2 * t); };
const damp = (k, dt) => 1 - Math.exp(-k * dt);
function hash2(x, y, s = 0) {
  let h = (Math.imul(x | 0, 374761393) + Math.imul(y | 0, 668265263) + Math.imul(s | 0, 982451653)) | 0;
  h = Math.imul(h ^ (h >>> 13), 1274126177); h ^= h >>> 16; return (h >>> 0) / 4294967296;
}
function hashStr(s) { let h = 2166136261; for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619); return h >>> 0; }
function vnoise(x, y, s = 0) {
  const xi = Math.floor(x), yi = Math.floor(y), xf = x - xi, yf = y - yi;
  const u = xf * xf * (3 - 2 * xf), v = yf * yf * (3 - 2 * yf);
  const a = hash2(xi, yi, s), b = hash2(xi + 1, yi, s), c = hash2(xi, yi + 1, s), d = hash2(xi + 1, yi + 1, s);
  return a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v;
}
function rng(seed) {
  let s = seed >>> 0 || 1;
  return () => { s = (s + 0x6D2B79F5) | 0; let t = Math.imul(s ^ (s >>> 15), 1 | s); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
const C = (hex) => new THREE.Color(hex);
const tmpC = new THREE.Color(), tmpV = new THREE.Vector3(), tmpV2 = new THREE.Vector3(), tmpM = new THREE.Matrix4();
const tmpQ = new THREE.Quaternion(), tmpS = new THREE.Vector3();
function shade(c, f) { return c.clone().multiplyScalar(f); }
function isTyping() {
  const a = document.activeElement; if (!a) return false;
  const tag = a.tagName; return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || a.isContentEditable;
}
function escapeHtml(s) { return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
const facingNum = (f) => (typeof f === "number" ? ((f % 4) + 4) % 4 : FACING_STR[f] ?? 2);
const angleOf = (f) => { const d = DIR4[facingNum(f)]; return Math.atan2(d[0], d[1]); };

// ───────────────────────────────────────────────────────────── shared uniforms + material patch
const U = {
  time: { value: 0 }, snow: { value: 0 }, wind: { value: 1 }, light: { value: new THREE.Color(1, 1, 1) },
  autumn: { value: 0 }, bare: { value: 0 }, grassTint: { value: new THREE.Color(1, 1, 1) },
};
// Vertex colours lit by Lambert, with: wind sway (attribute aSway: how far a vertex moves), season tint for
// leaves (aVeg.x > 0: a deciduous leaf, its value picks an autumn colour) and grass (aVeg.y: how grassy),
// and a soft snow cover on upward faces (uSnow).
function patch(mat, { snow = 1, sway = false, veg = false, key = "" } = {}) {
  mat.defines = Object.assign(mat.defines || {}, { W3_SNOW: snow.toFixed(3), W3_SWAY: sway ? 1 : 0, W3_VEG: veg ? 1 : 0 });
  mat.onBeforeCompile = (sh) => {
    Object.assign(sh.uniforms, { uTime: U.time, uWind: U.wind, uSnow: U.snow, uAutumn: U.autumn, uBare: U.bare, uGrassTint: U.grassTint });
    sh.vertexShader = sh.vertexShader
      .replace("#include <common>", `#include <common>
uniform float uTime; uniform float uWind; varying vec3 vW3Pos; varying vec3 vW3N;
#if W3_SWAY > 0
attribute float aSway;
#endif
#if W3_VEG > 0
attribute vec2 aVeg; varying vec2 vVeg;
#endif`)
      .replace("#include <begin_vertex>", `#include <begin_vertex>
#if W3_VEG > 0
vVeg = aVeg;
#endif
#if W3_SWAY > 0
{ vec4 wp0 = modelMatrix * vec4(position, 1.0);
  float ph = uTime * 1.6 + wp0.x * 0.55 + wp0.z * 0.37;
  transformed.x += sin(ph) * aSway * uWind;
  transformed.z += cos(ph * 0.83 + 1.3) * aSway * uWind * 0.7; }
#endif`)
      .replace("#include <project_vertex>", `#include <project_vertex>
{ vec4 w3p = vec4(transformed, 1.0); vec3 w3n = objectNormal;
#ifdef USE_INSTANCING
  w3p = instanceMatrix * w3p; w3n = mat3(instanceMatrix) * w3n;
#endif
  vW3Pos = (modelMatrix * w3p).xyz; vW3N = normalize(mat3(modelMatrix) * w3n); }`);
    sh.fragmentShader = sh.fragmentShader
      .replace("#include <common>", `#include <common>
uniform float uSnow; uniform float uAutumn; uniform float uBare; uniform vec3 uGrassTint; varying vec3 vW3Pos; varying vec3 vW3N;
#if W3_VEG > 0
varying vec2 vVeg;
#endif
float w3h(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float w3n(vec2 p) { vec2 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);
  return mix(mix(w3h(i), w3h(i + vec2(1.0, 0.0)), f.x), mix(w3h(i + vec2(0.0, 1.0)), w3h(i + vec2(1.0, 1.0)), f.x), f.y); }`)
      .replace("#include <color_fragment>", `#include <color_fragment>
#if W3_VEG > 0
if (vVeg.x > 0.0) {
  float l = dot(diffuseColor.rgb, vec3(0.3, 0.55, 0.15));
  float k = fract(vVeg.x * 7.31);
  vec3 au = k < 0.33 ? vec3(0.86, 0.42, 0.13) : k < 0.66 ? vec3(0.93, 0.68, 0.18) : vec3(0.72, 0.2, 0.12);
  diffuseColor.rgb = mix(diffuseColor.rgb, au * (0.55 + l * 1.4), uAutumn * smoothstep(0.0, 0.25, vVeg.x));
  diffuseColor.rgb = mix(diffuseColor.rgb, vec3(0.42, 0.38, 0.33) * (0.6 + l), uBare * 0.85);
}
diffuseColor.rgb = mix(diffuseColor.rgb, diffuseColor.rgb * uGrassTint, vVeg.y);
#endif
{ float sn = uSnow * float(W3_SNOW);
  if (sn > 0.001) {
    float up = smoothstep(0.3, 0.9, normalize(vW3N).y);
    float n = w3n(vW3Pos.xz * 0.9) * 0.55 + w3n(vW3Pos.xz * 3.1 + 7.0) * 0.3 + w3n(vW3Pos.xz * 9.0) * 0.15;
    float cov = clamp(smoothstep(0.08, 0.3, up * sn - n * 0.42 + 0.06), 0.0, 1.0);
    diffuseColor.rgb = mix(diffuseColor.rgb, vec3(0.90, 0.94, 1.0), cov);
  } }`);
  };
  mat.customProgramCacheKey = () => "w4" + snow + "_" + sway + "_" + veg + key;
  return mat;
}
function lambert(opts, p) { return patch(new THREE.MeshLambertMaterial(opts), p); }

// ───────────────────────────────────────────────────────────── canvas textures
function radialTex(stops, size = 64) {
  const c = document.createElement("canvas"); c.width = c.height = size;
  const g = c.getContext("2d"), gr = g.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  for (const [o, col] of stops) gr.addColorStop(o, col);
  g.fillStyle = gr; g.fillRect(0, 0, size, size);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}

// ───────────────────────────────────────────────────────────── billboards (one draw call per kind of sprite)
const BB_VERT = `
attribute vec4 aUV; attribute vec4 aTint;
varying vec2 vUv; varying vec4 vTint;
#include <fog_pars_vertex>
void main() {
  vec3 c = instanceMatrix[3].xyz; float sx = instanceMatrix[0][0]; float sy = instanceMatrix[1][1];
  vUv = aUV.xy + uv * aUV.zw; vTint = aTint;
  vec3 wp;
#if defined(MODE_FLAT)
  wp = c + vec3(position.x * sx, 0.0, -position.y * sy);
#else
  vec3 right = vec3(viewMatrix[0][0], viewMatrix[1][0], viewMatrix[2][0]);
  vec3 camUp = vec3(viewMatrix[0][1], viewMatrix[1][1], viewMatrix[2][1]);
#if defined(MODE_CYL)
  right = normalize(vec3(right.x, 0.0, right.z));
  vec3 up = normalize(mix(vec3(0.0, 1.0, 0.0), camUp, 0.65));
#else
  vec3 up = camUp;
#endif
  wp = c + right * position.x * sx + up * position.y * sy;
#ifdef ADDITIVE
  wp += normalize(cameraPosition - c) * min(sx * 0.5, length(cameraPosition - c) * 0.5);
#endif
#endif
  vec4 mvPosition = viewMatrix * vec4(wp, 1.0);
  gl_Position = projectionMatrix * mvPosition;
#ifndef NOFOG
  #include <fog_vertex>
#endif
}`;
const BB_FRAG = `
uniform sampler2D map; uniform vec3 uLight;
varying vec2 vUv; varying vec4 vTint;
#include <fog_pars_fragment>
void main() {
  vec4 t = texture2D(map, vUv);
#ifdef ALPHA_CUT
  if (t.a < 0.42) discard;
#endif
  float em = clamp(vTint.a - 1.0, 0.0, 1.0);
  vec3 col = t.rgb * vTint.rgb;
#ifdef LIT
  col *= mix(uLight, vec3(1.2), em);
#endif
#ifdef ADDITIVE
  gl_FragColor = vec4(col * min(vTint.a, 1.0) * t.a, 1.0);
#else
  gl_FragColor = vec4(col, t.a * min(vTint.a, 1.0));
#endif
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
#ifndef NOFOG
  #include <fog_fragment>
#endif
}`;
const BB_GEOM_FOOT = new THREE.PlaneGeometry(1, 1).translate(0, 0.5, 0);
const BB_GEOM_CENTER = new THREE.PlaneGeometry(1, 1);
class Billboards {
  constructor(tex, { mode = "cyl", additive = false, cut = false, lit = true, fog = true, cap = 256, a2c = false } = {}) {
    this.tex = tex; this.cap = 0; this.n = 0;
    const defines = {}; defines["MODE_" + mode.toUpperCase()] = 1;
    if (additive) defines.ADDITIVE = 1; if (cut) defines.ALPHA_CUT = 1; if (lit) defines.LIT = 1; if (!fog || additive) defines.NOFOG = 1;
    const uniforms = THREE.UniformsUtils.merge([THREE.UniformsLib.fog, { map: { value: null } }]);
    uniforms.map.value = tex; uniforms.uLight = U.light;   // the shared texture itself (merge would clone it, and a clone misses atlas updates)
    this.mat = new THREE.ShaderMaterial({
      uniforms, defines, vertexShader: BB_VERT, fragmentShader: BB_FRAG, fog: fog && !additive,
      transparent: !cut, depthWrite: cut, blending: additive ? THREE.AdditiveBlending : THREE.NormalBlending,
      alphaToCoverage: a2c, side: THREE.DoubleSide,
    });
    if (mode === "flat") { this.mat.polygonOffset = true; this.mat.polygonOffsetFactor = -2; this.mat.polygonOffsetUnits = -2; }
    this.geomSrc = mode === "cyl" ? BB_GEOM_FOOT : BB_GEOM_CENTER;
    this.group = new THREE.Group();
    this.grow(cap);
  }
  grow(cap) {
    if (this.mesh) { this.group.remove(this.mesh); this.mesh.geometry.dispose(); }
    this.cap = cap;
    const g = this.geomSrc.clone();
    this.uv = new THREE.InstancedBufferAttribute(new Float32Array(cap * 4), 4); this.uv.setUsage(THREE.DynamicDrawUsage);
    this.tint = new THREE.InstancedBufferAttribute(new Float32Array(cap * 4), 4); this.tint.setUsage(THREE.DynamicDrawUsage);
    g.setAttribute("aUV", this.uv); g.setAttribute("aTint", this.tint);
    this.mesh = new THREE.InstancedMesh(g, this.mat, cap);
    this.mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    this.mesh.frustumCulled = false; this.mesh.raycast = () => {}; this.mesh.count = 0;
    this.group.add(this.mesh);
  }
  begin() { this.n = 0; }
  push(x, y, z, sx, sy, u0 = 0, v0 = 0, us = 1, vs = 1, r = 1, g = 1, b = 1, a = 1) {
    if (this.n >= this.cap) { this.grow(this.cap * 2); }
    const i = this.n++, m = this.mesh.instanceMatrix.array, o = i * 16;
    m[o] = sx; m[o + 1] = 0; m[o + 2] = 0; m[o + 3] = 0; m[o + 4] = 0; m[o + 5] = sy; m[o + 6] = 0; m[o + 7] = 0;
    m[o + 8] = 0; m[o + 9] = 0; m[o + 10] = 1; m[o + 11] = 0; m[o + 12] = x; m[o + 13] = y; m[o + 14] = z; m[o + 15] = 1;
    const U4 = this.uv.array, T4 = this.tint.array, p = i * 4;
    U4[p] = u0; U4[p + 1] = v0; U4[p + 2] = us; U4[p + 3] = vs; T4[p] = r; T4[p + 1] = g; T4[p + 2] = b; T4[p + 3] = a;
  }
  end() {
    this.mesh.count = this.n; this.mesh.instanceMatrix.needsUpdate = true;
    this.uv.needsUpdate = true; this.tint.needsUpdate = true;
  }
}

// ───────────────────────────────────────────────────────────── shaders: sky, water, particles
const SKY_VERT = `varying vec3 vDir; void main() { vDir = position; vec4 p = projectionMatrix * modelViewMatrix * vec4(position, 1.0); gl_Position = p.xyww; }`;
const SKY_FRAG = `
uniform vec3 uTop, uHor, uBot, uSunDir, uSunCol, uMoonDir; uniform float uStars, uTime, uSunVis, uMoonVis;
varying vec3 vDir;
float h31(vec3 p) { return fract(sin(dot(p, vec3(12.9898, 78.233, 37.719))) * 43758.5453); }
void main() {
  vec3 d = normalize(vDir); float h = d.y;
  vec3 col = h > 0.0 ? mix(uHor, uTop, pow(clamp(h, 0.0, 1.0), 0.5)) : mix(uHor, uBot, pow(clamp(-h * 2.5, 0.0, 1.0), 0.6));
  float sd = max(dot(d, uSunDir), 0.0);
  col += uSunCol * (pow(sd, 5.0) * 0.18 + pow(sd, 40.0) * 0.35) * uSunVis;
  col += uSunCol * smoothstep(0.99925, 0.9996, sd) * 6.0 * uSunVis;
  if (uStars > 0.01 && h > 0.0) {
    vec3 p = d * 170.0; vec3 cell = floor(p); vec3 f = fract(p) - 0.5; float r = h31(cell);
    float s = step(0.988, r) * smoothstep(0.32, 0.05, length(f)) * (0.55 + 0.45 * sin(uTime * (1.5 + r * 3.0) + r * 90.0));
    col += vec3(0.85, 0.9, 1.0) * s * uStars * smoothstep(0.0, 0.25, h) * (0.6 + 2.4 * fract(r * 37.0));
  }
  float md = dot(d, uMoonDir);
  float disk = smoothstep(0.99905, 0.99935, md);
  vec3 off = normalize(uMoonDir + vec3(0.03, 0.02, 0.0));
  float shadeM = 1.0 - 0.85 * smoothstep(0.99935, 0.9996, dot(d, off));
  col += vec3(1.0, 0.97, 0.88) * disk * shadeM * 2.2 * uMoonVis;
  col += vec3(0.6, 0.7, 1.0) * pow(max(md, 0.0), 300.0) * 0.35 * uMoonVis;
  gl_FragColor = vec4(col, 1.0);
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
}`;
const RAIN_VERT = `
uniform float uTime, uHeavy; uniform vec3 uCenter; attribute vec4 aSeed; varying float vA;
void main() {
  vec3 box = vec3(36.0, 22.0, 36.0);
  vec3 p; p.xz = uCenter.xz + mod(aSeed.xz * box.xz - uCenter.xz, box.xz) - box.xz * 0.5;
  p.y = uCenter.y - 8.0 + mod(aSeed.y * box.y - uTime * 16.0 * (1.0 + uHeavy * 0.45) * (0.8 + aSeed.w * 0.4), box.y);
  p += vec3(0.08 + uHeavy * 0.2, 0.55 + uHeavy * 0.2, 0.03 + uHeavy * 0.06) * position.y;
  vA = 0.25 + 0.75 * position.y;
  gl_Position = projectionMatrix * viewMatrix * vec4(p, 1.0);
}`;
const RAIN_FRAG = `uniform vec3 uColor; uniform float uAlpha; varying float vA; void main() { gl_FragColor = vec4(uColor, uAlpha * vA); }`;
const SNOW_VERT = `
uniform float uTime, uPR; uniform vec3 uCenter; attribute vec4 aSeed; varying float vA;
void main() {
  vec3 box = vec3(34.0, 20.0, 34.0);
  vec3 p; p.y = uCenter.y - 7.0 + mod(aSeed.y * box.y - uTime * (0.9 + aSeed.w * 0.6), box.y);
  vec2 drift = vec2(sin(uTime * 0.7 + aSeed.w * 20.0), cos(uTime * 0.5 + aSeed.x * 20.0)) * 0.6 + vec2(uTime * 0.25, 0.0);
  p.xz = uCenter.xz + mod(aSeed.xz * box.xz + drift - uCenter.xz, box.xz) - box.xz * 0.5;
  vec4 mv = viewMatrix * vec4(p, 1.0);
  gl_PointSize = uPR * (40.0 + aSeed.w * 40.0) / max(-mv.z, 0.5);
  vA = smoothstep(30.0, 6.0, -mv.z);
  gl_Position = projectionMatrix * mv;
}`;
const SNOW_FRAG = `uniform vec3 uColor; uniform float uAlpha; varying float vA;
void main() { float d = length(gl_PointCoord - 0.5); if (d > 0.5) discard; gl_FragColor = vec4(uColor, uAlpha * vA * smoothstep(0.5, 0.15, d)); }`;
const FLY_VERT = `
uniform float uTime, uPR; attribute vec4 aSeed; varying float vA;
void main() {
  vec3 p = position;
  float t = uTime * (0.3 + aSeed.x * 0.4) + aSeed.y * 30.0;
  p += vec3(sin(t) * 0.9, sin(t * 1.7) * 0.3 + 0.2, cos(t * 0.8) * 0.9);
  vec4 mv = viewMatrix * vec4(p, 1.0);
  float blink = smoothstep(0.2, 1.0, sin(uTime * (1.3 + aSeed.z) + aSeed.w * 40.0));
  vA = blink;
  gl_PointSize = uPR * 70.0 / max(-mv.z, 0.5);
  gl_Position = projectionMatrix * mv;
}`;
const FLY_FRAG = `uniform float uAlpha; varying float vA;
void main() { float d = length(gl_PointCoord - 0.5); float a = smoothstep(0.5, 0.0, d); a *= a;
  gl_FragColor = vec4(vec3(1.0, 0.9, 0.45) * a * vA * uAlpha * 1.6, 1.0); }`;
const EMBER_VERT = `
uniform float uTime, uPR; uniform vec4 uFire[8]; attribute vec4 aSeed; varying float vA;
void main() {
  int i = int(aSeed.w); vec4 f = uFire[i];
  float life = fract(uTime * (0.45 + aSeed.x * 0.4) + aSeed.y);
  float ang = aSeed.z * 6.283 + life * 3.0;
  vec3 p = f.xyz + vec3(cos(ang) * (0.06 + life * 0.18), life * 1.5, sin(ang) * (0.06 + life * 0.18));
  vec4 mv = viewMatrix * vec4(p, 1.0);
  vA = f.w * (1.0 - life) * smoothstep(0.0, 0.08, life);
  gl_PointSize = uPR * (18.0 + 14.0 * (1.0 - life)) / max(-mv.z, 0.5);
  gl_Position = projectionMatrix * mv;
}`;
const EMBER_FRAG = `varying float vA;
void main() { float d = length(gl_PointCoord - 0.5); float a = smoothstep(0.5, 0.0, d);
  gl_FragColor = vec4(vec3(1.0, 0.55, 0.18) * a * vA * 2.0, 1.0); }`;
// smoke and steam: soft puffs rising from up to 16 sources (xyz + strength), each with params (rise, size, grey, speed)
const PUFF_VERT = `
uniform float uTime, uPR, uWind; uniform vec4 uSrc[16]; uniform vec4 uPar[16]; attribute vec4 aSeed; varying float vA; varying float vG;
void main() {
  int i = int(aSeed.w); vec4 s = uSrc[i]; vec4 q = uPar[i];
  float life = fract(uTime * q.w * (0.75 + aSeed.x * 0.5) + aSeed.y);
  vec3 p = s.xyz + vec3((aSeed.z - 0.5) * 0.12, 0.0, (aSeed.x - 0.5) * 0.12);
  p.y += life * q.x;
  float drift = life * life * q.x * (0.25 + 0.2 * uWind);
  p.x += drift * 0.8 + sin(life * 5.0 + aSeed.z * 30.0) * 0.07 * life * q.x;
  p.z += drift * 0.35 + cos(life * 4.0 + aSeed.x * 30.0) * 0.06 * life * q.x;
  vec4 mv = viewMatrix * vec4(p, 1.0);
  vA = s.w * smoothstep(0.0, 0.12, life) * (1.0 - life) * (1.0 - life);
  vG = q.z;
  gl_PointSize = uPR * q.y * (0.35 + life * 1.3) * 640.0 / max(-mv.z, 0.5);
  gl_Position = projectionMatrix * mv;
}`;
const PUFF_FRAG = `uniform vec3 uLight; varying float vA; varying float vG;
void main() { vec2 c = gl_PointCoord - 0.5; float d = length(c); if (d > 0.5) discard;
  float a = smoothstep(0.5, 0.1, d) * vA;
  vec3 col = vec3(vG) * mix(uLight, vec3(1.0), 0.3 + 0.35 * step(0.9, vG)) * (0.9 + 0.1 * (0.5 - c.y));
  gl_FragColor = vec4(col, a * 0.75);
  #include <colorspace_fragment>
}`;
// a soft rainbow band: a ring in the sky, faded at its feet
const BOW_VERT = `varying vec2 vUv; void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`;
const BOW_FRAG = `uniform float uAlpha; varying vec2 vUv;
vec3 hue(float h) { return clamp(abs(mod(h * 6.0 + vec3(0.0, 4.0, 2.0), 6.0) - 3.0) - 1.0, 0.0, 1.0); }
void main() {
  float r = vUv.y;                                  // 0 inner .. 1 outer (RingGeometry uv patched below)
  float band = smoothstep(0.0, 0.18, r) * smoothstep(1.0, 0.82, r);
  vec3 col = hue(0.78 * (1.0 - r));                  // violet inside, red outside
  float foot = smoothstep(0.0, 0.22, vUv.x) * smoothstep(1.0, 0.78, vUv.x);
  gl_FragColor = vec4(col * band * foot * uAlpha, 1.0);
}`;
const RIM_VERT = `varying vec3 vN; varying vec3 vV; void main() { vec4 wp = modelMatrix * vec4(position, 1.0);
  vN = normalize(mat3(modelMatrix) * normal); vV = normalize(cameraPosition - wp.xyz); gl_Position = projectionMatrix * viewMatrix * wp; }`;
const RIM_FRAG = `uniform vec3 uColor; uniform float uPower; varying vec3 vN; varying vec3 vV;
void main() { float r = pow(1.0 - abs(dot(normalize(vN), normalize(vV))), 2.2); gl_FragColor = vec4(uColor * r * uPower, 1.0);
  #include <colorspace_fragment>
}`;

// ───────────────────────────────────────────────────────────── palettes
const SKY = {
  night: { top: C("#060a1a"), hor: C("#1d2a50"), bot: C("#0a0e19"), sun: C("#a3b8ff"), sunI: 0.55, hemS: C("#43578f"), hemG: C("#171a24"), hemI: 0.8 },
  twi:   { top: C("#30427e"), hor: C("#f4a066"), bot: C("#3d3242"), sun: C("#ffae6b"), sunI: 1.5, hemS: C("#b39ab8"), hemG: C("#5a4636"), hemI: 0.85 },
  gold:  { top: C("#4a78c0"), hor: C("#ffc488"), bot: C("#c7a88e"), sun: C("#ffb56e"), sunI: 2.5, hemS: C("#d9cbbd"), hemG: C("#7d6a48"), hemI: 1.0 },
  day:   { top: C("#3a7fd6"), hor: C("#c4e4f6"), bot: C("#a3c8de"), sun: C("#fff2db"), sunI: 2.9, hemS: C("#d6e9ff"), hemG: C("#857f55"), hemI: 1.2 },
};
const WEATHER = {
  clear:  { mix: 0,    top: C("#3a7fd6"), hor: C("#c4e4f6"), light: 1.0,  sunVis: 1.0,  fog: [70, 280],  cloud: 0.45, cloudCol: 1.0 },
  cloudy: { mix: 0.62, top: C("#7f8c9c"), hor: C("#bcc4cc"), light: 0.42, sunVis: 0.25, fog: [45, 200],  cloud: 1.0,  cloudCol: 0.82 },
  rain:   { mix: 0.85, top: C("#58636f"), hor: C("#8d97a1"), light: 0.2,  sunVis: 0.0,  fog: [16, 95],   cloud: 1.0,  cloudCol: 0.6 },
  storm:  { mix: 0.95, top: C("#2a303b"), hor: C("#4f5763"), light: 0.05, sunVis: 0.0,  fog: [12, 75],   cloud: 1.0,  cloudCol: 0.42 },
  snow:   { mix: 0.75, top: C("#a6b1be"), hor: C("#dde3ea"), light: 0.38, sunVis: 0.12, fog: [14, 85],   cloud: 1.0,  cloudCol: 0.95 },
  fog:    { mix: 0.7,  top: C("#a7b2bc"), hor: C("#cfd5da"), light: 0.4,  sunVis: 0.3,  fog: [2, 30],    cloud: 0.6,  cloudCol: 0.95 },
};

// water: one surface per chunk; aShore 0 = open water .. 1 = the shore, aDeep 1 = deep, aRiver 1 = flowing
const WATER_VERT = `
uniform float uTime; attribute float aShore; attribute float aDeep; attribute float aRiver;
varying float vShore; varying float vDeep; varying float vRiver; varying vec3 vWPos;
#include <fog_pars_vertex>
void main() {
  vec3 p = position; vec4 wp = modelMatrix * vec4(p, 1.0);
  wp.y += (sin(wp.x * 1.1 + uTime * 1.3) + sin(wp.z * 1.4 - uTime * 1.1)) * 0.02 * (1.0 - aShore);
  vShore = aShore; vDeep = aDeep; vRiver = aRiver; vWPos = wp.xyz;
  vec4 mvPosition = viewMatrix * wp; gl_Position = projectionMatrix * mvPosition;
  #include <fog_vertex>
}`;
const WATER_FRAG = `
uniform float uTime, uSpec; uniform vec3 uDeep, uShallow, uSky, uSunDir, uSunCol, uAmb, uFoam;
varying float vShore; varying float vDeep; varying float vRiver; varying vec3 vWPos;
#include <fog_pars_fragment>
void wave(vec2 q, vec2 k, float a, float w, inout vec2 g) { g += a * k * cos(dot(k, q) + w * uTime); }
float h21(vec2 p) { return fract(sin(dot(p, vec2(41.3, 289.1))) * 43758.5453); }
float vn(vec2 p) { vec2 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);
  return mix(mix(h21(i), h21(i + vec2(1, 0)), f.x), mix(h21(i + vec2(0, 1)), h21(i + vec2(1, 1)), f.x), f.y); }
void main() {
  vec2 q = vWPos.xz; vec2 g = vec2(0.0);
  float fl = vRiver * uTime * 0.6;
  wave(q + fl, vec2(1.1, 0.0), 0.025, 1.3, g); wave(q, vec2(0.0, 1.4), 0.025, -1.1, g);
  wave(q, vec2(2.3, 1.7), 0.014, 2.1, g); wave(q, vec2(-3.1, 2.6), 0.010, 2.7, g);
  wave(q, vec2(5.3, -4.1), 0.006, 3.5, g); wave(q, vec2(-7.0, 6.2), 0.005, 4.1, g);
  vec3 n = normalize(vec3(-g.x * 2.4, 1.0, -g.y * 2.4));
  vec3 V = normalize(cameraPosition - vWPos);
  float fres = 0.03 + 0.97 * pow(1.0 - max(dot(n, V), 0.0), 5.0);
  float depth = clamp(vDeep * (1.0 - vShore), 0.0, 1.0);
  vec3 base = mix(uShallow, uDeep, smoothstep(0.1, 0.9, depth)) * uAmb;
  vec3 col = mix(base, uSky, clamp(fres * 1.1, 0.0, 0.75));
  vec3 H = normalize(V + uSunDir);
  float s = pow(max(dot(n, H), 0.0), 220.0) * uSpec * smoothstep(90.0, 15.0, length(cameraPosition - vWPos));
  col += uSunCol * s * 4.0;
  // rivers: soft streaks drifting downstream
  float st = vn(vec2(q.x * 1.3 + q.y * 0.4 - uTime * 0.9, q.y * 2.6 - q.x * 0.5)) ;
  col += uFoam * smoothstep(0.72, 0.95, st) * 0.18 * vRiver;
  float fn = sin(q.x * 5.0 + uTime * 1.2) * sin(q.y * 4.3 - uTime * 0.9) * 0.5 + 0.5;
  float foam = smoothstep(0.62, 0.8, vShore + fn * 0.12 - 0.05);
  col = mix(col, uFoam, foam * 0.55);
  float a = mix(mix(0.6, 0.9, depth), 0.97, fres); a = max(a, foam * 0.75);
  gl_FragColor = vec4(col, a);
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
  #include <fog_fragment>
}`;

// ───────────────────────────────────────────────────────────── palettes
const BIO3 = {   // [main, second (patches), grassy 0..1]
  ocean: ["#c8b98c", "#b3a57b", 0], lake: ["#8e8a66", "#7d7a5a", 0], beach: ["#ead9a3", "#e0cc92", 0],
  meadow: ["#84bd57", "#9cc95f", 1], grassland: ["#a3bb58", "#b8c467", 1], forest: ["#5c9140", "#6c9a45", 1],
  pine_forest: ["#5a7348", "#6a7a4c", 0.6], jungle: ["#3f8c43", "#4f9a46", 1], swamp: ["#62784a", "#6f7c50", 0.8],
  desert: ["#e6c88e", "#ddb97b", 0], savanna: ["#c9b45c", "#d3bd6a", 0.7], tundra: ["#9fae95", "#b4bca6", 0.4],
  snow: ["#eef3f8", "#e2eaf3", 0], mountain: ["#8a837b", "#9a9287", 0], rock: ["#9c9284", "#8d8478", 0],
};
const BIO3C = {}; for (const [k, v] of Object.entries(BIO3)) BIO3C[k] = [C(v[0]), C(v[1]), v[2]];
const ROCK_C = C("#7d766d"), SNOW_C = C("#f0f4f9"), DAMP_C = C("#b8a676"), BED_C = C("#6d6a4e");
const SEASON_T = {
  spring: { grass: C("#a8ffb0").multiplyScalar(1.0).lerp(C("#ffffff"), 0.75), autumn: 0, bare: 0, snow: 0 },
  summer: { grass: C("#ffffff"), autumn: 0, bare: 0, snow: 0 },
  autumn: { grass: C("#f0d090"), autumn: 0.85, bare: 0, snow: 0 },
  winter: { grass: C("#c8cfc0"), autumn: 0.3, bare: 0.75, snow: 0.6 },
};
const SKY_SPRITE = C("#ffe7a8");

// ───────────────────────────────────────────────────────────── module state
const S = {
  inited: false, paused: false, quality: "high", mode: "watch",
  container: null, renderer: null, scene: null, camera: null,
  meta: null, chunks: new Map(), cdat: new Map(), jobs: [], focusKey: "", lastFocus: null,
  kinds: {}, ents: new Map(), entObjs: new Map(), entsVersion: 0, animals: new Map(), places: [],
  zenData: null, spriteData: null, visitorData: null, studio: null, home: null, roofs: new Map(), roofWant: [],
  live: { phase: "day", sun: 0.35, season: "summer", weather: "clear", light: 1 },
  env: null, labels: new Map(), layer: null,
  cam: { yaw: -0.65, pitch: 0.62, dist: 14, tYaw: -0.65, tPitch: 0.62, tDist: 14, target: new THREE.Vector3(0.5, 2, 0.5), free: new THREE.Vector3(0.5, 2, 0.5), focus: "synth", fp: false },
  local: { x: 0, z: 0, y: 0, vx: 0, vz: 0, hop: 0, hv: 0, facing: "south", heading: 0, init: false, lastSend: 0, wasMoving: false },
  keys: new Set(), locked: false, drag: null, pointers: new Map(), prompt: null, interactTarget: null,
  stats: { fps: 0, drawCalls: 0, triangles: 0, ms: 0, frames: 0, acc: 0, msAcc: 0, last: 0, jobMax: 0, frameMax: 0, built: 0 },
  lastFrame: 0, raf: 0,
};
const World3D = {
  onMove: null, onAction: null, onPick: null,
  init, full, delta, setMode, setQuality, focusOn, pause, stats,
};

// ───────────────────────────────────────────────────────────── init
function init(container, opts = {}) {
  if (S.inited) return World3D;
  S.inited = true; S.container = container; S.quality = opts.quality === "low" ? "low" : "high";
  if (getComputedStyle(container).position === "static") container.style.position = "relative";
  container.classList.add("w3d-root");

  const r = S.renderer = new THREE.WebGLRenderer({ antialias: S.quality === "high", powerPreference: "low-power", alpha: false });
  r.setPixelRatio(Math.min(window.devicePixelRatio || 1, DPR_CAP[S.quality]));
  r.toneMapping = THREE.ACESFilmicToneMapping; r.toneMappingExposure = 1.05;
  r.outputColorSpace = THREE.SRGBColorSpace;
  r.shadowMap.enabled = S.quality === "high"; r.shadowMap.type = THREE.PCFSoftShadowMap;
  r.domElement.className = "w3d-canvas"; r.domElement.tabIndex = 0;
  container.appendChild(r.domElement);

  const scene = S.scene = new THREE.Scene();
  scene.fog = new THREE.Fog(0xc4e4f6, 40, 90);
  S.camera = new THREE.PerspectiveCamera(50, 1, 0.08, 1500);

  S.sun = new THREE.DirectionalLight(0xffffff, 2.5);
  S.sun.shadow.mapSize.set(2048, 2048); S.sun.shadow.bias = -0.0005; S.sun.shadow.normalBias = 0.04;
  S.sun.castShadow = true; scene.add(S.sun, S.sun.target);
  S.hemi = new THREE.HemisphereLight(0xd6e9ff, 0x857f55, 1.1); scene.add(S.hemi);
  makeLightPool();

  S.skyMat = new THREE.ShaderMaterial({
    vertexShader: SKY_VERT, fragmentShader: SKY_FRAG, side: THREE.BackSide, depthWrite: false, depthTest: false, fog: false,
    uniforms: { uTop: { value: new THREE.Color() }, uHor: { value: new THREE.Color() }, uBot: { value: new THREE.Color() },
      uSunDir: { value: new THREE.Vector3(0, 1, 0) }, uSunCol: { value: new THREE.Color() }, uMoonDir: { value: new THREE.Vector3(0, -1, 0) },
      uStars: { value: 0 }, uTime: U.time, uSunVis: { value: 1 }, uMoonVis: { value: 0 } },
  });
  S.sky = new THREE.Mesh(new THREE.SphereGeometry(900, 32, 16), S.skyMat);
  S.sky.renderOrder = -1000; S.sky.frustumCulled = false; scene.add(S.sky);

  S.waterMat = new THREE.ShaderMaterial({
    vertexShader: WATER_VERT, fragmentShader: WATER_FRAG, transparent: true, depthWrite: false, fog: true,
    uniforms: Object.assign(THREE.UniformsUtils.merge([THREE.UniformsLib.fog]), {
      uTime: U.time, uSpec: { value: 1 }, uDeep: { value: C("#1b5878") }, uShallow: { value: C("#45a8a8") },
      uSky: { value: new THREE.Color() }, uSunDir: { value: new THREE.Vector3() }, uSunCol: { value: new THREE.Color() },
      uAmb: { value: new THREE.Color(1, 1, 1) }, uFoam: { value: new THREE.Color(1, 1, 1) } }),
  });
  S.terrainMat = lambert({ vertexColors: true }, { snow: 1, veg: true, key: "terrain" });
  S.featMat = lambert({ vertexColors: true }, { snow: 0.8, sway: true, veg: true, key: "feat" });
  S.propMat = lambert({ vertexColors: true }, { snow: 0.6, key: "prop" });
  S.plainMat = lambert({ vertexColors: true }, { snow: 0, key: "plain" });

  S.glowTex = radialTex([[0, "rgba(255,255,255,1)"], [0.25, "rgba(255,255,255,.55)"], [0.6, "rgba(255,255,255,.12)"], [1, "rgba(255,255,255,0)"]]);
  S.blobTex = radialTex([[0, "rgba(0,0,0,.5)"], [0.55, "rgba(0,0,0,.28)"], [1, "rgba(0,0,0,0)"]]);
  makeAtlas();
  templates();
  S.entBB = new Billboards(S.atlasTex, { mode: "cyl", cut: true, lit: true, cap: 256, a2c: S.quality === "high" });
  S.blobBB = new Billboards(S.blobTex, { mode: "flat", lit: false, cap: 256 });
  S.glowBB = new Billboards(S.glowTex, { mode: "sph", additive: true, lit: false, cap: 256 });
  S.glowBB.mesh.renderOrder = 5;
  S.fxBB = new Billboards(S.atlasTex, { mode: "sph", lit: false, cap: 64 }); S.fxBB.mesh.renderOrder = 6;
  scene.add(S.entBB.group, S.blobBB.group, S.glowBB.group, S.fxBB.group);
  S.world = new THREE.Group(); scene.add(S.world);

  makeWeather();
  makeClouds();
  makeFireflies();
  makeSynth();
  makeSprite();
  S.avatar = makeOrb("#ffcf7a", "#e0702a", "#3a1d08", 0.2); S.avatar.group.visible = false; scene.add(S.avatar.group);
  S.env = makeEnv();

  const layer = S.layer = document.createElement("div"); layer.className = "w3d-layer"; container.appendChild(layer);
  S.prompt = document.createElement("div"); S.prompt.className = "w3d-prompt"; S.prompt.hidden = true; container.appendChild(S.prompt);
  S.cross = document.createElement("div"); S.cross.className = "w3d-crosshair"; S.cross.hidden = true; container.appendChild(S.cross);
  S.hint = document.createElement("div"); S.hint.className = "w3d-hint"; S.hint.hidden = true; container.appendChild(S.hint);
  S.loading = document.createElement("div"); S.loading.className = "w3d-loading"; S.loading.textContent = "The world is taking shape…"; container.appendChild(S.loading);

  bindInput();
  const ro = new ResizeObserver(resize); ro.observe(container); resize();
  document.addEventListener("pointerlockchange", () => { S.locked = document.pointerLockElement === S.renderer.domElement; updateHud(); });
  const C2 = window.Chunks;
  if (C2) {
    C2.meta().then((m) => { S.meta = m; if (!S.home && m.home) S.home = m.home; S.focusKey = ""; }).catch((e) => console.warn("world_meta:", e));
    C2.onLoad((c) => { prepare(c); S.focusKey = ""; });
  }
  S.lastFrame = performance.now();
  S.raf = requestAnimationFrame(frame);
  return World3D;
}

function resize() {
  const w = Math.max(1, S.container.clientWidth), h = Math.max(1, S.container.clientHeight);
  S.renderer.setSize(w, h, false);
  S.renderer.domElement.style.width = "100%"; S.renderer.domElement.style.height = "100%";
  S.camera.aspect = w / h; S.camera.updateProjectionMatrix(); S.vw = w; S.vh = h;
}
function makeLightPool() {
  if (S.pool) for (const l of S.pool) S.scene.remove(l);
  if (S.adaLight) S.scene.remove(S.adaLight);
  if (S.spriteLight) S.scene.remove(S.spriteLight);
  S.adaLight = new THREE.PointLight(0x8fb0ff, 3, 6, 1.6); S.scene.add(S.adaLight);
  S.spriteLight = new THREE.PointLight(0xffe2a0, 2, 7, 1.5); S.scene.add(S.spriteLight);
  S.pool = [];
  const n = S.quality === "high" ? 3 : 1;
  for (let i = 0; i < n; i++) { const l = new THREE.PointLight(0xffa04a, 0, 9, 1.5); S.scene.add(l); S.pool.push(l); }
}

// ───────────────────────────────────────────────────────────── terrain data (from window.Chunks)
const ckey = (cx, cy) => cx + "," + cy;
const BLOCK_RE = /^(oak|birch|pine|palm|jungle_tree|dead_tree|apple_tree|acacia|cactus|berry_bush|bush|rock|boulder|wall|stone_wall|cave_wall|standing_stone|well|cairn)$/;
// per chunk: bed and water heights in world units, and which tiles block walking
function prepare(c) {
  if (!S.meta) { const m = window.Chunks?.st.meta; if (m) S.meta = m; else return null; }
  const k = ckey(c.cx, c.cy); let d = S.cdat.get(k);
  if (d && d.c === c) return d;
  const n = N * N, bed = new Float32Array(n), wat = new Float32Array(n), blk = new Uint8Array(n), F = S.meta.FEATURES || [];
  for (let i = 0; i < n; i++) {
    // h is the ground (the bed under water); the sea and lakes lie at 0, rivers and pools a little above their bed
    const w = c.water[i], h = c.h[i];
    if (w) { const sy = (h < 0 ? 0 : h + 5) * VS; wat[i] = sy; bed[i] = Math.min(h * VS, sy - (w === 2 ? 0.45 : 0.1)); }
    else { wat[i] = -1e9; bed[i] = h * VS; }
    blk[i] = w === 2 || BLOCK_RE.test(F[c.feat[i]] || "") ? 1 : 0;
  }
  d = { c, bed, wat, blk, cx: c.cx, cy: c.cy };
  S.cdat.set(k, d);
  return d;
}
function dat(cx, cy) {
  const k = ckey(cx, cy), d = S.cdat.get(k); if (d) return d;
  const c = window.Chunks?.peek(cx, cy); return c ? prepare(c) : null;
}
function tileRef(x, y) {
  const cx = Math.floor(x / N), cy = Math.floor(y / N), d = dat(cx, cy);
  return d ? [d, (y - cy * N) * N + (x - cx * N)] : null;
}
function bedAt(x, y, fb = S.lastY ?? 0) { const r = tileRef(x, y); return r ? r[0].bed[r[1]] : fb; }
function waterAt(x, y) { const r = tileRef(x, y); return r ? r[0].wat[r[1]] : -1e9; }
// smooth ground height at a world point (bilinear over tile centres)
function groundY(wx, wz) {
  const u = wx - 0.5, v = wz - 0.5, x0 = Math.floor(u), y0 = Math.floor(v), fx = u - x0, fy = v - y0;
  const a = bedAt(x0, y0), b = bedAt(x0 + 1, y0, a), c = bedAt(x0, y0 + 1, a), d = bedAt(x0 + 1, y0 + 1, a);
  const y = lerp(lerp(a, b, fx), lerp(c, d, fx), fy);
  S.lastY = y; return y;
}
function standY(wx, wz) { return Math.max(groundY(wx, wz), waterAt(Math.floor(wx), Math.floor(wz)) - 0.05); }
function blockedTile(x, y) { const r = tileRef(x, y); return r ? !!r[0].blk[r[1]] : false; }
function infoAt(x, y) {
  const r = tileRef(x, y); if (!r) return null;
  const [d, i] = r, B = S.meta?.BIOMES || [], F = S.meta?.FEATURES || [];
  return { biome: B[d.c.biome[i]] || "", feature: d.c.feat[i] ? F[d.c.feat[i]] || "" : "", water: d.c.water[i], h: d.c.h[i] };
}

// ───────────────────────────────────────────────────────────── geometry buffers
class Buf {
  constructor(cap = 4096) { this.n = 0; this.alloc(cap); }
  alloc(cap) {
    const o = this; const grow = (a, k) => { const b = new Float32Array(cap * k); if (a) b.set(a.subarray(0, o.n * k)); return b; };
    this.p = grow(this.p, 3); this.no = grow(this.no, 3); this.c = grow(this.c, 3); this.v = grow(this.v, 2); this.s = grow(this.s, 1); this.cap = cap;
  }
  need(k) { if (this.n + k > this.cap) this.alloc(Math.max(this.cap * 2, this.n + k + 1024)); }
  geometry(sphere) {
    if (!this.n) return null;
    const g = new THREE.BufferGeometry(), n = this.n;
    g.setAttribute("position", new THREE.BufferAttribute(this.p.subarray(0, n * 3), 3));
    g.setAttribute("normal", new THREE.BufferAttribute(this.no.subarray(0, n * 3), 3));
    g.setAttribute("color", new THREE.BufferAttribute(this.c.subarray(0, n * 3), 3));
    g.setAttribute("aVeg", new THREE.BufferAttribute(this.v.subarray(0, n * 2), 2));
    g.setAttribute("aSway", new THREE.BufferAttribute(this.s.subarray(0, n), 1));
    if (sphere) g.boundingSphere = sphere; else g.computeBoundingSphere();
    return g;
  }
}
// a template: a few low-poly parts merged, flat-shaded, in object space (y up, standing on y = 0)
const GEO = {};
function flatGeo(key, make) {
  let g = GEO[key]; if (g) return g;
  g = make(); g = g.index ? g.toNonIndexed() : g; g.computeVertexNormals(); GEO[key] = g; return g;
}
class Tpl {
  constructor() { this.p = []; this.no = []; this.c = []; this.leaf = []; this.sw = []; this.tint = []; }
  part(geo, m, color, { leaf = 0, sway = 0, tint = 0 } = {}) {
    const g = geo.clone(); g.applyMatrix4(m);
    const P = g.attributes.position.array, Nn = g.attributes.normal.array;
    for (let i = 0; i < P.length; i += 3) {
      this.p.push(P[i], P[i + 1], P[i + 2]); this.no.push(Nn[i], Nn[i + 1], Nn[i + 2]);
      const f = 0.94 + hash2(i, P.length, 3) * 0.12;
      this.c.push(color.r * f, color.g * f, color.b * f); this.leaf.push(leaf); this.tint.push(tint);
      this.sw.push(sway * Math.max(0, P[i + 1]) * 0.05);
    }
    g.dispose(); return this;
  }
  done() {
    this.P = new Float32Array(this.p); this.NO = new Float32Array(this.no); this.CC = new Float32Array(this.c);
    this.L = new Uint8Array(this.leaf); this.SW = new Float32Array(this.sw); this.TI = new Uint8Array(this.tint); this.n = this.P.length / 3;
    return this;
  }
}
const M = (x = 0, y = 0, z = 0, sx = 1, sy = sx, sz = sx, ry = 0, rx = 0, rz = 0) =>
  new THREE.Matrix4().compose(new THREE.Vector3(x, y, z), new THREE.Quaternion().setFromEuler(new THREE.Euler(rx, ry, rz)), new THREE.Vector3(sx, sy, sz));
// put one template into a buffer: scaled, turned about y, moved
function emit(b, t, x, y, z, s, sy, ry, tint, leafVar, grassy = 0) {
  b.need(t.n);
  const cs = Math.cos(ry), sn = Math.sin(ry), P = t.P, NO = t.NO, CC = t.CC;
  let o = b.n;
  for (let i = 0; i < t.n; i++) {
    const i3 = i * 3, px = P[i3] * s, py = P[i3 + 1] * sy, pz = P[i3 + 2] * s, o3 = o * 3;
    b.p[o3] = x + px * cs + pz * sn; b.p[o3 + 1] = y + py; b.p[o3 + 2] = z - px * sn + pz * cs;
    const nx = NO[i3], nz = NO[i3 + 2];
    b.no[o3] = nx * cs + nz * sn; b.no[o3 + 1] = NO[i3 + 1]; b.no[o3 + 2] = -nx * sn + nz * cs;
    if (t.TI[i] && tint) { b.c[o3] = tint.r; b.c[o3 + 1] = tint.g; b.c[o3 + 2] = tint.b; }
    else { const f = tint && !t.TI[i] ? tint.f || 1 : 1; b.c[o3] = CC[i3] * f; b.c[o3 + 1] = CC[i3 + 1] * f; b.c[o3 + 2] = CC[i3 + 2] * f; }
    b.v[o * 2] = t.L[i] ? leafVar : 0; b.v[o * 2 + 1] = t.L[i] === 2 ? grassy : 0;
    b.s[o] = t.SW[i] * s; o++;
  }
  b.n = o;
}
// put one geometry into a buffer with a full matrix (for the few bigger things: places, the cabin)
function put(b, geo, m, color, { sway = 0, leaf = 0 } = {}) {
  const P = geo.attributes.position.array, Nn = geo.attributes.normal.array, n = P.length / 3;
  b.need(n);
  const nm = new THREE.Matrix3().getNormalMatrix(m), e = m.elements, ne = nm.elements;
  for (let i = 0; i < n; i++) {
    const x = P[i * 3], y = P[i * 3 + 1], z = P[i * 3 + 2], o = b.n + i, o3 = o * 3;
    b.p[o3] = e[0] * x + e[4] * y + e[8] * z + e[12]; b.p[o3 + 1] = e[1] * x + e[5] * y + e[9] * z + e[13]; b.p[o3 + 2] = e[2] * x + e[6] * y + e[10] * z + e[14];
    const a = Nn[i * 3], bb = Nn[i * 3 + 1], c = Nn[i * 3 + 2];
    let nx = ne[0] * a + ne[3] * bb + ne[6] * c, ny = ne[1] * a + ne[4] * bb + ne[7] * c, nz = ne[2] * a + ne[5] * bb + ne[8] * c;
    const l = Math.hypot(nx, ny, nz) || 1; b.no[o3] = nx / l; b.no[o3 + 1] = ny / l; b.no[o3 + 2] = nz / l;
    const f = 0.95 + hash2(i, n, 5) * 0.1;
    b.c[o3] = color.r * f; b.c[o3 + 1] = color.g * f; b.c[o3 + 2] = color.b * f;
    b.v[o * 2] = leaf; b.v[o * 2 + 1] = 0; b.s[o] = sway * Math.max(0, y) * 0.05;
  }
  b.n += n;
}
const box = () => flatGeo("box", () => new THREE.BoxGeometry(1, 1, 1));
const cyl = (seg = 6, top = 1, open = true) => flatGeo(`cyl${seg}_${top}_${open}`, () => new THREE.CylinderGeometry(0.5 * top, 0.5, 1, seg, 1, open).translate(0, 0.5, 0));
const cone = (seg = 7) => flatGeo("cone" + seg, () => new THREE.ConeGeometry(0.5, 1, seg, 1, true).translate(0, 0.5, 0));
const ico = (d = 0) => flatGeo("ico" + d, () => new THREE.IcosahedronGeometry(0.5, d));
const dode = () => flatGeo("dode", () => new THREE.DodecahedronGeometry(0.5, 0));
const blade = () => flatGeo("blade", () => { const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.Float32BufferAttribute([-0.5, 0, 0, 0.5, 0, 0, 0, 1, 0, 0.5, 0, 0, -0.5, 0, 0, 0, 1, 0], 3)); return g; });

// ───────────────────────────────────────────────────────────── feature templates (low poly)
const TPL = {};
const WOOD0 = new THREE.Color("#8a643f");
function templates() {
  if (TPL.oak) return TPL;
  const bark = C("#6b4a30"), leaf = C("#4d8d39"), leaf2 = C("#5d9c40");
  TPL.oak = new Tpl().part(cyl(6, 0.7), M(0, 0, 0, 0.24, 1.15, 0.24), bark, { sway: 0.2 })
    .part(ico(0), M(0, 1.45, 0, 1.25, 1.05, 1.25), leaf, { leaf: 1, sway: 1 }).part(ico(0), M(0.35, 1.2, 0.2, 0.85), leaf2, { leaf: 1, sway: 1 })
    .part(ico(0), M(-0.32, 1.25, -0.22, 0.8), leaf2, { leaf: 1, sway: 1 }).done();
  TPL.birch = new Tpl().part(cyl(6, 0.75), M(0, 0, 0, 0.15, 1.6, 0.15), C("#e9e5da"), { sway: 0.3 })
    .part(cyl(6, 1), M(0, 0.55, 0, 0.152, 0.05, 0.152), C("#3a3632")).part(cyl(6, 1), M(0, 1.0, 0, 0.14, 0.04, 0.14), C("#3a3632"))
    .part(ico(0), M(0, 1.75, 0, 0.8, 1.25, 0.8), C("#86bf4a"), { leaf: 1, sway: 1.2 }).part(ico(0), M(0.18, 1.4, 0.1, 0.55, 0.8, 0.55), C("#9ac954"), { leaf: 1, sway: 1.2 }).done();
  const pine = C("#2f5e3c"), pine2 = C("#376a42");
  TPL.pine = new Tpl().part(cyl(5, 0.6), M(0, 0, 0, 0.18, 0.7, 0.18), C("#5b4131"))
    .part(cone(7), M(0, 0.45, 0, 1.25, 1.0, 1.25), pine, { sway: 0.6 }).part(cone(7), M(0, 0.95, 0, 1.0, 0.9, 1.0), pine2, { sway: 0.6 })
    .part(cone(7), M(0, 1.45, 0, 0.72, 0.85, 0.72), pine, { sway: 0.6 }).done();
  const palm = new Tpl(), pt = C("#8a6a46");
  for (let i = 0; i < 5; i++) palm.part(cyl(5, 0.88), M(i * i * 0.025, i * 0.42, 0, 0.17 - i * 0.012, 0.44, 0.17 - i * 0.012, 0, 0, -i * 0.06), pt, { sway: 0.4 });
  for (let k = 0; k < 7; k++) { const a = k / 7 * Math.PI * 2; palm.part(cone(4), M(0.4 + Math.cos(a) * 0.45, 2.05, Math.sin(a) * 0.45, 0.32, 1.2, 0.08, -a, Math.PI / 2 + 0.35, 0).multiply(M(0, 0, 0, 1, 1, 1, 0, 0, 0)), C("#4c9a3a"), { leaf: 0, sway: 1.5 }); }
  TPL.palm = palm.done();
  const cac = C("#4f8a4a");
  TPL.cactus = new Tpl().part(cyl(7, 0.9, false), M(0, 0, 0, 0.32, 1.4, 0.32), cac, { sway: 0.05 })
    .part(cyl(6, 1, false), M(0.16, 0.55, 0, 0.14, 0.36, 0.14, 0, 0, -Math.PI / 2), cac).part(cyl(6, 0.8, false), M(0.5, 0.48, 0, 0.14, 0.45, 0.14), cac)
    .part(cyl(6, 1, false), M(-0.16, 0.8, 0, 0.12, 0.3, 0.12, 0, 0, Math.PI / 2), cac).part(cyl(6, 0.8, false), M(-0.44, 0.74, 0, 0.12, 0.34, 0.12), cac).done();
  TPL.jungle = new Tpl().part(cyl(6, 0.6), M(0, 0, 0, 0.3, 2.5, 0.3), C("#7a5a3c"), { sway: 0.15 })
    .part(ico(0), M(0, 2.6, 0, 1.9, 0.75, 1.9), C("#2f7d3a"), { leaf: 0, sway: 0.8 }).part(ico(0), M(0.5, 2.25, 0.3, 1.2, 0.6, 1.2), C("#3a8a40"), { sway: 0.8 })
    .part(ico(0), M(-0.5, 2.1, -0.35, 1.1, 0.55, 1.1), C("#2a7234"), { sway: 0.8 }).done();
  const dw = C("#6e5c4c");
  TPL.dead = new Tpl().part(cyl(5, 0.5), M(0, 0, 0, 0.2, 1.5, 0.2), dw, { sway: 0.1 })
    .part(cyl(4, 0.4), M(0.05, 0.8, 0, 0.08, 0.6, 0.08, 0, 0, -0.8), dw, { sway: 0.2 }).part(cyl(4, 0.4), M(-0.03, 1.05, 0.02, 0.07, 0.5, 0.07, 0.5, 0, 0.9), dw, { sway: 0.2 })
    .part(cyl(4, 0.4), M(0, 1.3, 0, 0.06, 0.45, 0.06, 1.8, 0.6, 0), dw, { sway: 0.2 }).done();
  TPL.stump = new Tpl().part(cyl(7, 0.9, false), M(0, 0, 0, 0.36, 0.28, 0.36), C("#7a5a3c")).part(cyl(7, 1, false), M(0, 0.27, 0, 0.3, 0.02, 0.3), C("#c9a57a")).done();
  TPL.bush = new Tpl().part(ico(0), M(0, 0.25, 0, 0.85, 0.6, 0.85), C("#4a8a3a"), { leaf: 1, sway: 1.5 }).part(ico(0), M(0.25, 0.2, 0.1, 0.55, 0.45, 0.55), C("#58963f"), { leaf: 1, sway: 1.5 }).done();
  const bb = new Tpl().part(ico(0), M(0, 0.26, 0, 0.85, 0.62, 0.85), C("#3f7f37"), { sway: 1.2 }).part(ico(0), M(0.22, 0.22, -0.1, 0.55, 0.45, 0.55), C("#4a8a3c"), { sway: 1.2 });
  for (let k = 0; k < 9; k++) { const a = k * 2.4, h = 0.18 + (k % 3) * 0.1; bb.part(ico(0), M(Math.cos(a) * 0.36, h, Math.sin(a) * 0.36, 0.08), C(k % 4 ? "#c7243c" : "#5a2a7a"), { sway: 1.2 }); }
  TPL.berry = bb.done();
  TPL.rock = new Tpl().part(dode(), M(0, 0.12, 0, 0.6, 0.38, 0.5), C("#8a847c")).part(dode(), M(0.2, 0.06, 0.12, 0.28, 0.2, 0.25), C("#7c766f")).done();
  TPL.boulder = new Tpl().part(dode(), M(0, 0.4, 0, 1.4, 1.0, 1.2), C("#8d867d")).part(dode(), M(0.55, 0.15, 0.3, 0.6, 0.45, 0.55), C("#7e776f")).done();
  const grass = new Tpl(), gc = C("#6faa3c");
  for (let k = 0; k < 6; k++) grass.part(blade(), M((hash2(k, 1) - 0.5) * 0.5, 0, (hash2(k, 2) - 0.5) * 0.5, 0.09, 0.45 + hash2(k, 3) * 0.25, 1, k * 1.1, (hash2(k, 4) - 0.5) * 0.5), shade(gc, 0.85 + hash2(k, 5) * 0.3), { leaf: 2, sway: 2.5 });
  TPL.grass = grass.done();
  const tuft = new Tpl();
  for (let k = 0; k < 3; k++) tuft.part(blade(), M((hash2(k, 7) - 0.5) * 0.3, 0, (hash2(k, 8) - 0.5) * 0.3, 0.08, 0.3, 1, k * 2.1, 0.2), shade(gc, 0.9 + hash2(k, 9) * 0.2), { leaf: 2, sway: 2.5 });
  TPL.tuft = tuft.done();
  const fl = new Tpl();
  for (let k = 0; k < 4; k++) fl.part(blade(), M((hash2(k, 11) - 0.5) * 0.4, 0, (hash2(k, 12) - 0.5) * 0.4, 0.07, 0.3, 1, k * 1.7, 0.2), gc, { leaf: 2, sway: 2 });
  for (let k = 0; k < 4; k++) { const x = (hash2(k, 13) - 0.5) * 0.5, z = (hash2(k, 14) - 0.5) * 0.5, h = 0.3 + hash2(k, 15) * 0.15;
    fl.part(cyl(3, 1), M(x, 0, z, 0.02, h, 0.02), C("#4f8a2f"), { sway: 2 }).part(ico(0), M(x, h, z, 0.13, 0.08, 0.13), C("#ffffff"), { sway: 2, tint: 1 }).part(ico(0), M(x, h + 0.02, z, 0.05), C("#f6d24a"), { sway: 2 }); }
  TPL.flowers = fl.done();
  const rd = new Tpl();
  for (let k = 0; k < 7; k++) { const x = (hash2(k, 21) - 0.5) * 0.6, z = (hash2(k, 22) - 0.5) * 0.6, h = 0.8 + hash2(k, 23) * 0.5;
    rd.part(blade(), M(x, 0, z, 0.06, h, 1, k * 1.3), C("#8fa24c"), { sway: 1.6 }); if (k % 2) rd.part(cyl(5, 1, false), M(x, h * 0.85, z, 0.05, 0.18, 0.05), C("#6b4428"), { sway: 1.6 }); }
  TPL.reeds = rd.done();
  TPL.drift = new Tpl().part(ico(1), M(0, 0, 0, 1.4, 0.36, 1.0), C("#f2f6fb")).done();
  TPL.apple = new Tpl().part(cyl(6, 0.7), M(0, 0, 0, 0.24, 1.0, 0.24), bark, { sway: 0.2 })
    .part(ico(0), M(0, 1.3, 0, 1.3, 1.0, 1.3), C("#4f9a3c"), { leaf: 1, sway: 1 }).part(ico(0), M(0.3, 1.05, 0.2, 0.8), leaf2, { leaf: 1, sway: 1 });
  for (let k = 0; k < 8; k++) { const a = k * 2.3; TPL.apple.part(ico(0), M(Math.cos(a) * 0.55, 1.05 + (k % 3) * 0.22, Math.sin(a) * 0.55, 0.11), C("#d43a2f"), { sway: 1 }); }
  TPL.apple.done();
  TPL.acacia = new Tpl().part(cyl(5, 0.6), M(0, 0, 0, 0.18, 1.6, 0.18, 0, 0, 0.12), C("#7a5a3c"), { sway: 0.2 })
    .part(ico(0), M(-0.15, 1.75, 0, 2.2, 0.38, 1.9), C("#6f9a3a"), { leaf: 1, sway: 0.8 }).part(ico(0), M(0.5, 1.6, 0.3, 1.2, 0.3, 1.1), C("#7aa43e"), { leaf: 1, sway: 0.8 }).done();
  const fern = new Tpl();
  for (let k = 0; k < 7; k++) fern.part(blade(), M(0, 0, 0, 0.16, 0.6, 1, k * 0.9, 0.7 + hash2(k, 41) * 0.3), C(k % 2 ? "#3f7a3a" : "#4a8a40"), { leaf: 2, sway: 2 });
  TPL.fern = fern.done();
  const logs = new Tpl().part(box(), M(0, -0.35, 0, 1.0, 0.7, 0.9), C("#7d766c"));
  for (let k = 0; k < 7; k++) logs.part(cyl(7, 1, true), M(0.52, 0.13 + k * 0.26, 0, 0.3, 1.04, 0.3, 0, 0, Math.PI / 2), C(k % 2 ? "#9a6c43" : "#8a5e3a"));
  TPL.wall = logs.done();
  TPL.stone_wall = new Tpl().part(box(), M(0, 0.55, 0, 1.0, 1.7, 0.85), C("#958d82")).part(box(), M(0.1, 1.45, 0.05, 0.7, 0.2, 0.7), C("#7d766c")).part(box(), M(0, -0.3, 0, 1.0, 0.6, 0.85), C("#7d766c")).done();
  TPL.door = new Tpl().part(box(), M(0, -0.3, 0, 1, 0.6, 0.9), C("#7d766c")).part(box(), M(0, 0.06, 0, 1, 0.12, 0.9), C("#b08458"))
    .part(box(), M(-0.44, 0.95, 0, 0.14, 1.9, 0.3), C("#6b4a30")).part(box(), M(0.44, 0.95, 0, 0.14, 1.9, 0.3), C("#6b4a30")).part(box(), M(0, 1.84, 0, 1.04, 0.18, 0.3), C("#5e412b")).done();
  TPL.floor = new Tpl().part(box(), M(0, -0.3, 0, 1, 0.6, 1), C("#7d766c")).part(box(), M(0, 0.06, 0, 1, 0.12, 1), C("#b08458")).part(box(), M(0, 0.125, 0.25, 1, 0.01, 0.03), C("#8a6440")).part(box(), M(0, 0.125, -0.25, 1, 0.01, 0.03), C("#8a6440")).done();
  TPL.cave_wall = new Tpl().part(dode(), M(0, 0.8, 0, 1.6, 2.2, 1.6), C("#7f7a74")).part(dode(), M(0.3, 1.6, -0.2, 1.1, 1.0, 1.1), C("#8c867e")).done();
  TPL.cave_floor = new Tpl().part(box(), M(0, 0.02, 0, 1, 0.05, 1), C("#4d4852")).done();
  TPL.rubble = new Tpl().part(dode(), M(0, 0.1, 0, 0.45, 0.3, 0.4), C("#958d82")).part(dode(), M(0.25, 0.08, 0.2, 0.32, 0.22, 0.3), C("#7d766c")).part(box(), M(-0.2, 0.08, -0.15, 0.4, 0.18, 0.25, 0.4), C("#8a8378")).done();
  TPL.standing_stone = new Tpl().part(box(), M(0, 0.9, 0, 0.55, 2.2, 0.36, 0, 0.04, 0.03), C("#9a958c")).part(box(), M(0, 2.02, 0, 0.45, 0.08, 0.3), C("#8a857e")).done();
  TPL.well = new Tpl().part(cyl(10, 1, false), M(0, -0.1, 0, 0.95, 0.75, 0.95), C("#958d82")).part(cyl(10, 1, false), M(0, 0.6, 0, 0.75, 0.03, 0.75), C("#1d3442"))
    .part(box(), M(-0.48, 0.8, 0, 0.08, 1.6, 0.08), WOOD0).part(box(), M(0.48, 0.8, 0, 0.08, 1.6, 0.08), WOOD0).part(box(), M(0, 1.55, 0, 1.05, 0.05, 0.05), C("#5a4030"))
    .part(box(), M(0, 1.75, -0.28, 1.2, 0.07, 0.7, 0, 0.75), C("#7a4b3a")).part(box(), M(0, 1.75, 0.28, 1.2, 0.07, 0.7, 0, -0.75), C("#7a4b3a")).done();
  const cairn = new Tpl(); for (let k = 0; k < 4; k++) cairn.part(dode(), M(0, 0.15 + k * 0.28, 0, 0.62 - k * 0.12, 0.3, 0.55 - k * 0.1, k * 1.3), C(k % 2 ? "#958d82" : "#7d766c"));
  TPL.cairn = cairn.done();
  const spring = new Tpl(); for (let k = 0; k < 8; k++) { const a = k / 8 * Math.PI * 2; spring.part(dode(), M(Math.cos(a) * 0.42, 0.05, Math.sin(a) * 0.42, 0.24, 0.18, 0.22, k), C(k % 2 ? "#958d82" : "#7d766c")); }
  spring.part(cyl(12, 1, false), M(0, 0.0, 0, 0.75, 0.06, 0.75), C("#62c6d8"));
  TPL.spring = spring.done();
  return TPL;
}
const FEAT_RULES = [
  [/^stump/, "stump", 0], [/^apple/, "apple", 1], [/^oak/, "oak", 1], [/^birch/, "birch", 1], [/pine|fir|spruce/, "pine", 0], [/^palm/, "palm", 0],
  [/^acacia/, "acacia", 1], [/cactus/, "cactus", 0], [/jungle/, "jungle", 0], [/dead/, "dead", 0], [/berry/, "berry", 0], [/bush|shrub/, "bush", 1],
  [/boulder/, "boulder", 0], [/^rock/, "rock", 0], [/flower/, "flowers", 0], [/reed|cattail/, "reeds", 0], [/fern/, "fern", 0],
  [/snow|drift/, "drift", 0], [/grass/, "grass", 0],
  [/^wall$/, "wall", 0, "wall"], [/^stone_wall$/, "stone_wall", 0, "wall"], [/^door$/, "door", 0, "wall"], [/^floor$/, "floor", 0, "flat"],
  [/^cave_wall$/, "cave_wall", 0, "flat"], [/^cave_floor$/, "cave_floor", 0, "flat"], [/^rubble$/, "rubble", 0, "flat"],
  [/standing_stone/, "standing_stone", 0, "flat"], [/^well$/, "well", 0, "flat"], [/^cairn$/, "cairn", 0, "flat"], [/^spring$/, "spring", 0, "flat"],
  [/tree/, "oak", 1],
];
const featRule = new Map();
function ruleFor(i) {
  let r = featRule.get(i); if (r !== undefined) return r;
  const name = S.meta?.FEATURES?.[i] || ""; r = null;
  for (const [re, t, leafy, struct] of FEAT_RULES) if (re.test(name)) { r = { t, leafy, struct, name }; break; }
  featRule.set(i, r); return r;
}
const FLOWER_C = ["#f3d34a", "#ec6a86", "#ffffff", "#b886ea", "#ff9f43", "#7fb0ff"].map(C);
const WALLISH = new Set(["wall", "stone_wall", "door"]);
const featAt = (x, y) => { const r = tileRef(x, y); return r ? S.meta?.FEATURES?.[r[0].c.feat[r[1]]] || "" : ""; };

// ───────────────────────────────────────────────────────────── chunk meshes, built a step at a time
function chunkJobs(ch) {
  const d = dat(ch.cx, ch.cy); if (!d) return [];
  const steps = [], T = (name, f) => { f.label = name; steps.push(f); };
  for (let r = 0; r < N; r += 8) T("terrain", () => buildTerrain(ch, d, r, r + 8));
  T("terrain-mesh", () => finishTerrain(ch)); T("water", () => buildWater(ch, d));
  for (let r = 0; r < N; r += 4) T("features", () => buildFeatures(ch, d, r, r + 4));
  T("features-mesh", () => finishFeatures(ch)); T("pois", () => buildPois(ch, d));
  return steps;
}
function neighbourhood(cx, cy) { for (const [a, b] of [[0, 0], [1, 0], [0, 1], [1, 1], [-1, 0], [0, -1]]) if (!dat(cx + a, cy + b)) return false; return true; }
const OCEAN_FLOOR = C("#c8b98c");
function buildTerrain(ch, d, r0, r1) {
  const V = N + 1, n = V * V;
  const tb = ch.tb || (ch.tb = { pos: new Float32Array(n * 3), nor: new Float32Array(n * 3), col: new Float32Array(n * 3), veg: new Float32Array(n * 2), sw: new Float32Array(n) });
  const { pos, nor, col, veg } = tb;
  const x0 = ch.cx * N, y0 = ch.cy * N, B = S.meta.BIOMES || [];
  const H = (i, j) => bedAt(x0 + i, y0 + j, d.bed[clamp(j, 0, N - 1) * N + clamp(i, 0, N - 1)]);
  const col1 = new THREE.Color(), col2 = new THREE.Color();
  for (let j = r0; j < (r1 >= N ? V : r1); j++) for (let i = 0; i < V; i++) {
    const k = j * V + i, gx = x0 + i, gy = y0 + j, y = H(i, j);
    pos[k * 3] = i + 0.5; pos[k * 3 + 1] = y; pos[k * 3 + 2] = j + 0.5;
    const nx = -(H(i + 1, j) - H(i - 1, j)) / 2, nz = -(H(i, j + 1) - H(i, j - 1)) / 2, l = Math.hypot(nx, 1, nz);
    nor[k * 3] = nx / l; nor[k * 3 + 1] = 1 / l; nor[k * 3 + 2] = nz / l;
    const r = tileRef(gx, gy) || [d, clamp(j, 0, N - 1) * N + clamp(i, 0, N - 1)], c = r[0].c, t = r[1];
    const bn = B[c.biome[t]] || "meadow", w = c.water[t], pal = BIO3C[bn] || BIO3C.meadow;
    const patchN = vnoise(gx / 7, gy / 7, 3) * 0.7 + vnoise(gx / 2.3, gy / 2.3, 4) * 0.3;
    col1.copy(pal[0]).lerp(pal[1], smooth(0.35, 0.75, patchN));
    col1.multiplyScalar(0.94 + hash2(gx, gy, 9) * 0.1);
    const steep = 1 - 1 / l;
    let grassy = pal[2];
    if (w) {
      col1.lerp(BED_C, w === 2 ? 0.7 : 0.4);
      if (bn === "ocean" || w === 2) col1.lerp(OCEAN_FLOOR, 0.35);
      grassy = 0;
    } else {
      let nearW = false;
      for (const [a, b] of DIR4) { const rr = tileRef(gx + a, gy + b); if (rr && rr[0].c.water[rr[1]]) { nearW = true; break; } }
      if (nearW && bn !== "beach") col1.lerp(DAMP_C, 0.4), grassy *= 0.6;
      const rk = smooth(0.32, 0.6, steep); if (rk > 0) { col1.lerp(col2.copy(ROCK_C).multiplyScalar(0.95 + patchN * 0.12), rk); grassy *= 1 - rk; }
      const sn = smooth(SNOWLINE, SNOWLINE + 2.5, y + (patchN - 0.5) * 1.5) * (1 - smooth(0.45, 0.75, steep));
      if (sn > 0 && bn !== "desert") { col1.lerp(SNOW_C, sn); grassy *= 1 - sn; }
    }
    col[k * 3] = col1.r; col[k * 3 + 1] = col1.g; col[k * 3 + 2] = col1.b;
    veg[k * 2 + 1] = grassy;
  }
}
function finishTerrain(ch) {
  const V = N + 1, x0 = ch.cx * N, y0 = ch.cy * N, { pos, nor, col, veg, sw } = ch.tb; ch.tb = null;
  const idx = new Uint16Array(N * N * 6); let o = 0;
  for (let j = 0; j < N; j++) for (let i = 0; i < N; i++) {
    const a = j * V + i, b = a + 1, c = a + V, e = c + 1;
    if (hash2(x0 + i, y0 + j, 1) < 0.5) { idx[o++] = a; idx[o++] = c; idx[o++] = b; idx[o++] = b; idx[o++] = c; idx[o++] = e; }
    else { idx[o++] = a; idx[o++] = c; idx[o++] = e; idx[o++] = a; idx[o++] = e; idx[o++] = b; }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(pos, 3)); g.setAttribute("normal", new THREE.BufferAttribute(nor, 3));
  g.setAttribute("color", new THREE.BufferAttribute(col, 3)); g.setAttribute("aVeg", new THREE.BufferAttribute(veg, 2)); g.setAttribute("aSway", new THREE.BufferAttribute(sw, 1));
  g.setIndex(new THREE.BufferAttribute(idx, 1)); g.computeBoundingSphere(); g.computeBoundingBox();
  const m = new THREE.Mesh(g, S.terrainMat); m.receiveShadow = true; m.name = "terrain";
  ch.group.add(m); ch.terrain = m;
}
function buildWater(ch, d) {
  const V = N + 1, x0 = ch.cx * N, y0 = ch.cy * N;
  let any = false;
  for (let j = 0; j < V && !any; j++) for (let i = 0; i < V; i++) if (waterAt(x0 + i, y0 + j) > -1e8) { any = true; break; }
  if (!any) return;
  const n = V * V, pos = new Float32Array(n * 3), sh = new Float32Array(n), dp = new Float32Array(n), rv = new Float32Array(n), wet = new Uint8Array(n);
  for (let j = 0; j < V; j++) for (let i = 0; i < V; i++) {
    const k = j * V + i, gx = x0 + i, gy = y0 + j, r = tileRef(gx, gy);
    let y = r ? r[0].wat[r[1]] : -1e9, w = r ? r[0].c.water[r[1]] : 0;
    if (y < -1e8) {    // a shore vertex: the mean level of the water next to it (hidden under the bank)
      let s = 0, c = 0, nd = 0;
      for (let b = -1; b <= 1; b++) for (let a = -1; a <= 1; a++) { const q = tileRef(gx + a, gy + b); if (q && q[0].wat[q[1]] > -1e8) { s += q[0].wat[q[1]]; c++; nd += q[0].c.water[q[1]] === 2 ? 1 : 0; } }
      y = c ? s / c : (r ? r[0].bed[r[1]] : 0); sh[k] = 1; dp[k] = 0;
    } else { wet[k] = 1; sh[k] = 0; dp[k] = w === 2 ? 1 : w === 3 ? 0.5 : 0.25; rv[k] = w === 3 ? 1 : 0; }
    pos[k * 3] = i + 0.5; pos[k * 3 + 1] = y; pos[k * 3 + 2] = j + 0.5;
  }
  // shallow water near the bank fades toward the shore colour
  for (let j = 0; j < V; j++) for (let i = 0; i < V; i++) {
    const k = j * V + i; if (!wet[k]) continue;
    let land = 0; for (const [a, b] of DIR4) { const ii = i + a, jj = j + b; if (ii >= 0 && jj >= 0 && ii < V && jj < V && !wet[jj * V + ii]) land++; else if (!(ii >= 0 && jj >= 0 && ii < V && jj < V)) { if (waterAt(x0 + ii, y0 + jj) < -1e8) land++; } }
    if (land) sh[k] = 0.45;
  }
  const idx = []; for (let j = 0; j < N; j++) for (let i = 0; i < N; i++) {
    const a = j * V + i, b = a + 1, c = a + V, e = c + 1;
    if (wet[a] || wet[b] || wet[c] || wet[e]) idx.push(a, c, b, b, c, e);
  }
  if (!idx.length) return;
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(pos, 3)); g.setAttribute("aShore", new THREE.BufferAttribute(sh, 1));
  g.setAttribute("aDeep", new THREE.BufferAttribute(dp, 1)); g.setAttribute("aRiver", new THREE.BufferAttribute(rv, 1));
  g.setIndex(idx); g.computeBoundingSphere();
  const m = new THREE.Mesh(g, S.waterMat); m.renderOrder = 2; m.name = "water";
  ch.group.add(m); ch.water = m;
}
function buildFeatures(ch, d, r0, r1) {
  templates();
  const b = ch.fb || (ch.fb = new Buf(16384)), x0 = ch.cx * N, y0 = ch.cy * N, B = S.meta.BIOMES || [], low = S.quality === "low";
  for (let j = r0; j < r1; j++) for (let i = 0; i < N; i++) {
    const t = j * N + i, gx = x0 + i, gy = y0 + j, f = d.c.feat[t], bn = B[d.c.biome[t]] || "";
    const h1 = hash2(gx, gy, 31), h2 = hash2(gx, gy, 32), h3 = hash2(gx, gy, 33);
    let rule = f ? ruleFor(f) : null;
    if (rule?.struct) {        // walls, floors, doors and the stones of old places: square on their tile
      const tpl = TPL[rule.t]; if (!tpl) continue;
      let ry = 0;
      if (rule.struct === "wall") ry = WALLISH.has(featAt(gx - 1, gy)) || WALLISH.has(featAt(gx + 1, gy)) ? 0 : Math.PI / 2;
      else if (/standing|cairn|rubble|cave_wall/.test(rule.t)) ry = h2 * Math.PI * 2;
      const sy = rule.t === "stone_wall" ? 0.35 + h1 * 0.9 : rule.t === "cave_wall" ? 0.8 + h1 * 0.6 : rule.t === "standing_stone" ? 0.8 + h1 * 0.5 : 1;
      emit(b, tpl, gx + 0.5 - x0, d.bed[t], gy + 0.5 - y0, rule.t === "cave_wall" ? 0.9 + h3 * 0.3 : 1, sy, ry, { f: 0.92 + h2 * 0.16 }, 0);
      continue;
    }
    if (!rule) {      // a little extra grass where the land is grassy (not a feature: just looks)
      if (low || d.c.water[t] || (BIO3[bn]?.[2] || 0) < 0.6 || h1 > 0.16) continue;
      rule = { t: "tuft" };
    }
    if (low && (rule.t === "grass" || rule.t === "flowers" || rule.t === "fern") && h1 < 0.5) continue;
    const tpl = TPL[rule.t]; if (!tpl) continue;
    const big = /oak|birch|pine|palm|jungle|dead|cactus|apple|acacia/.test(rule.t);
    const jx = (h1 - 0.5) * (big ? 0.35 : 0.6), jz = (h2 - 0.5) * (big ? 0.35 : 0.6);
    const wx = gx + 0.5 + jx, wz = gy + 0.5 + jz;
    let y = groundY(wx, wz);
    if (rule.t === "reeds" && d.c.water[t]) y = Math.max(y, d.wat[t] - 0.45);
    const s = (big ? 0.85 + h3 * 0.45 : 0.8 + h3 * 0.5) * (rule.t === "pine" && /snow|tundra|mountain/.test(bn) ? 0.85 : 1);
    const tint = rule.t === "flowers" ? FLOWER_C[Math.floor(h3 * FLOWER_C.length)] : { f: 0.9 + h2 * 0.2 };
    const small = SMALL.has(rule.t), bb = small ? (ch.sb || (ch.sb = new Buf(16384))) : b;
    emit(bb, tpl, wx - x0, y - 0.04, wz - y0, s, s * (0.9 + h1 * 0.25), h2 * Math.PI * 2, tint, rule.leafy ? 0.05 + h3 * 0.95 : 0, BIO3[bn]?.[2] || 1);
  }
}
// small plants (grass, flowers, ferns, reeds, drifts) go in their own mesh: no shadows, and hidden when far away
const SMALL = new Set(["grass", "tuft", "flowers", "fern", "reeds", "drift"]);
function finishFeatures(ch) {
  const sph = () => new THREE.Sphere(new THREE.Vector3(N / 2, ch.midY ?? 0, N / 2), N * 0.75 + 12);
  const g = ch.fb?.geometry(sph()); ch.fb = null;
  if (g) { const m = new THREE.Mesh(g, S.featMat); m.castShadow = S.quality === "high"; m.receiveShadow = true; m.name = "features"; ch.group.add(m); ch.feat = m; }
  const g2 = ch.sb?.geometry(sph()); ch.sb = null;
  if (g2) { const m = new THREE.Mesh(g2, S.featMat); m.receiveShadow = true; m.name = "small"; ch.group.add(m); ch.small = m; }
}
// near chunks show their small plants; far ones only trees and stones
function updateDetail() {
  const t = S.cam.target, far = S.quality === "low" ? 30 : 44;
  for (const ch of S.chunks.values()) if (ch.small) {
    const dx = Math.max(0, Math.abs(t.x - (ch.cx + 0.5) * N) - N / 2), dz = Math.max(0, Math.abs(t.z - (ch.cy + 0.5) * N) - N / 2);
    ch.small.visible = Math.hypot(dx, dz) < far;
  }
}

// ───────────────────────────────────────────────────────────── places (points of interest)
// Their walls and stones are features of the tiles; here: their names, a roof over cabins, and the small
// things a feature can't show (a beehive, a nest, a flag on a lookout hill).
const STONE = C("#958d82"), WOOD = C("#8a643f"), DWOOD = C("#5a4030");
function buildPois(ch, d) {
  const pois = d.c.pois || []; if (!pois.length) return;
  const b = new Buf(1024), x0 = ch.cx * N, y0 = ch.cy * N;
  ch.labels = [];
  for (const p of pois) {
    const px = p.x + 0.5 - x0, pz = p.y + 0.5 - y0, y = groundY(p.x + 0.5, p.y + 0.5);
    if (p.kind === "lookout") {
      put(b, box(), M(px, y + 1.1, pz, 0.06, 2.2, 0.06), DWOOD); put(b, box(), M(px + 0.32, y + 1.95, pz, 0.6, 0.38, 0.03), C("#d2463a"), { sway: 0.4 });
    }
    if (p.kind === "home" || p.kind === "cabin") S.roofWant.push(p);
    ch.labels.push({ name: p.name || p.kind, kind: p.kind, x: p.x + 0.5, z: p.y + 0.5, y: y + 3 });
  }
  const g = b.geometry(); if (!g) return;
  const m = new THREE.Mesh(g, S.propMat); m.castShadow = S.quality === "high"; m.receiveShadow = true; m.name = "pois";
  ch.group.add(m); ch.poi = m;
}

// ───────────────────────────────────────────────────────────── streaming: which chunks, nearest first
function updateChunks(fx, fz) {
  const C2 = window.Chunks; if (!C2 || !S.meta) return;
  const cx = Math.floor(fx / N), cy = Math.floor(fz / N), k = cx + "," + cy + ":" + S.chunks.size + ":" + S.cdat.size;
  if (k === S.focusKey) return;
  S.focusKey = k;
  const want = [];
  for (let dy = -RADIUS - 1; dy <= RADIUS + 1; dy++) for (let dx = -RADIUS - 1; dx <= RADIUS + 1; dx++) {
    const x = cx + dx, y = cy + dy, dd = Math.hypot((x + 0.5) * N - fx, (y + 0.5) * N - fz);
    want.push([x, y, dd, Math.max(Math.abs(dx), Math.abs(dy)) <= RADIUS]);
  }
  want.sort((a, b) => a[2] - b[2]);
  for (const [x, y, , mesh] of want) {
    if (!C2.peek(x, y)) { C2.get(x, y, mesh && Math.abs(x - cx) + Math.abs(y - cy) <= 1).catch(() => { S.focusKey = ""; }); continue; }
    if (!mesh) continue;
    const key = ckey(x, y);
    if (S.chunks.has(key)) continue;
    if (!neighbourhood(x, y)) continue;
    const ch = { cx: x, cy: y, key, group: new THREE.Group(), steps: null, done: false, dist: 0 };
    ch.group.position.set(x * N, 0, y * N); ch.group.visible = false;
    S.world.add(ch.group); S.chunks.set(key, ch);
    ch.steps = chunkJobs(ch);
    S.jobs.push(ch);
  }
  // nearest builds first
  S.jobs.sort((a, b) => Math.hypot(a.cx + 0.5 - fx / N, a.cy + 0.5 - fz / N) - Math.hypot(b.cx + 0.5 - fx / N, b.cy + 0.5 - fz / N));
  // let go of chunks well outside
  for (const [key, ch] of S.chunks) if (Math.abs(ch.cx - cx) > RADIUS + 1 || Math.abs(ch.cy - cy) > RADIUS + 1) disposeChunk(ch);
  for (const [key, d] of S.cdat) if (Math.abs(d.cx - cx) > RADIUS + 3 || Math.abs(d.cy - cy) > RADIUS + 3) S.cdat.delete(key);
  C2.trim([[cx, cy]], 12);
}
function disposeChunk(ch) {
  S.chunks.delete(ch.key);
  const i = S.jobs.indexOf(ch); if (i >= 0) S.jobs.splice(i, 1);
  ch.group.traverse((o) => { if (o.geometry) o.geometry.dispose(); });
  S.world.remove(ch.group);
}
// spend at most BUDGET_MS a frame building
function runJobs() {
  const t0 = performance.now();
  while (S.jobs.length && performance.now() - t0 < (S.budgetMs || BUDGET_MS)) runOne();
  if (S.loading) { const ready = [...S.chunks.values()].some((c) => c.done); S.loading.hidden = ready; }
  scheduleIdle();
}
function runOne() {
  {
    const ch = S.jobs[0];
    const step = ch.steps.shift();
    const s0 = performance.now();
    try { step && step(); } catch (e) { console.error("chunk build:", e); ch.steps.length = 0; }
    const js = performance.now() - s0; S.stats.jobMax = Math.max(S.stats.jobMax, js);
    if (step) { const k = step.label || "?", jb = S.stats.jobBy || (S.stats.jobBy = {}); (jb[k] || (jb[k] = [])).push(+js.toFixed(1)); if (jb[k].length > 400) jb[k].shift(); }
    if (!ch.steps.length) { S.jobs.shift(); ch.done = true; ch.group.visible = true; S.stats.built++; ch.born = U.time.value; }
  }
}
// keep building between frames when the browser is idle (each step stays short)
function scheduleIdle() {
  if (S.idleQ || !S.jobs.length || S.paused) return;
  const ric = window.requestIdleCallback || ((f) => setTimeout(() => f({ timeRemaining: () => 8, didTimeout: false }), 30));
  S.idleQ = ric((dl) => {
    S.idleQ = null;
    let n = 0;
    while (S.jobs.length && !S.paused && (dl.timeRemaining() > 6 || (dl.didTimeout && n === 0))) { runOne(); n++; }
    scheduleIdle();
  }, { timeout: 250 });
}
// rebuild everything (season change, quality change)
function rebuildAll() { for (const ch of [...S.chunks.values()]) disposeChunk(ch); S.focusKey = ""; }

// ───────────────────────────────────────────────────────────── roofs over cabins (fade away when someone is inside)
// A cabin is the walls, door and floor tiles connected to its place; its roof spans their outline.
function buildRoofs() {
  for (let i = S.roofWant.length - 1; i >= 0; i--) {
    const p = S.roofWant[i], key = p.kind + ":" + p.x + "," + p.y;
    if (S.roofs.has(key)) { S.roofWant.splice(i, 1); continue; }
    const seen = new Set(), q = [[p.x, p.y]], tiles = [];
    let ok = true;
    while (q.length && tiles.length < 400) {
      const [x, y] = q.pop(), k = x + "," + y; if (seen.has(k)) continue; seen.add(k);
      if (Math.abs(x - p.x) > 12 || Math.abs(y - p.y) > 12) continue;
      const r = tileRef(x, y); if (!r) { ok = false; break; }
      const fn = featAt(x, y); if (!/^(wall|floor|door)$/.test(fn)) continue;
      tiles.push([x, y, fn]);
      q.push([x + 1, y], [x - 1, y], [x, y + 1], [x, y - 1]);
    }
    if (!ok) continue;          // not all of it loaded yet
    S.roofWant.splice(i, 1);
    if (tiles.length < 4) continue;
    let x0 = 1e9, x1 = -1e9, y0 = 1e9, y1 = -1e9, base = -1e9;
    for (const [x, y] of tiles) { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); base = Math.max(base, bedAt(x, y)); }
    S.roofs.set(key, makeRoof(p, x0, y0, x1 + 1, y1 + 1, base, tiles));
  }
}
function makeRoof(p, x0, y0, x1, y1, base, tiles) {
  const g = new THREE.Group(), W = x1 - x0, D = y1 - y0, cx = (x0 + x1) / 2, cz = (y0 + y1) / 2, top = base + 1.9;
  const alongX = W >= D, span = alongX ? D : W, len = (alongX ? W : D) + 0.6, rise = Math.min(2.2, span * 0.38), half = span / 2 + 0.3;
  const slope = Math.atan2(rise, span / 2), rl = Math.hypot(rise, span / 2) + 0.4, b = new Buf(2048), home = p.kind === "home";
  const roofC = home ? C("#7b3f33") : C("#5d4f45"), stripC = home ? C("#62302a") : C("#4a3f37");
  for (const s of [-1, 1]) {
    const off = s * (span / 4 + 0.05), m = alongX ? M(cx, top + rise / 2, cz + off, len, 0.16, rl, 0, s * slope) : M(cx + off, top + rise / 2, cz, rl, 0.16, len, 0, 0, -s * slope);
    put(b, box(), m, roofC);
    for (let k = 1; k < 6; k++) {
      const o2 = s * (span / 4 + 0.05) * (0.2 + k * 0.32) / 1, yy = top + rise * (1 - (0.2 + k * 0.32) / 2) + 0.06;
      if (Math.abs(o2) > half) continue;
      put(b, box(), alongX ? M(cx, yy, cz + s * (half * (k / 6)), len, 0.05, 0.08, 0, s * slope) : M(cx + s * (half * (k / 6)), yy, cz, 0.08, 0.05, len, 0, 0, -s * slope), stripC);
    }
  }
  // gable ends
  const gable = new THREE.Shape([new THREE.Vector2(-half, 0), new THREE.Vector2(half, 0), new THREE.Vector2(0, rise)]);
  const gg = new THREE.ExtrudeGeometry(gable, { depth: 0.18, bevelEnabled: false }).toNonIndexed(); gg.computeVertexNormals();
  for (const s of [-1, 1]) {
    const m = alongX ? M(x0 + (s < 0 ? 0.02 : W - 0.2) + 0, top, cz, 1, 1, 1, Math.PI / 2) : M(cx, top, y0 + (s < 0 ? 0.02 : D - 0.2));
    if (alongX) m.multiply(new THREE.Matrix4().makeTranslation(0, 0, 0));
    put(b, gg, alongX ? M(s < 0 ? x0 : x1 - 0.18, top, cz, 1, 1, 1, Math.PI / 2).multiply(new THREE.Matrix4().makeTranslation(0, 0, 0)) : M(cx, top, s < 0 ? y0 : y1 - 0.18), home ? C("#8a5e3a") : C("#6b5a4a"));
  }
  if (home) {     // a stone chimney with smoke
    const chx = alongX ? x1 - 1.2 : cx + span / 4, chz = alongX ? cz - span / 4 : y0 + 1.2;
    put(b, box(), M(chx, top + rise * 0.6, chz, 0.6, rise * 1.2 + 1.2, 0.6), C("#8f877b"));
    S.chimney = new THREE.Vector3(chx, top + rise * 1.25 + 0.65, chz);
  }
  const mat = lambert({ vertexColors: true, transparent: true }, { snow: 1, key: "roof" });
  const mesh = new THREE.Mesh(b.geometry(), mat); mesh.castShadow = true; mesh.receiveShadow = true; g.add(mesh);
  // windows that glow at night: on the long walls, where a wall tile is
  if (!S.glassMat) { S.glassMat = new THREE.MeshLambertMaterial({ color: 0x324055, emissive: 0xffb45a, emissiveIntensity: 0, side: THREE.DoubleSide }); S.glassMats = [S.glassMat]; S.bLit = [true]; S.bGlow = [0]; }
  if (home) for (const [x, y, fn] of tiles) {
    if (fn !== "wall" || (x + y) % 3) continue;
    const ns = y === y0 || y === y1 - 1, ew = x === x0 || x === x1 - 1; if (ns === ew) continue;
    const wm = new THREE.Mesh(new THREE.PlaneGeometry(0.6, 0.5), S.glassMat);
    wm.position.set(x + 0.5 + (ew ? (x === x0 ? -0.52 : 0.52) : 0), bedAt(x, y) + 1.05, y + 0.5 + (ns ? (y === y0 ? -0.52 : 0.52) : 0)); wm.rotation.y = ew ? Math.PI / 2 : 0; g.add(wm);
  }
  S.scene.add(g);
  return { p, g, mat, mesh, box: [x0, y0, x1, y1], fade: 1, cx, cz, base };
}
function updateRoofs(dt) {
  if (S.roofWant.length && (S.roofT = (S.roofT || 0) - dt) < 0) { S.roofT = 0.5; buildRoofs(); }
  for (const [key, r] of S.roofs) {
    const [x0, y0, x1, y1] = r.box, inside = (x, z) => x > x0 && x < x1 && z > y0 && z < y1;
    if (Math.abs(r.cx - S.cam.target.x) > (RADIUS + 2) * N || Math.abs(r.cz - S.cam.target.z) > (RADIUS + 2) * N) { S.scene.remove(r.g); r.mesh.geometry.dispose(); S.roofs.delete(key); continue; }
    const zen = S.synth.group.visible && inside(S.synth.x, S.synth.z), you = S.mode === "visit" && S.local.init && inside(S.local.x, S.local.z);
    const close = S.cam.dist < 8 && inside(S.cam.target.x, S.cam.target.z);
    r.fade = lerp(r.fade, zen || you || close ? 0 : 1, damp(4, dt));
    r.mat.opacity = r.fade; r.mesh.visible = r.fade > 0.03; r.mat.depthWrite = r.fade > 0.95; r.mesh.castShadow = r.fade > 0.5;
  }
}
function insideAnyRoof(x, z) { for (const r of S.roofs.values()) { const [x0, y0, x1, y1] = r.box; if (x > x0 && x < x1 && z > y0 && z < y1) return r; } return null; }

// ───────────────────────────────────────────────────────────── things (entities): furniture in 3D, the rest as emoji
const FURN = {};
function furnGeo(kind) {
  if (FURN[kind] !== undefined) return FURN[kind];
  const b = new Buf(1024), w = C("#9a6e45"), dk = C("#5e412b");
  switch (kind) {
    case "bed": put(b, box(), M(0, 0.18, 0, 0.9, 0.28, 1.7), dk); put(b, box(), M(0, 0.37, 0.05, 0.84, 0.12, 1.55), C("#f3efe6"));
      put(b, box(), M(0, 0.42, 0.25, 0.86, 0.06, 1.1), C("#5f7fc9")); put(b, box(), M(0, 0.45, -0.6, 0.6, 0.12, 0.3), C("#ffffff")); put(b, box(), M(0, 0.45, -0.85, 0.9, 0.7, 0.08), dk); break;
    case "fireplace": put(b, box(), M(0, 0.55, 0, 1.2, 1.1, 0.6), C("#8d857a")); put(b, box(), M(0, 0.35, 0.21, 0.66, 0.55, 0.22), C("#241c18"));
      put(b, box(), M(0, 1.15, 0.05, 1.35, 0.12, 0.75), C("#6f675d")); put(b, box(), M(0, 1.9, -0.08, 0.6, 1.4, 0.45), C("#8d857a"));
      put(b, cyl(6, 1, false), M(-0.1, 0.15, 0.2, 0.12, 0.45, 0.12, 0, 0, Math.PI / 2), C("#6b4a30")); break;
    case "table": case "desk": put(b, box(), M(0, 0.7, 0, kind === "desk" ? 1.0 : 1.3, 0.07, 0.8), w);
      for (const [a, c] of [[-0.55, -0.32], [0.55, -0.32], [-0.55, 0.32], [0.55, 0.32]]) put(b, box(), M(a * (kind === "desk" ? 0.75 : 1), 0.34, c, 0.07, 0.68, 0.07), dk); break;
    case "bookshelf": put(b, box(), M(0, 0.9, 0, 1.0, 1.8, 0.36), dk);
      for (let s = 0; s < 4; s++) for (let k = 0; k < 7; k++) put(b, box(), M(-0.4 + k * 0.13, 0.2 + s * 0.43 + 0.13, 0.04, 0.1, 0.26 + hash2(k, s) * 0.08, 0.26), C(["#a33d2a", "#2f5d8a", "#d6a033", "#3f7a4a", "#6b3f7a", "#c9b8a0", "#8a2f45"][(k + s * 3) % 7])); break;
    case "easel": put(b, box(), M(-0.3, 0.8, 0.1, 0.05, 1.7, 0.05, 0, 0, 0.17), w); put(b, box(), M(0.3, 0.8, 0.1, 0.05, 1.7, 0.05, 0, 0, -0.17), w);
      put(b, box(), M(0, 0.75, -0.25, 0.05, 1.55, 0.05, 0, -0.32), w); put(b, box(), M(0, 0.62, 0.14, 0.75, 0.05, 0.08), dk); break;
    case "piano": put(b, box(), M(0, 0.62, 0, 1.45, 1.24, 0.55), C("#2a2522")); put(b, box(), M(0, 0.74, 0.36, 1.35, 0.06, 0.22), C("#f2efe6"));
      for (let k = 0; k < 9; k++) put(b, box(), M(-0.6 + k * 0.15, 0.785, 0.32, 0.05, 0.03, 0.12), C("#1a1715")); put(b, box(), M(0, 0.3, 0.3, 1.3, 0.6, 0.05), C("#2f2a26")); break;
    case "chest": put(b, box(), M(0, 0.25, 0, 0.8, 0.5, 0.5), C("#8a5a34")); put(b, box(), M(0, 0.53, 0, 0.84, 0.08, 0.54), C("#6b4428"));
      put(b, box(), M(0, 0.42, 0.26, 0.1, 0.14, 0.03), C("#d8b04a")); break;
    case "wood": case "woodpile": for (let k = 0; k < 5; k++) put(b, cyl(6, 1, false), M(-0.25 + (k % 3) * 0.25, 0.1 + Math.floor(k / 3) * 0.2, -0.3, 0.2, 0.7, 0.2, 0, Math.PI / 2), C(k % 2 ? "#8a643f" : "#7a5634")); break;
    case "lantern": put(b, box(), M(0, 0.15, 0, 0.18, 0.3, 0.18), C("#3a3430")); put(b, box(), M(0, 0.15, 0, 0.14, 0.22, 0.14), C("#ffd27a")); break;
    case "beehive": put(b, box(), M(0, 0.4, 0, 0.12, 0.8, 0.12), dk); put(b, box(), M(0, 0.82, 0, 0.7, 0.06, 0.7), w);
      for (let k = 0; k < 3; k++) put(b, ico(1), M(0, 0.98 + k * 0.2, 0, 0.62 - k * 0.15, 0.3, 0.62 - k * 0.15), C(k % 2 ? "#d8a93a" : "#e6bb4c"));
      put(b, box(), M(0, 0.96, 0.27, 0.14, 0.08, 0.04), C("#2a1d10")); break;
    case "nest": put(b, flatGeo("torus", () => new THREE.TorusGeometry(0.3, 0.12, 5, 10).rotateX(Math.PI / 2)), M(0, 0.1, 0), C("#8a6a3e"));
      for (let k = 0; k < 3; k++) put(b, ico(1), M((k - 1) * 0.12, 0.12, (k % 2) * 0.08, 0.13, 0.17, 0.13), C("#e8ecf0")); break;
    case "campfire": for (let k = 0; k < 8; k++) { const a = k / 8 * Math.PI * 2; put(b, dode(), M(Math.cos(a) * 0.38, 0.06, Math.sin(a) * 0.38, 0.2, 0.14, 0.18, k), C("#8a857e")); }
      for (let k = 0; k < 3; k++) put(b, cyl(6, 1, false), M(0, 0.08, 0, 0.12, 0.6, 0.12, k * 1.05, Math.PI / 2 - 0.25), C("#6b4a30")); break;
    case "rain barrel": put(b, cyl(10, 0.9, false), M(0, 0, 0, 0.6, 0.85, 0.6), C("#7a5634")); put(b, cyl(10, 1, false), M(0, 0.25, 0, 0.62, 0.06, 0.62), C("#3a3632")); put(b, cyl(10, 1, false), M(0, 0.62, 0, 0.6, 0.06, 0.6), C("#3a3632")); break;
    default: FURN[kind] = null; return null;
  }
  FURN[kind] = b.geometry(); return FURN[kind];
}
function makeEasel(e) {
  const g = new THREE.Group(), base = new THREE.Mesh(furnGeo("easel"), S.plainMat); base.castShadow = true; g.add(base);
  const cv = document.createElement("canvas"); cv.width = 256; cv.height = 192;
  const cx = cv.getContext("2d"); cx.fillStyle = "#f4eedf"; cx.fillRect(0, 0, 256, 192);
  const tex = new THREE.CanvasTexture(cv); tex.colorSpace = THREE.SRGBColorSpace;
  const pm = new THREE.Mesh(new THREE.PlaneGeometry(0.8, 0.6), new THREE.MeshLambertMaterial({ map: tex }));
  pm.position.set(0, 1.0, 0.16); pm.rotation.x = -0.17; g.add(pm);
  g.userData = { canvas: cv, tex, drawn: 0 };
  return g;
}
function entY(e) {
  const fn = featAt(e.x, e.y), base = bedAt(e.x, e.y);
  return fn === "floor" || fn === "door" ? base + 0.12 : standY(e.x + 0.5, e.y + 0.5);
}
// furniture stands with its back to the nearest wall
function furnFacing(e) {
  for (const [dx, dy, a] of [[0, -1, 0], [0, 1, Math.PI], [-1, 0, Math.PI / 2], [1, 0, -Math.PI / 2]]) if (WALLISH.has(featAt(e.x + dx, e.y + dy))) return a;
  return 0;
}
const LIGHTS = new Set(["fireplace", "lantern", "torch", "candle", "campfire", "fire"]);   // lit when e.lit
function syncEnts() {
  if (S.entSig === S.entsVersion + ":" + S.cdat.size) return;
  S.entSig = S.entsVersion + ":" + S.cdat.size;
  for (const [id, o] of S.entObjs) if (!S.ents.has(id)) { S.scene.remove(o); S.entObjs.delete(id); }
  for (const e of S.ents.values()) {
    let o = S.entObjs.get(e.id);
    if (!o) {
      if (e.kind === "easel") o = makeEasel(e);
      else { const g = furnGeo(e.kind); if (!g) continue; o = new THREE.Mesh(g, S.plainMat); o.castShadow = true; o.receiveShadow = true; }
      o.userData.ent = e.id; S.entObjs.set(e.id, o); S.scene.add(o);
    }
    const y = entY(e);
    o.position.set(e.x + 0.5, y, e.y + 0.5);
    o.rotation.y = e.facing != null ? angleOf(e.facing) : furnFacing(e);
  }
}

// ───────────────────────────────────────────────────────────── animals: small low-poly creatures
const ANIMAL = {
  deer: { body: [0.34, 0.3, 0.68], y: 0.62, col: "#a8744a", head: [0.15, 0.17, 0.26], hy: 0.98, hz: 0.36, leg: 0.55, lw: 0.06, legc: "#7a4e30", extra: "antlers", tail: "#f3eadc" },
  rabbit: { body: [0.2, 0.18, 0.26], y: 0.15, col: "#bba78c", head: [0.12, 0.12, 0.13], hy: 0.26, hz: 0.13, leg: 0.0, extra: "ears", tail: "#ffffff", hop: true },
  fox: { body: [0.17, 0.17, 0.42], y: 0.3, col: "#d0662b", head: [0.12, 0.12, 0.18], hy: 0.4, hz: 0.27, leg: 0.27, lw: 0.04, legc: "#3a2a22", extra: "foxtail" },
  bear: { body: [0.55, 0.52, 0.95], y: 0.78, col: "#5a3e2b", head: [0.3, 0.28, 0.32], hy: 1.0, hz: 0.55, leg: 0.55, lw: 0.14, legc: "#4a3222", extra: "bearears" },
  frog: { body: [0.12, 0.08, 0.13], y: 0.06, col: "#5f9c3a", head: [0.1, 0.06, 0.08], hy: 0.09, hz: 0.07, leg: 0, extra: "frogeyes", hop: true },
  owl: { body: [0.2, 0.28, 0.18], y: 0.18, col: "#8a7356", head: [0.2, 0.18, 0.17], hy: 0.4, hz: 0.0, leg: 0, extra: "owl", perch: 2.1 },
  bird: { body: [0.1, 0.09, 0.17], y: 0.08, col: "#5f78b8", head: [0.08, 0.08, 0.08], hy: 0.15, hz: 0.08, leg: 0, extra: "bird", fly: true },
  fish: { body: [0.06, 0.1, 0.28], y: 0, col: "#e0a060", head: [0.05, 0.08, 0.06], hy: 0, hz: 0.14, leg: 0, extra: "fin", swim: true },
  lizard: { body: [0.1, 0.06, 0.26], y: 0.06, col: "#8a8a4a", head: [0.07, 0.05, 0.1], hy: 0.07, hz: 0.17, leg: 0.06, lw: 0.03, legc: "#6a6a3a" },
  goat: { body: [0.3, 0.3, 0.55], y: 0.55, col: "#e6e0d4", head: [0.13, 0.15, 0.22], hy: 0.85, hz: 0.32, leg: 0.48, lw: 0.06, legc: "#8a8478", extra: "horns" },
  bee: { glow: "#ffd34a" }, bees: { glow: "#ffd34a" }, fireflies: { glow: "#fff08a" }, firefly: { glow: "#fff08a" },
};
const AGEO = {};
function animalGeo(kind) {
  if (AGEO[kind]) return AGEO[kind];
  const a = ANIMAL[kind] || ANIMAL.deer, b = new Buf(1024), c = C(a.col), dark = shade(c, 0.7), light = c.clone().lerp(C("#fff4e6"), 0.45);
  put(b, ico(1), M(0, a.y, 0, ...a.body), c);
  put(b, ico(1), M(0, a.y - a.body[1] * 0.18, 0.02, a.body[0] * 0.8, a.body[1] * 0.7, a.body[2] * 0.8), light);
  put(b, ico(1), M(0, a.hy, a.hz, ...a.head), c);
  const hx = a.head[0], hy = a.hy, hz = a.hz;
  switch (a.extra) {
    case "antlers": for (const s of [-1, 1]) { put(b, cyl(4, 0.6), M(s * 0.05, hy + 0.06, hz - 0.03, 0.03, 0.26, 0.03, 0, -0.2, s * 0.4), C("#e2d4b4")); put(b, cyl(4, 0.6), M(s * 0.12, hy + 0.2, hz - 0.06, 0.025, 0.14, 0.025, 0, 0.4, s * 0.9), C("#e2d4b4")); }
      put(b, ico(0), M(0, a.y + 0.08, -a.body[2] / 2, 0.08), C(a.tail)); put(b, box(), M(0, hy - 0.02, hz + 0.14, 0.06, 0.06, 0.06), C("#2a1d14")); break;
    case "ears": for (const s of [-1, 1]) put(b, ico(0), M(s * 0.035, hy + 0.12, hz - 0.02, 0.045, 0.2, 0.03, 0, -0.2, s * 0.15), c);
      put(b, ico(0), M(0, a.y + 0.03, -a.body[2] / 2, 0.08), C(a.tail)); break;
    case "foxtail": for (const s of [-1, 1]) put(b, cone(4), M(s * 0.045, hy + 0.04, hz - 0.03, 0.06, 0.1, 0.04), c);
      put(b, cone(5), M(0, a.y + 0.02, -a.body[2] / 2 - 0.05, 0.12, 0.34, 0.12, 0, -2.1), c); put(b, ico(0), M(0, a.y - 0.13, -a.body[2] / 2 - 0.3, 0.08), C("#ffffff"));
      put(b, cone(5), M(0, hy - 0.02, hz + 0.06, 0.07, 0.13, 0.07, 0, Math.PI / 2), c); break;
    case "bearears": for (const s of [-1, 1]) put(b, ico(0), M(s * 0.12, hy + 0.13, hz - 0.04, 0.08), dark); put(b, ico(0), M(0, hy - 0.04, hz + 0.16, 0.12, 0.1, 0.1), C("#8a6a4a")); break;
    case "horns": for (const s of [-1, 1]) put(b, cone(4), M(s * 0.05, hy + 0.1, hz - 0.06, 0.04, 0.2, 0.04, 0, -0.5, s * 0.25), C("#9a8a6a")); break;
    case "frogeyes": for (const s of [-1, 1]) put(b, ico(0), M(s * 0.04, hy + 0.04, hz, 0.045), C("#e8f0a0")); break;
    case "owl": put(b, ico(1), M(0, hy, 0.06, 0.15, 0.13, 0.06), C("#d8c3a0")); for (const s of [-1, 1]) { put(b, ico(0), M(s * 0.045, hy + 0.01, 0.1, 0.05), C("#ffd23a")); put(b, cone(4), M(s * 0.07, hy + 0.08, 0, 0.04, 0.09, 0.04), dark); }
      put(b, cone(4), M(0, hy - 0.03, 0.11, 0.025, 0.05, 0.025, 0, Math.PI / 2), C("#d9a33a")); break;
    case "bird": put(b, ico(0), M(0, a.y - 0.01, 0.04, 0.08, 0.06, 0.1), C("#e8823a")); put(b, cone(4), M(0, hy, hz + 0.05, 0.03, 0.06, 0.03, 0, Math.PI / 2), C("#e0b040"));
      put(b, box(), M(0, a.y + 0.01, -0.13, 0.08, 0.015, 0.1), dark); break;
    case "fin": put(b, cone(4), M(0, 0, -0.15, 0.02, 0.14, 0.12, 0, -Math.PI / 2), shade(c, 0.85)); put(b, ico(0), M(0, 0.04, 0.02, 0.01, 0.08, 0.08), dark); break;
  }
  return (AGEO[kind] = b.geometry());
}
const LEG = () => flatGeo("leg", () => new THREE.BoxGeometry(1, 1, 1).translate(0, -0.5, 0));
const WING = () => flatGeo("wing", () => new THREE.BoxGeometry(1, 0.1, 1).translate(0.5, 0, 0));
function makeAnimal(a) {
  const spec = ANIMAL[a.kind] || ANIMAL.deer, g = new THREE.Group(), o = { kind: a.kind, group: g, legs: [], wings: [], x: 0, z: 0, y: 0, heading: 0, init: false, ph: hash2(a.id | 0, 3) * 10, alt: 0 };
  if (spec.glow) { o.glow = C(spec.glow); return o; }
  const body = new THREE.Mesh(animalGeo(a.kind), S.plainMat); body.castShadow = true; g.add(body); o.body = body;
  if (spec.leg) {
    const lm = new THREE.MeshLambertMaterial({ color: spec.legc });
    for (const [sx, sz] of [[-1, 1], [1, 1], [-1, -1], [1, -1]]) {
      const l = new THREE.Mesh(LEG(), lm); l.scale.set(spec.lw, spec.leg, spec.lw);
      l.position.set(sx * spec.body[0] * 0.3, spec.y - spec.body[1] * 0.15, sz * spec.body[2] * 0.3); l.castShadow = true; g.add(l); o.legs.push(l);
    }
  }
  if (spec.fly || a.kind === "owl") {
    const wm = new THREE.MeshLambertMaterial({ color: shade(C(spec.col), 0.8) });
    for (const s of [-1, 1]) { const w = new THREE.Mesh(WING(), wm); w.scale.set(spec.body[0] * (a.kind === "owl" ? 2.2 : 2.6), 1, spec.body[2] * 0.7); w.position.set(s * spec.body[0] * 0.3, spec.y + 0.02, 0); w.rotation.y = s < 0 ? Math.PI : 0; g.add(w); o.wings.push(w); }
  }
  S.scene.add(g);
  return o;
}
function syncAnimals(list) {
  const seen = new Set();
  for (const a of list || []) {
    seen.add(a.id);
    let o = S.animals.get(a.id);
    if (!o) { o = makeAnimal(a); S.animals.set(a.id, o); }
    o.data = a;
  }
  for (const [id, o] of S.animals) if (!seen.has(id)) { if (o.group.parent) S.scene.remove(o.group); S.animals.delete(id); }
}
function updateAnimals(dt, t) {
  const night = S.env.night;
  for (const [, o] of S.animals) {
    const a = o.data, spec = ANIMAL[a.kind] || ANIMAL.deer;
    const tx = (a.fx ?? a.x) + 0.5, tz = (a.fy ?? a.y) + 0.5;
    const sp = moveToward(o, tx, tz, dt, spec.fly ? 3 : 2.2);
    const moving = sp > 0.15;
    o.walk = (o.walk || 0) + dt * (moving ? 9 : 0);
    if (spec.glow) {      // bees and fireflies: little lights that wander
      const k = /^bees?$/.test(a.kind) ? 1.2 : 0.6;
      o.gx = o.x + Math.sin(t * 2.3 * k + o.ph) * 0.5; o.gz = o.z + Math.cos(t * 1.9 * k + o.ph * 1.3) * 0.5;
      o.gy = standY(o.x, o.z) + (/^bees?$/.test(a.kind) ? 0.9 : 0.8) + Math.sin(t * 3.1 * k + o.ph) * 0.25;
      continue;
    }
    const ground = standY(o.x, o.z), water = waterAt(Math.floor(o.x), Math.floor(o.z));
    let y = ground;
    if (spec.swim) y = (water > -1e8 ? water : ground) - 0.12 + Math.sin(t * 2 + o.ph) * 0.02;
    if (spec.fly) { o.alt = lerp(o.alt, moving ? 2.4 : 0, damp(2, dt)); y = ground + o.alt; }
    if (spec.perch) { o.alt = lerp(o.alt, moving ? 3 : spec.perch, damp(2, dt)); y = ground + o.alt; }
    if (spec.hop && moving) y += Math.abs(Math.sin(o.walk * 0.9)) * (a.kind === "frog" ? 0.18 : 0.12);
    o.y = lerp(o.y || y, y, damp(10, dt));
    const target = moving ? Math.atan2(o.dirX || 0, o.dirZ || 1) : angleOf(a.facing ?? 2);
    o.heading = turnTo(o.heading, target, damp(6, dt));
    o.group.position.set(o.x, o.y, o.z); o.group.rotation.y = o.heading;
    const asleep = a.state === "sleeping";
    o.body.rotation.x = spec.swim ? 0 : moving ? Math.sin(o.walk * 2) * 0.03 : asleep ? 0.05 : 0;
    o.legs.forEach((l, i) => { l.rotation.x = moving ? Math.sin(o.walk + (i === 0 || i === 3 ? 0 : Math.PI)) * 0.55 : 0; });
    const flap = o.alt > 0.3 ? Math.sin(t * (a.kind === "owl" ? 9 : 22) + o.ph) * 0.9 : 0.15;
    o.wings.forEach((w, i) => { w.rotation.z = (i ? -1 : 1) * flap; w.visible = spec.fly || o.alt > 0.3; });
    if (spec.swim) o.body.rotation.y = Math.sin(t * 6 + o.ph) * 0.2;
    o.group.visible = night < 0.75 || !/deer|rabbit|fox|bird/.test(a.kind) || true;
  }
}

// ───────────────────────────────────────────────────────────── Zen, the Sprite and you
function makeOrb(inner, glow, eye, r) {
  const g = new THREE.Group();
  const core = new THREE.Mesh(new THREE.SphereGeometry(r, 28, 18), new THREE.MeshStandardMaterial({ color: inner, emissive: glow, emissiveIntensity: 0.5, roughness: 0.35 }));
  core.castShadow = true;
  const face = new THREE.Group(), eyeMat = new THREE.MeshBasicMaterial({ color: eye }), eyeGeo = new THREE.SphereGeometry(r * 0.18, 10, 8);
  const eyes = [-1, 1].map((s) => { const e = new THREE.Mesh(eyeGeo, eyeMat); e.position.set(s * r * 0.38, r * 0.15, r * 0.87); e.scale.set(1, 1.55, 0.6); face.add(e); return e; });
  g.add(core, face);
  return { group: g, core, face, eyes, x: 0, z: 0, y: 0, heading: 0, init: false, blinkT: 2, blink: 0 };
}
function makeSprite() {
  const g = new THREE.Group();
  const core = new THREE.Mesh(new THREE.SphereGeometry(0.075, 16, 12), new THREE.MeshBasicMaterial({ color: 0xfff6dc }));
  const halo = new THREE.Mesh(new THREE.SphereGeometry(0.13, 20, 14), new THREE.ShaderMaterial({ vertexShader: RIM_VERT, fragmentShader: RIM_FRAG,
    uniforms: { uColor: { value: C("#ffd98a") }, uPower: { value: 1.6 } }, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false }));
  const ring = new THREE.Mesh(new THREE.TorusGeometry(0.2, 0.006, 6, 40), new THREE.MeshBasicMaterial({ color: 0xffe7a8, transparent: true, opacity: 0.0, blending: THREE.AdditiveBlending, depthWrite: false }));
  ring.rotation.x = Math.PI / 2;
  g.add(core, halo, ring);
  S.scene.add(g);
  S.sprite = { group: g, core, halo, ring, x: 0, z: 0, y: 0, init: false, glow: 0.6, trail: [], trailT: 0 };
}
// the facing marker: a soft chevron on the ground in front of Zen
function makeFacing() {
  const sh = new THREE.Shape([new THREE.Vector2(-0.13, 0), new THREE.Vector2(0, 0.16), new THREE.Vector2(0.13, 0), new THREE.Vector2(0, 0.06)]);
  const m = new THREE.Mesh(new THREE.ShapeGeometry(sh).rotateX(-Math.PI / 2), new THREE.MeshBasicMaterial({ color: 0xbfd0ff, transparent: true, opacity: 0.6, depthWrite: false }));
  m.renderOrder = 3; S.scene.add(m); return m;
}
// ───────────────────────────────────────────────────────────── glyph atlas
const ATLAS = 2048, CELL = 128, PER_ROW = ATLAS / CELL;
function makeAtlas() {
  const c = document.createElement("canvas"); c.width = c.height = ATLAS;
  S.atlas = { canvas: c, ctx: c.getContext("2d", { willReadFrequently: true }), cells: new Map(), next: 0 };
  S.atlasTex = new THREE.CanvasTexture(c); S.atlasTex.colorSpace = THREE.SRGBColorSpace; S.atlasTex.anisotropy = 4;
  S.atlasTex.minFilter = THREE.LinearMipmapLinearFilter;
}
function glyphCell(key, glyph, color, letter) {
  const A = S.atlas; let cell = A.cells.get(key); if (cell) return cell;
  const max = PER_ROW * PER_ROW, idx = A.next < max ? A.next++ : max - 1, cx = (idx % PER_ROW) * CELL, cy = Math.floor(idx / PER_ROW) * CELL, g = A.ctx;
  g.clearRect(cx, cy, 128, 128);
  g.save(); g.beginPath(); g.rect(cx, cy, 128, 128); g.clip();
  g.font = `96px ${EMOJI_FONT}`; g.textAlign = "center"; g.textBaseline = "middle"; g.fillStyle = "#fff";
  if (glyph) g.fillText(glyph, cx + 64, cy + 70);
  let bb = alphaBox(g, cx, cy);
  if (!bb) { // no emoji font: draw a badge
    g.fillStyle = color || "#9aa"; g.beginPath(); g.arc(cx + 64, cy + 64, 46, 0, 7); g.fill();
    g.lineWidth = 6; g.strokeStyle = "rgba(255,255,255,.85)"; g.stroke();
    g.fillStyle = "#fff"; g.font = "bold 56px system-ui,sans-serif"; g.fillText(((letter || key)[0] || "?").toUpperCase(), cx + 64, cy + 68);
    bb = alphaBox(g, cx, cy) || { x: cx, y: cy, w: 128, h: 128 };
  }
  g.restore();
  const p = 2; const x = Math.max(cx, bb.x - p), y = Math.max(cy, bb.y - p);
  const w = Math.min(cx + 128, bb.x + bb.w + p) - x, h = Math.min(cy + 128, bb.y + bb.h + p) - y;
  cell = { u: x / ATLAS, v: 1 - (y + h) / ATLAS, us: w / ATLAS, vs: h / ATLAS, aspect: w / h };
  A.cells.set(key, cell); S.atlasTex.needsUpdate = true;
  return cell;
}
function alphaBox(g, cx, cy) {
  const d = g.getImageData(cx, cy, 128, 128).data; let x0 = 128, y0 = 128, x1 = -1, y1 = -1;
  for (let y = 0; y < 128; y++) for (let x = 0; x < 128; x++) if (d[(y * 128 + x) * 4 + 3] > 40) {
    if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y;
  }
  return x1 < 0 ? null : { x: cx + x0, y: cy + y0, w: x1 - x0 + 1, h: y1 - y0 + 1 };
}
// ───────────────────────────────────────────────────────────── weather, clouds
function makeWeather() {
  const mk = (n, perVert) => {
    const seed = new Float32Array(n * perVert * 4), pos = new Float32Array(n * perVert * 3), r = rng(n);
    for (let i = 0; i < n; i++) { const s = [r(), r(), r(), r()]; for (let j = 0; j < perVert; j++) { seed.set(s, (i * perVert + j) * 4); pos[(i * perVert + j) * 3 + 1] = j; } }
    const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.BufferAttribute(pos, 3)); g.setAttribute("aSeed", new THREE.BufferAttribute(seed, 4));
    return g;
  };
  const center = { value: new THREE.Vector3() }; S.weatherCenter = center;
  S.rainMat = new THREE.ShaderMaterial({ vertexShader: RAIN_VERT, fragmentShader: RAIN_FRAG, transparent: true, depthWrite: false,
    uniforms: { uTime: U.time, uCenter: center, uColor: { value: C("#c9d6e6") }, uAlpha: { value: 0 }, uHeavy: { value: 0 } } });
  S.snowMat = new THREE.ShaderMaterial({ vertexShader: SNOW_VERT, fragmentShader: SNOW_FRAG, transparent: true, depthWrite: false,
    uniforms: { uTime: U.time, uCenter: center, uPR: { value: 1 }, uColor: { value: C("#ffffff") }, uAlpha: { value: 0 } } });
  S.rain = new THREE.LineSegments(mk(5000, 2), S.rainMat); S.rain.frustumCulled = false;
  S.snowP = new THREE.Points(mk(2400, 1), S.snowMat); S.snowP.frustumCulled = false;
  S.scene.add(S.rain, S.snowP);
  setRainDensity();
  if (S.quality === "low") S.snowP.geometry.setDrawRange(0, 900);
  // embers for lit fires
  const ne = 8 * 22, seed = new Float32Array(ne * 4), r = rng(5);
  for (let i = 0; i < ne; i++) seed.set([r(), r(), r(), Math.floor(i / 22)], i * 4);
  const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(ne * 3), 3)); g.setAttribute("aSeed", new THREE.BufferAttribute(seed, 4));
  S.fireU = Array.from({ length: 8 }, () => new THREE.Vector4(0, -100, 0, 0));
  S.emberMat = new THREE.ShaderMaterial({ vertexShader: EMBER_VERT, fragmentShader: EMBER_FRAG, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    uniforms: { uTime: U.time, uPR: { value: 1 }, uFire: { value: S.fireU } } });
  S.embers = new THREE.Points(g, S.emberMat); S.embers.frustumCulled = false; S.scene.add(S.embers);
  // smoke + steam puffs
  const NP = 16, PER = 22, ps = new Float32Array(NP * PER * 4), r2 = rng(17);
  for (let i = 0; i < NP * PER; i++) ps.set([r2(), r2(), r2(), Math.floor(i / PER)], i * 4);
  const pg = new THREE.BufferGeometry(); pg.setAttribute("position", new THREE.BufferAttribute(new Float32Array(NP * PER * 3), 3)); pg.setAttribute("aSeed", new THREE.BufferAttribute(ps, 4));
  S.puffSrc = Array.from({ length: NP }, () => new THREE.Vector4(0, -100, 0, 0)); S.puffPar = Array.from({ length: NP }, () => new THREE.Vector4(1, 0.5, 0.9, 0.3));
  S.puffMat = new THREE.ShaderMaterial({ vertexShader: PUFF_VERT, fragmentShader: PUFF_FRAG, transparent: true, depthWrite: false,
    uniforms: { uTime: U.time, uPR: { value: 1 }, uWind: U.wind, uLight: U.light, uSrc: { value: S.puffSrc }, uPar: { value: S.puffPar } } });
  S.puffs = new THREE.Points(pg, S.puffMat); S.puffs.frustumCulled = false; S.puffs.renderOrder = 4; S.scene.add(S.puffs);
  // rainbow: a half annulus with uv.x along the arc and uv.y across the band
  const bp = [], bu = [], idx = [], N = 64;
  for (let i = 0; i <= N; i++) { const a = Math.PI * (i / N); for (const [rr, v] of [[0.92, 0], [1, 1]]) { bp.push(Math.cos(a) * rr, Math.sin(a) * rr, 0); bu.push(i / N, v); } }
  for (let i = 0; i < N; i++) { const a = i * 2; idx.push(a, a + 1, a + 2, a + 1, a + 3, a + 2); }
  const bg = new THREE.BufferGeometry(); bg.setAttribute("position", new THREE.Float32BufferAttribute(bp, 3)); bg.setAttribute("uv", new THREE.Float32BufferAttribute(bu, 2)); bg.setIndex(idx);
  S.bowMat = new THREE.ShaderMaterial({ vertexShader: BOW_VERT, fragmentShader: BOW_FRAG, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    side: THREE.DoubleSide, fog: false, uniforms: { uAlpha: { value: 0 } } });
  S.bow = new THREE.Mesh(bg, S.bowMat); S.bow.frustumCulled = false; S.bow.renderOrder = -900; S.bow.visible = false; S.scene.add(S.bow);
}
function setRainDensity() {
  const n = S.quality === "high" ? (S.live.weather === "storm" ? 5000 : 3000) : (S.live.weather === "storm" ? 3200 : 2400);
  S.rain.geometry.setDrawRange(0, n * 2);
}
function makeClouds() {
  const r = rng(99), puffs = [];
  S.cloudClusters = [];
  for (let c = 0; c < 18; c++) {
    const cl = { x: r() * 220 - 50, z: r() * 170 - 40, y: 30 + r() * 9, sp: 0.6 + r() * 0.6, puffs: [] };
    const n = 4 + Math.floor(r() * 4);
    for (let i = 0; i < n; i++) cl.puffs.push({ ox: (i - n / 2) * 1.6 + r() * 0.8, oy: r() * 1.2 - (Math.abs(i - n / 2) * 0.25), oz: (r() - 0.5) * 2.4, s: 1.6 + r() * 1.4 - Math.abs(i - n / 2) * 0.2, ry: r() * 6 });
    S.cloudClusters.push(cl); puffs.push(...cl.puffs);
  }
  S.cloudMat = new THREE.MeshLambertMaterial({ color: 0xffffff, emissive: 0xffffff, emissiveIntensity: 0.35, flatShading: true, transparent: true, opacity: 0.95 });
  S.clouds = new THREE.InstancedMesh(new THREE.IcosahedronGeometry(1, 1), S.cloudMat, puffs.length);
  S.clouds.frustumCulled = false; S.clouds.castShadow = true; S.scene.add(S.clouds);
}

function makeSynth() {
  const g = new THREE.Group();
  const core = new THREE.Mesh(new THREE.SphereGeometry(0.23, 32, 20),
    new THREE.MeshStandardMaterial({ color: 0xa9bcff, emissive: 0x4f6cf0, emissiveIntensity: 0.8, roughness: 0.3, metalness: 0.0 }));
  core.castShadow = true;
  const rim = new THREE.Mesh(new THREE.SphereGeometry(0.27, 24, 16), new THREE.ShaderMaterial({ vertexShader: RIM_VERT, fragmentShader: RIM_FRAG,
    uniforms: { uColor: { value: C("#7f9cff") }, uPower: { value: 1.2 } }, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false }));
  const face = new THREE.Group();
  const eyeMat = new THREE.MeshBasicMaterial({ color: 0x18203a });
  const eyeGeo = new THREE.SphereGeometry(0.042, 12, 8);
  const eyes = [-1, 1].map((s) => { const e = new THREE.Mesh(eyeGeo, eyeMat); e.position.set(s * 0.088, 0.035, 0.2); e.scale.set(1, 1.55, 0.6); face.add(e);
    const glint = new THREE.Mesh(new THREE.SphereGeometry(0.012, 6, 4), new THREE.MeshBasicMaterial({ color: 0xffffff })); glint.position.set(0.012, 0.018, 0.035); e.add(glint); return e; });
  const motes = [];
  for (let i = 0; i < 3; i++) { const m = new THREE.Mesh(new THREE.SphereGeometry(0.025, 8, 6), new THREE.MeshBasicMaterial({ color: 0xc8d6ff })); g.add(m); motes.push(m); }
  g.add(core, rim, face);
  S.scene.add(g);
  S.synth = { group: g, core, rim, face, eyes, motes, x: 0, z: 0, y: 0, heading: 0, blinkT: 2, blink: 0, init: false, sleep: 0 };
}
// ───────────────────────────────────────────────────────────── environment (sky, light, fog)
function makeEnv() {
  const e = { top: new THREE.Color(), hor: new THREE.Color(), bot: new THREE.Color(), sun: new THREE.Color(), hemS: new THREE.Color(), hemG: new THREE.Color(),
    sunI: 2, hemI: 1, sunDir: new THREE.Vector3(0.5, 0.8, 0.3), moonDir: new THREE.Vector3(0, -1, 0), stars: 0, sunVis: 1, moonVis: 0, fogN: 70, fogF: 280,
    night: 0, cloud: 0.5, cloudCol: 1, rain: 0, snowfall: 0, snow: 0, wind: 1, storm: 0, rainbow: 0, t: null };
  e.cur = null; return e;
}
function computeEnvTargets() {
  const L = S.live, isDay = (L.phase || "day") !== "night", sun = clamp(Number(L.sun ?? 0.35), 0, 1);
  const arc = Math.sin(Math.PI * sun), e = isDay ? arc : -arc;
  const ang = Math.PI * sun;
  const dir = new THREE.Vector3(Math.cos(ang), Math.max(0.06, arc * 0.92), 0.38).normalize();
  const P = (k) => (e < 0 ? SKY.twi[k].clone().lerp(SKY.night[k], smooth(0, 0.3, -e))
    : e < 0.2 ? SKY.twi[k].clone().lerp(SKY.gold[k], smooth(0, 0.2, e)) : SKY.gold[k].clone().lerp(SKY.day[k], smooth(0.2, 0.55, e)));
  const Pn = (k) => (e < 0 ? lerp(SKY.twi[k], SKY.night[k], smooth(0, 0.3, -e))
    : e < 0.2 ? lerp(SKY.twi[k], SKY.gold[k], smooth(0, 0.2, e)) : lerp(SKY.gold[k], SKY.day[k], smooth(0.2, 0.55, e)));
  const wx = WEATHER[L.weather] || WEATHER.clear;
  const dayF = smooth(-0.3, 0.45, e) * 0.85 + 0.15;
  const t = {
    top: P("top").lerp(shade(wx.top, dayF), wx.mix), hor: P("hor").lerp(shade(wx.hor, dayF), wx.mix), bot: P("bot").lerp(shade(wx.hor, dayF * 0.8), wx.mix),
    sun: P("sun"), hemS: P("hemS").lerp(shade(wx.hor, dayF), wx.mix * 0.6), hemG: P("hemG"),
    sunI: Pn("sunI") * (isDay ? wx.light : lerp(1, wx.light, 0.6)), hemI: Pn("hemI") * lerp(1, 1.05, wx.mix) * (L.weather === "rain" ? 0.8 : L.weather === "storm" ? 0.55 : 1),
    sunDir: isDay ? dir : new THREE.Vector3(-dir.x * 0.6, Math.max(0.25, arc * 0.8), -0.45).normalize(),
    moonDir: isDay ? new THREE.Vector3(0, -1, 0) : new THREE.Vector3(Math.cos(ang), Math.max(0.12, arc * 0.85), -0.4).normalize(),
    stars: isDay ? 0 : smooth(0.05, 0.35, -e) * (L.weather === "clear" ? 1 : L.weather === "cloudy" ? 0.25 : 0),
    sunVis: isDay ? wx.sunVis * smooth(-0.05, 0.08, e + 0.06) : 0, moonVis: isDay ? 0 : (wx.sunVis * 0.8 + 0.2) * (L.weather === "rain" || L.weather === "storm" ? 0.1 : 1),
    night: isDay ? smooth(0.25, -0.05, e) * 0.6 : smooth(0, 0.25, -e) * 0.4 + 0.6,
    fogN: wx.fog[0], fogF: wx.fog[1], cloud: wx.cloud, cloudCol: wx.cloudCol,
    rain: L.weather === "rain" || L.weather === "storm" ? 1 : 0, snowfall: L.weather === "snow" ? 1 : 0,
    storm: L.weather === "storm" ? 1 : 0, rainbow: L.env?.rainbow ? 1 : 0,
    snow: Math.max(L.season === "winter" ? 0.75 : 0, L.weather === "snow" ? 1 : 0),
    wind: L.weather === "storm" ? 3.2 : L.weather === "rain" ? 2.2 : L.weather === "snow" ? 1.4 : L.weather === "cloudy" ? 1.4 : 1,
  };
  if (!isDay) t.sunDir.copy(t.moonDir); // the directional light is the moon at night
  S.env.t = t;
  if (!S.env.cur) { S.env.cur = true; Object.assign(S.env, cloneEnv(t)); }
}
function cloneEnv(t) { const o = {}; for (const k in t) o[k] = t[k]?.clone ? t[k].clone() : t[k]; return o; }
function updateEnv(dt) {
  const E = S.env, t = E.t; if (!t) return;
  const a = damp(1.6, dt), slow = damp(0.35, dt);
  for (const k of ["top", "hor", "bot", "sun", "hemS", "hemG"]) E[k].lerp(t[k], a);
  E.sunDir.lerp(t.sunDir, a).normalize(); E.moonDir.lerp(t.moonDir, a).normalize();
  for (const k of ["sunI", "hemI", "stars", "sunVis", "moonVis", "night", "fogN", "fogF", "cloud", "cloudCol", "rain", "snowfall", "wind", "storm"]) E[k] = lerp(E[k], t[k], a);
  E.rainbow = lerp(E.rainbow, t.rainbow, damp(0.8, dt));
  // lightning: a bright double flash every few seconds in a storm
  if (E.storm > 0.5) {
    S.flashT = (S.flashT ?? 2) - dt;
    if (S.flashT < 0) { S.flashT = 3 + Math.random() * 6; S.flashSeq = [0, 0.14 + Math.random() * 0.1]; S.flashAge = 0; }
  }
  let flash = 0;
  if (S.flashSeq) { S.flashAge += dt; for (const st of S.flashSeq) { const a2 = S.flashAge - st; if (a2 >= 0) flash = Math.max(flash, Math.exp(-a2 * 14) * (st ? 0.75 : 1)); } if (S.flashAge > 1.2) S.flashSeq = null; }
  S.flash = flash;
  E.snow = lerp(E.snow, t.snow, slow);
  U.snow.value = E.snow; U.wind.value = E.wind;
  const sk = S.skyMat.uniforms;
  sk.uTop.value.copy(E.top); sk.uHor.value.copy(E.hor); sk.uBot.value.copy(E.bot); sk.uSunDir.value.copy(S.live.phase === "night" ? E.moonDir : E.sunDir);
  sk.uSunCol.value.copy(E.sun); sk.uStars.value = E.stars; sk.uSunVis.value = E.sunVis; sk.uMoonDir.value.copy(E.moonDir); sk.uMoonVis.value = E.moonVis;
  S.sun.color.copy(E.sun); S.sun.intensity = E.sunI;
  S.hemi.color.copy(E.hemS); S.hemi.groundColor.copy(E.hemG); S.hemi.intensity = E.hemI + flash * 3.2;
  if (flash > 0.01) { sk.uTop.value.lerp(C("#c9d4ff"), flash * 0.55); sk.uHor.value.lerp(C("#e6ecff"), flash * 0.5); }
  S.bowMat.uniforms.uAlpha.value = E.rainbow * 0.34 * (1 - E.night) * (1 - E.rain * 0.6); S.bow.visible = S.bowMat.uniforms.uAlpha.value > 0.005;
  // fog follows the horizon colour; distances grow with the camera distance (overview)
  const cd = S.cam.dist;
  S.scene.fog.color.copy(E.hor);
  const fk = S.live.weather === "fog" ? 0.45 : 1;
  S.scene.fog.near = E.fogN + cd * 0.9 * fk; S.scene.fog.far = Math.max(E.fogF, E.fogN + 25) + cd * 1.6 * fk;
  // water
  const wu = S.waterMat.uniforms;
  wu.uSky.value.copy(E.hor).lerp(E.top, 0.35);
  wu.uSunDir.value.copy(E.sunDir); wu.uSunCol.value.copy(E.sun).multiplyScalar(Math.max(E.sunVis, E.moonVis * 0.6));
  const amb = tmpC.copy(E.hemS).multiplyScalar(E.hemI * 0.55).add(new THREE.Color().copy(E.sun).multiplyScalar(E.sunI * Math.max(E.sunDir.y, 0) * 0.28));
  wu.uAmb.value.copy(amb); wu.uFoam.value.copy(amb).multiplyScalar(0.95);
  wu.uSpec.value = lerp(1, 0.3, E.night);
  // sprite light level
  const lv = amb.clone().multiplyScalar(1 / 1.05);
  const m = Math.max(lv.r, lv.g, lv.b); if (m > 1.1) lv.multiplyScalar(1.1 / m);
  lv.r = Math.max(lv.r, 0.24); lv.g = Math.max(lv.g, 0.26); lv.b = Math.max(lv.b, 0.34);
  U.light.value.copy(lv);
  // night: warm windows
  (S.glassMats || []).forEach((m, bi) => { if (!m) return;
    const tgt = S.bLit?.[bi] ? 1 : 0; S.bGlow[bi] = lerp(S.bGlow[bi] ?? tgt, tgt, damp(3, dt));
    m.emissiveIntensity = E.night * 2.2 * S.bGlow[bi]; });
  S.renderer.toneMappingExposure = 1.0 + E.night * 0.25;
  // weather particles
  S.rainMat.uniforms.uAlpha.value = E.rain * 0.42 + E.storm * 0.14; S.rain.visible = E.rain > 0.01; S.rainMat.uniforms.uHeavy.value = E.storm;
  S.rainMat.uniforms.uColor.value.copy(E.hor).lerp(C("#ffffff"), 0.4);
  S.snowMat.uniforms.uAlpha.value = E.snowfall * 0.9; S.snowP.visible = E.snowfall > 0.01;
  if (S.flyMat) S.flyMat.uniforms.uAlpha.value = E.night > 0.7 && E.rain < 0.5 && E.snowfall < 0.5 && S.live.season !== "winter" ? smooth(0.7, 0.95, E.night) : 0;
  // clouds
  S.cloudMat.color.copy(new THREE.Color(1, 1, 1).multiplyScalar(E.cloudCol));
  S.cloudMat.emissive.copy(E.hor).multiplyScalar(0.45);
  S.cloudMat.opacity = 0.95 - 0.88 * smooth(24, 50, S.camera.position.y);
  S.clouds.visible = S.cloudMat.opacity > 0.1;
}


// fireflies on summer nights: a cloud of blinking lights that follows the view
function makeFireflies() {
  const n = 70, pos = new Float32Array(n * 3), seed = new Float32Array(n * 4), r = rng(77);
  for (let i = 0; i < n; i++) { pos.set([(r() - 0.5) * 36, 0.4 + r() * 0.8, (r() - 0.5) * 36], i * 3); seed.set([r(), r(), r(), r()], i * 4); }
  const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.BufferAttribute(pos, 3)); g.setAttribute("aSeed", new THREE.BufferAttribute(seed, 4));
  S.flyMat = new THREE.ShaderMaterial({ vertexShader: FLY_VERT.replace("vec3 p = position;", "vec3 p = (modelMatrix * vec4(position, 1.0)).xyz;"), fragmentShader: FLY_FRAG, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    uniforms: { uTime: U.time, uPR: { value: 1 }, uAlpha: { value: 0 } } });
  S.flies = new THREE.Points(g, S.flyMat); S.flies.frustumCulled = false; S.scene.add(S.flies);
}

// ───────────────────────────────────────────────────────────── snapshots
const RENDER_KEYS = ["jx", "jz"];
function mergeEnt(old, e) {
  let n;
  if (old && e.kind !== undefined) { n = Object.assign({}, e); for (const k of RENDER_KEYS) if (old[k] !== undefined) n[k] = old[k]; }
  else n = Object.assign(old ? Object.assign({}, old) : {}, e);
  if (!old) { const h = hashStr(String(e.id)); n.jx = ((h & 255) / 255 - 0.5) * 0.4; n.jz = (((h >> 8) & 255) / 255 - 0.5) * 0.4; }
  return n;
}
function full(snap) {
  if (!S.inited || !snap) return;
  S.ents.clear();
  for (const e of snap.ents || []) S.ents.set(e.id, mergeEnt(null, e));
  S.entsVersion++;
  if (snap.kinds) S.kinds = Object.assign({}, S.kinds, snap.kinds);
  applyLive(snap, true);
}
function delta(snap) {
  if (!S.inited || !snap) return;
  for (const e of snap.ents || []) S.ents.set(e.id, mergeEnt(S.ents.get(e.id), e));
  for (const id of snap.removed || []) S.ents.delete(id);
  if ((snap.ents && snap.ents.length) || (snap.removed && snap.removed.length)) S.entsVersion++;
  if (snap.kinds) S.kinds = Object.assign({}, S.kinds, snap.kinds);
  applyLive(snap, false);
}
function applyLive(s, isFull) {
  const L = S.live, wasW = L.weather, wasS = L.season;
  for (const k of ["tick", "day", "phase", "season", "weather", "time", "light", "sun", "temperature", "env"]) if (s[k] !== undefined) L[k] = s[k];
  if (L.weather !== wasW && S.rain) setRainDensity();
  if (L.season !== wasS && !isFull) { /* leaves change colour through uniforms; snow on the ground follows */ }
  if (s.zen) S.zenData = Object.assign({}, S.zenData || {}, s.zen);
  if (s.sprite) S.spriteData = Object.assign({}, S.spriteData || {}, s.sprite);
  if (s.mind) S.mind = Object.assign({}, S.mind || {}, s.mind);
  if ("studio" in s) S.studio = s.studio || null;
  if (s.home) S.home = s.home;
  if (s.places) S.places = s.places;
  if (s.animals) syncAnimals(s.animals);
  if ("visitor" in s) {
    S.visitorData = s.visitor;
    if (s.visitor && S.mode === "visit" && S.local.init) {
      const v = s.visitor, fx = v.fx ?? v.x, fy = v.fy ?? v.y;
      if (Math.hypot(fx + 0.5 - S.local.x, fy + 0.5 - S.local.z) > 4) { S.local.x = fx + 0.5; S.local.z = fy + 0.5; S.local.vx = S.local.vz = 0; }
    }
  }
  if (isFull && S.zenData && !S.synth.init) { const z = S.zenData; S.cam.target.set((z.fx ?? z.x) + 0.5, 2, (z.fy ?? z.y) + 0.5); S.cam.free.copy(S.cam.target); }
  computeEnvTargets();
  const st = SEASON_T[L.season] || SEASON_T.summer;
  S.seasonT = st;
}

// ───────────────────────────────────────────────────────────── per-frame updates
function updateSeason(dt) {
  const st = S.seasonT || SEASON_T.summer, a = damp(0.6, dt);
  U.autumn.value = lerp(U.autumn.value, st.autumn, a); U.bare.value = lerp(U.bare.value, st.bare, a);
  U.grassTint.value.lerp(st.grass, a);
}
function updateClouds(dt) {
  const cp = S.camera.position, visible = Math.round(S.cloudClusters.length * clamp(S.env.cloud, 0, 1));
  let i = 0;
  S.cloudClusters.forEach((cl, ci) => {
    cl.x += cl.sp * dt * (0.5 + S.env.wind * 0.5);
    const rx = ((cl.x - cp.x) % 260 + 390) % 260 - 130, rz = ((cl.z - cp.z) % 220 + 330) % 220 - 110;
    const show = ci < visible;
    for (const p of cl.puffs) {
      const s = show ? p.s : 0.0001;
      tmpM.compose(tmpV.set(cp.x + rx + p.ox, Math.max(cl.y, cp.y * 0.4 + 22) + p.oy, cp.z + rz + p.oz), tmpQ.setFromAxisAngle(tmpV2.set(0, 1, 0), p.ry), tmpS.set(s * 1.25, s * 0.72, s));
      S.clouds.setMatrixAt(i++, tmpM);
    }
  });
  S.clouds.instanceMatrix.needsUpdate = true;
  S.clouds.castShadow = false;
}
function moveToward(o, tx, tz, dt, base = 4.4) {
  const dx = tx - o.x, dz = tz - o.z, d = Math.hypot(dx, dz);
  if (!o.init || d > 6) { o.x = tx; o.z = tz; o.init = true; return 0; }
  if (d < 1e-4) return 0;
  const step = Math.max(base, d * 4) * dt;
  if (step >= d) { o.x = tx; o.z = tz; } else { o.x += (dx / d) * step; o.z += (dz / d) * step; }
  o.dirX = dx / d; o.dirZ = dz / d;
  return Math.min(step, d) / Math.max(dt, 1e-4);
}
function turnTo(cur, target, k) { let d = target - cur; while (d > Math.PI) d -= Math.PI * 2; while (d < -Math.PI) d += Math.PI * 2; return cur + d * k; }
function floorY(x, z) { const fn = featAt(Math.floor(x), Math.floor(z)); return fn === "floor" || fn === "door" ? bedAt(Math.floor(x), Math.floor(z)) + 0.12 : standY(x, z); }

function updateSynth(dt, t) {
  const a = S.zenData, sy = S.synth; sy.group.visible = !!a;
  if (!a) { S.facingMark && (S.facingMark.visible = false); return; }
  const sleeping = !!a.sleeping;
  const speed = moveToward(sy, (a.fx ?? a.x) + 0.5, (a.fy ?? a.y) + 0.5, dt, 3.2);
  const ground = floorY(sy.x, sy.z);
  sy.groundY = lerp(sy.groundY ?? ground, ground, damp(10, dt));
  sy.sleep = lerp(sy.sleep, sleeping ? 1 : 0, damp(3, dt));
  const bob = Math.sin(t * 2.1) * 0.06 * (1 - sy.sleep * 0.6);
  sy.y = sy.groundY + 0.52 - sy.sleep * 0.24 + bob;
  sy.group.position.set(sy.x, sy.y, sy.z);
  // where it looks: where it is going, or the way it faces; at the Sprite while it waits for an answer
  let target = speed > 0.3 ? Math.atan2(sy.dirX, sy.dirZ) : angleOf(a.facing);
  if ((a.waiting || S.mind?.waiting) && S.sprite.init) target = Math.atan2(S.sprite.x - sy.x, S.sprite.z - sy.z);
  sy.heading = turnTo(sy.heading, target, damp(8, dt));
  sy.face.rotation.y = sy.heading;
  sy.blinkT -= dt; if (sy.blinkT < 0) { sy.blink = 0.14; sy.blinkT = 2.5 + Math.random() * 3; }
  sy.blink = Math.max(0, sy.blink - dt);
  const open = sleeping ? 0.12 : sy.blink > 0 ? 0.15 : 1;
  for (const e of sy.eyes) e.scale.y = lerp(e.scale.y, 1.55 * open, damp(25, dt));
  const pulse = 1 + Math.sin(t * 2.6) * 0.08;
  sy.core.material.emissiveIntensity = (0.72 + S.env.night * 0.2 - sy.sleep * 0.3) * pulse;
  sy.rim.material.uniforms.uPower.value = (1.1 + S.env.night * 0.3 - sy.sleep * 0.5) * pulse;
  sy.motes.forEach((m, i) => { const ang = t * (0.9 + i * 0.25) + i * 2.1, r = 0.38 + i * 0.04;
    m.position.set(Math.cos(ang) * r, Math.sin(t * 1.3 + i) * 0.12, Math.sin(ang) * r); m.visible = !sleeping; });
  S.adaLight.position.set(sy.x, sy.y + 0.1, sy.z);
  S.adaLight.intensity = (0.6 + S.env.night * 3) * (1 - sy.sleep * 0.5);
  // the facing chevron on the ground
  if (!S.facingMark) S.facingMark = makeFacing();
  const fa = angleOf(a.facing), fm = S.facingMark;
  fm.visible = !sleeping;
  fm.position.set(sy.x + Math.sin(fa) * 0.52, sy.groundY + 0.04, sy.z + Math.cos(fa) * 0.52);
  fm.rotation.y = fa; fm.material.opacity = 0.35 + 0.25 * Math.sin(t * 3) ** 2;
}
function updateSprite(dt, t) {
  const d = S.spriteData, sp = S.sprite; sp.group.visible = !!d;
  if (!d) return;
  moveToward(sp, (d.fx ?? d.x) + 0.5, (d.fy ?? d.y) + 0.5, dt, 2.2);
  const ground = Math.max(floorY(sp.x, sp.z), S.synth.groundY ?? -99);
  const state = d.state || "idle", want = state === "answering" ? 1.9 : state === "listening" ? 1.45 : 0.85;
  sp.glow = lerp(sp.glow, want, damp(3, dt));
  const bob = Math.sin(t * 1.7) * 0.12 + Math.sin(t * 3.3) * 0.04;
  sp.y = lerp(sp.y || ground + 1.1, ground + 1.1 + bob, damp(6, dt));
  sp.group.position.set(sp.x, sp.y, sp.z);
  const flick = state === "answering" ? 1 + Math.sin(t * 13) * 0.08 + Math.sin(t * 7.1) * 0.06 : 1;
  sp.core.scale.setScalar((0.9 + sp.glow * 0.15) * flick);
  sp.halo.scale.setScalar(1 + sp.glow * 0.25 + Math.sin(t * 2.4) * 0.05);
  sp.halo.material.uniforms.uPower.value = 1.2 + sp.glow * 0.8;
  sp.ring.material.opacity = state === "listening" ? 0.35 + 0.3 * Math.sin(t * 4) ** 2 : state === "answering" ? 0.25 : 0;
  sp.ring.scale.setScalar(1 + (t * 0.8 % 1) * (state === "listening" ? 0.8 : 0.3));
  sp.ring.rotation.z = t;
  S.spriteLight.position.copy(sp.group.position); S.spriteLight.intensity = (0.8 + S.env.night * 2.4) * sp.glow;
  // a fading trail of sparks
  sp.trailT -= dt;
  if (sp.trailT < 0) { sp.trailT = 0.06; sp.trail.push([sp.x, sp.y, sp.z, t]); if (sp.trail.length > 16) sp.trail.shift(); }
}

// things: emoji for small things, glows for fire and lamps, a shadow under each; the Sprite's glow and trail; Zen's hands
function updateSprites(dt, t) {
  const E = S.entBB, B = S.blobBB, G = S.glowBB, FX = S.fxBB, night = S.env.night;
  E.begin(); B.begin(); G.begin(); FX.begin();
  const cp = S.camera.position, lit = [];
  let fi = 0, puffs = [];
  for (const e of S.ents.values()) {
    const dx = e.x + 0.5 - cp.x, dz = e.y + 0.5 - cp.z; if (dx * dx + dz * dz > 70 * 70) continue;
    const x = e.x + 0.5, z = e.y + 0.5, y = entY(e), obj = S.entObjs.get(e.id);
    if (LIGHTS.has(e.kind) && e.lit) lit.push({ x, y: y + (e.kind === "fireplace" ? 0.4 : 0.3), z, fire: e.kind !== "lantern", e });
    if (obj) continue;
    const px = x + (e.jx || 0), pz = z + (e.jz || 0), c = entCell(e), h = 0.42 * (e.size || 1);
    E.push(px, y, pz, h * c.aspect, h, c.u, c.v, c.us, c.vs);
    B.push(px, y + 0.02, pz, 0.45, 0.45, 0, 0, 1, 1, 1, 1, 1, 0.6);
  }
  for (const s of lit) {
    const fl = s.fire ? 0.85 + Math.sin(t * 11 + s.x) * 0.08 + Math.sin(t * 17.3) * 0.06 : 1;
    G.push(s.x, s.y, s.z, s.fire ? 1.4 * fl : 0.9, s.fire ? 1.4 * fl : 0.9, 0, 0, 1, 1, 1, 0.62, 0.25, 0.7 + night * 0.5);
    if (s.fire && fi < 8) S.fireU[fi++].set(s.x, s.y - 0.15, s.z, 1);
    if (s.fire && s.e.kind === "fireplace" && S.chimney && insideAnyRoof(s.x, s.z)) puffs.push([S.chimney.x, S.chimney.y, S.chimney.z, 0.8, 2.6, 0.35, 0.82, 0.22]);
  }
  for (; fi < 8; fi++) S.fireU[fi].w = 0;
  S.puffSrc.forEach((v, i) => { const p = puffs[i]; if (!p) { v.w = 0; return; } v.set(p[0], p[1], p[2], p[3]); S.puffPar[i].set(p[4], p[5], p[6], p[7]); });
  lit.sort((a, b) => Math.hypot(a.x - cp.x, a.z - cp.z) - Math.hypot(b.x - cp.x, b.z - cp.z));
  S.pool.forEach((l, i) => { const s = lit[i]; if (!s) { l.intensity = 0; return; } l.position.set(s.x, s.y + 0.3, s.z); l.intensity = (s.fire ? 6 : 3) * (0.4 + night) * (s.fire ? 0.9 + Math.sin(t * 9 + i) * 0.1 : 1); });
  // the Sprite
  const sp = S.sprite;
  if (sp.group.visible) {
    const gl = sp.glow;
    G.push(sp.x, sp.y, sp.z, 0.9 + gl * 0.7, 0.9 + gl * 0.7, 0, 0, 1, 1, 1, 0.86, 0.55, 0.45 + gl * 0.35);
    G.push(sp.x, sp.y, sp.z, 0.35, 0.35, 0, 0, 1, 1, 1, 0.97, 0.85, 0.9);
    for (const [x, y, z, t0] of sp.trail) { const age = t - t0, a = Math.max(0, 1 - age / 1.0); if (a <= 0) continue;
      G.push(x + Math.sin(t0 * 31) * 0.05, y - age * 0.15, z + Math.cos(t0 * 27) * 0.05, 0.12 * a + 0.04, 0.12 * a + 0.04, 0, 0, 1, 1, 1, 0.9, 0.6, a * 0.7 * gl); }
    for (let i = 0; i < 4; i++) { const an = t * 2.2 + i * Math.PI / 2, r = 0.24 + 0.05 * Math.sin(t * 3 + i);
      G.push(sp.x + Math.cos(an) * r, sp.y + Math.sin(t * 2.7 + i * 1.7) * 0.1, sp.z + Math.sin(an) * r, 0.09, 0.09, 0, 0, 1, 1, 1, 0.95, 0.7, 0.8); }
    B.push(sp.x, floorY(sp.x, sp.z) + 0.03, sp.z, 0.5, 0.5, 0, 0, 1, 1, 1, 1, 1, 0.25);
  }
  // Zen: its glow on the ground and what it holds, circling slowly
  const sy = S.synth;
  if (sy.group.visible) {
    B.push(sy.x, sy.groundY + 0.03, sy.z, 0.75, 0.75, 0, 0, 1, 1, 1, 1, 1, 0.7 * (1 - sy.sleep * 0.4));
    G.push(sy.x, sy.y, sy.z, 1.3, 1.3, 0, 0, 1, 1, 0.55, 0.62, 1.0, 0.18 + night * 0.35);
    const hands = S.zenData?.hands || [];
    hands.forEach((k, i) => {
      const c = kindCell(typeof k === "string" ? k : k.kind), an = t * 0.8 + i * (Math.PI * 2 / Math.max(1, hands.length));
      FX.push(sy.x + Math.cos(an) * 0.42, sy.y - 0.05 + Math.sin(t * 2 + i) * 0.04, sy.z + Math.sin(an) * 0.42, 0.2 * c.aspect, 0.2, c.u, c.v, c.us, c.vs, 1, 1, 1, 0.95);
    });
  }
  // you, when visiting
  if (S.avatar.group.visible) B.push(S.avatar.group.position.x, S.avatar.groundY + 0.03, S.avatar.group.position.z, 0.6, 0.6, 0, 0, 1, 1, 1, 1, 1, 0.6);
  // bees and fireflies
  for (const [, o] of S.animals) if (o.glow && o.gx != null) {
    const bee = /^bees?$/.test(o.data.kind), a = bee ? 0.9 : 0.4 + night * 0.6 * (0.5 + 0.5 * Math.sin(t * 3 + o.ph));
    G.push(o.gx, o.gy, o.gz, bee ? 0.18 : 0.28, bee ? 0.18 : 0.28, 0, 0, 1, 1, o.glow.r, o.glow.g, o.glow.b, a);
    if (bee) { const c = kindCell("bee"); FX.push(o.gx, o.gy, o.gz, 0.14 * c.aspect, 0.14, c.u, c.v, c.us, c.vs, 1, 1, 1, 1); }
  } else if (!o.glow && o.group.visible) {
    const s = ANIMAL[o.data.kind]; if (s && !s.swim && o.alt < 1) B.push(o.x, standY(o.x, o.z) + 0.03, o.z, s.body[2] * 1.4, s.body[2] * 1.4, 0, 0, 1, 1, 1, 1, 1, 0.5);
  }
  E.end(); B.end(); G.end(); FX.end();
}
function entCell(e) { return kindCell(e.kind, e.glyph); }
function kindCell(kind, glyph) {
  const g = glyph || S.kinds[kind]?.glyph || GLYPH[kind] || (kind === "bee" ? "🐝" : "❔");
  return glyphCell("g:" + g, g, null, kind || "?");
}
// the easel shows the painting as it grows
function updateEasel(dt) {
  const st = S.studio; if (!st || !window.Studio) return;
  const m = window.Studio.normMedium(st.medium); if (m !== "paint") return;
  S.easelT = (S.easelT || 0) - dt; if (S.easelT > 0) return; S.easelT = 0.5;
  let best = null, bd = 1e9;
  for (const [id, o] of S.entObjs) { if (!o.userData.canvas) continue; const d = Math.hypot(o.position.x - S.synth.x, o.position.z - S.synth.z); if (d < bd) { bd = d; best = o; } }
  if (!best || bd > 6) return;
  window.Studio.setLive(st); window.Studio.drawLive(best.userData.canvas); best.userData.tex.needsUpdate = true;
}

// ───────────────────────────────────────────────────────────── you (visiting)
function updateVisitorFigure(dt, t) {
  const av = S.avatar, v = S.visitorData;
  let x, z;
  if (S.mode === "visit" && S.local.init) { x = S.local.x; z = S.local.z; av.heading = turnTo(av.heading, S.local.heading, damp(10, dt)); }
  else if (v) { moveToward(av, (v.fx ?? v.x) + 0.5, (v.fy ?? v.y) + 0.5, dt); x = av.x; z = av.z; av.heading = turnTo(av.heading, angleOf(v.facing), damp(8, dt)); }
  av.group.visible = !!v || (S.mode === "visit" && S.local.init);
  if (!av.group.visible) return;
  av.groundY = floorY(x, z);
  av.group.position.set(x, av.groundY + 0.42 + (S.mode === "visit" ? S.local.hop : 0) + Math.sin(t * 2.4) * 0.03, z);
  av.face.rotation.y = av.heading;
  av.group.visible = !(S.mode === "visit" && S.cam.fp);
}

// ───────────────────────────────────────────────────────────── labels (DOM)
function label(key, cls) {
  let l = S.labels.get(key);
  if (!l) { const el = document.createElement("div"); el.className = cls; S.layer.appendChild(el); l = { el, text: null, vis: true }; S.labels.set(key, l); }
  return l;
}
function placeLabel(l, pos, opacity, yOff = 0, defer = null) {
  tmpV.copy(pos).project(S.camera);
  const vis = opacity > 0.02 && tmpV.z < 1 && tmpV.z > -1 && Math.abs(tmpV.x) < 1.2 && Math.abs(tmpV.y) < 1.2;
  if (!vis) { if (l.vis) { l.el.style.display = "none"; l.vis = false; } return; }
  if (!l.vis) { l.el.style.display = ""; l.vis = true; }
  const x = (tmpV.x * 0.5 + 0.5) * S.vw, y = (-tmpV.y * 0.5 + 0.5) * S.vh + yOff;
  if (defer) defer.push({ l, x, y, z: tmpV.z });
  else l.el.style.transform = `translate3d(${x.toFixed(1)}px,${y.toFixed(1)}px,0) translate(-50%,-100%)`;
  const o = opacity.toFixed(2); if (l.op !== o) { l.el.style.opacity = o; l.op = o; }
  l.el.style.zIndex = String(1000 - Math.round(tmpV.z * 1000));
}
function setText(l, t) { if (l.text !== t) { l.text = t; l.el.textContent = t; } }
function updateLabels() {
  const cam = S.camera.position, fade = (d, near, far) => 1 - smooth(near, far, d), live = new Set(), bubbles = [];
  const z = S.zenData, sp = S.spriteData;
  const chars = [];
  if (S.synth.group.visible && z) chars.push(["zen", S.name || "Zen", S.synth.group.position, 0.45, z.said, z.sleeping, "synth", z.sleeping ? "" : (z.waiting || S.mind?.waiting ? "waiting for the Sprite…" : z.activity)]);
  if (S.sprite.group.visible && sp) chars.push(["sprite", "Sprite", S.sprite.group.position, 0.3, sp.said, false, "sprite",
    sp.state === "listening" ? "listening…" : sp.state === "answering" ? "answering" : ""]);
  if (S.avatar.group.visible && S.visitorData && S.mode !== "visit") chars.push(["you", "you", S.avatar.group.position, 0.45, S.visitorData.said, false, "", ""]);
  if (S.mode === "visit" && S.visitorData?.said) chars.push(["you", "", S.avatar.group.position, 0.45, S.visitorData.said, false, "", ""]);
  for (const [key, name, pos, hgt, said, sleeping, kind, activity] of chars) {
    const p = tmpV2.copy(pos); p.y += hgt; const d = cam.distanceTo(p), act = String(activity || "").trim();
    if (name) {
      const l = label(key, "w3d-tag" + (kind ? " w3d-tag-" + kind : "")); setText(l, name); live.add(key);
      const op = kind === "synth" ? Math.max(0.85 * fade(d, 40, 120), fade(d, 14, 34)) : fade(d, 16, 40);
      placeLabel(l, p, op, act ? -13 : 0);
      if (act) { const al = label(key + ":a", "w3d-act"); setText(al, act); live.add(key + ":a"); placeLabel(al, p, op * fade(d, 14, 30), 3); }
    }
    if (said) {
      const b = label(key + ":b", "w3d-bubble" + (kind ? " w3d-bubble-" + kind : ""));
      if (b.text !== said) { b.text = said; b.el.innerHTML = `<span>${escapeHtml(said)}</span>`; b.w = 0; }
      live.add(key + ":b"); placeLabel(b, p, fade(d, 26, 55), -22, bubbles);
    }
    if (sleeping) { const zz = label(key + ":z", "w3d-zzz"); if (!zz.el.firstChild) zz.el.innerHTML = "<i>z</i><i>z</i><i>z</i>"; live.add(key + ":z"); placeLabel(zz, p, fade(d, 25, 50), -20); }
  }
  bubbles.sort((a, b) => a.z - b.z);
  const placed = [];
  for (const bb of bubbles) {
    if (!bb.l.w) { bb.l.w = bb.l.el.offsetWidth; bb.l.h = bb.l.el.offsetHeight; }
    const w = bb.l.w, h = bb.l.h; let y = bb.y, x = clamp(bb.x, w / 2 + 6, S.vw - w / 2 - 6);
    for (let guard = 0; guard < 8; guard++) {
      const hit = placed.find((r) => Math.abs(r.x - x) < (r.w + w) / 2 + 4 && y > r.y - r.h - 4 && y - h < r.y + 4);
      if (!hit) break; y = hit.y - hit.h - 6;
    }
    y = Math.max(y, h + 6);
    placed.push({ x, y, w, h });
    bb.l.el.style.transform = `translate3d(${x.toFixed(1)}px,${y.toFixed(1)}px,0) translate(-50%,-100%)`;
  }
  // names of places nearby
  const known = new Set((S.places || []).map((p) => p.name));
  for (const ch of S.chunks.values()) for (const pl of ch.labels || []) {
    const key = "place:" + pl.name + pl.x + "," + pl.z, d = Math.hypot(pl.x - S.cam.target.x, pl.z - S.cam.target.z);
    if (d > 60) continue;
    const l = label(key, "w3d-place" + (known.has(pl.name) ? " known" : "")); setText(l, pl.kind === "home" ? "🏡 " + pl.name : pl.name); live.add(key);
    placeLabel(l, tmpV2.set(pl.x, pl.y, pl.z), fade(d, 28, 55) * (0.55 + 0.45 * smooth(6, 16, S.cam.dist)));
  }
  for (const [k, l] of S.labels) if (!live.has(k)) { if (k.startsWith("place:")) { l.el.remove(); S.labels.delete(k); } else if (l.vis) { l.el.style.display = "none"; l.vis = false; } }
}

// ───────────────────────────────────────────────────────────── camera
function focusPoint() {
  const c = S.cam;
  if (S.mode === "visit" && S.local.init) return tmpV2.set(S.local.x, S.local.y + (c.fp ? 0.62 : 0.75) + S.local.hop * (c.fp ? 1 : 0.4), S.local.z).clone();
  if (S.mode === "free") return c.free.clone().setY(groundY(c.free.x, c.free.z) + 1.0);
  if (c.focus === "sprite" && S.sprite.init) return new THREE.Vector3(S.sprite.x, S.sprite.y, S.sprite.z);
  if (c.focus === "home" && S.home) return new THREE.Vector3(S.home.x + 0.5, groundY(S.home.x + 0.5, S.home.y + 0.5) + 1, S.home.y + 0.5);
  if (S.zenData) { const sy = S.synth, a = S.zenData; return sy.init ? new THREE.Vector3(sy.x, sy.y, sy.z) : new THREE.Vector3((a.fx ?? a.x) + 0.5, groundY((a.fx ?? a.x) + 0.5, (a.fy ?? a.y) + 0.5) + 0.5, (a.fy ?? a.y) + 0.5); }
  return null;
}
function updateCamera(dt) {
  const c = S.cam, cam = S.camera, visit = S.mode === "visit";
  c.yaw = turnTo(c.yaw, c.tYaw, visit ? 1 : damp(10, dt));
  c.pitch = lerp(c.pitch, c.tPitch, visit ? 1 : damp(10, dt));
  c.dist = lerp(c.dist, c.tDist, damp(7, dt));
  if (S.mode === "free") {       // WASD pans the free camera
    const K = S.keys, sp = (K.has("ShiftLeft") || K.has("ShiftRight") ? 40 : 14) * dt * (0.5 + c.dist / 20);
    const fx = -Math.sin(c.yaw), fz = -Math.cos(c.yaw);
    if (K.has("KeyW") || K.has("ArrowUp")) c.free.x += fx * sp, c.free.z += fz * sp;
    if (K.has("KeyS") || K.has("ArrowDown")) c.free.x -= fx * sp, c.free.z -= fz * sp;
    if (K.has("KeyD") || K.has("ArrowRight")) c.free.x -= fz * sp, c.free.z += fx * sp;
    if (K.has("KeyA") || K.has("ArrowLeft")) c.free.x += fz * sp, c.free.z -= fx * sp;
  }
  const f = focusPoint();
  if (f) { if (c.target.distanceTo(f) > 40) c.target.copy(f); else c.target.lerp(f, visit ? 1 : damp(6, dt)); }
  const off = tmpV.set(Math.sin(c.yaw) * Math.cos(c.pitch), Math.sin(c.pitch), Math.cos(c.yaw) * Math.cos(c.pitch));
  if (visit && c.fp) { cam.position.copy(c.target); cam.lookAt(c.target.x - off.x, c.target.y - off.y, c.target.z - off.z); }
  else {
    let dist = c.dist;
    const look = tmpV2.copy(c.target);
    if (visit) { const sh = 0.3 * clamp(dist / 4, 0, 1); look.x += Math.cos(c.yaw) * sh; look.z -= Math.sin(c.yaw) * sh; }
    cam.position.copy(look).addScaledVector(off, dist);
    const gy = Math.max(groundY(cam.position.x, cam.position.z), waterAt(Math.floor(cam.position.x), Math.floor(cam.position.z))) + 0.4;
    if (cam.position.y < gy) cam.position.y = gy;
    cam.lookAt(look);
  }
  S.sky.position.copy(cam.position);
  S.weatherCenter.value.copy(cam.position);
  const half = clamp(c.dist * 1.6, 22, 48), sc = S.sun.shadow.camera;
  if (sc.right !== half) { sc.left = -half; sc.right = half; sc.top = half; sc.bottom = -half; sc.near = 1; sc.far = 260; sc.updateProjectionMatrix(); }
  const tex = (half * 2) / S.sun.shadow.mapSize.x, tgt = tmpV2.copy(c.target);
  tgt.x = Math.round(tgt.x / tex) * tex; tgt.z = Math.round(tgt.z / tex) * tex;
  S.sun.target.position.copy(tgt); S.sun.position.copy(tgt).addScaledVector(S.env.sunDir, 120);
  S.sun.target.updateMatrixWorld();
  S.flies.position.set(Math.round(c.target.x / 4) * 4, groundY(c.target.x, c.target.z), Math.round(c.target.z / 4) * 4);
}
function updateBow() {
  if (!S.bow.visible) return;
  const cp = S.camera.position, D = 560, sd = S.env.sunDir;
  let dx = -sd.x * 0.35, dz = -1; const l = Math.hypot(dx, dz); dx /= l; dz /= l;
  S.bow.position.set(cp.x + dx * D, cp.y - D * 0.16, cp.z + dz * D); S.bow.scale.setScalar(D * 0.6); S.bow.lookAt(cp.x, cp.y - D * 0.16, cp.z);
}
// fog: the far edge of the loaded land dissolves into the sky
function updateFog() {
  const E = S.env, d = S.cam.dist, reach = RADIUS * N + 14;
  const fogW = S.live.weather === "fog";
  S.scene.fog.near = (fogW ? 2 : Math.min(E.fogN, 30)) + d * 0.35;
  S.scene.fog.far = Math.min(fogW ? 34 : E.fogF, reach) + d * 0.55;
  S.scene.fog.color.copy(E.hor);
}

// ───────────────────────────────────────────────────────────── visit mode
function initLocal() {
  const L = S.local, v = S.visitorData;
  if (v) { L.x = (v.fx ?? v.x) + 0.5; L.z = (v.fy ?? v.y) + 0.5; L.facing = facingNum(v.facing); }
  else if (S.zenData) { L.x = S.synth.x || S.zenData.x + 0.5; L.z = (S.synth.z || S.zenData.y + 0.5) + 1.5; if (blockedTile(Math.floor(L.x), Math.floor(L.z))) L.z -= 3; L.facing = 0; }
  else return;
  L.y = floorY(L.x, L.z); L.vx = L.vz = 0; L.init = true; L.heading = angleOf(L.facing);
  S.cam.tYaw = S.cam.yaw = L.heading + Math.PI; S.cam.tPitch = S.cam.pitch = 0.32; S.cam.tDist = S.cam.dist = 4.6;
}
function collide(p, r = 0.28) {
  for (let it = 0; it < 3; it++) {
    for (let ty = Math.floor(p.z - r); ty <= Math.floor(p.z + r); ty++) for (let tx = Math.floor(p.x - r); tx <= Math.floor(p.x + r); tx++) {
      if (!blockedTile(tx, ty)) continue;
      const cx = clamp(p.x, tx, tx + 1), cz = clamp(p.z, ty, ty + 1), dx = p.x - cx, dz = p.z - cz, d2 = dx * dx + dz * dz;
      if (d2 >= r * r) continue;
      if (d2 > 1e-9) { const d = Math.sqrt(d2), push = r - d; p.x += (dx / d) * push; p.z += (dz / d) * push; }
      else { const o = [[p.x - tx + r, -1, 0], [tx + 1 - p.x + r, 1, 0], [p.z - ty + r, 0, -1], [ty + 1 - p.z + r, 0, 1]].sort((a, b) => a[0] - b[0]); p.x += o[0][1] * o[0][0]; p.z += o[0][2] * o[0][0]; }
    }
  }
}
function updateVisit(dt, now) {
  const L = S.local; if (!L.init) { initLocal(); if (!L.init) return; }
  const K = S.keys, c = S.cam, fwd = [-Math.sin(c.yaw), -Math.cos(c.yaw)], right = [Math.cos(c.yaw), -Math.sin(c.yaw)];
  let ix = 0, iz = 0;
  if (K.has("KeyW") || K.has("ArrowUp")) { ix += fwd[0]; iz += fwd[1]; }
  if (K.has("KeyS") || K.has("ArrowDown")) { ix -= fwd[0]; iz -= fwd[1]; }
  if (K.has("KeyD") || K.has("ArrowRight")) { ix += right[0]; iz += right[1]; }
  if (K.has("KeyA") || K.has("ArrowLeft")) { ix -= right[0]; iz -= right[1]; }
  const il = Math.hypot(ix, iz); if (il > 0) { ix /= il; iz /= il; }
  const sp = K.has("ShiftLeft") || K.has("ShiftRight") ? 6 : 3.2, a = damp(il > 0 ? 9 : 12, dt);
  L.vx = lerp(L.vx, ix * sp, a); L.vz = lerp(L.vz, iz * sp, a);
  const p = { x: L.x + L.vx * dt, z: L.z + L.vz * dt };
  if (tileRef(Math.floor(p.x), Math.floor(p.z))) collide(p); else { p.x = L.x; p.z = L.z; }    // never into land not loaded yet
  const mx = (p.x - L.x) / Math.max(dt, 1e-4), mz = (p.z - L.z) / Math.max(dt, 1e-4);
  L.x = p.x; L.z = p.z; L.vx = lerp(L.vx, mx, 0.5); L.vz = lerp(L.vz, mz, 0.5);
  L.y = lerp(L.y, floorY(L.x, L.z), damp(12, dt));
  if (L.hop > 0 || L.hv > 0) { L.hv -= 18 * dt; L.hop += L.hv * dt; if (L.hop <= 0) { L.hop = 0; L.hv = 0; } }
  const moving = Math.hypot(L.vx, L.vz) > 0.25;
  if (moving) { L.heading = Math.atan2(L.vx, L.vz); L.facing = Math.abs(L.vx) > Math.abs(L.vz) ? (L.vx > 0 ? 1 : 3) : (L.vz > 0 ? 2 : 0); }
  if (moving && now - L.lastSend > 120) { L.lastSend = now; sendMove(); }
  if (!moving && L.wasMoving) sendMove();
  L.wasMoving = moving;
  updateInteraction();
}
function sendMove() { const L = S.local; try { World3D.onMove?.(+(L.x - 0.5).toFixed(3), +(L.z - 0.5).toFixed(3), L.facing); } catch (e) { console.error(e); } }
function near(o, r) { return o.group.visible && o.init && Math.hypot(o.x - S.local.x, o.z - S.local.z) <= r; }
function updateInteraction() {
  const L = S.local, c = S.cam, fx = -Math.sin(c.yaw), fz = -Math.cos(c.yaw);
  let best = null, bestS = 1e9;
  const consider = (x, z, target, verb) => {
    const dx = x - L.x, dz = z - L.z, d = Math.hypot(dx, dz); if (d > 1.7) return;
    const dot = d > 1e-3 ? (dx * fx + dz * fz) / d : 1; if (dot < 0.2 && d > 0.8) return;
    const s = d + (1 - dot) * 1.3 - (target.kind === "entity" ? 0 : 0.35); if (s < bestS) { bestS = s; best = { target, verb }; }
  };
  const zen = S.name || "Zen";
  if (S.zenData && S.synth.group.visible) consider(S.synth.x, S.synth.z, { kind: "synth" }, `Talk to ${zen}`);
  for (const e of S.ents.values()) {
    if (S.entObjs.has(e.id)) continue;
    consider(e.x + 0.5 + (e.jx || 0), e.y + 0.5 + (e.jz || 0), { kind: "entity", id: e.id, entKind: e.kind }, `Take the ${String(e.kind).replace(/_/g, " ")}`);
  }
  S.interactTarget = best;
  const chips = [];
  if (best) chips.push(["E", best.verb]);
  if (S.visitorData?.hands?.length && near(S.synth, 2.2)) chips.push(["G", `Give ${zen} the ${S.visitorData.hands.at(-1)}`]);
  chips.push(["T", "Say something"]);
  const html = chips.map(([k, t]) => `<span class="w3d-chip"><kbd>${k}</kbd>${escapeHtml(t)}</span>`).join("");
  if (html !== S.promptHtml) { S.promptHtml = html; S.prompt.innerHTML = html; }
  S.prompt.hidden = !html;
}
function act(a) { try { World3D.onAction?.(a); } catch (e) { console.error(e); } }

// ───────────────────────────────────────────────────────────── input: drag to orbit (or pan, in free mode), wheel/pinch to zoom
function bindInput() {
  const el = S.renderer.domElement;
  el.addEventListener("contextmenu", (e) => e.preventDefault());
  el.addEventListener("pointerdown", (e) => {
    if (S.locked) return;
    S.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (S.pointers.size === 2) { const [a, b] = [...S.pointers.values()]; S.pinch = { d: Math.hypot(a.x - b.x, a.y - b.y), dist: S.cam.tDist }; S.drag = null; return; }
    S.drag = { x: e.clientX, y: e.clientY, moved: false, id: e.pointerId, button: e.button, pan: S.mode === "free" && e.button === 0 && !e.shiftKey };
    try { el.setPointerCapture(e.pointerId); } catch { /* fine */ }
  });
  el.addEventListener("pointermove", (e) => {
    const c = S.cam;
    if (S.locked) { look(e.movementX, e.movementY); return; }
    if (S.pointers.has(e.pointerId)) S.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (S.pinch && S.pointers.size === 2) { const [a, b] = [...S.pointers.values()], d = Math.hypot(a.x - b.x, a.y - b.y);
      c.tDist = clamp(S.pinch.dist * S.pinch.d / Math.max(20, d), 2.5, 70); return; }
    const d = S.drag; if (!d) { hover(e); return; }
    if (S.hoverEl) S.hoverEl.hidden = true;
    const dx = e.clientX - d.x, dy = e.clientY - d.y;
    if (!d.moved && Math.hypot(dx, dy) < 4) return;
    d.moved = true; d.x = e.clientX; d.y = e.clientY;
    if (S.mode === "visit") look(dx, dy);
    else if (d.pan) { const k = c.dist * 0.0022, rx = Math.cos(c.yaw), rz = -Math.sin(c.yaw), fx = -Math.sin(c.yaw), fz = -Math.cos(c.yaw);
      c.free.x += (-rx * dx + fx * dy) * k; c.free.z += (-rz * dx + fz * dy) * k; }
    else { c.tYaw -= dx * 0.006; c.tPitch = clamp(c.tPitch + dy * 0.004, 0.08, 1.45); }
  });
  const up = (e) => {
    S.pointers.delete(e.pointerId); if (S.pointers.size < 2) S.pinch = null;
    const d = S.drag; S.drag = null;
    try { el.releasePointerCapture(e.pointerId); } catch { /* fine */ }
    if (!d || d.moved) return;
    if (S.mode === "visit") { if (e.pointerType === "mouse") requestLock(); return; }
    pick(e);
  };
  el.addEventListener("pointerup", up); el.addEventListener("pointercancel", (e) => { S.pointers.delete(e.pointerId); S.drag = null; S.pinch = null; });
  el.addEventListener("pointerleave", () => { if (S.hoverEl) S.hoverEl.hidden = true; });
  el.addEventListener("wheel", (e) => {
    e.preventDefault();
    const c = S.cam, f = Math.pow(1.0015, e.deltaY * (e.deltaMode === 1 ? 30 : 1));
    if (S.mode === "visit") { if (!c.fp) c.tDist = clamp(c.tDist * f, 1.8, 10); return; }
    c.tDist = clamp(c.tDist * f, 2.5, 70);
  }, { passive: false });
  window.addEventListener("keydown", onKey);
  window.addEventListener("keyup", (e) => S.keys.delete(e.code));
  window.addEventListener("blur", () => S.keys.clear());
}
function look(dx, dy) {
  const c = S.cam;
  c.tYaw -= dx * 0.0024; c.yaw = c.tYaw;
  c.tPitch = clamp(c.tPitch + dy * 0.0022, c.fp ? -1.3 : -0.35, c.fp ? 1.3 : 1.25); c.pitch = c.tPitch;
}
function requestLock() { try { const p = S.renderer.domElement.requestPointerLock?.(); if (p?.catch) p.catch(() => {}); } catch { /* fine */ } }
const MOVE_KEYS = ["KeyW", "KeyA", "KeyS", "KeyD", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "ShiftLeft", "ShiftRight"];
function onKey(e) {
  if (S.mode === "watch" || isTyping() || e.ctrlKey || e.metaKey || e.altKey || S.paused) return;
  const code = e.code;
  if (MOVE_KEYS.includes(code)) { S.keys.add(code); if (code.startsWith("Arrow")) e.preventDefault(); return; }
  if (S.mode !== "visit" || e.repeat) return;
  switch (code) {
    case "Space": e.preventDefault(); if (S.local.hop === 0) S.local.hv = 4.6, S.local.hop = 0.001; break;
    case "KeyE": { const t = S.interactTarget?.target; if (t?.kind === "entity") act({ type: "take", id: t.id }); else if (t) act({ type: "talk" }); break; }
    case "KeyG": if (near(S.synth, 2.2)) act({ type: "give" }); break;
    case "KeyT": case "Enter": case "NumpadEnter": e.preventDefault(); if (document.pointerLockElement) document.exitPointerLock(); S.keys.clear(); act({ type: "talk" }); break;
    case "KeyV": S.cam.fp = !S.cam.fp; S.cam.tPitch = S.cam.pitch = S.cam.fp ? 0 : 0.32; updateHud(); break;
    default: return;
  }
}
function updateHud() {
  const v = S.mode === "visit";
  S.cross.hidden = !(v && (S.locked || S.cam.fp));
  S.hint.hidden = !(v && !S.locked) && S.mode !== "free";
  S.hint.innerHTML = v ? `<b>Click</b> to look around · <b>WASD</b> walk · <b>Shift</b> run · <b>E</b> take · <b>G</b> give · <b>T</b> talk · <b>V</b> first person · <b>Esc</b> release`
    : `<b>Drag</b> to move over the land · <b>Shift+drag</b> or right-drag to turn · <b>WASD</b> fly · <b>wheel</b> zoom`;
  if (!v) S.prompt.hidden = true;
  S.container.classList.toggle("w3d-visit", v); S.container.classList.toggle("w3d-free", S.mode === "free"); S.container.classList.toggle("w3d-locked", S.locked);
}

// ───────────────────────────────────────────────────────────── picking and hover
function pick(e) { const best = pickAt(e, true); if (best) try { World3D.onPick?.(best); } catch (err) { console.error(err); } }
function pickAt(e, terrain) {
  const rect = S.renderer.domElement.getBoundingClientRect(), mx = e.clientX - rect.left, my = e.clientY - rect.top;
  let best = null, bestD = 1e9;
  const test = (pos, hgt, radius, info) => {
    tmpV.copy(pos); tmpV.y += hgt; tmpV.project(S.camera); if (tmpV.z > 1) return;
    const sx = (tmpV.x * 0.5 + 0.5) * rect.width, sy = (-tmpV.y * 0.5 + 0.5) * rect.height;
    const dist = S.camera.position.distanceTo(pos), rpx = Math.max(14, radius * rect.height / (dist * 0.95));
    const d = Math.hypot(sx - mx, sy - my); if (d < rpx && d / rpx < bestD) { bestD = d / rpx; best = info; }
  };
  if (S.synth.group.visible) test(S.synth.group.position, 0, 0.45, { kind: "synth" });
  if (S.sprite.group.visible) test(S.sprite.group.position, 0, 0.35, { kind: "sprite" });
  for (const [id, o] of S.animals) if (o.init) test(new THREE.Vector3(o.gx ?? o.x, o.gy ?? o.y, o.gz ?? o.z), 0.2, 0.4, { kind: "animal", id, animal: o.data.kind });
  for (const ent of S.ents.values()) {
    const o = S.entObjs.get(ent.id), y0 = entY(ent);
    test(new THREE.Vector3(ent.x + 0.5 + (o ? 0 : ent.jx || 0), y0, ent.y + 0.5 + (o ? 0 : ent.jz || 0)), o ? 0.5 : 0.2, o ? 0.7 : 0.3, { kind: "entity", id: ent.id, entKind: ent.kind });
  }
  if (!best && terrain) {
    const ray = new THREE.Raycaster(); ray.setFromCamera(new THREE.Vector2((mx / rect.width) * 2 - 1, -(my / rect.height) * 2 + 1), S.camera);
    const hits = ray.intersectObjects([...S.chunks.values()].filter((c) => c.terrain).map((c) => c.terrain), false);
    if (hits[0]) { const p = hits[0].point, x = Math.floor(p.x), y = Math.floor(p.z); best = { kind: "tile", x, y, ...(infoAt(x, y) || {}) }; }
  }
  return best;
}
function hover(e) {
  if (S.mode === "visit" || S.drag) { if (S.hoverEl) S.hoverEl.hidden = true; return; }
  const now = performance.now(); if (now - (S.hoverT || 0) < 90) return; S.hoverT = now;
  const best = pickAt(e, false);
  if (!S.hoverEl) { S.hoverEl = document.createElement("div"); S.hoverEl.className = "w3d-hover"; S.container.appendChild(S.hoverEl); }
  const el = S.hoverEl;
  let html = "";
  if (best?.kind === "entity") { const ent = S.ents.get(best.id); if (ent) html = `<b>${escapeHtml(`${kindGlyph(ent.kind)} ${ent.name || String(ent.kind).replace(/_/g, " ")}`)}</b>${ent.lit ? " <span>lit</span>" : ""}${ent.text ? `<div>${escapeHtml(String(ent.text).slice(0, 80))}</div>` : ""}`; }
  else if (best?.kind === "animal") html = `<b>${escapeHtml(best.animal)}</b>`;
  else if (best?.kind === "synth") html = `<b>${escapeHtml(S.name || "Zen")}</b> <span>click to follow</span>`;
  else if (best?.kind === "sprite") html = `<b>✨ The Sprite of All Knowing</b> <span>${escapeHtml(S.spriteData?.state || "")}</span>`;
  if (!html) { el.hidden = true; return; }
  if (el.dataset.h !== html) { el.innerHTML = html; el.dataset.h = html; }
  const rect = S.container.getBoundingClientRect();
  el.style.transform = `translate(${Math.round(e.clientX - rect.left + 14)}px, ${Math.round(e.clientY - rect.top + 16)}px)`;
  el.hidden = false;
}
const kindGlyph = (k) => S.kinds[k]?.glyph || GLYPH[k] || "";

// ───────────────────────────────────────────────────────────── main loop
// A frame cap: 60 fps (30 on Low), whatever the screen's refresh rate. The browser isn't even asked for a
// frame until the next one is due, so the GPU (and its heat) stays with the Academy's training.
function nextFrame() {
  const gap = S.quality === "low" ? 1000 / 30 : 1000 / 60;
  const wait = Math.max(0, gap - (performance.now() - S.lastFrame) - 3);
  S.raf = setTimeout(() => requestAnimationFrame(frame), wait);
}
function frame(now) {
  if (S.paused) { S.raf = null; return; }
  nextFrame();
  const minGap = S.quality === "low" ? 1000 / 31 : 1000 / 61;
  if (now - S.lastFrame < minGap) return;
  const dt = Math.min(0.1, (now - S.lastFrame) / 1000); S.lastFrame = now;
  if (!S.vw || !S.vh || S.container.clientWidth === 0) return;
  const t0 = performance.now();
  U.time.value += dt; const t = U.time.value;
  updateEnv(dt); updateFog(); updateSeason(dt);
  if (S.mode === "visit") updateVisit(dt, now);
  updateSynth(dt, t); updateSprite(dt, t); updateVisitorFigure(dt, t); updateAnimals(dt, t);
  updateClouds(dt);
  updateCamera(dt);
  updateChunks(S.cam.target.x, S.cam.target.z);
  runJobs(); updateDetail();
  syncEnts(); updateRoofs(dt); updateEasel(dt);
  updateSprites(dt, t);
  updateBow();
  const pr = S.renderer.getPixelRatio(), k = pr * (S.vh / 900);
  S.snowMat.uniforms.uPR.value = k; S.emberMat.uniforms.uPR.value = k; S.puffMat.uniforms.uPR.value = k; S.flyMat.uniforms.uPR.value = k;
  S.renderer.render(S.scene, S.camera);
  updateLabels();
  const st = S.stats, info = S.renderer.info.render, ms = performance.now() - t0;
  st.drawCalls = info.calls; st.triangles = info.triangles; st.frameMax = Math.max(st.frameMax, ms);
  st.frames++; st.msAcc += ms;
  if (now - st.last > 1000) { st.fps = Math.round((st.frames * 1000) / (now - st.last)); st.ms = +(st.msAcc / st.frames).toFixed(2); st.frames = 0; st.msAcc = 0; st.last = now; }
}

// ───────────────────────────────────────────────────────────── public API
function setMode(mode) {
  if (!S.inited) return;
  mode = mode === "visit" ? "visit" : mode === "free" ? "free" : "watch";
  if (mode === S.mode) return;
  const was = S.mode;
  S.mode = mode; S.keys.clear(); if (S.hoverEl) S.hoverEl.hidden = true;
  if (mode === "visit") { S.local.init = false; S.cam.fp = false; initLocal(); }
  else {
    if (document.pointerLockElement) document.exitPointerLock();
    S.cam.fp = false; S.prompt.hidden = true;
    if (was === "visit") { S.cam.tPitch = 0.62; S.cam.tDist = 14; }
    if (mode === "free") S.cam.free.copy(S.cam.target);
  }
  updateHud();
}
function setQuality(q) {
  if (!S.inited) return;
  q = q === "low" ? "low" : "high"; if (q === S.quality) return;
  S.quality = q;
  S.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, DPR_CAP[q]));
  S.renderer.shadowMap.enabled = q === "high";
  setRainDensity(); S.snowP.geometry.setDrawRange(0, q === "high" ? 2400 : 900);
  makeLightPool();
  S.scene.traverse((o) => { if (o.material) (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => (m.needsUpdate = true)); });
  rebuildAll(); resize();
}
function focusOn(what) {
  if (!S.inited) return;
  const c = S.cam;
  if (S.mode === "free" && what !== "free") setMode("watch");
  c.focus = what === "sprite" ? "sprite" : what === "home" ? "home" : "synth";
  if (S.mode !== "visit") { c.tDist = what === "sprite" ? 8 : 14; c.tPitch = 0.6; }
}
function pause(p) {
  S.paused = !!p;
  if (!p) { S.lastFrame = performance.now(); if (S.raf == null && S.inited) nextFrame(); }
}
function stats() {
  const s = S.stats, out = { fps: s.fps, drawCalls: s.drawCalls, triangles: s.triangles, ms: s.ms, chunks: [...S.chunks.values()].filter((c) => c.done).length,
    building: S.jobs.length, jobMax: +s.jobMax.toFixed(1), frameMax: +s.frameMax.toFixed(1), built: s.built };
  s.jobMax = 0; s.frameMax = 0;
  return out;
}
World3D.setName = (n) => { S.name = n; };
World3D.flyTo = (x, y) => { if (!S.inited) return; setMode("free"); S.cam.free.set(x + 0.5, 0, y + 0.5); };
World3D.mode = () => S.mode;
World3D.groundAt = (x, y) => infoAt(x, y);
World3D._debug = S;
S.snapAll = () => { S.env.cur = null; computeEnvTargets(); U.snow.value = S.env.snow; const f = focusPoint(); if (f) S.cam.target.copy(f); S.cam.yaw = S.cam.tYaw; S.cam.pitch = S.cam.tPitch; S.cam.dist = S.cam.tDist; };
window.World3D = World3D;
export default World3D;
