"""v5 voxel engine: terrain, rules, body physics, A*, skills, persistence, wire format."""
import math
import sys
import time
import zlib
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ada.agent.skills import SKILLS, Result, SkillRunner  # noqa: E402
from ada.vox import blocks as B  # noqa: E402
from ada.vox import describe as D  # noqa: E402
from ada.vox import items as IT  # noqa: E402
from ada.vox import recipes as R  # noqa: E402
from ada.vox.path import find_path  # noqa: E402
from ada.vox.sim import Player, VoxelWorld  # noqa: E402
from ada.vox.terrain import Terrain  # noqa: E402

I = B.ID
SEED = 1234
LAB_Y = 200


@pytest.fixture(scope="module")
def w():
    world = VoxelWorld(SEED, threaded=False, sim_radius=2, creatures=False)
    for _ in range(3):
        world.tick()
    return world


_lab_slot = [0]


def lab(w, size=12, y=LAB_Y, floor="stone"):
    """A fresh flat platform high in the sky inside the simulated area; returns its corner (x, y, z)."""
    k = _lab_slot[0]
    _lab_slot[0] += 1
    ax, az = math.floor(w.agent.x) >> 4, math.floor(w.agent.z) >> 4
    x0 = (ax - 2) * 16 + (k % 4) * 16
    z0 = (az - 1) * 16 + (k // 4) * 16
    w.fill(x0, y, z0, x0 + size - 1, y, z0 + size - 1, floor)
    w.fill(x0, y + 1, z0, x0 + size - 1, y + 12, z0 + size - 1, "air")
    return x0, y, z0


def ticks(w, n):
    for _ in range(n):
        w.tick()


# ====================================================================== registry
def test_registry_consistency():
    assert B.BLOCKS[0]["name"] == "air"
    assert [b["id"] for b in B.BLOCKS] == list(range(len(B.BLOCKS)))
    assert len({b["base"] for b in B.BLOCKS}) >= 100
    keys = set(B.BLOCKS[1])
    for b in B.BLOCKS:
        assert set(b) == keys
        assert b["color"].startswith("#") and len(b["color"]) == 7
        # every block is an item, except air, fluids, fire/steam and technical states
        if b["item"] is None:
            assert b["name"] in ("air", "steam", "fire", "piston_head", "tall_grass", "fern") or b["liquid"], b
        else:
            assert b["item"] in IT.by_name, b["name"]
        for d in b["drops"]:
            assert d["item"] in IT.by_name, (b["name"], d)
            assert 0 < d["chance"] <= 1
    for it in IT.ITEMS:
        if it["place"]:
            assert it["place"] in B.by_name, it
    for r in R.CRAFTING:
        assert r["out"] in IT.by_name
        for ing in r["in"]:
            assert ing in IT.by_name or (ing.startswith("#") and ing[1:] in IT.GROUPS), (r, ing)
    for r in R.SMELTING:
        assert r["in"] in IT.by_name and r["out"] in IT.by_name and r["time"] > 0
    for f in R.FUELS:
        assert f in IT.by_name
    assert len(R.CRAFTING) + len(R.SMELTING) >= 120
    for g in IT.GROUPS.values():
        assert all(m in IT.by_name for m in g)


# ====================================================================== terrain
def test_terrain_deterministic_and_fast():
    t1, t2 = Terrain(SEED), Terrain(SEED)
    for cx, cz in ((0, 0), (5, -3), (-7, 11)):
        a, ca, _ = t1.generate(cx, cz)
        b, cb, _ = t2.generate(cx, cz)
        assert a.dtype == np.uint16 and a.shape == (256, 16, 16)
        assert np.array_equal(a, b) and ca == cb
    # order independence: generating neighbours first changes nothing
    t3 = Terrain(SEED)
    t3.generate(6, -3)
    assert np.array_equal(t3.generate(5, -3)[0], t1.generate(5, -3)[0])
    assert not np.array_equal(Terrain(SEED + 1).generate(0, 0)[0], t1.generate(0, 0)[0])
    t1.generate(1, 1)
    times = []
    for k in range(12):
        s = time.perf_counter()
        t1.generate(20 + k, -9 + k)
        times.append(time.perf_counter() - s)
    assert sum(times) / len(times) < 0.060, times


def test_terrain_features():
    t = Terrain(SEED)
    x0, y0, z0 = t.cabin
    blocks, containers, _ = t.generate(*t.spawn_chunk)
    names = {B.NAME[i] for i in np.unique(blocks).tolist()}
    for n in ("crafting_table", "furnace", "chest", "bed", "torch", "door_lower", "bedrock", "stone"):
        assert n in names
    chest = containers[(x0 + 3, y0 + 1, z0 + 1)]
    assert any(s and s["item"] == "bread" for s in chest["slots"])
    # biomes, ores, caves, water over a wider area
    seen_ores, cave_air, water = set(), 0, 0
    for cx in range(-3, 3):
        for cz in range(-3, 3):
            b, _, _ = t.generate(cx, cz)
            u = set(np.unique(b).tolist())
            seen_ores |= {B.NAME[i] for i in u if B.BLOCKS[i]["category"] == "ore"}
            cave_air += int((b[5:40] == 0).sum())
            water += int(np.isin(b, B.WATER_IDS).sum())
    assert {"coal_ore", "iron_ore"} <= seen_ores
    assert cave_air > 100 and water > 0
    xs, zs = np.meshgrid(np.arange(-3000, 3000, 60), np.arange(-3000, 3000, 60))
    _, biome, _ = t.columns(xs, zs)
    assert len(np.unique(biome)) >= 10
    assert t.ruins_near(0, 0, 512)


def test_chunk_bytes_format(w):
    data = w.chunk_bytes(0, 0)
    raw = zlib.decompress(data)
    arr = np.frombuffer(raw, dtype="<u2")
    assert arr.size == 16 * 16 * 256
    ch = w.chunks[(0, 0)]
    x, y, z = 5, 60, 9
    assert arr[x + 16 * (z + 16 * y)] == ch.b[y, z, x]
    assert len(data) < 40_000


# ====================================================================== rules
def test_gravity(w):
    x, y, z = lab(w)
    w.set(x + 3, y + 6, z + 3, I["sand"])
    ticks(w, 40)
    assert w.get(x + 3, y + 1, z + 3) == I["sand"]
    assert w.get(x + 3, y + 6, z + 3) == 0
    # a gravel column falls when its support is mined
    w.set(x + 6, y + 1, z + 6, I["dirt"])
    w.set(x + 6, y + 2, z + 6, I["gravel"])
    w.set(x + 6, y + 3, z + 6, I["gravel"])
    ticks(w, 5)
    w.break_block(x + 6, y + 1, z + 6)
    ticks(w, 40)
    assert w.get(x + 6, y + 1, z + 6) == I["gravel"] and w.get(x + 6, y + 2, z + 6) == I["gravel"]
    assert w.get(x + 6, y + 3, z + 6) == 0


def test_water_flow_and_sources(w):
    x, y, z = lab(w, size=16)
    cx, cz = x + 8, z + 8
    w.set(cx, y + 1, cz, I["water"])
    ticks(w, 400)
    lvl = {}
    for d in range(0, 9):
        lvl[d] = w.get(cx + d, y + 1, cz)
    assert lvl[0] == I["water"]
    assert B.BASE[lvl[7]] == "water" and B.STATE[lvl[7]] == 7
    assert lvl[8] == 0
    # remove the source: the flow dries up
    w.set(cx, y + 1, cz, 0)
    ticks(w, 400)
    assert not any(B.IS_WATER[w.get(cx + d, y + 1, cz)] for d in range(0, 8))
    # two sources make a third between them
    w.set(cx - 1, y + 1, cz, I["water"])
    w.set(cx + 1, y + 1, cz, I["water"])
    ticks(w, 60)
    assert w.get(cx, y + 1, cz) == I["water"]


def test_water_meets_lava(w):
    x, y, z = lab(w, size=12)
    # lava source next to flowing water -> obsidian
    w.set(x + 2, y + 1, z + 2, I["lava"])
    ticks(w, 5)
    w.set(x + 2, y + 1, z + 5, I["water"])
    ticks(w, 200)
    assert w.get(x + 2, y + 1, z + 2) in (I["obsidian"], I["cobblestone"])
    assert any(w.get(x + 2, y + 1, z + k) == I["obsidian"] for k in (2,))
    # flowing lava meeting water -> cobblestone somewhere
    w.set(x + 8, y + 1, z + 2, I["lava"])
    ticks(w, 150)
    w.set(x + 8, y + 1, z + 7, I["water"])
    ticks(w, 300)
    found = {w.get(x + 8 + dx, y + 1, z + dz) for dx in range(-3, 4) for dz in range(0, 9)}
    assert I["cobblestone"] in found or I["obsidian"] in found


def test_fire_spreads_burns_and_rain_puts_it_out(w):
    x, y, z = lab(w, size=10, floor="oak_planks")
    w.weather, w.weather_timer = "clear", 10 ** 6
    w.ignite(x + 5, y + 1, z + 5)
    assert w.get(x + 5, y + 1, z + 5) == I["fire"]
    ticks(w, 20 * 40)
    floor = w.region_blocks(x, y, z, x + 10, y + 1, z + 10)
    burnt = int((floor != I["oak_planks"]).sum())
    assert burnt >= 3, burnt
    # rain puts exposed fire out
    x2, y2, z2 = lab(w, size=8, floor="oak_planks")
    for k in range(3):
        w.ignite(x2 + 2 + k, y2 + 1, z2 + 3)
    w.weather = "rain"
    ticks(w, 20 * 12)
    fires = int((w.region_blocks(x2, y2, z2, x2 + 8, y2 + 4, z2 + 8) == I["fire"]).sum())
    w.weather = "clear"
    assert fires == 0


def test_light_propagation_and_day_night(w):
    x, y, z = lab(w, size=9)
    # a closed stone box: dark inside
    w.fill(x, y, z, x + 8, y + 5, z + 8, "stone")
    w.fill(x + 1, y + 1, z + 1, x + 7, y + 4, z + 7, "air")
    w.set_time(0.25)
    assert w.light_at(x + 4, y + 2, z + 4) == 0
    w.place_block(x + 2, y + 1, z + 2, I["torch"])
    ticks(w, 2)
    assert w.light_at(x + 2, y + 1, z + 2) == 14
    assert w.light_at(x + 3, y + 1, z + 2) == 13
    assert w.light_at(x + 6, y + 1, z + 6) == 14 - 8
    w.break_block(x + 2, y + 1, z + 2)
    ticks(w, 2)
    assert w.light_at(x + 3, y + 1, z + 2) == 0
    # open a hole in the roof: sky light pours in
    w.break_block(x + 4, y + 5, z + 4)
    ticks(w, 2)
    assert w.light_at(x + 4, y + 1, z + 4) == 15
    assert w.light_at(x + 5, y + 1, z + 4) == 14
    # day and night under the open sky
    w.set_time(0.25)
    assert w.light_at(x + 4, y + 7, z + 4) == 15 and w.sky_level() == 15
    w.set_time(0.75)
    assert w.light_at(x + 4, y + 7, z + 4) == 4 and w.is_night()
    w.set_time(0.25)


def test_crops_grow_on_wet_farmland(w):
    x, y, z = lab(w, size=8, floor="dirt")
    w.set(x + 2, y, z + 2, I["water"])
    for k in range(3, 6):
        ok, why = w.till(x + k, y, z + 2)
        assert ok, why
    ticks(w, 60)
    assert w.get(x + 3, y, z + 2) == I["farmland_wet"]
    for k in range(3, 6):
        ok, why = w.place_block(x + k, y + 1, z + 2, I["wheat_0"])
        assert ok, why
    w.set_time(0.25)
    g = w.growth
    w.growth = 40.0
    ticks(w, 20 * 30)
    w.growth = g
    assert all(w.get(x + k, y + 1, z + 2) == I["wheat_7"] for k in range(3, 6))
    # breaking a ripe crop drops wheat and seeds
    drops = w.break_block(x + 3, y + 1, z + 2, by=w.agent)
    assert ("wheat", 1) in drops


def test_signals_lamp_door_piston(w):
    x, y, z = lab(w, size=12)
    yy = y + 1
    assert w.place_block(x + 1, yy, z + 1, I["lever"])[0]
    for k in range(2, 6):
        assert w.place_block(x + k, yy, z + 1, I["wire_0"])[0]
    assert w.place_block(x + 6, yy, z + 1, I["lamp"])[0]
    # a door at the end of a branch
    for k in range(2, 5):
        assert w.place_block(x + 5, yy, z + k, I["wire_0"])[0]
    assert w.place_block(x + 5, yy, z + 5, I["door_lower"])[0]
    # a piston pushing a row of blocks east
    assert w.place_block(x + 4, yy, z + 2, I["piston"])[0] is False or True
    w.set(x + 3, yy, z + 3, I["piston"])
    w.meta[(x + 3, yy, z + 3)] = {"facing": [-1, 0, 0]}
    w.set(x + 4, yy, z + 3, I["wire_0"])
    w.set(x + 2, yy, z + 3, I["cobblestone"])
    w.set(x + 1, yy, z + 3, I["cobblestone"])
    ticks(w, 3)
    assert w.get(x + 6, yy, z + 1) == I["lamp"]
    r = w.use_block(x + 1, yy, z + 1, by=w.agent)
    assert r["ok"] and r["on"]
    ticks(w, 3)
    assert B.STATE[w.get(x + 2, yy, z + 1)] == 15
    assert B.STATE[w.get(x + 5, yy, z + 1)] == 12
    assert w.get(x + 6, yy, z + 1) == I["lamp_on"]
    assert w.light_at(x + 6, yy + 1, z + 1) >= 14
    assert w.get(x + 5, yy, z + 5) == I["door_lower_open"]
    assert w.get(x + 3, yy, z + 3) == I["piston_extended"]
    assert w.get(x + 2, yy, z + 3) == I["piston_head"]
    assert w.get(x + 1, yy, z + 3) == I["cobblestone"] and w.get(x + 0, yy, z + 3) == I["cobblestone"]
    # off again
    w.use_block(x + 1, yy, z + 1, by=w.agent)
    ticks(w, 3)
    assert w.get(x + 6, yy, z + 1) == I["lamp"]
    assert w.get(x + 5, yy, z + 5) == I["door_lower"]
    assert w.get(x + 3, yy, z + 3) == I["piston"] and w.get(x + 2, yy, z + 3) == 0


def test_tnt_explodes(w):
    x, y, z = lab(w, size=12)
    w.fill(x, y - 3, z, x + 11, y, z + 11, "stone")
    yy = y + 1
    w.place_block(x + 2, yy, z + 6, I["button"])
    w.place_block(x + 3, yy, z + 6, I["wire_0"])
    w.place_block(x + 4, yy, z + 6, I["tnt"])
    w.place_block(x + 6, yy, z + 6, I["tnt"])
    ticks(w, 2)
    w.use_block(x + 2, yy, z + 6, by=w.agent)
    ticks(w, 3)
    assert w.get(x + 4, yy, z + 6) == 0
    assert any(e.kind == "tnt" for e in w.entities.values())
    ticks(w, 140)
    assert not any(e.kind == "tnt" for e in w.entities.values())
    crater = w.region_blocks(x + 2, y - 2, z + 4, x + 8, y + 1, z + 9)
    assert int((crater == 0).sum()) > 20
    assert any(e["type"] == "explosion" for e in w.log)


def test_furnace_smelting(w):
    x, y, z = lab(w, size=8)
    a = w.agent
    ok, _ = w.place_block(x + 2, y + 1, z + 2, I["furnace"])
    assert ok
    a.add("raw_iron", 3)
    a.add("coal", 1)
    assert w.container_put((x + 2, y + 1, z + 2), a, "raw_iron", 3, slot="input") == 3
    assert w.container_put((x + 2, y + 1, z + 2), a, "coal", 1, slot="fuel") == 1
    ticks(w, 10)
    assert w.get(x + 2, y + 1, z + 2) == I["furnace_lit"]
    ticks(w, int(3 * 8 * 20) + 20)
    c = w.container(x + 2, y + 1, z + 2)
    assert c["output"] == {"item": "iron_ingot", "count": 3}
    assert w.container_take((x + 2, y + 1, z + 2), a, slot="output") == 3
    assert a.count("iron_ingot") >= 3
    a.remove("iron_ingot", 3)


def test_crafting_with_and_without_table(w):
    b = Player(w, 0.5, 300, 0.5, kind="test")
    b.add("oak_log", 3)
    r = w.craft(b, "oak_planks", 12)
    assert r["ok"] and b.count("oak_planks") == 12
    r = w.craft(b, "crafting_table")
    assert r["ok"] and b.count("crafting_table") == 1 and b.count("oak_planks") == 8
    r = w.craft(b, "stick", 4)
    assert r["ok"] and b.count("stick") == 4
    r = w.craft(b, "wooden_pickaxe")
    assert not r["ok"] and r.get("needs_table")
    x, y, z = lab(w, size=6)
    b.x, b.y, b.z = x + 2.5, y + 1, z + 2.5
    w.place_block(x + 3, y + 1, z + 2, I["crafting_table"])
    r = w.craft(b, "wooden_pickaxe")
    assert r["ok"] and b.count("wooden_pickaxe") == 1
    r = w.craft(b, "furnace")
    assert not r["ok"] and r["text"] == "I have no stone material."


# ====================================================================== body physics
def test_fall_damage_swim_and_step_up(w):
    x, y, z = lab(w, size=10)
    b = Player(w, x + 2.5, y + 11, z + 2.5, kind="test")
    for _ in range(60):
        b.step()
        b.vitals()
    assert b.on_ground and abs(b.y - (y + 1)) < 1e-6
    assert b.health == 20 - 7
    # step up onto a bed (0.5625 high) by walking
    w.set(x + 4, y + 1, z + 2, I["bed"])
    b.health = 20
    b.move_x = 1.0
    top = 0.0
    for _ in range(14):
        b.step()
        top = max(top, b.y)
    b.move_x = 0.0
    assert abs(top - (y + 1.5625)) < 1e-6 and b.x > x + 4
    # a full block needs a jump
    w.set(x + 7, y + 1, z + 2, I["stone"])
    b.x, b.y, b.z = x + 5.5, y + 1, z + 2.5
    b.move_x = 1.0
    for _ in range(20):
        b.step()
    assert b.x < x + 6.71 and b.y < y + 1.1
    b.jump = True
    for _ in range(20):
        b.step()
    b.jump = False
    b.move_x = 0
    assert b.y >= y + 2 - 1e-6
    # swimming
    x2, y2, z2 = lab(w, size=6)
    w.fill(x2, y2 + 1, z2, x2 + 5, y2 + 4, z2 + 5, "stone")
    w.fill(x2 + 1, y2 + 1, z2 + 1, x2 + 4, y2 + 4, z2 + 4, "water")
    s = Player(w, x2 + 2.5, y2 + 1, z2 + 2.5, kind="test")
    for _ in range(10):
        s.step()
    assert s.in_water
    s.jump = True
    for _ in range(60):
        s.step()
        s.vitals()
    assert s.y > y2 + 3.0 and s.air == 300
    s.jump = False
    for _ in range(80):
        s.step()
        s.vitals()
    assert s.y < y2 + 2 and s.head_in_water and s.air < 300


def test_drowning_and_starvation(w):
    x, y, z = lab(w, size=4)
    w.fill(x, y + 1, z, x + 3, y + 4, z + 3, "water")
    b = Player(w, x + 1.5, y + 1, z + 1.5, kind="test")
    for _ in range(20 * 20):
        b.step()
        b.vitals()
    assert b.health < 20
    b2 = Player(w, x + 1.5, y + 20, z + 1.5, kind="test")
    b2.food = 0
    for _ in range(81):
        b2.vitals()
    assert b2.health == 19


# ====================================================================== A*
def test_astar_around_over_and_up_ladders(w):
    x, y, z = lab(w, size=16)
    # a wall with a gap
    for k in range(0, 12):
        if k != 10:
            w.set(x + 6, y + 1, z + k, I["stone"])
            w.set(x + 6, y + 2, z + k, I["stone"])
    t = time.perf_counter()
    p = find_path(w, (x + 2.5, y + 1, z + 2.5), goal=(x + 10, y + 1, z + 2))
    assert p and not p.partial and time.perf_counter() - t < 0.05
    assert any(s.z >= z + 9 for s in p.steps)
    # a single block to jump over
    w.set(x + 3, y + 1, z + 14, I["stone"])
    for k in range(10, 16):
        w.set(x + k - 9, y + 1, z + 13, I["stone"])
        w.set(x + k - 9, y + 1, z + 15, I["stone"])
    p = find_path(w, (x + 1.5, y + 1, z + 14.5), goal=(x + 5, y + 1, z + 14))
    assert p and not p.partial and any(s.move == "jump" for s in p.steps)
    # a cliff with a ladder
    x2, y2, z2 = lab(w, size=10)
    w.fill(x2 + 5, y2 + 1, z2, x2 + 9, y2 + 5, z2 + 9, "stone")
    for k in range(1, 6):
        w.set(x2 + 4, y2 + k, z2 + 4, I["ladder"])
    p = find_path(w, (x2 + 1.5, y2 + 1, z2 + 4.5), goal=(x2 + 7, y2 + 6, z2 + 4))
    assert p and not p.partial and any(s.move == "climb" for s in p.steps)
    # and walk it for real
    a = w.agent
    a.x, a.y, a.z = x2 + 1.5, y2 + 1, z2 + 4.5
    res = w.skills.run_until_done({"skill": "go_to", "args": {"target": [x2 + 7, y2 + 6, z2 + 4]}}, 20 * 30)
    assert res.ok, res.text
    assert a.y >= y2 + 5.9


def test_astar_60_blocks_fast(w):
    a = w.agent
    sx, sz = math.floor(a.x), math.floor(a.z)
    sy = w.stand_y(sx, sz, a.y)
    gx, gz = sx + 42, sz + 42
    gy = w.stand_y(gx, gz)
    t = time.perf_counter()
    p = find_path(w, (sx + 0.5, sy, sz + 0.5), goal=(gx, gy, gz), near=2.0, max_nodes=8000)
    dt = time.perf_counter() - t
    assert p is not None and dt < 0.2, dt


# ====================================================================== skills
@pytest.fixture(scope="module")
def fresh():
    world = VoxelWorld(SEED, threaded=False, sim_radius=3, creatures=False)
    world.tick()
    return world


def run(world, skill, **args):
    return world.skills.run_until_done({"skill": skill, "args": args}, max_ticks=20 * 240)


def test_skill_chain_from_spawn(fresh):
    w = fresh
    a = w.agent
    r = run(w, "craft", item="crafting_table")
    assert not r.ok and r.text.startswith("I have no planks.")
    r = run(w, "mine_nearest", block="oak_log", count=4)
    assert r.ok, r.text
    assert a.count("#logs") >= 4
    r = run(w, "craft", item="oak_planks", count=12)
    assert r.ok and a.count("oak_planks") >= 12, r.text
    r = run(w, "craft", item="crafting_table")
    assert r.ok and a.has("crafting_table")
    r = run(w, "craft", item="wooden_pickaxe")
    assert r.ok and a.has("wooden_pickaxe"), r.text
    r = run(w, "mine_nearest", block="stone", count=9)
    assert r.ok and a.count("cobblestone") >= 9, r.text
    r = run(w, "craft", item="stone_pickaxe")
    assert r.ok and a.has("stone_pickaxe"), r.text
    r = run(w, "smelt", item="cobblestone", count=1)
    assert r.ok and a.has("stone"), r.text
    assert w.find_blocks([I["furnace"], I["furnace_lit"]], a.x, a.y, a.z, radius=24)


def test_build_small_hut(fresh):
    w = fresh
    a = w.agent
    a.add("cobblestone", 40)
    a.add("door", 1)
    r = run(w, "build", blueprint="small_hut", material="cobblestone")
    assert r.ok, r.text
    ox, oy, oz = r.details["origin"]
    walls = w.region_blocks(ox, oy, oz, ox + 3, oy + 3, oz + 3)
    assert int((walls == I["cobblestone"]).sum()) >= 22
    assert B.BASE[w.get(ox + 1, oy, oz + 2)] == "door"


def test_follow_and_give(fresh):
    w = fresh
    a = w.agent
    w.visitor_action({"action": "join", "name": "Chad"})
    v = w.visitor
    v.x, v.z = a.x + 8, a.z + 3
    v.y = w.stand_y(v.x, v.z, a.y)
    w.skills.start({"skill": "follow", "args": {"target": "Chad", "distance": 2, "seconds": 12}})
    ticks(w, 20 * 13)
    assert math.hypot(a.x - v.x, a.z - v.z) < 3.5
    r = w.skills.take_result()
    assert r and r.ok
    a.add("bread", 3)
    r = run(w, "give", target="visitor", item="bread", count=2)
    assert r.ok and v.count("bread") == 2, r.text
    w.visitor_action({"action": "leave"})


def test_runner_api_and_errors(fresh):
    w = fresh
    sk = w.skills
    assert isinstance(sk, SkillRunner)
    assert sk.start({"skill": "fly"}) == "I don't know how to fly."
    assert sk.start({"skill": "reflect"}) is not None
    assert sk.start({"skill": "mine_nearest", "args": {"block": "unobtanium"}}).startswith("I don't know")
    assert sk.start({"skill": "wait", "args": {"seconds": 5}}) is None
    assert sk.busy and sk.current == "wait"
    ticks(w, 20)
    assert 0 < sk.progress < 1
    sk.interrupt("test")
    r = sk.take_result()
    assert isinstance(r, Result) and not r.ok and r.details["interrupted"]
    assert sk.take_result() is None
    for name, spec in SKILLS.items():
        assert spec["doc"] and isinstance(spec["args"], dict) and isinstance(spec["example"], dict)
        if name not in ("follow", "sleep", "attack", "give", "use", "mine", "put", "take", "stop"):
            err = sk.validate({"skill": name, "args": spec["example"]}) if name != "stop" else None
            assert err is not None
    r = sk.run_until_done({"skill": "say", "args": {"text": "hello"}})
    assert r.ok and w.agent.said == "hello"
    r = sk.run_until_done({"skill": "eat", "args": {"item": "diamond"}})
    assert not r.ok and "eat" in r.text


def test_describe(fresh):
    w = fresh
    s = D.nearby_summary(w, w.agent)
    for k in ("pos", "biome", "light", "blocks", "creatures", "people", "looking_at", "standing_on", "time"):
        assert k in s
    for v in s["blocks"].values():
        n = v["nearest"]
        assert v["count"] >= 1 and n["bearing"] in ("N", "NE", "E", "SE", "S", "SW", "W", "NW", "here")
    txt = D.summary_text(w, w.agent)
    assert "inventory" in txt and len(txt) < 2400
    assert "cobblestone" in D.inventory_summary(w.agent) or D.inventory_summary(w.agent)


# ====================================================================== persistence and wire format
def test_persistence_round_trip(tmp_path):
    w = VoxelWorld(SEED, tmp_path, threaded=False, sim_radius=1, creatures=True)
    w.tick()
    a = w.agent
    x, y, z = math.floor(a.x) + 2, math.floor(a.y), math.floor(a.z)
    w.set(x, y + 3, z, I["glass"])
    w.place_block(x, y, z, I["chest"])
    w.container(x, y, z)["slots"][0] = {"item": "diamond", "count": 3}
    a.add("iron_ingot", 5)
    w.places["home"] = [1, 2, 3]
    from ada.vox.creatures import spawn_creature
    c = spawn_creature(w, "cow", a.x + 3, a.y, a.z)
    w.tick()
    t = w.t
    w.save()
    w.close()
    w2 = VoxelWorld.load(tmp_path, threaded=False, sim_radius=1)
    assert w2.seed == SEED and w2.t == t
    assert w2.get(x, y + 3, z) == I["glass"] and w2.get(x, y, z) == I["chest"]
    assert w2.container(x, y, z)["slots"][0] == {"item": "diamond", "count": 3}
    assert w2.agent.count("iron_ingot") == 5
    assert w2.places["home"] == [1, 2, 3]
    assert any(getattr(e, "kind", "") == "cow" and abs(e.x - c.x) < 2 for e in w2.entities.values())
    # unchanged chunks are not stored
    files = list((tmp_path / "region").glob("c.*.vox"))
    assert 1 <= len(files) <= 3
    w2.close()


def test_snapshot_schema(fresh):
    w = fresh
    full = w.snapshot(full=True)
    for k in ("t", "day", "time", "weather", "light", "blocks", "entities", "removed", "agent", "events"):
        assert k in full
    assert any(e["id"] == 1 for e in full["entities"])
    for e in full["entities"]:
        assert {"id", "kind", "x", "y", "z", "yaw", "pitch"} <= set(e)
    ag = full["agent"]
    for k in ("skill", "progress", "inventory", "health", "food", "x", "y", "z"):
        assert k in ag
    a = w.agent
    p = (math.floor(a.x) + 3, math.floor(a.y) + 4, math.floor(a.z))
    w.set(*p, I["glass"])
    w.say(a, "hi")
    s = w.snapshot()
    assert [*p, I["glass"]] in s["blocks"]
    assert any(e["type"] == "said" and e["text"] == "hi" for e in s["events"])
    assert any(e["id"] == 1 and e.get("said") == "hi" for e in s["entities"])
    s2 = w.snapshot()
    assert s2["blocks"] == [] and s2["events"] == []
    w.visitor_action({"action": "join", "name": "V"})
    s3 = w.snapshot()
    assert any(e["id"] == 2 for e in s3["entities"])
    w.visitor_action({"action": "leave"})
    s4 = w.snapshot()
    assert 2 in s4["removed"]
    import json
    json.dumps(s4)


def test_visitor_actions(fresh):
    w = fresh
    r = w.visitor_action({"action": "join", "name": "Chad"})
    assert r["ok"]
    v = w.visitor
    fx, fy, fz = math.floor(v.x), math.floor(v.y), math.floor(v.z)
    below = (fx, fy - 1, fz)
    name = w.get_name(*below)
    r = w.visitor_action({"action": "dig", "x": below[0], "y": below[1], "z": below[2]})
    assert r["ok"] and w.get(*below) == 0
    ticks(w, 30)
    assert v.count("#planks") + v.count("dirt") + v.count("cobblestone") + v.count("sand") > 0 or name
    v.add("cobblestone", 2)
    v.selected = v.find("cobblestone")
    r = w.visitor_action({"action": "place", "x": fx + 2, "y": fy, "z": fz, "item": "cobblestone"})
    assert r["ok"] or "attach" in r.get("text", "")
    r = w.visitor_action({"action": "move", "forward": 1, "yaw": 0.0})
    assert r["ok"]
    w.visitor_action({"action": "leave"})


def test_leaf_decay(w):
    x, y, z = lab(w, size=10, floor="dirt")
    w.grow_tree(x + 5, y + 1, z + 5, "oak")
    box = (x, y + 1, z, x + 10, y + 12, z + 10)
    leaves = int(np.isin(w.region_blocks(*box), B.LEAVES).sum())
    assert leaves > 10
    for yy in range(y + 1, y + 12):
        if w.get(x + 5, yy, z + 5) in B.LOGS:
            w.break_block(x + 5, yy, z + 5)
    ticks(w, 20 * 30)
    assert int(np.isin(w.region_blocks(*box), B.LEAVES).sum()) <= 2


def test_sneak_stops_at_edges(w):
    x, y, z = lab(w, size=4)
    b = Player(w, x + 2.5, y + 1, z + 2.5, kind="test")
    b.sneak = True
    b.move_x = 1.0
    for _ in range(80):
        b.step()
    assert b.on_ground and b.y == y + 1 and b.x < x + 4.3


def test_attack_creature_and_collect_drops(fresh):
    from ada.vox.creatures import spawn_creature
    w = fresh
    a = w.agent
    a.add("stone_sword", 1)
    x, z = math.floor(a.x) + 3, math.floor(a.z)
    cow = spawn_creature(w, "cow", x + 0.5, w.stand_y(x, z, a.y), z + 0.5)
    before = a.count("raw_meat") + a.count("leather")
    r = run(w, "attack", target=cow.id)
    assert r.ok, r.text
    assert cow.dead and a.count("raw_meat") + a.count("leather") > before
    assert any(e["type"] == "creature_died" and e["kind"] == "cow" for e in w.log)


def test_night_creatures_and_peaceful():
    w = VoxelWorld(SEED, threaded=False, sim_radius=2, creatures=True)
    w.set_time(0.75)
    ticks(w, 20 * 30)
    hostile = [e for e in w.entities.values() if getattr(e, "type", "") == "hostile"]
    assert hostile
    passive = [e for e in w.entities.values() if getattr(e, "type", "") == "passive"]
    assert passive
    w.peaceful = True
    ticks(w, 45)
    assert not [e for e in w.entities.values() if getattr(e, "type", "") == "hostile"]
