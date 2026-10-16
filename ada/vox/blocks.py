"""Block registry (DESIGN-v5 §2.1).

Every block *state* has its own uint16 id (water level 3 is ``water_3``, a lit furnace is
``furnace_lit``), so a renderer only ever needs ``BLOCKS[id]``. States of one block share a
``base`` (family) name and carry a ``state`` number; ``item`` is what the block is as an item
(placing that item gives the family's first state).

Fields of every entry (all present, JSON-safe):
  id, name, base, state, category, color, colors{top,side,bottom}|None, shape, solid,
  transparent, opaque, liquid, gravity, flammable, burn_time, light, hardness (seconds by hand,
  -1 = unbreakable), tool, tool_level, drops [{item, count, chance}], item, soil, plant
  (number of growth stages, 0 = not a plant), replaceable, climbable, conductive, friction,
  height (collision height, 1 = full cube), sound.
"""
from __future__ import annotations

BLOCKS: list[dict] = []
by_name: dict[str, dict] = {}

SHAPES = ("none", "cube", "cross", "liquid", "flat", "torch", "door", "ladder", "wire", "fence",
          "slab", "crop", "fire", "plate", "lever", "button", "bed", "pane")


def _add(name, color, *, base=None, state=0, category="made", colors=None, shape="cube", solid=True,
         transparent=False, liquid=False, gravity=False, flammable=False, burn_time=0.0, light=0,
         hardness=1.0, tool="none", tool_level=0, drops="self", item="self", soil=False, plant=0,
         replaceable=False, climbable=False, conductive=None, friction=0.6, height=1.0, sound="stone"):
    base = base or name
    if item == "self":
        item = base
    if drops == "self":
        drops = [{"item": item, "count": 1, "chance": 1.0}] if item else []
    else:
        drops = [d if isinstance(d, dict) else
                 {"item": d[0], "count": d[1], "chance": (d[2] if len(d) > 2 else 1.0)} for d in drops]
    if conductive is None:
        conductive = bool(solid and not transparent and shape == "cube")
    b = dict(id=len(BLOCKS), name=name, base=base, state=state, category=category, color=color,
             colors=colors, shape=shape, solid=bool(solid), transparent=bool(transparent),
             opaque=bool(solid and not transparent), liquid=bool(liquid), gravity=bool(gravity),
             flammable=bool(flammable), burn_time=float(burn_time), light=int(light),
             hardness=float(hardness), tool=tool, tool_level=int(tool_level), drops=drops, item=item,
             soil=bool(soil), plant=int(plant), replaceable=bool(replaceable), climbable=bool(climbable),
             conductive=bool(conductive), friction=float(friction), height=float(height), sound=sound)
    assert name not in by_name, name
    BLOCKS.append(b)
    by_name[name] = b
    return b


def _plant(name, color, **kw):
    kw.setdefault("category", "life")
    kw.setdefault("shape", "cross")
    kw.setdefault("sound", "grass")
    return _add(name, color, solid=False, transparent=True, hardness=kw.pop("hardness", 0.0),
                replaceable=kw.pop("replaceable", False), flammable=kw.pop("flammable", True),
                burn_time=kw.pop("burn_time", 2.0), **kw)


# ---------------------------------------------------------------------------- terrain
_add("air", "#000000", category="terrain", shape="none", solid=False, transparent=True, hardness=0,
     drops=[], item=None, replaceable=True, sound="none")
_add("stone", "#7d7d7d", category="terrain", hardness=7.5, tool="pickaxe", tool_level=1,
     drops=[("cobblestone", 1)])
_add("deepstone", "#4e4e55", category="terrain", hardness=11, tool="pickaxe", tool_level=1,
     drops=[("cobbled_deepstone", 1)])
_add("dirt", "#86603e", category="terrain", hardness=0.75, tool="shovel", soil=True, sound="gravel")
_add("grass", "#5d9b3a", category="terrain", colors={"top": "#5d9b3a", "side": "#7a7a3e", "bottom": "#86603e"},
     hardness=0.9, tool="shovel", drops=[("dirt", 1)], soil=True, sound="grass")
_add("sand", "#dbcf8e", category="terrain", gravity=True, hardness=0.75, tool="shovel", soil=True, sound="sand")
_add("red_sand", "#be6a2c", category="terrain", gravity=True, hardness=0.75, tool="shovel", soil=True, sound="sand")
_add("gravel", "#857f7c", category="terrain", gravity=True, hardness=0.9, tool="shovel",
     drops=[("gravel", 1, 0.9), ("flint", 1, 0.1)], sound="gravel")
_add("clay", "#a0a6b4", category="terrain", hardness=0.9, tool="shovel", drops=[("clay_ball", 4)], sound="gravel")
_add("snow", "#f4fbfc", category="terrain", gravity=True, hardness=0.3, tool="shovel", sound="snow")
_add("ice", "#90b4f2", category="terrain", transparent=True, hardness=0.75, tool="pickaxe", drops=[],
     friction=0.98, sound="glass")
_add("packed_ice", "#7fa3e6", category="terrain", hardness=0.75, tool="pickaxe", friction=0.98, sound="glass")
_add("mud", "#3c3837", category="terrain", hardness=0.75, tool="shovel", soil=True, friction=0.5, sound="gravel")
_add("bedrock", "#333333", category="terrain", hardness=-1, drops=[])
_add("sandstone", "#d8cb93", category="terrain", hardness=4, tool="pickaxe", tool_level=1)
_add("granite", "#9a6b58", category="terrain", hardness=7.5, tool="pickaxe", tool_level=1)
_add("basalt", "#505056", category="terrain", hardness=7.5, tool="pickaxe", tool_level=1)
_add("obsidian", "#15101f", category="terrain", hardness=250, tool="pickaxe", tool_level=4)
_add("cobblestone", "#727272", category="made", hardness=10, tool="pickaxe", tool_level=1)
_add("cobbled_deepstone", "#46464c", category="made", hardness=12, tool="pickaxe", tool_level=1)
_add("mossy_cobblestone", "#677a5a", category="made", hardness=10, tool="pickaxe", tool_level=1)

# ---------------------------------------------------------------------------- ores
_add("coal_ore", "#3a3a3a", category="ore", colors={"top": "#6e6e6e", "side": "#3a3a3a", "bottom": "#6e6e6e"},
     hardness=15, tool="pickaxe", tool_level=1, drops=[("coal", 1)])
_add("iron_ore", "#c8a888", category="ore", hardness=15, tool="pickaxe", tool_level=2, drops=[("raw_iron", 1)])
_add("copper_ore", "#c46d4a", category="ore", hardness=15, tool="pickaxe", tool_level=2, drops=[("raw_copper", 2)])
_add("gold_ore", "#f5d84a", category="ore", hardness=15, tool="pickaxe", tool_level=3, drops=[("raw_gold", 1)])
_add("diamond_ore", "#5decf5", category="ore", hardness=15, tool="pickaxe", tool_level=3, drops=[("diamond", 1)])
_add("spark_ore", "#d43a2a", category="ore", hardness=15, tool="pickaxe", tool_level=3, light=3,
     drops=[("spark_dust", 4)])
_add("crystal", "#c58bf2", category="ore", transparent=True, hardness=7.5, tool="pickaxe", tool_level=2,
     light=7, drops=[("crystal_shard", 2)], sound="glass")

# ---------------------------------------------------------------------------- life
WOODS = ("oak", "birch", "pine", "jungle", "acacia")
_LOG = {"oak": ("#6b5130", "#b08e5a"), "birch": ("#e3e1d8", "#d3c38c"), "pine": ("#3d2a18", "#7a5c36"),
        "jungle": ("#574119", "#ac8455"), "acacia": ("#6b6560", "#b9643a")}
_LEAF = {"oak": "#4a8a2a", "birch": "#6c9a48", "pine": "#355a35", "jungle": "#3f9a1e", "acacia": "#6f8f22"}
_PLANK = {"oak": "#a8854f", "birch": "#cdb97a", "pine": "#735534", "jungle": "#a47452", "acacia": "#b0603a"}
for w in WOODS:
    _add(f"{w}_log", _LOG[w][0], category="life", colors={"top": _LOG[w][1], "side": _LOG[w][0], "bottom": _LOG[w][1]},
         hardness=3, tool="axe", flammable=True, burn_time=15, sound="wood")
for w in WOODS:
    drops = [(f"{w}_sapling", 1, 0.06), ("stick", 1, 0.03)]
    if w == "oak":
        drops.append(("apple", 1, 0.03))
    _add(f"{w}_leaves", _LEAF[w], category="life", transparent=True, hardness=0.3, tool="shears",
         flammable=True, burn_time=2, drops=drops, sound="grass", conductive=False)
_add("cactus", "#2f7a26", category="life", hardness=0.6, transparent=True, sound="wool", conductive=False)
_plant("tall_grass", "#6aa84f", replaceable=True, drops=[("wheat_seeds", 1, 0.125)], item=None)
_plant("fern", "#4f8a3f", replaceable=True, drops=[("wheat_seeds", 1, 0.125)], item=None)
FLOWERS = {"yellow": "#f2d22e", "red": "#d32f2f", "blue": "#3f6fd8", "purple": "#9b4fd0", "white": "#f5f5f5",
           "orange": "#f08a24"}
for c, col in FLOWERS.items():
    _plant(f"{c}_flower", col)
_plant("red_mushroom", "#d23c32", light=0)
_plant("brown_mushroom", "#9a7255")
_plant("sugarcane", "#9ccf6a", plant=1)
_add("pumpkin", "#e38a1d", category="life", hardness=1.5, tool="axe", sound="wood")
_add("melon", "#6f9d2b", category="life", hardness=1.5, tool="axe", drops=[("melon_slice", 4)], sound="wood")
CROPS = {"wheat": (8, "wheat_seeds", "#c9b04a"), "carrots": (4, "carrot", "#e8862a"),
         "potatoes": (4, "potato", "#c8a85a")}
for crop, (n, seed, col) in CROPS.items():
    for s in range(n):
        ripe = s == n - 1
        if crop == "wheat":
            drops = [("wheat", 1), ("wheat_seeds", 2)] if ripe else [("wheat_seeds", 1)]
        else:
            drops = [(seed, 3)] if ripe else [(seed, 1)]
        _plant(f"{crop}_{s}", col if ripe else "#5fa83a", base=crop, state=s, shape="crop", plant=n,
               drops=drops, item=seed, flammable=False)
for w in WOODS:
    _plant(f"{w}_sapling", _LEAF[w], plant=2)
_add("vines", "#3c7a22", category="life", shape="ladder", solid=False, transparent=True, hardness=0.3,
     tool="shears", climbable=True, replaceable=True, flammable=True, burn_time=2, drops=[], sound="grass")
_add("lily_pad", "#2f8a2f", category="life", shape="flat", solid=False, transparent=True, hardness=0,
     sound="grass", height=0.1)
_add("moss", "#5a7d2e", category="life", hardness=0.3, tool="hoe", flammable=True, burn_time=2, soil=True,
     sound="grass")
_plant("coral", "#e2557a", flammable=False)
_plant("kelp", "#4c8a35", flammable=False, plant=1)
_plant("berry_bush", "#2f5f2a", base="berry_bush", state=0, plant=2, drops=[("berry_bush", 1)])
_plant("berry_bush_ripe", "#a8233a", base="berry_bush", state=1, plant=2, drops=[("berries", 2), ("berry_bush", 1)])

# ---------------------------------------------------------------------------- fluids
_add("water", "#3a66d8", category="fluid", shape="liquid", solid=False, transparent=True, liquid=True,
     hardness=-1, drops=[], item=None, replaceable=True, sound="water", conductive=False)
for lv in range(1, 8):
    _add(f"water_{lv}", "#3a66d8", base="water", state=lv, category="fluid", shape="liquid", solid=False,
         transparent=True, liquid=True, hardness=-1, drops=[], item=None, replaceable=True, sound="water",
         conductive=False)
_add("lava", "#e85a0f", category="fluid", shape="liquid", solid=False, transparent=True, liquid=True,
     hardness=-1, light=15, drops=[], item=None, replaceable=True, sound="lava", conductive=False)
for lv in range(1, 4):
    _add(f"lava_{lv}", "#e85a0f", base="lava", state=lv, category="fluid", shape="liquid", solid=False,
         transparent=True, liquid=True, hardness=-1, light=14, drops=[], item=None, replaceable=True,
         sound="lava", conductive=False)
_add("steam", "#e8eef2", category="fluid", shape="cross", solid=False, transparent=True, hardness=0, drops=[],
     item=None, replaceable=True, sound="none")

# ---------------------------------------------------------------------------- made
for w in WOODS:
    _add(f"{w}_planks", _PLANK[w], hardness=3, tool="axe", flammable=True, burn_time=15, sound="wood")
_add("stone_bricks", "#7a7a7a", hardness=7.5, tool="pickaxe", tool_level=1)
_add("glass", "#cfe8f0", transparent=True, hardness=0.45, drops=[], sound="glass", conductive=False)
_add("bricks", "#97523f", hardness=10, tool="pickaxe", tool_level=1)
_add("clay_tiles", "#b5684a", hardness=6, tool="pickaxe", tool_level=1)
WOOLS = {"white": "#eeeeee", "red": "#a12722", "orange": "#e0711a", "yellow": "#f8c527", "green": "#546d1b",
         "blue": "#353a9e", "purple": "#7a2aac", "black": "#1a1a1e"}
for c, col in WOOLS.items():
    _add(f"{c}_wool", col, hardness=1.2, tool="shears", flammable=True, burn_time=5, sound="wool")
_add("torch", "#ffd23f", shape="torch", solid=False, transparent=True, hardness=0, light=14, sound="wood",
     conductive=False)
_add("lantern", "#d9a03a", shape="torch", solid=False, transparent=True, hardness=3.5, tool="pickaxe",
     light=15, sound="metal", conductive=False)
_add("campfire", "#c4451c", shape="slab", transparent=True, hardness=2, tool="axe", light=15, height=0.4375,
     drops=[("charcoal", 2)], sound="wood", conductive=False)
_add("crafting_table", "#8a5f33", colors={"top": "#b4844a", "side": "#8a5f33", "bottom": "#a8854f"},
     hardness=3.75, tool="axe", flammable=True, burn_time=15, sound="wood")
_add("furnace", "#6b6b6b", colors={"top": "#7d7d7d", "side": "#5a5a5a", "bottom": "#7d7d7d"},
     hardness=17.5, tool="pickaxe", tool_level=1)
_add("furnace_lit", "#8a6b4b", base="furnace", state=1, hardness=17.5, tool="pickaxe", tool_level=1, light=13,
     item="furnace")
_add("chest", "#a2742f", hardness=3.75, tool="axe", flammable=True, burn_time=15, sound="wood", conductive=False)
for st, nm in enumerate(("door_lower", "door_upper", "door_lower_open", "door_upper_open")):
    is_open = "open" in nm
    _add(nm, "#8f6a3a", base="door", state=st, shape="door", solid=not is_open, transparent=True,
         hardness=4.5, tool="axe", item="door", drops=[("door", 1)] if "lower" in nm else [], sound="wood",
         conductive=False)
_add("ladder", "#9c7a44", shape="ladder", solid=False, transparent=True, hardness=0.6, tool="axe", climbable=True,
     flammable=True, burn_time=5, sound="wood")
_add("fence", "#a8854f", shape="fence", transparent=True, hardness=3, tool="axe", flammable=True, burn_time=15,
     sound="wood", conductive=False)
_add("bed", "#c23a3a", shape="bed", transparent=True, hardness=0.3, height=0.5625, sound="wool", conductive=False)
_add("farmland", "#704a2a", base="farmland", state=0, hardness=0.9, tool="shovel", soil=True, height=0.9375,
     drops=[("dirt", 1)], item="dirt", sound="gravel")
_add("farmland_wet", "#4f3420", base="farmland", state=1, hardness=0.9, tool="shovel", soil=True, height=0.9375,
     drops=[("dirt", 1)], item="dirt", sound="gravel")
_add("path", "#9a8148", hardness=0.9, tool="shovel", height=0.9375, drops=[("dirt", 1)], item="dirt",
     sound="gravel")
_add("sign", "#b08e5a", shape="flat", solid=False, transparent=True, hardness=1.5, tool="axe", flammable=True,
     burn_time=5, sound="wood", conductive=False)
_add("lamp", "#5a3a22", base="lamp", state=0, hardness=0.45, sound="glass")
_add("lamp_on", "#f4c26a", base="lamp", state=1, hardness=0.45, light=15, item="lamp", sound="glass")
_add("lever", "#6b5a44", base="lever", state=0, shape="lever", solid=False, transparent=True, hardness=0.75,
     sound="wood", conductive=False)
_add("lever_on", "#9a8a64", base="lever", state=1, shape="lever", solid=False, transparent=True, hardness=0.75,
     item="lever", sound="wood", conductive=False)
_add("button", "#7d7d7d", base="button", state=0, shape="button", solid=False, transparent=True, hardness=0.75,
     sound="stone", conductive=False)
_add("button_on", "#9d9d9d", base="button", state=1, shape="button", solid=False, transparent=True,
     hardness=0.75, item="button", sound="stone", conductive=False)
for lv in range(16):
    r = 0x4a + lv * 12
    _add(f"wire_{lv}", f"#{min(r, 255):02x}1010", base="wire", state=lv, shape="wire", solid=False,
         transparent=True, hardness=0, item="spark_dust", drops=[("spark_dust", 1)], light=0,
         replaceable=False, sound="stone", conductive=False)
_add("pressure_plate", "#8a8a8a", base="pressure_plate", state=0, shape="plate", solid=False, transparent=True,
     hardness=0.75, tool="pickaxe", sound="stone", conductive=False)
_add("pressure_plate_on", "#9a9a9a", base="pressure_plate", state=1, shape="plate", solid=False,
     transparent=True, hardness=0.75, tool="pickaxe", item="pressure_plate", sound="stone", conductive=False)
_add("piston", "#9a8a6a", base="piston", state=0, colors={"top": "#b8a27a", "side": "#7a7a7a", "bottom": "#6a6a6a"},
     hardness=2.5, transparent=False, sound="stone", conductive=False)
_add("piston_extended", "#7a7a7a", base="piston", state=1, hardness=2.5, item="piston", sound="stone",
     conductive=False)
_add("piston_head", "#b8a27a", category="made", hardness=2.5, drops=[], item=None, sound="stone",
     conductive=False)
_add("bell", "#e8c13a", transparent=True, hardness=5, tool="pickaxe", sound="metal", conductive=False)
_add("bookshelf", "#7a5a32", colors={"top": "#a8854f", "side": "#7a5a32", "bottom": "#a8854f"}, hardness=2.25,
     tool="axe", flammable=True, burn_time=15, drops=[("book", 3)], sound="wood")
_add("hay", "#c9a62c", hardness=0.75, tool="hoe", flammable=True, burn_time=5, sound="grass")
_add("scaffolding", "#c9a96a", shape="ladder", solid=True, transparent=True, hardness=0.05, climbable=True,
     flammable=True, burn_time=3, sound="wood", conductive=False)
_add("tnt", "#c8322a", colors={"top": "#d0d0d0", "side": "#c8322a", "bottom": "#d0d0d0"}, hardness=0.05,
     flammable=True, burn_time=1, sound="grass", conductive=False)
_add("fire", "#ff7a1a", category="fluid", shape="fire", solid=False, transparent=True, hardness=0, light=15,
     drops=[], item=None, replaceable=True, sound="fire", conductive=False)

# ---------------------------------------------------------------------------- lookups
ID = {b["name"]: b["id"] for b in BLOCKS}
N = len(BLOCKS)
AIR = 0


def fam(base: str) -> list[int]:
    """All ids of a block family (``fam('water')`` → water + water_1..7)."""
    return [b["id"] for b in BLOCKS if b["base"] == base]


def get(name_or_id) -> dict:
    if isinstance(name_or_id, int):
        return BLOCKS[name_or_id]
    return by_name[name_or_id]


SOLID = [b["solid"] for b in BLOCKS]
OPAQUE = [b["opaque"] for b in BLOCKS]
LIQUID = [b["liquid"] for b in BLOCKS]
LIGHT = [b["light"] for b in BLOCKS]
GRAVITY = [b["gravity"] for b in BLOCKS]
FLAMMABLE = [b["flammable"] for b in BLOCKS]
REPLACEABLE = [b["replaceable"] for b in BLOCKS]
CLIMBABLE = [b["climbable"] for b in BLOCKS]
HEIGHT = [b["height"] for b in BLOCKS]
HARDNESS = [b["hardness"] for b in BLOCKS]
BASE = [b["base"] for b in BLOCKS]
NAME = [b["name"] for b in BLOCKS]
STATE = [b["state"] for b in BLOCKS]
CONDUCTIVE = [b["conductive"] for b in BLOCKS]
WATER_IDS = fam("water")
LAVA_IDS = fam("lava")
WATER, LAVA = ID["water"], ID["lava"]
IS_WATER = [b["base"] == "water" for b in BLOCKS]
IS_LAVA = [b["base"] == "lava" for b in BLOCKS]
WIRE = fam("wire")
IS_WIRE = [b["base"] == "wire" for b in BLOCKS]
LOGS = [ID[f"{w}_log"] for w in WOODS]
LEAVES = [ID[f"{w}_leaves"] for w in WOODS]
# light attenuation for sky light going straight down: 0 clear, 1 diffuse (leaves/water), 15 opaque
SKY_ATTEN = [15 if b["opaque"] else (1 if (b["liquid"] or b["base"].endswith("leaves") or b["name"] in
                                          ("ice", "steam")) else 0) for b in BLOCKS]

import numpy as _np  # noqa: E402

np_solid = _np.array(SOLID, dtype=bool)
np_opaque = _np.array(OPAQUE, dtype=bool)
np_liquid = _np.array(LIQUID, dtype=bool)
np_light = _np.array(LIGHT, dtype=_np.int16)
np_sky_atten = _np.array(SKY_ATTEN, dtype=_np.int16)
np_transparent = ~np_opaque


def public() -> list[dict]:
    """The registry as served by ``GET /api/blocks``."""
    return BLOCKS
