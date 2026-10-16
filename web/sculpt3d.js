// sculpt3d.js — sculptures in 3D (three.js). A sculpture spec is a stack of shaped parts in a material; this module
// turns it into a THREE.Group, renders still thumbnails with one shared renderer, and mounts an orbit view.
//   buildSculpture(THREE, spec, { plinth }) → THREE.Group, about 1 unit tall, standing on y = 0
//   renderTo(canvas, spec)                   → paints a studio portrait of the sculpture into a 2D canvas
//   mountOrbit(container, spec)              → an interactive view; returns { dispose }
import * as THREE_NS from "./vendor/three.module.min.js";

// ───────────────────────────────────────────────── small helpers
function rng(seed) { let a = (seed >>> 0) || 1; return () => { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
function hash3(x, y, z, s) { let h = Math.imul(x | 0, 374761393) ^ Math.imul(y | 0, 668265263) ^ Math.imul(z | 0, 1274126177) ^ Math.imul(s | 0, 2246822519); h = Math.imul(h ^ (h >>> 13), 1274126177); return ((h ^ (h >>> 16)) >>> 0) / 4294967296; }
function noise3(x, y, z, s) {
  const xi = Math.floor(x), yi = Math.floor(y), zi = Math.floor(z), xf = x - xi, yf = y - yi, zf = z - zi;
  const u = xf * xf * (3 - 2 * xf), v = yf * yf * (3 - 2 * yf), w = zf * zf * (3 - 2 * zf);
  const L = (a, b, t) => a + (b - a) * t;
  const c = (dx, dy, dz) => hash3(xi + dx, yi + dy, zi + dz, s);
  return L(L(L(c(0, 0, 0), c(1, 0, 0), u), L(c(0, 1, 0), c(1, 1, 0), u), v), L(L(c(0, 0, 1), c(1, 0, 1), u), L(c(0, 1, 1), c(1, 1, 1), u), v), w);
}
const isHex = (c) => typeof c === "string" && /^#[0-9a-f]{6}$/i.test(c);

// procedural surface textures, cached per colour
const TEX = new Map();
function canvasTex(THREE, key, draw, size = 256) {
  const k = key + "|" + THREE.REVISION;
  if (TEX.has(k)) return TEX.get(k);
  const c = document.createElement("canvas"); c.width = c.height = size;
  draw(c.getContext("2d"), size);
  const t = new THREE.CanvasTexture(c); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.colorSpace = THREE.SRGBColorSpace;
  TEX.set(k, t); return t;
}
function woodTex(THREE, base, dark) {
  return canvasTex(THREE, "wood" + base + dark, (g, N) => {
    g.fillStyle = base; g.fillRect(0, 0, N, N);
    const r = rng(7);
    for (let i = 0; i < 70; i++) {
      const y = r() * N, a = 0.08 + r() * 0.22, w = 0.5 + r() * 2.5;
      g.strokeStyle = dark; g.globalAlpha = a; g.lineWidth = w; g.beginPath();
      for (let x = 0; x <= N; x += 8) g.lineTo(x, y + Math.sin(x / N * Math.PI * 2 * 2 + i) * 6 + Math.sin(x / 13 + i) * 1.5);
      g.stroke();
    }
    g.globalAlpha = 0.25; g.fillStyle = dark;
    for (let i = 0; i < 3; i++) { const x = r() * N, y = r() * N; g.beginPath(); g.ellipse(x, y, 10, 4, 0, 0, 7); g.fill(); }
  });
}
function speckleTex(THREE, base, light, dark) {
  return canvasTex(THREE, "stone" + base, (g, N) => {
    g.fillStyle = base; g.fillRect(0, 0, N, N);
    const r = rng(11);
    for (let i = 0; i < 3200; i++) { g.fillStyle = r() < 0.6 ? dark : light; g.globalAlpha = 0.3 + r() * 0.5; const s = 0.6 + r() * 1.8; g.fillRect(r() * N, r() * N, s, s); }
    g.globalAlpha = 0.12;
    for (let i = 0; i < 30; i++) { g.fillStyle = r() < 0.5 ? dark : light; g.beginPath(); g.arc(r() * N, r() * N, 6 + r() * 18, 0, 7); g.fill(); }
  });
}
function clayTex(THREE, base, dark) {
  return canvasTex(THREE, "clay" + base, (g, N) => {
    g.fillStyle = base; g.fillRect(0, 0, N, N);
    const r = rng(5);
    for (let i = 0; i < 900; i++) { g.fillStyle = dark; g.globalAlpha = 0.05 + r() * 0.08; g.fillRect(r() * N, r() * N, 1 + r() * 2, 1 + r() * 2); }
  });
}

// ───────────────────────────────────────────────── geometry
const GEO = new Map();
function baseGeo(THREE, shape, detail) {
  const k = shape + detail;
  if (GEO.has(k)) return GEO.get(k).clone();
  const d = detail;
  let g;
  switch (shape) {
    case "box": g = new THREE.BoxGeometry(2, 2, 2, 6 * d, 6 * d, 6 * d); break;
    case "cylinder": g = new THREE.CylinderGeometry(1, 1, 1, 20 * d, 4 * d); break;           // y scale is the full height
    case "cone": g = new THREE.ConeGeometry(1, 1, 20 * d, 4 * d); break;
    case "torus": g = new THREE.TorusGeometry(0.72, 0.28, 10 * d, 28 * d); break;          // outer radius 1, depth ±0.28
    case "capsule": g = new THREE.CapsuleGeometry(0.5, 1, 6 * d, 14 * d); g.scale(2, 1, 2); break; // half-extents 1
    case "octahedron": g = new THREE.OctahedronGeometry(1, 0); break;
    default: g = new THREE.SphereGeometry(1, 24 * d, 16 * d);
  }
  if (shape === "box") {   // soften the corners a little, as real hands would
    const p = g.attributes.position, v = new THREE.Vector3();
    for (let i = 0; i < p.count; i++) { v.fromBufferAttribute(p, i); const l = v.length(); v.lerp(v.clone().normalize().multiplyScalar(Math.min(l, 1.25)), 0.35); p.setXYZ(i, v.x, v.y, v.z); }
    g.computeVertexNormals();
  }
  GEO.set(k, g);
  return g.clone();
}
// lumps and thumbprints: displace along the normal by noise, more for rough work
function lumpy(THREE, g, amt, seed, scale) {
  if (amt <= 0) return g;
  if (g.index) g = g.toNonIndexed();
  g = mergeByPos(THREE, g);
  g.computeVertexNormals();
  const p = g.attributes.position, n = g.attributes.normal;
  for (let i = 0; i < p.count; i++) {
    const x = p.getX(i), y = p.getY(i), z = p.getZ(i);
    const k = (noise3(x * 2.2 * scale + 3, y * 2.2 * scale, z * 2.2 * scale, seed) - 0.5) * 2 + (noise3(x * 7 * scale, y * 7 * scale, z * 7 * scale, seed + 1) - 0.5) * 0.6;
    p.setXYZ(i, x + n.getX(i) * k * amt, y + n.getY(i) * k * amt, z + n.getZ(i) * k * amt);
  }
  g.computeVertexNormals();
  return g;
}
function mergeByPos(THREE, g) {   // weld duplicate vertices so displacement doesn't tear seams
  const p = g.attributes.position, map = new Map(), idx = [], pos = [];
  for (let i = 0; i < p.count; i++) {
    const k = Math.round(p.getX(i) * 1e4) + "," + Math.round(p.getY(i) * 1e4) + "," + Math.round(p.getZ(i) * 1e4);
    let j = map.get(k);
    if (j === undefined) { j = pos.length / 3; map.set(k, j); pos.push(p.getX(i), p.getY(i), p.getZ(i)); }
    idx.push(j);
  }
  const out = new THREE.BufferGeometry();
  out.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3)); out.setIndex(idx);
  // spherical uv for texture lookups
  const uv = [];
  for (let i = 0; i < pos.length; i += 3) { const x = pos[i], y = pos[i + 1], z = pos[i + 2]; uv.push(0.5 + Math.atan2(z, x) / Math.PI, y * 3.2 + 0.5); }
  out.setAttribute("uv", new THREE.Float32BufferAttribute(uv, 2));
  return out;
}

// v1 parts ({shape, w, h, y, rot, x}) → v2 parts
function partsOf(spec) {
  return (spec.parts || []).map((p) => {
    if (Array.isArray(p.pos)) return p;
    const w = +p.w || 0.3, h = +p.h || 0.3, full = p.shape === "cylinder" || p.shape === "cone";
    return { shape: p.shape || "sphere", pos: [+p.x || 0, +p.y || 0, 0], scale: [w / 2, full ? h : h / 2, w / 2], rot: [0, +p.rot || 0, Math.sin(+p.rot || 0) * 0.12], tone: 0 };
  });
}

// ───────────────────────────────────────────────── materials
function materialsFor(THREE, spec) {
  const mat = spec.material || "clay", fin = spec.finish || "smooth", cols = (spec.colors || []).filter(isHex);
  const def = { clay: ["#c2703d", "#e09f6b", "#9c4a2a"], wood: ["#a47148", "#c08552", "#7f5539"], stone: ["#a8a29e", "#d6d3d1", "#78716c"] }[mat] || ["#c2703d", "#e09f6b", "#9c4a2a"];
  const C = [0, 1, 2].map((i) => cols[i] || def[i]);
  if (mat === "stone") C[0] = "#" + new THREE.Color(C[0]).multiplyScalar(0.85).getHexString();
  const rough = { rough: 0.95, smooth: 0.68, polished: 0.32 }[fin] ?? 0.7;
  const glaze = isHex(spec.glaze) ? spec.glaze : null;
  return C.map((c, tone) => {
    if (mat === "wood") {
      const m = new THREE.MeshStandardMaterial({ color: 0xffffff, map: woodTex(THREE, c, C[2]), roughness: Math.min(0.9, rough + 0.05), metalness: 0 });
      return m;
    }
    if (mat === "stone") return new THREE.MeshStandardMaterial({ color: 0xffffff, map: speckleTex(THREE, c, C[1], C[2]), roughness: rough, metalness: 0 });
    // clay: matte, or glazed glossy where the glaze went (the dark tone stays bare clay)
    if (glaze && tone !== 2) {
      const gc = new THREE.Color(glaze);
      if (tone === 1) gc.lerp(new THREE.Color("#ffffff"), 0.25);
      return new THREE.MeshPhysicalMaterial({ color: gc, roughness: 0.25, clearcoat: 1, clearcoatRoughness: 0.12, metalness: 0 });
    }
    return new THREE.MeshStandardMaterial({ color: 0xffffff, map: clayTex(THREE, c, C[2]), roughness: Math.max(rough, 0.6), metalness: 0 });
  });
}

// ───────────────────────────────────────────────── the sculpture
export function buildSculpture(THREE, spec, opts = {}) {
  spec = spec || {};
  const T = THREE || THREE_NS;
  const group = new T.Group(); group.name = "sculpture";
  const skill = Math.max(0, Math.min(1, spec.skill ?? 0.6)), fin = spec.finish || (skill < 0.35 ? "rough" : skill < 0.75 ? "smooth" : "polished");
  const mats = materialsFor(T, spec), parts = partsOf(spec), r = rng((spec.seed >>> 0) || 77);
  const detail = opts.detail ?? 2;
  const lump = { rough: 0.045, smooth: 0.014, polished: 0.004 }[fin] ?? 0.015;
  const body = new T.Group();
  parts.forEach((p, i) => {
    const sc = p.scale || [0.2, 0.2, 0.2], pos = p.pos || [0, 0.2, 0], rot = p.rot || [0, 0, 0];
    let g = baseGeo(T, p.shape, detail);
    // bake the scale so lumps stay a constant size whatever the part's size
    g.scale(Math.max(0.005, sc[0]), Math.max(0.005, p.shape === "torus" ? sc[1] : sc[1]), Math.max(0.005, p.shape === "torus" ? sc[2] / 0.28 : sc[2]));
    g = lumpy(T, g, lump * Math.min(1, Math.max(0.25, Math.min(sc[0], sc[1], sc[2]) * 4)), ((spec.seed >>> 0) || 1) + i * 31, 1.6);
    const m = new T.Mesh(g, mats[p.tone || 0] || mats[0]);
    m.position.set(pos[0], pos[1], pos[2]);
    m.rotation.set(rot[0] || 0, rot[1] || 0, rot[2] || 0);
    m.castShadow = true; m.receiveShadow = true;
    body.add(m);
  });
  // stand it on the ground: lowest point at y = 0, centred
  body.updateMatrixWorld(true);
  const box = new T.Box3().setFromObject(body);
  if (isFinite(box.min.y)) { body.position.y -= box.min.y; body.position.x -= (box.min.x + box.max.x) / 2; body.position.z -= (box.min.z + box.max.z) / 2; }
  const h = isFinite(box.max.y) ? Math.max(0.05, box.max.y - box.min.y) : 1;
  group.add(body);
  group.userData.height = h;
  group.userData.size = isFinite(box.max.x) ? Math.max(box.max.x - box.min.x, box.max.z - box.min.z) : 1;
  if (opts.plinth) {
    const pw = Math.max(0.5, group.userData.size * 0.75 + 0.12), ph = opts.plinthHeight ?? 0.14;
    const pm = new T.MeshStandardMaterial({ color: opts.plinthColor || 0xd9d4cc, roughness: 0.85, map: speckleTex(T, "#d6d1c8", "#ece8e1", "#a9a39a") });
    const pl = new T.Mesh(new T.BoxGeometry(pw, ph, pw), pm); pl.position.y = ph / 2; pl.receiveShadow = pl.castShadow = true;
    const cap = new T.Mesh(new T.BoxGeometry(pw + 0.05, 0.03, pw + 0.05), pm); cap.position.y = ph - 0.015; cap.castShadow = true;
    body.position.y += ph;
    group.add(pl, cap);
    group.userData.plinth = ph;
  }
  group.userData.dispose = () => group.traverse((o) => { if (o.geometry) o.geometry.dispose(); if (o.material && !o.material.map) o.material.dispose(); });
  return group;
}

// ───────────────────────────────────────────────── a little studio
function studio(T) {
  const scene = new T.Scene();
  const hemi = new T.HemisphereLight(0xf2f0ff, 0x5b4d42, 0.65); scene.add(hemi);
  const key = new T.DirectionalLight(0xfff1dc, 2.2); key.position.set(1.6, 2.6, 2.2); key.castShadow = true;
  key.shadow.mapSize.set(1024, 1024); key.shadow.camera.left = -1.2; key.shadow.camera.right = 1.2; key.shadow.camera.top = 1.6; key.shadow.camera.bottom = -0.4; key.shadow.bias = -0.0008; key.shadow.normalBias = 0.02; key.shadow.radius = 4;
  scene.add(key);
  const rim = new T.DirectionalLight(0xbfd4ff, 1.4); rim.position.set(-2, 1.6, -2); scene.add(rim);
  const fill = new T.DirectionalLight(0xffffff, 0.5); fill.position.set(-2, 0.6, 2); scene.add(fill);
  const ground = new T.Mesh(new T.CircleGeometry(3, 48), new T.ShadowMaterial({ opacity: 0.32 }));
  ground.rotation.x = -Math.PI / 2; ground.receiveShadow = true; scene.add(ground);
  return scene;
}
function envFor(T, renderer) {   // a soft gradient room to reflect in glazes and polish
  if (renderer.__sculptEnv) return renderer.__sculptEnv;
  const pm = new T.PMREMGenerator(renderer), sc = new T.Scene();
  const geo = new T.SphereGeometry(10, 32, 16);
  const mat = new T.ShaderMaterial({ side: T.BackSide, uniforms: {}, vertexShader: "varying vec3 vP; void main(){ vP = position; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.); }",
    fragmentShader: "varying vec3 vP; void main(){ float h = normalize(vP).y; vec3 top = vec3(1.0,0.97,0.92); vec3 bot = vec3(0.25,0.22,0.2); vec3 c = mix(bot, top, smoothstep(-0.3, 0.7, h)); float win = smoothstep(0.85, 0.95, normalize(vP).x) * smoothstep(0.1, 0.4, h); c += win * 2.5; gl_FragColor = vec4(c,1.); }" });
  sc.add(new T.Mesh(geo, mat));
  renderer.__sculptEnv = pm.fromScene(sc, 0.02).texture;
  pm.dispose(); geo.dispose(); mat.dispose();
  return renderer.__sculptEnv;
}
function frameCamera(T, cam, obj, aspect, yaw = 0.6, pitch = 0.25, zoom = 1) {
  const h = obj.userData.height + (obj.userData.plinth || 0), s = Math.max(h, obj.userData.size * 0.9);
  const dist = (s * 0.62) / Math.tan((cam.fov * Math.PI / 180) / 2) * (aspect < 1 ? 1 / aspect : 1) * zoom + 0.4;
  const ty = h * 0.48;
  cam.position.set(Math.sin(yaw) * Math.cos(pitch) * dist, ty + Math.sin(pitch) * dist, Math.cos(yaw) * Math.cos(pitch) * dist);
  cam.lookAt(0, ty, 0); cam.near = 0.05; cam.far = 50; cam.updateProjectionMatrix();
}

// one shared renderer paints every thumbnail
let shared = null;
function sharedRenderer(T) {
  if (shared) return shared;
  const c = document.createElement("canvas");
  const r = new T.WebGLRenderer({ canvas: c, antialias: true, alpha: true, preserveDrawingBuffer: true });
  r.setPixelRatio(1); r.outputColorSpace = T.SRGBColorSpace; r.toneMapping = T.ACESFilmicToneMapping; r.toneMappingExposure = 0.92;
  r.shadowMap.enabled = true; r.shadowMap.type = T.PCFSoftShadowMap;
  shared = r; return r;
}
function backdrop(g, W, H) {
  const bg = g.createRadialGradient(W * 0.5, H * 0.42, 0, W * 0.5, H * 0.5, Math.max(W, H) * 0.75);
  bg.addColorStop(0, "#4a4440"); bg.addColorStop(0.55, "#2d2a2e"); bg.addColorStop(1, "#18171c");
  g.fillStyle = bg; g.fillRect(0, 0, W, H);
  const fl = g.createLinearGradient(0, H * 0.7, 0, H);
  fl.addColorStop(0, "rgba(255,240,220,0)"); fl.addColorStop(1, "rgba(255,240,220,.06)");
  g.fillStyle = fl; g.fillRect(0, H * 0.7, W, H * 0.3);
}
export async function renderTo(canvas, spec, opts = {}) {
  const T = THREE_NS, W = canvas.width, H = canvas.height, r = sharedRenderer(T);
  r.setSize(W, H, false);
  const scene = studio(T); scene.environment = envFor(T, r);
  const obj = buildSculpture(T, spec, { plinth: opts.plinth ?? true });
  scene.add(obj);
  const cam = new T.PerspectiveCamera(30, W / H, 0.05, 50);
  frameCamera(T, cam, obj, W / H, opts.yaw ?? 0.55, 0.2, 0.92);
  r.setClearColor(0x000000, 0); r.clear();
  r.render(scene, cam);
  const g = canvas.getContext("2d");
  backdrop(g, W, H);
  g.drawImage(r.domElement, 0, 0, W, H);
  obj.userData.dispose();
  return canvas;
}

// an orbit view: drag to turn, wheel to come closer, and it turns slowly by itself
export function mountOrbit(container, spec) {
  const T = THREE_NS, r = new T.WebGLRenderer({ antialias: true, alpha: true });
  r.setPixelRatio(Math.min(2, window.devicePixelRatio || 1)); r.outputColorSpace = T.SRGBColorSpace; r.toneMapping = T.ACESFilmicToneMapping;
  r.shadowMap.enabled = true; r.shadowMap.type = T.PCFSoftShadowMap;
  r.domElement.className = "orbit3d"; r.domElement.style.cssText = "width:100%;height:100%;display:block;touch-action:none;cursor:grab";
  container.appendChild(r.domElement);
  const scene = studio(T); scene.environment = envFor(T, r);
  const obj = buildSculpture(T, spec, { plinth: true, detail: 3 }); scene.add(obj);
  const cam = new T.PerspectiveCamera(30, 1, 0.05, 50);
  const st = { yaw: 0.55, pitch: 0.22, zoom: 1.05, vy: 0, drag: null, auto: true, raf: 0, dead: false };
  const resize = () => { const w = Math.max(1, container.clientWidth), h = Math.max(1, container.clientHeight); r.setSize(w, h, false); cam.aspect = w / h; };
  const ro = new ResizeObserver(resize); ro.observe(container); resize();
  const el = r.domElement;
  el.addEventListener("pointerdown", (e) => { st.drag = { x: e.clientX, y: e.clientY }; st.auto = false; el.setPointerCapture(e.pointerId); el.style.cursor = "grabbing"; });
  el.addEventListener("pointermove", (e) => { if (!st.drag) return; const dx = e.clientX - st.drag.x, dy = e.clientY - st.drag.y; st.drag = { x: e.clientX, y: e.clientY }; st.yaw -= dx * 0.01; st.vy = -dx * 0.01; st.pitch = Math.max(-0.2, Math.min(1.2, st.pitch + dy * 0.006)); });
  const up = () => { st.drag = null; el.style.cursor = "grab"; };
  el.addEventListener("pointerup", up); el.addEventListener("pointercancel", up);
  el.addEventListener("wheel", (e) => { e.preventDefault(); st.zoom = Math.max(0.55, Math.min(2.2, st.zoom * (1 + Math.sign(e.deltaY) * 0.08))); }, { passive: false });
  let last = performance.now();
  const loop = (now) => {
    if (st.dead) return;
    const dt = Math.min(0.05, (now - last) / 1000); last = now;
    if (!st.drag) { if (st.auto) st.yaw += dt * 0.35; else { st.yaw += st.vy; st.vy *= 0.92; } }
    frameCamera(T, cam, obj, cam.aspect, st.yaw, st.pitch, st.zoom);
    r.render(scene, cam);
    st.raf = requestAnimationFrame(loop);
  };
  st.raf = requestAnimationFrame(loop);
  return {
    dispose() { st.dead = true; cancelAnimationFrame(st.raf); ro.disconnect(); obj.userData.dispose(); r.dispose(); r.forceContextLoss?.(); el.remove(); },
    renderer: r,
  };
}

export default { buildSculpture, renderTo, mountOrbit };
