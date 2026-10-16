"""Item registry (DESIGN-v5 §2.2).

Every placeable block family is an item (``place`` names the block state it puts down), plus
tools, materials, food and a writable book. Item names are the stable identifiers used in
inventories, recipes, skills and the wire format.

Fields: name, kind (block|tool|material|food|misc), color, stack, place (block name | None),
tool (pickaxe|axe|shovel|hoe|sword|shears|None), tool_level (1 wood … 4 diamond), speed
(mining multiplier), durability, damage (melee), food (hunger points restored).
"""
from __future__ import annotations

from . import blocks as B

ITEMS: list[dict] = []
by_name: dict[str, dict] = {}


def _add(name, kind, color="#999999", *, stack=64, place=None, tool=None, tool_level=0, speed=1.0,
         durability=0, damage=1, food=0):
    it = dict(name=name, kind=kind, color=color, stack=stack, place=place, tool=tool, tool_level=tool_level,
              speed=speed, durability=durability, damage=damage, food=food)
    assert name not in by_name, name
    ITEMS.append(it)
    by_name[name] = it
    return it


# ---------------------------------------------------------------- blocks as items
_PLACE_OVERRIDE = {"wheat_seeds": "wheat_0", "carrot": "carrots_0", "potato": "potatoes_0", "spark_dust": "wire_0",
                   "door": "door_lower", "berry_bush": "berry_bush"}
_FOOD_BLOCK = {"carrot": 3, "potato": 1, "red_mushroom": 0, "brown_mushroom": 0}
_seen = set()
for b in B.BLOCKS:
    it = b["item"]
    if not it or it in _seen:
        continue
    _seen.add(it)
    place = _PLACE_OVERRIDE.get(it, it if it in B.by_name else None)
    kind = "food" if _FOOD_BLOCK.get(it) else "block"
    if it in ("wheat_seeds", "spark_dust"):
        kind = "material"
    _add(it, kind, b["color"], place=place, food=_FOOD_BLOCK.get(it, 0))

# ---------------------------------------------------------------- tools
TIERS = {"wooden": (1, 2.0, 60, "#a8854f"), "stone": (2, 4.0, 132, "#7d7d7d"), "iron": (3, 6.0, 251, "#d8d8d8"),
         "diamond": (4, 8.0, 1562, "#5decf5")}
_DMG = {"pickaxe": 2, "axe": 4, "shovel": 2, "hoe": 1, "sword": 4}
for tier, (lvl, spd, dur, col) in TIERS.items():
    for kind in ("pickaxe", "axe", "shovel", "hoe", "sword"):
        _add(f"{tier}_{kind}", "tool", col, stack=1, tool=kind, tool_level=lvl, speed=spd, durability=dur,
             damage=_DMG[kind] + lvl)
_add("shears", "tool", "#c8c8c8", stack=1, tool="shears", tool_level=3, speed=5.0, durability=238)
_add("bucket", "tool", "#c0c0c0", stack=16)
_add("water_bucket", "tool", "#3a66d8", stack=1, place="water")
_add("lava_bucket", "tool", "#e85a0f", stack=1, place="lava")
_add("flint_and_steel", "tool", "#5a5a5a", stack=1, durability=64)

# ---------------------------------------------------------------- materials
for name, col in [("stick", "#8a6a3a"), ("coal", "#2a2a2a"), ("charcoal", "#3a2a1a"), ("iron_ingot", "#d8d8d8"),
                  ("copper_ingot", "#c8723a"), ("gold_ingot", "#f5d84a"), ("raw_iron", "#c8a888"),
                  ("raw_copper", "#c46d4a"), ("raw_gold", "#e8c040"), ("diamond", "#5decf5"), ("string", "#eeeeee"),
                  ("leather", "#8a4a2a"), ("feather", "#f0f0f0"), ("bone", "#e8e4d0"), ("wheat", "#d8c050"),
                  ("flour", "#f4f0e0"), ("flint", "#3a3a3a"), ("clay_ball", "#a0a6b4"), ("brick", "#a2533c"),
                  ("paper", "#f4f4f4"), ("sugar", "#fafafa"), ("bowl", "#8a6a3a"), ("crystal_shard", "#c58bf2"),
                  ("slimeball", "#7ac86a"), ("dye", "#888888")]:
    _add(name, "material", col)
_add("book", "misc", "#7a4a2a", stack=1)

# ---------------------------------------------------------------- food
for name, val, col in [("apple", 4, "#d23a2a"), ("bread", 5, "#c8963a"), ("berries", 2, "#a8233a"),
                       ("baked_potato", 5, "#c8963a"), ("raw_meat", 3, "#d86a6a"), ("cooked_meat", 8, "#8a4a2a"),
                       ("raw_fish", 2, "#7aa0c8"), ("cooked_fish", 5, "#c8a07a"), ("pumpkin_pie", 8, "#d88a3a"),
                       ("mushroom_stew", 6, "#a87a5a"), ("melon_slice", 2, "#e84a4a")]:
    _add(name, "food", col, food=val, stack=1 if name == "mushroom_stew" else 64)

# ---------------------------------------------------------------- groups (recipe wildcards: "#planks")
GROUPS: dict[str, list[str]] = {
    "planks": [f"{w}_planks" for w in B.WOODS],
    "logs": [f"{w}_log" for w in B.WOODS],
    "saplings": [f"{w}_sapling" for w in B.WOODS],
    "wool": [f"{c}_wool" for c in B.WOOLS],
    "coal": ["coal", "charcoal"],
    "stone_material": ["cobblestone", "cobbled_deepstone"],
    "flowers": [f"{c}_flower" for c in B.FLOWERS],
    "sand": ["sand", "red_sand"],
}
FOOD = {it["name"]: it["food"] for it in ITEMS if it["food"] > 0}


def get(name: str) -> dict | None:
    return by_name.get(name)


def place_block(item: str) -> int | None:
    """The block id an item puts down, or None."""
    it = by_name.get(item)
    if not it or not it["place"]:
        return None
    return B.ID[it["place"]]


def matches(item: str, ingredient: str) -> bool:
    if ingredient.startswith("#"):
        return item in GROUPS[ingredient[1:]]
    return item == ingredient


def pretty(name: str) -> str:
    return name.replace("_", " ")


def public() -> list[dict]:
    return ITEMS
