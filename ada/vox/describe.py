"""Facts for the mind's observation (DESIGN-v5 §3.3): what is around the inhabitant, compactly.

    nearby_summary(world, body, radius=16) -> dict
    inventory_summary(body) -> str
    summary_text(world, body, radius=16) -> str     # a compact ready-to-use rendering of both

Positions are given both absolute (``pos``) and relative to the body's feet (``dx, dy, dz``, x east,
y up, z south) with a compass ``bearing`` (N = −z) and a distance in blocks.
"""
from __future__ import annotations

import math

import numpy as np

from . import blocks as B
from . import items as IT

I = B.ID
_BEARINGS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def bearing(dx, dz) -> str:
    """8-point compass bearing of a horizontal offset (north = −z, east = +x)."""
    if abs(dx) < 0.5 and abs(dz) < 0.5:
        return "here"
    ang = math.degrees(math.atan2(dx, -dz)) % 360
    return _BEARINGS[int((ang + 22.5) // 45) % 8]


def facing(body) -> str:
    vx, _, vz = body.look_vec()
    return bearing(vx * 10, vz * 10)


def _label(b) -> str | None:
    base, name, cat = b["base"], b["name"], b["category"]
    if cat == "ore":
        return name
    if base.endswith("_log"):
        return name
    if base in ("wheat", "carrots", "potatoes"):
        return f"{base} (ripe)" if b["state"] == b["plant"] - 1 else f"{base} (growing)"
    if base == "berry_bush":
        return "berry bush (ripe)" if b["state"] else "berry bush"
    if base == "water":
        return "water"
    if base == "lava":
        return "lava"
    if base == "furnace":
        return "furnace (lit)" if b["state"] else "furnace"
    if base == "door":
        return None if b["state"] in (1, 3) else ("door (open)" if b["state"] == 2 else "door")
    if base == "lamp":
        return "lamp (on)" if b["state"] else "lamp"
    if base == "lever":
        return "lever (on)" if b["state"] else "lever"
    if base == "farmland":
        return "farmland"
    if base == "wire":
        return "spark wire"
    if base.endswith("_sapling") or base.endswith("_flower") or base.endswith("_mushroom"):
        return name
    if name in ("chest", "crafting_table", "bed", "torch", "lantern", "campfire", "fire", "ladder", "sugarcane",
                "pumpkin", "melon", "cactus", "tnt", "bookshelf", "sign", "bell", "hay", "clay", "sand", "gravel",
                "red_sand", "obsidian", "button", "pressure_plate", "piston", "glass", "ice", "snow", "kelp",
                "coral", "lily_pad", "vines", "moss", "mud", "stone", "cobblestone", "scaffolding", "bricks",
                "stone_bricks", "mossy_cobblestone"):
        return name
    return None


LABEL = [_label(b) for b in B.BLOCKS]
# terrain-like labels are only reported when exposed to air (you can see them)
_NEEDS_EXPOSED = {n for n in ("stone", "sand", "gravel", "clay", "red_sand", "snow", "ice", "mud", "obsidian",
                              "cobblestone")}
for b in B.BLOCKS:
    if b["category"] == "ore":
        _NEEDS_EXPOSED.add(b["name"])
_IS_LABELLED = np.array([lbl is not None for lbl in LABEL])
_LABEL_IDS: dict[str, list[int]] = {}
for _i, _l in enumerate(LABEL):
    if _l:
        _LABEL_IDS.setdefault(_l, []).append(_i)


def _rel(body, x, y, z, center=True):
    fx, fy, fz = body.x, body.y, body.z
    cx, cy, cz = (x + 0.5, y, z + 0.5) if center else (x, y, z)
    dx, dy, dz = cx - fx, cy - fy, cz - fz
    return {"pos": [int(math.floor(x)), int(math.floor(y)), int(math.floor(z))], "dx": round(dx, 1),
            "dy": round(dy, 1), "dz": round(dz, 1), "bearing": bearing(dx, dz),
            "dist": round(math.sqrt(dx * dx + dy * dy + dz * dz), 1)}


def nearby_summary(world, body, radius: int = 16, max_kinds: int = 24, max_creatures: int = 12) -> dict:
    w = world
    bx, by, bz = math.floor(body.x), math.floor(body.y + 0.05), math.floor(body.z)
    vr = min(radius, 12)
    x0, y0, z0 = bx - radius, max(0, by - vr), bz - radius
    a = w.region_blocks(x0 - 1, y0 - 1, z0 - 1, bx + radius + 2, min(256, by + vr + 2), bz + radius + 2)
    open_ = ~B.np_opaque[a]
    exp = np.zeros_like(open_)
    exp[1:] |= open_[:-1]
    exp[:-1] |= open_[1:]
    exp[:, 1:] |= open_[:, :-1]
    exp[:, :-1] |= open_[:, 1:]
    exp[:, :, 1:] |= open_[:, :, :-1]
    exp[:, :, :-1] |= open_[:, :, 1:]
    core = a[1:-1, 1:-1, 1:-1]
    exp = exp[1:-1, 1:-1, 1:-1]
    blocks: dict[str, dict] = {}
    present = np.unique(core)
    for bid in present.tolist():
        lbl = LABEL[bid]
        if lbl is None:
            continue
        m = core == bid
        if lbl in _NEEDS_EXPOSED:
            m &= exp
        n = int(m.sum())
        if not n:
            continue
        pts = np.argwhere(m)
        d = (pts[:, 2] + x0 + 0.5 - body.x) ** 2 + (pts[:, 0] + y0 + 0.5 - body.y - 1) ** 2 + \
            (pts[:, 1] + z0 + 0.5 - body.z) ** 2
        k = int(np.argmin(d))
        yy, zz, xx = pts[k].tolist()
        e = blocks.get(lbl)
        if e is None or d[k] < e["_d"]:
            near = _rel(body, xx + x0, yy + y0, zz + z0)
            blocks[lbl] = {"count": n + (e["count"] if e else 0), "nearest": near, "_d": float(d[k])}
        else:
            e["count"] += n
    ordered = sorted(blocks.items(), key=lambda kv: kv[1]["_d"])[:max_kinds]
    blocks = {k: {"count": v["count"], "nearest": v["nearest"]} for k, v in ordered}
    creatures, people, items = [], [], []
    for e in w.entities.values():
        if e is body:
            continue
        dx, dz = e.x - body.x, e.z - body.z
        if dx * dx + dz * dz > (radius * 2) ** 2:
            continue
        r = _rel(body, e.x, e.y, e.z, center=False)
        del r["pos"]
        r["pos"] = [round(e.x, 1), round(e.y, 1), round(e.z, 1)]
        if getattr(e, "is_player", False):
            people.append({"id": e.id, "name": e.name, "kind": e.kind, "held": e.held(), **r,
                           "said": e.said if e.said and w.t < e.said_until else None})
        elif e.kind == "item":
            items.append({"id": e.id, "item": e.item, "count": e.count, **r})
        elif hasattr(e, "type"):
            creatures.append({"id": e.id, "kind": e.kind, **r, "hostile": e.type == "hostile" or e.angry > 0,
                              "health": round(e.health, 1)})
    creatures.sort(key=lambda c: c["dist"])
    items.sort(key=lambda c: c["dist"])
    fx, fz = bx, bz
    below = w.get(fx, math.floor(body.y - 0.05), fz)
    looking = None
    hit = w.raycast(body.eye(), body.look_vec(), reach=8.0, entities=True, skip=body)
    if hit:
        if "block" in hit:
            looking = {"block": LABEL[hit["id"]] or B.BASE[hit["id"]], **_rel(body, *hit["block"]),
                       "in_reach": hit["dist"] <= 4.5}
        else:
            ent = w.entities.get(hit["entity"])
            looking = {"entity": hit.get("name") or hit["kind"], "id": hit["entity"], "dist": hit["dist"],
                       "in_reach": hit["dist"] <= 3.0}
            if ent is not None and hasattr(ent, "item"):
                looking["item"] = ent.item
    light = w.light_at(fx, math.floor(body.y + 1), fz)
    return {
        "pos": [round(body.x, 1), round(body.y, 1), round(body.z, 1)],
        "facing": facing(body),
        "biome": w.biome(body.x, body.z),
        "time": w.clock(), "day": w.day(), "night": w.is_night(), "weather": w.weather,
        "light": light, "dark": light < 7,
        "temperature": w.temperature(body.x, body.y, body.z),
        "standing_on": B.NAME[below], "in_water": body.in_water, "in_lava": body.in_lava,
        "underwater": body.head_in_water, "on_fire": body.fire_ticks > 0,
        "health": round(body.health, 1), "food": round(body.food, 1), "air": body.air,
        "held": body.held(),
        "looking_at": looking,
        "blocks": blocks,
        "creatures": creatures[:max_creatures],
        "people": people,
        "items": items[:8],
    }


def inventory_summary(body) -> str:
    """'holding stone pickaxe; 12 cobblestone, 3 oak log, …' (most plentiful first)."""
    held = body.held()
    counts = body.items()
    if not counts:
        return "inventory empty"
    tools = []
    rest = []
    for name, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        it = IT.by_name.get(name, {})
        if it.get("tool") or it.get("kind") == "tool":
            tools.append(IT.pretty(name) + (f" ×{n}" if n > 1 else ""))
        else:
            rest.append(f"{n} {IT.pretty(name)}")
    parts = []
    if held:
        parts.append(f"holding {IT.pretty(held)}")
    if tools:
        parts.append("tools: " + ", ".join(tools))
    if rest:
        parts.append(", ".join(rest))
    free = sum(1 for s in body.inv if s is None)
    parts.append(f"{free} free slots")
    return "; ".join(parts)


def summary_text(world, body, radius: int = 16) -> str:
    """A compact text rendering of nearby_summary + inventory for a prompt."""
    s = nearby_summary(world, body, radius)
    lines = [f"{s['time']} day {s['day']}, {s['weather']}, {s['biome']}, light {s['light']}"
             f"{' (dark)' if s['dark'] else ''}; at {s['pos'][0]:.0f},{s['pos'][1]:.0f},{s['pos'][2]:.0f} "
             f"facing {s['facing']} on {s['standing_on'].replace('_', ' ')}"
             f"{', in water' if s['in_water'] else ''}{', IN LAVA' if s['in_lava'] else ''}",
             f"health {s['health']:.0f}/20, food {s['food']:.0f}/20" + (f", air {s['air']}" if s['air'] < 300 else ""),
             "inventory: " + inventory_summary(body)]
    la = s["looking_at"]
    if la:
        what = la.get("block") or la.get("entity")
        lines.append(f"looking at {str(what).replace('_', ' ')} {la['dist']}m" +
                     (f" at {la['pos'][0]},{la['pos'][1]},{la['pos'][2]}" if "pos" in la else ""))
    if s["blocks"]:
        bl = []
        for k, v in s["blocks"].items():
            n = v["nearest"]
            bl.append(f"{k.replace('_', ' ')} ×{v['count']} {n['dist']:.0f}m {n['bearing']} "
                      f"({n['pos'][0]},{n['pos'][1]},{n['pos'][2]})")
        lines.append("nearby: " + "; ".join(bl))
    if s["creatures"]:
        lines.append("creatures: " + "; ".join(
            f"{c['kind']}{' (hostile)' if c['hostile'] else ''} {c['dist']:.0f}m {c['bearing']}"
            for c in s["creatures"]))
    if s["people"]:
        lines.append("people: " + "; ".join(f"{p['name']} {p['dist']:.0f}m {p['bearing']}" for p in s["people"]))
    if s["items"]:
        lines.append("loose items: " + "; ".join(f"{i['count']} {i['item'].replace('_', ' ')} {i['dist']:.0f}m"
                                                for i in s["items"]))
    return "\n".join(lines)
