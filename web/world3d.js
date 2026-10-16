// world3d.js — the 3D view of the valley (three.js r170, vendored).
// One self-contained ES module. Exposes window.World3D and `export default World3D`.
// Coordinates: tile (x, y) occupies world X x..x+1 and world Z y..y+1; height is world Y.
// Continuous positions (fx, fy, onMove) are in tile units where an integer value is the tile centre
// (so fx = 12.0 is the centre of tile 12, world X = 12.5).
import * as THREE from "./vendor/three.module.min.js";

// ───────────────────────────────────────────────────────────── constants
const BLOCKING = new Set([1, 3, 4, 8, 13, 15, 18]);
const WATERISH = new Set([1, 11, 16]);
const LH = 0.6;            // world height of one terrace level
const WATER_Y = -0.2;      // water surface
const BED_Y = -0.85;       // river / lake bed
const BASE_Y = -2.6;       // bottom of the diorama skirt
const WALL_H = 1.75;       // building wall height
const EMOJI_FONT = `"Segoe UI Emoji","Apple Color Emoji","Noto Color Emoji","Twemoji Mozilla",sans-serif`;
const FACING = { north: [0, -1], south: [0, 1], east: [1, 0], west: [-1, 0] };
const DPR_CAP = { high: 1.5, low: 1 };
const READ_KINDS = new Set(["sign", "book"]);
const LIGHT_KINDS = new Set(["lamp", "candle", "fireplace", "stove", "lantern"]);
const FURN_KINDS = new Set(["fireplace", "stove", "oven", "sink", "pantry", "piano", "bookshelf", "bed", "table", "desk", "bench", "rug"]);   // drawn in 3D
const HIDDEN_KINDS = new Set(["window"]);                                                     // never drawn
const SURFACE_Y = { table: 0.64, desk: 0.68, bench: 0.4, stove: 0.8, workbench: 0.55, "chopping block": 0.42 };
const TILED_ROOM = /kitchen|wash|bath|scullery|larder/i;

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
function vary(c, seed, amt = 0.06) { const f = 1 + (seed - 0.5) * 2 * amt; return shade(c, f); }
function isTyping() {
  const a = document.activeElement; if (!a) return false;
  const tag = a.tagName; return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || a.isContentEditable;
}

// ───────────────────────────────────────────────────────────── shared uniforms + material patch
const U = {
  time: { value: 0 }, snow: { value: 0 }, wind: { value: 1 }, light: { value: new THREE.Color(1, 1, 1) },
  // dollhouse cut-away: walls of one building on the camera side of the focus are lowered
  cutBox: { value: new THREE.Vector4(0, 0, -1, -1) }, cutFocus: { value: new THREE.Vector2() }, cutDir: { value: new THREE.Vector2(0, 1) },
  cutY: { value: 99 },
};
const PV = `uniform float uTime; uniform float uWind; varying vec3 vW3Pos; varying vec3 vW3N;`;
function patch(mat, { snow = 0, wind = 0, key = "", cut = false } = {}) {
  mat.defines = Object.assign(mat.defines || {}, { W3_SNOW: snow.toFixed(3), W3_WIND: wind | 0, W3_CUT: cut ? 1 : 0 });
  mat.onBeforeCompile = (sh) => {
    sh.uniforms.uTime = U.time; sh.uniforms.uWind = U.wind; sh.uniforms.uSnow = U.snow;
    sh.uniforms.uCutBox = U.cutBox; sh.uniforms.uCutFocus = U.cutFocus; sh.uniforms.uCutDir = U.cutDir; sh.uniforms.uCutY = U.cutY;
    sh.vertexShader = sh.vertexShader
      .replace("#include <common>", "#include <common>\n" + PV + `
#if W3_CUT > 0
attribute vec3 aAnchor; uniform vec4 uCutBox; uniform vec2 uCutFocus; uniform vec2 uCutDir; uniform float uCutY;
#endif`)
      .replace("#include <begin_vertex>", `#include <begin_vertex>
#if W3_WIND > 0
{ vec3 ip = vec3(0.0);
#ifdef USE_INSTANCING
  ip = instanceMatrix[3].xyz;
#endif
  float ph = uTime * 1.6 + ip.x * 0.55 + ip.z * 0.37;
#if W3_WIND == 1
  float amt = max(position.y, 0.0) * 0.32;
#else
  float amt = 0.045;
#endif
  transformed.x += sin(ph) * amt * uWind;
  transformed.z += cos(ph * 0.83 + 1.3) * amt * uWind * 0.7;
}
#endif
#if W3_CUT > 0
// parts inside the cut building: interior ones always, outer-wall ones on the camera side of the focus.
// A part starting above the cut line folds away below it; a part crossing it is squashed down to it.
if (aAnchor.x > uCutBox.x && aAnchor.x < uCutBox.z && aAnchor.y > uCutBox.y && aAnchor.y < uCutBox.w) {
  bool inner = aAnchor.x > uCutBox.x + 0.5 && aAnchor.x < uCutBox.z - 0.5 && aAnchor.y > uCutBox.y + 0.5 && aAnchor.y < uCutBox.w - 0.5;
  if (inner || dot(aAnchor.xy - uCutFocus, uCutDir) > 0.3) {
    if (aAnchor.z > uCutY - 0.01) transformed.y = uCutY - 0.06;
    else if (transformed.y > uCutY) transformed.y = uCutY + (transformed.y - uCutY) * 0.03;
  }
}
#endif`)
      .replace("#include <project_vertex>", `#include <project_vertex>
{ vec4 w3p = vec4(transformed, 1.0); vec3 w3n = objectNormal;
#ifdef USE_INSTANCING
  w3p = instanceMatrix * w3p; w3n = mat3(instanceMatrix) * w3n;
#endif
  vW3Pos = (modelMatrix * w3p).xyz; vW3N = normalize(mat3(modelMatrix) * w3n); }`);
    sh.fragmentShader = sh.fragmentShader
      .replace("#include <common>", `#include <common>
uniform float uSnow; varying vec3 vW3Pos; varying vec3 vW3N;
float w3h(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float w3n(vec2 p) { vec2 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);
  return mix(mix(w3h(i), w3h(i + vec2(1.0, 0.0)), f.x), mix(w3h(i + vec2(0.0, 1.0)), w3h(i + vec2(1.0, 1.0)), f.x), f.y); }`)
      .replace("#include <color_fragment>", `#include <color_fragment>
{ float sn = uSnow * float(W3_SNOW);
  if (sn > 0.001) {
    float up = smoothstep(0.3, 0.9, normalize(vW3N).y);
    float n = w3n(vW3Pos.xz * 0.9) * 0.55 + w3n(vW3Pos.xz * 3.1 + 7.0) * 0.3 + w3n(vW3Pos.xz * 9.0) * 0.15;
    float cov = clamp(smoothstep(0.08, 0.3, up * sn - n * 0.42 + 0.06), 0.0, 1.0);
    diffuseColor.rgb = mix(diffuseColor.rgb, vec3(0.90, 0.94, 1.0), cov);
  } }`);
  };
  mat.customProgramCacheKey = () => "w3" + snow + "_" + wind + (cut ? "c" : "") + key;
  return mat;
}
function lambert(opts, p) { return patch(new THREE.MeshLambertMaterial(opts), p); }

// ───────────────────────────────────────────────────────────── geometry accumulator
class Builder {
  // anchored builders store, per vertex, the xz centre of the part it belongs to (for the wall cut-away)
  constructor(anchored = false) { this.p = []; this.n = []; this.c = []; this.anchored = anchored; this.a = []; this.anc = [0, 0]; }
  get count() { return this.p.length / 3; }
  tri(a, b, c, n, ca, cb, cc) {
    // orient so the face normal agrees with n
    const ux = b[0] - a[0], uy = b[1] - a[1], uz = b[2] - a[2], vx = c[0] - a[0], vy = c[1] - a[1], vz = c[2] - a[2];
    const cx = uy * vz - uz * vy, cy = uz * vx - ux * vz, cz = ux * vy - uy * vx;
    if (cx * n[0] + cy * n[1] + cz * n[2] < 0) { [b, c] = [c, b]; [cb, cc] = [cc, cb]; }
    this.p.push(...a, ...b, ...c); this.n.push(...n, ...n, ...n);
    this.c.push(ca.r, ca.g, ca.b, cb.r, cb.g, cb.b, cc.r, cc.g, cc.b);
    if (this.anchored) { const [ax, az, ay = -99] = this.anc; this.a.push(ax, az, ay, ax, az, ay, ax, az, ay); }
  }
  quad(a, b, c, d, n, ca, cb = ca, cc = ca, cd = ca) { this.tri(a, b, c, n, ca, cb, cc); this.tri(a, c, d, n, ca, cc, cd); }
  geom(g, m, color, shadeFn) {
    const ng = (g.index ? g.toNonIndexed() : g.clone()); ng.applyMatrix4(m);
    const P = ng.attributes.position.array, N = ng.attributes.normal.array, VC = ng.attributes.color?.array;
    for (let i = 0; i < P.length; i += 3) {
      this.p.push(P[i], P[i + 1], P[i + 2]); this.n.push(N[i], N[i + 1], N[i + 2]);
      let r = color.r, gg = color.g, b = color.b;
      if (VC) { r *= VC[i]; gg *= VC[i + 1]; b *= VC[i + 2]; }
      if (shadeFn) { const f = shadeFn(P[i], P[i + 1], P[i + 2]); r *= f; gg *= f; b *= f; }
      this.c.push(r, gg, b);
      if (this.anchored) this.a.push(this.anc[0], this.anc[1], this.anc[2] ?? -99);
    }
    ng.dispose();
  }
  box(cx, cy, cz, sx, sy, sz, color, ry = 0, shadeFn) {
    tmpM.compose(tmpV.set(cx, cy, cz), tmpQ.setFromAxisAngle(tmpV2.set(0, 1, 0), ry), tmpS.set(sx, sy, sz));
    if (this.anchored && !this.lockAnc) this.anc = [cx, cz, cy - sy / 2];
    this.geom(UNIT_BOX, tmpM, color, shadeFn);
  }
  build() {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(this.p, 3));
    g.setAttribute("normal", new THREE.Float32BufferAttribute(this.n, 3));
    g.setAttribute("color", new THREE.Float32BufferAttribute(this.c, 3));
    if (this.anchored) g.setAttribute("aAnchor", new THREE.Float32BufferAttribute(this.a, 3));
    g.computeBoundingSphere(); g.computeBoundingBox();
    return g;
  }
}
const UNIT_BOX = new THREE.BoxGeometry(1, 1, 1);

// Chunked instancing so the camera and the shadow camera can cull parts of the valley.
class Scatter {
  constructor(geom, mat, { cast = true, receive = true, chunk = S.quality === "low" ? 64 : 32 } = {}) {
    this.geom = geom; this.mat = mat; this.cast = cast; this.receive = receive; this.chunk = chunk; this.items = new Map();
  }
  add(x, z, m, color) {
    const k = Math.floor(x / this.chunk) + "," + Math.floor(z / this.chunk);
    let a = this.items.get(k); if (!a) this.items.set(k, a = []);
    a.push([m.clone(), color.clone()]);
  }
  build(parent) {
    const meshes = [];
    for (const list of this.items.values()) {
      const im = new THREE.InstancedMesh(this.geom, this.mat, list.length);
      list.forEach(([m, c], i) => { im.setMatrixAt(i, m); im.setColorAt(i, c); });
      im.instanceMatrix.needsUpdate = true; if (im.instanceColor) im.instanceColor.needsUpdate = true;
      im.computeBoundingSphere(); im.castShadow = this.cast; im.receiveShadow = this.receive;
      parent.add(im); meshes.push(im);
    }
    return meshes;
  }
}
function mat4(x, y, z, sx = 1, sy = sx, sz = sx, ry = 0, rx = 0, rz = 0) {
  const q = new THREE.Quaternion().setFromEuler(new THREE.Euler(rx, ry, rz));
  return new THREE.Matrix4().compose(new THREE.Vector3(x, y, z), q, new THREE.Vector3(sx, sy, sz));
}

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
const WATER_VERT = `
uniform float uTime; attribute float aShore; varying float vShore; varying vec3 vWPos;
#include <fog_pars_vertex>
void main() {
  vec3 p = position;
  p.y += (sin(p.x * 1.1 + uTime * 1.3) + sin(p.z * 1.4 - uTime * 1.1)) * 0.022 * (1.0 - aShore);
  vShore = aShore; vec4 wp = modelMatrix * vec4(p, 1.0); vWPos = wp.xyz;
  vec4 mvPosition = viewMatrix * wp; gl_Position = projectionMatrix * mvPosition;
  #include <fog_vertex>
}`;
const WATER_FRAG = `
uniform float uTime, uSpec; uniform vec3 uDeep, uShallow, uSky, uSunDir, uSunCol, uAmb, uFoam;
varying float vShore; varying vec3 vWPos;
#include <fog_pars_fragment>
void wave(vec2 q, vec2 k, float a, float w, inout vec2 g) { g += a * k * cos(dot(k, q) + w * uTime); }
void main() {
  vec2 q = vWPos.xz; vec2 g = vec2(0.0);
  wave(q, vec2(1.1, 0.0), 0.025, 1.3, g); wave(q, vec2(0.0, 1.4), 0.025, -1.1, g);
  wave(q, vec2(2.3, 1.7), 0.014, 2.1, g); wave(q, vec2(-3.1, 2.6), 0.010, 2.7, g);
  wave(q, vec2(5.3, -4.1), 0.006, 3.5, g); wave(q, vec2(-7.0, 6.2), 0.005, 4.1, g);
  wave(q, vec2(11.0, 9.0), 0.0025, 5.3, g);
  vec3 n = normalize(vec3(-g.x * 2.4, 1.0, -g.y * 2.4));
  vec3 V = normalize(cameraPosition - vWPos);
  float fres = 0.03 + 0.97 * pow(1.0 - max(dot(n, V), 0.0), 5.0);
  vec3 base = mix(uDeep, uShallow, smoothstep(0.0, 0.5, vShore)) * uAmb;
  vec3 col = mix(base, uSky, clamp(fres * 1.15, 0.0, 0.8));
  vec3 H = normalize(V + uSunDir);
  float s = pow(max(dot(n, H), 0.0), 220.0) * uSpec * smoothstep(90.0, 15.0, length(cameraPosition - vWPos));
  col += uSunCol * s * 4.0;
  float fn = sin(q.x * 5.0 + uTime * 1.2) * sin(q.y * 4.3 - uTime * 0.9) * 0.5 + 0.5;
  float foam = smoothstep(0.4, 0.5, vShore + fn * 0.1 - 0.07);
  col = mix(col, uFoam, foam * 0.6);
  float a = mix(0.74, 0.96, fres); a = max(a, foam * 0.8);
  gl_FragColor = vec4(col, a);
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
  #include <fog_fragment>
}`;
// rain: line segments generated entirely on the GPU around the camera
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
const SEASON = {
  spring: { grass: C("#78b24c"), grass2: C("#9cc45a"), leaf: [C("#6fb544"), C("#8cc63f"), C("#5aa23c")], tuft: C("#8ccf55"), field: "young" },
  summer: { grass: C("#5e9a38"), grass2: C("#86a83f"), leaf: [C("#3f8a35"), C("#4f9a3a"), C("#2f7a32")], tuft: C("#6faa3c"), field: "wheat" },
  autumn: { grass: C("#93983f"), grass2: C("#b39a46"), leaf: [C("#d9762b"), C("#c9452a"), C("#e8a93a"), C("#b8862f")], tuft: C("#b8a24a"), field: "stubble" },
  winter: { grass: C("#8a9a84"), grass2: C("#a3ad9c"), leaf: [C("#7d8a74"), C("#8e8f7a")], tuft: C("#9aa58e"), field: "none" },
};
const COL = {
  earth: C("#7d5a3a"), earthDeep: C("#4b3523"), rock: C("#7f7872"), rockDark: C("#56504c"), sand: C("#e4d29c"), sandSide: C("#c4ad78"),
  path: C("#b8946a"), soil: C("#6e4a30"), soilRidge: C("#5a3b26"), plaza: C("#b7b0a3"), snow: C("#eef3f8"), cave: C("#4a4552"),
  bed: C("#6f7552"), plank: C("#a87a4c"), wood: C("#8a643f"), darkWood: C("#5a4030"), stone: C("#8f877b"), pine: C("#2f5e3c"),
  pineFloor: C("#5c6a3c"), trunk: C("#6b4a30"), timber: C("#5b4131"),
};

// ───────────────────────────────────────────────────────────── module state
const S = {
  inited: false, paused: false, quality: "high", mode: "watch",
  container: null, renderer: null, scene: null, camera: null, clock: new THREE.Clock(),
  world: null, sig: "", season: "spring", weather: "clear",
  staticGroup: null, roofs: [], windowGlows: [], doorLamps: [], fireflySpots: [], bLit: [], bGlow: [], treeSpots: new Map(),
  kinds: {}, ents: new Map(), people: new Map(), ada: null, adaData: null, visitorData: null, avatar: null,
  live: { phase: "day", sun: 0.35, season: "spring", weather: "clear", light: 1 },
  env: null, labels: new Map(), layer: null,
  cam: { yaw: -0.65, pitch: 0.72, dist: 13, tYaw: -0.65, tPitch: 0.72, tDist: 13, target: new THREE.Vector3(64, 0, 48), focus: "synth", fp: false },
  local: { x: 0, z: 0, y: 0, vx: 0, vz: 0, hop: 0, hv: 0, facing: "south", heading: 0, init: false, lastSend: 0, wasMoving: false, walkPh: 0 },
  keys: new Set(), locked: false, drag: null, prompt: null, interactTarget: null,
  stats: { fps: 0, drawCalls: 0, triangles: 0, ms: 0, frames: 0, acc: 0, msAcc: 0, last: 0 },
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
  scene.fog = new THREE.Fog(0xc4e4f6, 70, 280);
  S.camera = new THREE.PerspectiveCamera(50, 1, 0.08, 1500);

  // lights
  S.sun = new THREE.DirectionalLight(0xffffff, 2.5);
  S.sun.shadow.mapSize.set(2048, 2048); S.sun.shadow.bias = -0.0004; S.sun.shadow.normalBias = 0.03;
  S.sun.castShadow = true; scene.add(S.sun, S.sun.target);
  S.hemi = new THREE.HemisphereLight(0xd6e9ff, 0x857f55, 1.1); scene.add(S.hemi);
  makeLightPool();

  // sky
  S.skyMat = new THREE.ShaderMaterial({
    vertexShader: SKY_VERT, fragmentShader: SKY_FRAG, side: THREE.BackSide, depthWrite: false, depthTest: false, fog: false,
    uniforms: { uTop: { value: new THREE.Color() }, uHor: { value: new THREE.Color() }, uBot: { value: new THREE.Color() },
      uSunDir: { value: new THREE.Vector3(0, 1, 0) }, uSunCol: { value: new THREE.Color() }, uMoonDir: { value: new THREE.Vector3(0, -1, 0) },
      uStars: { value: 0 }, uTime: U.time, uSunVis: { value: 1 }, uMoonVis: { value: 0 } },
  });
  S.sky = new THREE.Mesh(new THREE.SphereGeometry(900, 32, 16), S.skyMat);
  S.sky.renderOrder = -1000; S.sky.frustumCulled = false; scene.add(S.sky);

  // water material
  S.waterMat = new THREE.ShaderMaterial({
    vertexShader: WATER_VERT, fragmentShader: WATER_FRAG, transparent: true, depthWrite: false, fog: true,
    uniforms: Object.assign(THREE.UniformsUtils.merge([THREE.UniformsLib.fog]), {
      uTime: U.time, uSpec: { value: 1 }, uDeep: { value: C("#1f5f7a") }, uShallow: { value: C("#3fa0a8") },
      uSky: { value: new THREE.Color() }, uSunDir: { value: new THREE.Vector3() }, uSunCol: { value: new THREE.Color() },
      uAmb: { value: new THREE.Color(1, 1, 1) }, uFoam: { value: new THREE.Color(1, 1, 1) } }),
  });

  // textures + billboards
  S.glowTex = radialTex([[0, "rgba(255,255,255,1)"], [0.25, "rgba(255,255,255,.55)"], [0.6, "rgba(255,255,255,.12)"], [1, "rgba(255,255,255,0)"]]);
  S.blobTex = radialTex([[0, "rgba(0,0,0,.55)"], [0.55, "rgba(0,0,0,.32)"], [1, "rgba(0,0,0,0)"]]);
  makeAtlas();
  S.entBB = new Billboards(S.atlasTex, { mode: "cyl", cut: true, lit: true, cap: 512, a2c: S.quality === "high" });
  S.blobBB = new Billboards(S.blobTex, { mode: "flat", lit: false, cap: 512 });
  S.glowBB = new Billboards(S.glowTex, { mode: "sph", additive: true, lit: false, cap: 256 });
  S.glowBB.mesh.renderOrder = 5;
  S.fxBB = new Billboards(S.atlasTex, { mode: "sph", lit: false, cap: 64 }); S.fxBB.mesh.renderOrder = 6;
  scene.add(S.entBB.group, S.blobBB.group, S.glowBB.group, S.fxBB.group);

  makeWeather();
  makeClouds();
  makeSynth();
  S.env = makeEnv();

  // DOM layer
  const layer = S.layer = document.createElement("div"); layer.className = "w3d-layer"; container.appendChild(layer);
  S.prompt = document.createElement("div"); S.prompt.className = "w3d-prompt"; S.prompt.hidden = true; container.appendChild(S.prompt);
  S.cross = document.createElement("div"); S.cross.className = "w3d-crosshair"; S.cross.hidden = true; container.appendChild(S.cross);
  S.hint = document.createElement("div"); S.hint.className = "w3d-hint"; S.hint.hidden = true;
  S.hint.innerHTML = `<b>Click</b> to look around · <b>WASD</b> move · <b>Shift</b> run · <b>Space</b> hop · <b>V</b> first person · <b>Esc</b> release`;
  container.appendChild(S.hint);

  bindInput();
  const ro = new ResizeObserver(resize); ro.observe(container); resize();
  document.addEventListener("pointerlockchange", () => {
    S.locked = document.pointerLockElement === S.renderer.domElement; updateHud();
  });
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
  S.adaLight = new THREE.PointLight(0x8fb0ff, 3, 6, 1.6); S.scene.add(S.adaLight);
  let n;
  S.pool = [];
  n = S.quality === "high" ? 4 : 2;
  for (let i = 0; i < n; i++) { const l = new THREE.PointLight(0xffa04a, 0, 9, 1.5); S.scene.add(l); S.pool.push(l); }
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
function kindCell(kind) {
  const k = S.kinds[kind] || {};
  return glyphCell(kind, k.glyph || "❔", k.color);
}
function glyphOf(g, letter = "") { return glyphCell("g:" + g, g, null, letter || "?"); }
// the glyph an entity shows: its own (garden plants send their growth stage), else its kind's
function entCell(e) {
  if (e.glyph) return glyphCell("g:" + e.glyph, e.glyph, S.kinds[e.kind]?.color, e.kind);
  if (e.kind === "plant") {
    const st = Number(e.stage ?? 0), crop = S.kinds[e.crop];
    const g = st < 1.5 ? "🌱" : st < 3.5 || !crop?.glyph ? "🌿" : crop.glyph;
    return glyphCell("g:" + g, g, "#55a630", "plant");
  }
  return kindCell(e.kind);
}

// ───────────────────────────────────────────────────────────── world queries
function inMap(x, y) { const w = S.world; return w && x >= 0 && y >= 0 && x < w.W && y < w.H; }
function tileAt(x, y) { return inMap(x, y) ? S.world.T[y][x] : -1; }
function levelAt(x, y) { return inMap(x, y) ? (S.world.L[y][x] || 0) : 0; }
function topY(x, y) { const k = tileAt(x, y); if (k < 0) return BASE_Y; if (WATERISH.has(k)) return BED_Y; return levelAt(x, y) * LH; }
function deckY(x, y) { return Math.max(0, levelAt(x, y) * LH) + 0.07; }
function standY(x, y) {
  const k = tileAt(x, y); if (k === 11 || k === 16 || k === 20) return deckY(x, y); if (k === 1) return WATER_Y; if (k < 0) return 0;
  return levelAt(x, y) * LH;
}
function standYAt(wx, wz) { return standY(Math.floor(wx), Math.floor(wz)); }
function regionAt(x, y) { const w = S.world; if (!w?.R || !inMap(x, y)) return ""; const i = w.R[y]?.[x]; return w.RN[i] || ""; }
function blocked(x, y) { const k = tileAt(x, y); return k < 0 || BLOCKING.has(k); }
function isFruitTree(kind) { return /tree$/.test(kind || "") && !!S.kinds[kind]?.fruit; }
function buildingAt(x, y) { const w = S.world; return w && inMap(x, y) ? w.B[y * w.W + x] : -1; }
function roomAt(x, y) { const w = S.world; return w && inMap(x, y) ? w.RM[y * w.W + x] : null; }
// a tile on the outline of its building (the outer wall ring)
function onPerimeter(x, y) { const bi = buildingAt(x, y); if (bi < 0) return false; const b = S.world.buildings[bi]; return x === b.x0 || x === b.x1 || y === b.y0 || y === b.y1; }
function innerWall(x, y) { const k = tileAt(x, y); return (k === 8 || k === 9) && buildingAt(x, y) >= 0 && !onPerimeter(x, y); }

// ───────────────────────────────────────────────────────────── full snapshot → static world
function full(snap) {
  if (!S.inited || !snap) return;
  const W = snap.W, H = snap.H;
  if (snap.kinds) S.kinds = Object.assign({}, S.kinds, snap.kinds);
  const sig = W + "x" + H + "|" + (snap.terrain || []).map((r) => r.join("")).join("") + "|" +
    (snap.height || []).map((r) => r.join("")).join("") + "|" + JSON.stringify(snap.buildings || []);
  if (snap.season) S.live.season = snap.season;
  if (sig !== S.sig) {
    S.sig = sig;
    const B = new Int16Array(W * H).fill(-1);
    (snap.buildings || []).forEach((b, i) => { for (let y = b.y0; y <= b.y1; y++) for (let x = b.x0; x <= b.x1; x++) if (x >= 0 && y >= 0 && x < W && y < H) B[y * W + x] = i; });
    const RM = new Array(W * H).fill(null);
    (snap.buildings || []).forEach((b) => (b.rooms || []).forEach((rm) => {
      for (let y = rm.y0; y <= rm.y1; y++) for (let x = rm.x0; x <= rm.x1; x++) if (x >= 0 && y >= 0 && x < W && y < H) RM[y * W + x] = rm;
    }));
    const T = snap.terrain.map((r) => r.slice());
    for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) if (T[y][x] === 16) {
      let wet = false; for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) if (snap.terrain[y + dy]?.[x + dx] === 1) wet = true;
      if (!wet) T[y][x] = 20;
    }
    S.world = { W, H, T, L: snap.height || snap.terrain.map((r) => r.map(() => 0)), R: snap.regions, RN: snap.region_names || [],
      places: snap.places || {}, buildings: snap.buildings || [], B, RM };
    rescaleClouds();
    S.builtSeason = null;
  } else if (S.world) {
    S.world.places = snap.places || S.world.places; S.world.R = snap.regions || S.world.R; S.world.RN = snap.region_names || S.world.RN;
  }
  // entities: a full snapshot replaces the set
  const keep = new Map();
  for (const e of snap.ents || []) { const old = S.ents.get(e.id); keep.set(e.id, mergeEnt(old, e)); }
  S.ents = keep;
  for (const id of snap.removed || []) S.ents.delete(id);
  S.entsVersion = (S.entsVersion || 0) + 1;
  applyLive(snap, true);
  rebuildIfNeeded();
  syncFurniture();
  makePlaceLabels();
  if (!S.firstFull) { S.firstFull = true; snapCamera(); }
}

function rebuildIfNeeded() {
  if (!S.world) return;
  const key = S.live.season + "|" + S.quality;
  if (S.builtSeason === key) return;
  S.builtSeason = key;
  buildStatic();
  syncFurniture();
}

function buildStatic() {
  const t0 = performance.now();
  if (S.staticGroup) {
    S.scene.remove(S.staticGroup);
    S.staticGroup.traverse((o) => { if (o.geometry) o.geometry.dispose(); if (o.material && o.material !== S.waterMat && o.material !== S.flyMat) o.material.dispose(); });
  }
  const G = S.staticGroup = new THREE.Group(); S.scene.add(G);
  S.roofs = []; S.windowGlows = []; S.doorLamps = [];
  const season = SEASON[S.live.season] || SEASON.spring;
  buildTerrain(G, season);
  buildWater(G);
  buildVegetation(G, season);
  buildStructures(G);
  buildFireflies(G);
  S.furnSig = null;
  S.buildMs = performance.now() - t0;
}

// terrain: one merged mesh with bevelled terrace edges, corner AO and a diorama skirt
function tileColor(x, y, k, season) {
  const w = S.world, h1 = hash2(x, y, 1), mac = vnoise(x * 0.09, y * 0.09, 3);
  const grass = season.grass.clone().lerp(season.grass2, smooth(0.35, 0.75, mac));
  let c;
  switch (k) {
    case 1: case 11: case 16: c = COL.bed; break;
    case 2: c = COL.sand; break;
    case 3: c = shade(grass, 0.78); break;
    case 4: c = shade(grass, 0.92); break;
    case 5: c = shade(grass, 1.06); break;
    case 6: c = COL.path.clone().lerp(grass, 0.08 * mac); break;
    case 7: case 8: case 9: {
      const b = w.buildings[buildingAt(x, y)], rm = roomAt(x, y);
      c = rm?.floor ? C(rm.floor) : b?.floor ? C(b.floor) : C("#a0754d");
      if (k === 9 && b && !onPerimeter(x, y)) c = shade(C(b.floor || "#a0754d"), 0.8);   // threshold board
      break;
    }
    case 10: c = COL.soil; break;
    case 12: c = COL.plaza; break;
    case 13: c = COL.rock.clone().lerp(COL.rockDark, hash2(x, y, 5) * 0.5); break;
    case 14: c = COL.snow; break;
    case 15: c = shade(grass, 0.97); break;
    case 17: c = shade(grass, 0.86); break;
    case 18: c = COL.pineFloor.clone().lerp(grass, 0.3); break;
    case 19: c = COL.cave; break;
    case 20: c = COL.path; break;
    default: c = grass;
  }
  if (S.live.season === "winter" && (k === 0 || k === 5 || k === 15 || k === 17 || k === 3 || k === 18)) c = c.clone().lerp(COL.snow, 0.15);
  return vary(c, h1, k === 7 || k === 12 ? 0.03 : k === 0 || k === 5 || k === 15 || k === 17 ? 0.035 : 0.06);
}
function sideColor(k) {
  if (k === 2) return COL.sandSide;
  if (k === 13 || k === 14 || k === 4 || k === 19) return COL.rock;
  if (k === 7 || k === 8 || k === 9 || k === 12) return COL.stone;
  return COL.earth;
}
function buildTerrain(G, season) {
  const w = S.world, bd = new Builder(), W = w.W, H = w.H;
  const occTop = (x, y) => { const k = tileAt(x, y); let t = topY(x, y); if (k === 8 && buildingAt(x, y) < 0) t += 1.0; return t; };
  const DIRS = [[0, -1, "n"], [1, 0, "e"], [0, 1, "s"], [-1, 0, "w"]];
  const v = (x, y, z) => [x, y, z];
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    const k = w.T[y][x], top = topY(x, y), tc = tileColor(x, y, k, season);
    const drop = {}, nb = {};
    for (const [dx, dy, n] of DIRS) { const nt = inMap(x + dx, y + dy) ? topY(x + dx, y + dy) : BASE_Y; nb[n] = nt; drop[n] = top - nt; }
    const bev = (n) => (drop[n] > 0.25 && !WATERISH.has(k) ? 0.07 : 0);
    const x0 = x + bev("w"), x1 = x + 1 - bev("e"), z0 = y + bev("n"), z1 = y + 1 - bev("s");
    // corner AO from higher neighbours
    const ao = (cx, cy, sx, sy) => {
      let o = 0; const t = top + 0.15;
      if (occTop(x + sx, y) > t) o++; if (occTop(x, y + sy) > t) o++; if (occTop(x + sx, y + sy) > t) o += 0.6;
      return shade(tc, 1 - Math.min(o, 2) * 0.17);
    };
    const cNW = ao(0, 0, -1, -1), cNE = ao(1, 0, 1, -1), cSE = ao(1, 1, 1, 1), cSW = ao(0, 1, -1, 1);
    const up = [0, 1, 0];
    if (k === 12) { // plaza: 2x2 paving stones
      const mx = (x0 + x1) / 2, mz = (z0 + z1) / 2;
      const parts = [[x0, z0, mx, mz], [mx, z0, x1, mz], [x0, mz, mx, z1], [mx, mz, x1, z1]];
      parts.forEach(([a, b, c, d], i) => {
        const cc = vary(tc, hash2(x * 2 + (i & 1), y * 2 + (i >> 1), 9), 0.07);
        const g = 0.02;
        bd.quad(v(a + g, top, b + g), v(c - g, top, b + g), v(c - g, top, d - g), v(a + g, top, d - g), up, cc);
      });
      const grout = shade(tc, 0.72);
      bd.quad(v(x0, top - 0.01, z0), v(x1, top - 0.01, z0), v(x1, top - 0.01, z1), v(x0, top - 0.01, z1), up, grout);
    } else if (k === 7 && TILED_ROOM.test(roomAt(x, y)?.name || "")) { // kitchen / washroom tiles: 2x2 glazed squares
      const mx = (x0 + x1) / 2, mz = (z0 + z1) / 2, g = 0.025;
      [[x0, z0, mx, mz], [mx, z0, x1, mz], [x0, mz, mx, z1], [mx, mz, x1, z1]].forEach(([a, b, c2, d], i) => {
        const chk = ((x * 2 + (i & 1)) + (y * 2 + (i >> 1))) & 1;
        const cc = vary(shade(tc, chk ? 1.06 : 0.9), hash2(x * 2 + (i & 1), y * 2 + (i >> 1), 13), 0.025);
        bd.quad(v(a + g, top + 0.004, b + g), v(c2 - g, top + 0.004, b + g), v(c2 - g, top + 0.004, d - g), v(a + g, top + 0.004, d - g), up, cc);
      });
      bd.quad(v(x0, top, z0), v(x1, top, z0), v(x1, top, z1), v(x0, top, z1), up, shade(tc, 0.7));
    } else if (k === 7) { // wooden floor planks (rooms tint them; boards run along the room's long side)
      const rm = roomAt(x, y), alongZ = rm ? (rm.y1 - rm.y0) > (rm.x1 - rm.x0) : false;
      for (let i = 0; i < 4; i++) {
        if (alongZ) {
          const a = x0 + (x1 - x0) * i / 4, b = x0 + (x1 - x0) * (i + 1) / 4;
          const cc = vary(tc, hash2(x * 4 + i, y, 11), 0.08), ce = shade(cc, 0.85);
          bd.quad(v(a + 0.01, top, z0), v(b - 0.01, top, z0), v(b - 0.01, top, z1), v(a + 0.01, top, z1), up, cc);
          bd.quad(v(a, top - 0.005, z0), v(b, top - 0.005, z0), v(b, top - 0.005, z1), v(a, top - 0.005, z1), up, ce);
          continue;
        }
        const a = z0 + (z1 - z0) * i / 4, b = z0 + (z1 - z0) * (i + 1) / 4;
        const cc = vary(tc, hash2(x, y * 4 + i, 11), 0.08), ce = shade(cc, 0.85);
        bd.quad(v(x0, top, a + 0.01), v(x1, top, a + 0.01), v(x1, top, b - 0.01), v(x0, top, b - 0.01), up, cc, cc, cc, cc);
        bd.quad(v(x0, top - 0.005, a), v(x1, top - 0.005, a), v(x1, top - 0.005, b), v(x0, top - 0.005, b), up, ce);
      }
    } else {
      bd.quad(v(x0, top, z0), v(x1, top, z0), v(x1, top, z1), v(x0, top, z1), up, cNW, cNE, cSE, cSW);
    }
    // bevel + sides
    const sc = sideColor(k);
    for (const [dx, dy, n] of DIRS) {
      if (drop[n] <= 0.001) continue;
      const b = bev(n), bot = nb[n], isEdge = !inMap(x + dx, y + dy);
      // edge endpoints (outer), in order along the side
      let A, Bp, Ai, Bi, nrm;
      if (n === "n") { A = [x, y]; Bp = [x + 1, y]; Ai = [x0, z0]; Bi = [x1, z0]; nrm = [0, 0, -1]; }
      if (n === "s") { A = [x, y + 1]; Bp = [x + 1, y + 1]; Ai = [x0, z1]; Bi = [x1, z1]; nrm = [0, 0, 1]; }
      if (n === "w") { A = [x, y]; Bp = [x, y + 1]; Ai = [x0, z0]; Bi = [x0, z1]; nrm = [-1, 0, 0]; }
      if (n === "e") { A = [x + 1, y]; Bp = [x + 1, y + 1]; Ai = [x1, z0]; Bi = [x1, z1]; nrm = [1, 0, 0]; }
      if (b > 0) {
        const bn = [nrm[0] * 0.7, 0.7, nrm[2] * 0.7], bc = shade(tc, 1.04);
        bd.quad(v(Ai[0], top, Ai[1]), v(Bi[0], top, Bi[1]), v(Bp[0], top - b, Bp[1]), v(A[0], top - b, A[1]), bn, bc);
      }
      const st = top - b, sb = Math.max(bot, BASE_Y);
      const topC = k === 2 || k === 14 || k === 13 || WATERISH.has(k) ? sc : shade(tc.clone().lerp(sc, 0.25), 0.92);
      if (!WATERISH.has(k) && st - sb > 0.3 && k !== 13 && k !== 14) {
        // grassy lip then earth
        const lip = Math.min(0.14, (st - sb) * 0.3);
        bd.quad(v(A[0], st, A[1]), v(Bp[0], st, Bp[1]), v(Bp[0], st - lip, Bp[1]), v(A[0], st - lip, A[1]), nrm, topC, topC, shade(topC, 0.9), shade(topC, 0.9));
        const cTop = shade(sc, 0.95), cBot = isEdge ? shade(COL.earthDeep, 0.6) : shade(sc, 0.62);
        bd.quad(v(A[0], st - lip, A[1]), v(Bp[0], st - lip, Bp[1]), v(Bp[0], sb, Bp[1]), v(A[0], sb, A[1]), nrm, cTop, cTop, cBot, cBot);
      } else {
        const cTop = shade(sc, 0.95), cBot = isEdge ? shade(COL.earthDeep, 0.6) : shade(sc, 0.6);
        bd.quad(v(A[0], st, A[1]), v(Bp[0], st, Bp[1]), v(Bp[0], sb, Bp[1]), v(A[0], sb, A[1]), nrm, cTop, cTop, cBot, cBot);
      }
    }
  }
  const mat = lambert({ vertexColors: true }, { snow: 0.85, key: "terrain" });
  const mesh = new THREE.Mesh(bd.build(), mat); mesh.receiveShadow = true; mesh.castShadow = true; mesh.userData.ownMat = true;
  mesh.name = "terrain"; G.add(mesh); S.terrainMesh = mesh;
}

function buildWater(G) {
  const w = S.world, p = [], sh = [];
  const isW = (x, y) => inMap(x, y) && WATERISH.has(w.T[y][x]);
  const shore = (cx, cy) => { // corner (cx, cy)
    let land = 0; for (const [dx, dy] of [[-1, -1], [0, -1], [-1, 0], [0, 0]]) { const x = cx + dx, y = cy + dy; if (inMap(x, y) && !isW(x, y)) land++; }
    return land / 4;
  };
  for (let y = 0; y < w.H; y++) for (let x = 0; x < w.W; x++) {
    if (!isW(x, y)) continue;
    const a = [x, y], b = [x + 1, y], c = [x + 1, y + 1], d = [x, y + 1];
    for (const q of [a, c, b, a, d, c]) { p.push(q[0], WATER_Y, q[1]); sh.push(shore(q[0], q[1])); }
  }
  if (!p.length) return;
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(p, 3));
  g.setAttribute("aShore", new THREE.Float32BufferAttribute(sh, 1));
  g.computeBoundingSphere();
  const m = new THREE.Mesh(g, S.waterMat); m.renderOrder = 2; m.name = "water"; G.add(m);
}

// vegetation and natural props
const GEO = {};
function geos() {
  const hi = S.quality === "high";
  GEO.trunk = new THREE.CylinderGeometry(0.07, 0.12, 0.8, 6).translate(0, 0.4, 0);
  GEO.blob = new THREE.IcosahedronGeometry(1, hi ? 1 : 0);
  GEO.blobLo = new THREE.IcosahedronGeometry(1, 0);
  const cones = [[0.62, 0.9, 0.62], [0.5, 0.8, 1.08], [0.36, 0.7, 1.5], [0.2, 0.5, 1.86]];
  GEO.pine = mergeGeoms((hi ? cones : cones.slice(0, 3)).map(([r, h, y], i) => new THREE.ConeGeometry(r, hi ? h : h * 1.15, hi ? 7 : 6).translate(0, hi ? y : y + i * 0.08, 0)));
  GEO.pineTrunk = new THREE.CylinderGeometry(0.06, 0.1, 0.5, 5).translate(0, 0.25, 0);
  GEO.rock = new THREE.DodecahedronGeometry(1, 0);
  GEO.bloom = new THREE.OctahedronGeometry(1, 0);
  GEO.fruit = new THREE.IcosahedronGeometry(1, 0);
  GEO.crystal = new THREE.OctahedronGeometry(1, 0).scale(0.35, 1, 0.35);
  // grass tuft: a few blades leaning outward
  const blades = [];
  for (let i = 0; i < 5; i++) {
    const a = (i / 5) * Math.PI * 2 + 0.3, lean = 0.35, h = 0.22 + (i % 3) * 0.06;
    const bg = new THREE.BufferGeometry();
    const bx = Math.cos(a) * 0.03, bz = Math.sin(a) * 0.03, px = -Math.sin(a) * 0.028, pz = Math.cos(a) * 0.028;
    bg.setAttribute("position", new THREE.Float32BufferAttribute([bx - px, 0, bz - pz, bx + px, 0, bz + pz, bx + Math.cos(a) * h * lean, h, bz + Math.sin(a) * h * lean], 3));
    bg.computeVertexNormals();
    const n = bg.attributes.normal.array; for (let j = 0; j < 9; j += 3) { n[j] *= 0.3; n[j + 1] = 1; n[j + 2] *= 0.3; }
    blades.push(bg);
  }
  GEO.tuft = mergeGeoms(blades);
}
function mergeGeoms(list) {
  const p = [], n = [];
  for (const g0 of list) { const g = g0.index ? g0.toNonIndexed() : g0; p.push(...g.attributes.position.array); n.push(...g.attributes.normal.array); }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(p, 3)); g.setAttribute("normal", new THREE.Float32BufferAttribute(n, 3));
  return g;
}
function buildVegetation(G, season) {
  geos();
  const w = S.world, hi = S.quality === "high", sname = S.live.season;
  const M = {
    trunk: lambert({}, { snow: 0.4, key: "trunk" }),
    canopy: lambert({ flatShading: true }, { snow: 1.0, wind: 2, key: "canopy" }),
    pine: lambert({ flatShading: true }, { snow: 1.3, wind: 2, key: "pine" }),
    rock: lambert({ flatShading: true }, { snow: 1.0, key: "rock" }),
    tuft: lambert({ side: THREE.DoubleSide }, { snow: 0.5, wind: 1, key: "tuft" }),
    bloom: lambert({ flatShading: true }, { wind: 2, key: "bloom" }),
    fruit: lambert({ flatShading: true }, { key: "fruit" }),
    crystal: new THREE.MeshLambertMaterial({ color: 0xffffff, emissive: 0x6fb6ff, emissiveIntensity: 0.9, flatShading: true }),
  };
  for (const m of Object.values(M)) m.userData.shared = true;
  const sc = {
    trunk: new Scatter(GEO.trunk, M.trunk), canopy: new Scatter(GEO.blob, M.canopy), canopyLo: new Scatter(GEO.blobLo, M.canopy), pine: new Scatter(GEO.pine, M.pine),
    pineTrunk: new Scatter(GEO.pineTrunk, M.trunk), rock: new Scatter(GEO.rock, M.rock),
    tuft: new Scatter(GEO.tuft, M.tuft, { cast: false }), bloom: new Scatter(GEO.bloom, M.bloom, { cast: false }),
    fruit: new Scatter(GEO.fruit, M.fruit, { cast: false }), crystal: new Scatter(GEO.crystal, M.crystal, { cast: false }),
    ridge: new Scatter(UNIT_BOX, M.trunk, { cast: false }),
  };
  const blossom = [C("#f7c6d6"), C("#fbe4ec"), C("#f0a8c2")];
  S.treeSpots = new Map();
  const fruitTrees = new Set([...S.ents.values()].filter((e) => isFruitTree(e.kind)).map((e) => e.x + "," + e.y));
  for (let y = 0; y < w.H; y++) for (let x = 0; x < w.W; x++) {
    const k = w.T[y][x], top = topY(x, y), r = rng(hashStr(x + ":" + y) ^ 0x5bd1e995), cx = x + 0.5, cz = y + 0.5;
    const reg = regionAt(x, y);
    if (k === 3) { // broadleaf tree
      const s = 0.85 + r() * 0.35, jx = cx + (r() - 0.5) * 0.25, jz = cz + (r() - 0.5) * 0.25, ry = r() * 6.28;
      const orchard = reg === "orchard" || fruitTrees.has(x + "," + y);
      S.treeSpots.set(x + "," + y, { x: jx, z: jz, y: top, s, r: (orchard ? 0.55 : 0.5) * s, cy: top + (orchard ? 0.98 : 1.0) * s });
      sc.trunk.add(jx, jz, mat4(jx, top, jz, s, s * (orchard ? 0.85 : 1), s, ry), vary(COL.trunk, r(), 0.15));
      let pal = season.leaf; if (orchard && sname === "spring") pal = blossom;
      const base = pal[Math.floor(r() * pal.length)];
      const blobs = orchard
        ? [[0, 0.98, 0, 0.55, 0.78], [0.18, 0.88, 0.12, 0.38, 0.8]]
        : [[0, 1.0, 0, 0.5, 0.88], [0.22, 0.8, 0.1, 0.36, 0.85], [-0.17, 1.26, -0.1, 0.32, 0.9]];
      const nb = hi ? blobs.length : 2;
      for (let i = 0; i < nb; i++) {
        const [ox, oy, oz, rr, sy] = blobs[i], cos = Math.cos(ry), sin = Math.sin(ry);
        const px = jx + (ox * cos - oz * sin) * s, pz = jz + (ox * sin + oz * cos) * s;
        (i === 0 ? sc.canopy : sc.canopyLo).add(px, pz, mat4(px, top + oy * s, pz, rr * s, rr * s * sy, rr * s, r() * 6), vary(base, r(), 0.1).multiplyScalar(i === 0 ? 1 : 0.92));
      }
      if (orchard && !fruitTrees.has(x + "," + y) && (sname === "summer" || sname === "autumn")) {
        for (let i = 0; i < 5; i++) {
          const a = r() * 6.28, el = 0.2 + r() * 0.9, rad = 0.5 * s;
          const px = jx + Math.cos(a) * Math.cos(el) * rad, pz = jz + Math.sin(a) * Math.cos(el) * rad;
          sc.fruit.add(px, pz, mat4(px, top + 0.98 * s + Math.sin(el) * rad * 0.6 - 0.1, pz, 0.065), C(sname === "summer" ? "#e2382f" : "#e8892a"));
        }
      }
    } else if (k === 18) { // pine
      const s = 0.85 + r() * 0.4, jx = cx + (r() - 0.5) * 0.2, jz = cz + (r() - 0.5) * 0.2, hs = s * (1 + levelAt(x, y) * 0.03);
      sc.pineTrunk.add(jx, jz, mat4(jx, top, jz, s, s, s), vary(COL.trunk, r(), 0.15));
      sc.pine.add(jx, jz, mat4(jx, top + 0.18 * s, jz, s * 0.9, hs, s * 0.9, r() * 6.28), vary(COL.pine, r(), 0.14));
    } else if (k === 4) { // boulder + pebbles
      const s = 0.36 + r() * 0.12;
      sc.rock.add(cx, cz, mat4(cx + (r() - 0.5) * 0.15, top + s * 0.35, cz + (r() - 0.5) * 0.15, s * 1.15, s * 0.8, s, r() * 6, r() * 0.4), vary(COL.rock, r(), 0.12));
      for (let i = 0; i < 2; i++) { const px = x + 0.15 + r() * 0.7, pz = y + 0.15 + r() * 0.7, ps = 0.07 + r() * 0.06;
        sc.rock.add(px, pz, mat4(px, top + ps * 0.3, pz, ps, ps * 0.7, ps, r() * 6), vary(COL.rock, r(), 0.15)); }
    } else if (k === 13) { // cliff: rugged chunks
      const n = 2 + Math.floor(r() * 2);
      for (let i = 0; i < n; i++) {
        const px = x + 0.2 + r() * 0.6, pz = y + 0.2 + r() * 0.6, s = 0.3 + r() * 0.25;
        sc.rock.add(px, pz, mat4(px, top + s * 0.25, pz, s, s * (0.8 + r() * 0.9), s, r() * 6, r() * 0.5, r() * 0.5), vary(COL.rock.clone().lerp(COL.rockDark, r() * 0.6), r(), 0.1));
      }
    } else if (k === 5) { // flowers
      const cols = ["#ffd166", "#ef476f", "#ffffff", "#c77dff", "#ff8fab", "#7bdff2"];
      const nf = sname === "winter" ? 0 : hi ? 7 : 4;
      for (let i = 0; i < nf; i++) {
        const px = x + 0.1 + r() * 0.8, pz = y + 0.1 + r() * 0.8, s = 0.045 + r() * 0.025;
        sc.bloom.add(px, pz, mat4(px, top + 0.1 + r() * 0.12, pz, s, s * 0.7, s, r() * 6), C(cols[Math.floor(r() * cols.length)]));
      }
      for (let i = 0; i < 2; i++) { const px = x + 0.2 + r() * 0.6, pz = y + 0.2 + r() * 0.6; sc.tuft.add(px, pz, mat4(px, top, pz, 0.9, 0.8, 0.9, r() * 6), vary(season.tuft, r(), 0.12)); }
    } else if (k === 17) { // tall grass / bushes
      if (r() < 0.55) { const px = x + 0.3 + r() * 0.4, pz = y + 0.3 + r() * 0.4, s = 0.24 + r() * 0.12;
        sc.canopyLo.add(px, pz, mat4(px, top + s * 0.55, pz, s * 1.2, s, s * 1.2, r() * 6), vary(shade(season.leaf[0], 0.8), r(), 0.1)); }
      const nt = hi ? 4 : 2;
      for (let i = 0; i < nt; i++) { const px = x + 0.1 + r() * 0.8, pz = y + 0.1 + r() * 0.8, s = 1.3 + r() * 0.8;
        sc.tuft.add(px, pz, mat4(px, top, pz, s, s * 1.2, s, r() * 6), vary(season.tuft, r(), 0.12)); }
    } else if (k === 10) { // tilled soil ridges + crops
      for (let i = 0; i < 3; i++) {
        const pz = y + 0.2 + i * 0.3;
        sc.ridge.add(cx, pz, mat4(cx, top + 0.035, pz, 0.96, 0.07, 0.15), vary(COL.soilRidge, r(), 0.08));
        if (season.field !== "none") for (let j = 0; j < 3; j++) {
          const px = x + 0.18 + j * 0.32 + (r() - 0.5) * 0.06;
          const [col, s] = season.field === "wheat" ? [C("#e0bb52"), 1.8] : season.field === "young" ? [C("#7cc74a"), 0.8] : [C("#a98f52"), 0.6];
          sc.tuft.add(px, pz, mat4(px, top + 0.06, pz, s * 0.7, s, s * 0.7, r() * 6), vary(col, r(), 0.1));
        }
      }
    } else if (k === 19) { // cave: a few glowing crystals
      if (r() < 0.3) { const px = x + 0.3 + r() * 0.4, pz = y + 0.3 + r() * 0.4, s = 0.15 + r() * 0.1;
        sc.crystal.add(px, pz, mat4(px, top + s * 0.5, pz, s, s, s, r() * 6, (r() - 0.5) * 0.5), C(r() < 0.5 ? "#9fd4ff" : "#c9a6ff")); }
    } else if ((k === 0 || k === 15) && hi && r() < 0.4) { // decorative grass tufts
      const n = 1 + Math.floor(r() * 2);
      for (let i = 0; i < n; i++) { const px = x + 0.1 + r() * 0.8, pz = y + 0.1 + r() * 0.8, s = 0.7 + r() * 0.6;
        sc.tuft.add(px, pz, mat4(px, top, pz, s, s, s, r() * 6), vary(season.tuft, r(), 0.14)); }
    }
  }
  for (const s of Object.values(sc)) s.build(G);
}

// buildings, walls, fences, bridges, docks
function buildingBase(b) {
  const d = b.door || b.doors?.[0];
  return Math.max(levelAt(b.x0 + 1, b.y0 + 1), d ? levelAt(d[0], d[1]) : 0) * LH;
}
function buildStructures(G) {
  const w = S.world, bd = new Builder();
  S.wallMat = lambert({ vertexColors: true }, { snow: 0.5, key: "walls", cut: true });
  S.glassMats = []; S.bInfo = [];
  w.buildings.forEach((b, bi) => {
    const wb = new Builder(true), gb = new Builder(true);
    const base = buildingBase(b), top = base + WALL_H;
    S.bInfo[bi] = { base, top, b };
    if (b.glass) buildGreenhouse(G, wb, b, bi, base, top);
    else buildHouseWalls(G, wb, gb, b, bi, base, top);
    if (wb.count) {
      const m = new THREE.Mesh(wb.build(), S.wallMat); m.castShadow = m.receiveShadow = true; m.name = "walls:" + (b.name || bi); G.add(m);
    }
    if (gb.count) {
      const gm = lambert({ vertexColors: true, emissive: 0xffa040, emissiveIntensity: 0, color: 0x5b6f7f }, { key: "glass", cut: true });
      S.glassMats[bi] = gm;
      const m = new THREE.Mesh(gb.build(), gm); m.name = "glass:" + (b.name || bi); G.add(m);
    }
  });
  // stray wall tiles (garden walls), fences, bridges, docks
  const isFence = (x, y) => tileAt(x, y) === 15;
  for (let y = 0; y < w.H; y++) for (let x = 0; x < w.W; x++) {
    const k = w.T[y][x], top = topY(x, y), cx = x + 0.5, cz = y + 0.5, r = rng(hashStr("s" + x + ":" + y));
    if (k === 8 && buildingAt(x, y) < 0) {
      bd.box(cx, top + 0.45, cz, 0.96, 0.9, 0.96, vary(COL.stone, r(), 0.08));
      bd.box(cx, top + 0.94, cz, 1.0, 0.1, 1.0, shade(COL.stone, 0.8));
    } else if (k === 15) {
      const wc = vary(COL.wood, r(), 0.1);
      bd.box(cx, top + 0.3, cz, 0.1, 0.6, 0.1, shade(wc, 0.85));
      bd.box(cx, top + 0.62, cz, 0.13, 0.04, 0.13, shade(wc, 0.7));
      const e = isFence(x + 1, y), s = isFence(x, y + 1), wst = isFence(x - 1, y), nn = isFence(x, y - 1);
      if (e) for (const h of [0.24, 0.46]) bd.box(x + 1, top + h, cz, 1, 0.06, 0.045, wc);
      if (s) for (const h of [0.24, 0.46]) bd.box(cx, top + h, y + 1, 0.045, 0.06, 1, wc);
      if (!e && !s && !wst && !nn) for (const h of [0.24, 0.46]) bd.box(cx, top + h, cz, 0.8, 0.06, 0.045, wc);
    } else if (k === 20) { // a porch deck on dry ground: boards on low joists, a skirting board on open edges
      const dy = deckY(x, y) + 0.06;
      for (let i = 0; i < 6; i++) bd.box(x + (i + 0.5) / 6, dy - 0.04, cz, 1 / 6 - 0.02, 0.07, 1.0, vary(COL.plank, r(), 0.12), (r() - 0.5) * 0.03);
      for (const [ddx, ddy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
        const nk = tileAt(x + ddx, y + ddy); if (nk === 20 || nk === 8 || nk === 9) continue;
        if (ddx) bd.box(x + (ddx > 0 ? 0.97 : 0.03), dy - 0.12, cz, 0.06, 0.2, 1, COL.darkWood); else bd.box(cx, dy - 0.12, y + (ddy > 0 ? 0.97 : 0.03), 1, 0.2, 0.06, COL.darkWood);
      }
    } else if (k === 11 || k === 16) {
      const dy = deckY(x, y), runX = k === 11 ? (WATERISH.has(tileAt(x, y - 1)) || WATERISH.has(tileAt(x, y + 1)) || tileAt(x, y - 1) < 0)
        && !(tileAt(x - 1, y) === 1 && tileAt(x + 1, y) === 1) : true;
      const n = 6;
      for (let i = 0; i < n; i++) {
        const pc = vary(k === 11 ? COL.plank : shade(COL.plank, 0.92), r(), 0.12), a = (i + 0.5) / n;
        if (runX) bd.box(x + a, dy - 0.04, cz, 1 / n - 0.02, 0.07, 1.0, pc, (r() - 0.5) * 0.04);
        else bd.box(cx, dy - 0.04, y + a, 1.0, 0.07, 1 / n - 0.02, pc, (r() - 0.5) * 0.04);
      }
      // beams + posts into the water
      const beamC = shade(COL.darkWood, 0.9);
      if (runX) { bd.box(cx, dy - 0.12, y + 0.12, 1, 0.1, 0.1, beamC); bd.box(cx, dy - 0.12, y + 0.88, 1, 0.1, 0.1, beamC); }
      else { bd.box(x + 0.12, dy - 0.12, cz, 0.1, 0.1, 1, beamC); bd.box(x + 0.88, dy - 0.12, cz, 0.1, 0.1, 1, beamC); }
      const postH = dy - BED_Y;
      if ((x + y) % 2 === 0 || k === 16) for (const [px, pz] of runX ? [[cx, y + 0.1], [cx, y + 0.9]] : [[x + 0.1, cz], [x + 0.9, cz]]) {
        bd.box(px, BED_Y + postH / 2 + (k === 16 ? 0.12 : 0), pz, 0.12, postH + (k === 16 ? 0.24 : 0), 0.12, COL.darkWood);
      }
      if (k === 11) { // railings on the water sides
        const railC = shade(COL.wood, 0.9);
        if (runX) for (const z of [y + 0.06, y + 0.94]) { bd.box(cx, dy + 0.42, z, 1, 0.06, 0.06, railC); bd.box(x + 0.5, dy + 0.21, z, 0.07, 0.42, 0.07, shade(railC, 0.85)); }
        else for (const xx of [x + 0.06, x + 0.94]) { bd.box(xx, dy + 0.42, cz, 0.06, 0.06, 1, railC); bd.box(xx, dy + 0.21, y + 0.5, 0.07, 0.42, 0.07, shade(railC, 0.85)); }
      }
    }
  }
  if (bd.count) {
    const m = new THREE.Mesh(bd.build(), lambert({ vertexColors: true }, { snow: 0.5, key: "bld" }));
    m.castShadow = m.receiveShadow = true; m.userData.ownMat = true; m.name = "structures"; G.add(m);
  }
}

// a building with timber-framed walls: exterior walls with every door in b.doors, windows, inner plaster,
// interior partition walls (WALL tiles inside the outline) and interior doorways (DOOR tiles inside)
function buildHouseWalls(G, wb, gb, b, bi, base, top) {
  const wallC = C(b.wall || "#c9a27e"), roofC = C(b.roof || "#9c4a3a");
  const innerC = b.inner ? C(b.inner) : wallC.clone().lerp(C("#ffffff"), 0.35);
  const T = 0.45, doors = (b.doors && b.doors.length ? b.doors : b.door ? [b.door] : []);
  const sides = [
    { n: "n", fixed: b.y0, a0: b.x0, a1: b.x1, axis: "x", out: -1 },
    { n: "s", fixed: b.y1, a0: b.x0, a1: b.x1, axis: "x", out: 1 },
    { n: "w", fixed: b.x0, a0: b.y0, a1: b.y1, axis: "z", out: -1 },
    { n: "e", fixed: b.x1, a0: b.y0, a1: b.y1, axis: "z", out: 1 },
  ];
  const wallShade = (px, py) => 0.82 + 0.18 * smooth(base, base + 0.9, py);
  const innerShade = (px, py) => 0.86 + 0.14 * smooth(base, base + 1.2, py);
  for (const sd of sides) {
    const onSide = doors.filter(([dx, dy]) => sd.axis === "x" ? dy === sd.fixed && dx >= sd.a0 && dx <= sd.a1 : dx === sd.fixed && dy >= sd.a0 && dy <= sd.a1)
      .map(([dx, dy]) => (sd.axis === "x" ? dx : dy)).sort((p, q) => p - q);
    const segs = []; let st = sd.a0;
    for (const d of onSide) { segs.push([st, d]); st = d + 1; }
    segs.push([st, sd.a1 + 1]);
    const outerC = sd.out < 0 ? sd.fixed : sd.fixed + 1;          // outer face coordinate
    const mid = outerC - sd.out * T / 2;                        // slab centre across thickness
    const innerF = outerC - sd.out * T;                         // inner face coordinate
    // boxes are cut into one-tile pieces so the cut-away lowers whole pieces, never a slanted run
    const put = (a, b2, y0, y1, c, thick = T, outset = 0, fn, at = mid + sd.out * outset / 2) => {
      for (let s0 = a; s0 < b2 - 0.001; s0 = Math.min(b2, Math.floor(s0 + 1e-6) + 1)) {
        const s1 = Math.min(b2, Math.floor(s0 + 1e-6) + 1), along = (s0 + s1) / 2, len = s1 - s0, cy = (y0 + y1) / 2, h = y1 - y0;
        if (len <= 0.001) continue;
        if (sd.axis === "x") wb.box(along, cy, at, len, h, thick + outset, c, 0, fn);
        else wb.box(at, cy, along, thick + outset, h, len, c, 0, fn);
      }
    };
    for (const [a, b2] of segs) {
      put(a, b2, base, base + 0.3, COL.stone, T, 0.06);
      put(a, b2, base + 0.3, top - 0.14, wallC, T, 0, wallShade);
      put(a, b2, top - 0.14, top, COL.timber, T, 0.05);
      // inner plaster skin + skirting board
      put(Math.max(a, sd.a0 + 0.45), Math.min(b2, sd.a1 + 0.55), base + 0.14, top - 0.14, innerC, 0.02, 0, innerShade, innerF - sd.out * 0.01);
      put(Math.max(a, sd.a0 + 0.45), Math.min(b2, sd.a1 + 0.55), base, base + 0.14, COL.darkWood, 0.04, 0, null, innerF - sd.out * 0.02);
    }
    for (const doorOn of onSide) {
      put(doorOn, doorOn + 1, base + 1.2, top - 0.14, wallC);
      put(doorOn, doorOn + 1, base + 1.3, top - 0.14, innerC, 0.02, 0, null, innerF - sd.out * 0.01);
      put(doorOn, doorOn + 1, top - 0.14, top, COL.timber, T, 0.05);
      put(doorOn - 0.06, doorOn + 0.06, base, base + 1.2, COL.timber, T, 0.08);
      put(doorOn + 0.94, doorOn + 1.06, base, base + 1.2, COL.timber, T, 0.08);
      put(doorOn, doorOn + 1, base + 1.14, base + 1.24, COL.timber, T, 0.1);
      // open door leaf, swung inward
      const lx = sd.axis === "x" ? doorOn + 0.08 : outerC - sd.out * (T + 0.4), lz = sd.axis === "x" ? outerC - sd.out * (T + 0.4) : doorOn + 0.08;
      if (sd.axis === "x") wb.box(lx, base + 0.58, lz, 0.06, 1.12, 0.78, C("#7a4e2e")); else wb.box(lx, base + 0.58, lz, 0.78, 1.12, 0.06, C("#7a4e2e"));
      // step + lantern by the door
      const sx = sd.axis === "x" ? doorOn + 0.5 : outerC + sd.out * 0.25, sz = sd.axis === "x" ? outerC + sd.out * 0.25 : doorOn + 0.5;
      wb.box(sx, base + 0.04, sz, sd.axis === "x" ? 0.9 : 0.5, 0.08, sd.axis === "x" ? 0.5 : 0.9, COL.stone);
      const lpx = sd.axis === "x" ? doorOn + 1.22 : outerC + sd.out * 0.1, lpz = sd.axis === "x" ? outerC + sd.out * 0.1 : doorOn + 1.22;
      wb.box(lpx, base + 1.15, lpz, 0.12, 0.18, 0.12, COL.timber);
      gb.box(lpx, base + 1.15, lpz, 0.09, 0.13, 0.13, C("#ffcf7a"));
      S.doorLamps.push({ p: new THREE.Vector3(lpx, base + 1.15, lpz), bi });
    }
    const nearDoor = (a) => onSide.some((d) => Math.abs(a - d) <= 1);
    // timber posts every other tile for a half-timbered look
    for (let a = sd.a0; a <= sd.a1 + 1; a += 2) {
      if (onSide.some((d) => a >= d && a <= d + 1)) continue;
      put(a - 0.07, a + 0.07, base + 0.3, top - 0.14, COL.timber, T, 0.04);
    }
    // windows (not where a partition wall meets this wall, not next to a door)
    for (let a = sd.a0 + 1; a <= sd.a1 - 1; a++) {
      if (nearDoor(a) || (a - sd.a0) % 2 !== 1) continue;
      const ix = sd.axis === "x" ? a : sd.fixed - sd.out, iy = sd.axis === "x" ? sd.fixed - sd.out : a;
      if (innerWall(ix, iy)) continue;
      const along = a + 0.5, wy = base + 1.0, f = outerC + sd.out * 0.03, fi = innerF - sd.out * 0.03;
      const shut = roofC.clone().lerp(C("#ffffff"), 0.1), pane = C("#ffd28a");
      if (sd.axis === "x") {
        wb.box(along, wy, f, 0.6, 0.66, 0.05, COL.timber); gb.box(along, wy, f + sd.out * 0.02, 0.44, 0.5, 0.04, pane); gb.box(along, wy, fi - sd.out * 0.02, 0.44, 0.5, 0.04, pane);
        wb.box(along, wy, fi - sd.out * 0.01, 0.58, 0.64, 0.03, COL.timber);
        wb.box(along - 0.4, wy, f + sd.out * 0.01, 0.16, 0.62, 0.05, shut); wb.box(along + 0.4, wy, f + sd.out * 0.01, 0.16, 0.62, 0.05, shut);
        wb.box(along, wy - 0.38, f + sd.out * 0.04, 0.7, 0.06, 0.12, COL.timber);
        wb.box(along, wy - 0.35, fi - sd.out * 0.05, 0.66, 0.04, 0.12, COL.timber);
        S.windowGlows.push({ p: new THREE.Vector3(along, wy, f + sd.out * 0.3), bi });
      } else {
        wb.box(f, wy, along, 0.05, 0.66, 0.6, COL.timber); gb.box(f + sd.out * 0.02, wy, along, 0.04, 0.5, 0.44, pane); gb.box(fi - sd.out * 0.02, wy, along, 0.04, 0.5, 0.44, pane);
        wb.box(fi - sd.out * 0.01, wy, along, 0.03, 0.64, 0.58, COL.timber);
        wb.box(f + sd.out * 0.01, wy, along - 0.4, 0.05, 0.62, 0.16, shut); wb.box(f + sd.out * 0.01, wy, along + 0.4, 0.05, 0.62, 0.16, shut);
        wb.box(f + sd.out * 0.04, wy - 0.38, along, 0.12, 0.06, 0.7, COL.timber);
        wb.box(fi - sd.out * 0.05, wy - 0.35, along, 0.12, 0.04, 0.66, COL.timber);
        S.windowGlows.push({ p: new THREE.Vector3(f + sd.out * 0.3, wy, along), bi });
      }
    }
  }
  // corner posts
  for (const [cx, cz] of [[b.x0, b.y0], [b.x1 + 1, b.y0], [b.x0, b.y1 + 1], [b.x1 + 1, b.y1 + 1]]) {
    const ix = cx === b.x0 ? cx + 0.08 : cx - 0.08, iz = cz === b.y0 ? cz + 0.08 : cz - 0.08;
    wb.box(ix, base + WALL_H / 2, iz, 0.2, WALL_H, 0.2, COL.timber);
  }
  // interior partitions and doorways
  const Tw = 0.24, capC = COL.timber, skirtC = COL.darkWood;
  const isWallish = (x, y) => { const k = tileAt(x, y); return (k === 8 || k === 9) && buildingAt(x, y) === bi; };
  const partBox = (x0, z0, x1, z1) => { // one partition piece covering [x0,x1]×[z0,z1]
    const cx = (x0 + x1) / 2, cz = (z0 + z1) / 2, sx = x1 - x0, sz = z1 - z0;
    wb.box(cx, base + 0.07, cz, sx + 0.04, 0.14, sz + 0.04, skirtC);
    wb.box(cx, (base + 0.14 + top - 0.1) / 2, cz, sx, top - 0.1 - base - 0.14, sz, innerC, 0, innerShade);
    wb.box(cx, top - 0.05, cz, sx + 0.05, 0.1, sz + 0.05, capC);
  };
  const h = Tw / 2;
  for (let y = b.y0 + 1; y < b.y1; y++) for (let x = b.x0 + 1; x < b.x1; x++) {
    const k = tileAt(x, y), cx = x + 0.5, cz = y + 0.5;
    if (k === 8) {
      // the centre piece, plus an arm toward each connected neighbour (to its tile edge, or into the outer wall)
      let ax0 = cx - h, ax1 = cx + h, az0 = cz - h, az1 = cz + h;
      const reach = (dx, dy) => {
        const nx = x + dx, ny = y + dy; if (!isWallish(nx, ny)) return h;
        return onPerimeter(nx, ny) ? 0.5 + 0.55 + 0.03 : 0.5;
      };
      partBox(cx - reach(-1, 0), cz - h, cx + reach(1, 0), cz + h);
      if (reach(0, -1) > h || reach(0, 1) > h) {
        if (reach(0, -1) > h) partBox(cx - h, cz - reach(0, -1), cx + h, cz - h);
        if (reach(0, 1) > h) partBox(cx - h, cz + h, cx + h, cz + reach(0, 1));
      }
    } else if (k === 9) {
      // interior doorway: the wall runs along x if there is wall to the west or east
      const alongX = isWallish(x - 1, y) || isWallish(x + 1, y);
      const jamb = (a) => alongX ? wb.box(a, base + 0.62, cz, 0.1, 1.24, Tw + 0.08, capC) : wb.box(cx, base + 0.62, a, Tw + 0.08, 1.24, 0.1, capC);
      jamb((alongX ? x : y) + 0.05); jamb((alongX ? x : y) + 0.95);
      const hh = top - 0.1 - base - 1.34;
      if (alongX) {
        wb.box(cx, base + 1.29, cz, 1.0, 0.1, Tw + 0.1, capC);
        wb.box(cx, base + 1.34 + hh / 2, cz, 1.0, hh, Tw, innerC, 0, innerShade);
        wb.box(cx, top - 0.05, cz, 1.05, 0.1, Tw + 0.05, capC);
        wb.box(cx, base + 0.01, cz, 0.9, 0.02, Tw + 0.1, shade(skirtC, 1.2));
      } else {
        wb.box(cx, base + 1.29, cz, Tw + 0.1, 0.1, 1.0, capC);
        wb.box(cx, base + 1.34 + hh / 2, cz, Tw, hh, 1.0, innerC, 0, innerShade);
        wb.box(cx, top - 0.05, cz, Tw + 0.05, 0.1, 1.05, capC);
        wb.box(cx, base + 0.01, cz, Tw + 0.1, 0.02, 0.9, shade(skirtC, 1.2));
      }
    }
  }
  S.roofs.push(buildRoof(G, b, bi, top, wallC, roofC));
}

// a glass house: low stone curb, slim white frame, translucent panes and a glass gable roof
function buildGreenhouse(G, wb, b, bi, base, top) {
  const frameC = C(b.wall || "#eef6f2"), curbC = COL.stone, doors = (b.doors && b.doors.length ? b.doors : b.door ? [b.door] : []);
  const pb = new Builder(), x0 = b.x0 + 0.1, x1 = b.x1 + 0.9, z0 = b.y0 + 0.1, z1 = b.y1 + 0.9, curb = base + 0.32, eave = top - 0.15;
  const isDoor = (x, y) => doors.some(([dx, dy]) => dx === x && dy === y);
  const F = 0.07, white = C("#ffffff");
  const sides = [
    { fixed: z0, a0: b.x0, a1: b.x1, axis: "x", row: b.y0, n: [0, 0, -1] }, { fixed: z1, a0: b.x0, a1: b.x1, axis: "x", row: b.y1, n: [0, 0, 1] },
    { fixed: x0, a0: b.y0, a1: b.y1, axis: "z", row: b.x0, n: [-1, 0, 0] }, { fixed: x1, a0: b.y0, a1: b.y1, axis: "z", row: b.x1, n: [1, 0, 0] },
  ];
  const lo = (sd) => (sd.axis === "x" ? x0 : z0), hi = (sd) => (sd.axis === "x" ? x1 : z1);
  for (const sd of sides) {
    const box = (a, c0, y0, y1, thick, col) => { const along = (a + c0) / 2, len = c0 - a;
      if (sd.axis === "x") wb.box(along, (y0 + y1) / 2, sd.fixed, len, y1 - y0, thick, col); else wb.box(sd.fixed, (y0 + y1) / 2, along, thick, y1 - y0, len, col); };
    const pane = (s0, s1, y0, y1) => { if (sd.axis === "x") pb.quad([s0, y0, sd.fixed], [s1, y0, sd.fixed], [s1, y1, sd.fixed], [s0, y1, sd.fixed], sd.n, white);
      else pb.quad([sd.fixed, y0, s0], [sd.fixed, y0, s1], [sd.fixed, y1, s1], [sd.fixed, y1, s0], sd.n, white); };
    for (let a = sd.a0; a <= sd.a1; a++) {
      const tx = sd.axis === "x" ? a : sd.row, ty = sd.axis === "x" ? sd.row : a;
      const s0 = Math.max(a, lo(sd)), s1 = Math.min(a + 1, hi(sd));
      if (isDoor(tx, ty)) {
        box(s0, s1, base + 1.3, base + 1.38, F + 0.02, frameC);
        pane(s0, s1, base + 1.38, eave);
        continue;
      }
      box(s0, s1, base, curb, 0.22, vary(curbC, hash2(a, sd.row, 3), 0.06));
      box(s0, s1, curb, curb + 0.05, 0.26, shade(curbC, 0.8));
      box(s0, s1, base + 1.05, base + 1.1, F, frameC);
      pane(s0, s1, curb + 0.05, eave);
    }
    for (let a = sd.a0; a <= sd.a1 + 1; a++) { const p = clamp(a, lo(sd), hi(sd)); box(p - F / 2, p + F / 2, base, eave, F, frameC); }
    box(lo(sd), hi(sd), eave - 0.06, eave + 0.04, F + 0.04, frameC);
  }
  // roof: ridge along the long side
  const w = x1 - x0, d = z1 - z0, alongX = w >= d, span = alongX ? d : w, L = alongX ? w : d, rise = span * 0.3;
  const cxm = (x0 + x1) / 2, czm = (z0 + z1) / 2;
  const P = (u, v, y) => (alongX ? [cxm + u, y, czm + v] : [cxm + v, y, czm + u]);   // u along the ridge, v across
  const ov = 0.1, half = span / 2 + ov, ry = eave + 0.04 + rise * (half / (span / 2));
  for (const sg of [1, -1]) {
    const nrm = alongX ? [0, half, sg * rise] : [sg * rise, half, 0], nl = Math.hypot(...nrm), n = nrm.map((v) => v / nl);
    pb.quad(P(-L / 2 - ov, sg * half, eave - 0.03), P(L / 2 + ov, sg * half, eave - 0.03), P(L / 2 + ov, 0, ry), P(-L / 2 - ov, 0, ry), n, white);
    const ribs = Math.round(L);
    for (let i = 0; i <= ribs; i++) {
      const u = -L / 2 + (L * i) / ribs, a = new THREE.Vector3(...P(u, sg * half, eave)), c = new THREE.Vector3(...P(u, 0, ry + 0.02));
      const mm = a.clone().add(c).multiplyScalar(0.5), len = a.distanceTo(c);
      const m = new THREE.Matrix4().lookAt(a, c, new THREE.Vector3(0, 1, 0)).multiply(new THREE.Matrix4().makeScale(F, F, len)).setPosition(mm);
      wb.anc = [mm.x, mm.z, eave]; wb.lockAnc = true; wb.geom(UNIT_BOX, m, frameC); wb.lockAnc = false;
    }
    const e = P(0, sg * half, eave - 0.02); wb.box(e[0], e[1], e[2], alongX ? L + 0.2 : 0.1, 0.06, alongX ? 0.1 : L + 0.2, frameC);
  }
  const rp = P(0, 0, ry + 0.03); wb.box(rp[0], rp[1], rp[2], alongX ? L + 0.2 : 0.12, 0.1, alongX ? 0.12 : L + 0.2, frameC);
  for (const sg of [1, -1]) {   // gable triangles
    const a = P(sg * L / 2, -span / 2, eave), c = P(sg * L / 2, span / 2, eave), t = P(sg * L / 2, 0, ry - 0.02);
    pb.tri(a, c, t, alongX ? [sg, 0, 0] : [0, 0, sg], white, white, white);
  }
  S.glassPaneMat = new THREE.MeshPhongMaterial({ color: 0xd4efe6, specular: 0x9fb4c4, shininess: 80, transparent: true, opacity: 0.26,
    depthWrite: false, side: THREE.DoubleSide, vertexColors: true });
  const m = new THREE.Mesh(pb.build(), S.glassPaneMat); m.renderOrder = 3; m.castShadow = false; m.receiveShadow = false; m.userData.keepMat = true;
  m.name = "greenhouse-glass"; G.add(m);
}

// height of a pitched roof's surface above (x, z), for chimneys
function roofTopAt(b, base, x, z) {
  const w = b.x1 - b.x0 + 1, d = b.y1 - b.y0 + 1, alongX = w >= d, half = (alongX ? d : w) / 2, k = 0.78, rise = half * k + 0.15;
  const off = alongX ? Math.abs(z - (b.y0 + d / 2)) : Math.abs(x - (b.x0 + w / 2));
  return base + WALL_H + rise - Math.min(off, half) * k;
}

function buildRoof(G, b, bi, base, wallC, roofC) {
  const bd = new Builder(), w = b.x1 - b.x0 + 1, d = b.y1 - b.y0 + 1, alongX = w >= d;
  const L = alongX ? w : d, span = alongX ? d : w, ov = 0.32, half = span / 2;
  const k = 0.78, rise = half * k + 0.15;                    // pitch
  const r = rng(hashStr(b.name || "b" + bi));
  // slopes built from overlapping board strips (local: ridge along X, slopes across Z)
  for (const side of [1, -1]) {
    const E = new THREE.Vector3(0, -ov * k, side * (half + ov)), R = new THREE.Vector3(0, rise, 0);
    const sl = E.distanceTo(R), n = Math.max(3, Math.round(sl / 0.42));
    const zAx = E.clone().sub(R).normalize(), xAx = new THREE.Vector3(side, 0, 0), yAx = new THREE.Vector3().crossVectors(zAx, xAx);
    const basis = new THREE.Matrix4().makeBasis(xAx, yAx, zAx);
    for (let i = 0; i < n; i++) {
      const t = (i + 0.5) / n, c = R.clone().lerp(E, t).addScaledVector(yAx, 0.035 + (i % 2) * 0.012);
      const m = basis.clone().scale(new THREE.Vector3(L + ov * 2 + (i % 2) * 0.04, 0.07, sl / n * 1.18)).setPosition(c);
      bd.geom(UNIT_BOX, m, vary(roofC, r(), 0.05).multiplyScalar(i % 2 ? 0.9 : 1));
    }
  }
  bd.box(0, rise + 0.07, 0, L + ov * 2 + 0.06, 0.12, 0.22, shade(roofC, 0.65));
  // gables
  for (const gx of [-L / 2 + 0.02, L / 2 - 0.02]) {
    const nrm = [Math.sign(gx), 0, 0];
    const a = [gx, 0, -half], b2 = [gx, 0, half], c = [gx, rise, 0];
    bd.tri(a, b2, c, nrm, wallC, wallC, shade(wallC, 1.05));
    bd.tri(a, b2, c, [-nrm[0], 0, 0], shade(wallC, 0.8), shade(wallC, 0.8), shade(wallC, 0.8));
    bd.box(gx + Math.sign(gx) * 0.02, rise * 0.4, 0, 0.06, 0.06, span * 0.55, COL.timber);
    bd.box(gx + Math.sign(gx) * 0.03, rise * 0.55, 0, 0.05, 0.3, 0.28, shade(COL.timber, 1.2)); // attic vent
  }
  const hasHearth = [...S.ents.values()].some((e) => e.kind === "fireplace" && buildingAt(e.x, e.y) === bi);
  if (!hasHearth && r() < 0.75) { // chimney (a building with a fireplace gets a real one, built with the furniture)
    const cx = L * (r() < 0.5 ? -0.28 : 0.28), cz = half * 0.38, ch = rise * 0.62 + 0.75;
    bd.box(cx, ch / 2 + 0.1, cz, 0.34, ch, 0.34, COL.stone);
    bd.box(cx, ch + 0.12, cz, 0.42, 0.1, 0.42, shade(COL.stone, 0.75));
  }
  const g = bd.build();
  g.applyMatrix4(new THREE.Matrix4().makeRotationY(alongX ? 0 : Math.PI / 2).setPosition(b.x0 + w / 2, base, b.y0 + d / 2));
  g.computeBoundingSphere();
  const mat = lambert({ vertexColors: true, transparent: false }, { snow: 1.2, key: "roof" });
  const m = new THREE.Mesh(g, mat); m.castShadow = m.receiveShadow = true; m.userData.ownMat = true; m.name = "roof:" + (b.name || bi);
  G.add(m);
  return { mesh: m, b, bi, fade: 1 };
}

function buildFireflies(G) {
  const w = S.world, spots = [], n = S.quality === "high" ? 260 : 90, r = rng(77);
  const cand = [];
  for (let y = 0; y < w.H; y++) for (let x = 0; x < w.W; x++) {
    const k = w.T[y][x], reg = regionAt(x, y);
    if ((k === 17 || k === 5 || (k === 0 && (reg === "meadow" || reg === "forest" || reg === "orchard"))) || (k === 0 && (tileAt(x + 1, y) === 3 || tileAt(x, y + 1) === 3))) cand.push([x, y]);
  }
  if (!cand.length) return;
  const pos = new Float32Array(n * 3), seed = new Float32Array(n * 4);
  for (let i = 0; i < n; i++) {
    const [x, y] = cand[Math.floor(r() * cand.length)];
    pos.set([x + r(), standY(x, y) + 0.3 + r() * 0.8, y + r()], i * 3); seed.set([r(), r(), r(), r()], i * 4);
  }
  const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.BufferAttribute(pos, 3)); g.setAttribute("aSeed", new THREE.BufferAttribute(seed, 4));
  g.computeBoundingSphere();
  S.flyMat = S.flyMat || new THREE.ShaderMaterial({ vertexShader: FLY_VERT, fragmentShader: FLY_FRAG, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    uniforms: { uTime: U.time, uPR: { value: 1 }, uAlpha: { value: 0 } } });
  const p = new THREE.Points(g, S.flyMat); p.frustumCulled = false; p.name = "fireflies"; G.add(p);
}


// ───────────────────────────────────────────────────────────── furniture (3D pieces for a few entity kinds)
// distance from a tile centre to the face of a wall next to it in direction (dx, dy), or null when there is none
function wallGap(x, y, dx, dy) {
  const nx = x + dx, ny = y + dy, k = tileAt(nx, ny);
  if (k !== 8) return null;
  if (buildingAt(nx, ny) < 0) return 0.52;
  return onPerimeter(nx, ny) ? 1.05 : 0.88;
}
const WALL_DIRS = [[0, -1], [0, 1], [-1, 0], [1, 0]];
function wallSide(x, y, prefer) {
  const order = prefer === "outer" ? [...WALL_DIRS].sort((a, b) => (onPerimeter(x + b[0], y + b[1]) ? 1 : 0) - (onPerimeter(x + a[0], y + a[1]) ? 1 : 0)) : WALL_DIRS;
  for (const [dx, dy] of order) { const g = wallGap(x, y, dx, dy); if (g != null) return { dx, dy, gap: g }; }
  return null;
}
function furnSig() {
  let s = S.sig.length + ":";
  for (const e of S.ents.values()) if (FURN_KINDS.has(e.kind)) s += e.id + e.kind[0] + e.x + "," + e.y + ";";
  return s;
}
function syncFurniture() {
  if (!S.world || !S.staticGroup) return;
  const sig = furnSig(); if (sig === S.furnSig) return;
  S.furnSig = sig; buildFurniture();
}
function buildFurniture() {
  if (S.furnMesh) { S.scene.remove(S.furnMesh); S.furnMesh.geometry.dispose(); S.furnMesh = null; }
  S.beds = new Map(); S.furn = new Map(); S.chimneys = [];
  S.furnMat = S.furnMat || lambert({ vertexColors: true }, { snow: 0.6, key: "furn", cut: true });
  const fb = new Builder(true);
  const NOCUT = [-1e4, -1e4, 0]; fb.lockAnc = true; fb.anc = NOCUT;   // furniture stays whole, except a chimney breast in a cut wall
  for (const e of S.ents.values()) {
    if (!FURN_KINDS.has(e.kind) || !inMap(e.x, e.y)) continue;
    const k = S.kinds[e.kind] || {}, base = standY(e.x, e.y), cx = e.x + 0.5, cz = e.y + 0.5, r = rng(hashStr("f" + e.id));
    const free = e.kind === "table" || e.kind === "rug";
    const ws = free ? null : wallSide(e.x, e.y, e.kind === "fireplace" ? "outer" : null);
    const dir = ws ? [ws.dx, ws.dy] : [0, -1], gap = ws ? ws.gap : free ? 0 : 0.35;
    const v = [-dir[0], -dir[1]], u = [Math.abs(dir[1]), Math.abs(dir[0])];   // v: out of the wall, u: along it
    let sideShift = 0;
    if (e.kind === "bed" && ws) for (const sg of [-1, 1]) {   // tuck a bed into a corner
      const g = wallGap(e.x, e.y, u[0] * sg, u[1] * sg); if (g != null) { sideShift = sg * (g - 0.5); break; }
    }
    const ox = cx + dir[0] * gap + u[0] * sideShift, oz = cz + dir[1] * gap + u[1] * sideShift;
    const P = (a, b) => [ox + u[0] * a + v[0] * b, oz + u[1] * a + v[1] * b];
    // a box given along-wall extent [a0,a1], out-of-wall extent [b0,b1] and height [y0,y1] (relative to the floor)
    const fbox = (a0, a1, b0, b1, y0, y1, col) => {
      const [px, pz] = P((a0 + a1) / 2, (b0 + b1) / 2), sa = a1 - a0, sb = b1 - b0;
      fb.box(px, base + (y0 + y1) / 2, pz, u[0] ? sa : sb, y1 - y0, u[0] ? sb : sa, col);
    };
    const wood = C(k.color && e.kind !== "bed" && e.kind !== "rug" ? k.color : "#8a5a3c");
    if (e.kind === "fireplace") {
      const st = (i) => vary(COL.stone, hash2(e.id, i, 4), 0.1);
      fbox(-0.72, -0.4, 0, 0.56, 0, 0.92, st(1)); fbox(0.4, 0.72, 0, 0.56, 0, 0.92, st(2));
      fbox(-0.72, 0.72, 0, 0.56, 0.92, 1.12, st(3));
      fbox(-0.8, 0.8, 0, 0.64, 1.12, 1.2, COL.timber);
      { const [wx, wz] = P(0, -0.2); fb.anc = [wx, wz, base + 1.2]; fbox(-0.56, 0.56, 0, 0.42, 1.2, WALL_H - 0.02, shade(COL.stone, 1.05)); fb.anc = NOCUT; }
      fbox(-0.4, 0.4, 0, 0.12, 0, 0.92, C("#1d1714"));
      fbox(-0.4, 0.4, 0, 0.5, 0, 0.04, C("#2a211c"));
      fbox(-0.82, 0.82, 0.56, 0.98, 0, 0.035, shade(COL.stone, 0.85));
      fbox(-0.24, 0.2, 0.22, 0.32, 0.04, 0.12, C("#6b4630")); fbox(-0.16, 0.26, 0.3, 0.4, 0.05, 0.13, C("#5a3a26"));
      const [fx, fz] = P(0, 0.3);
      S.furn.set(e.id, { fire: new THREE.Vector3(fx, base + 0.16, fz) });
      // a stone chimney on the outside of the wall, rising past the roof
      const bi = ws && onPerimeter(e.x + dir[0], e.y + dir[1]) ? buildingAt(e.x + dir[0], e.y + dir[1]) : -1;
      if (bi >= 0) {
        const b = S.world.buildings[bi], bb = buildingBase(b);
        const out0 = gap + 0.45 - 0.02, [qx, qz] = P(0, -out0 - 0.36);   // centre of the stack, just outside the wall
        const roofY = roofTopAt(b, bb, qx, qz), topY = Math.max(roofY + 0.9, bb + WALL_H + 1.2);
        const cb = (a0, a1, b0, b1, y0, y1, col) => fbox(a0, a1, -out0 - b1, -out0 - b0, y0 - base, y1 - base, col);
        const rows = Math.ceil((topY - base) / 0.42);
        for (let i = 0; i < rows; i++) {   // stone courses, slightly varied
          const y0 = base + i * 0.42, y1 = Math.min(topY, y0 + 0.42), wide = y1 <= bb + WALL_H + 0.2;
          const hw = wide ? 0.55 : 0.4, d = wide ? 0.7 : 0.55;
          const sc = vary(COL.stone, hash2(e.id, i, 9), 0.16).multiplyScalar(i % 2 ? 0.94 : 1.04);
          cb(-hw, hw, 0, d, y0 + 0.02, y1 - 0.02, sc);
          cb(-hw + 0.03, hw - 0.03, 0.03, d - 0.03, y0, y1, shade(COL.stone, 0.62));   // mortar joint
          if (i % 2 === 0) for (const a of [-hw + 0.2, hw - 0.25]) cb(a - 0.08, a + 0.08, -0.02, d + 0.02, y0 + 0.08, y0 + 0.3, vary(COL.stone, hash2(e.id, i, 11), 0.2));
        }
        cb(-0.48, 0.48, -0.04, 0.63, topY, topY + 0.1, shade(COL.stone, 0.75));
        cb(-0.26, 0.26, 0.08, 0.47, topY + 0.1, topY + 0.13, C("#1b1612"));
        const [sx, sz] = P(0, -out0 - 0.28);
        S.chimneys.push({ id: e.id, p: new THREE.Vector3(sx, topY + 0.2, sz) });
      }
    } else if (e.kind === "stove") {
      const iron = C("#2c2e33"), dark = C("#1c1d21");
      for (const a of [-0.3, 0.3]) for (const b of [0.1, 0.58]) fbox(a - 0.04, a + 0.04, b - 0.04, b + 0.04, 0, 0.14, dark);
      fbox(-0.38, 0.38, 0.04, 0.66, 0.12, 0.72, iron);
      fbox(-0.42, 0.42, 0.02, 0.7, 0.72, 0.78, dark);
      fbox(-0.2, 0.2, 0.66, 0.69, 0.24, 0.52, C("#4a2416"));
      fbox(-0.22, 0.22, 0.69, 0.71, 0.53, 0.56, C("#8d8f94"));
      fbox(0.16, 0.3, 0.12, 0.26, 0.78, WALL_H - 0.05, dark);
      for (const a of [-0.18, 0.18]) fbox(a - 0.13, a + 0.13, 0.3, 0.56, 0.78, 0.8, C("#3b3d43"));
      const [gx, gz] = P(0, 0.72), [tx, tz] = P(0, 0.36);
      S.furn.set(e.id, { fire: new THREE.Vector3(gx, base + 0.38, gz), top: new THREE.Vector3(tx, base + 0.8, tz) });
    } else if (e.kind === "oven") {
      const iron = C("#33363c"), dark = C("#1d1f23");
      fbox(-0.42, 0.42, 0.04, 0.68, 0, 0.9, iron);
      fbox(-0.45, 0.45, 0.02, 0.71, 0.9, 0.96, dark);
      fbox(-0.32, 0.32, 0.68, 0.7, 0.18, 0.62, dark); fbox(-0.22, 0.22, 0.7, 0.71, 0.28, 0.52, C("#3a2a22"));
      fbox(-0.26, 0.26, 0.7, 0.75, 0.66, 0.69, C("#9a9da3"));
      fbox(-0.3, 0.3, 0.68, 0.7, 0.72, 0.84, shade(iron, 1.2));
      const [gx, gz] = P(0, 0.74), [tx, tz] = P(0, 0.36);
      S.furn.set(e.id, { fire: new THREE.Vector3(gx, base + 0.4, gz), top: new THREE.Vector3(tx, base + 0.96, tz) });
    } else if (e.kind === "sink") {
      const cab = C("#d8cfbf"), stone = C("#c9c4bc");
      fbox(-0.46, 0.46, 0.04, 0.58, 0.06, 0.78, cab); fbox(-0.44, 0.44, 0.06, 0.56, 0, 0.06, shade(cab, 0.6));
      fbox(-0.42, -0.02, 0.58, 0.6, 0.12, 0.72, shade(cab, 0.92)); fbox(0.02, 0.42, 0.58, 0.6, 0.12, 0.72, shade(cab, 0.92));
      fbox(-0.5, 0.5, 0.02, 0.64, 0.78, 0.84, stone);
      fbox(-0.28, 0.28, 0.16, 0.52, 0.8, 0.845, C("#8f9aa3"));
      fbox(-0.03, 0.03, 0.06, 0.12, 0.84, 1.06, C("#b8bcc2")); fbox(-0.03, 0.03, 0.06, 0.3, 1.02, 1.07, C("#b8bcc2"));
      S.furn.set(e.id, { surf: 0.84 });
    } else if (e.kind === "pantry") {
      const paint = C("#e7dcc6"), trim = C("#b99c74");
      fbox(-0.48, 0.48, 0.04, 0.56, 0, 1.62, paint);
      fbox(-0.52, 0.52, 0.02, 0.6, 1.62, 1.7, trim);
      fbox(-0.44, -0.015, 0.56, 0.58, 0.08, 1.56, shade(paint, 1.04)); fbox(0.015, 0.44, 0.56, 0.58, 0.08, 1.56, shade(paint, 1.04));
      fbox(-0.48, 0.48, 0.56, 0.585, 0.78, 0.82, trim);
      for (const a of [-0.07, 0.07]) fbox(a - 0.02, a + 0.02, 0.58, 0.61, 0.98, 1.04, C("#6b5440"));
    } else if (e.kind === "piano") {
      const body = C(k.color || "#2b2d42"), dark = shade(body, 0.7);
      fbox(-0.62, 0.62, 0.04, 0.46, 0, 1.18, body);
      fbox(-0.64, 0.64, 0.02, 0.5, 1.18, 1.23, dark);
      fbox(-0.62, 0.62, 0.46, 0.74, 0.64, 0.72, body);
      fbox(-0.56, 0.56, 0.5, 0.72, 0.72, 0.745, C("#f4f1ea"));
      for (let i = 0; i < 14; i++) { if (i % 7 === 2 || i % 7 === 6) continue; const a = -0.52 + i * 0.077; fbox(a, a + 0.04, 0.5, 0.6, 0.745, 0.77, C("#1b1b22")); }
      fbox(-0.56, 0.56, 0.46, 0.5, 0.74, 0.96, dark);
      for (const a of [-0.56, 0.56]) fbox(a - 0.04, a + 0.04, 0.64, 0.72, 0, 0.64, dark);
      fbox(-0.2, 0.2, 0.42, 0.46, 0.9, 1.08, C("#f7f2e4"));
    } else if (e.kind === "bookshelf") {
      const wd = C(k.color || "#7f5539"), cols = ["#a33d2a", "#3c6fb0", "#e9c46a", "#2d6a4f", "#6d597a", "#e76f51", "#f1ede4", "#264653"];
      fbox(-0.52, 0.52, 0.04, 0.4, 0, 0.04, wd); fbox(-0.52, 0.52, 0.04, 0.06, 0, 1.55, shade(wd, 0.75));
      for (const a of [-0.52, 0.48]) fbox(a, a + 0.04, 0.04, 0.42, 0, 1.55, wd);
      for (const sy of [0.5, 1.02, 1.52]) fbox(-0.52, 0.52, 0.04, 0.42, sy, sy + 0.035, wd);
      for (const [y0, y1] of [[0.04, 0.5], [0.535, 1.02], [1.055, 1.52]]) {
        let a = -0.47;
        while (a < 0.42) {
          const bw = 0.04 + r() * 0.045, bh = (y1 - y0) * (0.62 + r() * 0.3);
          if (r() < 0.12) { a += 0.06; continue; }
          fbox(a, Math.min(0.47, a + bw), 0.08, 0.34 + r() * 0.04, y0, y0 + bh, vary(C(cols[Math.floor(r() * cols.length)]), r(), 0.12));
          a += bw + 0.005;
        }
      }
    } else if (e.kind === "bed") {
      const blanket = C(e.owner === "synth" ? "#7f95e0" : e.owner === "companion" ? (S.people.values().next().value?.data?.color || "#7fb3a6") : k.color || "#5390d9");
      for (const a of [-0.44, 0.44]) for (const b of [0.08, 1.7]) fbox(a - 0.04, a + 0.04, b - 0.04, b + 0.04, 0, 0.14, shade(wood, 0.7));
      fbox(-0.48, 0.48, 0.04, 1.76, 0.12, 0.28, wood);
      fbox(-0.5, 0.5, 0, 0.08, 0, 0.86, shade(wood, 0.9)); fbox(-0.52, 0.52, -0.01, 0.09, 0.86, 0.9, shade(wood, 0.75));
      fbox(-0.5, 0.5, 1.72, 1.8, 0, 0.52, shade(wood, 0.9));
      fbox(-0.45, 0.45, 0.08, 1.72, 0.28, 0.42, C("#f4efe6"));
      fbox(-0.32, 0.32, 0.12, 0.42, 0.42, 0.53, C("#fffaf2"));
      fbox(-0.49, 0.49, 0.62, 1.73, 0.24, 0.46, blanket);
      fbox(-0.49, 0.49, 0.54, 0.64, 0.4, 0.475, shade(blanket, 1.15));
      const [px, pz] = P(0, 0.3), [mx, mz] = P(0, 0.9);
      S.beds.set(e.id, { id: e.id, owner: e.owner, tx: e.x, ty: e.y, px, pz, mx, mz, hx: dir[0], hz: dir[1], top: base + 0.44 });
    } else if (e.kind === "table") {
      fbox(-0.5, 0.5, -0.4, 0.4, 0.6, 0.66, wood);
      for (const a of [-0.42, 0.42]) for (const b of [-0.32, 0.32]) fbox(a - 0.04, a + 0.04, b - 0.04, b + 0.04, 0, 0.6, shade(wood, 0.8));
      S.furn.set(e.id, { surf: 0.66 });
    } else if (e.kind === "desk") {
      fbox(-0.52, 0.52, 0.04, 0.66, 0.64, 0.7, wood);
      fbox(0.16, 0.5, 0.06, 0.64, 0.3, 0.64, shade(wood, 0.9)); fbox(0.22, 0.44, 0.64, 0.66, 0.42, 0.52, shade(wood, 0.7));
      for (const b of [0.08, 0.62]) fbox(-0.5, -0.44, b - 0.03, b + 0.03, 0, 0.64, shade(wood, 0.8));
      fbox(0.44, 0.5, 0.08, 0.62, 0, 0.3, shade(wood, 0.8));
      S.furn.set(e.id, { surf: 0.7 });
    } else if (e.kind === "bench") {
      const back = !!ws, bw = C(k.color || "#8d6a4a");
      fbox(-0.55, 0.55, 0.12, 0.5, 0.36, 0.42, bw);
      for (const a of [-0.45, 0.45]) fbox(a - 0.05, a + 0.05, 0.16, 0.46, 0, 0.36, shade(bw, 0.75));
      if (back) { fbox(-0.55, 0.55, 0.1, 0.16, 0.42, 0.82, shade(bw, 0.9)); }
      S.furn.set(e.id, { surf: 0.42 });
    } else if (e.kind === "rug") {
      const rc = C(e.color || k.color || "#9d0208"), border = C("#efe0c4");
      const big = ruggable(e.x, e.y);
      const [ha, hb] = big ? [1.0, 0.68] : [0.45, 0.35];
      fbox(-ha, ha, -0.5 - hb + 0.5, -0.5 + hb + 0.5, 0.004, 0.014, border);
      fbox(-ha + 0.08, ha - 0.08, -hb + 0.08, hb - 0.08, 0.014, 0.02, rc);
      fbox(-ha + 0.2, ha - 0.2, -hb + 0.2, hb - 0.2, 0.02, 0.024, shade(rc, 1.35));
      fbox(-ha + 0.3, ha - 0.3, -hb + 0.3, hb - 0.3, 0.024, 0.027, rc);
      for (const a of [-ha - 0.04, ha + 0.04]) for (let i = 0; i < 9; i++) { const b = -hb + 0.08 + (i / 8) * (hb * 2 - 0.16); fbox(a - 0.04, a + 0.04, b - 0.012, b + 0.012, 0.004, 0.01, border); }
    }
  }
  S.entsVersion = (S.entsVersion || 0) + 1;
  if (!fb.count) return;
  const m = new THREE.Mesh(fb.build(), S.furnMat); m.castShadow = true; m.receiveShadow = true; m.name = "furniture";
  S.scene.add(m); S.furnMesh = m;
}
// a rug only spreads over 2×1.4 tiles when the floor around it is open
function ruggable(x, y) {
  for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) { const k = tileAt(x + dx, y + dy); if (k === 8 || k < 0) return false; }
  return true;
}
// the bed a sleeping being lies in: on or next to the being's tile, its own bed first
function findBed(x, y, owner) {
  if (!S.beds) return null;
  let best = null, bd = 1e9;
  for (const b of S.beds.values()) {
    const d = Math.hypot(b.mx - (x + 0.5), b.mz - (y + 0.5));
    if (Math.max(Math.abs(b.tx - x), Math.abs(b.ty - y)) > 1 && d > 1.6) continue;
    const score = d - (owner && b.owner === owner ? 5 : 0);
    if (score < bd) { bd = score; best = b; }
  }
  return best;
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
function rescaleClouds() {
  const w = S.world; if (!w || !S.cloudClusters) return;
  const r = rng(99);
  for (const cl of S.cloudClusters) { cl.x = r() * (w.W + 100) - 50; cl.z = r() * (w.H + 70) - 35; cl.y = 24 + r() * 8; }
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

// ───────────────────────────────────────────────────────────── characters
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
function skinFor(name) { const s = ["#f1c7a5", "#e0a982", "#c68863", "#8d5a3b", "#f5d2b8", "#a8714f"]; return s[hashStr(name) % s.length]; }
function hairFor(name) { const s = ["#3b2a20", "#6b4226", "#b5793a", "#d9b56b", "#1f1b1a", "#8a8a8a", "#a33d2a"]; return s[(hashStr(name) >> 3) % s.length]; }
let FIG_MAT = null, FG = null;
function makeFigure(name, color, role = "", isPlayer = false, hat = null) {
  if (!FIG_MAT) {
    FIG_MAT = lambert({ vertexColors: true }, { key: "fig" });
    FG = { leg: new THREE.CylinderGeometry(0.05, 0.045, 0.3, 6), foot: new THREE.BoxGeometry(0.09, 0.05, 0.14), cap: new THREE.CapsuleGeometry(0.17, 0.2, 4, 10),
      torso: new THREE.CylinderGeometry(0.13, 0.21, 0.44, 10), belt: new THREE.CylinderGeometry(0.19, 0.2, 0.05, 10), arm: new THREE.CapsuleGeometry(0.042, 0.22, 3, 6),
      hand: new THREE.SphereGeometry(0.045, 8, 6), head: new THREE.SphereGeometry(0.15, 16, 12), eye: new THREE.SphereGeometry(0.022, 6, 5),
      beanie: new THREE.SphereGeometry(0.158, 14, 8, 0, Math.PI * 2, 0, Math.PI * 0.5), rim: new THREE.CylinderGeometry(0.162, 0.162, 0.05, 14),
      pom: new THREE.SphereGeometry(0.05, 8, 6), box: UNIT_BOX, torus: new THREE.TorusGeometry(0.11, 0.035, 6, 12), chef: new THREE.CylinderGeometry(0.12, 0.1, 0.14, 10),
      puff: new THREE.SphereGeometry(0.15, 10, 8), apron: new THREE.CylinderGeometry(0.155, 0.218, 0.32, 10, 1, true, -0.9, 1.8),
      brim: new THREE.CylinderGeometry(0.3, 0.3, 0.025, 14), crown: new THREE.CylinderGeometry(0.12, 0.15, 0.12, 12), band: new THREE.CylinderGeometry(0.152, 0.152, 0.03, 12),
      hair: new THREE.SphereGeometry(0.158, 14, 8, 0, Math.PI * 2, 0, Math.PI * 0.55), ring: new THREE.TorusGeometry(0.035, 0.008, 4, 10), bun: new THREE.SphereGeometry(0.07, 8, 6) };
  }
  const g = new THREE.Group(), body = C(color || "#88a"), skin = C(skinFor(name)), hair = C(hairFor(name));
  const B = new Builder();
  const add = (bd, geo, x, y, z, col, sx = 1, sy = 1, sz = 1, rx = 0) => bd.geom(geo, mat4(x, y, z, sx, sy, sz, 0, rx, 0), col);
  const fmat = lambert({ vertexColors: true }, { key: "fig" });
  const mesh = (bd) => { const m = new THREE.Mesh(bd.build(), fmat); m.castShadow = true; return m; };
  const parts = {};
  const legC = C(isPlayer ? "#3a4a6b" : "#3b3a46"), shoe = C("#3a2a20");
  parts.legs = [-1, 1].map((sd) => {
    const pivot = new THREE.Group(); pivot.position.set(sd * 0.075, 0.3, 0);
    const lb = new Builder(); add(lb, FG.leg, 0, -0.15, 0, legC); add(lb, FG.foot, 0, -0.29, 0.02, shoe);
    pivot.add(mesh(lb)); g.add(pivot); return pivot;
  });
  parts.arms = [-1, 1].map((sd) => {
    const pivot = new THREE.Group(); pivot.position.set(sd * (isPlayer ? 0.2 : 0.17), 0.66, 0);
    const ab = new Builder(); add(ab, FG.arm, 0, -0.14, 0, shade(body, 0.85)); add(ab, FG.hand, 0, -0.3, 0, skin);
    pivot.add(mesh(ab)); pivot.rotation.z = sd * 0.12; g.add(pivot); return pivot;
  });
  if (isPlayer) add(B, FG.cap, 0, 0.5, 0, body);
  else { add(B, FG.torso, 0, 0.5, 0, body); add(B, FG.belt, 0, 0.38, 0, shade(body, 0.6)); }
  add(B, FG.head, 0, 0.88, 0, skin);
  for (const sd of [-1, 1]) add(B, FG.eye, sd * 0.055, 0.9, 0.135, C("#1c1c24"));
  const rl = (role || "").toLowerCase();
  if (isPlayer) {
    add(B, FG.beanie, 0, 0.9, 0, C("#c4452d")); add(B, FG.rim, 0, 0.91, 0, C("#9e3522")); add(B, FG.pom, 0, 1.07, 0, C("#fff3e0"));
    add(B, FG.box, 0, 0.55, -0.2, C("#6d4c33"), 0.26, 0.3, 0.13); add(B, FG.box, 0, 0.68, -0.2, C("#8a6244"), 0.27, 0.08, 0.14);
    add(B, FG.torus, 0, 0.74, 0, C("#2f8f83"), 1, 1, 1, Math.PI / 2);
  } else if (rl.includes("baker") || rl.includes("cook")) {
    add(B, FG.chef, 0, 1.04, 0, C("#ffffff")); add(B, FG.puff, 0, 1.15, 0, C("#ffffff"), 1, 0.7, 1); add(B, FG.apron, 0, 0.46, 0, C("#fdf6ea"));
  } else if (hat) { // a soft sun hat in their own colour
    add(B, FG.hair, 0, 0.885, 0, hair, 1, 1, 1, -0.25);
    add(B, FG.brim, 0, 0.99, 0, C(hat), 0.72, 1, 0.72); add(B, FG.crown, 0, 1.05, 0, shade(C(hat), 1.15), 0.95, 0.85, 0.95); add(B, FG.band, 0, 1.01, 0, C("#f2e8cf"), 0.98, 1, 0.98);
  } else if (rl.includes("garden") || rl.includes("farm")) {
    add(B, FG.brim, 0, 0.99, 0, C("#e3c46b")); add(B, FG.crown, 0, 1.06, 0, C("#d9b75a")); add(B, FG.band, 0, 1.02, 0, C("#a33d2a"));
  } else {
    add(B, FG.hair, 0, 0.885, 0, hair, 1, 1, 1, -0.25);
    if (rl.includes("librar") || rl.includes("teach") || rl.includes("schol")) {
      for (const sd of [-1, 1]) add(B, FG.ring, sd * 0.055, 0.9, 0.145, C("#2a2a33"));
      add(B, FG.box, 0.2, 0.42, 0.06, C("#3c6fb0"), 0.12, 0.16, 0.04);
    } else if (rl.includes("fish")) {
      add(B, FG.brim, 0, 0.99, 0, C("#3d6b8f"), 0.75, 1, 0.75); add(B, FG.crown, 0, 1.05, 0, C("#4a7da3"), 1, 0.8, 1);
    } else if (hashStr(name) % 2) add(B, FG.bun, 0, 0.98, -0.12, hair);
  }
  g.add(mesh(B));
  S.scene.add(g);
  return { group: g, parts, mat: fmat, x: 0, z: 0, y: 0, heading: 0, walk: 0, moving: false, init: false };
}
function animateFigure(f, dt, speed, sleeping) {
  f.walk += dt * (speed > 0.05 ? 9 + speed * 1.5 : 0);
  const amp = speed > 0.05 ? Math.min(0.75, 0.3 + speed * 0.12) : 0;
  f.swing = lerp(f.swing || 0, amp, damp(10, dt));
  const s = Math.sin(f.walk) * f.swing;
  f.parts.legs[0].rotation.x = s; f.parts.legs[1].rotation.x = -s;
  f.parts.arms[0].rotation.x = -s * 0.8; f.parts.arms[1].rotation.x = s * 0.8;
  f.bob = Math.abs(Math.cos(f.walk)) * 0.04 * (f.swing / 0.75);
}

// ───────────────────────────────────────────────────────────── live state (deltas)
const RENDER_KEYS = ["jx", "jz", "phase", "hop", "px", "pz", "flip"];
function mergeEnt(old, e) {
  // a full entity record replaces the old one (so fields like `on` or `lit` can go away); a partial one is merged
  let n;
  if (old && e.kind !== undefined) { n = Object.assign({}, e); for (const k of RENDER_KEYS) if (old[k] !== undefined) n[k] = old[k]; }
  else n = Object.assign(old ? Object.assign({}, old) : {}, e);
  if (!old) { const h = hashStr(String(e.id)); n.jx = ((h & 255) / 255 - 0.5) * 0.3; n.jz = (((h >> 8) & 255) / 255 - 0.5) * 0.3; n.phase = ((h >> 16) & 255) / 40; n.hop = 0; }
  return n;
}
function delta(snap) {
  if (!S.inited || !snap) return;
  for (const e of snap.ents || []) S.ents.set(e.id, mergeEnt(S.ents.get(e.id), e));
  for (const id of snap.removed || []) S.ents.delete(id);
  if ((snap.ents && snap.ents.length) || (snap.removed && snap.removed.length)) S.entsVersion = (S.entsVersion || 0) + 1;
  applyLive(snap, false);
  rebuildIfNeeded();
  syncFurniture();
}
function applyLive(s, isFull) {
  const L = S.live;
  const wasW = L.weather;
  for (const k of ["tick", "day", "phase", "season", "weather", "time", "light", "sun", "temperature", "env"]) if (s[k] !== undefined) L[k] = s[k];
  if (L.weather !== wasW && S.rain) setRainDensity();
  if (s.ada) S.adaData = Object.assign({}, S.adaData || {}, s.ada);
  if (s.companion?.name) S.companionName = s.companion.name;
  if (!s.people && s.companion && isFull) s = Object.assign({}, s, { people: [Object.assign({ role: "companion" }, s.companion)] });
  if (s.people) {
    const seen = new Set();
    for (const p of s.people) {
      seen.add(p.name);
      let f = S.people.get(p.name);
      if (!f) { f = makeFigure(p.name, p.color, p.role, false, p.hat); S.people.set(p.name, f); }
      f.data = p;
    }
    for (const [n, f] of S.people) if (!seen.has(n)) { S.scene.remove(f.group); S.people.delete(n); removeLabel("p:" + n); }
  }
  if ("visitor" in s) {
    S.visitorData = s.visitor;
    if (s.visitor && S.mode === "visit" && S.local.init) {
      const v = s.visitor, fx = v.fx ?? v.x, fy = v.fy ?? v.y;
      if (Math.hypot(fx + 0.5 - S.local.x, fy + 0.5 - S.local.z) > 3) { S.local.x = fx + 0.5; S.local.z = fy + 0.5; S.local.vx = S.local.vz = 0; }
    }
  }
  computeEnvTargets();
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
  S.cloudMat.opacity = 0.95 - 0.55 * smooth(40, 90, S.camera.position.y);
}

// ───────────────────────────────────────────────────────────── per-frame updates
function updateClouds(dt) {
  const W = S.world?.W || 128, H = S.world?.H || 96;
  const visible = Math.round(S.cloudClusters.length * clamp(S.env.cloud, 0, 1));
  let i = 0;
  S.cloudClusters.forEach((cl, ci) => {
    cl.x += cl.sp * dt * (0.5 + S.env.wind * 0.5);
    if (cl.x > W + 60) cl.x = -60;
    const show = ci < visible;
    for (const p of cl.puffs) {
      const s = show ? p.s : 0.0001;
      tmpM.compose(tmpV.set(cl.x + p.ox, cl.y + p.oy, cl.z + p.oz), tmpQ.setFromAxisAngle(tmpV2.set(0, 1, 0), p.ry), tmpS.set(s * 1.25, s * 0.72, s));
      S.clouds.setMatrixAt(i++, tmpM);
    }
  });
  S.clouds.instanceMatrix.needsUpdate = true;
  S.clouds.castShadow = S.quality === "high" && S.env.cloud < 0.9;
}

function moveToward(o, tx, tz, dt, base = 4.4) {
  const dx = tx - o.x, dz = tz - o.z, d = Math.hypot(dx, dz);
  if (!o.init || d > 4.5) { o.x = tx; o.z = tz; o.init = true; return 0; }
  if (d < 1e-4) return 0;
  const step = Math.max(base, d * 4) * dt;
  if (step >= d) { o.x = tx; o.z = tz; } else { o.x += (dx / d) * step; o.z += (dz / d) * step; }
  o.dirX = dx / d; o.dirZ = dz / d;
  return Math.min(step, d) / Math.max(dt, 1e-4);
}
function turnTo(cur, target, k) { let d = target - cur; while (d > Math.PI) d -= Math.PI * 2; while (d < -Math.PI) d += Math.PI * 2; return cur + d * k; }
function faceAngle(facing) { const f = FACING[facing] || FACING.south; return Math.atan2(f[0], f[1]); }

function updateSynth(dt, t) {
  const a = S.adaData, sy = S.synth; sy.group.visible = !!a && !!S.world;
  if (!a || !S.world) return;
  const sleeping = !!a.sleeping, bed = sleeping ? findBed(a.x, a.y, "synth") : null;
  sy.inBed = !!bed;
  // in bed she rests on the pillow
  const speed = moveToward(sy, bed ? bed.px - bed.hx * 0.12 : a.x + 0.5, bed ? bed.pz - bed.hz * 0.12 : a.y + 0.5, dt);
  const ground = bed ? bed.top - 0.18 : standYAt(sy.x, sy.z);
  sy.groundY = lerp(sy.groundY ?? ground, ground, damp(10, dt));
  sy.sleep = lerp(sy.sleep, sleeping ? 1 : 0, damp(3, dt));
  const bob = Math.sin(t * 2.1) * 0.06 * (1 - sy.sleep * 0.6);
  sy.y = sy.groundY + 0.52 - sy.sleep * 0.22 + bob;
  // wet: a darker, bluer core
  const wet = smooth(0.4, 1, Number(a.wet) || 0);
  sy.core.material.color.setRGB(lerp(0.66, 0.42, wet), lerp(0.74, 0.55, wet), lerp(1.0, 0.9, wet));
  sy.group.position.set(sy.x, sy.y, sy.z);
  const target = bed ? Math.atan2(-bed.hx, -bed.hz) : speed > 0.2 ? Math.atan2(sy.dirX, sy.dirZ) : faceAngle(a.facing);
  sy.heading = turnTo(sy.heading, target, damp(8, dt));
  sy.face.rotation.y = sy.heading;
  // blink
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
}

function updatePeople(dt) {
  for (const [name, f] of S.people) {
    const p = f.data; if (!p || !S.world) { f.group.visible = false; continue; }
    f.group.visible = true;
    const owner = p.role === "companion" || (S.companionName && p.name === S.companionName) ? "companion" : p.name;
    const bed = p.sleeping ? findBed(p.x, p.y, owner) : null;
    f.inBed = !!bed;
    // lying on the back in bed: feet toward the foot end, head on the pillow
    const tx = bed ? bed.px - bed.hx * 0.86 : p.x + 0.5, tz = bed ? bed.pz - bed.hz * 0.86 : p.y + 0.5;
    const speed = moveToward(f, tx, tz, dt);
    const ground = bed ? bed.top + 0.1 : standYAt(f.x, f.z); f.y = lerp(f.y || ground, ground, damp(10, dt));
    const target = bed ? Math.atan2(-bed.hx, -bed.hz) : speed > 0.2 ? Math.atan2(f.dirX, f.dirZ) : faceAngle(p.facing);
    f.heading = turnTo(f.heading, target, damp(bed ? 14 : 10, dt));
    animateFigure(f, dt, bed ? 0 : speed, p.sleeping);
    f.group.rotation.order = "YXZ";
    f.lie = lerp(f.lie || 0, bed ? 1 : 0, damp(5, dt));
    f.group.position.set(f.x, f.y + (f.bob || 0), f.z); f.group.rotation.y = f.heading;
    f.group.rotation.x = -Math.PI / 2 * f.lie;
    if (p.sleeping && !bed) { f.group.rotation.z = lerp(f.group.rotation.z, Math.PI / 2 * 0.95, damp(4, dt)); f.group.position.y += 0.15; }
    else f.group.rotation.z = lerp(f.group.rotation.z, 0, damp(6, dt));
    const wet = smooth(0.4, 1, Number(p.wet) || 0);
    f.mat.color.setRGB(lerp(1, 0.7, wet), lerp(1, 0.76, wet), lerp(1, 0.9, wet));
  }
}

function ensureAvatar() {
  if (!S.avatar) S.avatar = makeFigure("you", "#ff9a3c", "", true);
  return S.avatar;
}
function updateVisitorFigure(dt) {
  const v = S.visitorData;
  if (S.mode === "visit") {
    const av = ensureAvatar(); const L = S.local;
    av.group.visible = !S.cam.fp && L.init;
    av.group.position.set(L.x, L.y + L.hop + (av.bob || 0), L.z);
    av.heading = turnTo(av.heading, L.heading, damp(12, dt)); av.group.rotation.y = av.heading;
    animateFigure(av, dt, Math.hypot(L.vx, L.vz), false);
    return;
  }
  if (!v) { if (S.avatar) S.avatar.group.visible = false; return; }
  const av = ensureAvatar(); av.group.visible = true;
  const fx = v.fx ?? v.x, fy = v.fy ?? v.y;
  const speed = moveToward(av, fx + 0.5, fy + 0.5, dt, 5);
  const ground = standYAt(av.x, av.z); av.y = lerp(av.y || ground, ground, damp(10, dt));
  av.heading = turnTo(av.heading, speed > 0.2 ? Math.atan2(av.dirX, av.dirZ) : faceAngle(v.facing), damp(10, dt));
  animateFigure(av, dt, speed, false);
  av.group.position.set(av.x, av.y + (av.bob || 0), av.z); av.group.rotation.y = av.heading;
}

// entities, shadow blobs, glows, lights, smoke and steam
const FRUIT_SPOTS = [[0.2, 0.15], [2.3, -0.1], [4.2, 0.25], [1.2, -0.35], [3.3, -0.3], [5.4, 0.05]];
function entSize(e, k) {
  const size = k.size || "small";
  let h = size === "big" ? 0.9 : size === "creature" ? 0.55 : 0.42;
  if (e.kind === "plant") h = 0.72 * (0.28 + 0.72 * clamp(Number(e.stage ?? 4) / 4, 0, 1));
  else if (e.kind === "sprout" || e.growth !== undefined) h *= 0.35 + 0.65 * clamp((e.growth ?? 100) / 100, 0, 1);
  if (e.kind === "berry bush") h = 0.62;
  return h;
}
// where each entity wants to stand: on its host (e.on), on a table, or shuffled aside when it shares a tile
function layoutEnts() {
  const byTile = new Map(), onHost = new Map(), surf = new Map();
  for (const e of S.ents.values()) {
    const f = S.furn?.get(e.id);
    if (f?.surf) surf.set(e.x + "," + e.y, f.surf);
  }
  for (const e of S.ents.values()) {
    e.slotX = 0; e.slotZ = 0; e.lift = 0; e.host = null;
    if (HIDDEN_KINDS.has(e.kind) || FURN_KINDS.has(e.kind) || isFruitTree(e.kind)) continue;
    const k = S.kinds[e.kind] || {};
    if (k.size === "creature") continue;
    if (e.on != null && S.ents.has(e.on)) { const key = e.on; (onHost.get(key) || onHost.set(key, []).get(key)).push(e); continue; }
    const key = e.x + "," + e.y; (byTile.get(key) || byTile.set(key, []).get(key)).push(e);
  }
  for (const [key, list] of byTile) {
    const sy = surf.get(key), n = list.length;
    list.sort((a, b) => (a.id > b.id ? 1 : -1));
    list.forEach((e, i) => {
      if (sy && (S.kinds[e.kind]?.size || "small") === "small") e.lift = sy;
      if (n > 1) { const a = (i / n) * Math.PI * 2 + 0.7, r = sy ? 0.2 : n === 2 ? 0.2 : 0.27; e.slotX = Math.cos(a) * r; e.slotZ = Math.sin(a) * r * 0.85; }
    });
  }
  for (const [hostId, list] of onHost) {
    const host = S.ents.get(hostId), f = S.furn?.get(hostId), n = list.length;
    list.forEach((e, i) => {
      e.host = host; e.lift = f?.top ? f.top.y - standY(host.x, host.y) : SURFACE_Y[host.kind] ?? 0.5;
      e.slotX = n > 1 ? ((i / (n - 1)) - 0.5) * 0.36 : 0; e.slotZ = 0;
    });
  }
  S.layoutSig = S.entsVersion;
}
function updateSprites(dt, t) {
  const E = S.entBB, B = S.blobBB, G = S.glowBB, FX = S.fxBB; E.begin(); B.begin(); G.begin(); FX.begin();
  if (S.layoutSig !== S.entsVersion) layoutEnts();
  const lit = [], puffs = [], bLit = [];
  const cp = S.camera.position, night = S.env.night;
  for (const e of S.ents.values()) {
    if (HIDDEN_KINDS.has(e.kind)) continue;
    const k = S.kinds[e.kind] || {}, size = k.size || "small";
    const small = size === "small", creature = size === "creature";
    const furn = FURN_KINDS.has(e.kind), fruitTree = isFruitTree(e.kind);
    let tx, tz;
    if (e.host) { const h = S.furn?.get(e.host.id)?.top; tx = (h ? h.x : e.host.x + 0.5) + e.slotX; tz = (h ? h.z : e.host.y + 0.5) + e.slotZ; }
    else {
      const jit = small && !e.slotX && !e.slotZ && !e.lift;
      tx = e.x + 0.5 + e.slotX + (jit ? e.jx : 0); tz = e.y + 0.5 + e.slotZ + (jit ? e.jz : 0);
    }
    if (e.px === undefined || Math.hypot(tx - e.px, tz - e.pz) > 4) { e.px = tx; e.pz = tz; }
    let moving = false;
    const dx = tx - e.px, dz = tz - e.pz, d = Math.hypot(dx, dz);
    if (d > 1e-3) { const st = Math.max(3.2, d * 4) * dt; if (st >= d) { e.px = tx; e.pz = tz; } else { e.px += dx / d * st; e.pz += dz / d * st; moving = true; } if (Math.abs(dx) > 0.02) e.flip = dx > 0; }
    const tile = tileAt(Math.floor(e.px), Math.floor(e.pz));
    const ground = e.host ? standY(e.host.x, e.host.y) : standYAt(e.px, e.pz);
    const lightK = (e.lit === true || e.lit === 1) && (LIGHT_KINDS.has(e.kind) || k.light);
    if (lightK) { const bi = buildingAt(e.x, e.y); if (bi >= 0) bLit[bi] = true; }
    // furniture is drawn in 3D: only its fire shows here
    if (furn) {
      const f = S.furn?.get(e.id);
      if (lightK && f?.fire) {
        const fl = 0.85 + Math.sin(t * 13 + e.phase) * 0.08 + Math.sin(t * 23.7) * 0.06;
        if (e.kind === "fireplace") {
          const c = glyphOf("🔥", "f"), h = 0.42 * (0.92 + Math.sin(t * 9 + e.phase) * 0.05 + Math.sin(t * 17.3) * 0.04);
          E.push(f.fire.x, f.fire.y - 0.08, f.fire.z, h * c.aspect, h, c.u, c.v, c.us, c.vs, 1, 1, 1, 2);
        }
        const gs = (e.kind === "fireplace" ? 1.1 : 0.55) * fl;
        G.push(f.fire.x, f.fire.y + 0.1, f.fire.z, gs, gs, 0, 0, 1, 1, 1, 0.5, 0.18, 0.18 + night * 0.17);
        lit.push({ x: f.fire.x, y: f.fire.y + 0.35, z: f.fire.z, fire: true, hearth: true, col: [1, 0.55, 0.2], fl, power: k.light || (e.kind === "fireplace" ? 6 : 2) });
        if (e.kind === "fireplace") for (const ch of S.chimneys || []) if (ch.id === e.id) puffs.push([ch.p.x, ch.p.y, ch.p.z, 0.85, 3.6, 1.15, 0.78, 0.11]);
      }
      if (e.steam) { const f2 = S.furn?.get(e.id); const p = f2?.top || new THREE.Vector3(e.px, ground + 0.8, e.pz); puffs.push([p.x, p.y + 0.1, p.z, 0.6, 1.0, 0.4, 0.97, 0.45]); }
      if (e.smoke) puffs.push([e.px, ground + 0.9, e.pz, 0.9, 1.3, 0.55, 0.28, 0.5]);
      continue;
    }
    // fruit trees: the vegetation pass drew the tree; hang its fruit in the canopy
    if (fruitTree) {
      const spot = S.treeSpots.get(e.x + "," + e.y), fg = k.fruit || "🍎", fc = glyphOf(fg, "o"), n = clamp(Math.round(Number(e.fruit) || 0), 0, 6);
      let cx = e.x + 0.5, cz = e.y + 0.5, cy = ground + 1.0, rad = 0.5;
      if (spot) { cx = spot.x; cz = spot.z; cy = spot.cy; rad = spot.r; }
      else { const c = kindCell(e.kind), h = 1.5; E.push(e.px, ground, e.pz, h * c.aspect, h, c.u, c.v, c.us, c.vs); cx = e.px; cz = e.pz; cy = ground + 0.9; rad = 0.45; }
      // fruit on the side facing the camera so it isn't hidden in the leaves
      const va = Math.atan2(cp.x - cx, cp.z - cz);
      for (let i = 0; i < n; i++) {
        const [ang, el] = FRUIT_SPOTS[i], a = va + (ang - 2.7) * 0.42, r = rad * 0.98;
        const sw = Math.sin(t * 1.6 + i + e.phase) * 0.015 * S.env.wind, hh = 0.2;
        E.push(cx + Math.sin(a) * r * Math.cos(el) + sw, cy + Math.sin(el) * r * 0.8 - hh * 0.5, cz + Math.cos(a) * r * Math.cos(el), hh * fc.aspect, hh, fc.u, fc.v, fc.us, fc.vs, 1, 1, 1, 1.15);
      }
      continue;
    }
    const cell = entCell(e);
    let h = entSize(e, k);
    if (e.lift && small) h *= 0.82;
    let y = ground + (e.lift || 0);
    if (moving) e.hop += dt * 13; else e.hop = 0;
    if (creature) {
      y += Math.abs(Math.sin(e.hop)) * 0.22;
      if (tile === 1) { y = WATER_Y - h * 0.45 + Math.pow(Math.max(0, Math.sin(t * 0.8 + e.phase * 3)), 12) * 0.7; } // fish leap
      else if (e.kind === "bird") y += 0.05 + Math.abs(Math.sin(t * 3 + e.phase)) * 0.06;
    } else if (small && !e.lift) y += 0.04 + Math.sin(t * 1.8 + e.phase) * 0.035;
    else if (small) y += 0.01;
    const w = h * cell.aspect;
    if (S.mode === "visit" && Math.hypot(e.px - cp.x, e.pz - cp.z) < (S.cam.fp ? 0.75 : 0.45) && cp.y < y + h + 0.6) continue; // don't fill the screen
    const em = lightK ? 2 : 1, flip = creature && e.flip;
    const wet = Number(e.wet) > 0.4 ? clamp((Number(e.wet) - 0.4) / 0.6, 0, 1) : 0;
    const tr = 1 - 0.28 * wet, tg = 1 - 0.22 * wet, tb = 1 - 0.06 * wet;
    E.push(e.px, y, e.pz, flip ? -w : w, h, cell.u, cell.v, cell.us, cell.vs, tr, tg, tb, em);
    if (e.kind === "berry bush" && Number(e.fruit) > 0) {
      const bc = glyphOf(k.fruit || "🫐", "b"), n = clamp(Math.round(Number(e.fruit)), 0, 6), va = Math.atan2(cp.x - e.px, cp.z - e.pz);
      for (let i = 0; i < n; i++) {
        const a = va + (i / Math.max(1, n - 1) - 0.5) * 1.6, r = 0.2, hh = 0.15;
        E.push(e.px + Math.sin(a) * r, y + 0.12 + (i % 3) * 0.11, e.pz + Math.cos(a) * r, hh * bc.aspect, hh, bc.u, bc.v, bc.us, bc.vs, 1, 1, 1, 1.1);
      }
    }
    if (tile !== 1 && !e.lift) B.push(e.px, ground + 0.015, e.pz, w * 0.95, w * 0.6, 0, 0, 1, 1, 1, 1, 1, small ? 0.75 : 0.9);
    if (lightK || e.kind === "shrine") {
      const fire = e.kind === "fire pit" || e.kind === "campfire" || e.kind === "oven";
      const col = fire ? [1, 0.55, 0.2] : e.kind === "shrine" ? [0.7, 0.45, 1] : [1, 0.8, 0.45];
      const fl = fire ? 0.85 + Math.sin(t * 13 + e.phase) * 0.08 + Math.sin(t * 23.7) * 0.06 : 0.93 + Math.sin(t * 7 + e.phase) * 0.04 + Math.sin(t * 15.1 + e.phase) * 0.03;
      const gs = (fire ? 1.9 : 0.75) * fl * (0.6 + night * 0.5);
      const fy = fire ? y + h * 0.45 : y + h * 0.82;
      G.push(e.px, fy, e.pz, gs, gs, 0, 0, 1, 1, col[0], col[1] * 0.85, col[2] * 0.7, (0.22 + night * 0.35) * (e.kind === "shrine" && !lightK ? 0.6 : 1));
      if (!fire && lightK) G.push(e.px, fy, e.pz, 0.16 * fl, 0.22 * fl, 0, 0, 1, 1, 1, 0.75, 0.35, 0.9);   // the flame itself
      if (lightK) lit.push({ x: e.px, y: y + h * 0.75, z: e.pz, fire, col, fl, power: k.light || 3 });
    }
    if (e.steam) puffs.push([e.px, y + h * 0.85, e.pz, 0.65, 1.0, 0.38, 0.97, 0.45]);
    if (e.smoke) puffs.push([e.px, y + h * 0.7, e.pz, 0.9, 1.2, 0.5, 0.25, 0.5]);
  }
  S.bLit = bLit;
  // carried items float beside the synth / visitor
  const carry = (list, x, y, z, side) => (list || []).slice(0, 3).forEach((kind, i) => {
    const c = kindCell(kind), h = 0.3; E.push(x + side * 0.32 + i * 0.12, y + Math.sin(t * 2 + i) * 0.03, z, h * c.aspect, h, c.u, c.v, c.us, c.vs, 1, 1, 1, 1.4);
  });
  if (S.adaData && S.synth.group.visible && !S.synth.inBed) carry(S.adaData.carrying, S.synth.x, S.synth.y + 0.05, S.synth.z, 1);
  const vc = S.visitorData?.carrying;
  if (S.avatar?.group.visible && vc?.length) carry(vc, S.avatar.group.position.x, S.avatar.group.position.y + 0.55, S.avatar.group.position.z, 1);
  // blobs under characters
  if (S.synth.group.visible && !S.synth.inBed) B.push(S.synth.x, S.synth.groundY + 0.015, S.synth.z, 0.6, 0.6, 0, 0, 1, 1, 1, 1, 1, 0.6);
  for (const f of S.people.values()) if (f.group.visible && !f.inBed) B.push(f.x, f.y + 0.015, f.z, 0.55, 0.55, 0, 0, 1, 1, 1, 1, 1, 0.75);
  if (S.avatar?.group.visible) B.push(S.avatar.group.position.x, (S.mode === "visit" ? S.local.y : S.avatar.y) + 0.015, S.avatar.group.position.z, 0.55, 0.55, 0, 0, 1, 1, 1, 1, 1, 0.75 * (1 - Math.min(S.local.hop, 0.5)));
  // synth halo
  if (S.synth.group.visible) { const s = 1.05 + night * 0.5 + Math.sin(t * 2.6) * 0.06; G.push(S.synth.x, S.synth.y, S.synth.z, s, s, 0, 0, 1, 1, 0.32, 0.45, 1, (0.2 + night * 0.22) * (1 - S.synth.sleep * 0.4)); }
  // beings: music notes, drips
  if (S.synth.group.visible && S.adaData) beingFX(FX, S.synth.group.position, 0.1, S.adaData, t, 1);
  for (const f of S.people.values()) if (f.group.visible && f.data) beingFX(FX, f.group.position, f.inBed ? 0.2 : 0.75, f.data, t, 2);
  // windows + door lanterns at night, only where a light burns inside
  if (night > 0.05) {
    const cut = S.cut;
    for (const w of S.windowGlows) {
      if (!bLit[w.bi]) continue;
      if (cut && cut.bi === w.bi && cut.amt > 0.3 && (w.p.x - U.cutFocus.value.x) * U.cutDir.value.x + (w.p.z - U.cutFocus.value.y) * U.cutDir.value.y > 0.3) continue;
      G.push(w.p.x, w.p.y, w.p.z, 0.95, 0.85, 0, 0, 1, 1, 1, 0.68, 0.32, 0.3 * night * (S.bGlow[w.bi] ?? 1));
    }
    for (const w of S.doorLamps) if (bLit[w.bi]) G.push(w.p.x, w.p.y, w.p.z, 1.0, 1.0, 0, 0, 1, 1, 1, 0.7, 0.35, 0.5 * night);
  }
  E.end(); B.end(); G.end(); FX.end();
  // light pool: the lit things nearest the camera get real point lights
  for (const s of lit) s.d = Math.hypot(s.x - cp.x, s.y - cp.y, s.z - cp.z) * 0.5 + Math.hypot(s.x - S.cam.target.x, s.z - S.cam.target.z);
  lit.sort((a, b) => a.d - b.d);
  S.pool.forEach((l, i) => {
    const s = lit[i];
    if (!s) { l.intensity = 0; return; }
    l.position.set(s.x, s.y + 0.25, s.z); l.color.setRGB(s.col[0], s.col[1] * 0.9, s.col[2] * 0.8);
    const pw = clamp(s.power, 1, 8);
    l.intensity = (0.7 + pw * 0.36) * s.fl * (0.45 + night * 0.75); l.distance = 2.6 + pw * 0.9;
  });
  // embers (open fires only)
  let fi = 0;
  for (const s of lit) { if (!s.fire || s.hearth || fi >= 8) continue; S.fireU[fi++].set(s.x, s.y - 0.15, s.z, 1); }
  for (; fi < 8; fi++) S.fireU[fi].w = 0;
  // smoke + steam, nearest first
  puffs.sort((a, b) => Math.hypot(a[0] - cp.x, a[2] - cp.z) - Math.hypot(b[0] - cp.x, b[2] - cp.z));
  S.puffSrc.forEach((v, i) => {
    const p = puffs[i]; if (!p) { v.w = 0; return; }
    v.set(p[0], p[1], p[2], p[3]); S.puffPar[i].set(p[4], p[5], p[6], p[7]);
  });
}
// floating notes while playing music, drips while wet
function beingFX(FX, pos, hgt, d, t, seed) {
  const act = String(d.activity || "").toLowerCase();
  if (/^playing (the )?piano|^playing music|singing/.test(act)) {
    for (let i = 0; i < 4; i++) {
      const life = (t * 0.45 + i / 4 + seed * 0.13) % 1, g = i % 2 ? "🎵" : "🎶", c = glyphOf(g, "n");
      const a = (seed * 1.7 + i * 2.1) + life * 1.2, r = 0.25 + life * 0.35, hh = 0.2 + life * 0.06;
      const al = smooth(0, 0.12, life) * (1 - smooth(0.65, 1, life));
      FX.push(pos.x + Math.cos(a) * r, pos.y + hgt + 0.25 + life * 0.9, pos.z + Math.sin(a) * r, hh * c.aspect, hh, c.u, c.v, c.us, c.vs, 1, 1, 1, al);
    }
  }
  const wet = Number(d.wet) || 0;
  if (wet > 0.4) {
    const c = glyphOf("💧", "d"), n = wet > 0.75 ? 4 : 2;
    for (let i = 0; i < n; i++) {
      const life = (t * 0.9 + i / n + seed * 0.37) % 1, a = seed * 2.3 + i * 2.4, r = 0.18 + (i % 2) * 0.08, hh = 0.11;
      FX.push(pos.x + Math.cos(a) * r, pos.y + hgt + 0.15 - life * 0.7, pos.z + Math.sin(a) * r, hh * c.aspect, hh, c.u, c.v, c.us, c.vs, 1, 1, 1, (1 - life) * 0.9);
    }
  }
}

// ───────────────────────────────────────────────────────────── labels (DOM)
function label(key, cls) {
  let l = S.labels.get(key);
  if (!l) {
    const el = document.createElement("div"); el.className = cls; S.layer.appendChild(el);
    l = { el, text: null, vis: true }; S.labels.set(key, l);
  }
  return l;
}
function removeLabel(key) { for (const k of [key, key + ":b", key + ":z"]) { const l = S.labels.get(k); if (l) { l.el.remove(); S.labels.delete(k); } } }
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
  const cam = S.camera.position, over = S.cam.focus === "overview" || S.cam.dist > 45;
  const fade = (d, near, far) => 1 - smooth(near, far, d);
  const chars = [];
  if (S.synth.group.visible && S.adaData) chars.push(["ada", S.adaData.name || "Zen", S.synth.group.position, 0.42, S.adaData.said, S.adaData.sleeping, true, S.adaData.activity]);
  for (const [n, f] of S.people) if (f.group.visible) chars.push(["p:" + n, n, f.group.position, f.inBed ? 0.45 : 1.12, f.data.said, f.data.sleeping, false, f.data.activity]);
  if (S.avatar?.group.visible && S.mode !== "visit" && S.visitorData) chars.push(["you", S.visitorData.name || "you", S.avatar.group.position, 1.2, S.visitorData.said, false, false]);
  if (S.mode === "visit" && S.visitorData?.said && S.avatar) chars.push(["you", "", S.avatar.group.position, 1.2, S.visitorData.said, false, false]);
  const live = new Set(), bubbles = [];
  for (const [key, name, pos, hgt, said, sleeping, synth, activity] of chars) {
    const p = tmpV2.copy(pos); p.y += hgt; const d = cam.distanceTo(p);
    const act = sleeping ? "" : String(activity || "").trim();
    if (name) {
      const l = label(key, "w3d-tag" + (synth ? " w3d-tag-synth" : "")); setText(l, name); live.add(key);
      const op = synth ? Math.max(0.85 * fade(d, 40, 140), fade(d, 14, 34)) : fade(d, 14, 32) * (over ? 0 : 1);
      placeLabel(l, p, op, act ? -13 : 0);
      if (act) { // what they are doing, small and quiet under the name
        const al = label(key + ":a", "w3d-act"); setText(al, act); live.add(key + ":a");
        placeLabel(al, p, op * fade(d, 12, 26), 3);
      }
    }
    if (said) {
      const b = label(key + ":b", "w3d-bubble" + (synth ? " w3d-bubble-synth" : ""));
      if (b.text !== said) { b.text = said; b.el.innerHTML = `<span>${escapeHtml(said)}</span>`; b.w = 0; }
      live.add(key + ":b");
      placeLabel(b, p, fade(d, 22, 45), -22, bubbles);
    }
    if (sleeping) {
      const z = label(key + ":z", "w3d-zzz"); if (!z.el.firstChild) z.el.innerHTML = "<i>z</i><i>z</i><i>z</i>"; live.add(key + ":z");
      placeLabel(z, p, fade(d, 25, 50), -20);
    }
  }
  // keep speech bubbles from overlapping: nearest keeps its spot, others move up
  bubbles.sort((a, b) => a.z - b.z);
  const placed = [];
  for (const bb of bubbles) {
    if (!bb.l.w) { bb.l.w = bb.l.el.offsetWidth; bb.l.h = bb.l.el.offsetHeight; }
    const w = bb.l.w, h = bb.l.h; let y = bb.y;
    for (let guard = 0; guard < 8; guard++) {
      const hit = placed.find((r) => Math.abs(r.x - bb.x) < (r.w + w) / 2 + 4 && y > r.y - r.h - 4 && y - h < r.y + 4);
      if (!hit) break; y = hit.y - hit.h - 6;
    }
    placed.push({ x: bb.x, y, w, h });
    bb.l.el.style.transform = `translate3d(${bb.x.toFixed(1)}px,${y.toFixed(1)}px,0) translate(-50%,-100%)`;
  }
  // place names in overview
  for (const [k, pl] of S.placeLabels || []) {
    live.add(k);
    if (pl.room) { // room names show on the floor of a building whose roof is off
      const r = S.roofs.find((rr) => rr.bi === pl.bi), o = r ? (1 - r.fade) * fade(S.cam.dist, 16, 34) * 0.9 : 0;
      tmpV2.set(pl.x + 0.5, standY(pl.x, pl.y) + 0.15, pl.y + 0.5); placeLabel(pl.l, tmpV2, o);
      continue;
    }
    const o = smooth(28, 55, S.cam.dist);
    tmpV2.set(pl.x + 0.5, standY(pl.x, pl.y) + (pl.bi >= 0 ? WALL_H + 1.2 : 1.6), pl.y + 0.5); placeLabel(pl.l, tmpV2, o);
  }
  for (const [k, l] of S.labels) if (!live.has(k)) { if (l.vis) { l.el.style.display = "none"; l.vis = false; } }
}
function makePlaceLabels() {
  for (const [, pl] of S.placeLabels || []) pl.l.el.remove();
  for (const [k] of S.placeLabels || []) S.labels.delete(k);
  S.placeLabels = new Map();
  for (const [name, xy] of Object.entries(S.world?.places || {})) {
    if (!Array.isArray(xy)) continue;
    const b = S.world.buildings.find((bb) => bb.name === name), bi = buildingAt(xy[0], xy[1]);
    const room = !b && bi >= 0;   // a room inside a building
    const key = "place:" + name, l = label(key, room ? "w3d-place w3d-room" : "w3d-place"); setText(l, b?.label || name.replace(/_/g, " "));
    S.placeLabels.set(key, { l, x: xy[0], y: xy[1], room, bi });
  }
}

// ───────────────────────────────────────────────────────────── roofs cut-away
// the point the view is about: the visitor, the followed person, or Zen
function focusSubject() {
  const c = S.cam;
  if (S.mode === "visit" && S.local.init) return { x: S.local.x, z: S.local.z, strong: true };
  if (c.focus === "overview") return null;
  if (c.focus === "you" && S.avatar?.group.visible) return { x: S.avatar.group.position.x, z: S.avatar.group.position.z };
  if (c.focus.startsWith("person:")) { const f = S.people.get(c.focus.slice(7)); if (f?.group.visible) return { x: f.x, z: f.z }; }
  if (S.adaData && S.synth.init) return { x: S.synth.x, z: S.synth.z };
  return null;
}
function updateRoofs(dt) {
  const f = focusSubject(), near = S.cam.dist < 46 || S.mode === "visit";
  const cp = S.camera.position;
  let inB = -1;
  for (let i = 0; i < S.roofs.length; i++) {
    const r = S.roofs[i], b = r.b, m = f?.strong ? 0.35 : 0.02;
    const inside = !!f && near && f.x > b.x0 - m && f.x < b.x1 + 1 + m && f.z > b.y0 - m && f.z < b.y1 + 1 + m;
    const camIn = cp.x > b.x0 - 0.3 && cp.x < b.x1 + 1.3 && cp.z > b.y0 - 0.3 && cp.z < b.y1 + 1.3 && cp.y < standY(b.x0, b.y0) + WALL_H + 3;
    if (inside) inB = r.bi;
    const target = inside || camIn ? 0 : 1;
    r.fade = lerp(r.fade, target, damp(6, dt));
    const mat = r.mesh.material;
    const tr = r.fade < 0.99;
    if (mat.transparent !== tr) { mat.transparent = tr; mat.depthWrite = !tr; mat.needsUpdate = true; }
    mat.opacity = r.fade; r.mesh.visible = r.fade > 0.03; r.mesh.castShadow = r.fade > 0.5;
  }
  // dollhouse cut: walls of that building between the camera and the focus drop to knee height
  const cut = S.cut || (S.cut = { bi: -1, amt: 0 });
  const want = inB >= 0 && !(S.mode === "visit" && S.cam.fp) ? inB : -1;
  if (cut.bi !== want) { cut.amt = lerp(cut.amt, 0, damp(10, dt)); if (cut.amt < 0.02 || cut.bi < 0) { cut.bi = want; } }
  else cut.amt = lerp(cut.amt, want >= 0 ? 1 : 0, damp(5, dt));
  const info = S.bInfo?.[cut.bi];
  if (cut.bi >= 0 && info && cut.amt > 0.005) {
    const b = info.b; U.cutBox.value.set(b.x0, b.y0, b.x1 + 1, b.y1 + 1);
    if (f) U.cutFocus.value.set(f.x, f.z);
    const dx = cp.x - U.cutFocus.value.x, dz = cp.z - U.cutFocus.value.y, dl = Math.hypot(dx, dz) || 1;
    U.cutDir.value.set(dx / dl, dz / dl);
    U.cutY.value = lerp(info.top + 0.05, info.base + 0.55, smooth(0, 1, cut.amt));
  } else { U.cutBox.value.set(0, 0, -1, -1); U.cutY.value = 99; }
}

// ───────────────────────────────────────────────────────────── camera
function snapCamera() {
  const c = S.cam; c.yaw = c.tYaw; c.pitch = c.tPitch; c.dist = c.tDist;
  const f = focusPoint(); if (f) c.target.copy(f);
}
function focusPoint() {
  const c = S.cam, w = S.world;
  if (c.focus === "overview" && w) return tmpV2.set(w.W / 2, 1.5, w.H / 2).clone();
  if (S.mode === "visit" && S.local.init) return new THREE.Vector3(S.local.x, S.local.y + (c.fp ? 0.82 : 0.95) + (c.fp ? S.local.hop : S.local.hop * 0.4), S.local.z);
  if (c.focus === "you" && S.avatar?.group.visible) return S.avatar.group.position.clone().add(new THREE.Vector3(0, 0.8, 0));
  if (c.focus.startsWith("person:")) { const f = S.people.get(c.focus.slice(7)); if (f) return f.group.position.clone().add(new THREE.Vector3(0, 0.9, 0)); }
  if (S.adaData) { const sy = S.synth, a = S.adaData; return sy.init ? new THREE.Vector3(sy.x, sy.y, sy.z) : new THREE.Vector3(a.x + 0.5, standY(a.x, a.y) + 0.5, a.y + 0.5); }
  return w ? new THREE.Vector3(w.W / 2, 1, w.H / 2) : null;
}
function updateCamera(dt) {
  const c = S.cam, cam = S.camera;
  const k = damp(S.mode === "visit" ? 18 : 6, dt);
  c.yaw = turnTo(c.yaw, c.tYaw, S.mode === "visit" ? 1 : damp(10, dt));
  c.pitch = lerp(c.pitch, c.tPitch, S.mode === "visit" ? 1 : damp(10, dt));
  c.dist = lerp(c.dist, c.tDist, damp(c.focus === "overview" ? 2.5 : 7, dt));
  const f = focusPoint();
  if (f) c.target.lerp(f, S.mode === "visit" ? 1 : c.focus === "overview" ? damp(2.5, dt) : k);
  const off = tmpV.set(Math.sin(c.yaw) * Math.cos(c.pitch), Math.sin(c.pitch), Math.cos(c.yaw) * Math.cos(c.pitch));
  if (S.mode === "visit" && c.fp) {
    cam.position.copy(c.target);
    cam.lookAt(c.target.x - off.x, c.target.y - off.y, c.target.z - off.z);
  } else {
    let dist = c.dist;
    const look = tmpV2.copy(c.target);
    if (S.mode === "visit") { // over-the-shoulder: shift the pivot a little to the right of the avatar
      const sh = 0.32 * clamp(dist / 4, 0, 1); look.x += Math.cos(c.yaw) * sh; look.z -= Math.sin(c.yaw) * sh;
      dist = cameraClearance(look, off, dist);
    }
    cam.position.copy(look).addScaledVector(off, dist);
    const gy = S.world ? groundBelow(cam.position.x, cam.position.z) + 0.35 : -99;
    if (cam.position.y < gy) cam.position.y = gy;
    cam.lookAt(look);
  }
  S.sky.position.copy(cam.position);
  S.weatherCenter.value.copy(cam.position);
  // shadow camera follows the view, snapped to texels to avoid shimmer
  const ov = c.focus === "overview" || c.dist > 40, half = ov ? Math.max(S.world?.W || 128, S.world?.H || 96) * 0.62 : 26;
  const sc = S.sun.shadow.camera;
  if (sc.right !== half) { sc.left = -half; sc.right = half; sc.top = half; sc.bottom = -half; sc.near = 1; sc.far = 220; sc.updateProjectionMatrix(); }
  const tex = (half * 2) / S.sun.shadow.mapSize.x;
  const tgt = ov && S.world ? tmpV2.set(S.world.W / 2, 0, S.world.H / 2) : tmpV2.copy(c.target);
  tgt.x = Math.round(tgt.x / tex) * tex; tgt.z = Math.round(tgt.z / tex) * tex; tgt.y = 0;
  S.sun.target.position.copy(tgt); S.sun.position.copy(tgt).addScaledVector(S.env.sunDir, 100);
  S.sun.target.updateMatrixWorld();
}
function updateBow() {
  if (!S.bow.visible) return;
  const cp = S.camera.position, D = 560, sd = S.env.sunDir;
  let dx = -sd.x * 0.35, dz = -1; const l = Math.hypot(dx, dz); dx /= l; dz /= l;
  S.bow.position.set(cp.x + dx * D, cp.y - D * 0.16, cp.z + dz * D);
  S.bow.scale.setScalar(D * 0.6);
  S.bow.lookAt(cp.x, cp.y - D * 0.16, cp.z);
}
function groundBelow(x, z) {
  const tx = Math.floor(x), tz = Math.floor(z); if (!inMap(tx, tz)) return BASE_Y;
  const k = tileAt(tx, tz); let y = Math.max(topY(tx, tz), WATER_Y);
  if (k === 8) y += buildingAt(tx, tz) >= 0 ? WALL_H : 1.0;
  return y;
}
function cameraClearance(target, off, dist) {
  for (let s = 0.4; s < dist; s += 0.15) {
    const x = target.x + off.x * s, y = target.y + off.y * s, z = target.z + off.z * s;
    const tx = Math.floor(x), tz = Math.floor(z), k = tileAt(tx, tz);
    let top = groundBelow(x, z);
    if (k === 3 || k === 18) top += 0.7;
    if (y < top + 0.15) return Math.max(0.6, s - 0.25);
  }
  return dist;
}

// ───────────────────────────────────────────────────────────── visit mode movement + interaction
function initLocal() {
  const L = S.local, v = S.visitorData;
  if (v) { L.x = (v.fx ?? v.x) + 0.5; L.z = (v.fy ?? v.y) + 0.5; L.facing = v.facing || "south"; }
  else if (S.adaData) { L.x = S.adaData.x + 0.5; L.z = S.adaData.y + 1.5; if (blocked(Math.floor(L.x), Math.floor(L.z))) L.z -= 2; }
  else if (S.world) { L.x = S.world.W / 2; L.z = S.world.H / 2; }
  else return;
  L.y = standYAt(L.x, L.z); L.vx = L.vz = 0; L.init = true; L.heading = faceAngle(L.facing);
  S.cam.tYaw = S.cam.yaw = L.heading + Math.PI; S.cam.tPitch = S.cam.pitch = 0.32; S.cam.tDist = S.cam.dist = 4.6;
}
function collide(p, r = 0.3) {
  for (let it = 0; it < 3; it++) {
    for (let ty = Math.floor(p.z - r); ty <= Math.floor(p.z + r); ty++) for (let tx = Math.floor(p.x - r); tx <= Math.floor(p.x + r); tx++) {
      if (!blocked(tx, ty)) continue;
      const cx = clamp(p.x, tx, tx + 1), cz = clamp(p.z, ty, ty + 1), dx = p.x - cx, dz = p.z - cz, d2 = dx * dx + dz * dz;
      if (d2 >= r * r) continue;
      if (d2 > 1e-9) { const d = Math.sqrt(d2), push = r - d; p.x += (dx / d) * push; p.z += (dz / d) * push; }
      else { // centre inside the tile: push out along the shortest axis
        const opts = [[p.x - tx + r, -1, 0], [tx + 1 - p.x + r, 1, 0], [p.z - ty + r, 0, -1], [ty + 1 - p.z + r, 0, 1]].sort((a, b) => a[0] - b[0]);
        p.x += opts[0][1] * opts[0][0]; p.z += opts[0][2] * opts[0][0];
      }
    }
  }
}
function facingFrom(x, z) { return Math.abs(x) > Math.abs(z) ? (x > 0 ? "east" : "west") : (z > 0 ? "south" : "north"); }
function updateVisit(dt, now) {
  const L = S.local; if (!L.init) { initLocal(); if (!L.init) return; }
  const K = S.keys, c = S.cam;
  const fwd = [-Math.sin(c.yaw), -Math.cos(c.yaw)], right = [Math.cos(c.yaw), -Math.sin(c.yaw)];
  let ix = 0, iz = 0;
  if (K.has("KeyW") || K.has("ArrowUp")) { ix += fwd[0]; iz += fwd[1]; }
  if (K.has("KeyS") || K.has("ArrowDown")) { ix -= fwd[0]; iz -= fwd[1]; }
  if (K.has("KeyD") || K.has("ArrowRight")) { ix += right[0]; iz += right[1]; }
  if (K.has("KeyA") || K.has("ArrowLeft")) { ix -= right[0]; iz -= right[1]; }
  const il = Math.hypot(ix, iz); if (il > 0) { ix /= il; iz /= il; }
  const sp = K.has("ShiftLeft") || K.has("ShiftRight") ? 5.6 : 3.1;
  const a = damp(il > 0 ? 9 : 12, dt);
  L.vx = lerp(L.vx, ix * sp, a); L.vz = lerp(L.vz, iz * sp, a);
  const p = { x: L.x + L.vx * dt, z: L.z + L.vz * dt };
  collide(p);
  if (S.world) { p.x = clamp(p.x, 0.3, S.world.W - 0.3); p.z = clamp(p.z, 0.3, S.world.H - 0.3); }
  const movedX = (p.x - L.x) / Math.max(dt, 1e-4), movedZ = (p.z - L.z) / Math.max(dt, 1e-4);
  L.x = p.x; L.z = p.z;
  // keep velocity consistent with what collision allowed (sliding)
  L.vx = lerp(L.vx, movedX, 0.5); L.vz = lerp(L.vz, movedZ, 0.5);
  L.y = lerp(L.y, standYAt(L.x, L.z), damp(12, dt));
  // hop
  if (L.hop > 0 || L.hv > 0) { L.hv -= 18 * dt; L.hop += L.hv * dt; if (L.hop <= 0) { L.hop = 0; L.hv = 0; } }
  const speed = Math.hypot(L.vx, L.vz), moving = speed > 0.25;
  if (moving) { L.heading = Math.atan2(L.vx, L.vz); L.facing = facingFrom(L.vx, L.vz); }
  if (moving && now - L.lastSend > 100) { L.lastSend = now; sendMove(); }
  if (!moving && L.wasMoving) sendMove();
  L.wasMoving = moving;
  updateInteraction();
}
function sendMove() {
  const L = S.local;
  try { World3D.onMove?.(+(L.x - 0.5).toFixed(3), +(L.z - 0.5).toFixed(3), L.facing); } catch (e) { console.error(e); }
}
function nearSynth(r) { return S.adaData && S.synth.group.visible && Math.hypot(S.synth.x - S.local.x, S.synth.z - S.local.z) <= r; }
function updateInteraction() {
  const L = S.local, c = S.cam, fx = -Math.sin(c.yaw), fz = -Math.cos(c.yaw);
  let best = null, bestS = 1e9;
  const consider = (x, z, target, verb) => {
    const dx = x - L.x, dz = z - L.z, d = Math.hypot(dx, dz); if (d > 1.6) return;
    const dot = d > 1e-3 ? (dx * fx + dz * fz) / d : 1;
    if (dot < 0.25 && d > 0.75) return;
    const s = d + (1 - dot) * 1.3 - (target.kind === "entity" ? 0 : 0.35); if (s < bestS) { bestS = s; best = { target, verb }; }
  };
  if (S.adaData && S.synth.group.visible) consider(S.synth.x, S.synth.z, { kind: "synth" }, `Talk to ${S.adaData.name || "Zen"}`);
  for (const [n, f] of S.people) if (f.group.visible) consider(f.x, f.z, { kind: "person", name: n }, `Talk to ${n}`);
  for (const e of S.ents.values()) {
    const k = S.kinds[e.kind] || {};
    const verb = READ_KINDS.has(e.kind) ? `Read ${e.kind}` : k.size === "small" ? `Pick up ${e.kind}` : `Use ${e.kind}`;
    consider(e.px ?? e.x + 0.5, e.pz ?? e.y + 0.5, { kind: "entity", id: e.id }, verb);
  }
  S.interactTarget = best;
  const chips = [];
  if (best) chips.push(["E", best.verb]);
  const carrying = S.visitorData?.carrying?.length;
  const zen = S.adaData?.name || "Zen";
  if (carrying && nearSynth(2)) chips.push(["G", `Give to ${zen}`]);
  if (nearSynth(2)) chips.push(["H", `Hug ${zen}`]);
  const html = chips.map(([k, t]) => `<span class="w3d-chip"><kbd>${k}</kbd>${escapeHtml(t)}</span>`).join("");
  if (html !== S.promptHtml) { S.promptHtml = html; S.prompt.innerHTML = html; }
  S.prompt.hidden = !html;
}
function escapeHtml(s) { return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
function act(a) { try { World3D.onAction?.(a); } catch (e) { console.error(e); } }

// ───────────────────────────────────────────────────────────── input
function bindInput() {
  const el = S.renderer.domElement;
  el.addEventListener("contextmenu", (e) => e.preventDefault());
  el.addEventListener("pointerdown", (e) => {
    if (S.locked) return;
    S.drag = { x: e.clientX, y: e.clientY, moved: false, id: e.pointerId, button: e.button };
    try { el.setPointerCapture(e.pointerId); } catch {}
  });
  el.addEventListener("pointermove", (e) => {
    const c = S.cam;
    if (S.locked) { look(e.movementX, e.movementY); return; }
    const d = S.drag; if (!d) { hover(e); return; }
    if (S.hoverEl) S.hoverEl.hidden = true;
    const dx = e.clientX - d.x, dy = e.clientY - d.y;
    if (!d.moved && Math.hypot(dx, dy) < 4) return;
    d.moved = true; d.x = e.clientX; d.y = e.clientY;
    if (S.mode === "visit") look(dx, dy);
    else { c.tYaw -= dx * 0.006; c.tPitch = clamp(c.tPitch + dy * 0.004, 0.12, 1.45); }
  });
  const up = (e) => {
    const d = S.drag; S.drag = null;
    try { el.releasePointerCapture(e.pointerId); } catch {}
    if (!d || d.moved) return;
    if (S.mode === "visit") { requestLock(); return; }
    pick(e);
  };
  el.addEventListener("pointerup", up); el.addEventListener("pointercancel", () => { S.drag = null; });
  el.addEventListener("pointerleave", () => { if (S.hoverEl) S.hoverEl.hidden = true; });
  el.addEventListener("wheel", (e) => {
    e.preventDefault();
    const c = S.cam, f = Math.pow(1.0015, e.deltaY * (e.deltaMode === 1 ? 30 : 1));
    if (S.mode === "visit") { if (!c.fp) c.tDist = clamp(c.tDist * f, 1.8, 10); return; }
    c.tDist = clamp(c.tDist * f, 3, Math.max(60, Math.max(S.world?.W || 128, S.world?.H || 96) * 1.5));
    if (c.focus === "overview" && c.tDist < 40) c.focus = "synth";
  }, { passive: false });
  window.addEventListener("keydown", onKey);
  window.addEventListener("keyup", (e) => S.keys.delete(e.code));
  window.addEventListener("blur", () => S.keys.clear());
}
function look(dx, dy) {
  const c = S.cam;
  c.tYaw -= dx * 0.0024; c.yaw = c.tYaw;
  c.tPitch = clamp(c.tPitch + dy * 0.0022, c.fp ? -1.3 : -0.35, c.fp ? 1.3 : 1.25);
  c.pitch = c.tPitch;
}
function requestLock() {
  const el = S.renderer.domElement;
  try { const p = el.requestPointerLock?.(); if (p?.catch) p.catch(() => {}); } catch {}
}
function onKey(e) {
  if (S.mode !== "visit" || isTyping() || e.ctrlKey || e.metaKey || e.altKey) return;
  const code = e.code;
  if (e.type === "keydown") {
    const move = ["KeyW", "KeyA", "KeyS", "KeyD", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "ShiftLeft", "ShiftRight"];
    if (move.includes(code)) { S.keys.add(code); if (code.startsWith("Arrow")) e.preventDefault(); return; }
    if (e.repeat) return;
    const zen = () => nearSynth(2);
    switch (code) {
      case "Space": e.preventDefault(); if (S.local.hop === 0) S.local.hv = 4.6, S.local.hop = 0.001; break;
      case "KeyE": if (S.interactTarget) act({ type: "interact", target: S.interactTarget.target }); break;
      case "KeyG": if (zen()) act({ type: "give" }); break;
      case "KeyH": if (zen()) act({ type: "hug" }); break;
      case "KeyQ": act({ type: "drop" }); break;
      case "KeyT": case "Enter": case "NumpadEnter": e.preventDefault(); if (document.pointerLockElement) document.exitPointerLock(); S.keys.clear(); act({ type: "talk" }); break;
      case "KeyV": S.cam.fp = !S.cam.fp; if (S.cam.fp) { S.cam.tPitch = S.cam.pitch = 0; } else { S.cam.tPitch = S.cam.pitch = 0.32; } updateHud(); break;
      case "Digit1": case "Digit2": case "Digit3": case "Digit4": act({ type: "slot", index: +code.slice(5) - 1 }); break;
      default: return;
    }
  }
}
function updateHud() {
  const v = S.mode === "visit";
  S.cross.hidden = !(v && (S.locked || S.cam.fp));
  S.hint.hidden = !(v && !S.locked);
  if (!v) S.prompt.hidden = true;
  S.container.classList.toggle("w3d-visit", v); S.container.classList.toggle("w3d-locked", S.locked);
}

// picking: characters/entities by screen distance, then the terrain by marching the height grid
function pick(e) {
  if (!S.world) return;
  const best = pickAt(e, true);
  if (best) try { World3D.onPick?.(best); } catch (err) { console.error(err); }
}
function entInfo(ent) {
  const info = { kind: "entity", id: ent.id, entKind: ent.kind };
  if (Array.isArray(ent.contents)) info.contents = ent.contents.slice();
  for (const k of ["lit", "fruit", "stage", "crop", "owner", "text", "name"]) if (ent[k] !== undefined) info[k] = ent[k];
  return info;
}
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
  for (const [n, f] of S.people) if (f.group.visible) test(f.group.position, 0.55, 0.6, { kind: "person", name: n });
  for (const ent of S.ents.values()) {
    if (HIDDEN_KINDS.has(ent.kind)) continue;
    const k = S.kinds[ent.kind] || {}; let h = entSize(ent, k), y0 = standY(ent.x, ent.y) + (ent.lift || 0), px = ent.px ?? ent.x + 0.5, pz = ent.pz ?? ent.y + 0.5;
    if (isFruitTree(ent.kind)) { const sp = S.treeSpots.get(ent.x + "," + ent.y); if (sp) { px = sp.x; pz = sp.z; y0 = sp.y; h = 2; } }
    if (FURN_KINDS.has(ent.kind)) h = ent.kind === "rug" ? 0.1 : 0.8;
    test(new THREE.Vector3(px, y0, pz), h / 2, Math.max(h * 0.7, 0.3), entInfo(ent));
  }
  if (!best && terrain) {
    const ray = new THREE.Raycaster(); ray.setFromCamera(new THREE.Vector2((mx / rect.width) * 2 - 1, -(my / rect.height) * 2 + 1), S.camera);
    const o = ray.ray.origin, d = ray.ray.direction;
    for (let s = 0; s < 400; s += 0.05) {
      const x = o.x + d.x * s, y = o.y + d.y * s, z = o.z + d.z * s, tx = Math.floor(x), tz = Math.floor(z);
      if (inMap(tx, tz) && y <= Math.max(topY(tx, tz), WATER_Y) + (tileAt(tx, tz) === 8 ? WALL_H : 0)) { best = { kind: "tile", x: tx, y: tz }; break; }
      if (y < BASE_Y) break;
    }
  }
  return best;
}
// hover: a small label naming the thing under the pointer (and what is inside it)
function hover(e) {
  if (!S.world || S.mode === "visit" || S.drag) { if (S.hoverEl) S.hoverEl.hidden = true; return; }
  const now = performance.now(); if (now - (S.hoverT || 0) < 90) return; S.hoverT = now;
  const best = pickAt(e, false);
  if (!S.hoverEl) { S.hoverEl = document.createElement("div"); S.hoverEl.className = "w3d-hover"; S.container.appendChild(S.hoverEl); }
  const el = S.hoverEl;
  let html = "";
  if (best?.kind === "entity") {
    const ent = S.ents.get(best.id), k = S.kinds[ent?.kind] || {};
    if (ent) {
      const name = ent.name ? `${ent.name} (${ent.kind})` : ent.kind === "plant" && ent.crop ? `${ent.crop} plant` : ent.kind;
      html = `<b>${escapeHtml((ent.glyph || k.glyph || "") + " " + name)}</b>`;
      const extra = [];
      if (ent.lit) extra.push("lit");
      if (ent.fruit > 0 && k.fruit) extra.push(`${ent.fruit} ${k.fruit}`);
      if (ent.kind === "plant" && ent.stage !== undefined) extra.push(["seed", "sprout", "growing", "flowering", "ripe"][clamp(Math.floor(ent.stage), 0, 4)]);
      if (extra.length) html += ` <span>${escapeHtml(extra.join(" · "))}</span>`;
      if (Array.isArray(ent.contents)) {
        const cnt = new Map(); for (const c of ent.contents) cnt.set(c, (cnt.get(c) || 0) + 1);
        html += `<div>${cnt.size ? [...cnt].map(([c, n]) => escapeHtml(`${S.kinds[c]?.glyph || ""} ${n > 1 ? n + " × " : ""}${c}`)).join(", ") : "empty"}</div>`;
      }
    }
  }
  if (!html) { el.hidden = true; return; }
  if (el.dataset.h !== html) { el.innerHTML = html; el.dataset.h = html; }
  const rect = S.container.getBoundingClientRect();
  el.style.transform = `translate(${Math.round(e.clientX - rect.left + 14)}px, ${Math.round(e.clientY - rect.top + 16)}px)`;
  el.hidden = false;
}

// ───────────────────────────────────────────────────────────── main loop
function frame(now) {
  S.raf = requestAnimationFrame(frame);
  if (S.paused) return;
  // A frame cap: the valley looks the same at 60 fps as at 240, and on a laptop the browser
  // shares the GPU (and its heat) with the Academy's training.
  const minGap = S.quality === "low" ? 1000 / 31 : 1000 / 61;
  if (now - S.lastFrame < minGap) return;
  const dt = Math.min(0.1, (now - S.lastFrame) / 1000); S.lastFrame = now;
  if (!S.vw || !S.vh || S.container.clientWidth === 0) return;
  const t0 = performance.now();
  U.time.value += dt; const t = U.time.value;
  updateEnv(dt);
  if (S.world) {
    if (S.mode === "visit") updateVisit(dt, now);
    updateSynth(dt, t); updatePeople(dt); updateVisitorFigure(dt);
    updateSprites(dt, t);
  }
  updateClouds(dt);
  updateCamera(dt);
  updateBow();
  if (S.world) updateRoofs(dt);
  const pr = S.renderer.getPixelRatio();
  S.snowMat.uniforms.uPR.value = pr * (S.vh / 900); S.emberMat.uniforms.uPR.value = pr * (S.vh / 900); S.puffMat.uniforms.uPR.value = pr * (S.vh / 900); if (S.flyMat) S.flyMat.uniforms.uPR.value = pr * (S.vh / 900);
  S.renderer.render(S.scene, S.camera);
  updateLabels();
  const st = S.stats, info = S.renderer.info.render;
  st.drawCalls = info.calls; st.triangles = info.triangles;
  st.frames++; st.msAcc += performance.now() - t0;
  if (now - st.last > 1000) { st.fps = Math.round((st.frames * 1000) / (now - st.last)); st.ms = +(st.msAcc / st.frames).toFixed(2); st.frames = 0; st.msAcc = 0; st.last = now; }
}

// ───────────────────────────────────────────────────────────── public API
function setMode(mode) {
  if (!S.inited) return;
  mode = mode === "visit" ? "visit" : "watch";
  if (mode === S.mode) return;
  S.mode = mode; S.keys.clear();
  if (mode === "visit") { S.local.init = false; S.cam.focus = "you"; S.cam.fp = false; initLocal(); }
  else {
    if (document.pointerLockElement) document.exitPointerLock();
    S.cam.fp = false; S.cam.focus = "synth"; S.cam.tPitch = 0.72; S.cam.tDist = 13; S.prompt.hidden = true;
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
  rebuildIfNeeded(); resize();
}
function focusOn(what) {
  if (!S.inited) return;
  const c = S.cam;
  if (what === "overview") { c.focus = "overview"; c.tDist = Math.max(S.world?.W || 128, S.world?.H || 96) * 0.95; c.tPitch = 0.95; }
  else if (what === "you") { c.focus = "you"; if (S.mode === "visit") { c.tYaw = c.yaw = S.local.heading + Math.PI; c.tPitch = c.pitch = 0.32; } else { c.tDist = 11; c.tPitch = 0.65; } }
  else if (what && what !== "synth" && S.people.has(what)) { c.focus = "person:" + what; if (S.mode !== "visit") { c.tDist = 12; c.tPitch = 0.7; } }
  else { c.focus = "synth"; if (S.mode !== "visit") { c.tDist = 13; c.tPitch = 0.72; } }
}
function pause(p) { S.paused = !!p; if (!p) S.lastFrame = performance.now(); }
function stats() { const s = S.stats; return { fps: s.fps, drawCalls: s.drawCalls, triangles: s.triangles, ms: s.ms }; }

World3D._debug = S;
S.snapAll = () => { S.env.cur = null; computeEnvTargets(); U.snow.value = S.env.snow; snapCamera(); for (const r of S.roofs) r.fade = 1; };
window.World3D = World3D;
export default World3D;
