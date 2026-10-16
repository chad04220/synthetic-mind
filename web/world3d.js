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
};
const PV = `uniform float uTime; uniform float uWind; varying vec3 vW3Pos; varying vec3 vW3N;`;
function patch(mat, { snow = 0, wind = 0, key = "" } = {}) {
  mat.defines = Object.assign(mat.defines || {}, { W3_SNOW: snow.toFixed(3), W3_WIND: wind | 0 });
  mat.onBeforeCompile = (sh) => {
    sh.uniforms.uTime = U.time; sh.uniforms.uWind = U.wind; sh.uniforms.uSnow = U.snow;
    sh.vertexShader = sh.vertexShader
      .replace("#include <common>", "#include <common>\n" + PV)
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
  mat.customProgramCacheKey = () => "w3" + snow + "_" + wind + key;
  return mat;
}
function lambert(opts, p) { return patch(new THREE.MeshLambertMaterial(opts), p); }

// ───────────────────────────────────────────────────────────── geometry accumulator
class Builder {
  constructor() { this.p = []; this.n = []; this.c = []; }
  get count() { return this.p.length / 3; }
  tri(a, b, c, n, ca, cb, cc) {
    // orient so the face normal agrees with n
    const ux = b[0] - a[0], uy = b[1] - a[1], uz = b[2] - a[2], vx = c[0] - a[0], vy = c[1] - a[1], vz = c[2] - a[2];
    const cx = uy * vz - uz * vy, cy = uz * vx - ux * vz, cz = ux * vy - uy * vx;
    if (cx * n[0] + cy * n[1] + cz * n[2] < 0) { [b, c] = [c, b]; [cb, cc] = [cc, cb]; }
    this.p.push(...a, ...b, ...c); this.n.push(...n, ...n, ...n);
    this.c.push(ca.r, ca.g, ca.b, cb.r, cb.g, cb.b, cc.r, cc.g, cc.b);
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
    }
    ng.dispose();
  }
  box(cx, cy, cz, sx, sy, sz, color, ry = 0, shadeFn) {
    tmpM.compose(tmpV.set(cx, cy, cz), tmpQ.setFromAxisAngle(tmpV2.set(0, 1, 0), ry), tmpS.set(sx, sy, sz));
    this.geom(UNIT_BOX, tmpM, color, shadeFn);
  }
  build() {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(this.p, 3));
    g.setAttribute("normal", new THREE.Float32BufferAttribute(this.n, 3));
    g.setAttribute("color", new THREE.Float32BufferAttribute(this.c, 3));
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
    const uniforms = THREE.UniformsUtils.merge([THREE.UniformsLib.fog, { map: { value: tex } }]);
    uniforms.uLight = U.light;
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
uniform float uTime; uniform vec3 uCenter; attribute vec4 aSeed; varying float vA;
void main() {
  vec3 box = vec3(36.0, 22.0, 36.0);
  vec3 p; p.xz = uCenter.xz + mod(aSeed.xz * box.xz - uCenter.xz, box.xz) - box.xz * 0.5;
  p.y = uCenter.y - 8.0 + mod(aSeed.y * box.y - uTime * 16.0 * (0.8 + aSeed.w * 0.4), box.y);
  p += vec3(0.08, 0.55, 0.03) * position.y;
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
  staticGroup: null, roofs: [], windowGlows: [], doorLamps: [], fireflySpots: [],
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
  scene.add(S.entBB.group, S.blobBB.group, S.glowBB.group);

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
  const n = S.quality === "high" ? 3 : 1;
  S.pool = [];
  for (let i = 0; i < n; i++) { const l = new THREE.PointLight(0xffa04a, 0, 9, 1.5); S.scene.add(l); S.pool.push(l); }
}

// ───────────────────────────────────────────────────────────── glyph atlas
function makeAtlas() {
  const c = document.createElement("canvas"); c.width = c.height = 1024;
  S.atlas = { canvas: c, ctx: c.getContext("2d", { willReadFrequently: true }), cells: new Map(), next: 0 };
  S.atlasTex = new THREE.CanvasTexture(c); S.atlasTex.colorSpace = THREE.SRGBColorSpace; S.atlasTex.anisotropy = 4;
  S.atlasTex.minFilter = THREE.LinearMipmapLinearFilter;
}
function glyphCell(key, glyph, color) {
  const A = S.atlas; let cell = A.cells.get(key); if (cell) return cell;
  const idx = A.next < 64 ? A.next++ : 63, cx = (idx % 8) * 128, cy = Math.floor(idx / 8) * 128, g = A.ctx;
  g.clearRect(cx, cy, 128, 128);
  g.save(); g.beginPath(); g.rect(cx, cy, 128, 128); g.clip();
  g.font = `96px ${EMOJI_FONT}`; g.textAlign = "center"; g.textBaseline = "middle"; g.fillStyle = "#fff";
  if (glyph) g.fillText(glyph, cx + 64, cy + 70);
  let bb = alphaBox(g, cx, cy);
  if (!bb) { // no emoji font: draw a badge
    g.fillStyle = color || "#9aa"; g.beginPath(); g.arc(cx + 64, cy + 64, 46, 0, 7); g.fill();
    g.lineWidth = 6; g.strokeStyle = "rgba(255,255,255,.85)"; g.stroke();
    g.fillStyle = "#fff"; g.font = "bold 56px system-ui,sans-serif"; g.fillText((key[0] || "?").toUpperCase(), cx + 64, cy + 68);
    bb = alphaBox(g, cx, cy) || { x: cx, y: cy, w: 128, h: 128 };
  }
  g.restore();
  const p = 2; const x = Math.max(cx, bb.x - p), y = Math.max(cy, bb.y - p);
  const w = Math.min(cx + 128, bb.x + bb.w + p) - x, h = Math.min(cy + 128, bb.y + bb.h + p) - y;
  cell = { u: x / 1024, v: 1 - (y + h) / 1024, us: w / 1024, vs: h / 1024, aspect: w / h };
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

// ───────────────────────────────────────────────────────────── world queries
function inMap(x, y) { const w = S.world; return w && x >= 0 && y >= 0 && x < w.W && y < w.H; }
function tileAt(x, y) { return inMap(x, y) ? S.world.T[y][x] : -1; }
function levelAt(x, y) { return inMap(x, y) ? (S.world.L[y][x] || 0) : 0; }
function topY(x, y) { const k = tileAt(x, y); if (k < 0) return BASE_Y; if (WATERISH.has(k)) return BED_Y; return levelAt(x, y) * LH; }
function deckY(x, y) { return Math.max(0, levelAt(x, y) * LH) + 0.07; }
function standY(x, y) {
  const k = tileAt(x, y); if (k === 11 || k === 16) return deckY(x, y); if (k === 1) return WATER_Y; if (k < 0) return 0;
  return levelAt(x, y) * LH;
}
function standYAt(wx, wz) { return standY(Math.floor(wx), Math.floor(wz)); }
function regionAt(x, y) { const w = S.world; if (!w?.R || !inMap(x, y)) return ""; const i = w.R[y]?.[x]; return w.RN[i] || ""; }
function blocked(x, y) { const k = tileAt(x, y); return k < 0 || BLOCKING.has(k); }
function buildingAt(x, y) { const w = S.world; return w && inMap(x, y) ? w.B[y * w.W + x] : -1; }

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
    S.world = { W, H, T: snap.terrain, L: snap.height || snap.terrain.map((r) => r.map(() => 0)), R: snap.regions, RN: snap.region_names || [],
      places: snap.places || {}, buildings: snap.buildings || [], B };
    S.builtSeason = null;
  } else if (S.world) {
    S.world.places = snap.places || S.world.places; S.world.R = snap.regions || S.world.R; S.world.RN = snap.region_names || S.world.RN;
  }
  // entities: a full snapshot replaces the set
  const keep = new Map();
  for (const e of snap.ents || []) { const old = S.ents.get(e.id); keep.set(e.id, mergeEnt(old, e)); }
  S.ents = keep;
  for (const id of snap.removed || []) S.ents.delete(id);
  applyLive(snap, true);
  rebuildIfNeeded();
  makePlaceLabels();
  if (!S.firstFull) { S.firstFull = true; snapCamera(); }
}

function rebuildIfNeeded() {
  if (!S.world) return;
  const key = S.live.season + "|" + S.quality;
  if (S.builtSeason === key) return;
  S.builtSeason = key;
  buildStatic();
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
    case 7: case 8: case 9: { const b = w.buildings[buildingAt(x, y)]; c = b?.floor ? C(b.floor) : C("#a0754d"); break; }
    case 10: c = COL.soil; break;
    case 12: c = COL.plaza; break;
    case 13: c = COL.rock.clone().lerp(COL.rockDark, hash2(x, y, 5) * 0.5); break;
    case 14: c = COL.snow; break;
    case 15: c = shade(grass, 0.97); break;
    case 17: c = shade(grass, 0.86); break;
    case 18: c = COL.pineFloor.clone().lerp(grass, 0.3); break;
    case 19: c = COL.cave; break;
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
    } else if (k === 7) { // wooden floor planks
      for (let i = 0; i < 4; i++) {
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
  for (let y = 0; y < w.H; y++) for (let x = 0; x < w.W; x++) {
    const k = w.T[y][x], top = topY(x, y), r = rng(hashStr(x + ":" + y) ^ 0x5bd1e995), cx = x + 0.5, cz = y + 0.5;
    const reg = regionAt(x, y);
    if (k === 3) { // broadleaf tree
      const s = 0.85 + r() * 0.35, jx = cx + (r() - 0.5) * 0.25, jz = cz + (r() - 0.5) * 0.25, ry = r() * 6.28;
      const orchard = reg === "orchard";
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
      if (orchard && (sname === "summer" || sname === "autumn")) {
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
    } else if ((k === 0 || k === 15) && hi && r() < 0.32) { // decorative grass tufts
      const n = 1 + Math.floor(r() * 2);
      for (let i = 0; i < n; i++) { const px = x + 0.1 + r() * 0.8, pz = y + 0.1 + r() * 0.8, s = 0.7 + r() * 0.6;
        sc.tuft.add(px, pz, mat4(px, top, pz, s, s, s, r() * 6), vary(season.tuft, r(), 0.14)); }
    }
  }
  for (const s of Object.values(sc)) s.build(G);
}

// buildings, walls, fences, bridges, docks
function buildStructures(G) {
  const w = S.world, bd = new Builder(), glass = new Builder();
  // buildings
  w.buildings.forEach((b, bi) => {
    const wallC = C(b.wall || "#c9a27e"), roofC = C(b.roof || "#9c4a3a");
    const base = Math.max(levelAt(b.x0 + 1, b.y0 + 1), levelAt(b.door?.[0] ?? b.x0, b.door?.[1] ?? b.y0)) * LH;
    const T = 0.45, top = base + WALL_H;
    const door = b.door || [-1, -1];
    const sides = [
      { n: "n", fixed: b.y0, a0: b.x0, a1: b.x1, axis: "x", out: -1 },
      { n: "s", fixed: b.y1, a0: b.x0, a1: b.x1, axis: "x", out: 1 },
      { n: "w", fixed: b.x0, a0: b.y0, a1: b.y1, axis: "z", out: -1 },
      { n: "e", fixed: b.x1, a0: b.y0, a1: b.y1, axis: "z", out: 1 },
    ];
    const wallShade = (px, py) => 0.82 + 0.18 * smooth(base, base + 0.9, py);
    for (const sd of sides) {
      const doorOn = sd.axis === "x" ? (door[1] === sd.fixed && door[0] >= sd.a0 && door[0] <= sd.a1 ? door[0] : null)
                                     : (door[0] === sd.fixed && door[1] >= sd.a0 && door[1] <= sd.a1 ? door[1] : null);
      // wall slab segments (outer half of the border tiles)
      const segs = doorOn == null ? [[sd.a0, sd.a1 + 1]] : [[sd.a0, doorOn], [doorOn + 1, sd.a1 + 1]];
      const outerC = sd.out < 0 ? sd.fixed : sd.fixed + 1;          // outer face coordinate
      const mid = outerC - sd.out * T / 2;                        // slab centre across thickness
      const put = (a, b2, y0, y1, c, thick = T, outset = 0, fn) => {
        if (b2 - a <= 0.001) return;
        const along = (a + b2) / 2, len = b2 - a, cy = (y0 + y1) / 2, h = y1 - y0, m2 = mid + sd.out * outset / 2;
        if (sd.axis === "x") bd.box(along, cy, m2, len, h, thick + outset, c, 0, fn);
        else bd.box(m2, cy, along, thick + outset, h, len, c, 0, fn);
      };
      for (const [a, b2] of segs) {
        put(a, b2, base, base + 0.3, COL.stone, T, 0.06);
        put(a, b2, base + 0.3, top - 0.14, wallC, T, 0, wallShade);
        put(a, b2, top - 0.14, top, COL.timber, T, 0.05);
      }
      if (doorOn != null) {
        put(doorOn, doorOn + 1, base + 1.2, top - 0.14, wallC);
        put(doorOn, doorOn + 1, top - 0.14, top, COL.timber, T, 0.05);
        put(doorOn - 0.06, doorOn + 0.06, base, base + 1.2, COL.timber, T, 0.08);
        put(doorOn + 0.94, doorOn + 1.06, base, base + 1.2, COL.timber, T, 0.08);
        put(doorOn, doorOn + 1, base + 1.14, base + 1.24, COL.timber, T, 0.1);
        // open door leaf, swung inward
        const lx = sd.axis === "x" ? doorOn + 0.08 : outerC - sd.out * (T + 0.4), lz = sd.axis === "x" ? outerC - sd.out * (T + 0.4) : doorOn + 0.08;
        if (sd.axis === "x") bd.box(lx, base + 0.58, lz, 0.06, 1.12, 0.78, C("#7a4e2e")); else bd.box(lx, base + 0.58, lz, 0.78, 1.12, 0.06, C("#7a4e2e"));
        // step + lantern by the door
        const sx = sd.axis === "x" ? doorOn + 0.5 : outerC + sd.out * 0.25, sz = sd.axis === "x" ? outerC + sd.out * 0.25 : doorOn + 0.5;
        bd.box(sx, base + 0.04, sz, sd.axis === "x" ? 0.9 : 0.5, 0.08, sd.axis === "x" ? 0.5 : 0.9, COL.stone);
        const lpx = sd.axis === "x" ? doorOn + 1.22 : outerC + sd.out * 0.1, lpz = sd.axis === "x" ? outerC + sd.out * 0.1 : doorOn + 1.22;
        bd.box(lpx, base + 1.15, lpz, 0.12, 0.18, 0.12, COL.timber);
        glass.box(lpx, base + 1.15, lpz, 0.09, 0.13, 0.13, C("#ffcf7a"));
        S.doorLamps.push(new THREE.Vector3(lpx, base + 1.15, lpz));
      }
      // timber posts every other tile for a half-timbered look
      for (let a = sd.a0; a <= sd.a1 + 1; a += 2) {
        if (doorOn != null && a >= doorOn && a <= doorOn + 1) continue;
        put(a - 0.07, a + 0.07, base + 0.3, top - 0.14, COL.timber, T, 0.04);
      }
      // windows
      for (let a = sd.a0 + 1; a <= sd.a1 - 1; a++) {
        if (doorOn != null && Math.abs(a - doorOn) <= 1) continue;
        if ((a - sd.a0) % 2 !== 1) continue;
        const along = a + 0.5, wy = base + 1.0, f = outerC + sd.out * 0.03, fi = outerC - sd.out * (T + 0.01);
        const shut = roofC.clone().lerp(C("#ffffff"), 0.1);
        if (sd.axis === "x") {
          bd.box(along, wy, f, 0.6, 0.66, 0.05, COL.timber); glass.box(along, wy, f + sd.out * 0.02, 0.44, 0.5, 0.04, C("#ffd28a")); glass.box(along, wy, fi, 0.44, 0.5, 0.04, C("#ffd28a"));
          bd.box(along - 0.4, wy, f + sd.out * 0.01, 0.16, 0.62, 0.05, shut); bd.box(along + 0.4, wy, f + sd.out * 0.01, 0.16, 0.62, 0.05, shut);
          bd.box(along, wy - 0.38, f + sd.out * 0.04, 0.7, 0.06, 0.12, COL.timber);
          S.windowGlows.push(new THREE.Vector3(along, wy, f + sd.out * 0.3));
        } else {
          bd.box(f, wy, along, 0.05, 0.66, 0.6, COL.timber); glass.box(f + sd.out * 0.02, wy, along, 0.04, 0.5, 0.44, C("#ffd28a")); glass.box(fi, wy, along, 0.04, 0.5, 0.44, C("#ffd28a"));
          bd.box(f + sd.out * 0.01, wy, along - 0.4, 0.05, 0.62, 0.16, shut); bd.box(f + sd.out * 0.01, wy, along + 0.4, 0.05, 0.62, 0.16, shut);
          bd.box(f + sd.out * 0.04, wy - 0.38, along, 0.12, 0.06, 0.7, COL.timber);
          S.windowGlows.push(new THREE.Vector3(f + sd.out * 0.3, wy, along));
        }
      }
    }
    // corner posts
    for (const [cx, cz] of [[b.x0, b.y0], [b.x1 + 1, b.y0], [b.x0, b.y1 + 1], [b.x1 + 1, b.y1 + 1]]) {
      const ix = cx === b.x0 ? cx + 0.08 : cx - 0.08, iz = cz === b.y0 ? cz + 0.08 : cz - 0.08;
      bd.box(ix, base + WALL_H / 2, iz, 0.2, WALL_H, 0.2, COL.timber);
    }
    S.roofs.push(buildRoof(G, b, bi, top, wallC, roofC));
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
  if (glass.count) {
    S.glassMat = new THREE.MeshLambertMaterial({ vertexColors: true, emissive: 0xffa040, emissiveIntensity: 0 });
    S.glassMat.color.set(0x5b6f7f);
    const m = new THREE.Mesh(glass.build(), S.glassMat); m.userData.ownMat = true; m.name = "glass"; G.add(m);
  }
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
  if (r() < 0.75) { // chimney
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
  return { mesh: m, b, fade: 1 };
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
    uniforms: { uTime: U.time, uCenter: center, uColor: { value: C("#c9d6e6") }, uAlpha: { value: 0 } } });
  S.snowMat = new THREE.ShaderMaterial({ vertexShader: SNOW_VERT, fragmentShader: SNOW_FRAG, transparent: true, depthWrite: false,
    uniforms: { uTime: U.time, uCenter: center, uPR: { value: 1 }, uColor: { value: C("#ffffff") }, uAlpha: { value: 0 } } });
  S.rain = new THREE.LineSegments(mk(3000, 2), S.rainMat); S.rain.frustumCulled = false;
  S.snowP = new THREE.Points(mk(2400, 1), S.snowMat); S.snowP.frustumCulled = false;
  S.scene.add(S.rain, S.snowP);
  if (S.quality === "low") { S.rain.geometry.setDrawRange(0, 2400); S.snowP.geometry.setDrawRange(0, 900); }
  // embers for lit fires
  const ne = 8 * 22, seed = new Float32Array(ne * 4), r = rng(5);
  for (let i = 0; i < ne; i++) seed.set([r(), r(), r(), Math.floor(i / 22)], i * 4);
  const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(ne * 3), 3)); g.setAttribute("aSeed", new THREE.BufferAttribute(seed, 4));
  S.fireU = Array.from({ length: 8 }, () => new THREE.Vector4(0, -100, 0, 0));
  S.emberMat = new THREE.ShaderMaterial({ vertexShader: EMBER_VERT, fragmentShader: EMBER_FRAG, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    uniforms: { uTime: U.time, uPR: { value: 1 }, uFire: { value: S.fireU } } });
  S.embers = new THREE.Points(g, S.emberMat); S.embers.frustumCulled = false; S.scene.add(S.embers);
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
function makeFigure(name, color, role = "", isPlayer = false) {
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
  const mesh = (bd) => { const m = new THREE.Mesh(bd.build(), FIG_MAT); m.castShadow = true; return m; };
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
  return { group: g, parts, x: 0, z: 0, y: 0, heading: 0, walk: 0, moving: false, init: false };
}
function animateFigure(f, dt, speed, sleeping) {
  f.walk += dt * (speed > 0.05 ? 9 + speed * 1.5 : 0);
  const amp = speed > 0.05 ? Math.min(0.75, 0.3 + speed * 0.12) : 0;
  f.swing = lerp(f.swing || 0, amp, damp(10, dt));
  const s = Math.sin(f.walk) * f.swing;
  f.parts.legs[0].rotation.x = s; f.parts.legs[1].rotation.x = -s;
  f.parts.arms[0].rotation.x = -s * 0.8; f.parts.arms[1].rotation.x = s * 0.8;
  f.bob = Math.abs(Math.cos(f.walk)) * 0.04 * (f.swing / 0.75);
  f.group.rotation.x = sleeping ? lerp(f.group.rotation.x, 0, 0.1) : 0;
}

// ───────────────────────────────────────────────────────────── live state (deltas)
function mergeEnt(old, e) {
  const n = Object.assign(old ? Object.assign({}, old) : {}, e);
  if (!old) { const h = hashStr(String(e.id)); n.jx = ((h & 255) / 255 - 0.5) * 0.3; n.jz = (((h >> 8) & 255) / 255 - 0.5) * 0.3; n.phase = ((h >> 16) & 255) / 40; n.hop = 0; }
  return n;
}
function delta(snap) {
  if (!S.inited || !snap) return;
  for (const e of snap.ents || []) S.ents.set(e.id, mergeEnt(S.ents.get(e.id), e));
  for (const id of snap.removed || []) S.ents.delete(id);
  applyLive(snap, false);
  rebuildIfNeeded();
}
function applyLive(s, isFull) {
  const L = S.live;
  for (const k of ["tick", "day", "phase", "season", "weather", "time", "light", "sun", "temperature"]) if (s[k] !== undefined) L[k] = s[k];
  if (s.ada) S.adaData = Object.assign({}, S.adaData || {}, s.ada);
  if (s.people) {
    const seen = new Set();
    for (const p of s.people) {
      seen.add(p.name);
      let f = S.people.get(p.name);
      if (!f) { f = makeFigure(p.name, p.color, p.role); S.people.set(p.name, f); }
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
    night: 0, cloud: 0.5, cloudCol: 1, rain: 0, snowfall: 0, snow: 0, wind: 1, t: null };
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
    sunI: Pn("sunI") * (isDay ? wx.light : lerp(1, wx.light, 0.6)), hemI: Pn("hemI") * lerp(1, 1.05, wx.mix) * (L.weather === "rain" ? 0.8 : 1),
    sunDir: isDay ? dir : new THREE.Vector3(-dir.x * 0.6, Math.max(0.25, arc * 0.8), -0.45).normalize(),
    moonDir: isDay ? new THREE.Vector3(0, -1, 0) : new THREE.Vector3(Math.cos(ang), Math.max(0.12, arc * 0.85), -0.4).normalize(),
    stars: isDay ? 0 : smooth(0.05, 0.35, -e) * (L.weather === "clear" ? 1 : L.weather === "cloudy" ? 0.25 : 0),
    sunVis: isDay ? wx.sunVis * smooth(-0.05, 0.08, e + 0.06) : 0, moonVis: isDay ? 0 : (wx.sunVis * 0.8 + 0.2) * (L.weather === "rain" ? 0.1 : 1),
    night: isDay ? smooth(0.25, -0.05, e) * 0.6 : smooth(0, 0.25, -e) * 0.4 + 0.6,
    fogN: wx.fog[0], fogF: wx.fog[1], cloud: wx.cloud, cloudCol: wx.cloudCol,
    rain: L.weather === "rain" ? 1 : 0, snowfall: L.weather === "snow" ? 1 : 0,
    snow: Math.max(L.season === "winter" ? 0.75 : 0, L.weather === "snow" ? 1 : 0),
    wind: L.weather === "rain" ? 2.2 : L.weather === "snow" ? 1.4 : L.weather === "cloudy" ? 1.4 : 1,
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
  for (const k of ["sunI", "hemI", "stars", "sunVis", "moonVis", "night", "fogN", "fogF", "cloud", "cloudCol", "rain", "snowfall", "wind"]) E[k] = lerp(E[k], t[k], a);
  E.snow = lerp(E.snow, t.snow, slow);
  U.snow.value = E.snow; U.wind.value = E.wind;
  const sk = S.skyMat.uniforms;
  sk.uTop.value.copy(E.top); sk.uHor.value.copy(E.hor); sk.uBot.value.copy(E.bot); sk.uSunDir.value.copy(S.live.phase === "night" ? E.moonDir : E.sunDir);
  sk.uSunCol.value.copy(E.sun); sk.uStars.value = E.stars; sk.uSunVis.value = E.sunVis; sk.uMoonDir.value.copy(E.moonDir); sk.uMoonVis.value = E.moonVis;
  S.sun.color.copy(E.sun); S.sun.intensity = E.sunI;
  S.hemi.color.copy(E.hemS); S.hemi.groundColor.copy(E.hemG); S.hemi.intensity = E.hemI;
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
  if (S.glassMat) S.glassMat.emissiveIntensity = E.night * 2.2;
  S.renderer.toneMappingExposure = 1.0 + E.night * 0.25;
  // weather particles
  S.rainMat.uniforms.uAlpha.value = E.rain * 0.42; S.rain.visible = E.rain > 0.01;
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
  const speed = moveToward(sy, a.x + 0.5, a.y + 0.5, dt);
  const ground = standYAt(sy.x, sy.z);
  sy.groundY = lerp(sy.groundY ?? ground, ground, damp(10, dt));
  const sleeping = !!a.sleeping;
  sy.sleep = lerp(sy.sleep, sleeping ? 1 : 0, damp(3, dt));
  const bob = Math.sin(t * 2.1) * 0.06 * (1 - sy.sleep * 0.6);
  sy.y = sy.groundY + 0.52 - sy.sleep * 0.22 + bob;
  sy.group.position.set(sy.x, sy.y, sy.z);
  const target = speed > 0.2 ? Math.atan2(sy.dirX, sy.dirZ) : faceAngle(a.facing);
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
    const speed = moveToward(f, p.x + 0.5, p.y + 0.5, dt);
    const ground = standYAt(f.x, f.z); f.y = lerp(f.y || ground, ground, damp(10, dt));
    const target = speed > 0.2 ? Math.atan2(f.dirX, f.dirZ) : faceAngle(p.facing);
    f.heading = turnTo(f.heading, target, damp(10, dt));
    animateFigure(f, dt, speed, p.sleeping);
    f.group.position.set(f.x, f.y + (f.bob || 0), f.z); f.group.rotation.y = f.heading;
    if (p.sleeping) { f.group.rotation.z = lerp(f.group.rotation.z, Math.PI / 2 * 0.95, damp(4, dt)); f.group.position.y += 0.15; }
    else f.group.rotation.z = lerp(f.group.rotation.z, 0, damp(6, dt));
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

// entities, shadow blobs, glows, lights
function updateSprites(dt, t) {
  const E = S.entBB, B = S.blobBB, G = S.glowBB; E.begin(); B.begin(); G.begin();
  const lit = [];
  const fz = S.cam.target, cp = S.camera.position;
  for (const e of S.ents.values()) {
    const k = S.kinds[e.kind] || {}, size = k.size || "small", cell = kindCell(e.kind);
    const small = size === "small", creature = size === "creature";
    const tx = e.x + 0.5 + (small ? e.jx : 0), tz = e.y + 0.5 + (small ? e.jz : 0);
    if (e.px === undefined || Math.hypot(tx - e.px, tz - e.pz) > 4) { e.px = tx; e.pz = tz; }
    let moving = false;
    const dx = tx - e.px, dz = tz - e.pz, d = Math.hypot(dx, dz);
    if (d > 1e-3) { const st = Math.max(3.2, d * 4) * dt; if (st >= d) { e.px = tx; e.pz = tz; } else { e.px += dx / d * st; e.pz += dz / d * st; moving = true; } if (Math.abs(dx) > 0.02) e.flip = dx > 0; }
    let h = size === "big" ? 0.9 : creature ? 0.55 : 0.42;
    if (e.kind === "sprout" || e.growth !== undefined) h *= 0.35 + 0.65 * clamp((e.growth ?? 100) / 100, 0, 1);
    const tile = tileAt(Math.floor(e.px), Math.floor(e.pz));
    let y = standYAt(e.px, e.pz);
    if (moving) e.hop += dt * 13; else e.hop = 0;
    if (creature) {
      y += Math.abs(Math.sin(e.hop)) * 0.22;
      if (tile === 1) { y = WATER_Y - h * 0.45 + Math.pow(Math.max(0, Math.sin(t * 0.8 + e.phase * 3)), 12) * 0.7; } // fish leap
      else if (e.kind === "bird") y += 0.05 + Math.abs(Math.sin(t * 3 + e.phase)) * 0.06;
    } else if (small) y += 0.04 + Math.sin(t * 1.8 + e.phase) * 0.035;
    const w = h * cell.aspect;
    if (S.mode === "visit" && Math.hypot(e.px - cp.x, e.pz - cp.z) < (S.cam.fp ? 0.75 : 0.45) && cp.y < y + h + 0.6) continue; // don't fill the screen
    const glowing = e.lit === true || e.lit === 1;
    const em = glowing ? 2 : 1;
    const flip = creature && e.flip;
    E.push(e.px, y, e.pz, flip ? -w : w, h, cell.u, cell.v, cell.us, cell.vs, 1, 1, 1, em);
    if (tile !== 1) B.push(e.px, standYAt(e.px, e.pz) + 0.015, e.pz, w * 0.95, w * 0.6, 0, 0, 1, 1, 1, 1, 1, small ? 0.75 : 0.9);
    if (glowing || e.kind === "shrine") {
      const fire = e.kind === "fire pit" || e.kind === "campfire" || e.kind === "oven";
      const col = fire ? [1, 0.55, 0.2] : e.kind === "shrine" ? [0.7, 0.45, 1] : [1, 0.8, 0.45];
      const fl = fire ? 0.85 + Math.sin(t * 13 + e.phase) * 0.08 + Math.sin(t * 23.7) * 0.06 : 1;
      const gs = (fire ? 1.9 : 1.3) * fl * (0.6 + S.env.night * 0.5);
      G.push(e.px, y + h * 0.45, e.pz, gs, gs, 0, 0, 1, 1, col[0], col[1] * 0.85, col[2] * 0.7, (0.18 + S.env.night * 0.3) * (e.kind === "shrine" && !glowing ? 0.6 : 1));
      if (glowing) lit.push({ x: e.px, y: y + h * 0.6, z: e.pz, fire, col, fl, d: Math.hypot(e.px - fz.x, e.pz - fz.z) });
    }
  }
  // carried items float beside the synth / visitor
  const carry = (list, x, y, z, side) => (list || []).slice(0, 3).forEach((kind, i) => {
    const c = kindCell(kind), h = 0.3; E.push(x + side * 0.32 + i * 0.12, y + Math.sin(t * 2 + i) * 0.03, z, h * c.aspect, h, c.u, c.v, c.us, c.vs, 1, 1, 1, 1.4);
  });
  if (S.adaData && S.synth.group.visible) carry(S.adaData.carrying, S.synth.x, S.synth.y + 0.05, S.synth.z, 1);
  const vc = S.visitorData?.carrying;
  if (S.avatar?.group.visible && vc?.length) carry(vc, S.avatar.group.position.x, S.avatar.group.position.y + 0.55, S.avatar.group.position.z, 1);
  // blobs under characters
  if (S.synth.group.visible) B.push(S.synth.x, S.synth.groundY + 0.015, S.synth.z, 0.6, 0.6, 0, 0, 1, 1, 1, 1, 1, 0.6);
  for (const f of S.people.values()) if (f.group.visible) B.push(f.x, f.y + 0.015, f.z, 0.55, 0.55, 0, 0, 1, 1, 1, 1, 1, 0.75);
  if (S.avatar?.group.visible) B.push(S.avatar.group.position.x, (S.mode === "visit" ? S.local.y : S.avatar.y) + 0.015, S.avatar.group.position.z, 0.55, 0.55, 0, 0, 1, 1, 1, 1, 1, 0.75 * (1 - Math.min(S.local.hop, 0.5)));
  // synth halo
  if (S.synth.group.visible) { const s = 1.05 + S.env.night * 0.5 + Math.sin(t * 2.6) * 0.06; G.push(S.synth.x, S.synth.y, S.synth.z, s, s, 0, 0, 1, 1, 0.32, 0.45, 1, (0.2 + S.env.night * 0.22) * (1 - S.synth.sleep * 0.4)); }
  // windows + door lanterns at night
  const nt = S.env.night;
  if (nt > 0.05) {
    for (const p of S.windowGlows) G.push(p.x, p.y, p.z, 0.95, 0.85, 0, 0, 1, 1, 1, 0.68, 0.32, 0.3 * nt);
    for (const p of S.doorLamps) G.push(p.x, p.y, p.z, 1.0, 1.0, 0, 0, 1, 1, 1, 0.7, 0.35, 0.5 * nt);
  }
  E.end(); B.end(); G.end();
  // light pool: nearest lit things get real point lights
  lit.sort((a, b) => a.d - b.d);
  S.pool.forEach((l, i) => {
    const s = lit[i];
    if (!s) { l.intensity = 0; return; }
    l.position.set(s.x, s.y + 0.25, s.z); l.color.setRGB(s.col[0], s.col[1] * 0.9, s.col[2] * 0.8);
    l.intensity = (s.fire ? 5 : 3) * s.fl * (0.4 + S.env.night * 0.8); l.distance = s.fire ? 8 : 6;
  });
  // embers
  let fi = 0;
  for (const s of lit) { if (!s.fire || fi >= 8) continue; S.fireU[fi++].set(s.x, s.y - 0.15, s.z, 1); }
  for (; fi < 8; fi++) S.fireU[fi].w = 0;
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
  if (S.synth.group.visible && S.adaData) chars.push(["ada", S.adaData.name || "Zen", S.synth.group.position, 0.42, S.adaData.said, S.adaData.sleeping, true]);
  for (const [n, f] of S.people) if (f.group.visible) chars.push(["p:" + n, n, f.group.position, 1.12, f.data.said, f.data.sleeping, false]);
  if (S.avatar?.group.visible && S.mode !== "visit" && S.visitorData) chars.push(["you", S.visitorData.name || "you", S.avatar.group.position, 1.2, S.visitorData.said, false, false]);
  if (S.mode === "visit" && S.visitorData?.said && S.avatar) chars.push(["you", "", S.avatar.group.position, 1.2, S.visitorData.said, false, false]);
  const live = new Set(), bubbles = [];
  for (const [key, name, pos, hgt, said, sleeping, synth] of chars) {
    const p = tmpV2.copy(pos); p.y += hgt; const d = cam.distanceTo(p);
    if (name) {
      const l = label(key, "w3d-tag" + (synth ? " w3d-tag-synth" : "")); setText(l, name); live.add(key);
      placeLabel(l, p, synth ? Math.max(0.85 * fade(d, 40, 140), fade(d, 14, 34)) : fade(d, 14, 32) * (over ? 0 : 1));
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
    live.add(k); const o = smooth(28, 55, S.cam.dist);
    tmpV2.set(pl.x + 0.5, standY(pl.x, pl.y) + 1.6, pl.y + 0.5); placeLabel(pl.l, tmpV2, o);
  }
  for (const [k, l] of S.labels) if (!live.has(k)) { if (l.vis) { l.el.style.display = "none"; l.vis = false; } }
}
function makePlaceLabels() {
  for (const [, pl] of S.placeLabels || []) pl.l.el.remove();
  for (const [k] of S.placeLabels || []) S.labels.delete(k);
  S.placeLabels = new Map();
  for (const [name, xy] of Object.entries(S.world?.places || {})) {
    if (!Array.isArray(xy)) continue;
    const b = S.world.buildings.find((bb) => bb.name === name);
    const key = "place:" + name, l = label(key, "w3d-place"); setText(l, b?.label || name.replace(/_/g, " "));
    S.placeLabels.set(key, { l, x: xy[0], y: xy[1] });
  }
}

// ───────────────────────────────────────────────────────────── roofs cut-away
function updateRoofs(dt) {
  let px = null, pz = null, strong = false;
  if (S.mode === "visit") { px = S.local.x; pz = S.local.z; strong = true; }
  else if (S.cam.focus === "synth" && S.adaData && S.cam.dist < 30) { px = S.synth.x; pz = S.synth.z; }
  else if (S.cam.focus === "you" && S.avatar) { px = S.avatar.x; pz = S.avatar.z; }
  const cp = S.camera.position;
  for (const r of S.roofs) {
    const b = r.b, m = strong ? 0.6 : 0.05;
    const inside = px != null && px > b.x0 - m && px < b.x1 + 1 + m && pz > b.y0 - m && pz < b.y1 + 1 + m;
    const camIn = cp.x > b.x0 - 0.3 && cp.x < b.x1 + 1.3 && cp.z > b.y0 - 0.3 && cp.z < b.y1 + 1.3 && cp.y < standY(b.x0, b.y0) + WALL_H + 3;
    const target = inside || camIn ? 0 : 1;
    r.fade = lerp(r.fade, target, damp(6, dt));
    const mat = r.mesh.material;
    const tr = r.fade < 0.99;
    if (mat.transparent !== tr) { mat.transparent = tr; mat.depthWrite = !tr; mat.needsUpdate = true; }
    mat.opacity = r.fade; r.mesh.visible = r.fade > 0.03; r.mesh.castShadow = r.fade > 0.5;
  }
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
    const d = S.drag; if (!d) return;
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
  el.addEventListener("wheel", (e) => {
    e.preventDefault();
    const c = S.cam, f = Math.pow(1.0015, e.deltaY * (e.deltaMode === 1 ? 30 : 1));
    if (S.mode === "visit") { if (!c.fp) c.tDist = clamp(c.tDist * f, 1.8, 10); return; }
    c.tDist = clamp(c.tDist * f, 3, 170);
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
    const k = S.kinds[ent.kind] || {}; const h = k.size === "big" ? 0.9 : k.size === "creature" ? 0.55 : 0.42;
    test(new THREE.Vector3(ent.px ?? ent.x + 0.5, standY(ent.x, ent.y), ent.pz ?? ent.y + 0.5), h / 2, h * 0.7, { kind: "entity", id: ent.id, entKind: ent.kind });
  }
  if (!best) {
    const ray = new THREE.Raycaster(); ray.setFromCamera(new THREE.Vector2((mx / rect.width) * 2 - 1, -(my / rect.height) * 2 + 1), S.camera);
    const o = ray.ray.origin, d = ray.ray.direction;
    for (let s = 0; s < 400; s += 0.05) {
      const x = o.x + d.x * s, y = o.y + d.y * s, z = o.z + d.z * s, tx = Math.floor(x), tz = Math.floor(z);
      if (inMap(tx, tz) && y <= Math.max(topY(tx, tz), WATER_Y) + (tileAt(tx, tz) === 8 ? WALL_H : 0)) { best = { kind: "tile", x: tx, y: tz }; break; }
      if (y < BASE_Y) break;
    }
  }
  if (best) try { World3D.onPick?.(best); } catch (err) { console.error(err); }
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
  if (S.world) updateRoofs(dt);
  const pr = S.renderer.getPixelRatio();
  S.snowMat.uniforms.uPR.value = pr * (S.vh / 900); S.emberMat.uniforms.uPR.value = pr * (S.vh / 900); if (S.flyMat) S.flyMat.uniforms.uPR.value = pr * (S.vh / 900);
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
  S.rain.geometry.setDrawRange(0, q === "high" ? 6000 : 2400); S.snowP.geometry.setDrawRange(0, q === "high" ? 2400 : 900);
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
