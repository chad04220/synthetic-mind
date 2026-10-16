"""Endless deterministic voxel terrain (DESIGN-v5 §2.4).

A chunk column is 16×16×256 blocks stored as ``uint16`` with shape ``(256, 16, 16)`` indexed
``[y, z, x]`` so that the flat C-order index is ``x + 16*(z + 16*y)`` (the wire format).

Everything is a pure function of ``(seed, x, z)``: noise is hash-based gradient noise evaluated
with numpy, so chunks can be generated in any order and always come out the same. Trees that
overhang a chunk border are produced by both chunks from the same per-chunk candidate list.
"""
from __future__ import annotations

import zlib

import numpy as np

from . import blocks as B

H_MAX = 256
SEA = 62
BIOMES = ["plains", "forest", "birch_forest", "taiga", "jungle", "desert", "savanna", "swamp", "mountains",
          "snowy_tundra", "ocean", "beach", "river"]
BI = {n: i for i, n in enumerate(BIOMES)}
# rough air temperature (°C) per biome at sea level
BIOME_TEMP = {"plains": 18, "forest": 16, "birch_forest": 15, "taiga": 4, "jungle": 28, "desert": 34, "savanna": 28,
              "swamp": 20, "mountains": 8, "snowy_tundra": -8, "ocean": 14, "beach": 22, "river": 15}

_M32 = 0xFFFFFFFF
I = B.ID


def _seed32(seed, salt) -> int:
    h = zlib.crc32(f"{seed}:{salt}".encode())
    return h & 0x7FFFFFFF


def _hash(ix, iy, iz, seed):
    h = (ix * 0x27D4EB2D + iy * 0x165667B1 + iz * 0x1B873593 + seed * 0x5BD1E995) & _M32
    h ^= h >> 15
    h = (h * 0x2C1B3C6D) & _M32
    h ^= h >> 12
    h = (h * 0x297A2D39) & _M32
    h ^= h >> 15
    return h


def _fade(t):
    return t * t * t * (t * (t * 6 - 15) + 10)


_G2 = np.array([[1, 1], [-1, 1], [1, -1], [-1, -1], [1.4, 0], [-1.4, 0], [0, 1.4], [0, -1.4]], dtype=np.float64)
_G3 = np.array([[1, 1, 0], [-1, 1, 0], [1, -1, 0], [-1, -1, 0], [1, 0, 1], [-1, 0, 1], [1, 0, -1], [-1, 0, -1],
                [0, 1, 1], [0, -1, 1], [0, 1, -1], [0, -1, -1], [1, 1, 0], [-1, 1, 0], [0, -1, 1], [0, -1, -1]],
               dtype=np.float64)


def perlin2(x, z, seed):
    xi = np.floor(x)
    zi = np.floor(z)
    xf, zf = x - xi, z - zi
    xi = xi.astype(np.int64)
    zi = zi.astype(np.int64)

    def g(ix, iz, dx, dz):
        k = _hash(ix, iz, 0, seed) & 7
        return _G2[k, 0] * dx + _G2[k, 1] * dz

    u, v = _fade(xf), _fade(zf)
    a = g(xi, zi, xf, zf)
    b = g(xi + 1, zi, xf - 1, zf)
    c = g(xi, zi + 1, xf, zf - 1)
    d = g(xi + 1, zi + 1, xf - 1, zf - 1)
    ab = a + u * (b - a)
    cd = c + u * (d - c)
    return (ab + v * (cd - ab)) * 0.9


def perlin3(x, y, z, seed):
    xi, yi, zi = np.floor(x), np.floor(y), np.floor(z)
    xf, yf, zf = x - xi, y - yi, z - zi
    xi, yi, zi = xi.astype(np.int64), yi.astype(np.int64), zi.astype(np.int64)
    u, v, w = _fade(xf), _fade(yf), _fade(zf)

    def g(ix, iy, iz, dx, dy, dz):
        k = _hash(ix, iy, iz, seed) & 15
        return _G3[k, 0] * dx + _G3[k, 1] * dy + _G3[k, 2] * dz

    out = 0
    acc = []
    for oz in (0, 1):
        for oy in (0, 1):
            n0 = g(xi, yi + oy, zi + oz, xf, yf - oy, zf - oz)
            n1 = g(xi + 1, yi + oy, zi + oz, xf - 1, yf - oy, zf - oz)
            acc.append(n0 + u * (n1 - n0))
    y0 = acc[0] + v * (acc[1] - acc[0])
    y1 = acc[2] + v * (acc[3] - acc[2])
    out = y0 + w * (y1 - y0)
    return out


def fbm2(x, z, seed, octaves=3, lac=2.0, gain=0.5):
    tot, amp, norm, f = 0.0, 1.0, 0.0, 1.0
    for o in range(octaves):
        tot = tot + amp * perlin2(x * f, z * f, seed + o * 1013)
        norm += amp
        amp *= gain
        f *= lac
    return tot / norm


def _smooth(t):
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3 - 2 * t)


class Terrain:
    """The generator for one seed. ``generate(cx, cz)`` → (blocks, containers, spawns)."""

    def __init__(self, seed: int):
        self.seed = int(seed)
        s = self.s = {k: _seed32(seed, k) for k in ("cont", "mnt", "det", "riv", "lake", "temp", "hum", "cave1",
                                                    "cave2", "cave3", "ore", "var", "over", "birch", "deep")}
        self._s = s
        self.spawn_chunk, self.cabin = self._find_spawn()
        x0, y0, z0 = self.cabin
        self.spawn = (x0 + 3.5, float(y0 + 1), z0 + 9.5)

    # ------------------------------------------------------------------ columns
    def columns(self, xs, zs):
        """Pure per-column data for arbitrary coordinate arrays: H (surface y), biome, mnt."""
        s = self.s
        x = np.asarray(xs, dtype=np.float64)
        z = np.asarray(zs, dtype=np.float64)
        c = fbm2(x / 700.0, z / 700.0, s["cont"], 4) * 1.7 + 0.12
        e = fbm2(x / 380.0, z / 380.0, s["mnt"], 3)
        d = fbm2(x / 70.0, z / 70.0, s["det"], 3)
        mnt = np.maximum(0.0, e - 0.22) * 190.0 * _smooth((c + 0.1) / 0.3)
        h_land = 64.0 + d * 6.0 + np.maximum(c + 0.3, 0) * 10.0 + mnt
        h_ocean = 62.0 + (c + 0.3) * 70.0
        t = _smooth((c + 0.32) / 0.1)
        h = h_ocean * (1 - t) + h_land * t
        # lakes: depressions below sea level inland
        lk = fbm2(x / 160.0, z / 160.0, s["lake"], 2)
        h = h - np.maximum(0.0, lk - 0.33) * 70.0 * (mnt < 4)
        # rivers
        r = np.abs(fbm2(x / 520.0, z / 520.0, s["riv"], 3))
        rw = 0.028
        k = np.clip(r / rw, 0, 1)
        river_on = (r < rw) & (t > 0.5)
        h = np.where(river_on, np.minimum(h, 57.0 + (k ** 1.5) * (h - 57.0)), h)
        H = np.clip(np.floor(h), 8, 230).astype(np.int64)
        temp = fbm2(x / 900.0, z / 900.0, s["temp"], 2) * 1.4 - np.maximum(0, H - 95) / 90.0
        hum = fbm2(x / 800.0, z / 800.0, s["hum"], 2) * 1.4
        bv = fbm2(x / 200.0, z / 200.0, s["birch"], 1)
        biome = np.full(H.shape, BI["plains"], dtype=np.int64)
        temperate = np.select([hum > 0.32, hum > 0.06, hum > -0.12], [BI["swamp"], BI["forest"], BI["forest"]],
                              BI["plains"])
        temperate = np.where((temperate == BI["forest"]) & (bv > 0.25), BI["birch_forest"], temperate)
        temperate = np.where((temperate == BI["swamp"]) & (H > 67), BI["forest"], temperate)
        hot = np.select([hum < -0.12, hum < 0.18], [BI["desert"], BI["savanna"]], BI["jungle"])
        biome = np.select([temp < -0.38, temp < -0.16, temp > 0.3], [BI["snowy_tundra"], BI["taiga"], hot],
                          temperate)
        biome = np.where(mnt > 12, BI["mountains"], biome)
        beach = (c < -0.12) & (H <= 64) & (H >= 59)
        biome = np.where(beach, BI["beach"], biome)
        biome = np.where(river_on & (H < SEA), BI["river"], biome)
        biome = np.where((t < 0.5) & (H < SEA - 1), BI["ocean"], biome)
        return H, biome, mnt

    def biome_at(self, x, z) -> str:
        H, b, _ = self.columns(np.array([x]), np.array([z]))
        return BIOMES[int(b[0])]

    def height_at(self, x, z) -> int:
        H, _, _ = self.columns(np.array([x]), np.array([z]))
        return int(H[0])

    # ------------------------------------------------------------------ spawn
    def _find_spawn(self):
        good = {BI["plains"], BI["forest"], BI["birch_forest"], BI["savanna"], BI["taiga"]}
        cands = [(0, 0)]
        for r in range(1, 40):
            for i in range(-r, r + 1):
                cands += [(i, -r), (i, r)]
            for i in range(-r + 1, r):
                cands += [(-r, i), (r, i)]
        ox = np.arange(2, 13)
        gx, gz = np.meshgrid(ox, ox)
        for cx, cz in cands:
            H, b, _ = self.columns(gx + cx * 16, gz + cz * 16)
            if int(H.min()) < SEA + 2 or int(H.max()) - int(H.min()) > 4:
                continue
            if not set(np.unique(b).tolist()) <= good:
                continue
            y0 = int(np.round(np.median(H)))
            return (cx, cz), (cx * 16 + 4, y0, cz * 16 + 2)
        return (0, 0), (4, 70, 2)

    # ------------------------------------------------------------------ generation
    def generate(self, cx: int, cz: int):
        """→ (blocks uint16[256,16,16], containers {(x,y,z): dict}, spawns [dict])."""
        s = self.s
        rng = np.random.default_rng([self.seed & 0xFFFFFFFF, cx & 0xFFFFFFFF, cz & 0xFFFFFFFF, 7])
        lx = np.arange(16)
        gx, gz = np.meshgrid(lx + cx * 16, lx + cz * 16)  # [z, x]
        H, biome, mnt = self.columns(gx, gz)
        y = np.arange(H_MAX).reshape(-1, 1, 1)
        Hb = H[None]
        top = np.full(H.shape, I["grass"], dtype=np.uint16)
        fill = np.full(H.shape, I["dirt"], dtype=np.uint16)
        bm = biome
        under = H < SEA
        sandy = (bm == BI["desert"]) | (bm == BI["beach"])
        top[sandy] = I["sand"]
        fill[sandy] = I["sand"]
        top[bm == BI["snowy_tundra"]] = I["snow"]
        rough = perlin2(gx / 9.0, gz / 9.0, s["var"])
        mtop = (bm == BI["mountains"])
        top[mtop & (H > 105)] = I["stone"]
        fill[mtop & (H > 105)] = I["stone"]
        top[mtop & (H > 105) & (rough > 0.25)] = I["gravel"]
        top[mtop & (H > 135)] = I["snow"]
        top[(bm == BI["swamp"]) & (rough > 0.2)] = I["mud"]
        top[(bm == BI["jungle"]) & (rough > 0.45)] = I["moss"]
        top[(bm == BI["savanna"]) & (rough > 0.5)] = I["dirt"]
        uw_top = np.where(rough > 0.3, I["gravel"], np.where(rough < -0.35, I["clay"], I["sand"])).astype(np.uint16)
        uw_top = np.where((bm == BI["swamp"]) | (bm == BI["river"]) & (rough > 0.1), I["dirt"], uw_top)
        uw_top = np.where(bm == BI["ocean"], np.where(rough > 0.35, I["gravel"], I["sand"]), uw_top).astype(np.uint16)
        top = np.where(under | ((H <= SEA) & ~sandy & (bm != BI["swamp"]) & (rough > 0.0)), uw_top, top)
        top = np.where((H == SEA) & (bm == BI["swamp"]), I["grass"], top).astype(np.uint16)
        fill = np.where(under & (top == I["sand"]), I["sand"], fill).astype(np.uint16)
        blocks = np.zeros((H_MAX, 16, 16), dtype=np.uint16)
        deep_line = 18 + (perlin2(gx / 30.0, gz / 30.0, s["deep"]) * 4).astype(np.int64)
        blocks[:] = np.where(y < Hb - 3, np.where(y < deep_line[None], I["deepstone"], I["stone"]),
                             np.where(y < Hb, fill[None], np.where(y == Hb, top[None],
                                                                   np.where(y <= SEA, I["water"], 0))))
        # sandstone under sand
        blocks[:] = np.where((y >= Hb - 6) & (y < Hb - 3) & sandy[None] & ~under[None], I["sandstone"], blocks)
        cold = (bm == BI["snowy_tundra"]) | ((bm == BI["taiga"]) & (rough > 0.3))
        if cold.any() and under.any():
            iz, ix = np.nonzero(cold & under)
            blocks[SEA, iz, ix] = I["ice"]
        # 3D noise on a coarse grid (4×4×4), trilinear upsample
        lo_x = np.arange(5) * 4 + cx * 16
        lo_z = np.arange(5) * 4 + cz * 16
        lo_y = np.arange(65) * 4
        LY, LZ, LX = np.meshgrid(lo_y, lo_z, lo_x, indexing="ij")
        n1 = _up(perlin3(LX / 48.0, LY / 32.0, LZ / 48.0, s["cave1"]))
        n2 = _up(perlin3(LX / 48.0, LY / 32.0, LZ / 48.0, s["cave2"]))
        n3 = _up(perlin3(LX / 30.0, LY / 22.0, LZ / 30.0, s["cave3"]))
        # stone variants
        stoneish = blocks == I["stone"]
        blocks[stoneish & (n3 > 0.42) & (y > 30)] = I["granite"]
        blocks[(blocks == I["deepstone"]) & (n3 < -0.45)] = I["basalt"]
        # mountain overhangs and hollows
        if (mnt > 12).any():
            mm = (mnt > 12)[None]
            over = (y > Hb) & (y <= Hb + 9) & mm & (n3 > 0.3 + (y - Hb) * 0.045) & (blocks == 0)
            blocks[over] = I["stone"]
            hol = (y > Hb - 8) & (y <= Hb) & mm & (n3 < -0.42)
            blocks[hol] = 0
        # caves
        spaghetti = (n1 * n1 + n2 * n2) < 0.0045
        cheese = n3 > 0.55
        entrance = perlin2(gx / 40.0, gz / 40.0, s["over"])[None] > 0.55
        lim = np.where(under, H - 9, np.where(entrance[0], H + 1, H - 5))[None]
        cave = (spaghetti | cheese) & (y >= 4) & (y < lim) & (blocks != I["water"])
        blocks[cave] = 0
        lava_fill = cave & (y <= 10)
        blocks[lava_fill] = I["lava"]
        # bedrock
        blocks[0] = I["bedrock"]
        br = rng.random((3, 16, 16))
        for k in range(1, 4):
            blocks[k][br[k - 1] < (0.8 - k * 0.25)] = I["bedrock"]
        self._ores(blocks, rng)
        containers, spawns = {}, []
        self._plants(blocks, H, biome, cx, cz, rng, spawns)
        self._trees(blocks, cx, cz)
        self._ruins(blocks, H, biome, cx, cz, containers)
        if (cx, cz) == self.spawn_chunk:
            self._cabin(blocks, cx, cz, containers)
        self._animals(blocks, H, biome, cx, cz, rng, spawns)
        return blocks, containers, spawns

    # ------------------------------------------------------------------ ores
    _ORES = [("coal_ore", 18, 9, 5, 130), ("iron_ore", 12, 6, 5, 70), ("copper_ore", 8, 7, 20, 90),
             ("gold_ore", 3, 5, 5, 34), ("spark_ore", 5, 5, 5, 18), ("diamond_ore", 1, 4, 5, 16),
             ("crystal", 1, 3, 6, 30), ("gravel", 4, 12, 5, 80), ("clay", 2, 8, 40, 70)]

    def _ores(self, blocks, rng):
        hosts = np.zeros(B.N, dtype=bool)
        for n in ("stone", "deepstone", "granite", "basalt"):
            hosts[I[n]] = True
        for name, veins, size, ylo, yhi in self._ORES:
            if name == "diamond_ore" and rng.random() > 0.7:
                continue
            for _ in range(veins):
                c = np.array([rng.integers(1, 15), rng.integers(ylo, yhi), rng.integers(1, 15)])
                steps = rng.integers(-1, 2, size=(size, 3))
                pts = c + np.cumsum(steps, axis=0)
                pts[:, 0] = np.clip(pts[:, 0], 0, 15)
                pts[:, 2] = np.clip(pts[:, 2], 0, 15)
                pts[:, 1] = np.clip(pts[:, 1], 1, 254)
                ys, xs, zs = pts[:, 1], pts[:, 0], pts[:, 2]
                ok = hosts[blocks[ys, zs, xs]]
                blocks[ys[ok], zs[ok], xs[ok]] = I[name]

    # ------------------------------------------------------------------ plants
    def _plants(self, blocks, H, biome, cx, cz, rng, spawns):
        r = rng.random((6, 16, 16))
        Hc = np.clip(H + 1, 0, 255)
        zz, xx = np.meshgrid(np.arange(16), np.arange(16), indexing="ij")
        topb = blocks[H, zz, xx]
        above = blocks[Hc, zz, xx]
        grassy = (topb == I["grass"]) & (above == 0)
        bm = biome
        dens_grass = np.select([bm == BI["plains"], bm == BI["savanna"], bm == BI["forest"], bm == BI["birch_forest"],
                                bm == BI["jungle"], bm == BI["swamp"], bm == BI["taiga"]],
                               [0.3, 0.35, 0.12, 0.12, 0.3, 0.15, 0.08], 0.03)
        place = np.zeros((16, 16), dtype=np.uint16)
        fern_b = (bm == BI["taiga"]) | (bm == BI["jungle"])
        place[grassy & (r[0] < dens_grass)] = I["tall_grass"]
        place[grassy & (r[0] < dens_grass * 0.4) & fern_b] = I["fern"]
        flowers = [I[f"{c}_flower"] for c in B.FLOWERS]
        fl_d = np.where((bm == BI["plains"]) | (bm == BI["forest"]) | (bm == BI["birch_forest"]), 0.025, 0.004)
        fl = grassy & (r[1] < fl_d)
        if fl.any():
            # flower colour patches by position
            idx = ((cx * 7 + cz * 13 + (r[2] * 2).astype(int)) % len(flowers))
            place[fl] = np.array(flowers, dtype=np.uint16)[np.broadcast_to(idx, fl.shape)[fl]]
        mush = grassy & (r[1] > 0.993) & ((bm == BI["swamp"]) | (bm == BI["forest"]) | (bm == BI["taiga"]))
        place[mush] = np.where(r[2][mush] < 0.5, I["red_mushroom"], I["brown_mushroom"])
        place[grassy & (r[3] < 0.012) & (bm == BI["taiga"])] = I["berry_bush_ripe"]
        place[grassy & (r[3] > 0.998) & (bm == BI["plains"])] = I["pumpkin"]
        place[grassy & (r[3] > 0.995) & (bm == BI["jungle"])] = I["melon"]
        iz, ix = np.nonzero(place)
        if len(iz):
            blocks[Hc[iz, ix], iz, ix] = place[iz, ix]
        # cactus
        dry = (topb == I["sand"]) & (above == 0) & (bm == BI["desert"]) & (r[4] < 0.012)
        for z, x in zip(*np.nonzero(dry)):
            if 0 < x < 15 and 0 < z < 15:
                h = 1 + int(r[5, z, x] * 3)
                blocks[H[z, x] + 1:H[z, x] + 1 + h, z, x] = I["cactus"]
        # sugarcane by water
        wet = np.zeros((16, 16), dtype=bool)
        water_top = blocks[SEA, zz, xx] == I["water"]
        wet[1:, :] |= water_top[:-1, :]
        wet[:-1, :] |= water_top[1:, :]
        wet[:, 1:] |= water_top[:, :-1]
        wet[:, :-1] |= water_top[:, 1:]
        cane = wet & (H == SEA) & ((topb == I["sand"]) | (topb == I["grass"]) | (topb == I["dirt"])) & \
            (above == 0) & (r[4] > 0.85)
        for z, x in zip(*np.nonzero(cane)):
            h = 1 + int(r[5, z, x] * 3)
            blocks[SEA + 1:SEA + 1 + h, z, x] = I["sugarcane"]
        # water plants
        sw = water_top & (bm == BI["swamp"]) & (r[2] < 0.08) & (blocks[SEA + 1, zz, xx] == 0)
        blocks[SEA + 1][sw] = I["lily_pad"]
        oc = (bm == BI["ocean"]) & (H < SEA - 2) & (r[3] < 0.08)
        for z, x in zip(*np.nonzero(oc)):
            hb = H[z, x]
            if blocks[hb + 1, z, x] == I["water"]:
                if r[4, z, x] < 0.3 and hb < SEA - 6:
                    blocks[hb + 1, z, x] = I["coral"]
                else:
                    k = 1 + int(r[5, z, x] * min(6, SEA - hb - 2))
                    blocks[hb + 1:hb + 1 + k, z, x] = I["kelp"]
        return spawns

    # ------------------------------------------------------------------ trees
    _TREE_DENS = {"forest": 0.65, "birch_forest": 0.6, "jungle": 1.0, "taiga": 0.55, "plains": 0.035,
                  "savanna": 0.07, "swamp": 0.3, "snowy_tundra": 0.05, "mountains": 0.08}

    def _tree_cands(self, ncx, ncz):
        rng = np.random.default_rng([self.seed & 0xFFFFFFFF, ncx & 0xFFFFFFFF, ncz & 0xFFFFFFFF, 3])
        n = 14
        lx = rng.integers(0, 16, n)
        lz = rng.integers(0, 16, n)
        roll = rng.random(n)
        var = rng.integers(0, 1 << 30, n)
        wx, wz = lx + ncx * 16, lz + ncz * 16
        H, bm, mnt = self.columns(wx, wz)
        out = []
        cab = self.cabin
        for i in range(n):
            bname = BIOMES[int(bm[i])]
            d = self._TREE_DENS.get(bname, 0.0)
            if roll[i] >= d or H[i] < SEA:
                continue
            if bname == "mountains" and H[i] > 110:
                continue
            if abs(wx[i] - (cab[0] + 3)) < 10 and abs(wz[i] - (cab[2] + 4)) < 12:
                continue
            if bname in ("forest", "plains", "swamp"):
                kind = "oak"
            elif bname == "birch_forest":
                kind = "birch"
            elif bname in ("taiga", "snowy_tundra", "mountains"):
                kind = "pine"
            elif bname == "jungle":
                kind = "jungle" if roll[i] < 0.5 else "oak"
            else:
                kind = "acacia"
            if bname == "forest" and (var[i] % 5 == 0):
                kind = "birch"
            out.append((int(wx[i]), int(H[i]) + 1, int(wz[i]), kind, int(var[i]), bname == "swamp"))
        return out

    def _trees(self, blocks, cx, cz):
        ok_base = np.zeros(B.N, dtype=bool)
        for n in ("grass", "dirt", "snow", "moss", "mud"):
            ok_base[I[n]] = True
        can_leaf = np.zeros(B.N, dtype=bool)
        for b in B.BLOCKS:
            if b["replaceable"] and not b["liquid"] or b["name"] in ("air",) or b["category"] == "life" and \
                    b["shape"] == "cross":
                can_leaf[b["id"]] = True
        can_log = can_leaf.copy()
        for l in B.LEAVES:
            can_log[l] = True
        for ncx in (cx - 1, cx, cx + 1):
            for ncz in (cz - 1, cz, cz + 1):
                for (wx, wy, wz, kind, var, vines) in self._tree_cands(ncx, ncz):
                    lx, lz = wx - cx * 16, wz - cz * 16
                    if 0 <= lx < 16 and 0 <= lz < 16:
                        if not ok_base[blocks[wy - 1, lz, lx]] or blocks[wy, lz, lx] not in (0, I["tall_grass"],
                                                                                          I["fern"]):
                            continue
                    offs, ids = _tree_template(kind, var, vines)
                    xs = offs[:, 0] + lx
                    ys = offs[:, 1] + wy
                    zs = offs[:, 2] + lz
                    m = (xs >= 0) & (xs < 16) & (zs >= 0) & (zs < 16) & (ys > 0) & (ys < 255)
                    if not m.any():
                        continue
                    xs, ys, zs, idv = xs[m], ys[m], zs[m], ids[m]
                    cur = blocks[ys, zs, xs]
                    islog = np.isin(idv, B.LOGS)
                    w = np.where(islog, can_log[cur], can_leaf[cur])
                    blocks[ys[w], zs[w], xs[w]] = idv[w]

    # ------------------------------------------------------------------ ruins
    def _ruin_site(self, rx, rz):
        rng = np.random.default_rng([self.seed & 0xFFFFFFFF, rx & 0xFFFFFFFF, rz & 0xFFFFFFFF, 11])
        if rng.random() > 0.55:
            return None
        ccx, ccz = rx * 4 + int(rng.integers(0, 4)), rz * 4 + int(rng.integers(0, 4))
        ox, oz = int(rng.integers(1, 8)), int(rng.integers(1, 8))
        size = int(rng.integers(5, 8))
        return ccx, ccz, ox, oz, size, int(rng.integers(0, 1 << 30))

    def ruins_near(self, x, z, radius=256):
        out = []
        for rx in range((x - radius) // 64, (x + radius) // 64 + 1):
            for rz in range((z - radius) // 64, (z + radius) // 64 + 1):
                site = self._ruin_site(rx, rz)
                if site:
                    ccx, ccz, ox, oz, size, _ = site
                    out.append((ccx * 16 + ox + size // 2, ccz * 16 + oz + size // 2))
        return out

    def _ruins(self, blocks, H, biome, cx, cz, containers):
        site = self._ruin_site(cx // 4, cz // 4)
        if not site or (site[0], site[1]) != (cx, cz) or (cx, cz) == self.spawn_chunk:
            return
        _, _, ox, oz, size, var = site
        sub_b = biome[oz:oz + size, ox:ox + size]
        if np.isin(sub_b, [BI["ocean"], BI["river"]]).any():
            return
        sub = H[oz:oz + size, ox:ox + size]
        y0 = int(np.median(sub))
        if y0 < SEA:
            return
        r = np.random.default_rng(var)
        for z in range(oz, oz + size):
            for x in range(ox, ox + size):
                blocks[H[z, x] + 1:y0, z, x] = I["cobblestone"]
                blocks[y0 + 1:y0 + 7, z, x] = 0
                blocks[y0, z, x] = I["mossy_cobblestone"] if r.random() < 0.3 else I["stone_bricks"]
        wall_h = int(r.integers(2, 4))
        for z in range(oz, oz + size):
            for x in range(ox, ox + size):
                edge = x in (ox, ox + size - 1) or z in (oz, oz + size - 1)
                if not edge:
                    continue
                hh = wall_h - (1 if r.random() < 0.35 else 0) - (1 if r.random() < 0.2 else 0)
                for k in range(1, hh + 1):
                    blocks[y0 + k, z, x] = [I["stone_bricks"], I["mossy_cobblestone"], I["cobblestone"]][
                        int(r.integers(0, 3))]
        # doorway
        mx = ox + size // 2
        blocks[y0 + 1:y0 + 4, oz + size - 1, mx] = 0
        cx_, cz_ = ox + 1, oz + 1
        blocks[y0 + 1, cz_, cx_] = I["chest"]
        loot_pool = [("iron_ingot", 1, 4), ("coal", 2, 8), ("bread", 1, 3), ("wheat_seeds", 2, 6), ("book", 1, 1),
                     ("spark_dust", 2, 6), ("gold_ingot", 1, 3), ("diamond", 1, 1), ("oak_sapling", 1, 3),
                     ("string", 1, 4), ("raw_copper", 2, 5), ("apple", 1, 3), ("bone", 1, 3), ("torch", 2, 6)]
        slots = [None] * 27
        for i in range(int(r.integers(3, 7))):
            name, a, b = loot_pool[int(r.integers(0, len(loot_pool)))]
            if name == "diamond" and r.random() > 0.3:
                continue
            slots[int(r.integers(0, 27))] = {"item": name, "count": int(r.integers(a, b + 1))}
        containers[(cx * 16 + cx_, y0 + 1, cz * 16 + cz_)] = {"kind": "chest", "slots": slots}
        if r.random() < 0.5:
            blocks[y0 + 1, oz + size - 2, ox + size - 2] = I["torch"]

    # ------------------------------------------------------------------ the cabin
    def _cabin(self, blocks, cx, cz, containers):
        X0, y0, Z0 = self.cabin
        ox, oz = X0 - cx * 16, Z0 - cz * 16
        # yard: flatten local [ox-2, ox+9) × [oz-1, oz+11)
        for z in range(max(0, oz - 1), min(16, oz + 11)):
            for x in range(max(0, ox - 2), min(16, ox + 9)):
                col = blocks[:, z, x]
                col[y0 + 1:y0 + 12] = 0
                seg = col[y0 - 5:y0]
                seg[(seg == 0) | B.np_liquid[seg]] = I["dirt"]
                col[y0] = I["grass"]
        P, L, G = I["oak_planks"], I["oak_log"], I["glass"]
        for dz in range(7):
            for dx in range(7):
                x, z = ox + dx, oz + dz
                blocks[y0, z, x] = P
                blocks[y0 + 4, z, x] = P
                edge = dx in (0, 6) or dz in (0, 6)
                corner = dx in (0, 6) and dz in (0, 6)
                if edge:
                    for k in (1, 2, 3):
                        blocks[y0 + k, z, x] = L if corner else P
        # roof trim
        for dz in range(1, 6):
            for dx in range(1, 6):
                blocks[y0 + 5, oz + dz, ox + dx] = P if (dx in (1, 5) or dz in (1, 5)) else L
        # door (south wall dz=6, dx=3)
        blocks[y0 + 1, oz + 6, ox + 3] = I["door_lower"]
        blocks[y0 + 2, oz + 6, ox + 3] = I["door_upper"]
        # windows
        for (dx, dz) in ((0, 3), (6, 3), (3, 0), (1, 6), (5, 6)):
            blocks[y0 + 2, oz + dz, ox + dx] = G
        # inside
        blocks[y0 + 1, oz + 1, ox + 1] = I["crafting_table"]
        blocks[y0 + 1, oz + 1, ox + 2] = I["furnace"]
        blocks[y0 + 1, oz + 1, ox + 3] = I["chest"]
        blocks[y0 + 1, oz + 1, ox + 5] = I["bed"]
        blocks[y0 + 1, oz + 5, ox + 1] = I["torch"]
        blocks[y0 + 1, oz + 5, ox + 5] = I["torch"]
        # outside: torches flanking the door, a path
        blocks[y0 + 1, oz + 7, ox + 1] = I["torch"]
        blocks[y0 + 1, oz + 7, ox + 5] = I["torch"]
        for dz in (7, 8):
            blocks[y0, oz + dz, ox + 3] = I["path"]
        slots = [None] * 27
        for i, (name, n) in enumerate([("bread", 6), ("apple", 4), ("torch", 8), ("wheat_seeds", 8), ("book", 1),
                                       ("oak_sapling", 2)]):
            slots[i] = {"item": name, "count": n}
        containers[(X0 + 3, y0 + 1, Z0 + 1)] = {"kind": "chest", "slots": slots}
        containers[(X0 + 2, y0 + 1, Z0 + 1)] = _new_furnace()

    # ------------------------------------------------------------------ animals
    def _animals(self, blocks, H, biome, cx, cz, rng, spawns):
        bname = BIOMES[int(biome[8, 8])]
        r = rng.random()
        land = {"plains": ["cow", "sheep", "pig", "chicken"], "forest": ["pig", "chicken", "sheep", "bee"],
                "birch_forest": ["chicken", "sheep", "bee"], "savanna": ["cow", "sheep"], "jungle": ["chicken", "pig"],
                "taiga": ["rabbit", "wolf", "sheep"], "snowy_tundra": ["rabbit", "bear"], "desert": ["rabbit"],
                "swamp": ["slime", "chicken"], "mountains": ["sheep", "rabbit"]}
        if bname in ("ocean", "river") or (H[8, 8] < SEA and r < 0.3):
            if r < 0.25:
                for k in range(int(rng.integers(2, 5))):
                    spawns.append({"kind": "fish", "x": cx * 16 + 4.5 + k, "y": SEA - 1.5, "z": cz * 16 + 8.5})
            return
        kinds = land.get(bname)
        if not kinds or r > 0.12:
            return
        kind = kinds[int(rng.integers(0, len(kinds)))]
        if kind == "slime":
            return
        for k in range(int(rng.integers(2, 4)) if kind not in ("bear", "wolf") else 1):
            lx, lz = int(rng.integers(2, 14)), int(rng.integers(2, 14))
            col = blocks[:, lz, lx]
            nz = np.nonzero(B.np_solid[col])[0]
            if not len(nz):
                continue
            yy = int(nz[-1]) + 1
            if yy <= SEA:
                continue
            spawns.append({"kind": kind, "x": cx * 16 + lx + 0.5, "y": float(yy), "z": cz * 16 + lz + 0.5})


def _new_furnace():
    return {"kind": "furnace", "input": None, "fuel": None, "output": None, "burn": 0.0, "burn_max": 0.0,
            "progress": 0.0}


# ---------------------------------------------------------------------- upsampling
_W4 = (np.arange(16) % 4) / 4.0
_I4 = np.arange(16) // 4
_WY = (np.arange(256) % 4) / 4.0
_IY = np.arange(256) // 4


def _up(a):
    """(65, 5, 5) coarse samples [y, z, x] → (256, 16, 16) by trilinear interpolation."""
    a = a[:, :, _I4] * (1 - _W4) + a[:, :, _I4 + 1] * _W4
    a = a[:, _I4, :] * (1 - _W4)[None, :, None] + a[:, _I4 + 1, :] * _W4[None, :, None]
    a = a[_IY] * (1 - _WY)[:, None, None] + a[_IY + 1] * _WY[:, None, None]
    return a


# ---------------------------------------------------------------------- tree templates
_TPL_CACHE: dict = {}


def _tree_template(kind, var, vines):
    key = (kind, var % 6, bool(vines))
    t = _TPL_CACHE.get(key)
    if t is not None:
        return t
    r = np.random.default_rng((var % 6) * 31 + len(kind) * 7 + int(vines))
    log, leaf = I[f"{kind}_log"], I[f"{kind}_leaves"]
    pts = {}
    if kind in ("oak", "birch"):
        h = int(r.integers(4, 7)) + (1 if kind == "birch" else 0)
        for dy in range(h - 2, h + 2):
            rad = 2 if dy < h else 1
            for dx in range(-rad, rad + 1):
                for dz in range(-rad, rad + 1):
                    if abs(dx) == rad and abs(dz) == rad and (dy >= h or r.random() < 0.5):
                        continue
                    pts[(dx, dy, dz)] = leaf
        for dy in range(h):
            pts[(0, dy, 0)] = log
        if vines:
            for (dx, dy, dz), v in list(pts.items()):
                if v == leaf and abs(dx) == 2 and r.random() < 0.3:
                    for k in range(1, 4):
                        pts.setdefault((dx + (1 if dx > 0 else -1), dy - k + 1, dz), I["vines"])
    elif kind == "pine":
        h = int(r.integers(7, 11))
        top = h + 1
        for dy in range(2, top + 1):
            rad = max(0, min(3, (top - dy + 1) // 2)) if (dy % 2 == 0 or dy == top) else max(0, (top - dy) // 3)
            for dx in range(-rad, rad + 1):
                for dz in range(-rad, rad + 1):
                    if abs(dx) + abs(dz) <= rad + 1:
                        pts[(dx, dy, dz)] = leaf
        pts[(0, top, 0)] = leaf
        for dy in range(h):
            pts[(0, dy, 0)] = log
    elif kind == "jungle":
        h = int(r.integers(9, 14))
        for dy in range(h - 3, h + 2):
            rad = 3 if dy < h else 2
            for dx in range(-rad, rad + 1):
                for dz in range(-rad, rad + 1):
                    if dx * dx + dz * dz <= rad * rad + 1:
                        pts[(dx, dy, dz)] = leaf
        for dy in range(h):
            pts[(0, dy, 0)] = log
        for (dx, dy, dz), v in list(pts.items()):
            if v == leaf and dx * dx + dz * dz >= 8 and dy == h - 3 and r.random() < 0.4:
                for k in range(1, 5):
                    pts.setdefault((dx, dy - k, dz), I["vines"])
    else:  # acacia: a bent trunk and a flat canopy
        h = int(r.integers(5, 7))
        sx = 1 if r.random() < 0.5 else -1
        for dy in range(h):
            pts[(sx if dy >= h - 2 else 0, dy, 0)] = log
        cx = sx
        for dx in range(-2, 3):
            for dz in range(-2, 3):
                if abs(dx) + abs(dz) <= 3:
                    pts[(cx + dx, h, dz)] = leaf
        for dx in range(-1, 2):
            for dz in range(-1, 2):
                pts[(cx + dx, h + 1, dz)] = leaf
    offs = np.array(list(pts.keys()), dtype=np.int64)
    ids = np.array(list(pts.values()), dtype=np.uint16)
    _TPL_CACHE[key] = (offs, ids)
    return offs, ids
