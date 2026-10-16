"""VoxelWorld: the 20 Hz voxel simulation (DESIGN-v5 §2.3, §2.5, §4).

    w = VoxelWorld(seed, folder)          # or VoxelWorld.load(folder)
    w.tick()                              # block updates, fluids, fire, plants, signals, creatures, time
    w.get(x, y, z) -> id ; w.set(x, y, z, id, by=None)
    w.raycast(origin, dir, reach) -> dict | None
    w.chunk_bytes(cx, cz) -> bytes        # zlib(uint16 LE, index = x + 16*(z + 16*y))
    w.snapshot(full=False) -> dict        # §4 tick payload
    w.save() ; w.state() ; VoxelWorld.load(folder)

The inhabitant is ``w.agent`` (a Body, entity id 1) driven by ``w.skills`` (a SkillRunner);
the visitor (entity id 2) exists between ``visitor_action({"action": "join"})`` and "leave".
All public methods take ``w.lock`` (an RLock) so a web thread may call ``chunk_bytes`` or
``visitor_action`` while the world thread ticks.
"""
from __future__ import annotations

import json
import math
import os
import random
import struct
import threading
import time
import zlib
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from . import blocks as B
from . import items as IT
from . import recipes as R
from .body import Body
from .terrain import BIOME_TEMP, Terrain, _new_furnace, _tree_template

I = B.ID
AIR = 0
N = B.N
SOLID, OPAQUE, LIQUID, LIGHT = B.SOLID, B.OPAQUE, B.LIQUID, B.LIGHT
REPL, GRAV, BASE, STATE, NAME = B.REPLACEABLE, B.GRAVITY, B.BASE, B.STATE, B.NAME
IS_WATER, IS_LAVA, HARD, FLAM = B.IS_WATER, B.IS_LAVA, B.HARDNESS, B.FLAMMABLE
SKY_ATT = B.SKY_ATTEN
NP_ATT = B.np_sky_atten
NP_TRANS = B.np_transparent
NP_LIGHT = B.np_light
WATER_LV = [I["water"]] + [I[f"water_{k}"] for k in range(1, 8)]
LAVA_LV = [I["lava"]] + [I[f"lava_{k}"] for k in range(1, 4)]
WIRE_LV = [I[f"wire_{k}"] for k in range(16)]
LOGSET = set(B.LOGS)
LEAFSET = set(B.LEAVES)
DIRS6 = ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))
DIRS4 = ((1, 0, 0), (-1, 0, 0), (0, 0, 1), (0, 0, -1))
SIGNAL_BASES = {"lever", "button", "pressure_plate", "wire", "lamp", "door", "piston", "tnt"}
IS_SIGNAL = [BASE[i] in SIGNAL_BASES for i in range(N)]
CONTAINER_BASES = {"chest", "furnace"}
GROWER_BASES = {"wheat", "carrots", "potatoes", "oak_sapling", "birch_sapling", "pine_sapling", "jungle_sapling",
                "acacia_sapling", "sugarcane", "cactus", "berry_bush", "fire", "steam", "farmland"}
IS_GROWER = np.array([BASE[i] in GROWER_BASES and NAME[i] != "berry_bush_ripe" for i in range(N)])
# blocks whose update handler does something
_UPD = set()
for _b in B.BLOCKS:
    if (_b["gravity"] or _b["liquid"] or _b["shape"] in ("cross", "crop", "torch", "wire", "plate", "lever", "button",
                                                          "door", "ladder", "flat", "bed", "fire")
            or _b["base"] in ("farmland", "vines", "piston", "fire")):
        _UPD.add(_b["id"])
HAS_UPD = [i in _UPD for i in range(N)]
BEDROCK = I["bedrock"]
SOIL = {I[n] for n in ("grass", "dirt", "moss", "mud", "farmland", "farmland_wet")}
SAND = {I["sand"], I["red_sand"]}
TICKS_PER_SEC = 20
DT = 1.0 / TICKS_PER_SEC
REACH = 4.5
_SPAWNS = {"plains", "forest", "birch_forest", "savanna", "jungle", "taiga", "swamp", "mountains", "snowy_tundra"}


class Chunk:
    __slots__ = ("cx", "cz", "b", "mv", "sky", "blk", "skv", "blv", "lit", "dirty", "zcache", "top", "saved")

    def __init__(self, cx, cz, blocks):
        self.cx, self.cz = cx, cz
        self.b = np.ascontiguousarray(blocks, dtype=np.uint16)
        self.mv = memoryview(self.b.reshape(-1))
        self.sky = self.blk = self.skv = self.blv = None
        self.lit = False
        self.dirty = False
        self.saved = False
        self.zcache = None
        att = NP_ATT[self.b] > 0
        nz = att.any(axis=0)
        top = 255 - np.argmax(att[::-1], axis=0)
        self.top = np.where(nz, top, -1).astype(np.int16)

    def set_light(self, sky, blk):
        self.sky = np.ascontiguousarray(sky, dtype=np.uint8)
        self.blk = np.ascontiguousarray(blk, dtype=np.uint8)
        self.skv = memoryview(self.sky.reshape(-1))
        self.blv = memoryview(self.blk.reshape(-1))
        self.lit = True


def _nbr_max(s, out):
    """out = max over the 6 face neighbours of s (0 outside)."""
    out[...] = 0
    np.maximum(out[1:], s[:-1], out=out[1:])
    np.maximum(out[:-1], s[1:], out=out[:-1])
    np.maximum(out[:, 1:], s[:, :-1], out=out[:, 1:])
    np.maximum(out[:, :-1], s[:, 1:], out=out[:, :-1])
    np.maximum(out[:, :, 1:], s[:, :, :-1], out=out[:, :, 1:])
    np.maximum(out[:, :, :-1], s[:, :, 1:], out=out[:, :, :-1])
    return out


def _spread(L, trans, base, fixed=None, iters=15):
    """Flood light: L = max(base, nbr-1) in transparent cells; ``fixed`` mask keeps cells."""
    n = np.empty_like(L)
    for _ in range(iters):
        _nbr_max(L, n)
        n -= 1
        np.maximum(n, 0, out=n)
        new = np.where(trans, np.maximum(base, n), base)
        if fixed is not None:
            new[fixed] = L[fixed]
        if np.array_equal(new, L):
            break
        L = new
    return L


def compute_chunk_light(b, top):
    """Vectorised sky + block light for one chunk array (neighbours ignored)."""
    att = NP_ATT[b]
    cum = np.cumsum(att[::-1], axis=0)[::-1]
    direct = np.clip(15 - cum, 0, 15).astype(np.int16)
    trans = NP_TRANS[b]
    sky = direct.copy()
    if (top >= 0).any():
        ylo = max(0, int(top[top >= 0].min()) - 15)
        yhi = min(256, int(top.max()) + 2)
        sky[ylo:yhi] = _spread(direct[ylo:yhi].copy(), trans[ylo:yhi], direct[ylo:yhi])
    em = NP_LIGHT[b]
    blk = np.zeros_like(sky)
    if em.any():
        ys = np.nonzero(em.any(axis=(1, 2)))[0]
        y0, y1 = max(0, int(ys.min()) - 15), min(256, int(ys.max()) + 16)
        blk[y0:y1] = _spread(em[y0:y1].copy(), trans[y0:y1], em[y0:y1])
    return sky.astype(np.uint8), blk.astype(np.uint8)


# ====================================================================== entities
class Entity:
    """A light entity: dropped item, falling block or primed TNT."""
    kind = "entity"

    def __init__(self, world, x, y, z):
        self.world = world
        self.id = world._new_id()
        self.x, self.y, self.z = x, y, z
        self.vx = self.vy = self.vz = 0.0
        self.age = 0
        self.rest = False
        self.dead = False

    def _fall(self, size=0.25):
        w = self.world
        if self.rest:
            if self.age % 10 == 0 and not SOLID[w.get(math.floor(self.x), math.floor(self.y - 0.05),
                                                     math.floor(self.z))]:
                self.rest = False
            return
        cell = w.get(math.floor(self.x), math.floor(self.y), math.floor(self.z))
        if IS_WATER[cell]:
            self.vy = min(self.vy + 0.01, 0.06)
            self.vx *= 0.8
            self.vz *= 0.8
        else:
            self.vy = max(self.vy - 0.04, -1.5)
        nx, nz = self.x + self.vx, self.z + self.vz
        if SOLID[w.get(math.floor(nx), math.floor(self.y + 0.1), math.floor(nz))]:
            self.vx = self.vz = 0.0
            nx, nz = self.x, self.z
        self.x, self.z = nx, nz
        ny = self.y + self.vy
        fy = math.floor(ny)
        below = w.get(math.floor(self.x), fy, math.floor(self.z))
        if self.vy < 0 and SOLID[below]:
            self.y = fy + B.HEIGHT[below]
            self.vy = 0.0
            self.vx *= 0.5
            self.vz *= 0.5
            if abs(self.vx) < 0.005 and abs(self.vz) < 0.005:
                self.rest = True
                self.vx = self.vz = 0.0
        elif self.vy > 0 and SOLID[w.get(math.floor(self.x), math.floor(ny + size), math.floor(self.z))]:
            self.vy = 0.0
        else:
            self.y = ny
        if self.y < -10:
            self.dead = True


class ItemEntity(Entity):
    kind = "item"

    def __init__(self, world, x, y, z, item, count, delay=10, owner=None):
        super().__init__(world, x, y, z)
        self.item, self.count = item, count
        self.delay = delay
        self.owner = owner
        self.dur = None

    def step(self):
        self.age += 1
        if self.delay > 0:
            self.delay -= 1
        self._fall()
        if IS_LAVA[self.world.get(math.floor(self.x), math.floor(self.y), math.floor(self.z))]:
            self.dead = True
        if self.age > 6000:
            self.dead = True

    def public(self):
        return {"id": self.id, "kind": "item", "x": round(self.x, 2), "y": round(self.y, 2), "z": round(self.z, 2),
                "yaw": 0.0, "pitch": 0.0, "item": self.item, "count": self.count}


class FallingBlock(Entity):
    kind = "falling_block"

    def __init__(self, world, x, y, z, bid):
        super().__init__(world, x + 0.5, y, z + 0.5)
        self.block = bid

    def step(self):
        self.age += 1
        w = self.world
        self.vy = max(self.vy - 0.04, -2.0)
        ny = self.y + self.vy
        bx, bz = math.floor(self.x), math.floor(self.z)
        for yy in range(math.floor(self.y) - 1, math.floor(ny) - 1, -1):
            below = w.get(bx, yy, bz)
            if SOLID[below] or yy < 0:
                land = yy + 1
                cur = w.get(bx, land, bz)
                if REPL[cur] or cur == AIR:
                    w.set(bx, land, bz, self.block)
                else:
                    w.spawn_item(bx + 0.5, land + 0.5, bz + 0.5, B.BLOCKS[self.block]["item"], 1)
                self.dead = True
                return
        self.y = ny
        if self.y < 0:
            self.dead = True

    def public(self):
        return {"id": self.id, "kind": "falling_block", "x": round(self.x, 2), "y": round(self.y, 2),
                "z": round(self.z, 2), "yaw": 0.0, "pitch": 0.0, "block": self.block}


class PrimedTNT(Entity):
    kind = "tnt"

    def __init__(self, world, x, y, z, fuse=80):
        super().__init__(world, x + 0.5, y, z + 0.5)
        self.fuse = fuse

    def step(self):
        self.age += 1
        self._fall(0.9)
        self.fuse -= 1
        if self.fuse <= 0:
            self.dead = True
            self.world.explode(self.x, self.y + 0.5, self.z, 3.2)

    def public(self):
        return {"id": self.id, "kind": "tnt", "x": round(self.x, 2), "y": round(self.y, 2), "z": round(self.z, 2),
                "yaw": 0.0, "pitch": 0.0, "fuse": self.fuse}


class Player(Body):
    is_player = True


# ====================================================================== the world
class VoxelWorld:
    VERSION = 1

    def __init__(self, seed: int = 0, folder: str | os.PathLike | None = None, *, agent_name: str = "Ada",
                 peaceful: bool = False, day_seconds: float = 1200.0, sim_radius: int = 6, threaded: bool = True,
                 creatures: bool = True, _restore: dict | None = None):
        self.lock = threading.RLock()
        self.seed = int(seed)
        self.folder = Path(folder) if folder else None
        self.region = self.folder / "region" if self.folder else None
        if self.region:
            self.region.mkdir(parents=True, exist_ok=True)
        self.terrain = Terrain(self.seed)
        self.rng = random.Random(self.seed ^ 0x5EED)
        self.nprng = np.random.default_rng(self.seed & 0xFFFFFFFF)
        self.chunks: dict[tuple, Chunk] = {}
        self.peaceful = peaceful
        self.creatures_on = creatures
        self.day_ticks = int(day_seconds * TICKS_PER_SEC)
        self.sim_radius = sim_radius
        self.keep_radius = sim_radius + 6
        self.max_loaded = 600       # ~256 KB each (blocks + light)
        self.t = 0
        self.time_offset = int(self.day_ticks * 0.02)
        self.weather = "clear"
        self.weather_timer = self.rng.randint(6000, 18000)
        self.growth = 1.0           # multiplier on plant growth chances
        self.hunger_rate = 0.002    # exhaustion per tick (≈ one food point per 100 s)
        self.fire_spread = True
        self.max_hostiles = 4       # night creatures near the inhabitant at once
        self.update_cap = 400
        self.entities: dict[int, object] = {}
        self._next_id = 100
        self.containers: dict[tuple, dict] = {}
        self.meta: dict[tuple, dict] = {}
        self.places: dict[str, list] = {}
        self.growers: dict[tuple, int] = {}
        self.burning: dict[tuple, float] = {}
        self.active: set = set()
        self._sched: dict[int, list] = {}
        self._sched_set: set = set()
        self._deferred: dict[tuple, list] = {}
        self._light_dirty: set = set()
        self._sig_dirty: set = set()
        self._changes: dict[tuple, int] = {}
        self._events: list = []
        self.log: deque = deque(maxlen=400)
        self._seq = 0
        self._sent_ids: set = set()
        self._spawned_chunks: set = set()
        self._furnaces: set = set()
        self._plates: set = set()
        self._buttons: dict = {}
        self._leaf_due: dict = {}
        self.perf = deque(maxlen=2000)
        self.agent_info: dict = {}
        self._pool = ThreadPoolExecutor(1, thread_name_prefix="vox-gen") if threaded else None
        self._pending: dict[tuple, object] = {}
        self._no_sync = False
        self._reload: set = set()
        self.threaded = threaded
        self.spawn = self.terrain.spawn
        sx, sy, sz = self.spawn
        self.agent = Player(self, sx, sy, sz, kind="agent", name=agent_name, eid=1)
        self.agent.spawn_point = self.spawn
        self.entities[1] = self.agent
        self.visitor: Player | None = None
        self._sleep_ticks = 0
        if _restore:
            self._restore(_restore)
        # warm the chunks right around the inhabitant synchronously, the rest in the background
        acx, acz = math.floor(self.agent.x) >> 4, math.floor(self.agent.z) >> 4
        for dx in range(-2, 3):
            for dz in range(-2, 3):
                self._chunk(acx + dx, acz + dz)
        self._update_active(force=True)
        from ..agent.skills import SkillRunner  # late import: skills depend on this module
        self.skills = SkillRunner(self, self.agent)

    # ------------------------------------------------------------------ ids / events
    def _new_id(self):
        self._next_id += 1
        return self._next_id

    def emit(self, type_, **kw):
        self._seq += 1
        ev = {"seq": self._seq, "t": self.t, "type": type_, **kw}
        self._events.append(ev)
        self.log.append(ev)
        return ev

    def events_since(self, seq: int) -> list:
        return [e for e in self.log if e["seq"] > seq]

    # ------------------------------------------------------------------ chunks
    def _chunk_file(self, cx, cz):
        return self.region / f"c.{cx}.{cz}.vox" if self.region else None

    def _produce(self, cx, cz):
        """Load a saved chunk or generate it; pure (no world mutation) so it can run off-thread."""
        f = self._chunk_file(cx, cz)
        if f is not None and f.exists():
            raw = zlib.decompress(f.read_bytes())
            (hl,) = struct.unpack("<I", raw[:4])
            head = json.loads(raw[4:4 + hl])
            blocks = np.frombuffer(raw[4 + hl:], dtype="<u2").reshape(256, 16, 16).astype(np.uint16)
            ch = Chunk(cx, cz, blocks)
            ch.saved = True
            sky, blk = compute_chunk_light(ch.b, ch.top)
            ch.set_light(sky, blk)
            return ch, head, None
        blocks, containers, spawns = self.terrain.generate(cx, cz)
        ch = Chunk(cx, cz, blocks)
        sky, blk = compute_chunk_light(ch.b, ch.top)
        ch.set_light(sky, blk)
        return ch, {"containers": [[*k, v] for k, v in containers.items()], "meta": []}, spawns

    def _install(self, cx, cz, produced):
        key = (cx, cz)
        if key in self.chunks:
            return self.chunks[key]
        ch, head, spawns = produced
        self.chunks[key] = ch
        for x, y, z, v in head.get("containers", []):
            self.containers.setdefault((x, y, z), v)
            if v.get("kind") == "furnace" and (v.get("burn", 0) > 0 or v.get("input")):
                self._furnaces.add((x, y, z))
        for x, y, z, v in head.get("meta", []):
            self.meta.setdefault((x, y, z), v)
        # growers (crops, saplings, cane, cactus, fire...)
        g = IS_GROWER[ch.b]
        if g.any():
            ys, zs, xs = np.nonzero(g)
            for y, z, x in zip(ys.tolist(), zs.tolist(), xs.tolist()):
                self.growers[(cx * 16 + x, y, cz * 16 + z)] = 0
        if spawns and key not in self._spawned_chunks and self.creatures_on:
            self._spawned_chunks.add(key)
            from .creatures import spawn_creature
            for s in spawns:
                spawn_creature(self, s["kind"], s["x"], s["y"], s["z"])
        elif spawns is not None:
            self._spawned_chunks.add(key)
        for p in self._deferred.pop(key, ()):
            self.schedule(*p)
        return ch

    def _chunk(self, cx, cz) -> Chunk:
        ch = self.chunks.get((cx, cz))
        if ch is None:
            with self.lock:
                ch = self.chunks.get((cx, cz))
                if ch is None:
                    ch = self._install(cx, cz, self._produce(cx, cz))
        return ch

    def chunk_loaded(self, cx, cz):
        return (cx, cz) in self.chunks

    def _request(self, cx, cz):
        key = (cx, cz)
        if key in self.chunks or key in self._pending:
            return
        if self._pool is None:
            self._chunk(cx, cz)
            return
        self._pending[key] = self._pool.submit(self._produce, cx, cz)

    def _collect_pending(self, budget=3):
        done = [k for k, f in self._pending.items() if f.done()]
        for k in done[:budget]:
            f = self._pending.pop(k)
            try:
                self._install(k[0], k[1], f.result())
            except Exception as e:  # pragma: no cover - surfaced as an event
                self.emit("error", text=f"chunk {k}: {e!r}")

    def _players(self):
        out = [self.agent]
        if self.visitor is not None:
            out.append(self.visitor)
        return out

    def _update_active(self, force=False):
        r = self.sim_radius
        want = set()
        for p in self._players():
            pcx, pcz = math.floor(p.x) >> 4, math.floor(p.z) >> 4
            for dx in range(-r, r + 1):
                for dz in range(-r, r + 1):
                    want.add((pcx + dx, pcz + dz))
        for k in sorted(want - set(self.chunks), key=lambda k: min(
                abs(k[0] - (math.floor(p.x) >> 4)) + abs(k[1] - (math.floor(p.z) >> 4)) for p in self._players())):
            self._request(*k)
        newly = {k for k in want if k in self.chunks} - self.active
        self.active = {k for k in want if k in self.chunks}
        for k in newly:
            for p in self._deferred.pop(k, ()):
                self.schedule(*p)

    def _unload_far(self):
        if len(self.chunks) <= self.max_loaded:
            return
        ps = [(math.floor(p.x) >> 4, math.floor(p.z) >> 4) for p in self._players()]
        far = sorted(self.chunks, key=lambda k: -min(max(abs(k[0] - a), abs(k[1] - b)) for a, b in ps))
        for k in far[: len(self.chunks) - self.max_loaded + 50]:
            if min(max(abs(k[0] - a), abs(k[1] - b)) for a, b in ps) <= self.keep_radius:
                break
            self._unload(k)

    def _unload(self, key):
        ch = self.chunks.get(key)
        if ch is None:
            return
        if ch.dirty:
            self._save_chunk(ch)
        x0, z0 = key[0] * 16, key[1] * 16

        def inside(p):
            return x0 <= p[0] < x0 + 16 and z0 <= p[2] < z0 + 16
        for d in (self.containers, self.meta, self.growers, self.burning):
            for p in [p for p in d if inside(p)]:
                d.pop(p, None)
        self._furnaces = {p for p in self._furnaces if not inside(p)}
        del self.chunks[key]

    # ------------------------------------------------------------------ block access
    def get(self, x, y, z) -> int:
        if y < 0:
            return BEDROCK
        if y > 255:
            return AIR
        ch = self.chunks.get((x >> 4, z >> 4))
        if ch is None:
            if self._no_sync:
                # creatures and items treat unloaded chunks as a wall (never stall the tick)
                self._request(x >> 4, z >> 4)
                return BEDROCK
            ch = self._chunk(x >> 4, z >> 4)
        return ch.mv[(y << 8) | ((z & 15) << 4) | (x & 15)]

    def get_name(self, x, y, z) -> str:
        return NAME[self.get(x, y, z)]

    def set(self, x, y, z, bid, by=None, update=True) -> bool:
        """Set a block; every change is recorded for the page and wakes neighbouring updates."""
        if y < 0 or y > 255:
            return False
        if isinstance(bid, str):
            bid = I[bid]
        with self.lock:
            ch = self.chunks.get((x >> 4, z >> 4)) or self._chunk(x >> 4, z >> 4)
            i = (y << 8) | ((z & 15) << 4) | (x & 15)
            old = ch.mv[i]
            if old == bid:
                return False
            ch.mv[i] = bid
            ch.dirty = True
            ch.zcache = None
            p = (x, y, z)
            self._changes[p] = bid
            lx, lz = x & 15, z & 15
            if SKY_ATT[old] != SKY_ATT[bid]:
                if SKY_ATT[bid] and y > ch.top[lz, lx]:
                    ch.top[lz, lx] = y
                elif not SKY_ATT[bid] and y == ch.top[lz, lx]:
                    col = NP_ATT[ch.b[:y, lz, lx]] > 0
                    nz = np.nonzero(col)[0]
                    ch.top[lz, lx] = int(nz[-1]) if len(nz) else -1
            if ch.lit and (SKY_ATT[old] != SKY_ATT[bid] or LIGHT[old] != LIGHT[bid] or OPAQUE[old] != OPAQUE[bid]):
                self._light_dirty.add(p)
            ob, nb = BASE[old], BASE[bid]
            if ob != nb:
                if ob in CONTAINER_BASES:
                    self.containers.pop(p, None)
                    self._furnaces.discard(p)
                if nb in CONTAINER_BASES and p not in self.containers:
                    self.containers[p] = ({"kind": "chest", "slots": [None] * 27} if nb == "chest"
                                          else _new_furnace())
                if ob in ("piston", "sign", "door", "lamp", "tnt"):
                    self.meta.pop(p, None)
                self.burning.pop(p, None)
            if IS_GROWER[bid]:
                self.growers[p] = 0
            elif IS_GROWER[old]:
                self.growers.pop(p, None)
            if nb == "pressure_plate":
                self._plates.add(p)
            elif ob == "pressure_plate":
                self._plates.discard(p)
            if IS_SIGNAL[old] or IS_SIGNAL[bid] or (B.CONDUCTIVE[old] != B.CONDUCTIVE[bid]):
                self._sig_dirty.add(p)
            if update:
                self.schedule(x, y, z)
                for dx, dy, dz in DIRS6:
                    self.schedule(x + dx, y + dy, z + dz)
            if old in LOGSET and bid not in LOGSET:
                self._leaf_check_around(x, y, z)
            return True

    def fill(self, x0, y0, z0, x1, y1, z1, bid):
        """Bulk-set the box [x0,x1]×[y0,y1]×[z0,z1] (inclusive) without block updates; relights the
        touched chunks. The page is told to reload those chunks (snapshot ``reload``)."""
        if isinstance(bid, str):
            bid = I[bid]
        x0, x1 = min(x0, x1), max(x0, x1)
        y0, y1 = max(0, min(y0, y1)), min(255, max(y0, y1))
        z0, z1 = min(z0, z1), max(z0, z1)
        with self.lock:
            for cx in range(x0 >> 4, (x1 >> 4) + 1):
                for cz in range(z0 >> 4, (z1 >> 4) + 1):
                    ch = self._chunk(cx, cz)
                    ax0, ax1 = max(x0, cx * 16), min(x1, cx * 16 + 15)
                    az0, az1 = max(z0, cz * 16), min(z1, cz * 16 + 15)
                    ch.b[y0:y1 + 1, az0 - cz * 16:az1 - cz * 16 + 1, ax0 - cx * 16:ax1 - cx * 16 + 1] = bid
                    ch.dirty = True
                    ch.zcache = None
                    att = NP_ATT[ch.b] > 0
                    nz = att.any(axis=0)
                    ch.top[:] = np.where(nz, 255 - np.argmax(att[::-1], axis=0), -1)
                    self._light_chunk(ch)
                    self._reload.add((cx, cz))
            for d in (self.containers, self.growers, self.meta):
                for p in [p for p in d if len(p) == 3 and x0 <= p[0] <= x1 and y0 <= p[1] <= y1 and
                          z0 <= p[2] <= z1]:
                    d.pop(p, None)
            if IS_GROWER[bid]:
                for x in range(x0, x1 + 1):
                    for y in range(y0, y1 + 1):
                        for z in range(z0, z1 + 1):
                            self.growers[(x, y, z)] = self.t
            if BASE[bid] in CONTAINER_BASES:
                for x in range(x0, x1 + 1):
                    for y in range(y0, y1 + 1):
                        for z in range(z0, z1 + 1):
                            self.containers[(x, y, z)] = ({"kind": "chest", "slots": [None] * 27}
                                                          if BASE[bid] == "chest" else _new_furnace())

    def region_blocks(self, x0, y0, z0, x1, y1, z1, layer="b") -> np.ndarray:
        """Blocks (or 'sky'/'blk' light) in [x0,x1)×[y0,y1)×[z0,z1) as an array [y, z, x]."""
        y0c, y1c = max(0, y0), min(256, y1)
        out = np.zeros((y1 - y0, z1 - z0, x1 - x0), dtype=np.uint16 if layer == "b" else np.uint8)
        if layer == "sky":
            out[:] = 15
        for cx in range(x0 >> 4, ((x1 - 1) >> 4) + 1):
            for cz in range(z0 >> 4, ((z1 - 1) >> 4) + 1):
                ch = self._chunk(cx, cz)
                if layer != "b" and not ch.lit:
                    self._light_chunk(ch)
                arr = ch.b if layer == "b" else (ch.sky if layer == "sky" else ch.blk)
                ax0, ax1 = max(x0, cx * 16), min(x1, cx * 16 + 16)
                az0, az1 = max(z0, cz * 16), min(z1, cz * 16 + 16)
                out[y0c - y0:y1c - y0, az0 - z0:az1 - z0, ax0 - x0:ax1 - x0] = \
                    arr[y0c:y1c, az0 - cz * 16:az1 - cz * 16, ax0 - cx * 16:ax1 - cx * 16]
                if layer == "b" and y0 < 0:
                    out[:min(0, y1) - y0, az0 - z0:az1 - z0, ax0 - x0:ax1 - x0] = BEDROCK
        return out

    def _region_write(self, arr, x0, y0, z0, layer):
        y1, z1, x1 = y0 + arr.shape[0], z0 + arr.shape[1], x0 + arr.shape[2]
        for cx in range(x0 >> 4, ((x1 - 1) >> 4) + 1):
            for cz in range(z0 >> 4, ((z1 - 1) >> 4) + 1):
                ch = self.chunks.get((cx, cz))
                if ch is None or not ch.lit:
                    continue
                dst = ch.sky if layer == "sky" else ch.blk
                ax0, ax1 = max(x0, cx * 16), min(x1, cx * 16 + 16)
                az0, az1 = max(z0, cz * 16), min(z1, cz * 16 + 16)
                dst[y0:y1, az0 - cz * 16:az1 - cz * 16, ax0 - cx * 16:ax1 - cx * 16] = \
                    arr[:, az0 - z0:az1 - z0, ax0 - x0:ax1 - x0]

    # ------------------------------------------------------------------ light
    def _light_chunk(self, ch):
        sky, blk = compute_chunk_light(ch.b, ch.top)
        ch.set_light(sky, blk)

    def sky_level(self) -> int:
        """The sky light the sun gives right now (15 day … 4 night), less in rain."""
        a = math.sin(2 * math.pi * self.time_of_day())
        lvl = 4 + 11 * min(1.0, max(0.0, (a + 0.12) / 0.3))
        if self.weather == "rain":
            lvl -= 3
        elif self.weather == "thunder":
            lvl -= 5
        return int(max(4, round(lvl)))

    def light_at(self, x, y, z) -> int:
        """Effective light 0–15 at a block (block light, or sky light dimmed by the time of day)."""
        if y > 255:
            return self.sky_level()
        if y < 0:
            return 0
        ch = self._chunk(x >> 4, z >> 4)
        if not ch.lit:
            self._light_chunk(ch)
        if self._light_dirty:
            self._process_light(budget=4)
        i = (y << 8) | ((z & 15) << 4) | (x & 15)
        return max(ch.blv[i], ch.skv[i] - (15 - self.sky_level()))

    def raw_light(self, x, y, z):
        ch = self._chunk(x >> 4, z >> 4)
        if not ch.lit:
            self._light_chunk(ch)
        i = (y << 8) | ((z & 15) << 4) | (x & 15)
        return ch.skv[i], ch.blv[i]

    def _process_light(self, budget=1):
        done = 0
        while self._light_dirty and done < budget:
            p0 = next(iter(self._light_dirty))
            group = [p for p in self._light_dirty if abs(p[0] - p0[0]) <= 16 and abs(p[2] - p0[2]) <= 16 and
                     abs(p[1] - p0[1]) <= 24]
            for p in group:
                self._light_dirty.discard(p)
            self._relight(group)
            done += 1

    def _relight(self, cells):
        xs = [p[0] for p in cells]
        ys = [p[1] for p in cells]
        zs = [p[2] for p in cells]
        M = 15
        x0, x1 = min(xs) - M, max(xs) + M + 1
        z0, z1 = min(zs) - M, max(zs) + M + 1
        # vertical extent: down to the first opaque block below each changed column, then 15 more
        low = min(ys)
        for (x, y, z) in cells:
            yy = y - 1
            while yy > 0 and not OPAQUE[self.get(x, yy, z)] and y - yy < 96:
                yy -= 1
            low = min(low, yy)
        y0 = max(0, low - M)
        y1 = min(256, max(ys) + M + 1)
        # include a 1-cell shell whose stored light is kept fixed
        X0, X1, Y0, Y1, Z0, Z1 = x0 - 1, x1 + 1, max(0, y0 - 1), min(256, y1 + 1), z0 - 1, z1 + 1
        blk_arr = self.region_blocks(X0, Y0, Z0, X1, Y1, Z1)
        sky_old = self.region_blocks(X0, Y0, Z0, X1, Y1, Z1, "sky").astype(np.int16)
        bl_old = self.region_blocks(X0, Y0, Z0, X1, Y1, Z1, "blk").astype(np.int16)
        trans = NP_TRANS[blk_arr]
        att = NP_ATT[blk_arr]
        # incoming direct sky at the top of the box: 15 minus attenuation above it
        incoming = np.full((Z1 - Z0, X1 - X0), 15, dtype=np.int16)
        if Y1 < 256:
            tops = np.full((Z1 - Z0, X1 - X0), -1, dtype=np.int16)
            for cx in range(X0 >> 4, ((X1 - 1) >> 4) + 1):
                for cz in range(Z0 >> 4, ((Z1 - 1) >> 4) + 1):
                    ch = self._chunk(cx, cz)
                    ax0, ax1 = max(X0, cx * 16), min(X1, cx * 16 + 16)
                    az0, az1 = max(Z0, cz * 16), min(Z1, cz * 16 + 16)
                    tops[az0 - Z0:az1 - Z0, ax0 - X0:ax1 - X0] = ch.top[az0 - cz * 16:az1 - cz * 16,
                                                                        ax0 - cx * 16:ax1 - cx * 16]
            mt = int(tops.max())
            if mt >= Y1:
                above = NP_ATT[self.region_blocks(X0, Y1, Z0, X1, mt + 1, Z1)].sum(axis=0)
                incoming = np.clip(15 - above, 0, 15).astype(np.int16)
        cum = np.cumsum(att[::-1], axis=0)[::-1]
        direct = np.clip(incoming[None] - cum, 0, 15).astype(np.int16)
        fixed = np.zeros(blk_arr.shape, dtype=bool)
        fixed[0] = fixed[-1] = True
        fixed[:, 0] = fixed[:, -1] = True
        fixed[:, :, 0] = fixed[:, :, -1] = True
        if Y0 == 0:
            fixed[0] = False
        if Y1 == 256:
            fixed[-1] = False
        sky = np.where(fixed, sky_old, direct)
        sky = _spread(sky, trans, direct, fixed)
        em = NP_LIGHT[blk_arr]
        bl = np.where(fixed, bl_old, em)
        bl = _spread(bl, trans, em, fixed)
        iy0 = 1 if Y0 < y0 else 0
        self._region_write(sky[iy0:iy0 + (y1 - y0), 1:-1, 1:-1].astype(np.uint8), x0, y0, z0, "sky")
        self._region_write(bl[iy0:iy0 + (y1 - y0), 1:-1, 1:-1].astype(np.uint8), x0, y0, z0, "blk")

    # ------------------------------------------------------------------ time and weather
    def time_of_day(self) -> float:
        """0 = sunrise (06:00), 0.25 noon, 0.5 sunset, 0.75 midnight."""
        return ((self.t + self.time_offset) % self.day_ticks) / self.day_ticks

    def day(self) -> int:
        return (self.t + self.time_offset) // self.day_ticks

    def clock(self) -> str:
        h = (6 + 24 * self.time_of_day()) % 24
        return f"{int(h):02d}:{int((h % 1) * 60):02d}"

    def is_night(self) -> bool:
        return 0.54 < self.time_of_day() < 0.96

    def moon_phase(self) -> int:
        return self.day() % 8

    def raining_on(self, x, y, z) -> bool:
        if self.weather == "clear":
            return False
        fx, fz = math.floor(x), math.floor(z)
        ch = self._chunk(fx >> 4, fz >> 4)
        return y > ch.top[fz & 15, fx & 15]

    def biome(self, x, z) -> str:
        return self.terrain.biome_at(math.floor(x), math.floor(z))

    def temperature(self, x, y, z) -> float:
        b = self.biome(x, z)
        t = BIOME_TEMP.get(b, 15) - max(0, y - 80) * 0.15
        t += 4 * math.sin(2 * math.pi * self.time_of_day()) - (3 if self.weather != "clear" else 0)
        return round(t, 1)

    def precipitation(self, x, z) -> str:
        if self.weather == "clear":
            return "none"
        b = self.biome(x, z)
        if b in ("desert", "savanna"):
            return "none"
        return "snow" if b in ("snowy_tundra", "taiga") or self.terrain.height_at(math.floor(x), math.floor(z)) > 120 \
            else "rain"

    def _weather_tick(self):
        self.weather_timer -= 1
        if self.weather_timer > 0:
            return
        if self.weather == "clear":
            self.weather = "thunder" if self.rng.random() < 0.2 else "rain"
            self.weather_timer = self.rng.randint(2400, 9000)
        else:
            self.weather = "clear"
            self.weather_timer = self.rng.randint(9000, 30000)
        self.emit("weather", weather=self.weather)

    def set_time(self, frac):
        cur = (self.t + self.time_offset) % self.day_ticks
        target = int(frac * self.day_ticks)
        self.time_offset += (target - cur) % self.day_ticks

    # ------------------------------------------------------------------ the tick
    def tick(self):
        t0 = time.perf_counter()
        with self.lock:
            self.t += 1
            t = self.t
            if self._pending:
                self._collect_pending()
            if t % 20 == 0:
                self._update_active()
            self._weather_tick()
            # the inhabitant's skill sets its controls, then everybody moves
            try:
                self.skills.tick()
            except Exception as e:  # a skill bug must never stop the world
                self.emit("error", text=f"skill: {e!r}")
                self.skills.interrupt("error")
            for p in self._players():
                if p.sleeping:
                    p.stop()
                if not getattr(p, "remote", False):
                    p.step()        # a client-driven visitor moves itself (positions come from the page)
                p.vitals()
                if p.said and t >= p.said_until:
                    p.said = None
            self._step_entities()
            self._run_updates()
            if t % 5 == 0:
                self._furnace_tick(5 * DT)
            if self._plates and t % 4 == 0:
                self._plate_tick()
            if self._buttons:
                for p, until in list(self._buttons.items()):
                    if t >= until:
                        del self._buttons[p]
                        if self.get(*p) == I["button_on"]:
                            self.set(*p, I["button"])
            if self._sig_dirty:
                self._signals()
            if t % 20 == 3:
                self._grow_tick()
            if t % 2 == 1:
                self._random_ticks()
            if self.creatures_on and t % 40 == 7:
                from .creatures import population_tick
                population_tick(self)
            self._sleep_tick()
            if self._light_dirty:
                self._process_light(budget=1)
            if t % 200 == 0:
                self._unload_far()
            if self.folder and t % 1200 == 600:
                self.save(partial=True)
        self.perf.append(time.perf_counter() - t0)

    def _step_entities(self):
        self._no_sync = self._pool is not None
        try:
            self._step_entities_inner()
        finally:
            self._no_sync = False

    def _step_entities_inner(self):
        from .creatures import Creature
        act = self.active
        dead = []
        for e in list(self.entities.values()):
            if e is self.agent or e is self.visitor:
                continue
            if ((math.floor(e.x) >> 4, math.floor(e.z) >> 4) not in act):
                continue
            if isinstance(e, Creature):
                e.think()
                e.step()
                e.vitals()
                if e.dead:
                    dead.append(e.id)
            else:
                e.step()
                if e.dead:
                    dead.append(e.id)
        for i in dead:
            self.entities.pop(i, None)
        # pickups
        items = [e for e in self.entities.values() if isinstance(e, ItemEntity) and e.delay <= 0 and not e.dead]
        if items:
            for p in self._players():
                if p.dead:
                    continue
                for e in items:
                    if e.dead:
                        continue
                    dx, dz = e.x - p.x, e.z - p.z
                    if dx * dx + dz * dz < 2.0 and -0.6 < e.y - p.y < 2.2:
                        left = p.add(e.item, e.count, e.dur)
                        got = e.count - left
                        if got:
                            self.emit("picked", who=p.id, name=p.name, item=e.item, count=got)
                        if left:
                            e.count = left
                        else:
                            e.dead = True
                            self.entities.pop(e.id, None)
            if self.t % 20 == 0:
                self._merge_items(items)

    def _merge_items(self, items):
        by = {}
        for e in items:
            if e.dead or not e.rest:
                continue
            k = (e.item, math.floor(e.x), math.floor(e.y), math.floor(e.z))
            o = by.get(k)
            if o is not None and IT.by_name[e.item]["stack"] >= o.count + e.count and e.dur is None:
                o.count += e.count
                e.dead = True
                self.entities.pop(e.id, None)
            else:
                by[k] = e

    # ------------------------------------------------------------------ update queue
    def schedule(self, x, y, z, delay=None):
        if y < 0 or y > 255:
            return
        ch = self.chunks.get((x >> 4, z >> 4))
        if ch is None:
            return
        bid = ch.mv[(y << 8) | ((z & 15) << 4) | (x & 15)]
        if not HAS_UPD[bid]:
            return
        if delay is None:
            delay = 5 if IS_WATER[bid] else (30 if IS_LAVA[bid] else (2 if GRAV[bid] else 1))
        key = (x, y, z)
        if key in self._sched_set:
            return
        self._sched_set.add(key)
        self._sched.setdefault(self.t + delay, []).append(key)

    def _run_updates(self):
        lst = self._sched.pop(self.t, None)
        if not lst:
            return
        cap = self.update_cap
        if len(lst) > cap:
            self._sched.setdefault(self.t + 1, []).extend(lst[cap:])
            lst = lst[:cap]
        act = self.active
        for p in lst:
            self._sched_set.discard(p)
            if (p[0] >> 4, p[2] >> 4) not in act:
                self._deferred.setdefault((p[0] >> 4, p[2] >> 4), []).append(p)
                continue
            self._update(*p)

    def _update(self, x, y, z):
        bid = self.get(x, y, z)
        if not HAS_UPD[bid]:
            return
        if B.LIQUID[bid]:
            self._fluid(x, y, z, bid)
            return
        below = self.get(x, y - 1, z)
        if GRAV[bid]:
            if not SOLID[below] and y > 0:
                self.set(x, y, z, AIR)
                fb = FallingBlock(self, x, y, z, bid)
                self.entities[fb.id] = fb
            return
        if not self._supported(x, y, z, bid):
            self.break_block(x, y, z, cause="unsupported")
            return
        base = BASE[bid]
        if base == "farmland" and SOLID[self.get(x, y + 1, z)]:
            self.set(x, y, z, I["dirt"])

    def _supported(self, x, y, z, bid) -> bool:
        b = B.BLOCKS[bid]
        base, shape = b["base"], b["shape"]
        get = self.get
        below = get(x, y - 1, z)
        if shape in ("cross", "crop"):
            if base in ("wheat", "carrots", "potatoes"):
                return BASE[below] == "farmland"
            if base == "sugarcane":
                if below == bid:
                    return True
                if below not in SOIL and below not in SAND:
                    return False
                return any(IS_WATER[get(x + dx, y - 1, z + dz)] for dx, _, dz in DIRS4)
            if base in ("kelp", "coral"):
                return (SOLID[below] or below == bid)
            if base in ("red_mushroom", "brown_mushroom"):
                return SOLID[below]
            if base == "steam":
                return True
            return below in SOIL or (base == "cactus" and below in SAND) or base == "fire"
        if base == "cactus":
            if not (below == bid or below in SAND):
                return False
            return not any(SOLID[get(x + dx, y, z + dz)] for dx, _, dz in DIRS4)
        if base == "door":
            st = STATE[bid]
            if st in (0, 2):
                return SOLID[below] and BASE[get(x, y + 1, z)] == "door"
            return BASE[below] == "door"
        if shape in ("wire", "plate") or base == "bed":
            return SOLID[below]
        if shape in ("torch", "lever", "button", "flat") and base not in ("lily_pad",):
            if SOLID[below]:
                return True
            if base == "lantern" and SOLID[get(x, y + 1, z)]:
                return True
            return any(SOLID[get(x + dx, y, z + dz)] for dx, _, dz in DIRS4)
        if base == "lily_pad":
            return below == I["water"]
        if base == "ladder":
            return any(SOLID[get(x + dx, y, z + dz)] for dx, _, dz in DIRS4)
        if base == "vines":
            if get(x, y + 1, z) == bid:
                return True
            return any(SOLID[get(x + dx, y, z + dz)] or get(x + dx, y, z + dz) in LEAFSET for dx, _, dz in DIRS4) \
                or SOLID[get(x, y + 1, z)] or get(x, y + 1, z) in LEAFSET
        if base == "fire":
            return SOLID[below] or any(FLAM[get(x + dx, y + dy, z + dz)] for dx, dy, dz in DIRS6)
        return True

    # ------------------------------------------------------------------ fluids
    def _fluid(self, x, y, z, bid):
        water = IS_WATER[bid]
        lv = STATE[bid]
        LV = WATER_LV if water else LAVA_LV
        maxlv = 7 if water else 3
        get = self.get
        # mixing
        if not water:
            for dx, dy, dz in DIRS6:
                if dy == -1:
                    continue
                if IS_WATER[get(x + dx, y + dy, z + dz)]:
                    self.set(x, y, z, I["obsidian"] if lv == 0 else I["cobblestone"])
                    self._steam(x, y + 1, z)
                    self.emit("hiss", x=x, y=y, z=z)
                    return
        if lv > 0:
            above = get(x, y + 1, z)
            if (IS_WATER[above] if water else IS_LAVA[above]):
                new = 1
            else:
                best = 99
                srcs = 0
                for dx, _, dz in DIRS4:
                    n = get(x + dx, y, z + dz)
                    if (IS_WATER[n] if water else IS_LAVA[n]):
                        s = STATE[n]
                        if s == 0:
                            srcs += 1
                        best = min(best, s)
                new = best + 1 if best < 99 else 99
                if water and srcs >= 2:
                    b2 = get(x, y - 1, z)
                    if SOLID[b2] or b2 == I["water"]:
                        new = 0
            if new > maxlv:
                self.set(x, y, z, AIR)
                return
            if new != lv:
                self.set(x, y, z, LV[new])
                return
        # flow down
        below = get(x, y - 1, z)
        if y > 0 and self._can_flow(below, water):
            self._flow_into(x, y - 1, z, below, water, LV[1])
            if lv != 0:
                return
        elif y > 0 and (IS_WATER[below] if water else IS_LAVA[below]) and lv != 0:
            return
        nl = lv + 1
        if nl > maxlv:
            return
        for dx, _, dz in DIRS4:
            n = get(x + dx, y, z + dz)
            if self._can_flow(n, water):
                self._flow_into(x + dx, y, z + dz, n, water, LV[nl])
            elif (IS_WATER[n] if water else IS_LAVA[n]) and STATE[n] > nl:
                self.set(x + dx, y, z + dz, LV[nl])
            elif not water and IS_WATER[n]:
                self.set(x + dx, y, z + dz, I["stone"] if n == I["water"] else I["cobblestone"])
            elif not water and FLAM[n] and self.fire_spread and self.rng.random() < 0.3:
                self._ignite_near(x + dx, y, z + dz)

    def _can_flow(self, n, water):
        if n == AIR:
            return True
        if B.LIQUID[n]:
            return False
        return REPL[n] and not SOLID[n]

    def _flow_into(self, x, y, z, cur, water, new_id):
        if cur != AIR and not B.LIQUID[cur]:
            if BASE[cur] == "fire":
                self.emit("hiss", x=x, y=y, z=z)
            else:
                for d in B.BLOCKS[cur]["drops"]:
                    if d["chance"] >= 1:
                        self.spawn_item(x + 0.5, y + 0.3, z + 0.5, d["item"], d["count"])
        if not water:
            for dx, dy, dz in DIRS6:
                if IS_WATER[self.get(x + dx, y + dy, z + dz)]:
                    self.set(x, y, z, I["cobblestone"])
                    self._steam(x, y + 1, z)
                    return
        self.set(x, y, z, new_id)

    def _steam(self, x, y, z):
        if self.get(x, y, z) == AIR:
            self.set(x, y, z, I["steam"], update=False)
            self.growers[(x, y, z)] = self.t

    # ------------------------------------------------------------------ fire
    def _ignite_near(self, x, y, z):
        """Light fire in an air cell next to (x,y,z)."""
        for dx, dy, dz in ((0, 1, 0),) + DIRS4:
            p = (x + dx, y + dy, z + dz)
            if self.get(*p) == AIR:
                self.set(*p, I["fire"])
                return True
        return False

    def ignite(self, x, y, z):
        cur = self.get(x, y, z)
        if cur == I["tnt"]:
            self.prime_tnt(x, y, z)
            return True
        if cur == AIR or REPL[cur] and not B.LIQUID[cur]:
            self.set(x, y, z, I["fire"])
            self.growers[(x, y, z)] = self.t
            return True
        return self._ignite_near(x, y, z)

    def _fire_tick(self, p):
        x, y, z = p
        get = self.get
        age = self.t - self.growers.get(p, self.t)
        if self.weather != "clear" and self.raining_on(x, y, z) and self.rng.random() < 0.6:
            self.set(x, y, z, AIR)
            return
        if any(IS_WATER[get(x + dx, y + dy, z + dz)] for dx, dy, dz in DIRS6):
            self.set(x, y, z, AIR)
            return
        fuel = False
        for dx, dy, dz in DIRS6:
            q = (x + dx, y + dy, z + dz)
            n = get(*q)
            if FLAM[n]:
                fuel = True
                if n == I["tnt"]:
                    self.prime_tnt(*q)
                    continue
                left = self.burning.get(q)
                if left is None:
                    left = B.BLOCKS[n]["burn_time"] or 3.0
                left -= 1.5 * (0.5 + self.rng.random())
                if left <= 0:
                    self.burning.pop(q, None)
                    self.set(*q, I["fire"])
                    self.growers[q] = self.t
                else:
                    self.burning[q] = left
        if not fuel and age > 60 + self.rng.randint(0, 80):
            self.set(x, y, z, AIR)
            return
        if self.fire_spread and fuel:
            for _ in range(3):
                q = (x + self.rng.randint(-1, 1), y + self.rng.randint(-1, 2), z + self.rng.randint(-1, 1))
                if get(*q) == AIR and any(FLAM[get(q[0] + a, q[1] + b, q[2] + c)] for a, b, c in DIRS6) \
                        and self.rng.random() < 0.45:
                    self.set(*q, I["fire"])
                    self.growers[q] = self.t
        for e in self._bodies_at(x, y, z):
            e.fire_ticks = max(e.fire_ticks, 80)

    def _bodies_at(self, x, y, z):
        out = []
        for e in self.entities.values():
            if isinstance(e, Body) and e.overlaps_cell(x, y, z):
                out.append(e)
        return out

    # ------------------------------------------------------------------ plants and random ticks
    def _grow_tick(self):
        act = self.active
        rnd = self.rng.random
        g = self.growth
        for p in list(self.growers):
            if (p[0] >> 4, p[2] >> 4) not in act:
                continue
            bid = self.get(*p)
            base = BASE[bid]
            if not IS_GROWER[bid]:
                self.growers.pop(p, None)
                continue
            if base == "fire":
                if rnd() < 0.7:
                    self._fire_tick(p)
                continue
            if base == "steam":
                if self.t - self.growers.get(p, 0) > 40:
                    self.set(*p, AIR)
                continue
            if base == "farmland":
                if rnd() < 0.2:
                    wet = self._water_near(*p, 4)
                    if wet and bid != I["farmland_wet"]:
                        self.set(*p, I["farmland_wet"], update=False)
                    elif not wet and bid == I["farmland_wet"] and self.weather == "clear":
                        self.set(*p, I["farmland"], update=False)
                    elif not wet and BASE[self.get(p[0], p[1] + 1, p[2])] not in ("wheat", "carrots", "potatoes") \
                            and rnd() < 0.05:
                        self.set(*p, I["dirt"])
                continue
            if base in ("wheat", "carrots", "potatoes"):
                n = B.BLOCKS[bid]["plant"]
                st = STATE[bid]
                if st >= n - 1:
                    self.growers.pop(p, None)
                    continue
                if self.light_at(*p) >= 9:
                    wet = self.get(p[0], p[1] - 1, p[2]) == I["farmland_wet"] or self.weather != "clear"
                    if rnd() < (1 / 20 if wet else 1 / 40) * g:
                        self.set(*p, I[f"{base}_{st + 1}"], update=False)
                continue
            if base.endswith("_sapling"):
                if self.light_at(*p) >= 9 and rnd() < g / 120:
                    self.grow_tree(*p, base[:-8])
                continue
            if base in ("sugarcane", "cactus"):
                if self.get(p[0], p[1] + 1, p[2]) == AIR and rnd() < g / 60:
                    h = 1
                    while self.get(p[0], p[1] - h, p[2]) == bid:
                        h += 1
                    if h < 3:
                        self.set(p[0], p[1] + 1, p[2], bid)
                continue
            if base == "berry_bush" and STATE[bid] == 0:
                if rnd() < g / 90:
                    self.set(*p, I["berry_bush_ripe"], update=False)
                    self.growers.pop(p, None)

    def _water_near(self, x, y, z, r):
        a = self.region_blocks(x - r, y, z - r, x + r + 1, y + 2, z + r + 1)
        return bool(np.isin(a, WATER_LV).any())

    def grow_tree(self, x, y, z, kind):
        offs, ids = _tree_template(kind, self.rng.randint(0, 5), False)
        for (dx, dy, dz), bid in zip(offs.tolist(), ids.tolist()):
            if dy < 0:
                continue
            p = (x + dx, y + dy, z + dz)
            cur = self.get(*p)
            if cur == AIR or REPL[cur] and not B.LIQUID[cur] or (dx, dy, dz) == (0, 0, 0) or \
                    (cur in LEAFSET and bid in LOGSET):
                self.set(*p, bid, update=False)
        self.emit("tree_grew", x=x, y=y, z=z, kind=kind)

    def _leaf_check_around(self, x, y, z):
        due = self.t + self.rng.randint(40, 200)
        for dx in range(-4, 5):
            for dy in range(-2, 5):
                for dz in range(-4, 5):
                    if self.get(x + dx, y + dy, z + dz) in LEAFSET:
                        self._leaf_due[(x + dx, y + dy, z + dz)] = due + abs(dx) * 7 + dy * 3

    def _leaf_decay(self):
        lc = self._leaf_due
        if not lc:
            return
        n = 0
        for p, due in list(lc.items()):
            if due > self.t:
                continue
            del lc[p]
            n += 1
            bid = self.get(*p)
            if bid not in LEAFSET:
                continue
            a = self.region_blocks(p[0] - 4, p[1] - 4, p[2] - 4, p[0] + 5, p[1] + 5, p[2] + 5)
            if not np.isin(a, B.LOGS).any():
                self.break_block(*p, cause="decay")
            if n > 30:
                break

    def _random_ticks(self):
        """Sample random cells in a few active chunks: grass spread, lava ignition, ice melt."""
        if not self.active:
            return
        self._leaf_decay()
        act = list(self.active)
        for _ in range(3):
            key = act[self.rng.randrange(len(act))]
            ch = self.chunks.get(key)
            if ch is None:
                continue
            hi = int(ch.top.max()) + 2
            lo = max(1, int(ch.top.min()) - 24)
            if hi <= lo:
                continue
            ys = self.nprng.integers(lo, hi, 24)
            zs = self.nprng.integers(0, 16, 24)
            xs = self.nprng.integers(0, 16, 24)
            ids = ch.b[ys, zs, xs]
            for k in np.nonzero((ids == I["grass"]) | (ids == I["dirt"]) | (ids == I["lava"]) |
                                (ids == I["ice"]) | (ids == I["snow"]))[0].tolist():
                x, y, z = key[0] * 16 + int(xs[k]), int(ys[k]), key[1] * 16 + int(zs[k])
                bid = int(ids[k])
                above = self.get(x, y + 1, z)
                if bid == I["grass"]:
                    if OPAQUE[above]:
                        self.set(x, y, z, I["dirt"])
                        continue
                    for _ in range(2):
                        q = (x + self.rng.randint(-1, 1), y + self.rng.randint(-2, 1), z + self.rng.randint(-1, 1))
                        if self.get(*q) == I["dirt"] and not OPAQUE[self.get(q[0], q[1] + 1, q[2])] and \
                                self.light_at(q[0], q[1] + 1, q[2]) >= 9:
                            self.set(*q, I["grass"], update=False)
                elif bid == I["lava"] and self.fire_spread:
                    for _ in range(2):
                        q = (x + self.rng.randint(-2, 2), y + self.rng.randint(0, 2), z + self.rng.randint(-2, 2))
                        if self.get(*q) == AIR and any(FLAM[self.get(q[0] + a, q[1] + b, q[2] + c)]
                                                       for a, b, c in DIRS6):
                            self.set(*q, I["fire"])
                            self.growers[q] = self.t
                elif bid in (I["ice"], I["snow"]):
                    sk, bl = self.raw_light(x, y + 1, z)
                    if bl > 11:
                        self.set(x, y, z, I["water"] if bid == I["ice"] else AIR)

    # ------------------------------------------------------------------ breaking / placing / using
    def harvestable(self, bid, tool_item) -> bool:
        b = B.BLOCKS[bid]
        if b["tool_level"] <= 0:
            return True
        it = IT.by_name.get(tool_item) if tool_item else None
        return bool(it and it["tool"] == b["tool"] and it["tool_level"] >= b["tool_level"])

    def break_block(self, x, y, z, by=None, tool=None, drop=True, cause="broken") -> list:
        """Remove a block with its drops (as item entities). Returns [(item, count)]."""
        with self.lock:
            bid = self.get(x, y, z)
            if bid == AIR or (by is not None and HARD[bid] < 0):
                return []
            b = B.BLOCKS[bid]
            base = b["base"]
            drops = []
            if drop and self.harvestable(bid, tool):
                if tool == "shears" and (base.endswith("_leaves") or base in ("vines", "tall_grass", "fern")):
                    if base not in ("tall_grass", "fern"):
                        drops.append((base, 1))
                else:
                    for d in b["drops"]:
                        if d["chance"] >= 1 or self.rng.random() < d["chance"]:
                            drops.append((d["item"], d["count"]))
            p = (x, y, z)
            c = self.containers.get(p)
            if c is not None:
                for s in _container_slots(c):
                    if s:
                        drops.append((s["item"], s["count"]))
            new = AIR
            if bid == I["ice"] and SOLID[self.get(x, y - 1, z)] and by is not None:
                new = I["water"]
            if base == "door":
                st = STATE[bid]
                other = (x, y + 1, z) if st in (0, 2) else (x, y - 1, z)
                if BASE[self.get(*other)] == "door":
                    self.set(*other, AIR)
                if st in (1, 3):
                    drops = [("door", 1)] if drop and by is not None else []
            if bid == I["piston_extended"]:
                f = self._facing(p)
                h = (x + f[0], y + f[1], z + f[2])
                if self.get(*h) == I["piston_head"]:
                    self.set(*h, AIR)
            if bid == I["piston_head"]:
                for dx, dy, dz in DIRS6:
                    q = (x + dx, y + dy, z + dz)
                    if self.get(*q) == I["piston_extended"]:
                        self.set(*q, I["piston"])
            self.set(x, y, z, new, by=by)
            for item, n in drops:
                self.spawn_item(x + 0.5, y + 0.3, z + 0.5, item, n)
            if by is not None:
                self.emit("broke", who=by.id, name=by.name, block=NAME[bid], x=x, y=y, z=z,
                          drops=[[i, n] for i, n in drops])
            return drops

    def _facing(self, p):
        f = self.meta.get(p, {}).get("facing", [0, 1, 0])
        return tuple(f)

    def can_place(self, x, y, z, bid, by=None) -> tuple[bool, str]:
        if y < 1 or y > 254:
            return False, "That is outside the world."
        cur = self.get(x, y, z)
        if not (cur == AIR or REPL[cur]):
            return False, f"There is {NAME[cur].replace('_', ' ')} in the way."
        if SOLID[bid]:
            for e in self.entities.values():
                if isinstance(e, Body) and not e.dead and e.overlaps_cell(x, y, z):
                    return False, "Someone is standing there."
        base = BASE[bid]
        if base == "door" and not (self.get(x, y + 1, z) == AIR or REPL[self.get(x, y + 1, z)]):
            return False, "There is no room for a door."
        if base in ("water", "lava") or base == "lily_pad":
            pass
        elif base != "door" and not self._supported(x, y, z, bid):
            return False, f"A {NAME[bid].replace('_', ' ')} needs something to stand on there."
        if base == "door" and not SOLID[self.get(x, y - 1, z)]:
            return False, "A door needs solid ground."
        # every block needs a neighbour to attach to
        if not any(self.get(x + dx, y + dy, z + dz) not in (AIR,) and not B.LIQUID[self.get(x + dx, y + dy, z + dz)]
                   for dx, dy, dz in DIRS6) and base not in ("lily_pad",):
            return False, "There is nothing to attach it to."
        return True, ""

    def place_block(self, x, y, z, bid, by=None) -> tuple[bool, str]:
        with self.lock:
            if isinstance(bid, str):
                bid = I[bid]
            ok, why = self.can_place(x, y, z, bid, by)
            if not ok:
                return False, why
            base = BASE[bid]
            self.set(x, y, z, bid, by=by)
            if base == "door":
                self.set(x, y + 1, z, I["door_upper"], by=by)
            if base == "piston" and by is not None:
                vx, vy, vz = by.look_vec()
                if abs(vy) > 0.7:
                    f = [0, 1 if vy > 0 else -1, 0]
                elif abs(vx) > abs(vz):
                    f = [1 if vx > 0 else -1, 0, 0]
                else:
                    f = [0, 0, 1 if vz > 0 else -1]
                self.meta[(x, y, z)] = {"facing": f}
            if base == "fire":
                self.growers[(x, y, z)] = self.t
            if by is not None:
                self.emit("placed", who=by.id, name=by.name, block=NAME[bid], x=x, y=y, z=z)
            return True, ""

    def till(self, x, y, z, by=None) -> tuple[bool, str]:
        bid = self.get(x, y, z)
        if bid not in (I["grass"], I["dirt"], I["path"]):
            return False, "Only grass or dirt can be tilled."
        above = self.get(x, y + 1, z)
        if above != AIR:
            if REPL[above] and not B.LIQUID[above]:
                self.break_block(x, y + 1, z, by=by)
            else:
                return False, "Something is on top of it."
        self.set(x, y, z, I["farmland_wet"] if self._water_near(x, y, z, 4) else I["farmland"], by=by)
        if by is not None:
            self.emit("tilled", who=by.id, name=by.name, x=x, y=y, z=z)
        return True, ""

    def use_block(self, x, y, z, by=None) -> dict:
        """Right-click a block. Returns {ok, text, kind, ...}."""
        with self.lock:
            bid = self.get(x, y, z)
            base = BASE[bid]
            p = (x, y, z)
            held = by.held() if by is not None else None
            if held == "flint_and_steel" and (bid == I["tnt"] or FLAM[bid] or SOLID[bid]):
                if bid == I["tnt"]:
                    self.prime_tnt(x, y, z)
                else:
                    self._ignite_near(x, y, z)
                if by:
                    by.wear_tool()
                return {"ok": True, "text": "Fire!", "kind": "ignite"}
            if held == "bucket" and B.LIQUID[bid] and STATE[bid] == 0:
                self.set(x, y, z, AIR, by=by)
                by.remove("bucket", 1)
                by.add("water_bucket" if IS_WATER[bid] else "lava_bucket", 1)
                return {"ok": True, "text": "Filled the bucket.", "kind": "bucket"}
            if base == "door":
                st = STATE[bid]
                lower = (x, y, z) if st in (0, 2) else (x, y - 1, z)
                self._toggle_door(lower, None)
                opened = STATE[self.get(*lower)] == 2
                self.emit("door", who=by.id if by else None, x=x, y=y, z=z, open=opened)
                return {"ok": True, "text": "Opened the door." if opened else "Closed the door.", "kind": "door",
                        "open": opened}
            if base == "lever":
                on = bid == I["lever"]
                self.set(x, y, z, I["lever_on"] if on else I["lever"], by=by)
                return {"ok": True, "text": "Lever on." if on else "Lever off.", "kind": "lever", "on": on}
            if base == "button":
                self.set(x, y, z, I["button_on"], by=by)
                self._buttons[p] = self.t + 20
                return {"ok": True, "text": "Pressed the button.", "kind": "button"}
            if base in CONTAINER_BASES:
                c = self.containers.setdefault(p, {"kind": "chest", "slots": [None] * 27} if base == "chest"
                                               else _new_furnace())
                return {"ok": True, "text": f"Opened the {base}.", "kind": base, "container": c}
            if base == "crafting_table":
                return {"ok": True, "text": "A crafting table: I can craft here.", "kind": "crafting_table"}
            if base == "bed":
                if by is None:
                    return {"ok": False, "text": "Nobody to sleep."}
                if not (self.is_night() or self.weather == "thunder"):
                    by.spawn_point = (x + 0.5, y + 1.0, z + 0.5)
                    return {"ok": False, "text": "I can only sleep at night (spawn point set).", "kind": "bed"}
                by.sleeping = True
                by.spawn_point = (x + 0.5, y + 1.0, z + 0.5)
                by.x, by.y, by.z = x + 0.5, y + B.HEIGHT[bid], z + 0.5
                self.emit("sleep", who=by.id, name=by.name)
                return {"ok": True, "text": "Sleeping…", "kind": "bed"}
            if base == "bell":
                self.emit("bell", x=x, y=y, z=z)
                return {"ok": True, "text": "Ding!", "kind": "bell"}
            if base == "sign":
                return {"ok": True, "text": self.meta.get(p, {}).get("text", ""), "kind": "sign"}
            if base == "berry_bush" and STATE[bid] == 1:
                self.set(x, y, z, I["berry_bush"], by=by)
                self.spawn_item(x + 0.5, y + 0.5, z + 0.5, "berries", 2)
                return {"ok": True, "text": "Picked berries.", "kind": "berries"}
            if base == "tnt":
                return {"ok": False, "text": "It needs fire or a signal.", "kind": "tnt"}
            return {"ok": False, "text": f"Nothing happens with the {NAME[bid].replace('_', ' ')}.", "kind": "none"}

    def _toggle_door(self, lower, want_open):
        lb = self.get(*lower)
        if BASE[lb] != "door":
            return
        is_open = STATE[lb] == 2
        if want_open is None:
            want_open = not is_open
        if want_open == is_open:
            return
        up = (lower[0], lower[1] + 1, lower[2])
        self.set(*lower, I["door_lower_open"] if want_open else I["door_lower"], update=False)
        if BASE[self.get(*up)] == "door":
            self.set(*up, I["door_upper_open"] if want_open else I["door_upper"], update=False)

    def set_sign(self, x, y, z, text):
        if BASE[self.get(x, y, z)] == "sign":
            self.meta[(x, y, z)] = {"text": str(text)[:200]}
            self._chunk(x >> 4, z >> 4).dirty = True
            return True
        return False

    # ------------------------------------------------------------------ signals
    def _is_source_on(self, bid):
        return bid in (I["lever_on"], I["button_on"], I["pressure_plate_on"])

    def _signals(self):
        seeds = self._sig_dirty
        self._sig_dirty = set()
        get = self.get
        # wires to recompute: connected components touching the seeds
        start = set()
        for (x, y, z) in seeds:
            for dx, dy, dz in ((0, 0, 0),) + DIRS6:
                q = (x + dx, y + dy, z + dz)
                if B.IS_WIRE[get(*q)]:
                    start.add(q)
        wires = set()
        stack = list(start)
        while stack and len(wires) < 2048:
            p = stack.pop()
            if p in wires:
                continue
            wires.add(p)
            x, y, z = p
            for dx, _, dz in DIRS4:
                for dy in (0, 1, -1):
                    q = (x + dx, y + dy, z + dz)
                    if q not in wires and B.IS_WIRE[get(*q)]:
                        stack.append(q)
        level = {}
        frontier = []
        for p in wires:
            x, y, z = p
            if any(self._is_source_on(get(x + dx, y + dy, z + dz)) for dx, dy, dz in DIRS6):
                level[p] = 15
                frontier.append(p)
        while frontier:
            nxt = []
            for p in frontier:
                lv = level[p] - 1
                if lv <= 0:
                    continue
                x, y, z = p
                for dx, _, dz in DIRS4:
                    for dy in (0, 1, -1):
                        q = (x + dx, y + dy, z + dz)
                        if q in wires and level.get(q, 0) < lv:
                            level[q] = lv
                            nxt.append(q)
            frontier = nxt
        for p in wires:
            want = WIRE_LV[level.get(p, 0)]
            if get(*p) != want:
                self.set(*p, want, update=False)
        # consumers next to the network, the sources or the seeds
        cand = set()
        for p in list(wires) + list(seeds):
            x, y, z = p
            for dx, dy, dz in ((0, 0, 0),) + DIRS6:
                cand.add((x + dx, y + dy, z + dz))
        for q in cand:
            bid = get(*q)
            base = BASE[bid]
            if base not in ("lamp", "door", "piston", "tnt"):
                continue
            pw = self.powered(*q)
            if base == "door" and STATE[bid] in (1, 3):
                continue  # driven by the lower half
            if base == "door":
                pw = pw or self.powered(q[0], q[1] + 1, q[2])
            if base == "lamp":
                want = I["lamp_on"] if pw else I["lamp"]
                if bid != want:
                    self.set(*q, want, update=False)
            elif base == "door":
                m = self.meta.get(q, {})
                if m.get("powered", False) != pw:   # only a change of power moves the door
                    m["powered"] = pw
                    self.meta[q] = m
                    self._toggle_door(q, pw)
            elif base == "piston":
                if pw and bid == I["piston"]:
                    self._piston_extend(q)
                elif not pw and bid == I["piston_extended"]:
                    self._piston_retract(q)
            elif base == "tnt" and pw:
                self.prime_tnt(*q)

    def powered(self, x, y, z) -> bool:
        get = self.get
        for dx, dy, dz in DIRS6:
            n = get(x + dx, y + dy, z + dz)
            if self._is_source_on(n):
                return True
            if B.IS_WIRE[n] and STATE[n] > 0:
                return True
        return False

    def _plate_tick(self):
        occupied = set()
        for e in self.entities.values():
            if isinstance(e, (Body, ItemEntity)):
                occupied.add((math.floor(e.x), math.floor(e.y + 0.05), math.floor(e.z)))
        for p in list(self._plates):
            bid = self.get(*p)
            want = I["pressure_plate_on"] if p in occupied else I["pressure_plate"]
            if BASE[bid] != "pressure_plate":
                self._plates.discard(p)
            elif bid != want:
                self.set(*p, want)

    def _piston_extend(self, p):
        f = self._facing(p)
        line = []
        q = (p[0] + f[0], p[1] + f[1], p[2] + f[2])
        while True:
            bid = self.get(*q)
            if bid == AIR or (REPL[bid] and not SOLID[bid]):
                break
            if HARD[bid] < 0 or bid in (I["obsidian"], I["piston_extended"], I["piston_head"]) or \
                    BASE[bid] in CONTAINER_BASES or len(line) >= 12 or not (0 < q[1] < 255):
                return False
            line.append((q, bid))
            q = (q[0] + f[0], q[1] + f[1], q[2] + f[2])
        end = self.get(*q)
        if end != AIR:
            self.break_block(*q, cause="piston")
        for (c, bid) in reversed(line):
            dst = (c[0] + f[0], c[1] + f[1], c[2] + f[2])
            self.set(*dst, bid)
            if c in self.containers:
                self.containers[dst] = self.containers.pop(c)
        head = (p[0] + f[0], p[1] + f[1], p[2] + f[2])
        self.set(*head, I["piston_head"], update=False)
        self.set(*p, I["piston_extended"], update=False)
        moved = {c for c, _ in line} | {head}
        for e in self.entities.values():
            if isinstance(e, Body) and any(e.overlaps_cell(*c) for c in moved):
                e.x += f[0]
                e.y += f[1]
                e.z += f[2]
        self.emit("piston", x=p[0], y=p[1], z=p[2], extended=True)
        return True

    def _piston_retract(self, p):
        f = self._facing(p)
        head = (p[0] + f[0], p[1] + f[1], p[2] + f[2])
        if self.get(*head) == I["piston_head"]:
            self.set(*head, AIR)
        self.set(*p, I["piston"], update=False)
        self.emit("piston", x=p[0], y=p[1], z=p[2], extended=False)

    # ------------------------------------------------------------------ TNT
    def prime_tnt(self, x, y, z, fuse=80):
        if self.get(x, y, z) == I["tnt"]:
            self.set(x, y, z, AIR)
        e = PrimedTNT(self, x, y, z, fuse)
        self.entities[e.id] = e
        self.emit("tnt_primed", x=x, y=y, z=z)
        return e

    def explode(self, cx, cy, cz, power=3.2):
        r = int(math.ceil(power))
        bx, by, bz = math.floor(cx), math.floor(cy), math.floor(cz)
        removed = 0
        drops = {}
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                for dz in range(-r, r + 1):
                    d = math.sqrt(dx * dx + dy * dy + dz * dz)
                    if d > power * (0.75 + 0.3 * self.rng.random()):
                        continue
                    p = (bx + dx, by + dy, bz + dz)
                    bid = self.get(*p)
                    if bid == AIR or B.LIQUID[bid] or HARD[bid] < 0 or HARD[bid] >= 100:
                        continue
                    if bid == I["tnt"]:
                        self.prime_tnt(*p, fuse=10 + self.rng.randint(0, 20))
                        continue
                    c = self.containers.get(p)
                    if c is not None:
                        for s in _container_slots(c):
                            if s:
                                self.spawn_item(p[0] + 0.5, p[1] + 0.5, p[2] + 0.5, s["item"], s["count"])
                    if self.rng.random() < 0.3:
                        for dd in B.BLOCKS[bid]["drops"]:
                            if dd["chance"] >= 1:
                                drops[p] = (dd["item"], dd["count"])
                    self.set(*p, AIR)
                    removed += 1
        for p, (item, n) in drops.items():
            self.spawn_item(p[0] + 0.5, p[1] + 0.5, p[2] + 0.5, item, n)
        for e in list(self.entities.values()):
            if isinstance(e, Body):
                d = math.sqrt((e.x - cx) ** 2 + (e.y + e.h / 2 - cy) ** 2 + (e.z - cz) ** 2)
                if d < power * 2:
                    e.hurt(round((1 - d / (power * 2)) * 18), "explosion")
                    k = (1 - d / (power * 2)) * 1.2 / max(d, 0.5)
                    e.vx += (e.x - cx) * k
                    e.vz += (e.z - cz) * k
                    e.vy += 0.5 * (1 - d / (power * 2))
            elif isinstance(e, ItemEntity):
                if math.dist((e.x, e.y, e.z), (cx, cy, cz)) < power:
                    e.vy = 0.3
                    e.rest = False
        self.emit("explosion", x=round(cx, 1), y=round(cy, 1), z=round(cz, 1), blocks=removed)

    # ------------------------------------------------------------------ items
    def spawn_item(self, x, y, z, item, count=1, vel=None, delay=10, dur=None):
        if not item or count <= 0 or item not in IT.by_name:
            return None
        e = ItemEntity(self, x, y, z, item, count, delay)
        e.dur = dur
        if vel:
            e.vx, e.vy, e.vz = vel
        else:
            e.vx = (self.rng.random() - 0.5) * 0.1
            e.vz = (self.rng.random() - 0.5) * 0.1
            e.vy = 0.1
        self.entities[e.id] = e
        return e

    def drop_from(self, body, item, count=1, throw=0.3):
        """A body tosses items in front of itself."""
        got = 0
        dur = None
        if count > 0:
            i = body.find(item)
            if i is not None and body.inv[i].get("dur") is not None:
                dur = body.inv[i]["dur"]
            got = body.remove(item, count)
        if not got:
            return None
        vx, vy, vz = body.look_vec()
        e = self.spawn_item(body.x + vx * 0.4, body.y + 1.3, body.z + vz * 0.4, item, got,
                            vel=(vx * throw, 0.1, vz * throw), delay=30, dur=dur)
        self.emit("dropped", who=body.id, name=body.name, item=item, count=got)
        return e

    def items_near(self, x, y, z, r):
        return [e for e in self.entities.values() if isinstance(e, ItemEntity) and not e.dead and
                (e.x - x) ** 2 + (e.y - y) ** 2 + (e.z - z) ** 2 <= r * r]

    # ------------------------------------------------------------------ crafting
    def table_near(self, body, r=4.5):
        bx, by, bz = math.floor(body.x), math.floor(body.y), math.floor(body.z)
        ri = int(math.ceil(r))
        a = self.region_blocks(bx - ri, by - 2, bz - ri, bx + ri + 1, by + 3, bz + ri + 1)
        hits = np.argwhere(a == I["crafting_table"])
        best = None
        for (yy, zz, xx) in hits.tolist():
            p = (bx - ri + xx, by - 2 + yy, bz - ri + zz)
            d = math.dist((p[0] + 0.5, p[1] + 0.5, p[2] + 0.5), body.eye())
            if d <= r + 0.5 and (best is None or d < best[0]):
                best = (d, p)
        return best[1] if best else None

    def missing_for(self, body, recipe, times=1) -> dict:
        """Ingredients still missing for ``times`` crafts: {ingredient: n}."""
        out = {}
        for ing, n in recipe["in"].items():
            have = body.count(ing)
            need = n * times
            if have < need:
                out[ing] = need - have
        return out

    def craft(self, body, item, count=1) -> dict:
        """Craft ``count`` of ``item`` from the body's inventory (2×2 by hand, 3×3 needs a table)."""
        with self.lock:
            opts = R.recipes_for(item)
            if not opts:
                return {"ok": False, "text": f"There is no recipe for {IT.pretty(item)}.", "made": 0}
            table = self.table_near(body) is not None
            last_missing = None
            for rec in opts:
                if rec["needs_table"] and not table:
                    last_missing = last_missing or {"#table": 1}
                    continue
                times = max(1, -(-count // rec["count"]))
                miss = self.missing_for(body, rec, times)
                if miss:
                    # maybe fewer
                    can = min(body.count(i) // n for i, n in rec["in"].items())
                    if can <= 0:
                        last_missing = miss if last_missing is None or "#table" in last_missing else last_missing
                        continue
                    times = can
                for ing, n in rec["in"].items():
                    body.remove(ing, n * times)
                made = rec["count"] * times
                left = body.add(item, made)
                if left:
                    self.spawn_item(body.x, body.y + 1, body.z, item, left)
                self.emit("crafted", who=body.id, name=body.name, item=item, count=made)
                return {"ok": True, "text": f"Crafted {made} {IT.pretty(item)}.", "made": made}
            if last_missing and "#table" in last_missing:
                return {"ok": False, "text": f"I need a crafting table nearby to make {IT.pretty(item)}.", "made": 0,
                        "needs_table": True}
            ing, n = next(iter(last_missing.items()))
            have = body.count(ing)
            nm = IT.pretty(ing.lstrip("#"))
            text = f"I have no {nm}." if have == 0 else f"I need {n} more {nm}."
            return {"ok": False, "text": text, "made": 0, "missing": last_missing}

    # ------------------------------------------------------------------ containers and furnaces
    def container(self, x, y, z):
        return self.containers.get((x, y, z))

    def container_put(self, pos, body, item, count, slot=None) -> int:
        """Move items from a body into a chest (slot ignored) or a furnace slot ('input'|'fuel')."""
        with self.lock:
            c = self.containers.get(tuple(pos))
            if c is None:
                return 0
            have = body.count(item)
            count = min(count, have)
            if count <= 0:
                return 0
            stack = IT.by_name[item]["stack"]
            moved = 0
            if c["kind"] == "chest":
                slots = c["slots"]
                for s in slots:
                    if s and s["item"] == item and s["count"] < stack:
                        k = min(stack - s["count"], count - moved)
                        s["count"] += k
                        moved += k
                for i in range(len(slots)):
                    if moved >= count:
                        break
                    if slots[i] is None:
                        k = min(stack, count - moved)
                        slots[i] = {"item": item, "count": k}
                        moved += k
            else:
                key = slot or ("fuel" if item in R.FUELS and item not in R.SMELT_BY_INPUT else "input")
                s = c.get(key)
                if s is None:
                    k = min(stack, count)
                    c[key] = {"item": item, "count": k}
                    moved = k
                elif s["item"] == item:
                    k = min(stack - s["count"], count)
                    s["count"] += k
                    moved = k
                self._furnaces.add(tuple(pos))
            body.remove(item, moved)
            self._chunk(pos[0] >> 4, pos[2] >> 4).dirty = True
            if moved:
                self.emit("stored", who=body.id, name=body.name, item=item, count=moved, x=pos[0], y=pos[1],
                          z=pos[2])
            return moved

    def container_take(self, pos, body, item=None, count=64, slot=None) -> int:
        with self.lock:
            c = self.containers.get(tuple(pos))
            if c is None:
                return 0
            moved = 0
            if c["kind"] == "chest":
                for i, s in enumerate(c["slots"]):
                    if not s or (item and s["item"] != item) or moved >= count:
                        continue
                    k = min(s["count"], count - moved)
                    left = body.add(s["item"], k)
                    k -= left
                    s["count"] -= k
                    moved += k
                    if s["count"] <= 0:
                        c["slots"][i] = None
            else:
                keys = [slot] if slot else ["output", "input", "fuel"]
                for key in keys:
                    s = c.get(key)
                    if not s or (item and s["item"] != item) or moved >= count:
                        continue
                    k = min(s["count"], count - moved)
                    k -= body.add(s["item"], k)
                    s["count"] -= k
                    moved += k
                    if s["count"] <= 0:
                        c[key] = None
            self._chunk(pos[0] >> 4, pos[2] >> 4).dirty = True
            if moved:
                self.emit("took", who=body.id, name=body.name, item=item, count=moved, x=pos[0], y=pos[1], z=pos[2])
            return moved

    def _furnace_tick(self, dt):
        for p in list(self._furnaces):
            c = self.containers.get(p)
            if c is None or c.get("kind") != "furnace":
                self._furnaces.discard(p)
                continue
            if (p[0] >> 4, p[2] >> 4) not in self.active:
                continue
            inp, out = c.get("input"), c.get("output")
            rec = R.SMELT_BY_INPUT.get(inp["item"]) if inp else None
            can = rec is not None and (out is None or (out["item"] == rec["out"] and
                                                       out["count"] < IT.by_name[rec["out"]]["stack"]))
            if c["burn"] > 0:
                c["burn"] -= dt
            if c["burn"] <= 0 and can and c.get("fuel"):
                f = c["fuel"]
                c["burn"] = c["burn_max"] = R.FUELS.get(f["item"], 0)
                f["count"] -= 1
                if f["item"] == "lava_bucket":
                    c["fuel"] = {"item": "bucket", "count": 1}
                elif f["count"] <= 0:
                    c["fuel"] = None
            if c["burn"] > 0 and can:
                c["progress"] += dt
                if c["progress"] >= rec["time"] - 1e-6:
                    c["progress"] = 0.0
                    inp["count"] -= 1
                    if inp["count"] <= 0:
                        c["input"] = None
                    if out is None:
                        c["output"] = {"item": rec["out"], "count": 1}
                    else:
                        out["count"] += 1
                    self.emit("smelted", x=p[0], y=p[1], z=p[2], item=rec["out"])
            else:
                c["progress"] = 0.0
            lit = c["burn"] > 0
            bid = self.get(*p)
            want = I["furnace_lit"] if lit else I["furnace"]
            if BASE[bid] == "furnace" and bid != want:
                self.set(*p, want, update=False)
            if not lit and not (can and c.get("fuel")):
                c["burn"] = 0.0
                self._furnaces.discard(p)
            self._chunk(p[0] >> 4, p[2] >> 4).dirty = True

    # ------------------------------------------------------------------ bodies
    def on_hurt(self, body, amount, cause, attacker):
        if body.is_player:
            body.sleeping = False
            self.emit("hurt", who=body.id, name=body.name, amount=amount, cause=cause,
                      by=getattr(attacker, "kind", None))

    def on_death(self, body, cause):
        if body.is_player:
            for s in body.inv:
                if s:
                    self.spawn_item(body.x, body.y + 0.5, body.z, s["item"], s["count"], dur=s.get("dur"))
            body.inv = [None] * 36
            self.emit("died", who=body.id, name=body.name, cause=cause, x=round(body.x), y=round(body.y),
                      z=round(body.z))
            sx, sy, sz = body.spawn_point
            body.x, body.y, body.z = sx, sy, sz
            body.vx = body.vy = body.vz = 0.0
            body.health, body.food, body.air, body.fire_ticks, body.fall = 20.0, 20.0, 300, 0, 0.0
            if body is self.agent:
                self.skills.interrupt("died")
        else:
            body.dead = True
            from .creatures import on_creature_death
            on_creature_death(self, body, cause)

    def _sleep_tick(self):
        a = self.agent
        if a.sleeping:
            bid = self.get(math.floor(a.x), math.floor(a.y - 0.3), math.floor(a.z))
            if BASE[bid] != "bed":
                a.sleeping = False
        if a.sleeping and (self.visitor is None or self.visitor.sleeping):
            self._sleep_ticks += 1
            if self._sleep_ticks >= 60:
                self.set_time(0.0)
                if self.weather != "clear":
                    self.weather = "clear"
                    self.weather_timer = self.rng.randint(9000, 30000)
                for p in self._players():
                    if p.sleeping:
                        p.sleeping = False
                        p.y += 0.6
                self._sleep_ticks = 0
                self.emit("morning", day=self.day())
        else:
            self._sleep_ticks = 0

    def say(self, body, text):
        text = str(text)[:300]
        body.said = text
        body.said_until = self.t + 20 * min(10, 3 + len(text) // 20)
        return self.emit("said", who=body.id, name=body.name, text=text, x=round(body.x, 1), y=round(body.y, 1),
                         z=round(body.z, 1))

    def find_entity(self, ref, near=None, max_dist=64.0):
        """An entity by id, by name (visitor/agent name) or by kind ('cow' → nearest cow within max_dist)."""
        if ref is None:
            return None
        if isinstance(ref, (int, float)) or (isinstance(ref, str) and ref.isdigit()):
            return self.entities.get(int(ref))
        s = str(ref).strip().lower()
        if s in ("visitor", "player", "you", "me") and self.visitor is not None:
            return self.visitor
        if s in ("agent", "self", "inhabitant"):
            return self.agent
        for e in self.entities.values():
            nm = getattr(e, "name", None)
            if nm and nm.lower() == s and not getattr(e, "dead", False):
                return e
        s = s.replace("nearest ", "").replace("the ", "")
        if s.endswith("s") and s[:-1] in _CREATURE_KINDS():
            s = s[:-1]
        best, bd = None, 1e18
        nx, ny, nz = (near.x, near.y, near.z) if near is not None else (self.agent.x, self.agent.y, self.agent.z)
        for e in self.entities.values():
            k = getattr(e, "kind", "")
            if k == s or (k == "item" and getattr(e, "item", None) == s):
                if getattr(e, "dead", False) or e is near:
                    continue
                d = (e.x - nx) ** 2 + (e.y - ny) ** 2 + (e.z - nz) ** 2
                if d < bd and d <= max_dist * max_dist:
                    best, bd = e, d
        return best

    # ------------------------------------------------------------------ queries
    def raycast(self, origin, direction, reach=REACH, entities=False, skip=None, fluids=False) -> dict | None:
        """First block (and optionally entity) along a ray. Returns {block:[x,y,z], id, name, face:[dx,dy,dz],
        place:[x,y,z], dist} or {entity, dist} or None."""
        ox, oy, oz = origin
        dx, dy, dz = direction
        ln = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
        dx, dy, dz = dx / ln, dy / ln, dz / ln
        ent_hit = None
        if entities:
            for e in self.entities.values():
                if e is skip or getattr(e, "dead", False):
                    continue
                hw = getattr(e, "w", 0.3) / 2
                hh = getattr(e, "h", 0.3)
                t = _ray_box(ox, oy, oz, dx, dy, dz, e.x - hw, e.y, e.z - hw, e.x + hw, e.y + hh, e.z + hw)
                if t is not None and t <= reach and (ent_hit is None or t < ent_hit[0]):
                    ent_hit = (t, e)
        x, y, z = math.floor(ox), math.floor(oy), math.floor(oz)
        sx = 1 if dx > 0 else -1
        sy = 1 if dy > 0 else -1
        sz = 1 if dz > 0 else -1
        tdx = abs(1 / dx) if dx else 1e30
        tdy = abs(1 / dy) if dy else 1e30
        tdz = abs(1 / dz) if dz else 1e30
        tmx = ((x + (sx > 0)) - ox) / dx if dx else 1e30
        tmy = ((y + (sy > 0)) - oy) / dy if dy else 1e30
        tmz = ((z + (sz > 0)) - oz) / dz if dz else 1e30
        face = (0, 0, 0)
        t = 0.0
        while t <= reach:
            bid = self.get(x, y, z)
            if bid != AIR and (fluids or not B.LIQUID[bid]):
                if ent_hit and ent_hit[0] < t:
                    break
                return {"block": [x, y, z], "id": bid, "name": NAME[bid], "face": list(face),
                        "place": [x + face[0], y + face[1], z + face[2]], "dist": round(t, 3)}
            if tmx < tmy and tmx < tmz:
                x += sx
                t = tmx
                tmx += tdx
                face = (-sx, 0, 0)
            elif tmy < tmz:
                y += sy
                t = tmy
                tmy += tdy
                face = (0, -sy, 0)
            else:
                z += sz
                t = tmz
                tmz += tdz
                face = (0, 0, -sz)
        if ent_hit:
            e = ent_hit[1]
            return {"entity": e.id, "kind": e.kind, "name": getattr(e, "name", None), "dist": round(ent_hit[0], 3)}
        return None

    def find_blocks(self, ids, x, y, z, radius=24, limit=64, dy=None) -> list:
        """Positions of blocks with ids in ``ids`` within a box radius, nearest first."""
        x, y, z = math.floor(x), math.floor(y), math.floor(z)
        dy = radius if dy is None else dy
        a = self.region_blocks(x - radius, max(0, y - dy), z - radius, x + radius + 1, min(256, y + dy + 1),
                               z + radius + 1)
        hits = np.argwhere(np.isin(a, list(ids)))
        if not len(hits):
            return []
        y0 = max(0, y - dy)
        pts = hits[:, [2, 0, 1]] + np.array([x - radius, y0, z - radius])
        d = ((pts - np.array([x, y, z])) ** 2).sum(axis=1)
        order = np.argsort(d, kind="stable")[:limit]
        return [tuple(p) for p in pts[order].tolist()]

    def stand_y(self, x, z, y_hint=None):
        """The feet y of the top standable spot in a column (near y_hint if given)."""
        x, z = math.floor(x), math.floor(z)
        if y_hint is None:
            ch = self._chunk(x >> 4, z >> 4)
            y = int(ch.top[z & 15, x & 15]) + 1
            while y > 1 and not SOLID[self.get(x, y - 1, z)]:
                y -= 1
            return y
        y = int(y_hint)
        for d in range(0, 24):
            for yy in (y + d, y - d):
                if SOLID[self.get(x, yy - 1, z)] and not SOLID[self.get(x, yy, z)] and not SOLID[self.get(x, yy + 1, z)]:
                    return yy
        return y

    # ------------------------------------------------------------------ the visitor
    def visitor_action(self, cmd: dict) -> dict:
        """The page's commands for the visitor: join|leave|move|dig|place|use|give|drop|select|say."""
        with self.lock:
            a = cmd.get("action")
            v = self.visitor
            if a == "join":
                if v is None:
                    ax, az = self.agent.x + 2, self.agent.z + 2
                    y = self.stand_y(ax, az, self.agent.y)
                    v = self.visitor = Player(self, math.floor(ax) + 0.5, y, math.floor(az) + 0.5, kind="visitor",
                                              name=cmd.get("name") or "Visitor", eid=2)
                    self.entities[2] = v
                    self._update_active()
                    self.emit("joined", who=2, name=v.name)
                return {"ok": True, "visitor": v.status()}
            if v is None:
                return {"ok": False, "text": "No visitor in the world."}
            if a == "leave":
                self.entities.pop(2, None)
                self.visitor = None
                self.emit("left", who=2, name=v.name)
                return {"ok": True}
            if a == "move":
                if "x" in cmd:
                    v.x, v.y, v.z = float(cmd["x"]), float(cmd["y"]), float(cmd["z"])
                    v.vx = v.vz = 0.0
                    v.vy = float(cmd.get("vy", 0.0))
                    v.remote = True
                    v.anim = cmd.get("anim", "walk" if cmd.get("moving") else "idle")
                elif any(k in cmd for k in ("forward", "strafe", "move_x", "move_z", "jump")):
                    v.remote = False
                if "yaw" in cmd:
                    v.yaw = float(cmd["yaw"])
                if "pitch" in cmd:
                    v.pitch = float(cmd["pitch"])
                for k in ("move_x", "move_z"):
                    if k in cmd:
                        setattr(v, k, float(cmd[k]))
                if "forward" in cmd or "strafe" in cmd:
                    f, s = float(cmd.get("forward", 0)), float(cmd.get("strafe", 0))
                    sy, cy = math.sin(v.yaw), math.cos(v.yaw)
                    v.move_x = -sy * f + cy * s
                    v.move_z = -cy * f - sy * s
                for k in ("jump", "sneak", "sprint", "descend"):
                    if k in cmd:
                        setattr(v, k, bool(cmd[k]))
                return {"ok": True}
            if a == "select":
                v.selected = int(cmd.get("slot", 0)) % 9
                return {"ok": True}
            if a == "say":
                self.say(v, cmd.get("text", ""))
                return {"ok": True}
            x, y, z = (int(cmd[k]) for k in ("x", "y", "z")) if "x" in cmd else (None, None, None)
            if a in ("dig", "place", "use") and x is not None:
                if math.dist(v.eye(), (x + 0.5, y + 0.5, z + 0.5)) > 6.0:
                    return {"ok": False, "text": "Too far."}
            if a == "dig":
                bid = self.get(x, y, z)
                if HARD[bid] < 0:
                    return {"ok": False, "text": "Unbreakable."}
                tool = v.held()
                drops = self.break_block(x, y, z, by=v, tool=tool)
                it = IT.by_name.get(tool) if tool else None
                if it and it["tool"]:
                    v.wear_tool()
                return {"ok": True, "drops": drops}
            if a == "place":
                item = cmd.get("item") or v.held()
                if not item or not v.has(item):
                    return {"ok": False, "text": "Nothing to place."}
                bid = cmd.get("block")
                bid = I[bid] if isinstance(bid, str) else (bid or IT.place_block(item))
                if bid is None:
                    return {"ok": False, "text": "That can't be placed."}
                if item in ("water_bucket", "lava_bucket"):
                    self.set(x, y, z, bid, by=v)
                    v.remove(item, 1)
                    v.add("bucket", 1)
                    return {"ok": True}
                ok, why = self.place_block(x, y, z, bid, by=v)
                if ok:
                    v.remove(item, 1)
                return {"ok": ok, "text": why}
            if a == "use":
                return self.use_block(x, y, z, by=v)
            if a == "give":
                item, n = cmd.get("item") or v.held(), int(cmd.get("count", 1))
                if not item or not v.has(item):
                    return {"ok": False, "text": "You don't have that."}
                if math.dist((v.x, v.y, v.z), (self.agent.x, self.agent.y, self.agent.z)) > 6:
                    return {"ok": False, "text": f"{self.agent.name} is too far away."}
                n = v.remove(item, n)
                left = self.agent.add(item, n)
                if left:
                    self.spawn_item(self.agent.x, self.agent.y + 1, self.agent.z, item, left)
                self.emit("gave", who=2, name=v.name, to=1, item=item, count=n)
                return {"ok": True}
            if a == "drop":
                item = cmd.get("item") or v.held()
                e = self.drop_from(v, item, int(cmd.get("count", 1)))
                return {"ok": e is not None}
            if a == "craft":
                return self.craft(v, cmd.get("item"), int(cmd.get("count", 1)))
            if a == "eat":
                ok = v.eat(cmd.get("item") or v.held())
                return {"ok": ok}
            return {"ok": False, "text": f"Unknown visitor action {a!r}."}

    # ------------------------------------------------------------------ wire format
    def chunk_bytes(self, cx, cz) -> bytes:
        """zlib-compressed uint16 little-endian blocks, index = x + 16*(z + 16*y)."""
        with self.lock:
            ch = self._chunk(cx, cz)
            if ch.zcache is None:
                ch.zcache = zlib.compress(ch.b.astype("<u2", copy=False).tobytes(), 6)
            return ch.zcache

    def agent_status(self) -> dict:
        a = self.agent
        d = a.status()
        d.update({"skill": self.skills.current, "progress": round(self.skills.progress, 3),
                  "status": self.skills.status, "biome": self.biome(a.x, a.z)})
        d.update(self.agent_info)
        return d

    def snapshot(self, full: bool = False) -> dict:
        """The §4 tick payload: changes since the previous snapshot (``full`` resends every entity)."""
        with self.lock:
            ents = []
            seen = set()
            centers = [(p.x, p.z) for p in self._players()]
            for e in self.entities.values():
                if any((e.x - cx) ** 2 + (e.z - cz) ** 2 < 64 * 64 for cx, cz in centers):
                    ents.append(e.public())
                    seen.add(e.id)
            removed = [] if full else sorted(self._sent_ids - seen)
            self._sent_ids = seen
            if full:
                blocks = []
            else:
                blocks = [[x, y, z, b] for (x, y, z), b in self._changes.items()]
            self._changes = {}
            events = self._events
            self._events = []
            reload = set(self._reload)
            self._reload.clear()
            if len(blocks) > 6000:
                reload |= {(b[0] >> 4, b[2] >> 4) for b in blocks}
                blocks = []
            elif reload:
                blocks = [b for b in blocks if (b[0] >> 4, b[2] >> 4) not in reload]
            reload = sorted(reload)
            snap = {"t": self.t, "day": self.day(), "time": round(self.time_of_day(), 4), "clock": self.clock(),
                    "weather": self.weather, "light": self.sky_level(), "moon": self.moon_phase(),
                    "blocks": blocks, "entities": ents, "removed": removed, "agent": self.agent_status(),
                    "visitor": self.visitor.status() if self.visitor else None, "events": events}
            if reload:
                snap["reload"] = [list(k) for k in reload]
            if full:
                snap["spawn"] = list(self.spawn)
                snap["places"] = self.places
            return snap

    # ------------------------------------------------------------------ persistence
    def _save_chunk(self, ch):
        if not self.region:
            return
        x0, z0 = ch.cx * 16, ch.cz * 16

        def inside(p):
            return len(p) == 3 and x0 <= p[0] < x0 + 16 and z0 <= p[2] < z0 + 16
        head = {"containers": [[*p, c] for p, c in self.containers.items() if inside(p)],
                "meta": [[*p, m] for p, m in self.meta.items() if inside(p)]}
        hj = json.dumps(head, separators=(",", ":")).encode()
        raw = struct.pack("<I", len(hj)) + hj + ch.b.astype("<u2", copy=False).tobytes()
        f = self._chunk_file(ch.cx, ch.cz)
        tmp = f.with_suffix(".tmp")
        tmp.write_bytes(zlib.compress(raw, 6))
        os.replace(tmp, f)
        ch.dirty = False
        ch.saved = True

    def state(self) -> dict:
        from .creatures import Creature
        ents = []
        for e in self.entities.values():
            if isinstance(e, Creature):
                ents.append({"type": "creature", **e.to_dict()})
            elif isinstance(e, ItemEntity):
                ents.append({"type": "item", "item": e.item, "count": e.count, "pos": [e.x, e.y, e.z], "age": e.age,
                             "dur": e.dur})
        return {"version": self.VERSION, "seed": self.seed, "t": self.t, "time_offset": self.time_offset,
                "day_ticks": self.day_ticks, "weather": self.weather, "weather_timer": self.weather_timer,
                "peaceful": self.peaceful, "agent": self.agent.to_dict(), "entities": ents, "places": self.places,
                "spawned_chunks": [list(k) for k in self._spawned_chunks], "next_id": self._next_id,
                "growth": self.growth, "agent_info": self.agent_info}

    def save(self, partial=False):
        if not self.region:
            return
        with self.lock:
            n = 0
            for ch in list(self.chunks.values()):
                if ch.dirty:
                    self._save_chunk(ch)
                    n += 1
                    if partial and n >= 16:
                        break
            st = json.dumps(self.state(), separators=(",", ":")).encode()
            f = self.region / "world.json.z"
            tmp = f.with_suffix(".tmp")
            tmp.write_bytes(zlib.compress(st, 6))
            os.replace(tmp, f)

    def _restore(self, st):
        self.t = st.get("t", 0)
        self.time_offset = st.get("time_offset", self.time_offset)
        self.weather = st.get("weather", "clear")
        self.weather_timer = st.get("weather_timer", self.weather_timer)
        self.peaceful = st.get("peaceful", self.peaceful)
        self.places = st.get("places", {})
        self.growth = st.get("growth", 1.0)
        self.agent_info = st.get("agent_info", {})
        self._spawned_chunks = {tuple(k) for k in st.get("spawned_chunks", [])}
        self._next_id = max(self._next_id, st.get("next_id", 100))
        self.agent.load_dict(st["agent"])
        from .creatures import Creature
        for d in st.get("entities", []):
            if d["type"] == "creature":
                c = Creature.from_dict(self, d)
                self.entities[c.id] = c
            elif d["type"] == "item":
                e = ItemEntity(self, *d["pos"], d["item"], d["count"], 0)
                e.age, e.dur = d.get("age", 0), d.get("dur")
                self.entities[e.id] = e

    @classmethod
    def load(cls, folder, **kw) -> "VoxelWorld":
        f = Path(folder) / "region" / "world.json.z"
        st = json.loads(zlib.decompress(f.read_bytes()))
        kw.setdefault("day_seconds", st.get("day_ticks", 24000) / TICKS_PER_SEC)
        return cls(st["seed"], folder, _restore=st, **kw)

    @classmethod
    def open(cls, seed, folder, **kw) -> "VoxelWorld":
        """Load the world in ``folder`` if one was saved there, else create it from ``seed``."""
        if folder and (Path(folder) / "region" / "world.json.z").exists():
            return cls.load(folder, **kw)
        return cls(seed, folder, **kw)

    def close(self):
        if self.folder:
            self.save()
        if self._pool:
            self._pool.shutdown(wait=False, cancel_futures=True)

    # ------------------------------------------------------------------ stats
    def perf_stats(self) -> dict:
        if not self.perf:
            return {}
        a = sorted(self.perf)
        return {"ticks": len(a), "avg_ms": round(1000 * sum(a) / len(a), 3),
                "p99_ms": round(1000 * a[min(len(a) - 1, int(len(a) * 0.99))], 3),
                "max_ms": round(1000 * a[-1], 3), "chunks": len(self.chunks), "active": len(self.active),
                "entities": len(self.entities)}


def _container_slots(c):
    if c.get("kind") == "chest":
        return c["slots"]
    return [c.get("input"), c.get("fuel"), c.get("output")]


def _ray_box(ox, oy, oz, dx, dy, dz, x0, y0, z0, x1, y1, z1):
    tmin, tmax = -1e30, 1e30
    for o, d, a, b in ((ox, dx, x0, x1), (oy, dy, y0, y1), (oz, dz, z0, z1)):
        if abs(d) < 1e-12:
            if o < a or o > b:
                return None
        else:
            t1, t2 = (a - o) / d, (b - o) / d
            if t1 > t2:
                t1, t2 = t2, t1
            tmin, tmax = max(tmin, t1), min(tmax, t2)
            if tmin > tmax:
                return None
    if tmax < 0:
        return None
    return max(tmin, 0.0)


def _CREATURE_KINDS():
    from .creatures import KINDS
    return KINDS
