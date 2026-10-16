// vox.js — the 3D voxel world: chunks streamed from /api/chunk and meshed in voxworker.js, a procedural
// texture array (blocks.js), sky with sun, moon, stars, clouds, fog, rain and snow, the inhabitant and the
// creatures, dropped items, and your body when you visit (pointer lock, WASD, dig, place, use).
//
// Coordinates are block units: block (x, y, z) fills [x, x+1) × [y, y+1) × [z, z+1); +y is up.
// Entities: x, y, z are the feet (centre of the bottom of the body). yaw/pitch in radians, Minecraft style:
// the facing direction is (-sin yaw · cos pitch, -sin pitch, cos yaw · cos pitch); yaw 0 faces +z, pitch > 0 looks down.
import * as THREE from "./vendor/three.module.min.js";
import { Reg, Tex, K, blockOf, findBlock, breakTime, workerTables, toolInfo, iconURL, normName } from "./blocks.js";

THREE.ColorManagement.enabled = false;

const clamp = (v, a, b) => (v < a ? a : v > b ? b : v);
const lerp = (a, b, t) => a + (b - a) * t;
const damp = (k, dt) => 1 - Math.exp(-k * dt);
const kk = (cx, cz) => cx + "," + cz;
const wrapAngle = (a) => { while (a > Math.PI) a -= 2 * Math.PI; while (a < -Math.PI) a += 2 * Math.PI; return a; };
function isTyping() { const a = document.activeElement; return !!a && (a.tagName === "INPUT" || a.tagName === "TEXTAREA" || a.tagName === "SELECT" || a.isContentEditable); }
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
function hash(a, b, c = 0) { let h = (Math.imul(a | 0, 374761393) + Math.imul(b | 0, 668265263) + Math.imul(c | 0, 982451653)) | 0; h = Math.imul(h ^ (h >>> 13), 1274126177); h ^= h >>> 16; return (h >>> 0) / 4294967296; }

/** Parse the world `time` into a fraction of the day (0 = midnight, 0.25 = sunrise, 0.5 = noon). */
export function dayFraction(t) {
  if (t == null) return 0.4;
  if (typeof t === "string") { const m = t.match(/(\d+):(\d+)/); return m ? ((+m[1] + +m[2] / 60) / 24) % 1 : 0.4; }
  if (t <= 1) return t;
  if (t <= 24) return t / 24;
  return (t % 24000) / 24000;
}

// ───────────────────────────────────────────── shaders
const CHUNK_VS = `
precision highp float;
attribute vec3 uvl; attribute vec4 lt;
uniform float uTime;
varying vec3 vUv; varying vec4 vLt; varying float vDist;
void main() {
  vec4 wp = modelMatrix * vec4(position, 1.0);
  float fl = floor(lt.w * 255.0 + 0.5);
  if (fl == 1.0 || fl == 2.0) {
    float k = fl == 1.0 ? 0.055 : 0.02;
    wp.x += sin(uTime * 1.7 + wp.z * 0.6 + wp.y * 0.3) * k;
    wp.z += cos(uTime * 1.3 + wp.x * 0.5) * k;
  }
  if (fl == 3.0 && fract(position.y) > 0.01) wp.y += sin(uTime * 1.6 + wp.x * 0.9 + wp.z * 0.7) * 0.025 - 0.03;
  vUv = uvl; vLt = lt;
  vec4 mv = viewMatrix * wp; vDist = length(mv.xyz);
  gl_Position = projectionMatrix * mv;
}`;
const CHUNK_FS = `
precision highp float; precision highp sampler2DArray;
uniform sampler2DArray uTex;
uniform float uDay, uTime, uAlphaTest, uOpacity, uFogNear, uFogFar, uFlash;
uniform vec3 uSkyTint, uFogColor;
varying vec3 vUv; varying vec4 vLt; varying float vDist;
void main() {
  float fl = floor(vLt.w * 255.0 + 0.5);
  vec2 uv = vUv.xy;
  if (fl == 3.0) uv += vec2(uTime * 0.035, uTime * 0.021) + 0.05 * vec2(sin(uTime + uv.y * 3.0), cos(uTime * 0.8 + uv.x * 3.0));
  if (fl == 4.0) uv += vec2(uTime * 0.012, -uTime * 0.009) + 0.06 * vec2(sin(uTime * 0.5 + uv.y * 2.0), 0.0);
  vec4 tex = texture(uTex, vec3(uv, vUv.z));
  if (tex.a < uAlphaTest) discard;
  float sky = vLt.y * (uDay + uFlash);
  vec3 light = max(vec3(sky) * uSkyTint, vec3(vLt.z) * vec3(1.0, 0.85, 0.62));
  light = pow(clamp(light, 0.0, 1.2), vec3(1.3)) * 0.95 + 0.045;
  vec3 col = tex.rgb * vLt.x * light;
  float a = tex.a;
  if (fl == 4.0) { col = tex.rgb * (1.05 + 0.1 * sin(uTime * 2.0 + uv.x * 6.0)); a = 1.0; }
  else if (uOpacity < 1.0) { a = fl == 3.0 ? uOpacity : max(uOpacity, tex.a * 0.85); }
  float f = smoothstep(uFogNear, uFogFar, vDist);
  gl_FragColor = vec4(mix(col, uFogColor, f), a);
}`;
const SKY_VS = `varying vec3 vDir; void main() { vDir = normalize(position); vec4 p = projectionMatrix * modelViewMatrix * vec4(position, 1.0); gl_Position = p.xyww; }`;
const SKY_FS = `
precision highp float;
uniform vec3 uTop, uHorizon, uSunDir, uSunGlow; uniform float uGlow;
varying vec3 vDir;
void main() {
  vec3 d = normalize(vDir);
  float h = clamp(d.y, -0.2, 1.0);
  vec3 col = mix(uHorizon, uTop, pow(max(h, 0.0), 0.55));
  if (d.y < 0.0) col = mix(uHorizon, uHorizon * 0.8, clamp(-d.y * 4.0, 0.0, 1.0));
  float s = max(dot(d, uSunDir), 0.0);
  col += uSunGlow * (pow(s, 6.0) * 0.45 + pow(s, 48.0) * 0.6) * uGlow * (1.0 - clamp(d.y, 0.0, 1.0) * 0.5);
  gl_FragColor = vec4(col, 1.0);
}`;

// ───────────────────────────────────────────── palettes for the sky
const SKY = {
  day: { top: [0.36, 0.58, 0.95], hor: [0.72, 0.84, 0.98] },
  dusk: { top: [0.25, 0.32, 0.6], hor: [0.98, 0.6, 0.36] },
  night: { top: [0.015, 0.025, 0.07], hor: [0.05, 0.08, 0.16] },
};
const mix3 = (a, b, t) => [lerp(a[0], b[0], t), lerp(a[1], b[1], t), lerp(a[2], b[2], t)];

// ───────────────────────────────────────────── creatures
const KINDS = {
  cow: { body: [0.9, 0.75, 1.3], bodyY: 0.95, head: [0.5, 0.5, 0.45], legs: 0.55, col: "#5a3b26", spot: "#f2efe8", headCol: "#5a3b26", snout: "#d9a7a0" },
  pig: { body: [0.8, 0.65, 1.1], bodyY: 0.68, head: [0.5, 0.5, 0.45], legs: 0.35, col: "#f0a2a6", headCol: "#f0a2a6", snout: "#e07e88" },
  sheep: { body: [0.85, 0.8, 1.15], bodyY: 0.9, head: [0.4, 0.42, 0.45], legs: 0.5, col: "#eeeae0", headCol: "#d8c8b4", snout: "#c9b49c", fluffy: true },
  wolf: { body: [0.5, 0.5, 1.0], bodyY: 0.7, head: [0.42, 0.4, 0.45], legs: 0.45, col: "#9a9690", headCol: "#a8a49e", snout: "#5a5652", ears: true, tail: true },
  bear: { body: [1.1, 0.95, 1.6], bodyY: 1.0, head: [0.6, 0.55, 0.55], legs: 0.55, col: "#4a3424", headCol: "#553c2a", snout: "#8a6a50", ears: true },
  rabbit: { body: [0.32, 0.3, 0.45], bodyY: 0.25, head: [0.26, 0.26, 0.26], legs: 0.12, col: "#a7836a", headCol: "#ae8b72", snout: "#f0c0c8", bunny: true },
  chicken: { biped: true, body: [0.4, 0.42, 0.5], bodyY: 0.5, head: [0.26, 0.34, 0.24], legs: 0.3, col: "#f7f5ee", headCol: "#f7f5ee", snout: "#f0b030", wattle: "#e0303a" },
  fish: { fish: true, col: "#f08a3a" },
  bee: { bee: true, col: "#f2c230" },
  slime: { slime: true, col: "#6fd06a" },
  hollow: { hollow: true, col: "#d8d6cc" },
  skeleton: { hollow: true, col: "#d8d6cc" },
};
const PEOPLE = {
  agent: { skin: "#f1c9a5", shirt: "#1fb3a4", pants: "#2c3a6b", hair: "#3a2a1f", shoes: "#2a2a2a", glow: "#7ff6ff" },
  you: { skin: "#e8b88f", shirt: "#f08a3c", pants: "#3d4a5c", hair: "#6b4528", shoes: "#3a3a3a" },
  other: { skin: "#d9a982", shirt: "#8a6af0", pants: "#33384a", hair: "#222", shoes: "#333" },
};

// ───────────────────────────────────────────── module state
const S = {
  inited: false, paused: false, mode: "watch", rd: 6, quality: "high",
  chunks: new Map(), tiles: new Map(), fetching: 0, maxFetch: 6, want: new Set(), lastCenter: null,
  ents: new Map(), agentId: null, agentName: "", agent: null, visitor: null,
  time: 0.4, day: 1, weather: "clear", daylight: 1, flash: 0, rainAmt: 0, snowAmt: 0, lightOverride: null,
  stats: { fps: 0, ms: 0, frames: 0, msAcc: 0, last: 0, frameMax: 0, meshMs: [], meshMax: 0, meshLast: 0, editLat: [], tris: 0, calls: 0 },
  editT0: new Map(),
  cam: { yaw: 0.6, pitch: 0.45, dist: 11, tYaw: 0.6, tPitch: 0.45, tDist: 11, target: new THREE.Vector3(0, 70, 0), fp: true, third: false },
  me: { pos: new THREE.Vector3(0, 80, 0), vel: new THREE.Vector3(), yaw: 0, pitch: 0, onGround: false, sneak: false, sprint: false, inWater: false, init: false, lastSend: 0, sentKey: "" },
  keys: new Set(), mouse: { left: false, right: false }, locked: false,
  hot: { slots: [], selected: 0, creative: false },
  dig: null, placeCD: 0, swing: 0, hit: null,
  cb: { command: null, select: null, key: null, status: null },
};

// ───────────────────────────────────────────── init
export async function createVox(container, opts = {}) {
  S.container = container; S.rd = clamp(opts.renderDistance || 6, 2, 12);
  Object.assign(S.cb, { command: opts.onCommand, select: opts.onSelect, key: opts.onKey, status: opts.onStatus });
  const canvas = document.createElement("canvas"); canvas.className = "vx-canvas"; canvas.tabIndex = 0;
  container.appendChild(canvas);
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: "high-performance", alpha: false });
  if (!renderer.capabilities.isWebGL2) throw new Error("WebGL 2 is needed for the 3D world");
  renderer.outputColorSpace = THREE.LinearSRGBColorSpace;
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, opts.dprCap || 1.5));
  S.renderer = renderer; S.canvas = canvas;
  const scene = new THREE.Scene(); S.scene = scene;
  const camera = new THREE.PerspectiveCamera(72, 1, 0.06, 1400); S.camera = camera; scene.add(camera);
  scene.fog = new THREE.Fog(0xb8d0f0, 60, 120);

  // texture array from the procedural atlas
  const tex = new THREE.DataArrayTexture(Tex.data, 16, 16, Tex.layers);
  tex.format = THREE.RGBAFormat; tex.type = THREE.UnsignedByteType;
  tex.magFilter = THREE.NearestFilter; tex.minFilter = THREE.NearestMipmapLinearFilter; tex.generateMipmaps = true;
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping; tex.needsUpdate = true;
  S.tex = tex;
  const U = S.U = {
    uTex: { value: tex }, uTime: { value: 0 }, uDay: { value: 1 }, uFlash: { value: 0 }, uSkyTint: { value: new THREE.Color(1, 1, 1) },
    uFogColor: { value: new THREE.Color(0.7, 0.8, 0.95) }, uFogNear: { value: 60 }, uFogFar: { value: 120 },
  };
  const mk = (alphaTest, opacity, extra) => new THREE.ShaderMaterial(Object.assign({
    vertexShader: CHUNK_VS, fragmentShader: CHUNK_FS,
    uniforms: { ...U, uAlphaTest: { value: alphaTest }, uOpacity: { value: opacity } },
  }, extra));
  S.mat = [
    mk(0.5, 1, {}),
    mk(0.5, 1, { side: THREE.DoubleSide }),
    mk(0.02, 0.74, { transparent: true, depthWrite: false, side: THREE.DoubleSide }),
  ];

  buildSky(); buildWeather(); buildOverlays(); buildLights();

  // the meshing worker
  S.worker = new Worker(new URL("./voxworker.js", import.meta.url));
  S.worker.onmessage = onWorker;
  S.worker.onerror = (e) => console.error("voxworker:", e.message || e);
  const wt = workerTables();
  S.worker.postMessage({ type: "init", tables: wt.tables, lut: wt.lut });

  // DOM overlays: labels, crosshair, hint, loading
  const layer = document.createElement("div"); layer.className = "vx-layer"; container.appendChild(layer); S.layer = layer;
  S.cross = div("vx-cross", container); S.cross.hidden = true;
  S.hint = div("vx-hint", container); S.hint.hidden = true;
  S.loading = div("vx-loading", container); S.loading.textContent = "Loading the world…";
  S.digBar = div("vx-digbar", container); S.digBar.hidden = true; S.digBar.innerHTML = "<i></i>";

  bindInput();
  new ResizeObserver(resize).observe(container); resize();
  document.addEventListener("visibilitychange", () => { if (!document.hidden && !S.paused) { S.lastFrame = performance.now(); if (S.raf == null) nextFrame(); } });
  S.inited = true; S.lastFrame = performance.now(); nextFrame();
  setInterval(updateChunks, 200);
  return API;
}
function div(cls, parent) { const d = document.createElement("div"); d.className = cls; parent.appendChild(d); return d; }
function resize() {
  const w = S.container.clientWidth, h = S.container.clientHeight; if (!w || !h) return;
  S.renderer.setSize(w, h, false); S.camera.aspect = w / h; S.camera.updateProjectionMatrix(); S.vw = w; S.vh = h;
}

// ───────────────────────────────────────────── sky, sun, moon, stars, clouds
function buildSky() {
  const g = new THREE.SphereGeometry(900, 32, 16);
  S.skyU = { uTop: { value: new THREE.Color() }, uHorizon: { value: new THREE.Color() }, uSunDir: { value: new THREE.Vector3(0, 1, 0) }, uSunGlow: { value: new THREE.Color(1, 0.75, 0.45) }, uGlow: { value: 1 } };
  const m = new THREE.ShaderMaterial({ vertexShader: SKY_VS, fragmentShader: SKY_FS, uniforms: S.skyU, side: THREE.BackSide, depthWrite: false, fog: false });
  S.sky = new THREE.Mesh(g, m); S.sky.renderOrder = -10; S.sky.frustumCulled = false; S.scene.add(S.sky);
  const sq = (col, size, drawFn) => {
    const c = document.createElement("canvas"); c.width = c.height = 32; const x = c.getContext("2d"); drawFn(x);
    const t = new THREE.CanvasTexture(c); t.magFilter = THREE.NearestFilter;
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(size, size), new THREE.MeshBasicMaterial({ map: t, transparent: true, fog: false, depthWrite: false, blending: THREE.AdditiveBlending }));
    mesh.renderOrder = -9; mesh.frustumCulled = false; S.scene.add(mesh); return mesh;
  };
  S.sun = sq("#fff", 90, (x) => { x.fillStyle = "rgba(255,200,90,.35)"; x.fillRect(0, 0, 32, 32); x.fillStyle = "#fff6d0"; x.fillRect(6, 6, 20, 20); x.fillStyle = "#fffef4"; x.fillRect(9, 9, 14, 14); });
  S.moon = sq("#fff", 60, (x) => { x.fillStyle = "#dfe6f5"; x.fillRect(4, 4, 24, 24); x.fillStyle = "#b8c2d8"; for (const [a, b, s] of [[9, 9, 5], [18, 14, 6], [11, 20, 4], [21, 7, 3]]) x.fillRect(a, b, s, s); });
  const N = 900, pos = new Float32Array(N * 3);
  for (let i = 0; i < N; i++) { const u = hash(i, 1) * 2 - 1, th = hash(i, 2) * Math.PI * 2, r = Math.sqrt(1 - u * u); pos.set([r * Math.cos(th) * 850, Math.abs(u) * 850, r * Math.sin(th) * 850], i * 3); }
  const sg = new THREE.BufferGeometry(); sg.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  S.stars = new THREE.Points(sg, new THREE.PointsMaterial({ color: 0xffffff, size: 2.2, sizeAttenuation: false, transparent: true, opacity: 0, fog: false, depthWrite: false }));
  S.stars.renderOrder = -9; S.stars.frustumCulled = false; S.scene.add(S.stars);
  // clouds: a blocky noise texture on a big plane that drifts
  const c = document.createElement("canvas"); c.width = c.height = 64; const x = c.getContext("2d"), im = x.createImageData(64, 64);
  for (let j = 0; j < 64; j++) for (let i = 0; i < 64; i++) {
    let v = 0, a = 1, f = 1 / 16, tot = 0;
    for (let o = 0; o < 3; o++) { v += a * smoothNoise(i * f, j * f, 64 * f, o + 3); tot += a; a *= 0.5; f *= 2; }
    v /= tot; const on = v > 0.52, k = (i + j * 64) * 4;
    im.data[k] = im.data[k + 1] = im.data[k + 2] = 255; im.data[k + 3] = on ? 230 : 0;
  }
  x.putImageData(im, 0, 0);
  const ct = new THREE.CanvasTexture(c); ct.magFilter = THREE.NearestFilter; ct.minFilter = THREE.NearestFilter; ct.wrapS = ct.wrapT = THREE.RepeatWrapping; ct.repeat.set(4, 4);
  S.clouds = new THREE.Mesh(new THREE.PlaneGeometry(3072, 3072), new THREE.MeshBasicMaterial({ map: ct, transparent: true, opacity: 0.85, depthWrite: false, side: THREE.DoubleSide, fog: false }));
  S.clouds.rotation.x = -Math.PI / 2; S.clouds.renderOrder = -5; S.clouds.frustumCulled = false; S.scene.add(S.clouds);
}
function smoothNoise(x, y, period, seed) {   // tileable value noise
  const xi = Math.floor(x), yi = Math.floor(y), xf = x - xi, yf = y - yi, u = xf * xf * (3 - 2 * xf), v = yf * yf * (3 - 2 * yf);
  const p = Math.round(period), h = (a, b) => hash(((a % p) + p) % p, ((b % p) + p) % p, seed);
  const a = h(xi, yi), b = h(xi + 1, yi), c = h(xi, yi + 1), d = h(xi + 1, yi + 1);
  return a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v;
}
function buildLights() {
  S.hemi = new THREE.HemisphereLight(0xdfeaff, 0x5a4a3a, 1.6); S.scene.add(S.hemi);
  S.sunLight = new THREE.DirectionalLight(0xfff2dd, 1.8); S.scene.add(S.sunLight); S.scene.add(S.sunLight.target);
}

// ───────────────────────────────────────────── weather particles
function buildWeather() {
  const N = 1400, pos = new Float32Array(N * 6), seed = new Float32Array(N * 3);
  for (let i = 0; i < N; i++) { seed[i * 3] = hash(i, 7) * 48 - 24; seed[i * 3 + 1] = hash(i, 8) * 34; seed[i * 3 + 2] = hash(i, 9) * 48 - 24; }
  const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  S.rain = new THREE.LineSegments(g, new THREE.LineBasicMaterial({ color: 0xa8c0e0, transparent: true, opacity: 0.5, depthWrite: false }));
  S.rain.frustumCulled = false; S.rain.visible = false; S.scene.add(S.rain); S.rainSeed = seed;
  const M = 1200, sp = new Float32Array(M * 3), ss = new Float32Array(M * 3);
  for (let i = 0; i < M; i++) { ss[i * 3] = hash(i, 17) * 48 - 24; ss[i * 3 + 1] = hash(i, 18) * 30; ss[i * 3 + 2] = hash(i, 19) * 48 - 24; }
  const sg = new THREE.BufferGeometry(); sg.setAttribute("position", new THREE.BufferAttribute(sp, 3));
  S.snow = new THREE.Points(sg, new THREE.PointsMaterial({ color: 0xffffff, size: 0.13, transparent: true, opacity: 0.9, depthWrite: false }));
  S.snow.frustumCulled = false; S.snow.visible = false; S.scene.add(S.snow); S.snowSeed = ss;
}
function updateWeather(dt, t) {
  const cam = S.camera.position, raining = S.rainAmt > 0.02, snowing = S.snowAmt > 0.02;
  S.rain.visible = raining; S.snow.visible = snowing;
  if (raining) {
    const p = S.rain.geometry.attributes.position.array, sd = S.rainSeed, n = Math.floor((sd.length / 3) * S.rainAmt);
    for (let i = 0; i < sd.length / 3; i++) {
      const o = i * 6;
      if (i >= n) { p[o + 1] = p[o + 4] = -999; continue; }
      const x = Math.floor(cam.x) + sd[i * 3], z = Math.floor(cam.z) + sd[i * 3 + 2];
      let y = cam.y + 18 - ((sd[i * 3 + 1] + t * 24) % 34);
      const ground = surfaceY(Math.floor(x), Math.floor(z));
      if (y < ground) y = -999;
      p[o] = x + 0.5; p[o + 1] = y; p[o + 2] = z + 0.5; p[o + 3] = x + 0.5 - 0.05; p[o + 4] = y + 0.7; p[o + 5] = z + 0.5;
    }
    S.rain.geometry.attributes.position.needsUpdate = true;
    S.rain.material.color.setRGB(0.55 + 0.25 * S.daylight, 0.62 + 0.25 * S.daylight, 0.75 + 0.2 * S.daylight);
  }
  if (snowing) {
    const p = S.snow.geometry.attributes.position.array, sd = S.snowSeed, n = Math.floor((sd.length / 3) * S.snowAmt);
    for (let i = 0; i < sd.length / 3; i++) {
      const o = i * 3; if (i >= n) { p[o + 1] = -999; continue; }
      const x = cam.x + sd[o] + Math.sin(t * 0.7 + i) * 0.6, z = cam.z + sd[o + 2] + Math.cos(t * 0.5 + i * 1.3) * 0.6;
      let y = cam.y + 16 - ((sd[o + 1] + t * 2.2) % 30);
      if (y < surfaceY(Math.floor(x), Math.floor(z))) y = -999;
      p[o] = x; p[o + 1] = y; p[o + 2] = z;
    }
    S.snow.geometry.attributes.position.needsUpdate = true;
  }
}

// ───────────────────────────────────────────── environment (time of day, weather)
function updateEnv(dt) {
  const t = S.time, ang = (t - 0.25) * Math.PI * 2, elev = Math.sin(ang);
  const sunDir = new THREE.Vector3(Math.cos(ang), Math.sin(ang), 0.25).normalize();
  let day = clamp((elev + 0.12) / 0.4, 0, 1); day = day * day * (3 - 2 * day);
  const wantRain = /rain|storm|thunder/.test(S.weather) ? 1 : 0, wantSnow = /snow/.test(S.weather) ? 1 : 0;
  S.rainAmt = lerp(S.rainAmt, wantRain, damp(0.8, dt)); S.snowAmt = lerp(S.snowAmt, wantSnow, damp(0.8, dt));
  const gloom = Math.max(S.rainAmt, S.snowAmt * 0.6, /cloud|overcast|fog/.test(S.weather) ? 0.45 : 0);
  let daylight = lerp(0.1, 1, day) * (1 - gloom * 0.35);
  if (S.lightOverride != null) daylight = lerp(daylight, S.lightOverride, 0.5);
  S.daylight = daylight;
  // sky colours
  const duskK = clamp(1 - Math.abs(elev) / 0.32, 0, 1) * (elev > -0.25 ? 1 : 0);
  let top = mix3(SKY.night.top, SKY.day.top, day), hor = mix3(SKY.night.hor, SKY.day.hor, day);
  top = mix3(top, SKY.dusk.top, duskK * 0.5); hor = mix3(hor, SKY.dusk.hor, duskK * 0.75);
  const grey = (c, k, lvl) => mix3(c, [lvl, lvl, lvl * 1.05], k);
  top = grey(top, gloom * 0.7, 0.45 * day + 0.04); hor = grey(hor, gloom * 0.7, 0.55 * day + 0.06);
  if (S.flash > 0) { top = mix3(top, [0.9, 0.92, 1], S.flash); hor = mix3(hor, [0.9, 0.92, 1], S.flash); }
  S.skyU.uTop.value.setRGB(...top); S.skyU.uHorizon.value.setRGB(...hor); S.skyU.uSunDir.value.copy(sunDir);
  S.skyU.uGlow.value = clamp(elev + 0.3, 0, 1) * (1 - gloom * 0.8);
  S.skyU.uSunGlow.value.setRGB(1, lerp(0.55, 0.85, day), lerp(0.3, 0.7, day));
  // fog
  const U = S.U, far = S.rd * 16 * (1 - gloom * 0.35), under = S.underwater;
  U.uFogColor.value.setRGB(...(under ? [0.08, 0.2, 0.42 * (0.3 + daylight)] : hor));
  U.uFogNear.value = under ? 1 : far * 0.55; U.uFogFar.value = under ? 18 : far * 0.97;
  S.scene.fog.color.copy(U.uFogColor.value); S.scene.fog.near = U.uFogNear.value; S.scene.fog.far = U.uFogFar.value;
  U.uDay.value = daylight; U.uFlash.value = S.flash;
  U.uSkyTint.value.setRGB(...mix3(mix3([0.55, 0.62, 0.95], [1, 1, 1], day), [1.0, 0.82, 0.68], duskK * 0.6));
  // sun, moon, stars, clouds follow the camera
  const cp = S.camera.position;
  S.sky.position.copy(cp);
  S.sun.position.copy(cp).addScaledVector(sunDir, 700); S.sun.lookAt(cp); S.sun.visible = elev > -0.15;
  S.sun.material.opacity = clamp((elev + 0.15) * 4, 0, 1) * (1 - gloom * 0.85);
  S.moon.position.copy(cp).addScaledVector(sunDir, -700); S.moon.lookAt(cp); S.moon.visible = elev < 0.15;
  S.moon.material.opacity = clamp((0.15 - elev) * 4, 0, 1) * (1 - gloom * 0.85);
  S.stars.position.copy(cp); S.stars.material.opacity = clamp(-elev * 3, 0, 1) * (1 - gloom);
  S.stars.rotation.z = ang * 0.1;
  S.clouds.position.set(cp.x, 192, cp.z);
  const ct = S.clouds.material.map; ct.offset.set((cp.x + U.uTime.value * 1.2) / 768, -(cp.z) / 768);
  const cl = lerp(0.12, 1, day) * (1 - gloom * 0.4);
  S.clouds.material.color.setRGB(cl, cl, cl * 1.02 + 0.02); S.clouds.material.opacity = lerp(0.8, 0.95, gloom);
  // lights for entities
  S.hemi.intensity = lerp(0.35, 1.9, daylight); S.sunLight.intensity = lerp(0.1, 1.9, day) * (1 - gloom * 0.5);
  S.sunLight.position.copy(cp).addScaledVector(elev > 0 ? sunDir : sunDir.clone().negate(), 50); S.sunLight.target.position.copy(cp);
  // thunder
  if (/thunder|storm/.test(S.weather) && Math.random() < dt / 9) S.flash = 0.8;
  S.flash = Math.max(0, S.flash - dt * 3);
  S.renderer.setClearColor(new THREE.Color(...hor));
}

// ───────────────────────────────────────────── chunks
function wantedCenter() {
  if (S.mode === "visit" && S.me.init) return [S.me.pos.x, S.me.pos.z];
  return [S.cam.target.x, S.cam.target.z];
}
function updateChunks() {
  if (!S.inited || !Reg.ready) return;
  const [x, z] = wantedCenter(), ccx = Math.floor(x / 16), ccz = Math.floor(z / 16), r = S.rd;
  const sig = `${ccx},${ccz},${r}`;
  if (sig !== S.lastCenter) {
    S.lastCenter = sig; S.worker.postMessage({ type: "center", x, z });
    const want = new Set(), list = [];
    for (let dz = -r; dz <= r; dz++) for (let dx = -r; dx <= r; dx++) if (dx * dx + dz * dz <= r * r + 1) { const key = kk(ccx + dx, ccz + dz); want.add(key); list.push([dx * dx + dz * dz, ccx + dx, ccz + dz, key]); }
    list.sort((a, b) => a[0] - b[0]); S.want = want; S.wantList = list;
    // unload what is far away
    const drop = [];
    for (const [key, c] of S.chunks) {
      if ((c.cx - ccx) ** 2 + (c.cz - ccz) ** 2 > (r + 2) ** 2) { disposeChunk(c); S.chunks.delete(key); drop.push(key); }
    }
    if (drop.length) S.worker.postMessage({ type: "unload", keys: drop });
    // a neighbour that left the wanted set may make a chunk meshable now
    for (const c of S.chunks.values()) if (c.data && !c.meshReq) tryMesh(c);
  }
  for (const [, cx, cz, key] of S.wantList || []) {
    if (S.fetching >= S.maxFetch) break;
    let c = S.chunks.get(key);
    if (!c) { c = { key, cx, cz, data: null, meshes: [], state: "new", fails: 0, retryAt: 0, edits: [] }; S.chunks.set(key, c); }
    if (c.state === "new" || (c.state === "failed" && performance.now() > c.retryAt)) fetchChunk(c);
  }
}
async function fetchChunk(c) {
  c.state = "loading"; S.fetching++;
  try {
    const r = await fetch(`/api/chunk?cx=${c.cx}&cz=${c.cz}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const buf = await r.arrayBuffer();
    if (!S.chunks.has(c.key)) return;
    S.worker.postMessage({ type: "chunk", key: c.key, cx: c.cx, cz: c.cz, buf }, [buf]);
  } catch (e) {
    c.state = "failed"; c.fails++; c.retryAt = performance.now() + Math.min(15000, 1500 * c.fails);
    if (c.fails === 1) console.warn(`chunk ${c.key}: ${e.message}`);
  } finally { S.fetching--; }
}
function onWorker(ev) {
  const m = ev.data;
  if (m.type === "data") {
    const c = S.chunks.get(m.key); if (!c) return;
    c.data = m.blocks; c.hmap = m.hmap; c.top = m.top; c.depth = m.depth; c.maxY = m.maxY; c.state = "ready";
    if (c.edits.length) { const list = c.edits; c.edits = []; applyEditsLocal(list, true); }
    drawTile(c);
    for (let dz = -1; dz <= 1; dz++) for (let dx = -1; dx <= 1; dx++) { const n = S.chunks.get(kk(c.cx + dx, c.cz + dz)); if (n && n.data) tryMesh(n); }
    if (S.loading && !S.loading.hidden && S.chunks.size) S.loading.hidden = true;
  } else if (m.type === "mesh") {
    const c = S.chunks.get(m.key); if (!c) return;
    setMeshes(c, m.parts);
    const st = S.stats; st.meshMs.push(m.ms); if (st.meshMs.length > 200) st.meshMs.shift(); st.meshMax = Math.max(st.meshMax, m.ms); st.meshLast = m.ms;
    if (m.why === "edit" && S.editT0.has(m.key)) { st.editLat.push({ t0: S.editT0.get(m.key), meshed: performance.now() }); S.editT0.delete(m.key); if (st.editLat.length > 50) st.editLat.shift(); S.pendingLat = true; }
  } else if (m.type === "error") {
    const c = S.chunks.get(m.key); if (c) { c.state = "failed"; c.fails++; c.retryAt = performance.now() + 3000; }
    console.warn(m.msg);
  } else if (m.type === "bench") { S.benchCb?.(m.times); }
}
function tryMesh(c) {
  if (!c.data) return;
  let missing = 0;
  for (let dz = -1; dz <= 1; dz++) for (let dx = -1; dx <= 1; dx++) {
    if (!dx && !dz) continue;
    const key = kk(c.cx + dx, c.cz + dz), n = S.chunks.get(key);
    if (n?.data) continue;
    if (S.want.has(key) && n?.state !== "failed") { if (dx === 0 || dz === 0) return; missing++; } else missing++;
  }
  if (c.meshReq && (c.missing || 0) <= missing) return;
  c.meshReq = true; c.missing = missing;
  S.worker.postMessage({ type: "mesh", keys: [c.key] });
}
function setMeshes(c, parts) {
  for (const m of c.meshes) { S.scene.remove(m); m.geometry.dispose(); }
  c.meshes = [];
  parts.forEach((p, i) => {
    if (!p) return;
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(p.pos, 3));
    g.setAttribute("uvl", new THREE.BufferAttribute(p.uvl, 3));
    g.setAttribute("lt", new THREE.BufferAttribute(p.lt, 4, true));
    g.setIndex(new THREE.BufferAttribute(p.idx, 1));
    g.boundingSphere = new THREE.Sphere(new THREE.Vector3(8, (c.maxY || 64) / 2, 8), Math.hypot(12, (c.maxY || 64) / 2 + 2));
    const mesh = new THREE.Mesh(g, S.mat[i]); mesh.position.set(c.cx * 16, 0, c.cz * 16); mesh.matrixAutoUpdate = false; mesh.updateMatrix();
    mesh.renderOrder = i === 2 ? 2 : 0;
    S.scene.add(mesh); c.meshes.push(mesh);
  });
}
function disposeChunk(c) { for (const m of c.meshes) { S.scene.remove(m); m.geometry.dispose(); } c.meshes = []; }

// voxel access on the main thread (collisions, ray casts, the minimap)
function rawAt(x, y, z) {
  if (y < 0) return -1; if (y > 255) return 0;
  const cx = Math.floor(x / 16), cz = Math.floor(z / 16), c = S.chunks.get(kk(cx, cz));
  if (!c || !c.data) return -1;
  return c.data[(x - cx * 16) + ((z - cz * 16) << 4) + (y << 8)];
}
function blockAtXYZ(x, y, z) { const v = rawAt(x, y, z); return v <= 0 ? null : blockOf(v); }
function surfaceY(x, z) {
  const cx = Math.floor(x / 16), cz = Math.floor(z / 16), c = S.chunks.get(kk(cx, cz));
  if (!c || !c.hmap) return -1e9;
  const col = (x - cx * 16) + ((z - cz * 16) << 4), id = c.top[col], b = Reg.byId.get(id);
  return c.hmap[col] + 1 - (b && b.kind === K.LIQUID ? 0.15 : 0);
}
function applyEditsLocal(list, fromPending) {
  const send = [];
  for (const e of list) {
    const [x, y, z, v] = e; if (y < 0 || y > 255) continue;
    const cx = Math.floor(x / 16), cz = Math.floor(z / 16), key = kk(cx, cz), c = S.chunks.get(key);
    if (!c) continue;
    if (!c.data) { if (!fromPending) c.edits.push(e); continue; }
    const lx = x - cx * 16, lz = z - cz * 16, i = lx + (lz << 4) + (y << 8);
    if (c.data[i] === v) continue;
    c.data[i] = v; send.push(e);
    if (!S.editT0.has(key)) S.editT0.set(key, performance.now());
    // column top for the minimap and the rain
    const col = lx + (lz << 4);
    if (y >= c.hmap[col] - 1) { recolumn(c, col); c.tileDirty = true; }
    if (y > (c.maxY || 0)) c.maxY = y;
  }
  if (send.length) S.worker.postMessage({ type: "edits", list: send });
  for (const c of S.chunks.values()) if (c.tileDirty) { c.tileDirty = false; drawTile(c); }
}
function recolumn(c, col) {
  let y = 255; for (; y >= 0; y--) { const v = c.data[col + (y << 8)]; if (v && blockOf(v)?.kind) break; }
  if (y < 0) { c.hmap[col] = 0; c.top[col] = 0; c.depth[col] = 0; return; }
  const b = blockOf(c.data[col + (y << 8)]); c.hmap[col] = y; c.top[col] = b ? b.id : 0;
  let d = 0; if (b && b.kind === K.LIQUID) { let yy = y; while (yy > 0 && blockOf(c.data[col + (yy << 8)])?.kind === K.LIQUID) { yy--; d++; } }
  c.depth[col] = d;
}
// a 16×16 picture of the chunk seen from above, for the minimap and the Map tab
function drawTile(c) {
  if (!c.hmap) return;
  let t = S.tiles.get(c.key);
  if (!t) { const cv = document.createElement("canvas"); cv.width = cv.height = 16; t = { cx: c.cx, cz: c.cz, canvas: cv, g: cv.getContext("2d"), seen: Date.now() }; S.tiles.set(c.key, t); }
  const im = t.g.createImageData(16, 16);
  for (let z = 0; z < 16; z++) for (let x = 0; x < 16; x++) {
    const col = x + (z << 4), b = Reg.byId.get(c.top[col]), h = c.hmap[col];
    let rgb = b ? b.top : [0, 0, 0];
    const hn = z > 0 ? c.hmap[col - 16] : h, hw = x > 0 ? c.hmap[col - 1] : h;
    let f = 1 + clamp((h - hn) * 0.07 + (h - hw) * 0.05, -0.25, 0.25);
    if (b && b.kind === K.LIQUID) f = b.isLava ? 1 : clamp(1.05 - c.depth[col] * 0.06, 0.55, 1.05);
    f *= 0.9 + clamp((h - 64) / 160, -0.15, 0.2);
    const k = col * 4; im.data[k] = clamp(rgb[0] * f, 0, 255); im.data[k + 1] = clamp(rgb[1] * f, 0, 255); im.data[k + 2] = clamp(rgb[2] * f, 0, 255); im.data[k + 3] = b ? 255 : 0;
  }
  t.g.putImageData(im, 0, 0); t.ver = (t.ver || 0) + 1; S.tilesVer = (S.tilesVer || 0) + 1;
}

// ───────────────────────────────────────────── block geometry for items, held blocks and the hand
const blockGeoCache = new Map();
function blockGeometry(id) {
  if (blockGeoCache.has(id)) return blockGeoCache.get(id);
  const b = Reg.byId.get(id), L = Tex.layerOf.get(id) || [0, 0, 0];
  const pos = [], uvl = [], lt = [], idx = [];
  const quad = (pts, layer, shade) => {
    const base = pos.length / 3;
    pts.forEach(([x, y, z, u, v]) => { pos.push(x - 0.5, y, z - 0.5); uvl.push(u, v, layer); lt.push(255 * shade, 255, 0, 0); });
    idx.push(base, base + 1, base + 2, base, base + 2, base + 3);
  };
  if (b && (b.kind === K.CROSS || b.kind === K.TORCH)) {
    quad([[0, 0, 0.5, 0, 0], [1, 0, 0.5, 1, 0], [1, 1, 0.5, 1, 1], [0, 1, 0.5, 0, 1]], L[1], 1);
    quad([[0.5, 0, 1, 0, 0], [0.5, 0, 0, 1, 0], [0.5, 1, 0, 1, 1], [0.5, 1, 1, 0, 1]], L[1], 1);
  } else {
    const h = b ? b.h : 1;
    quad([[0, h, 1, 0, 0], [1, h, 1, 1, 0], [1, h, 0, 1, 1], [0, h, 0, 0, 1]], L[0], 1);
    quad([[0, 0, 0, 0, 0], [1, 0, 0, 1, 0], [1, 0, 1, 1, 1], [0, 0, 1, 0, 1]], L[2], 0.55);
    quad([[1, 0, 1, 0, 0], [1, 0, 0, 1, 0], [1, h, 0, 1, h], [1, h, 1, 0, h]], L[1], 0.76);
    quad([[0, 0, 0, 0, 0], [0, 0, 1, 1, 0], [0, h, 1, 1, h], [0, h, 0, 0, h]], L[1], 0.76);
    quad([[0, 0, 1, 0, 0], [1, 0, 1, 1, 0], [1, h, 1, 1, h], [0, h, 1, 0, h]], L[1], 0.88);
    quad([[1, 0, 0, 0, 0], [0, 0, 0, 1, 0], [0, h, 0, 1, h], [1, h, 0, 0, h]], L[1], 0.88);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute("uvl", new THREE.Float32BufferAttribute(uvl, 3));
  g.setAttribute("lt", new THREE.BufferAttribute(new Uint8Array(lt), 4, true));
  g.setIndex(idx); g.computeBoundingSphere();
  blockGeoCache.set(id, g); return g;
}
const iconTexCache = new Map();
function iconTexture(ref) {
  const key = normName(typeof ref === "object" ? ref.item ?? ref.name : ref);
  if (iconTexCache.has(key)) return iconTexCache.get(key);
  const img = new Image(); img.src = iconURL(ref, 64);
  const t = new THREE.Texture(img); img.onload = () => { t.needsUpdate = true; }; t.magFilter = THREE.NearestFilter;
  iconTexCache.set(key, t); return t;
}
const TOOLCOL = { wood: 0xa07848, stone: 0x8a8a8a, iron: 0xdcdcdc, gold: 0xf2cf4a, diamond: 0x5fe0d6 };
/** A small 3D object for an item: a block, a tool, or a flat icon. Size is the block edge. */
function itemObject(ref, size = 0.25) {
  const b = findBlock(ref);
  const o = new THREE.Group();
  if (b && b.kind !== K.AIR) {
    const m = new THREE.Mesh(blockGeometry(b.id), S.mat[1]); m.scale.setScalar(size); m.position.y = -size / 2; o.add(m); o.userData.block = b.id;
  } else {
    const t = toolInfo(typeof ref === "object" ? ref.item ?? ref.name : ref);
    if (t) {
      const handle = new THREE.Mesh(new THREE.BoxGeometry(size * 0.14, size * 1.6, size * 0.14), new THREE.MeshLambertMaterial({ color: 0x6b4a2a }));
      const hm = new THREE.MeshLambertMaterial({ color: TOOLCOL[t.material] || 0xaaaaaa });
      const head = t.kind === "pickaxe" ? new THREE.Mesh(new THREE.BoxGeometry(size * 1.2, size * 0.18, size * 0.18), hm)
        : t.kind === "sword" ? new THREE.Mesh(new THREE.BoxGeometry(size * 0.2, size * 1.4, size * 0.08), hm)
        : new THREE.Mesh(new THREE.BoxGeometry(size * 0.5, size * 0.42, size * 0.12), hm);
      head.position.y = t.kind === "sword" ? size * 1.2 : size * 0.7; if (t.kind === "axe" || t.kind === "hoe") head.position.x = size * 0.22;
      o.add(handle, head);
    } else {
      const m = new THREE.Mesh(new THREE.PlaneGeometry(size * 1.4, size * 1.4), new THREE.MeshBasicMaterial({ map: iconTexture(ref), transparent: true, alphaTest: 0.3, side: THREE.DoubleSide }));
      o.add(m);
    }
  }
  return o;
}

// ───────────────────────────────────────────── figures
const matCache = new Map();
function lam(col) { if (!matCache.has(col)) matCache.set(col, new THREE.MeshLambertMaterial({ color: col })); return matCache.get(col); }
function boxMesh(w, h, d, col, y0 = 0) { const g = new THREE.BoxGeometry(w, h, d); g.translate(0, y0, 0); return new THREE.Mesh(g, Array.isArray(col) ? col : lam(col)); }
function faceTexture(skin, hair, eye = "#1d2433", glow) {
  const c = document.createElement("canvas"); c.width = c.height = 16; const g = c.getContext("2d");
  g.fillStyle = skin; g.fillRect(0, 0, 16, 16); g.fillStyle = hair; g.fillRect(0, 0, 16, 4); g.fillRect(0, 4, 2, 3); g.fillRect(14, 4, 2, 3);
  g.fillStyle = "#fff"; g.fillRect(3, 8, 3, 2); g.fillRect(10, 8, 3, 2);
  g.fillStyle = glow || eye; g.fillRect(4, 8, 2, 2); g.fillRect(10, 8, 2, 2);
  g.fillStyle = "rgba(200,90,90,.55)"; g.fillRect(2, 11, 2, 1); g.fillRect(12, 11, 2, 1);
  g.fillStyle = "#8a4a3a"; g.fillRect(6, 12, 4, 1);
  const t = new THREE.CanvasTexture(c); t.magFilter = THREE.NearestFilter; return t;
}
function humanoid(pal, opts = {}) {
  const root = new THREE.Group(), body = new THREE.Group(); root.add(body);
  const skin = lam(pal.skin), hairM = lam(pal.hair);
  const headMats = [skin, skin, hairM, skin, new THREE.MeshLambertMaterial({ map: faceTexture(pal.skin, pal.hair, "#1d2433", pal.glow ? "#0d6f7a" : null) }), hairM];
  const head = new THREE.Group(); head.position.y = 1.38; body.add(head);
  head.add(boxMesh(0.44, 0.44, 0.44, headMats, 0.22));
  if (opts.thin) head.children[0].material = [lam(pal.shirt), lam(pal.shirt), lam(pal.shirt), lam(pal.shirt), new THREE.MeshLambertMaterial({ map: hollowFace() }), lam(pal.shirt)];
  const torso = boxMesh(opts.thin ? 0.36 : 0.48, 0.66, opts.thin ? 0.18 : 0.26, pal.shirt, 0.33); torso.position.y = 0.72; body.add(torso);
  const limb = (w, h, col, x, y) => { const g = new THREE.Group(); g.position.set(x, y, 0); g.add(boxMesh(w, h, w, col, -h / 2)); body.add(g); return g; };
  const aw = opts.thin ? 0.12 : 0.2, lw = opts.thin ? 0.13 : 0.22;
  const armL = limb(aw, 0.64, pal.shirt, (opts.thin ? 0.24 : 0.34), 1.36), armR = limb(aw, 0.64, pal.shirt, -(opts.thin ? 0.24 : 0.34), 1.36);
  for (const a of [armL, armR]) { const hand = boxMesh(aw * 1.02, 0.14, aw * 1.02, pal.skin, -0.64 + 0.07); a.add(hand); }
  const legL = limb(lw, 0.72, pal.pants, 0.12, 0.72), legR = limb(lw, 0.72, pal.pants, -0.12, 0.72);
  for (const l of [legL, legR]) l.add(boxMesh(lw * 1.04, 0.12, lw * 1.12, pal.shoes || "#333", -0.72 + 0.06));
  const handPt = new THREE.Group(); handPt.position.set(0, -0.62, 0.1); armR.add(handPt);
  if (pal.glow) {   // a small glowing antenna: it pulses while the mind is thinking
    const stalk = boxMesh(0.035, 0.18, 0.035, "#c9d6e0", 0.09); stalk.position.set(0.1, 0.44, 0); head.add(stalk);
    const orb = new THREE.Mesh(new THREE.IcosahedronGeometry(0.075, 1), new THREE.MeshBasicMaterial({ color: pal.glow }));
    orb.position.set(0.1, 0.66, 0); head.add(orb); root.userData.orb = orb;
    const halo = new THREE.Mesh(new THREE.IcosahedronGeometry(0.13, 1), new THREE.MeshBasicMaterial({ color: pal.glow, transparent: true, opacity: 0.25, depthWrite: false }));
    orb.add(halo); root.userData.halo = halo;
  }
  root.userData.parts = { body, head, armL, armR, legL, legR, handPt };
  root.userData.height = 1.9;
  return root;
}
function hollowFace() {
  const c = document.createElement("canvas"); c.width = c.height = 16; const g = c.getContext("2d");
  g.fillStyle = "#d8d6cc"; g.fillRect(0, 0, 16, 16); g.fillStyle = "#222"; g.fillRect(3, 6, 4, 3); g.fillRect(9, 6, 4, 3); g.fillRect(6, 11, 4, 1); g.fillRect(5, 12, 1, 1); g.fillRect(10, 12, 1, 1);
  const t = new THREE.CanvasTexture(c); t.magFilter = THREE.NearestFilter; return t;
}
function creature(kind) {
  const d = KINDS[kind] || { body: [0.6, 0.5, 0.8], bodyY: 0.55, head: [0.36, 0.36, 0.36], legs: 0.3, col: `hsl(${(hash(kind.length, kind.charCodeAt(0)) * 360) | 0} 40% 55%)` };
  const root = new THREE.Group(), body = new THREE.Group(); root.add(body);
  const parts = { body, legs: [] };
  if (d.hollow) {
    const h = humanoid({ skin: d.col, shirt: d.col, pants: "#bfbdb2", hair: d.col, shoes: "#bfbdb2" }, { thin: true });
    h.userData.isPerson = true; return h;
  }
  if (d.slime) {
    const outer = new THREE.Mesh(new THREE.BoxGeometry(0.9, 0.9, 0.9), new THREE.MeshLambertMaterial({ color: d.col, transparent: true, opacity: 0.6 })); outer.position.y = 0.45;
    const inner = boxMesh(0.5, 0.5, 0.5, "#4fae4a", 0.45); const eyes = boxMesh(0.4, 0.1, 0.02, "#173", 0.6); eyes.position.z = 0.46;
    body.add(inner, outer, eyes); parts.slime = outer; root.userData.parts = parts; root.userData.height = 1; return root;
  }
  if (d.fish) {
    body.add(boxMesh(0.16, 0.26, 0.5, d.col, 0.25)); const tail = boxMesh(0.04, 0.24, 0.2, "#e06a2a", 0.25); tail.position.z = -0.32; body.add(tail);
    const eye = boxMesh(0.18, 0.05, 0.05, "#111", 0.3); eye.position.z = 0.16; body.add(eye); parts.tail = tail; root.userData.parts = parts; root.userData.height = 0.5; return root;
  }
  if (d.bee) {
    const b = boxMesh(0.3, 0.3, 0.4, d.col, 0.5); body.add(b);
    for (const z of [-0.06, 0.08]) { const s = boxMesh(0.31, 0.31, 0.05, "#2a2016", 0.5); s.position.z = z; body.add(s); }
    const wm = new THREE.MeshLambertMaterial({ color: 0xeef6ff, transparent: true, opacity: 0.6 });
    const w1 = new THREE.Mesh(new THREE.BoxGeometry(0.22, 0.02, 0.16), wm), w2 = w1.clone(); w1.position.set(0.14, 0.68, 0); w2.position.set(-0.14, 0.68, 0); body.add(w1, w2);
    parts.wings = [w1, w2]; root.userData.parts = parts; root.userData.height = 0.8; root.userData.fly = true; return root;
  }
  const [bw, bh, bl] = d.body, ly = d.legs;
  const torso = boxMesh(bw, bh, bl, d.col, 0); torso.position.y = d.bodyY; body.add(torso);
  if (d.spot) for (let i = 0; i < 3; i++) { const s = boxMesh(bw * 1.01, bh * 0.45, bl * 0.25, d.spot, 0); s.position.set(0, d.bodyY + (i % 2 ? 0.1 : -0.05), -bl * 0.3 + i * bl * 0.3); body.add(s); }
  if (d.fluffy) { const f = boxMesh(bw * 1.15, bh * 1.1, bl * 1.05, "#fbf9f2", 0); f.position.y = d.bodyY; body.add(f); }
  const head = new THREE.Group(); head.position.set(0, d.bodyY + (d.biped ? bh * 0.55 : bh * 0.25), bl / 2 + (d.biped ? -0.05 : d.head[2] * 0.35)); body.add(head);
  const [hw, hh, hd] = d.head;
  head.add(boxMesh(hw, hh, hd, d.headCol || d.col, 0));
  const snout = boxMesh(hw * (d.biped ? 0.3 : 0.55), hh * (d.biped ? 0.18 : 0.35), 0.1, d.snout || d.col, d.biped ? 0 : -hh * 0.18); snout.position.z = hd / 2 + 0.04; head.add(snout);
  for (const sx of [-1, 1]) { const e = boxMesh(0.06, 0.07, 0.02, "#151515", hh * 0.12); e.position.set(sx * hw * 0.28, 0, hd / 2 + 0.005); head.add(e); }
  if (d.wattle) { const w = boxMesh(0.08, 0.1, 0.04, d.wattle, -hh * 0.3); w.position.z = hd / 2 + 0.03; head.add(w); }
  if (d.ears) for (const sx of [-1, 1]) { const e = boxMesh(0.1, 0.14, 0.06, d.headCol, hh / 2 + 0.06); e.position.x = sx * hw * 0.3; head.add(e); }
  if (d.bunny) for (const sx of [-1, 1]) { const e = boxMesh(0.06, 0.22, 0.04, d.headCol, hh / 2 + 0.1); e.position.x = sx * 0.06; head.add(e); }
  if (d.tail) { const t = boxMesh(0.1, 0.1, 0.36, d.col, 0); t.position.set(0, d.bodyY + bh * 0.25, -bl / 2 - 0.15); t.rotation.x = -0.5; body.add(t); }
  const legW = d.biped ? 0.06 : Math.min(0.24, bw * 0.28);
  const legPos = d.biped ? [[0.1, 0], [-0.1, 0]] : [[bw / 2 - legW / 2, bl / 2 - legW / 2 - 0.02], [-(bw / 2 - legW / 2), bl / 2 - legW / 2 - 0.02], [bw / 2 - legW / 2, -(bl / 2 - legW / 2 - 0.02)], [-(bw / 2 - legW / 2), -(bl / 2 - legW / 2 - 0.02)]];
  for (const [x, z] of legPos) { const g = new THREE.Group(); g.position.set(x, ly, z); g.add(boxMesh(legW, ly, legW, d.biped ? "#e0a030" : d.headCol || d.col, -ly / 2)); body.add(g); parts.legs.push(g); }
  parts.head = head; root.userData.parts = parts; root.userData.height = d.bodyY + bh + 0.3;
  return root;
}

// ───────────────────────────────────────────── entities
function entKind(e) {
  const k = normName(e.kind || "");
  if (k === "agent" || k === "inhabitant" || k === "mind" || (S.agentId != null && e.id === S.agentId)) return "agent";
  if (k === "visitor" || k === "player" || k === "you") return "visitor";
  if (k === "item" || k === "dropped_item" || k === "drop") return "item";
  if (k === "falling_block" || k === "falling") return "falling";
  return k || "thing";
}
function isMe(e) { return S.mode === "visit" && (e.you || (S.visitor?.id != null && e.id === S.visitor.id) || (entKind(e) === "visitor" && !S.visitor?.id && S.othersSeen !== true)); }
function upsertEntity(e) {
  if (e.id == null) return;
  let rec = S.ents.get(e.id);
  if (!rec) {
    const kind = entKind(e);
    let obj;
    if (kind === "agent") obj = humanoid(PEOPLE.agent);
    else if (kind === "visitor") obj = humanoid(e.you ? PEOPLE.you : PEOPLE.other);
    else if (kind === "item") { obj = new THREE.Group(); obj.add(itemObject(e.item ?? e.held ?? e.block ?? e.name, 0.28)); obj.userData.spin = true; }
    else if (kind === "falling") { obj = new THREE.Group(); const b = findBlock(e.block ?? e.item ?? e.held); if (b) { const m = new THREE.Mesh(blockGeometry(b.id), S.mat[1]); obj.add(m); } }
    else obj = creature(kind);
    rec = { id: e.id, kind, obj, data: {}, pos: new THREE.Vector3(e.x ?? 0, e.y ?? 0, e.z ?? 0), tgt: new THREE.Vector3(), yaw: e.yaw || 0, pitch: 0, walk: 0, speed: 0, swing: 0, saidAt: 0, said: "", heldKey: "" };
    S.scene.add(obj); S.ents.set(e.id, rec);
  }
  Object.assign(rec.data, e);
  const d = rec.data;
  rec.tgt.set(+d.x || 0, +d.y || 0, +d.z || 0);
  if (rec.pos.distanceToSquared(rec.tgt) > 400) rec.pos.copy(rec.tgt);   // a jump, not a walk
  if ("said" in e) {
    const s = String(e.said ?? "").trim();
    if (s && s !== rec.said) { rec.said = s; rec.saidAt = performance.now(); } else if (!s) rec.said = "";
  }
  const hk = d.held == null ? "" : typeof d.held === "object" ? JSON.stringify(d.held) : String(d.held);
  if (hk !== rec.heldKey && rec.obj.userData.parts?.handPt) {
    rec.heldKey = hk; const hp = rec.obj.userData.parts.handPt; hp.clear();
    if (hk) { const it = itemObject(d.held, 0.22); it.rotation.set(-0.4, 0.6, 0); hp.add(it); }
  }
}
function removeEntity(id) {
  const rec = S.ents.get(id); if (!rec) return;
  S.scene.remove(rec.obj); rec.label?.remove(); rec.bubble?.remove(); S.ents.delete(id);
}
function animateEntities(dt, t) {
  for (const rec of S.ents.values()) {
    const o = rec.obj, d = rec.data, p = o.userData.parts;
    const hide = rec.kind === "visitor" && isMe(d);
    o.visible = !hide;
    const before = rec.pos.clone();
    rec.pos.lerp(rec.tgt, damp(10, dt));
    const sp = before.distanceTo(rec.pos) / Math.max(dt, 1e-3);
    rec.speed = lerp(rec.speed, Math.min(sp, 6), damp(8, dt));
    const yaw = +d.yaw || 0; rec.yaw += wrapAngle(yaw - rec.yaw) * damp(10, dt);
    o.position.copy(rec.pos); o.rotation.y = -rec.yaw;
    if (o.userData.spin) { o.rotation.y = t * 1.6 + (typeof rec.id === "number" ? rec.id : 0); o.position.y += 0.2 + Math.sin(t * 2.4 + rec.pos.x) * 0.06; continue; }
    if (o.userData.fly) o.position.y += 0.15 + Math.sin(t * 3 + rec.pos.x) * 0.1;
    const anim = normName(d.anim || "");
    if (p) {
      const walking = rec.speed > 0.4 || anim === "walk" || anim === "run" || anim === "swim";
      rec.walk += dt * (walking ? 4 + rec.speed * 1.6 : 0);
      const sw = walking ? Math.sin(rec.walk * 2.2) * Math.min(0.9, 0.35 + rec.speed * 0.15) : 0;
      if (p.legs) p.legs.forEach((l, i) => { l.rotation.x = (i % 2 ? -sw : sw) * (i > 1 ? -1 : 1) * 0.8; });
      if (p.legL) {
        p.legL.rotation.x = lerp(p.legL.rotation.x, sw, 0.5); p.legR.rotation.x = lerp(p.legR.rotation.x, -sw, 0.5);
        let ar = -sw * 0.8, al = sw * 0.8;
        if (/mine|dig|attack|chop|break|hit/.test(anim)) { ar = -1.2 - Math.abs(Math.sin(t * 9)) * 1.1; }
        else if (/place|use|build|give|plant/.test(anim)) { rec.swing = (rec.swing + dt * 4) % 1; ar = -0.6 - Math.sin(rec.swing * Math.PI) * 0.9; }
        else if (/eat|drink/.test(anim)) { ar = -1.7 + Math.sin(t * 10) * 0.15; }
        else if (/craft|smelt/.test(anim)) { ar = -0.9 + Math.sin(t * 7) * 0.3; al = -0.9 + Math.cos(t * 7) * 0.3; }
        else if (rec.data.held && !walking) ar = -0.25;
        p.armR.rotation.x = lerp(p.armR.rotation.x, ar, damp(18, dt)); p.armL.rotation.x = lerp(p.armL.rotation.x, al, damp(18, dt));
        p.armL.rotation.z = 0.05; p.armR.rotation.z = -0.05;
        const pitch = clamp(+d.pitch || 0, -1, 1); p.head.rotation.x = lerp(p.head.rotation.x, pitch * 0.8, damp(8, dt));
        p.body.position.y = walking ? Math.abs(Math.sin(rec.walk * 2.2)) * 0.03 : Math.sin(t * 1.5) * 0.008;
        if (/sleep/.test(anim)) { o.rotation.z = Math.PI / 2; o.position.y += 0.3; } else o.rotation.z = 0;
        if (/sneak|crouch/.test(anim)) p.body.rotation.x = 0.3; else p.body.rotation.x = 0;
      }
      if (p.slime) { const s = 1 + Math.sin(t * 5 + rec.pos.x) * 0.08; p.slime.scale.set(1 / s, s, 1 / s); }
      if (p.tail) p.tail.rotation.y = Math.sin(t * 8) * 0.5;
      if (p.wings) { p.wings[0].rotation.z = Math.sin(t * 40) * 0.5; p.wings[1].rotation.z = -Math.sin(t * 40) * 0.5; }
      if (p.head && !p.legL && rec.speed < 0.2) p.head.rotation.x = Math.sin(t * 0.7 + rec.pos.z) * 0.15 + 0.1;
    }
    if (o.userData.orb) {
      const think = !!S.agent?.thinking, k = think ? 0.6 + 0.4 * Math.sin(t * 10) : 0.85;
      o.userData.orb.material.color.setRGB(0.5 * k + 0.3, k, k); o.userData.halo.material.opacity = think ? 0.35 + 0.25 * Math.sin(t * 10) : 0.18;
      o.userData.orb.scale.setScalar(think ? 1.15 + 0.15 * Math.sin(t * 10) : 1);
    }
  }
}

// labels: name tags, speech bubbles and a thinking cloud, as DOM over the canvas
const tmpV = new THREE.Vector3();
function updateLabels() {
  const cam = S.camera, w = S.vw, h = S.vh, now = performance.now();
  for (const rec of S.ents.values()) {
    const d = rec.data, isAgent = rec.kind === "agent", person = isAgent || rec.kind === "visitor";
    const name = d.name || (isAgent ? S.agentName : "");
    const showTag = person && name && rec.obj.visible;
    const dist = rec.obj.position.distanceTo(cam.position);
    const ttl = Math.max(4500, Math.min(12000, rec.said.length * 75));
    const bubbleText = rec.said && now - rec.saidAt < ttl ? rec.said : isAgent && S.agent?.thinking ? "…" : "";
    tmpV.copy(rec.obj.position); tmpV.y += (rec.obj.userData.height || 1) + 0.25;
    tmpV.project(cam);
    const on = tmpV.z < 1 && tmpV.z > -1 && Math.abs(tmpV.x) < 1.2 && Math.abs(tmpV.y) < 1.2 && dist < (isAgent ? 90 : 40);
    const sx = (tmpV.x * 0.5 + 0.5) * w, sy = (-tmpV.y * 0.5 + 0.5) * h;
    if (showTag && on) {
      if (!rec.label) { rec.label = div(`vx-tag ${isAgent ? "vx-tag-agent" : ""}`, S.layer); }
      if (rec.label._t !== name) { rec.label._t = name; rec.label.textContent = name; }
      rec.label.hidden = false; rec.label.style.transform = `translate(${sx}px, ${sy}px) translate(-50%, -100%)`;
      rec.label.style.opacity = String(clamp(1.3 - dist / 70, 0.35, 1));
    } else if (rec.label) rec.label.hidden = true;
    if (bubbleText && on && dist < 48 && rec.obj.visible) {
      if (!rec.bubble) rec.bubble = div(`vx-bubble ${isAgent ? "vx-bubble-agent" : ""}`, S.layer);
      if (rec.bubble._t !== bubbleText) { rec.bubble._t = bubbleText; rec.bubble.innerHTML = bubbleText === "…" ? '<span class="vx-dots"><i></i><i></i><i></i></span>' : `<span>${esc(bubbleText)}</span>`; rec.bubble.classList.toggle("thinking", bubbleText === "…"); }
      rec.bubble.hidden = false; rec.bubble.style.transform = `translate(${sx}px, ${sy - (showTag ? 26 : 4)}px) translate(-50%, -100%)`;
    } else if (rec.bubble) rec.bubble.hidden = true;
  }
}

// ───────────────────────────────────────────── overlays: selection box, crack, hand
function buildOverlays() {
  const eg = new THREE.EdgesGeometry(new THREE.BoxGeometry(1.004, 1.004, 1.004)); eg.translate(0.5, 0.5, 0.5);
  S.sel = new THREE.LineSegments(eg, new THREE.LineBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.55 })); S.sel.visible = false; S.scene.add(S.sel);
  S.crackTex = [];
  for (let st = 0; st < 10; st++) {
    const c = document.createElement("canvas"); c.width = c.height = 16; const g = c.getContext("2d");
    g.fillStyle = "rgba(0,0,0,.72)";
    let n = 0; const lines = 3 + st;
    for (let i = 0; i < lines; i++) {
      let x = 8 + (hash(i, 0, 5) - 0.5) * 4, y = 8 + (hash(i, 1, 5) - 0.5) * 4; const steps = 2 + st * 0.9;
      for (let s = 0; s < steps; s++) { g.fillRect(Math.floor(x), Math.floor(y), 1, 1); x += Math.round((hash(i, s, 9) - 0.5) * 2.4); y += Math.round((hash(i, s, 11) - 0.5) * 2.4); n++; }
    }
    const t = new THREE.CanvasTexture(c); t.magFilter = THREE.NearestFilter; t.minFilter = THREE.NearestFilter; S.crackTex.push(t);
  }
  const cg = new THREE.BoxGeometry(1.006, 1.006, 1.006); cg.translate(0.5, 0.5, 0.5);
  S.crack = new THREE.Mesh(cg, new THREE.MeshBasicMaterial({ map: S.crackTex[0], transparent: true, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 }));
  S.crack.visible = false; S.scene.add(S.crack);
  S.hand = new THREE.Group(); S.hand.position.set(0.42, -0.36, -0.62); S.camera.add(S.hand); S.hand.visible = false;
  S.myFig = humanoid(PEOPLE.you); S.myFig.visible = false; S.scene.add(S.myFig);
}
function setHandItem() {
  const it = S.hot.slots[S.hot.selected], key = it ? JSON.stringify(it.item ?? it.id ?? it.name) : "";
  if (key === S.handKey) return; S.handKey = key;
  S.hand.clear();
  if (!it) { const arm = boxMesh(0.14, 0.42, 0.14, PEOPLE.you.skin, 0.21); arm.rotation.x = -1.1; arm.position.set(0.04, -0.06, 0.05); S.hand.add(arm); }
  else { const o = itemObject(it.id ?? it.item ?? it.name, 0.3); o.rotation.set(0.15, 0.75, 0); S.hand.add(o); }
  const fig = S.myFig.userData.parts.handPt; fig.clear();
  if (it) { const o = itemObject(it.id ?? it.item ?? it.name, 0.22); o.rotation.set(-0.4, 0.6, 0); fig.add(o); }
}

// ───────────────────────────────────────────── input
function bindInput() {
  const el = S.canvas;
  el.addEventListener("contextmenu", (e) => e.preventDefault());
  el.addEventListener("pointerdown", (e) => {
    el.focus({ preventScroll: true });
    if (S.mode === "visit") {
      if (!S.locked && e.pointerType === "mouse") { el.requestPointerLock?.()?.catch?.(() => {}); return; }
      if (e.button === 0) S.mouse.left = true;
      if (e.button === 2) { S.mouse.right = true; rightClick(); }
      return;
    }
    S.drag = { x: e.clientX, y: e.clientY, id: e.pointerId }; el.setPointerCapture(e.pointerId);
  });
  el.addEventListener("pointermove", (e) => {
    if (S.mode === "visit" && S.locked) {
      const k = 0.0024 * (S.sens || 1);
      S.me.yaw = wrapAngle(S.me.yaw + e.movementX * k); S.me.pitch = clamp(S.me.pitch + e.movementY * k, -1.55, 1.55); return;
    }
    if (S.drag && S.drag.id === e.pointerId) {
      const dx = e.clientX - S.drag.x, dy = e.clientY - S.drag.y; S.drag.x = e.clientX; S.drag.y = e.clientY;
      S.cam.tYaw += dx * 0.007; S.cam.tPitch = clamp(S.cam.tPitch + dy * 0.005, -0.25, 1.45);
    }
  });
  const up = (e) => { if (e.button === 0) { S.mouse.left = false; S.dig = null; } if (e.button === 2) S.mouse.right = false; if (S.drag?.id === e.pointerId) S.drag = null; };
  el.addEventListener("pointerup", up); el.addEventListener("pointercancel", up);
  el.addEventListener("wheel", (e) => {
    e.preventDefault();
    if (S.mode === "visit") { if (!S.locked) return; const n = 9; selectSlot((S.hot.selected + (e.deltaY > 0 ? 1 : -1) + n) % n); }
    else S.cam.tDist = clamp(S.cam.tDist * (e.deltaY > 0 ? 1.12 : 0.89), 3, 60);
  }, { passive: false });
  document.addEventListener("pointerlockchange", () => {
    S.locked = document.pointerLockElement === el;
    if (!S.locked) { S.mouse.left = S.mouse.right = false; S.dig = null; S.keys.clear(); }
    hud();
  });
  addEventListener("keydown", (e) => {
    if (isTyping() || S.paused) return;
    if (S.mode !== "visit") { if (["KeyW", "KeyA", "KeyS", "KeyD"].includes(e.code) && document.activeElement === el) S.keys.add(e.code); return; }
    if (!S.locked && document.activeElement !== el) return;
    const code = e.code;
    if (["Space", "ArrowUp", "ArrowDown"].includes(code)) e.preventDefault();
    if (/^Digit[1-9]$/.test(code)) { selectSlot(+code.slice(5) - 1); return; }
    if (code === "F5" || code === "KeyV") { e.preventDefault(); S.cam.third = !S.cam.third; hud(); return; }
    if (code === "KeyE") { e.preventDefault(); if (document.pointerLockElement) document.exitPointerLock(); S.cb.key?.("inventory"); return; }
    if (code === "KeyT" || code === "Enter") { e.preventDefault(); if (document.pointerLockElement) document.exitPointerLock(); S.cb.key?.("talk"); return; }
    if (code === "KeyQ") { const it = S.hot.slots[S.hot.selected]; if (it) S.cb.command?.({ action: "drop", slot: S.hot.selected, count: e.ctrlKey ? it.count || 1 : 1 }); return; }
    if (code === "KeyG") { give(); return; }
    S.keys.add(code);
    if (e.ctrlKey && code !== "ControlLeft") e.preventDefault();
  });
  addEventListener("keyup", (e) => S.keys.delete(e.code));
  addEventListener("blur", () => { S.keys.clear(); S.mouse.left = S.mouse.right = false; });
}
function selectSlot(i) { if (i === S.hot.selected) return; S.hot.selected = i; S.dig = null; setHandItem(); S.cb.select?.(i); }
function give() {
  const it = S.hot.slots[S.hot.selected], ag = agentRec();
  if (!it) { S.cb.status?.("Nothing in your hand to give."); return; }
  if (!ag || ag.pos.distanceTo(S.me.pos) > 4) { S.cb.status?.(`Walk within 4 blocks of ${S.agentName || "it"} to hand it something.`); return; }
  S.cb.command?.({ action: "give", slot: S.hot.selected, item: it.item ?? it.name ?? it.id, count: it.count || 1, to: ag.id });
}
function agentRec() { for (const r of S.ents.values()) if (r.kind === "agent") return r; return null; }

// ───────────────────────────────────────────── visiting: physics, ray cast, dig, place
const HW = 0.3;
function solidBox(x, y, z) {   // the collision height of a cell (0 = free), unloaded = solid
  const v = rawAt(x, y, z); if (v < 0) return y < 0 ? 1 : 1; if (v === 0) return 0;
  const b = blockOf(v); if (!b) return 1;
  if (!b.solid || b.kind === K.CROSS || b.kind === K.LIQUID || b.kind === K.TORCH || b.kind === K.FLAT) return 0;
  return b.kind === K.SLAB ? b.h : 1;
}
function collides(px, py, pz, h) {
  const x0 = Math.floor(px - HW), x1 = Math.floor(px + HW - 1e-6), y0 = Math.floor(py), y1 = Math.floor(py + h - 1e-6), z0 = Math.floor(pz - HW), z1 = Math.floor(pz + HW - 1e-6);
  for (let y = y0; y <= y1; y++) for (let z = z0; z <= z1; z++) for (let x = x0; x <= x1; x++) { const s = solidBox(x, y, z); if (s && py < y + s) return { x, y, z, top: y + s }; }
  return null;
}
function inLiquid(px, py, pz) { const b = blockAtXYZ(Math.floor(px), Math.floor(py), Math.floor(pz)); return b && b.kind === K.LIQUID ? b : null; }
function climbing(px, py, pz) { const b = blockAtXYZ(Math.floor(px), Math.floor(py + 0.2), Math.floor(pz)); return !!(b && b.climbable); }
function updateVisit(dt) {
  const me = S.me, k = S.keys, H = me.sneak ? 1.5 : 1.8;
  if (!me.init) return;
  // a chunk that isn't loaded yet holds you in place
  if (rawAt(Math.floor(me.pos.x), Math.floor(me.pos.y), Math.floor(me.pos.z)) < 0 && me.pos.y >= 0) { me.vel.set(0, 0, 0); return; }
  me.sneak = k.has("ShiftLeft") || k.has("ShiftRight");
  if (k.has("ControlLeft") || k.has("ControlRight")) me.sprint = true;
  const fwd = (k.has("KeyW") || k.has("ArrowUp") ? 1 : 0) - (k.has("KeyS") || k.has("ArrowDown") ? 1 : 0);
  const str = (k.has("KeyD") || k.has("ArrowRight") ? 1 : 0) - (k.has("KeyA") || k.has("ArrowLeft") ? 1 : 0);
  if (fwd <= 0) me.sprint = false;
  const liquid = inLiquid(me.pos.x, me.pos.y + 0.4, me.pos.z); me.inWater = !!liquid;
  S.underwater = !!inLiquid(S.camera.position.x, S.camera.position.y, S.camera.position.z) && S.mode === "visit" && !S.cam.third;
  const speed = me.sneak ? 1.4 : me.sprint ? 5.7 : 4.3, sy = Math.sin(me.yaw), cy = Math.cos(me.yaw);
  // forward = (-sin yaw, cos yaw); right = (-cos yaw, -sin yaw)
  let wx = -sy * fwd - cy * str, wz = cy * fwd - sy * str; const wl = Math.hypot(wx, wz); if (wl > 0) { wx /= wl; wz /= wl; }
  const sp = liquid ? speed * 0.55 : speed, acc = me.onGround ? 14 : liquid ? 6 : 3.2;
  me.vel.x = lerp(me.vel.x, wx * sp, damp(acc, dt)); me.vel.z = lerp(me.vel.z, wz * sp, damp(acc, dt));
  if (liquid) {
    me.vel.y = lerp(me.vel.y, -1.2, damp(2.5, dt));
    if (k.has("Space")) me.vel.y = lerp(me.vel.y, 3.6, damp(8, dt));
  } else if (climbing(me.pos.x, me.pos.y, me.pos.z)) {
    me.vel.y = k.has("Space") || fwd > 0 ? 2.6 : me.sneak ? 0 : Math.max(me.vel.y - 28 * dt, -2.2);
  } else {
    me.vel.y -= 28 * dt; if (me.vel.y < -60) me.vel.y = -60;
    if (k.has("Space") && me.onGround) { me.vel.y = 8.7; me.onGround = false; }
  }
  // move axis by axis with sub-steps
  const steps = Math.ceil(Math.max(Math.abs(me.vel.x), Math.abs(me.vel.y), Math.abs(me.vel.z)) * dt / 0.35) || 1;
  const sdt = dt / steps; let ground = false;
  for (let s = 0; s < steps; s++) {
    for (const ax of ["x", "z"]) {
      const d = me.vel[ax] * sdt; if (!d) continue;
      const old = me.pos[ax]; me.pos[ax] += d;
      const hit = collides(me.pos.x, me.pos.y, me.pos.z, H);
      if (hit) {
        // step up onto slabs and paths (≤ 0.6)
        const up = hit.top - me.pos.y;
        if (me.onGround && up > 0 && up <= 0.6 && !collides(me.pos.x, me.pos.y + up + 0.001, me.pos.z, H)) { me.pos.y += up + 0.001; continue; }
        me.pos[ax] = old; me.vel[ax] = 0;
      } else if (me.sneak && me.onGround && !collides(me.pos.x, me.pos.y - 0.6, me.pos.z, 0.55)) { me.pos[ax] = old; me.vel[ax] = 0; }   // sneaking keeps you on the edge
    }
    const dy = me.vel.y * sdt; me.pos.y += dy;
    const hit = collides(me.pos.x, me.pos.y, me.pos.z, H);
    if (hit) {
      if (dy < 0) { me.pos.y = hit.top + 1e-4; ground = true; } else me.pos.y = hit.y - H - 1e-4;
      me.vel.y = 0;
    }
  }
  me.onGround = ground || (!!collides(me.pos.x, me.pos.y - 0.02, me.pos.z, 0.02) && me.vel.y <= 0);
  if (me.pos.y < -20) { const v = S.visitor; me.pos.set(v?.x ?? 0, (v?.y ?? 100) + 2, v?.z ?? 0); me.vel.set(0, 0, 0); }
  // tell the server where we are, 10 times a second when something changed
  const now = performance.now();
  if (now - me.lastSend > 100) {
    const r = (v) => Math.round(v * 100) / 100, key = `${r(me.pos.x)},${r(me.pos.y)},${r(me.pos.z)},${r(me.yaw)},${r(me.pitch)}`;
    if (key !== me.sentKey) { me.sentKey = key; me.lastSend = now; S.cb.command?.({ action: "move", x: r(me.pos.x), y: r(me.pos.y), z: r(me.pos.z), yaw: r(me.yaw), pitch: r(me.pitch), sneak: me.sneak || undefined }, true); }
  }
}
function eyePos() { return new THREE.Vector3(S.me.pos.x, S.me.pos.y + (S.me.sneak ? 1.32 : 1.62), S.me.pos.z); }
function lookDir(yaw, pitch) { return new THREE.Vector3(-Math.sin(yaw) * Math.cos(pitch), -Math.sin(pitch), Math.cos(yaw) * Math.cos(pitch)); }
/** Voxel DDA: the first non-air, non-liquid cell along the ray. */
function raycast(o, d, reach) {
  let x = Math.floor(o.x), y = Math.floor(o.y), z = Math.floor(o.z);
  const sx = Math.sign(d.x), sy = Math.sign(d.y), sz = Math.sign(d.z);
  const tdx = Math.abs(1 / d.x), tdy = Math.abs(1 / d.y), tdz = Math.abs(1 / d.z);
  let tx = d.x ? ((sx > 0 ? x + 1 - o.x : o.x - x) * tdx) : Infinity, ty = d.y ? ((sy > 0 ? y + 1 - o.y : o.y - y) * tdy) : Infinity, tz = d.z ? ((sz > 0 ? z + 1 - o.z : o.z - z) * tdz) : Infinity;
  let n = [0, 0, 0], t = 0;
  for (let i = 0; i < 64 && t <= reach; i++) {
    const v = rawAt(x, y, z);
    if (v > 0) { const b = blockOf(v); if (b && b.kind !== K.LIQUID && b.kind !== K.AIR) return { x, y, z, n, b, raw: v, t }; }
    if (tx < ty && tx < tz) { x += sx; t = tx; tx += tdx; n = [-sx, 0, 0]; }
    else if (ty < tz) { y += sy; t = ty; ty += tdy; n = [0, -sy, 0]; }
    else { z += sz; t = tz; tz += tdz; n = [0, 0, -sz]; }
  }
  return null;
}
function updateTarget(dt) {
  const reach = S.hot.creative ? 7 : 5;
  const hit = S.locked && !S.cam.third ? raycast(eyePos(), lookDir(S.me.yaw, S.me.pitch), reach) : S.locked ? raycast(eyePos(), lookDir(S.me.yaw, S.me.pitch), reach) : null;
  S.hit = hit;
  if (hit) {
    S.sel.visible = true; S.sel.position.set(hit.x, hit.y, hit.z);
    const h = hit.b.kind === K.SLAB ? hit.b.h : hit.b.kind === K.FLAT ? 0.07 : 1; S.sel.scale.set(1, h, 1);
  } else S.sel.visible = false;
  // dig while the left button is held
  if (S.mouse.left && hit) {
    const key = `${hit.x},${hit.y},${hit.z}`, held = S.hot.slots[S.hot.selected];
    if (!S.dig || S.dig.key !== key) S.dig = { key, x: hit.x, y: hit.y, z: hit.z, t: 0, need: breakTime(hit.b, held && (held.item ?? held.name), S.hot.creative) };
    S.dig.t += dt; S.swing = (S.swing + dt * 5) % 1;
    if (S.dig.need === Infinity) { S.crack.visible = false; S.digBar.hidden = true; S.cb.status?.(`${hit.b.label} can't be broken.`); }
    else {
      const f = clamp(S.dig.t / S.dig.need, 0, 1);
      S.crack.visible = true; S.crack.position.set(hit.x, hit.y, hit.z); S.crack.material.map = S.crackTex[Math.min(9, Math.floor(f * 10))];
      S.digBar.hidden = S.dig.need < 0.3; S.digBar.firstChild.style.width = `${Math.round(f * 100)}%`;
      if (f >= 1) {
        const { x, y, z } = S.dig; S.dig = S.hot.creative ? null : { ...S.dig, key: "", t: -0.15 };
        localEdit(x, y, z, 0);
        S.cb.command?.({ action: "dig", x, y, z }).catch?.(() => reloadAround(x, z));
        S.crack.visible = false; S.digBar.hidden = true;
      }
    }
  } else { S.crack.visible = false; S.digBar.hidden = true; if (!S.mouse.left) S.dig = null; }
  // keep placing while the right button is held (every 0.25 s)
  S.placeCD -= dt;
  if (S.mouse.right && S.placeCD <= 0 && S.rightHeld) rightClick();
  S.rightHeld = S.mouse.right;
}
function rightClick() {
  const hit = S.hit; S.placeCD = 0.25;
  if (!hit) return;
  if (hit.b.usable && !S.me.sneak) { S.swing = 0.01; S.cb.command?.({ action: "use", x: hit.x, y: hit.y, z: hit.z }); return; }
  const it = S.hot.slots[S.hot.selected]; if (!it) return;
  const b = findBlock(it.id ?? it.item ?? it.name);
  if (!b || b.kind === K.AIR) { S.cb.command?.({ action: "use", x: hit.x, y: hit.y, z: hit.z, item: it.item ?? it.name }); return; }
  let [x, y, z] = [hit.x + hit.n[0], hit.y + hit.n[1], hit.z + hit.n[2]];
  if (hit.b.replaceable || (hit.b.kind === K.CROSS && !/sapling|flower|mushroom/.test(hit.b.key))) [x, y, z] = [hit.x, hit.y, hit.z];
  const cur = blockAtXYZ(x, y, z);
  if (cur && !(cur.replaceable || cur.kind === K.LIQUID || (cur.kind === K.CROSS && /grass|fern/.test(cur.key)))) return;
  if (y < 0 || y > 255) return;
  // not inside yourself (or the inhabitant)
  if (b.solid !== false && b.kind !== K.CROSS && b.kind !== K.TORCH && b.kind !== K.FLAT) {
    const me = S.me, H = me.sneak ? 1.5 : 1.8;
    if (x + 1 > me.pos.x - HW && x < me.pos.x + HW && z + 1 > me.pos.z - HW && z < me.pos.z + HW && y + 1 > me.pos.y && y < me.pos.y + H) return;
  }
  S.swing = 0.01;
  localEdit(x, y, z, b.id);
  S.cb.command?.({ action: "place", x, y, z, id: b.id, item: it.item ?? it.name ?? b.key }).catch?.(() => reloadAround(x, z));
}
function localEdit(x, y, z, v) { S.lastLocalEdit = performance.now(); applyEditsLocal([[x, y, z, v]]); }
function reloadAround(x, z) {   // the server said no: get the truth again
  const key = kk(Math.floor(x / 16), Math.floor(z / 16)), c = S.chunks.get(key); if (!c) return;
  c.state = "new"; c.meshReq = false; c.data = null; S.lastCenter = null;
}

// ───────────────────────────────────────────── camera
function updateCamera(dt) {
  const cam = S.camera, c = S.cam;
  if (S.mode === "visit" && S.me.init) {
    const eye = eyePos(), dir = lookDir(S.me.yaw, S.me.pitch);
    if (!c.third) { cam.position.copy(eye); cam.lookAt(eye.clone().add(dir)); }
    else {
      const back = eye.clone().addScaledVector(dir, -4.2); const d = clearDistance(eye, back); cam.position.copy(eye).addScaledVector(dir, -d); cam.lookAt(eye);
    }
    S.hand.visible = !c.third && S.locked;
    const sw = S.mouse.left && S.dig ? Math.sin(S.swing * Math.PI * 2) : S.swing > 0 ? Math.sin(S.swing * Math.PI) : 0;
    if (!S.mouse.left && S.swing > 0) { S.swing += dt * 4; if (S.swing >= 1) S.swing = 0; }
    const bob = Math.hypot(S.me.vel.x, S.me.vel.z) > 0.5 && S.me.onGround ? Math.sin(performance.now() / 120) * 0.015 : 0;
    S.hand.position.set(0.42, -0.36 + bob - Math.abs(sw) * 0.08, -0.62 + Math.abs(sw) * 0.1); S.hand.rotation.set(-Math.abs(sw) * 0.6, 0, 0);
    // your figure, for the third-person view
    S.myFig.visible = c.third; S.myFig.position.copy(S.me.pos); S.myFig.rotation.y = -S.me.yaw;
    const p = S.myFig.userData.parts, walk = Math.hypot(S.me.vel.x, S.me.vel.z), ph = performance.now() / 160;
    p.legL.rotation.x = Math.sin(ph) * Math.min(0.8, walk * 0.18); p.legR.rotation.x = -p.legL.rotation.x;
    p.armL.rotation.x = -p.legL.rotation.x * 0.8; p.armR.rotation.x = S.mouse.left ? -1.2 - Math.abs(Math.sin(ph * 2)) : p.legL.rotation.x * 0.8;
    p.head.rotation.x = S.me.pitch * 0.8; p.body.rotation.x = S.me.sneak ? 0.3 : 0;
    return;
  }
  S.hand.visible = false; S.myFig.visible = false;
  // watch: orbit the inhabitant (or the spot it was last seen)
  const ag = agentRec();
  if (ag) c.target.lerp(new THREE.Vector3(ag.pos.x, ag.pos.y + 1.2, ag.pos.z), damp(4, dt));
  if (S.keys.size) {   // WASD nudges the orbit when the canvas has focus
    const f = (S.keys.has("KeyW") ? 1 : 0) - (S.keys.has("KeyS") ? 1 : 0), r = (S.keys.has("KeyD") ? 1 : 0) - (S.keys.has("KeyA") ? 1 : 0);
    c.tYaw += r * dt * 1.4; c.tDist = clamp(c.tDist - f * dt * 10, 3, 60);
  }
  c.yaw += (c.tYaw - c.yaw) * damp(8, dt); c.pitch += (c.tPitch - c.pitch) * damp(8, dt); c.dist += (c.tDist - c.dist) * damp(6, dt);
  const off = new THREE.Vector3(Math.sin(c.yaw) * Math.cos(c.pitch), Math.sin(c.pitch), Math.cos(c.yaw) * Math.cos(c.pitch));
  const want = c.target.clone().addScaledVector(off, c.dist);
  const d = clearDistance(c.target, want);
  cam.position.copy(c.target).addScaledVector(off, d); cam.lookAt(c.target);
  S.underwater = !!inLiquid(cam.position.x, cam.position.y, cam.position.z);
}
// how far the camera can go from `from` towards `to` before a solid block is in the way
function clearDistance(from, to) {
  const dir = to.clone().sub(from), len = dir.length(); if (len < 1e-3) return len; dir.divideScalar(len);
  const hit = raycastSolid(from, dir, len);
  return hit == null ? len : Math.max(0.3, hit - 0.25);
}
function raycastSolid(o, d, reach) {
  for (let t = 0; t < reach; t += 0.2) {
    const x = Math.floor(o.x + d.x * t), y = Math.floor(o.y + d.y * t), z = Math.floor(o.z + d.z * t);
    const v = rawAt(x, y, z); if (v > 0) { const b = blockOf(v); if (b && b.opaque) return t; }
  }
  return null;
}

// ───────────────────────────────────────────── HUD bits drawn by vox (crosshair, hint)
function hud() {
  const v = S.mode === "visit";
  S.cross.hidden = !(v && S.locked && !S.cam.third);
  S.hint.hidden = !v || S.locked;
  if (v && !S.locked) S.hint.innerHTML = matchMedia("(pointer: coarse)").matches ? "Visiting needs a keyboard and mouse." : "<b>Click</b> to walk in · <b>WASD</b> move · <b>Space</b> jump · <b>Left-click</b> dig · <b>Right-click</b> place / use · <b>E</b> inventory · <b>G</b> give · <b>V</b> camera · <b>Esc</b> release";
  S.canvas.classList.toggle("visit", v);
  S.cb.key?.("hud");
}

// ───────────────────────────────────────────── frame loop: 60 fps cap, nothing while hidden
function nextFrame() {
  const gap = 1000 / (S.fpsCap || 60), wait = Math.max(0, gap - (performance.now() - S.lastFrame) - 3);
  S.raf = setTimeout(() => requestAnimationFrame(frame), wait);
}
function frame(now) {
  S.raf = null;
  if (S.paused || document.hidden) return;
  nextFrame();
  if (now - S.lastFrame < 1000 / ((S.fpsCap || 60) + 1)) return;
  const dt = Math.min(0.1, (now - S.lastFrame) / 1000); S.lastFrame = now;
  if (!S.vw || !S.vh || S.container.clientWidth === 0) return;
  const t0 = performance.now();
  S.U.uTime.value += dt; const t = S.U.uTime.value;
  if (S.mode === "visit") { updateVisit(dt); updateTarget(dt); } else { S.sel.visible = false; S.crack.visible = false; }
  updateCamera(dt);
  updateEnv(dt);
  updateWeather(dt, t);
  animateEntities(dt, t);
  S.renderer.render(S.scene, S.camera);
  updateLabels();
  if (S.pendingLat) {   // an edit's mesh arrived: it is on screen with this frame
    S.pendingLat = false; const e = S.stats.editLat.at(-1); if (e && !e.shown) { e.shown = performance.now(); }
  }
  const st = S.stats, ms = performance.now() - t0, info = S.renderer.info.render;
  st.calls = info.calls; st.tris = info.triangles; st.frameMax = Math.max(st.frameMax, ms); st.frames++; st.msAcc += ms;
  if (now - st.last > 1000) { st.fps = Math.round((st.frames * 1000) / (now - st.last)); st.ms = +(st.msAcc / st.frames).toFixed(2); st.frames = 0; st.msAcc = 0; st.last = now; }
}

// ───────────────────────────────────────────── public API
function update(w) {
  if (!w) return;
  if (w.time != null) S.time = dayFraction(w.time);
  if (w.day != null) S.day = w.day;
  if (w.weather != null) S.weather = String(w.weather).toLowerCase();
  if (w.light != null && typeof w.light === "number") S.lightOverride = w.light > 1 ? w.light / 15 : w.light;
  if (w.agent) {
    S.agent = { ...(S.agent || {}), ...w.agent };
    if (w.agent.id != null) S.agentId = w.agent.id;
    if (w.agent.name) S.agentName = w.agent.name;
    if (w.agent.x != null) upsertEntity({ id: S.agentId ?? "agent", kind: "agent", ...pick(w.agent, ["x", "y", "z", "yaw", "pitch", "name", "said", "held", "health", "anim"]) });
  }
  if (Array.isArray(w.blocks) && w.blocks.length) applyEditsLocal(w.blocks.map((b) => [b[0] | 0, b[1] | 0, b[2] | 0, b[3] | 0]));
  if (w.full) for (const id of [...S.ents.keys()]) if (!(w.entities || []).some((e) => e.id === id) && id !== (S.agentId ?? "agent")) removeEntity(id);
  for (const e of w.entities || []) upsertEntity(e);
  for (const id of w.removed || []) removeEntity(id);
  if ("visitor" in w) {
    const v = w.visitor; S.visitor = v || null;
    if (v && v.x != null && S.mode === "visit") {
      const far = !S.me.init || Math.hypot(v.x - S.me.pos.x, v.y - S.me.pos.y, v.z - S.me.pos.z) > 8 || v.teleport;
      if (far) { S.me.pos.set(+v.x, +v.y, +v.z); S.me.vel.set(0, 0, 0); if (!S.me.init) { S.me.yaw = +v.yaw || 0; S.me.pitch = +v.pitch || 0; } S.me.init = true; }
    }
  }
}
const pick = (o, keys) => { const r = {}; for (const k of keys) if (k in o) r[k] = o[k]; return r; };
function setMode(mode) {
  mode = mode === "visit" ? "visit" : "watch";
  if (mode === S.mode) return;
  S.mode = mode; S.keys.clear(); S.dig = null; S.lastCenter = null;
  if (mode === "visit") {
    S.me.init = false;
    const v = S.visitor, ag = agentRec();
    if (v && v.x != null) { S.me.pos.set(+v.x, +v.y, +v.z); S.me.init = true; }
    else if (ag) { S.me.pos.set(ag.pos.x + 2, ag.pos.y + 1, ag.pos.z + 2); S.me.init = true; }
    S.me.yaw = S.cam.yaw + Math.PI; S.me.pitch = 0.1;
    setHandItem();
  } else if (document.pointerLockElement) document.exitPointerLock();
  hud();
}
function setHotbar(h) {
  Object.assign(S.hot, h);
  setHandItem();
}
function setRenderDistance(r) { S.rd = clamp(r | 0, 2, 12); S.lastCenter = null; }
function pause(p) { S.paused = !!p; if (!p) { S.lastFrame = performance.now(); if (S.raf == null && S.inited) nextFrame(); } else if (document.pointerLockElement) document.exitPointerLock(); }
function stats() {
  const s = S.stats, mm = s.meshMs, avg = mm.length ? mm.reduce((a, b) => a + b, 0) / mm.length : 0;
  const lat = s.editLat.filter((e) => e.shown).map((e) => e.shown - e.t0);
  const out = { fps: s.fps, ms: s.ms, frameMax: +s.frameMax.toFixed(1), calls: s.calls, triangles: s.tris,
    chunks: [...S.chunks.values()].filter((c) => c.meshes.length).length, loaded: [...S.chunks.values()].filter((c) => c.data).length,
    meshAvg: +avg.toFixed(2), meshMax: +s.meshMax.toFixed(2), meshLast: +s.meshLast.toFixed(2), meshCount: mm.length,
    editLatLast: lat.length ? Math.round(lat.at(-1)) : null, editLatMax: lat.length ? Math.round(Math.max(...lat)) : null };
  s.frameMax = 0;
  return out;
}
function camInfo() {
  const p = S.mode === "visit" && S.me.init ? S.me.pos : S.cam.target;
  return { x: p.x, y: p.y, z: p.z, yaw: S.mode === "visit" ? S.me.yaw : S.cam.yaw + Math.PI, mode: S.mode, me: S.me.init && S.mode === "visit" ? { x: S.me.pos.x, z: S.me.pos.z, yaw: S.me.yaw } : null };
}
const API = {
  update, setMode, setHotbar, setRenderDistance, pause, stats, camInfo,
  get tiles() { return S.tiles; }, get tilesVer() { return S.tilesVer || 0; },
  setSensitivity(v) { S.sens = v; },
  focusAgent() { S.cam.tDist = 11; S.cam.tPitch = 0.45; },
  isLocked: () => S.locked,
  mode: () => S.mode,
  agentPos() { const a = agentRec(); return a ? { x: a.pos.x, y: a.pos.y, z: a.pos.z } : null; },
  // for tests and the Health tab
  debug: {
    S,
    setView(yaw, pitch, dist) { S.cam.tYaw = S.cam.yaw = yaw; S.cam.tPitch = S.cam.pitch = pitch; S.cam.tDist = S.cam.dist = dist; },
    look(yaw, pitch) { S.me.yaw = yaw; S.me.pitch = pitch; },
    teleport(x, y, z) { S.me.pos.set(x, y, z); S.me.vel.set(0, 0, 0); S.me.init = true; },
    lock(v) { S.locked = v; hud(); },
    mouse(btn, down) { if (btn === 0) { S.mouse.left = down; if (!down) S.dig = null; } else { S.mouse.right = down; if (down) rightClick(); } },
    key(code, down) { down ? S.keys.add(code) : S.keys.delete(code); },
    bench(key, n = 5) { return new Promise((res) => { S.benchCb = res; S.worker.postMessage({ type: "bench", key, n }); }); },
    hit: () => S.hit && { x: S.hit.x, y: S.hit.y, z: S.hit.z, block: S.hit.b.key },
    blockAt: (x, y, z) => blockAtXYZ(x, y, z)?.key ?? null,
    third(v) { S.cam.third = v; hud(); },
  },
};
export default API;
