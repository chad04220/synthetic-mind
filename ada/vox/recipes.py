"""Recipes (DESIGN-v5 §2.3): shapeless crafting, smelting and fuels.

CRAFTING: [{"out", "count", "in": {ingredient: n}, "needs_table"}]; an ingredient is an item name
or "#group" (any item of ``items.GROUPS[group]``). A 2×2 grid holds at most 4 items, so a recipe
with more than 4 items (or marked ``needs_table``) needs a crafting table within 4 blocks.
SMELTING: [{"in", "out", "time"}] (seconds per item).  FUELS: {item: seconds of burning}.
"""
from __future__ import annotations

from . import blocks as B
from . import items as I

CRAFTING: list[dict] = []


def _c(out, ins, count=1, table=None):
    n = sum(ins.values())
    if table is None:
        table = n > 4
    CRAFTING.append({"out": out, "count": count, "in": dict(ins), "needs_table": bool(table)})


# wood
for w in B.WOODS:
    _c(f"{w}_planks", {f"{w}_log": 1}, 4)
_c("stick", {"#planks": 2}, 4)
_c("crafting_table", {"#planks": 4}, table=False)
_c("chest", {"#planks": 8})
_c("furnace", {"#stone_material": 8})
_c("torch", {"#coal": 1, "stick": 1}, 4)
_c("torch", {"crystal_shard": 1, "stick": 1}, 4)
_c("lantern", {"torch": 1, "iron_ingot": 1}, table=True)
_c("campfire", {"stick": 3, "#coal": 1, "#logs": 3})
_c("ladder", {"stick": 7}, 3)
_c("fence", {"stick": 4, "#planks": 2}, 3)
_c("door", {"#planks": 6}, 3)
_c("bed", {"#wool": 3, "#planks": 3})
_c("sign", {"#planks": 6, "stick": 1}, 3)
_c("bowl", {"#planks": 3}, 4, table=True)
_c("bookshelf", {"#planks": 6, "book": 3})
_c("scaffolding", {"stick": 6, "string": 1}, 6)
_c("chest", {"#logs": 2}, 1, table=True)
# tools
_MAT = {"wooden": "#planks", "stone": "#stone_material", "iron": "iron_ingot", "diamond": "diamond"}
_SHAPE = {"pickaxe": (3, 2), "axe": (3, 2), "shovel": (1, 2), "hoe": (2, 2), "sword": (2, 1)}
for tier, mat in _MAT.items():
    for kind, (m, s) in _SHAPE.items():
        _c(f"{tier}_{kind}", {mat: m, "stick": s}, table=True)
_c("shears", {"iron_ingot": 2}, table=False)
_c("bucket", {"iron_ingot": 3}, table=True)
_c("flint_and_steel", {"iron_ingot": 1, "flint": 1})
# stone and earth
_c("stone_bricks", {"stone": 4}, 4)
_c("bricks", {"brick": 4})
_c("clay", {"clay_ball": 4})
_c("sandstone", {"#sand": 4})
_c("packed_ice", {"ice": 9})
_c("mossy_cobblestone", {"cobblestone": 1, "vines": 1})
_c("mossy_cobblestone", {"cobblestone": 1, "moss": 1})
_c("snow", {"ice": 1}, 1)
_c("crystal", {"crystal_shard": 4})
_c("gravel", {"flint": 4})
# wool and dye
_c("white_wool", {"string": 4})
_c("string", {"white_wool": 1}, 4)
_c("dye", {"#flowers": 1}, 2)
for colour, src in [("red", "red_flower"), ("orange", "orange_flower"), ("yellow", "yellow_flower"),
                    ("blue", "blue_flower"), ("purple", "purple_flower"), ("black", "coal"), ("green", "cactus")]:
    _c(f"{colour}_wool", {"white_wool": 1, src: 1})
    _c(f"{colour}_wool", {"#wool": 1, src: 1, "dye": 1})
# signals
_c("lamp", {"glass": 4, "spark_dust": 4, "torch": 1})
_c("lever", {"stick": 1, "cobblestone": 1})
_c("button", {"stone": 1})
_c("button", {"#planks": 1})
_c("pressure_plate", {"stone": 2})
_c("pressure_plate", {"#planks": 2})
_c("piston", {"#planks": 3, "cobblestone": 4, "iron_ingot": 1, "spark_dust": 1})
_c("bell", {"copper_ingot": 4, "stick": 1})
_c("tnt", {"#sand": 4, "spark_dust": 2, "coal": 3})
_c("spark_dust", {"crystal_shard": 1, "coal": 1}, 2)
# paper, books
_c("paper", {"sugarcane": 3}, 3, table=True)
_c("book", {"paper": 3, "leather": 1})
_c("sugar", {"sugarcane": 1})
# farming and food
_c("hay", {"wheat": 9})
_c("wheat", {"hay": 1}, 9)
_c("flour", {"wheat": 1})
_c("bread", {"wheat": 3}, table=True)
_c("pumpkin_pie", {"pumpkin": 1, "sugar": 1, "flour": 1})
_c("mushroom_stew", {"bowl": 1, "red_mushroom": 1, "brown_mushroom": 1})
_c("melon", {"melon_slice": 9})
_c("wheat_seeds", {"wheat": 1}, 1)
_c("wheat_seeds", {"pumpkin": 1}, 4)
for w in B.WOODS:
    _c(f"{w}_sapling", {f"{w}_leaves": 4})
_c("leather", {"raw_meat": 4, "string": 1})

SMELTING: list[dict] = []


def _s(inp, out, time=8.0):
    SMELTING.append({"in": inp, "out": out, "time": float(time)})


for raw, ingot in [("raw_iron", "iron_ingot"), ("raw_copper", "copper_ingot"), ("raw_gold", "gold_ingot"),
                   ("iron_ore", "iron_ingot"), ("copper_ore", "copper_ingot"), ("gold_ore", "gold_ingot")]:
    _s(raw, ingot)
_s("sand", "glass")
_s("red_sand", "glass")
_s("clay_ball", "brick")
_s("clay", "clay_tiles")
_s("cobblestone", "stone")
_s("cobbled_deepstone", "deepstone")
_s("raw_meat", "cooked_meat")
_s("raw_fish", "cooked_fish")
_s("potato", "baked_potato")
_s("flour", "bread")
_s("cactus", "dye")
_s("coal_ore", "coal")
_s("diamond_ore", "diamond")
_s("spark_ore", "spark_dust")
for w in B.WOODS:
    _s(f"{w}_log", "charcoal")

FUELS: dict[str, float] = {"coal": 80.0, "charcoal": 80.0, "lava_bucket": 1000.0, "hay": 20.0, "stick": 5.0,
                           "bowl": 5.0, "crafting_table": 15.0, "chest": 15.0, "ladder": 15.0, "fence": 15.0,
                           "bookshelf": 15.0, "scaffolding": 2.5}
for w in B.WOODS:
    FUELS[f"{w}_log"] = 15.0
    FUELS[f"{w}_planks"] = 15.0
    FUELS[f"{w}_sapling"] = 5.0
for t in ("pickaxe", "axe", "shovel", "hoe", "sword"):
    FUELS[f"wooden_{t}"] = 10.0
for c in B.WOOLS:
    FUELS[f"{c}_wool"] = 5.0

SMELT_BY_INPUT = {r["in"]: r for r in SMELTING}


def recipes_for(item: str) -> list[dict]:
    return [r for r in CRAFTING if r["out"] == item]


def all_ingredients() -> set[str]:
    out = set()
    for r in CRAFTING:
        out.update(r["in"])
        out.add(r["out"])
    for r in SMELTING:
        out.update((r["in"], r["out"]))
    out.update(FUELS)
    return out


def public() -> dict:
    return {"crafting": CRAFTING, "smelting": SMELTING, "fuels": FUELS, "groups": I.GROUPS}
