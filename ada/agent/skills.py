"""Skills (DESIGN-v5 §3.2): fast, deterministic abilities executed by the World at 20 Hz.

Each skill is a resumable state machine: a generator that yields once per tick and returns a
``Result``. ``Skill.step(world, body)`` advances it by one tick and returns None while running,
or the Result when finished. Helpers compose with ``yield from`` and fail by raising ``Fail``
with a friendly sentence ("I have no planks.", "I can't reach that.").

    runner = world.skills                       # SkillRunner for world.agent
    err = runner.start({"skill": "mine_nearest", "args": {"block": "oak_log", "count": 4}})
    runner.busy, runner.current, runner.progress, runner.status
    runner.interrupt("why")                     # the running skill ends with ok=False
    res = runner.take_result()                  # the finished Result once, else None

``SKILLS`` is the machine-readable catalog: {name: {"doc", "args": {arg: description}, "example"}}.
"""
from __future__ import annotations

import math
import re
import threading
from collections import deque
from dataclasses import dataclass, field

import numpy as np

from ..vox import blocks as B
from ..vox import items as IT
from ..vox import recipes as R
from ..vox.path import find_path

I = B.ID
REACH = 4.5
AIR = 0


@dataclass
class Result:
    ok: bool
    text: str
    details: dict = field(default_factory=dict)

    def to_dict(self):
        return {"ok": self.ok, "text": self.text, "details": self.details}


class Fail(Exception):
    def __init__(self, text, **details):
        super().__init__(text)
        self.text = text
        self.details = details


# ====================================================================== catalog
_POS = "x,y,z (a [x, y, z] list, absolute block coordinates)"
_ENT = "entity id, a name (the visitor's name) or a creature kind ('cow' = the nearest cow)"
SKILLS: dict[str, dict] = {
    "go_to": {"doc": "Walk (path-finding, swimming, climbing) to a place, an entity, a block kind or a named place.",
              "args": {"target": f"{_POS} | {_ENT} | a named place | a block name (nearest one)",
                       "distance": "float, how close to get (default 1.5)",
                       "dig": "bool, allow digging through blocks (default false)"},
              "example": {"target": [10, 64, -3]}},
    "look_at": {"doc": "Turn to look at a position or an entity.",
                "args": {"target": f"{_POS} | {_ENT}"}, "example": {"target": "visitor"}},
    "mine": {"doc": "Mine the block at a position (walks there, best tool, collects the drops).",
             "args": {"pos": _POS}, "example": {"pos": [4, 63, 7]}},
    "mine_nearest": {"doc": "Find and mine the nearest blocks of a kind, collecting the drops.",
                     "args": {"block": "block name or kind (oak_log, log, stone, iron_ore, coal, sand…)",
                              "count": "int, how many blocks (default 1)"},
                     "example": {"block": "oak_log", "count": 4}},
    "place": {"doc": "Place a block from the inventory at a position (or in front of me).",
              "args": {"block": "item name to place", "pos": f"{_POS} (optional)"},
              "example": {"block": "torch", "pos": [3, 65, 2]}},
    "build": {"doc": "Build a blueprint: a named one (hut, small_hut, wall, tower, farm_plot, bridge) or a list of "
                     "[dx, dy, dz, block] placements, from an origin corner.",
              "args": {"blueprint": "name | list of [dx, dy, dz, block]", "pos": f"origin {_POS} (optional)",
                       "material": "block for the walls (default: what I have most of)"},
              "example": {"blueprint": "small_hut", "material": "oak_planks"}},
    "craft": {"doc": "Craft items from the inventory (making missing intermediates; uses or places a table).",
              "args": {"item": "item name", "count": "int (default 1)"}, "example": {"item": "wooden_pickaxe"}},
    "smelt": {"doc": "Smelt items in a furnace (uses a nearby one, or places/crafts one) and collect the output.",
              "args": {"item": "item to smelt (or the result wanted, e.g. iron_ingot)", "count": "int (default all)",
                       "fuel": "fuel item (default: the best I have)"},
              "example": {"item": "raw_iron", "count": 3}},
    "use": {"doc": "Use a block: open/close doors, flip levers, press buttons, open chests/furnaces, sleep in beds.",
            "args": {"pos": _POS}, "example": {"pos": [0, 64, 5]}},
    "put": {"doc": "Put items into a chest.", "args": {"chest": f"{_POS} | 'nearest'", "item": "item name",
                                                       "count": "int (default all)"},
            "example": {"chest": "nearest", "item": "cobblestone", "count": 32}},
    "take": {"doc": "Take items from a chest.", "args": {"chest": f"{_POS} | 'nearest'",
                                                         "item": "item name (default everything)",
                                                         "count": "int (default all)"},
             "example": {"chest": "nearest", "item": "bread", "count": 2}},
    "eat": {"doc": "Eat food from the inventory (the best one if no item is given).",
            "args": {"item": "food item (optional)"}, "example": {"item": "bread"}},
    "attack": {"doc": "Fight a creature until it dies (best weapon), then collect its drops.",
               "args": {"target": _ENT}, "example": {"target": "cow"}},
    "follow": {"doc": "Follow someone, staying near them, until stopped (or for some seconds).",
               "args": {"target": _ENT, "distance": "float (default 3)", "seconds": "float (0 = until stopped)"},
               "example": {"target": "visitor", "distance": 3}},
    "give": {"doc": "Walk to someone and hand them items.",
             "args": {"target": _ENT, "item": "item name", "count": "int (default 1)"},
             "example": {"target": "visitor", "item": "apple", "count": 2}},
    "plant": {"doc": "Plant seeds/saplings on farmland or soil (finds a spot, tilling if I have a hoe).",
              "args": {"seed": "wheat_seeds | carrot | potato | <wood>_sapling | sugarcane …",
                       "pos": f"{_POS} of the soil block (optional)", "count": "int (default 1)"},
              "example": {"seed": "wheat_seeds", "count": 4}},
    "till": {"doc": "Till grass/dirt into farmland with a hoe (near water if possible).",
             "args": {"pos": f"{_POS} (optional)", "count": "int (default 1)"}, "example": {"count": 4}},
    "harvest": {"doc": "Harvest ripe crops (wheat, carrots, potatoes, berries, sugarcane, pumpkins, melons) and "
                       "replant.", "args": {"pos": f"{_POS} (optional)", "count": "int (default all nearby)"},
                "example": {}},
    "sleep": {"doc": "Sleep in a nearby bed through the night (sets the spawn point).", "args": {},
              "example": {}},
    "say": {"doc": "Say something out loud (a speech bubble).", "args": {"text": "what to say"},
            "example": {"text": "Hello!"}},
    "wait": {"doc": "Wait for some seconds.", "args": {"seconds": "float (default 3)"}, "example": {"seconds": 5}},
    "stop": {"doc": "Stop what I'm doing.", "args": {}, "example": {}},
    "equip": {"doc": "Hold an item in my hand.", "args": {"item": "item name"}, "example": {"item": "stone_sword"}},
    "drop": {"doc": "Drop items on the ground in front of me.", "args": {"item": "item name", "count": "int"},
             "example": {"item": "dirt", "count": 10}},
}

ALIASES = {"walk": "go_to", "goto": "go_to", "go": "go_to", "move_to": "go_to", "dig": "mine", "break": "mine",
           "collect_nearest": "mine_nearest", "gather": "mine_nearest", "chop": "mine_nearest", "make": "craft",
           "cook": "smelt", "open": "use", "store": "put", "deposit": "put", "withdraw": "take", "fight": "attack",
           "kill": "attack", "hand": "give", "sow": "plant", "hoe": "till", "reap": "harvest", "rest": "sleep",
           "speak": "say", "idle": "wait", "hold": "equip", "toss": "drop", "look": "look_at"}

BLUEPRINTS = {}


def _hut(n, h=2):
    """An n×n outer square hut with walls h high, a door on the south side and a flat roof."""
    out = []
    for dy in range(h):
        for dx in range(n):
            for dz in range(n):
                if dx in (0, n - 1) or dz in (0, n - 1):
                    if dz == n - 1 and dx == n // 2:
                        continue
                    out.append([dx, dy, dz, "#material"])
    out.append([n // 2, 0, n - 1, "door"])
    for dx in range(n):
        for dz in range(n):
            out.append([dx, h, dz, "#material"])
    return out


BLUEPRINTS["small_hut"] = _hut(3)
BLUEPRINTS["hut"] = _hut(5)
BLUEPRINTS["wall"] = [[dx, dy, 0, "#material"] for dy in range(2) for dx in range(5)]
BLUEPRINTS["tower"] = [[dx, dy, dz, "#material"] for dy in range(5) for dx in range(3) for dz in range(3)
                       if dx != 1 or dz != 1] + [[1, dy, 1, "ladder"] for dy in range(5)]
BLUEPRINTS["bridge"] = [[0, -1, dz, "#material"] for dz in range(8)]
BLUEPRINTS["farm_plot"] = [[1, -1, 1, "water_bucket"]]


# ====================================================================== argument parsing
def _num(v, name, kind=float, default=None):
    if v is None:
        if default is None:
            raise Fail(f"I need a {name}.")
        return default
    try:
        return kind(v)
    except (TypeError, ValueError):
        raise Fail(f"{v!r} is not a valid {name}.")


_NUMS = re.compile(r"-?\d+(?:\.\d+)?")


def parse_pos(v, args=None):
    if v is None and args is not None and all(k in args for k in ("x", "y", "z")):
        v = [args["x"], args["y"], args["z"]]
    if v is None:
        return None
    if isinstance(v, dict) and all(k in v for k in ("x", "y", "z")):
        v = [v["x"], v["y"], v["z"]]
    if isinstance(v, str):
        nums = _NUMS.findall(v)              # "1,64,-3", "(1, 64, -3)", "oak_log at 1 64 -3"
        if len(nums) >= 3:
            v = nums[-3:]
    if isinstance(v, (list, tuple)) and len(v) == 3:
        try:
            return tuple(int(math.floor(float(c))) for c in v)
        except (TypeError, ValueError):
            pass
    raise Fail(f"I don't understand the position {v!r}; use [x, y, z].")


def _item_name(v, what="item"):
    if not v or not isinstance(v, str):
        raise Fail(f"Which {what}?")
    s = v.strip().lower().replace(" ", "_")
    if s in IT.by_name:
        return s
    for cand in (s.rstrip("s"), s[:-2] if s.endswith("es") else None, s + "_ore", s.replace("wooden", "wood"),
                 s.replace("wood_", "wooden_")):
        if cand and cand in IT.by_name:
            return cand
    short = {"planks": "oak_planks", "plank": "oak_planks", "log": "oak_log", "logs": "oak_log", "wood": "oak_log",
             "table": "crafting_table", "workbench": "crafting_table", "sticks": "stick", "seeds": "wheat_seeds",
             "seed": "wheat_seeds", "iron": "iron_ingot", "gold": "gold_ingot", "copper": "copper_ingot",
             "meat": "raw_meat", "fish": "raw_fish", "cobble": "cobblestone", "torches": "torch",
             "sapling": "oak_sapling", "wool": "white_wool"}
    if s in short:
        return short[s]
    raise Fail(f"I don't know what {v.replace('_', ' ')} is.")


def resolve_blocks(name) -> list[int]:
    """Block ids for a block name or kind ('log' → every log, 'iron' → iron ore)."""
    s = str(name).strip().lower().replace(" ", "_")
    if s in ("log", "logs", "wood", "tree", "trees"):
        return list(B.LOGS)
    if s in ("leaves", "leaf"):
        return list(B.LEAVES)
    if s in ("crops", "crop"):
        return [b["id"] for b in B.BLOCKS if b["base"] in ("wheat", "carrots", "potatoes")]
    if s in ("flower", "flowers"):
        return [I[f"{c}_flower"] for c in B.FLOWERS]
    if s in ("ore", "ores"):
        return [b["id"] for b in B.BLOCKS if b["category"] == "ore"]
    for cand in (s, s.rstrip("s"), s + "_ore", s.replace("_ore", "") + "_ore"):
        if cand in B.by_name:
            base = B.by_name[cand]["base"]
            return B.fam(base)
    # an item that some block drops (cobblestone → stone, coal → coal ore, raw_iron → iron ore)
    out = [b["id"] for b in B.BLOCKS if any(d["item"] == s and d["chance"] >= 0.5 for d in b["drops"])
           and b["hardness"] >= 0]
    if out:
        return out
    raise Fail(f"I don't know a block called {str(name).replace('_', ' ')}.")


# ====================================================================== the skill object
class Skill:
    def __init__(self, runner, name, fn, args):
        self.runner = runner
        self.world = runner.world
        self.body = runner.body
        self.name = name
        self.fn = fn
        self.args = args
        self.progress = 0.0
        self.status = ""
        self.ticks = 0
        self._gen = None

    def step(self, world, body):
        """Advance one tick. Returns None while running, else the Result."""
        self.ticks += 1
        if self._gen is None:
            self._gen = self.fn(self, world, body, **self.args)
        try:
            next(self._gen)
            return None
        except StopIteration as e:
            r = e.value
            if r is None:
                r = Result(True, "Done.")
            elif isinstance(r, str):
                r = Result(True, r)
            return r
        except Fail as f:
            return Result(False, f.text, f.details)

    def close(self):
        if self._gen is not None:
            try:
                self._gen.close()
            except Exception:
                pass


class SkillRunner:
    """Runs one skill at a time for a body, from ``world.tick()``."""

    def __init__(self, world, body):
        self.world = world
        self.body = body
        self.skill: Skill | None = None
        self._result: Result | None = None
        self.last_result: Result | None = None
        self._inbox: deque = deque()
        self._lock = threading.Lock()
        self.history: deque = deque(maxlen=50)
        self.auto_defend = True     # reflex: hit back at a hostile attacker in reach, without stopping the skill
        self._last_swing = -100

    # -- state
    @property
    def busy(self) -> bool:
        return self.skill is not None

    @property
    def current(self) -> str | None:
        return self.skill.name if self.skill else None

    @property
    def progress(self) -> float:
        return self.skill.progress if self.skill else 0.0

    @property
    def status(self) -> str:
        return self.skill.status if self.skill else ""

    # -- control
    def validate(self, spec) -> tuple[str, dict]:
        if isinstance(spec, str):
            spec = {"skill": spec, "args": {}}
        if not isinstance(spec, dict):
            raise Fail("An action must look like {\"skill\": name, \"args\": {...}}.")
        name = str(spec.get("skill") or spec.get("name") or "").strip().lower()
        name = ALIASES.get(name, name)
        args = spec.get("args") or {}
        if not isinstance(args, dict):
            raise Fail("The args must be an object.")
        if name in ("reflect", "practice"):
            raise Fail(f"{name} is handled by the mind, not the body.")
        if name not in _IMPL:
            raise Fail(f"I don't know how to {name.replace('_', ' ') or 'do that'}.")
        parse = _PARSE.get(name)
        args = parse(self.world, self.body, dict(args)) if parse else {}
        return name, args

    def start(self, spec) -> str | None:
        """Start a skill now (interrupting any running one). Returns None, or the friendly error."""
        try:
            name, args = self.validate(spec)
        except Fail as f:
            return f.text
        if self.skill is not None:
            self.interrupt(f"switched to {name}")
        self.body.sleeping = False if name != "sleep" else self.body.sleeping
        self.skill = Skill(self, name, _IMPL[name], args)
        self.world.emit("skill_start", who=self.body.id, skill=name, args=_jsonable(args))
        return None

    def submit(self, spec):
        """Thread-safe: queue a skill to start on the next tick (errors become results)."""
        with self._lock:
            self._inbox.append(spec)

    def interrupt(self, reason="stopped"):
        if self.skill is None:
            return
        sk = self.skill
        sk.close()
        self.skill = None
        self.body.stop()
        self._finish(sk, Result(False, f"Interrupted ({reason}).", {"interrupted": True, "reason": reason}))

    def take_result(self) -> Result | None:
        r, self._result = self._result, None
        return r

    def tick(self):
        if self._inbox:
            with self._lock:
                specs = list(self._inbox)
                self._inbox.clear()
            for spec in specs:
                err = self.start(spec)
                if err:
                    name = (spec.get("skill") if isinstance(spec, dict) else str(spec)) or "?"
                    self._finish(None, Result(False, err, {"skill": name, "rejected": True}))
        if self.auto_defend:
            self._reflex()
        sk = self.skill
        if sk is None:
            return
        r = sk.step(self.world, self.body)
        if r is not None and self.skill is sk:
            self.skill = None
            self.body.stop()
            self._finish(sk, r)

    def _reflex(self):
        b, w = self.body, self.world
        att = b.attacker
        if att is None:
            return
        if getattr(att, "dead", False) or not hasattr(att, "type") or \
                math.dist((att.x, att.y, att.z), (b.x, b.y, b.z)) > 16:
            b.attacker = None
            return
        if not (att.type == "hostile" or getattr(att, "angry", 0) > 0) or self.current == "attack":
            return
        if math.dist((att.x, att.y, att.z), (b.x, b.y, b.z)) < 3.2 and w.t - self._last_swing >= 12:
            from ..vox.creatures import melee
            self._last_swing = w.t
            slot = _best_weapon(b)
            held = b.selected
            if slot is not None and slot < 9:
                b.selected = slot
            b.look_at(att.x, att.y + att.h * 0.6, att.z)
            melee(w, b, att)
            b.selected = held

    def _finish(self, sk, r: Result):
        name = sk.name if sk else r.details.get("skill")
        r.details.setdefault("skill", name)
        if sk:
            r.details.setdefault("seconds", round(sk.ticks / 20, 2))
        self._result = r
        self.last_result = r
        self.history.append({"t": self.world.t, "skill": name, "ok": r.ok, "text": r.text})
        self.world.emit("skill_done", who=self.body.id, skill=name, ok=r.ok, text=r.text)

    def run_until_done(self, spec, max_ticks=20 * 600):
        """Testing helper: start a skill and tick the world until it finishes."""
        err = self.start(spec)
        if err:
            return Result(False, err)
        for _ in range(max_ticks):
            self.world.tick()
            if self.skill is None:
                return self.take_result()
        self.interrupt("timeout")
        return self.take_result()


def _jsonable(args):
    out = {}
    for k, v in args.items():
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = v
        elif isinstance(v, tuple):
            out[k] = list(v)
        elif hasattr(v, "id"):
            out[k] = {"entity": v.id}
        else:
            out[k] = str(v)[:80]
    return out


# ====================================================================== helpers (generators)
def _center(p):
    return (p[0] + 0.5, p[1] + 0.5, p[2] + 0.5)


def _eye_dist(b, p):
    ex, ey, ez = b.eye()
    return math.sqrt((ex - p[0] - 0.5) ** 2 + (ey - p[1] - 0.5) ** 2 + (ez - p[2] - 0.5) ** 2)


def in_reach(b, p, r=REACH):
    return _eye_dist(b, p) <= r


def _feet(b):
    return (math.floor(b.x), math.floor(b.y + 0.05), math.floor(b.z))


def _dig_cost_fn(b):
    def cost(bid):
        bb = B.BLOCKS[bid]
        if bb["hardness"] < 0 or bb["liquid"]:
            return None
        slot = b.best_tool(bid)
        tool = b.inv[slot]["item"] if slot is not None else None
        t = b.break_time(bid, tool)
        return None if t > 30 else t
    return cost


def navigate(sk, w, b, goal=None, near=1.0, reach=None, reach_dist=REACH - 0.3, allow_dig=False, tries=6,
             goal_fn=None, quiet=False):
    """Walk to ``goal`` (feet cell, within ``near``) or to where block ``reach`` is within reach.
    If no walkable way exists, digs through natural blocks (never through built ones)."""
    def arrived():
        if reach is not None:
            return in_reach(b, reach, reach_dist + 0.2) and (goal_fn is None or goal_fn(*_feet(b)))
        dx, dz = b.x - goal[0] - 0.5, b.z - goal[2] - 0.5
        return math.hypot(dx, dz) <= max(near, 0.3) + 0.25 and abs(b.y - goal[1]) <= max(1.6, near)

    stuck = 0
    for attempt in range(tries):
        if arrived():
            b.stop()
            return True
        far_target = None
        tgt = reach if reach is not None else goal
        dist = math.hypot(tgt[0] + 0.5 - b.x, tgt[2] + 0.5 - b.z)
        if dist > 56:
            # long trip: hop towards it in legs across the surface
            k = 44 / dist
            fx = math.floor(b.x + (tgt[0] + 0.5 - b.x) * k)
            fz = math.floor(b.z + (tgt[2] + 0.5 - b.z) * k)
            fy = w.stand_y(fx, fz)
            far_target = (fx, fy, fz)
            path = find_path(w, (b.x, b.y + 0.05, b.z), goal=far_target, near=4.0, max_nodes=5000,
                             margin=12, allow_dig=allow_dig, dig_cost=_dig_cost_fn(b) if allow_dig else None)
        elif reach is not None:
            path = find_path(w, (b.x, b.y + 0.05, b.z), reach=reach, reach_dist=reach_dist, max_nodes=4000,
                             allow_dig=allow_dig, dig_cost=_dig_cost_fn(b) if allow_dig else None, goal_fn=goal_fn)
        else:
            path = find_path(w, (b.x, b.y + 0.05, b.z), goal=goal, near=near, max_nodes=5000, allow_dig=allow_dig,
                             dig_cost=_dig_cost_fn(b) if allow_dig else None, goal_fn=goal_fn)
        if path is None or (not path.steps):
            if arrived():
                return True
            if not allow_dig:
                allow_dig = True      # a competent player digs out of a hole
                continue
            stuck += 1
            if stuck >= 2:
                raise Fail("I can't reach that." if not quiet else "I can't get there.")
            yield
            continue
        ok = yield from walk_path(sk, w, b, path)
        if far_target is not None and ok:
            continue
        if ok and path.partial:
            # partial progress: try again from here, but give up if we didn't get closer
            stuck += 1
            if stuck >= 3:
                raise Fail("I can't reach that.")
    if arrived():
        b.stop()
        return True
    raise Fail("I can't reach that.")


def walk_path(sk, w, b, path):
    steps = path.steps
    n = len(steps)
    for k, st in enumerate(steps):
        # clear the way
        for cell in st.dig:
            if B.SOLID[w.get(*cell)]:
                ok = yield from dig_block(sk, w, b, cell, collect=False)
                if not ok:
                    return False
        # doors
        for cell in ((st.x, st.y, st.z), (st.x, st.y + 1, st.z)):
            bid = w.get(*cell)
            if B.BASE[bid] == "door" and B.SOLID[bid]:
                b.look_at(*_center(cell))
                w.use_block(*cell, by=b)   # opens both halves
                yield
                break
        cx, cz = st.x + 0.5, st.z + 0.5
        last = k == n - 1
        tol = 0.22 if last else 0.38
        limit = 70 + int(abs(st.y - b.y) * 20)
        ticks = 0
        while True:
            dx, dz = cx - b.x, cz - b.z
            d = math.hypot(dx, dz)
            dy = st.y - b.y
            close_h = d < tol
            if st.move in ("swim", "climb"):
                close_v = abs(dy) < 0.45 or (dy < 0 and b.on_ground)
            elif st.move == "drop":
                close_v = dy > -0.5 and (b.on_ground or b.in_water)
            else:
                close_v = abs(dy) < 0.6 or (b.in_water and dy < 0.9)
            if close_h and close_v:
                break
            if not last and d < 0.7 and abs(dy) < 0.6:
                # skip ahead if already near the next waypoint's line
                break
            ticks += 1
            if ticks > limit:
                b.stop()
                return False
            if d > 3.5 or dy > 2.5 or dy < -6:
                b.stop()
                return False
            sp = 1.0 if d > 0.6 else max(0.25, d * 1.6)
            if d > 1e-3:
                b.move_x, b.move_z = dx / d * sp, dz / d * sp
                b.face_dir(dx, dz)
            else:
                b.move_x = b.move_z = 0.0
            b.pitch = 0.0
            b.sprint = n - k > 6 and not b.in_water and b.food > 6
            b.jump = False
            b.descend = False
            if dy > 0.5:
                if b.in_water or b.on_ladder:
                    b.jump = True
                elif b.on_ground and (b.collided_h or d < 1.2):
                    b.jump = True
            elif dy < -0.5 and (b.in_water or b.on_ladder):
                b.descend = True
                if b.on_ladder:
                    b.move_x = b.move_z = 0.0
            if b.head_in_water and dy >= -0.5 and b.air < 200:
                b.jump = True
            if b.in_water and b.collided_h:
                b.jump = True
            if b.in_lava:
                b.jump = True
            b.anim = "walk"
            yield
    b.stop()
    return True


def dig_block(sk, w, b, p, collect=True):
    """Break the block at p (must be within reach): best tool, hardness time, optional pickup."""
    bid = w.get(*p)
    if bid == AIR or B.LIQUID[bid]:
        return True
    bb = B.BLOCKS[bid]
    if bb["hardness"] < 0:
        raise Fail(f"The {bb['name'].replace('_', ' ')} can't be broken.")
    slot = b.best_tool(bid)
    if slot is not None:
        b.select_slot(slot)
        slot = b.find(b.inv[b.selected]["item"]) if b.inv[b.selected] else None
    else:
        # don't waste a tool's durability on something hands do as well
        it = IT.by_name.get(b.held()) if b.held() else None
        if it and it["tool"]:
            for i in range(9):
                if b.inv[i] is None or not IT.by_name[b.inv[i]["item"]]["tool"]:
                    b.selected = i
                    break
    tool = b.held()
    t = b.break_time(bid, tool)
    need = max(1, int(math.ceil(t * 20)))
    done = 0
    while done < need:
        if w.get(*p) != bid:
            break
        if not in_reach(b, p, REACH + 0.6):
            return False
        b.stop()
        b.look_at(*_center(p))
        b.anim = "mine"
        done += 1
        yield
    if w.get(*p) == bid:
        w.break_block(*p, by=b, tool=tool)
        it = IT.by_name.get(tool) if tool else None
        if it and it["tool"]:
            b.wear_tool()
        b.exhaustion += 0.005
    b.anim = "idle"
    if collect:
        yield from collect_items(sk, w, b, _center(p), radius=5.0)
    return True


def collect_items(sk, w, b, around, radius=5.0, max_ticks=120):
    """Pick up loose items near a point (walks over them)."""
    for _ in range(8):
        yield
    t = 0
    tried = set()
    while t < max_ticks:
        items = [e for e in w.items_near(*around, radius) if e.id not in tried and b.space_for(e.item) > 0]
        if not items:
            return True
        e = min(items, key=lambda e: (e.x - b.x) ** 2 + (e.z - b.z) ** 2 + (e.y - b.y) ** 2)
        tried.add(e.id)
        goal = (math.floor(e.x), math.floor(e.y + 0.1), math.floor(e.z))
        if math.hypot(e.x - b.x, e.z - b.z) < 1.2 and -0.6 < e.y - b.y < 2.2:
            yield
            t += 1
            continue
        path = find_path(w, (b.x, b.y + 0.05, b.z), goal=goal, near=0.9, max_nodes=1500, margin=6, partial=False,
                         allow_dig=True, dig_cost=_dig_cost_fn(b))
        if path is None:
            continue
        t0 = w.t
        yield from walk_path(sk, w, b, path)
        for _ in range(3):
            yield
        t += w.t - t0
    return True


def find_spot_near(w, b, avoid=(), radius=3, need_head=False):
    """A free cell near the body (in reach, not where anyone stands) where a block can be put down;
    on the ground if possible, else against any solid face (tunnel walls)."""
    fx, fy, fz = _feet(b)
    best = None
    for r in range(1, radius + 1):
        for dx in range(-r, r + 1):
            for dz in range(-r, r + 1):
                if max(abs(dx), abs(dz)) != r:
                    continue
                for dy in (0, -1, 1, 2):
                    p = (fx + dx, fy + dy, fz + dz)
                    if p in avoid:
                        continue
                    cur = w.get(*p)
                    if not (cur == AIR or (B.REPLACEABLE[cur] and not B.LIQUID[cur])):
                        continue
                    below = w.get(p[0], p[1] - 1, p[2])
                    on_ground = B.SOLID[below] and B.BASE[below] != "door"
                    side = any(B.SOLID[w.get(p[0] + ax, p[1] + ay, p[2] + az)] for ax, ay, az in
                               ((1, 0, 0), (-1, 0, 0), (0, 0, 1), (0, 0, -1), (0, 1, 0)))
                    if not (on_ground or side):
                        continue
                    if need_head and w.get(p[0], p[1] + 1, p[2]) != AIR:
                        continue
                    if any(e.overlaps_cell(*p) for e in w._players()):
                        continue
                    if not in_reach(b, p, REACH - 0.5):
                        continue
                    # don't block my own way: avoid the cells right at my feet level in front if possible
                    d = abs(dx) + abs(dz) + abs(dy) * 0.5 + (0 if on_ground else 3)
                    if best is None or d < best[0]:
                        best = (d, p)
        if best:
            return best[1]
    return None


def place_item(sk, w, b, item, p, walk=True):
    """Place ``item`` at p (walking within reach, never standing in the target)."""
    bid = IT.place_block(item)
    if bid is None:
        raise Fail(f"A {IT.pretty(item)} can't be placed.")
    if not b.has(item):
        raise Fail(f"I have no {IT.pretty(item)}.")
    cur = w.get(*p)
    if cur == bid:
        return True
    if walk and (not in_reach(b, p, REACH - 0.2) or (B.SOLID[bid] and b.overlaps_cell(*p))):
        def not_in(x, y, z):
            return not ((x, z) == (p[0], p[2]) and y in (p[1], p[1] - 1, p[1] + 1))
        yield from navigate(sk, w, b, reach=p, reach_dist=REACH - 0.4, goal_fn=not_in)
    if b.overlaps_cell(*p) and B.SOLID[bid]:
        # step aside
        spot = find_spot_near(w, b, avoid={p}, radius=2, need_head=True)
        if spot:
            yield from navigate(sk, w, b, goal=spot, near=0.3)
    b.look_at(*_center(p))
    for _ in range(3):        # a hand swing per placement (~7 blocks a second)
        b.anim = "place"
        yield
    if item in ("water_bucket", "lava_bucket"):
        if not (w.get(*p) == AIR or B.REPLACEABLE[w.get(*p)]):
            raise Fail("There is something in the way.")
        w.set(*p, bid, by=b)
        b.remove(item, 1)
        b.add("bucket", 1)
        return True
    ok, why = w.place_block(*p, bid, by=b)
    if not ok:
        raise Fail(why)
    b.remove(item, 1)
    b.anim = "place"
    return True


def _pick_material(b, prefer=None):
    if prefer:
        return prefer
    best, n = None, 0
    for name, c in b.items().items():
        it = IT.by_name[name]
        pb = it["place"]
        if not pb:
            continue
        bb = B.by_name[pb]
        if bb["solid"] and bb["opaque"] and not bb["gravity"] and bb["category"] in ("made", "terrain") and \
                name not in ("crafting_table", "furnace", "chest", "tnt", "bookshelf", "lamp", "piston") and c > n:
            best, n = name, c
    return best


# ---------------------------------------------------------------------- crafting plans
def plan_craft(inv: dict, item: str, count: int, depth=0):
    """→ (steps [(recipe, times)], inv_after, needs_table, missing {ingredient: n} | None)."""
    recs = R.recipes_for(item)
    if not recs:
        return None, inv, False, {item: count}
    first_missing = None
    for rec in recs:
        times = max(1, -(-count // rec["count"]))
        inv2 = dict(inv)
        steps = []
        table = rec["needs_table"]
        ok = True
        for ing, n in rec["in"].items():
            need = n * times
            have = _inv_count(inv2, ing)
            if have < need:
                if depth >= 3:
                    ok = False
                    first_missing = first_missing or {ing: need - have}
                    break
                sub_ok = False
                for target in _group_targets(inv2, ing):
                    sub, inv3, t2, miss = plan_craft(inv2, target, need - have, depth + 1)
                    if sub is not None:
                        steps += sub
                        inv2 = inv3
                        table = table or t2
                        sub_ok = True
                        break
                if not sub_ok:
                    ok = False
                    first_missing = first_missing or {ing: need - have}
                    break
            _inv_take(inv2, ing, need)
        if ok:
            inv2[item] = inv2.get(item, 0) + rec["count"] * times
            return steps + [(rec, times)], inv2, table, None
    return None, inv, False, first_missing


def _inv_count(inv, ing):
    if ing.startswith("#"):
        return sum(inv.get(k, 0) for k in IT.GROUPS[ing[1:]])
    return inv.get(ing, 0)


def _inv_take(inv, ing, n):
    keys = sorted(IT.GROUPS[ing[1:]], key=lambda k: -inv.get(k, 0)) if ing.startswith("#") else [ing]
    for k in keys:
        if n <= 0:
            break
        t = min(inv.get(k, 0), n)
        if t:
            inv[k] -= t
            n -= t
            if inv[k] == 0:
                del inv[k]


def _group_targets(inv, ing):
    if not ing.startswith("#"):
        return [ing]
    members = IT.GROUPS[ing[1:]]
    if ing == "#planks":
        return sorted(members, key=lambda m: -inv.get(m.replace("_planks", "_log"), 0))
    return members


def ensure_station(sk, w, b, kind):
    """Make sure a crafting table / furnace is usable: walk to one nearby, or place (or craft) one.
    Returns its position; ``sk.placed`` records stations this skill put down itself."""
    bid_names = ("furnace", "furnace_lit") if kind == "furnace" else (kind,)
    ids = [I[n] for n in bid_names]
    if kind == "crafting_table" and w.table_near(b) is not None:
        sk.table = w.table_near(b)
        return sk.table
    own = b.has(kind)
    radius = 8 if own else 24
    found = w.find_blocks(ids, b.x, b.y, b.z, radius=radius, dy=12, limit=6)
    for p in found:
        if kind == "crafting_table":
            sk.table = p
        if in_reach(b, p, REACH - 0.3):
            return p
        try:
            sk.status = f"walking to the {kind.replace('_', ' ')}"
            yield from navigate(sk, w, b, reach=p, reach_dist=REACH - 0.6, tries=6)
            return p
        except Fail:
            continue
    if not b.has(kind):
        steps, _, needs_table, missing = plan_craft(b.items(), kind, 1)
        if steps is None:
            ing, n = next(iter(missing.items()))
            nm = IT.pretty(ing.lstrip("#"))
            raise Fail(f"There is no {kind.replace('_', ' ')} nearby and I can't make one: I need {n} more {nm}.")
        if needs_table:
            yield from ensure_station(sk, w, b, "crafting_table")
        for rec, times in steps:
            r = _apply_recipe(w, b, rec, times, sk)
            if not r:
                raise Fail(f"I couldn't craft a {kind.replace('_', ' ')}.")
            yield
    spot = find_spot_near(w, b, radius=3)
    if spot is None:
        raise Fail(f"There is no room to put down a {kind.replace('_', ' ')}.")
    sk.status = f"placing a {kind.replace('_', ' ')}"
    yield from place_item(sk, w, b, kind, spot)
    if kind == "crafting_table":
        sk.table = spot
    if not hasattr(sk, "placed"):
        sk.placed = []
    sk.placed.append(spot)
    return spot


def pick_up_placed(sk, w, b, kind="crafting_table"):
    """Take back a station this skill placed (a player keeps their portable table)."""
    for p in list(getattr(sk, "placed", [])):
        if w.get_name(*p) == kind:
            try:
                if not in_reach(b, p):
                    yield from navigate(sk, w, b, reach=p, reach_dist=REACH - 0.6, tries=2)
                yield from dig_block(sk, w, b, p, collect=True)
            except Fail:
                pass
        sk.placed.remove(p)


def _table_ok(w, b, sk=None):
    if w.table_near(b) is not None:
        return True
    p = getattr(sk, "table", None)
    return p is not None and w.get_name(*p) == "crafting_table" and _eye_dist(b, p) <= REACH + 1.5


def _apply_recipe(w, b, rec, times, sk=None):
    if rec["needs_table"] and not _table_ok(w, b, sk):
        return False
    for ing, n in rec["in"].items():
        if b.count(ing) < n * times:
            return False
    for ing, n in rec["in"].items():
        b.remove(ing, n * times)
    made = rec["count"] * times
    left = b.add(rec["out"], made)
    if left:
        w.spawn_item(b.x, b.y + 1, b.z, rec["out"], left)
    w.emit("crafted", who=b.id, name=b.name, item=rec["out"], count=made)
    return True


# ====================================================================== the skills
def sk_wait(sk, w, b, seconds=3.0):
    n = max(1, int(seconds * 20))
    for i in range(n):
        sk.progress = i / n
        sk.status = f"waiting {seconds - i / 20:.0f}s"
        yield
    return Result(True, f"Waited {seconds:g} seconds.")


def sk_stop(sk, w, b):
    b.stop()
    return Result(True, "Stopped.")
    yield  # pragma: no cover


def sk_say(sk, w, b, text=""):
    w.say(b, text)
    return Result(True, f'Said "{text}".', {"text": text})
    yield  # pragma: no cover


def sk_equip(sk, w, b, item):
    if not b.select(item):
        raise Fail(f"I have no {IT.pretty(item)}.")
    yield
    return Result(True, f"Holding {IT.pretty(item)}.")


def sk_drop(sk, w, b, item, count=1):
    if not b.has(item):
        raise Fail(f"I have no {IT.pretty(item)}.")
    n = min(count, b.count(item))
    w.drop_from(b, item, n)
    yield
    return Result(True, f"Dropped {n} {IT.pretty(item)}.")


def _resolve_target(w, b, target):
    """→ ('pos', (x,y,z)) | ('entity', e) | ('block', p)."""
    if isinstance(target, (list, tuple)) and len(target) == 3 or (isinstance(target, dict) and "x" in target):
        return "pos", parse_pos(target)
    if isinstance(target, str) and target.count(",") == 2:
        return "pos", parse_pos(target)
    if isinstance(target, (int, float)):
        e = w.entities.get(int(target))
        if e is None:
            raise Fail("I can't see that.")
        return "entity", e
    s = str(target).strip()
    low = s.lower()
    if low in w.places:
        return "pos", tuple(int(math.floor(v)) for v in w.places[low])
    if s in w.places:
        return "pos", tuple(int(math.floor(v)) for v in w.places[s])
    if low in ("home", "spawn", "cabin"):
        sp = b.spawn_point if low == "home" else w.spawn
        return "pos", (math.floor(sp[0]), math.floor(sp[1]), math.floor(sp[2]))
    e = w.find_entity(s, near=b)
    if e is not None and e is not b:
        return "entity", e
    try:
        ids = resolve_blocks(s)
    except Fail:
        raise Fail(f"I don't know where {s} is.")
    found = w.find_blocks(ids, b.x, b.y, b.z, radius=32, dy=16, limit=1)
    if not found:
        raise Fail(f"I can't see any {s.replace('_', ' ')} nearby.")
    return "block", found[0]


def sk_go_to(sk, w, b, target=None, distance=1.5, dig=False):
    kind, t = _resolve_target(w, b, target)
    sk.status = "walking"
    if kind == "entity":
        start = math.dist((b.x, b.z), (t.x, t.z))
        for _ in range(12):
            d = math.dist((b.x, b.z), (t.x, t.z))
            sk.progress = max(0.0, 1 - d / max(start, 1e-6))
            if d <= distance + 0.5 and abs(t.y - b.y) < 3:
                b.stop()
                return Result(True, f"I'm next to {_ent_name(t)}.", {"pos": [round(b.x, 1), round(b.y, 1),
                                                                             round(b.z, 1)]})
            goal = (math.floor(t.x), math.floor(t.y + 0.05), math.floor(t.z))
            path = find_path(w, (b.x, b.y + 0.05, b.z), goal=goal, near=max(distance, 1.0), max_nodes=5000,
                             allow_dig=dig, dig_cost=_dig_cost_fn(b) if dig else None)
            if path is None:
                raise Fail(f"I can't reach {_ent_name(t)}.")
            # walk a part of the path, then re-plan as the target moves
            part = type(path)(steps=path.steps[:12], partial=True)
            yield from walk_path(sk, w, b, part)
            yield
        raise Fail(f"I can't catch up with {_ent_name(t)}.")
    if kind == "block":
        yield from navigate(sk, w, b, reach=t, reach_dist=3.0, allow_dig=dig)
        return Result(True, f"I'm at the {w.get_name(*t).replace('_', ' ')}.", {"pos": list(t)})
    x, y, z = t
    if B.SOLID[w.get(x, y, z)]:
        y = w.stand_y(x, z, y)
    start = math.dist((b.x, b.y, b.z), (x + 0.5, y, z + 0.5))
    sk.progress = 0.0
    yield from navigate(sk, w, b, goal=(x, y, z), near=max(0.3, distance), allow_dig=dig, tries=12)
    sk.progress = 1.0
    return Result(True, f"Arrived at {x}, {y}, {z}.", {"pos": [x, y, z], "distance": round(start, 1)})


def _ent_name(e):
    return getattr(e, "name", None) or getattr(e, "kind", "it")


def sk_look_at(sk, w, b, target=None):
    kind, t = _resolve_target(w, b, target)
    if kind == "entity":
        b.look_at(t.x, t.y + getattr(t, "eye_h", 0.5), t.z)
        name = _ent_name(t)
    else:
        b.look_at(*_center(t))
        name = w.get_name(*t).replace("_", " ")
    yield
    return Result(True, f"Looking at {name}.")


def sk_mine(sk, w, b, pos):
    bid = w.get(*pos)
    if bid == AIR or B.LIQUID[bid]:
        raise Fail("There is nothing to mine there.")
    name = B.NAME[bid].replace("_", " ")
    if B.HARDNESS[bid] < 0:
        raise Fail(f"The {name} can't be broken.")
    _check_harvest(b, bid)
    if _lava_next_to(w, pos):
        raise Fail(f"There is lava next to that {name}; too dangerous.")
    sk.status = f"walking to the {name}"
    before = b.items()
    if not in_reach(b, pos, REACH - 0.2):
        yield from navigate(sk, w, b, reach=pos, allow_dig=True)
    yield from _clear_line(sk, w, b, pos)
    sk.status = f"mining the {name}"
    yield from dig_block(sk, w, b, pos)
    gained = _diff(before, b.items())
    return Result(True, f"Mined the {name}." + (f" Got {_fmt(gained)}." if gained else ""), {"gained": gained})


def _check_harvest(b, bid):
    bb = B.BLOCKS[bid]
    if bb["tool_level"] > 0:
        slot = b.best_tool(bid)
        tool = b.inv[slot]["item"] if slot is not None else None
        it = IT.by_name.get(tool) if tool else None
        if not it or it["tool"] != bb["tool"] or it["tool_level"] < bb["tool_level"]:
            need = {1: "a wooden", 2: "a stone", 3: "an iron", 4: "a diamond"}[bb["tool_level"]]
            raise Fail(f"I need {need} {bb['tool']} (or better) to mine {bb['name'].replace('_', ' ')}.")


def _lava_next_to(w, p):
    return any(B.IS_LAVA[w.get(p[0] + dx, p[1] + dy, p[2] + dz)] for dx, dy, dz in
               ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, 0, 1), (0, 0, -1)))


def _clear_line(sk, w, b, p):
    """Mine whatever stands between the eye and the target block."""
    for _ in range(4):
        ex, ey, ez = b.eye()
        cx, cy, cz = _center(p)
        hit = w.raycast((ex, ey, ez), (cx - ex, cy - ey, cz - ez), reach=REACH + 1)
        if hit is None or tuple(hit["block"]) == tuple(p):
            return
        q = tuple(hit["block"])
        hb = B.BLOCKS[hit["id"]]
        if hb["hardness"] < 0 or _lava_next_to(w, q) or not hb["solid"] or \
                hb["category"] not in ("terrain", "ore", "life"):
            return
        yield from dig_block(sk, w, b, q, collect=False)


def _diff(before, after):
    out = {}
    for k, v in after.items():
        d = v - before.get(k, 0)
        if d > 0:
            out[k] = d
    return out


def _fmt(d):
    return ", ".join(f"{n} {IT.pretty(k)}" for k, n in d.items())


def _exposed(w, p):
    return any(not B.OPAQUE[w.get(p[0] + dx, p[1] + dy, p[2] + dz)] for dx, dy, dz in
               ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)))


def sk_mine_nearest(sk, w, b, block, count=1):
    ids = resolve_blocks(block)
    name = str(block).replace("_", " ")
    _check_harvest(b, ids[0])
    logs_only = all(i in B.LOGS for i in ids)
    before = b.items()
    mined = 0
    failed = set()
    misses = 0
    while mined < count:
        sk.progress = mined / count
        found = w.find_blocks(ids, b.x, b.y, b.z, radius=28, dy=14, limit=48)
        found = [p for p in found if p not in failed and not _lava_next_to(w, p)]
        if logs_only:
            found = [p for p in found if _is_tree(w, p)]
        if not found:
            break
        fx, fy, fz = _feet(b)
        # prefer exposed blocks and blocks at our level; skip the one we stand on if it is a deep drop
        scored = []
        for p in found[:24]:
            d = math.dist((p[0], p[1], p[2]), (b.x, b.y + 1, b.z))
            if not _exposed(w, p):
                d += 6
            if p[1] > fy + 4:
                d += (p[1] - fy - 4) * 4
            scored.append((d, p))
        scored.sort()
        p = scored[0][1]
        sk.status = f"going to {name} at {p[0]}, {p[1]}, {p[2]}"
        try:
            if not in_reach(b, p, REACH - 0.2):
                yield from navigate(sk, w, b, reach=p, allow_dig=not _exposed(w, p), tries=3)
            yield from _clear_line(sk, w, b, p)
        except Fail:
            failed.add(p)
            misses += 1
            if misses > 6:
                break
            continue
        if not in_reach(b, p, REACH + 0.5):
            failed.add(p)
            continue
        sk.status = f"mining {name} ({mined + 1}/{count})"
        bid = w.get(*p)
        ok = yield from dig_block(sk, w, b, p)
        if ok and w.get(*p) != bid:
            mined += 1
        else:
            failed.add(p)
    sk.status = "collecting"
    yield from collect_items(sk, w, b, (b.x, b.y, b.z), radius=7.0, max_ticks=100)
    gained = _diff(before, b.items())
    sk.progress = 1.0
    if mined == 0:
        raise Fail(f"I couldn't find any {name} I can reach.", gained=gained)
    txt = f"Mined {mined} {name}" + (f" (wanted {count})" if mined < count else "") + "."
    if gained:
        txt += f" Got {_fmt(gained)}."
    return Result(mined >= count, txt, {"mined": mined, "gained": gained})


def _is_tree(w, p):
    """A natural log: part of a trunk with leaves around its top (not a house beam)."""
    x, y, z = p
    top = y
    while w.get(x, top + 1, z) in B.LOGS and top - y < 16:
        top += 1
    a = w.region_blocks(x - 2, top - 1, z - 2, x + 3, top + 3, z + 3)
    return int(np.isin(a, B.LEAVES).sum()) >= 4


def sk_place(sk, w, b, block, pos=None):
    item = block
    if not b.has(item):
        raise Fail(f"I have no {IT.pretty(item)}.")
    if pos is None:
        pos = find_spot_near(w, b, radius=3)
        if pos is None:
            raise Fail("There is no free spot near me.")
    yield from place_item(sk, w, b, item, pos)
    return Result(True, f"Placed {IT.pretty(item)} at {pos[0]}, {pos[1]}, {pos[2]}.", {"pos": list(pos)})


def sk_craft(sk, w, b, item, count=1):
    steps, _, needs_table, missing = plan_craft(b.items(), item, count)
    if steps is None:
        if not R.recipes_for(item):
            raise Fail(f"{IT.pretty(item).capitalize()} can't be crafted." +
                       (" It is smelted in a furnace." if any(r["out"] == item for r in R.SMELTING) else ""))
        # report the top-level ingredient that is missing
        rec = R.recipes_for(item)[0]
        times = max(1, -(-count // rec["count"]))
        top = None
        for ing, n in rec["in"].items():
            if b.count(ing) < n * times:
                top = (ing, n * times - b.count(ing))
                break
        ing, n = top or next(iter(missing.items()))
        nm = IT.pretty(ing.lstrip("#"))
        have = b.count(ing)
        txt = f"I have no {nm}." if have == 0 else f"I need {n} more {nm}."
        root, rn = next(iter(missing.items()))
        if root != ing:
            txt += f" (To make them I'd need {IT.pretty(root.lstrip('#'))}.)"
        raise Fail(txt, missing=missing)
    if needs_table:
        sk.status = "finding a crafting table"
        yield from ensure_station(sk, w, b, "crafting_table")
    before = b.items()
    for i, (rec, times) in enumerate(steps):
        sk.status = f"crafting {IT.pretty(rec['out'])}"
        sk.progress = i / len(steps)
        if rec["needs_table"] and not _table_ok(w, b, sk):
            yield from ensure_station(sk, w, b, "crafting_table")
        if not _apply_recipe(w, b, rec, times, sk):
            raise Fail(f"I couldn't craft {IT.pretty(rec['out'])}.")
        for _ in range(4):
            b.anim = "craft"
            yield
    if item != "crafting_table":
        yield from pick_up_placed(sk, w, b, "crafting_table")
    gained = _diff(before, b.items())
    made = gained.get(item, 0)
    return Result(True, f"Crafted {made} {IT.pretty(item)}.", {"made": made, "item": item})


def _best_fuel(b, exclude=None):
    order = ["coal", "charcoal", "lava_bucket"] + [f"{w}_log" for w in B.WOODS] + \
            [f"{w}_planks" for w in B.WOODS] + ["stick"] + [f"{w}_sapling" for w in B.WOODS]
    for f in order:
        if f != exclude and b.has(f):
            return f
    return None


def sk_smelt(sk, w, b, item, count=None, fuel=None):
    if item not in R.SMELT_BY_INPUT:
        srcs = [r["in"] for r in R.SMELTING if r["out"] == item and b.has(r["in"])]
        if not srcs:
            if any(r["out"] == item for r in R.SMELTING):
                ins = sorted({r["in"] for r in R.SMELTING if r["out"] == item})
                raise Fail(f"I have nothing to smelt into {IT.pretty(item)} (that needs "
                           f"{' or '.join(IT.pretty(i) for i in ins[:3])}).")
            raise Fail(f"{IT.pretty(item).capitalize()} can't be smelted.")
        item = srcs[0]
    have = b.count(item)
    if have == 0:
        raise Fail(f"I have no {IT.pretty(item)}.")
    count = have if count is None else min(int(count), have)
    rec = R.SMELT_BY_INPUT[item]
    fuel = fuel or _best_fuel(b, exclude=item)
    if fuel is None or not b.has(fuel):
        raise Fail("I have no fuel (coal, wood or planks).")
    if fuel not in R.FUELS:
        raise Fail(f"{IT.pretty(fuel).capitalize()} doesn't burn.")
    sk.status = "finding a furnace"
    fp = yield from ensure_station(sk, w, b, "furnace")
    if not in_reach(b, fp):
        yield from navigate(sk, w, b, reach=fp, reach_dist=REACH - 0.6)
    c = w.container(*fp)
    if c is None:
        raise Fail("That furnace doesn't work.")
    # clear a different output or input first
    if c.get("output"):
        w.container_take(fp, b, slot="output")
    if c.get("input") and c["input"]["item"] != item:
        w.container_take(fp, b, slot="input")
    burn_units = R.FUELS[fuel]
    need_fuel = max(0, math.ceil((count * rec["time"] - max(0.0, c.get("burn", 0.0))) / burn_units))
    if c.get("fuel") and c["fuel"]["item"] != fuel:
        w.container_take(fp, b, slot="fuel")
    have_fuel = (c.get("fuel") or {}).get("count", 0)
    put_fuel = max(0, need_fuel - have_fuel)
    if b.count(fuel) < put_fuel:
        count = max(1, int((b.count(fuel) + have_fuel) * burn_units // rec["time"])) if b.count(fuel) else count
        put_fuel = b.count(fuel)
    b.look_at(*_center(fp))
    put = w.container_put(fp, b, item, count, slot="input")
    if put_fuel:
        w.container_put(fp, b, fuel, put_fuel, slot="fuel")
    yield
    target = rec["out"]
    start_out = b.count(target)
    limit = int(count * rec["time"] * 20 * 1.3) + 200
    t = 0
    while t < limit:
        c = w.container(*fp)
        if c is None:
            raise Fail("The furnace is gone.")
        out = (c.get("output") or {}).get("count", 0)
        sk.progress = min(1.0, out / max(1, put))
        sk.status = f"smelting {IT.pretty(item)} ({out}/{put})"
        if out >= put or (not c.get("input") and c.get("progress", 0) == 0):
            break
        if c.get("burn", 0) <= 0 and not c.get("fuel"):
            # out of fuel: add more if we can
            f2 = _best_fuel(b, exclude=item)
            if f2 is None:
                break
            if c.get("fuel") is None or c["fuel"]["item"] == f2:
                w.container_put(fp, b, f2, 1, slot="fuel")
            else:
                break
        if not in_reach(b, fp, REACH + 2):
            yield from navigate(sk, w, b, reach=fp, reach_dist=REACH - 0.6)
        t += 1
        yield
    if not in_reach(b, fp):
        yield from navigate(sk, w, b, reach=fp, reach_dist=REACH - 0.6)
    w.container_take(fp, b, slot="output")
    c = w.container(*fp)
    if c and c.get("input") and c["input"]["item"] == item and (c.get("burn", 0) <= 0 and not c.get("fuel")):
        w.container_take(fp, b, slot="input")
    gained = b.count(target) - start_out
    if gained <= 0:
        raise Fail("Nothing came out of the furnace.")
    return Result(gained >= put, f"Smelted {gained} {IT.pretty(target)}.", {"made": gained, "item": target,
                                                                           "furnace": list(fp)})


def sk_use(sk, w, b, pos):
    if not in_reach(b, pos):
        yield from navigate(sk, w, b, reach=pos, reach_dist=REACH - 0.5)
    b.look_at(*_center(pos))
    yield
    r = w.use_block(*pos, by=b)
    if r.get("kind") == "bed" and r.get("ok"):
        return (yield from _sleep_in_bed(sk, w, b, pos))
    det = {k: v for k, v in r.items() if k not in ("ok", "text", "container")}
    c = r.get("container")
    if c is not None:
        det["contents"] = _contents(c)
    return Result(bool(r.get("ok")), r.get("text", ""), det)


def _contents(c):
    if c.get("kind") == "chest":
        out = {}
        for s in c["slots"]:
            if s:
                out[s["item"]] = out.get(s["item"], 0) + s["count"]
        return out
    return {k: (c.get(k) or None) for k in ("input", "fuel", "output")} | {"burning": c.get("burn", 0) > 0}


def _find_chest(w, b, chest, item=None):
    if chest is None or (isinstance(chest, str) and chest.lower() in ("nearest", "chest", "")):
        found = w.find_blocks([I["chest"]], b.x, b.y, b.z, radius=32, dy=12, limit=8)
        if not found:
            raise Fail("There is no chest nearby.")
        if item:
            for p in found:
                c = w.container(*p)
                if c and any(s and s["item"] == item for s in c["slots"]):
                    return p
        return found[0]
    p = parse_pos(chest)
    if B.BASE[w.get(*p)] != "chest":
        raise Fail("There is no chest there.")
    return p


def sk_put(sk, w, b, chest=None, item=None, count=None):
    p = _find_chest(w, b, chest)
    if not b.has(item):
        raise Fail(f"I have no {IT.pretty(item)}.")
    if not in_reach(b, p):
        yield from navigate(sk, w, b, reach=p, reach_dist=REACH - 0.5)
    b.look_at(*_center(p))
    yield
    n = w.container_put(p, b, item, b.count(item) if count is None else count)
    if n == 0:
        raise Fail("The chest is full.")
    return Result(True, f"Put {n} {IT.pretty(item)} in the chest.", {"count": n, "chest": list(p)})


def sk_take(sk, w, b, chest=None, item=None, count=None):
    p = _find_chest(w, b, chest, item)
    if not in_reach(b, p):
        yield from navigate(sk, w, b, reach=p, reach_dist=REACH - 0.5)
    b.look_at(*_center(p))
    yield
    before = b.items()
    n = w.container_take(p, b, item, 10 ** 6 if count is None else count)
    if n == 0:
        c = w.container(*p)
        if item:
            raise Fail(f"There is no {IT.pretty(item)} in the chest.", contents=_contents(c) if c else {})
        raise Fail("The chest is empty." if c and not any(c["slots"]) else "My inventory is full.")
    got = _diff(before, b.items())
    return Result(True, f"Took {_fmt(got)} from the chest.", {"gained": got, "chest": list(p)})


def sk_eat(sk, w, b, item=None):
    if item is None:
        foods = [(IT.FOOD[n], n) for n in b.items() if n in IT.FOOD]
        if not foods:
            raise Fail("I have nothing to eat.")
        need = 20 - b.food
        foods.sort(key=lambda f: (abs(f[0] - need), -f[0]))
        item = foods[0][1]
    if item not in IT.FOOD:
        raise Fail(f"I can't eat {IT.pretty(item)}.")
    if not b.has(item):
        raise Fail(f"I have no {IT.pretty(item)}.")
    if b.food >= 20:
        raise Fail("I'm not hungry.")
    b.select(item)
    for i in range(32):
        b.anim = "eat"
        b.stop()
        sk.progress = i / 32
        yield
    b.eat(item)
    w.emit("ate", who=b.id, name=b.name, item=item)
    return Result(True, f"Ate {IT.pretty(item)}. Food is {b.food:.0f}/20.", {"food": b.food})


def _best_weapon(b):
    best, dmg = None, 1
    for i, s in enumerate(b.inv):
        if s:
            it = IT.by_name[s["item"]]
            if it["tool"] and it["damage"] > dmg:
                best, dmg = i, it["damage"]
    return best


def sk_attack(sk, w, b, target=None):
    from ..vox.creatures import melee
    kind, e = _resolve_target(w, b, target)
    if kind != "entity" or not hasattr(e, "hurt"):
        raise Fail("I can only attack creatures.")
    if e is b:
        raise Fail("I won't hurt myself.")
    name = _ent_name(e)
    slot = _best_weapon(b)
    if slot is not None:
        b.select_slot(slot)
    t = 0
    last_path = -100
    path_steps = []
    best_d, best_t = 1e9, 0
    while not e.dead and t < 20 * 40:
        t += 1
        d = math.dist((b.x, b.y, b.z), (e.x, e.y, e.z))
        if d < best_d - 0.5:
            best_d, best_t = d, t
        elif t - best_t > 200 and d > 2.9:
            raise Fail(f"I can't reach the {name}.")
        sk.progress = 1 - e.health / e.max_health
        sk.status = f"fighting {name}"
        if d > 40:
            raise Fail(f"The {name} got away.")
        if d <= 2.9:
            b.stop()
            b.look_at(e.x, e.y + e.h * 0.6, e.z)
            if t % 12 == 0:
                melee(w, b, e)
            yield
            continue
        if t - last_path > 15 or not path_steps:
            last_path = t
            goal = (math.floor(e.x), math.floor(e.y + 0.05), math.floor(e.z))
            p = find_path(w, (b.x, b.y + 0.05, b.z), goal=goal, near=1.5, max_nodes=2000)
            path_steps = p.steps[:6] if p else []
            if not path_steps:
                dx, dz = e.x - b.x, e.z - b.z
                dd = math.hypot(dx, dz) or 1
                b.move_x, b.move_z = dx / dd, dz / dd
                b.jump = b.collided_h
                yield
                continue
        st = path_steps[0]
        dx, dz = st.x + 0.5 - b.x, st.z + 0.5 - b.z
        dd = math.hypot(dx, dz)
        if dd < 0.4:
            path_steps.pop(0)
        else:
            b.move_x, b.move_z = dx / dd, dz / dd
            b.face_dir(dx, dz)
            b.jump = st.y > b.y + 0.5 and (b.collided_h or dd < 1.2) or b.in_water
            b.sprint = True
        yield
    b.stop()
    if not e.dead:
        raise Fail(f"I couldn't defeat the {name}.")
    yield from collect_items(sk, w, b, (e.x, e.y, e.z), radius=5)
    return Result(True, f"Defeated the {name}.", {"kind": e.kind})


def sk_follow(sk, w, b, target=None, distance=3.0, seconds=0.0):
    kind, e = _resolve_target(w, b, target)
    if kind != "entity":
        raise Fail("I can only follow someone who moves.")
    name = _ent_name(e)
    t = 0
    limit = int(seconds * 20) if seconds else None
    steps = []
    last = -100
    while limit is None or t < limit:
        t += 1
        if getattr(e, "dead", False) or (e.id not in w.entities):
            return Result(True, f"{name} is gone.")
        if limit:
            sk.progress = t / limit
        d = math.hypot(e.x - b.x, e.z - b.z)
        sk.status = f"following {name} ({d:.0f} m)"
        if d <= distance and abs(e.y - b.y) < 2.5:
            b.stop()
            b.look_at(e.x, e.y + getattr(e, "eye_h", 1.0), e.z)
            steps = []
            yield
            continue
        if d > 64:
            raise Fail(f"I lost {name}.")
        if t - last > 20 or not steps:
            last = t
            goal = (math.floor(e.x), math.floor(e.y + 0.05), math.floor(e.z))
            p = find_path(w, (b.x, b.y + 0.05, b.z), goal=goal, near=max(1.0, distance - 0.5), max_nodes=3000)
            steps = p.steps[:16] if p else []
        if steps:
            st = steps[0]
            dx, dz = st.x + 0.5 - b.x, st.z + 0.5 - b.z
            dd = math.hypot(dx, dz)
            if dd < 0.4 and abs(st.y - b.y) < 0.7:
                steps.pop(0)
            else:
                b.move_x, b.move_z = dx / max(dd, 1e-6), dz / max(dd, 1e-6)
                b.face_dir(dx, dz)
                b.jump = (st.y > b.y + 0.5 and (b.collided_h or dd < 1.2)) or b.in_water
                b.sprint = d > 8
        else:
            b.stop()
        yield
    return Result(True, f"Followed {name} for {seconds:g} s.")


def sk_give(sk, w, b, target=None, item=None, count=1):
    kind, e = _resolve_target(w, b, target)
    if kind != "entity":
        raise Fail("Give it to whom?")
    if not b.has(item):
        raise Fail(f"I have no {IT.pretty(item)}.")
    count = min(count, b.count(item))
    name = _ent_name(e)
    for _ in range(10):
        if math.hypot(e.x - b.x, e.z - b.z) <= 2.5 and abs(e.y - b.y) < 2:
            break
        goal = (math.floor(e.x), math.floor(e.y + 0.05), math.floor(e.z))
        p = find_path(w, (b.x, b.y + 0.05, b.z), goal=goal, near=1.8, max_nodes=4000)
        if p is None:
            raise Fail(f"I can't reach {name}.")
        yield from walk_path(sk, w, b, type(p)(steps=p.steps[:14]))
        yield
    else:
        raise Fail(f"I can't catch up with {name}.")
    b.look_at(e.x, e.y + getattr(e, "eye_h", 1.0), e.z)
    yield
    if getattr(e, "is_player", False):
        n = b.remove(item, count)
        left = e.add(item, n)
        if left:
            w.spawn_item(e.x, e.y + 0.5, e.z, item, left)
        w.emit("gave", who=b.id, name=b.name, to=e.id, item=item, count=n)
    else:
        n = count
        w.drop_from(b, item, count, throw=0.25)
    return Result(True, f"Gave {n} {IT.pretty(item)} to {name}.", {"count": n})


_SEED_ON = {"wheat_seeds": "farmland", "carrot": "farmland", "potato": "farmland", "sugarcane": "sand_or_soil",
            "berry_bush": "soil", "cactus": "sand"}


def _find_soil(w, b, seed, avoid=()):
    if seed in ("wheat_seeds", "carrot", "potato"):
        ids = [I["farmland"], I["farmland_wet"]]
    elif seed == "cactus":
        ids = [I["sand"], I["red_sand"]]
    else:
        ids = [I["grass"], I["dirt"], I["farmland"], I["farmland_wet"]] + ([I["sand"]] if seed == "sugarcane" else [])
    for p in w.find_blocks(ids, b.x, b.y, b.z, radius=16, dy=4, limit=200):
        if p in avoid:
            continue
        if w.get(p[0], p[1] + 1, p[2]) != AIR:
            continue
        if seed == "sugarcane" and not any(B.IS_WATER[w.get(p[0] + dx, p[1], p[2] + dz)]
                                           for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1))):
            continue
        return p
    return None


def _has_hoe(b):
    for s in b.inv:
        if s and IT.by_name[s["item"]]["tool"] == "hoe":
            return s["item"]
    return None


def sk_till(sk, w, b, pos=None, count=1):
    hoe = _has_hoe(b)
    if hoe is None:
        raise Fail("I need a hoe to till.")
    done = []
    for i in range(count):
        sk.progress = i / count
        p = pos
        if p is None:
            p = _till_spot(w, b, set(done))
            if p is None:
                break
        if not in_reach(b, p):
            def off(x, y, z, p=p):
                return (x, z) != (p[0], p[2])
            yield from navigate(sk, w, b, reach=p, reach_dist=REACH - 0.8, goal_fn=off)
        b.select(hoe)
        b.look_at(*_center(p))
        for _ in range(6):
            b.anim = "till"
            yield
        ok, why = w.till(*p, by=b)
        if not ok:
            if pos is not None:
                raise Fail(why)
            done.append(p)
            continue
        b.wear_tool()
        done.append(p)
        if pos is not None:
            break
    if not done:
        raise Fail("There is no grass or dirt to till nearby.")
    return Result(True, f"Tilled {len(done)} block{'s' if len(done) > 1 else ''}.", {"tilled": [list(p) for p in done]})


def _till_spot(w, b, avoid):
    cands = w.find_blocks([I["grass"], I["dirt"]], b.x, b.y, b.z, radius=12, dy=3, limit=300)
    best = None
    water = w.find_blocks(B.WATER_IDS[:1], b.x, b.y, b.z, radius=16, dy=3, limit=40)
    for p in cands:
        if p in avoid or w.get(p[0], p[1] + 1, p[2]) not in (AIR, I["tall_grass"], I["fern"]):
            continue
        if w.get(p[0], p[1] + 2, p[2]) != AIR:
            continue
        near_w = min((max(abs(p[0] - q[0]), abs(p[2] - q[2])) for q in water if abs(q[1] - p[1]) <= 1), default=99)
        near_farm = any(B.BASE[w.get(p[0] + dx, p[1], p[2] + dz)] == "farmland" for dx, dz in
                        ((1, 0), (-1, 0), (0, 1), (0, -1)))
        score = math.dist(p, (b.x, b.y - 1, b.z)) + (0 if near_w <= 4 else 8) - (3 if near_farm else 0)
        if best is None or score < best[0]:
            best = (score, p)
    return best[1] if best else None


def sk_plant(sk, w, b, seed, pos=None, count=1):
    if not b.has(seed):
        raise Fail(f"I have no {IT.pretty(seed)}.")
    bid = IT.place_block(seed)
    if bid is None or B.BLOCKS[bid]["shape"] not in ("cross", "crop") and seed not in ("cactus",):
        raise Fail(f"{IT.pretty(seed).capitalize()} can't be planted.")
    planted = []
    for i in range(count):
        if not b.has(seed):
            break
        sk.progress = i / count
        p = pos
        if p is None:
            p = _find_soil(w, b, seed, set(planted))
            if p is None and seed in ("wheat_seeds", "carrot", "potato") and _has_hoe(b):
                sk.status = "tilling"
                yield from sk_till(sk, w, b, None, 1)
                p = _find_soil(w, b, seed, set(planted))
            if p is None:
                if planted:
                    break
                raise Fail("There is no farmland to plant on." if seed in ("wheat_seeds", "carrot", "potato")
                           else "There is no good soil nearby.")
        target = (p[0], p[1] + 1, p[2])
        sk.status = f"planting {IT.pretty(seed)}"
        try:
            yield from place_item(sk, w, b, seed, target)
        except Fail:
            if pos is not None:
                raise
            planted.append(p)
            continue
        planted.append(p)
        if pos is not None:
            break
    if not planted:
        raise Fail("I couldn't plant anything.")
    return Result(True, f"Planted {len(planted)} {IT.pretty(seed)}.", {"planted": [list(p) for p in planted]})


def _ripe_ids():
    ids = [I["wheat_7"], I["carrots_3"], I["potatoes_3"], I["berry_bush_ripe"], I["pumpkin"], I["melon"]]
    return ids


def sk_harvest(sk, w, b, pos=None, count=None):
    before = b.items()
    done = 0
    limit = count or 64
    tried = set()
    ax, ay, az = b.x, b.y, b.z        # search around where I started, so I don't wander off
    while done < limit:
        sk.progress = done / limit if count else 0.0
        if pos is not None:
            if done:
                break
            p = pos
        else:
            cands = [p for p in w.find_blocks(_ripe_ids(), ax, ay, az, radius=16, dy=4, limit=40)
                     if p not in tried]
            canes = [p for p in w.find_blocks([I["sugarcane"]], ax, ay, az, radius=16, dy=4, limit=40)
                     if w.get(p[0], p[1] - 1, p[2]) == I["sugarcane"] and p not in tried]
            cands = sorted(cands + canes, key=lambda q: math.dist(q, (b.x, b.y, b.z)))
            if not cands:
                break
            p = cands[0]
        tried.add(p)
        bid = w.get(*p)
        base = B.BASE[bid]
        if bid not in _ripe_ids() and not (base == "sugarcane"):
            if pos is not None:
                raise Fail("That isn't ready to harvest.")
            continue
        sk.status = f"harvesting {base.replace('_', ' ')}"
        try:
            if not in_reach(b, p):
                yield from navigate(sk, w, b, reach=p, reach_dist=REACH - 0.8)
        except Fail:
            continue
        if base == "berry_bush":
            w.use_block(*p, by=b)
            yield from collect_items(sk, w, b, _center(p), radius=3)
        else:
            yield from dig_block(sk, w, b, p)
        done += 1
        # replant
        seed = {"wheat": "wheat_seeds", "carrots": "carrot", "potatoes": "potato"}.get(base)
        if seed and b.has(seed) and w.get(*p) == AIR and B.BASE[w.get(p[0], p[1] - 1, p[2])] == "farmland":
            try:
                yield from place_item(sk, w, b, seed, p)
            except Fail:
                pass
    if done == 0:
        raise Fail("There is nothing ripe to harvest nearby.")
    gained = _diff(before, b.items())
    return Result(True, f"Harvested {done} plant{'s' if done > 1 else ''}." + (f" Got {_fmt(gained)}." if gained
                                                                                else ""), {"gained": gained})


def _sleep_in_bed(sk, w, b, pos):
    t = 0
    while b.sleeping and t < 20 * 30:
        sk.status = "sleeping"
        t += 1
        yield
    if w.is_night():
        return Result(False, "I woke up before morning.")
    return Result(True, "Slept until morning.", {"day": w.day()})


def sk_sleep(sk, w, b):
    if not (w.is_night() or w.weather == "thunder"):
        raise Fail("I can only sleep at night.")
    beds = w.find_blocks([I["bed"]], b.x, b.y, b.z, radius=32, dy=10, limit=3)
    if not beds:
        # the bed at home (where I last slept, or the cabin)
        for home in (b.spawn_point, w.spawn):
            near = w.find_blocks([I["bed"]], home[0], home[1], home[2], radius=8, dy=4, limit=1)
            if near and math.dist(near[0], (b.x, b.y, b.z)) < 400:
                beds = near
                sk.status = "going home to bed"
                break
    if not beds:
        if b.has("bed"):
            spot = find_spot_near(w, b, radius=3, need_head=True)
            if spot is None:
                raise Fail("There is no room for my bed.")
            yield from place_item(sk, w, b, "bed", spot)
            beds = [spot]
        else:
            raise Fail("There is no bed nearby.")
    p = beds[0]
    sk.status = "going to bed"
    if not in_reach(b, p):
        yield from navigate(sk, w, b, reach=p, reach_dist=REACH - 1.0)
    r = w.use_block(*p, by=b)
    if not r.get("ok"):
        raise Fail(r.get("text", "I can't sleep."))
    return (yield from _sleep_in_bed(sk, w, b, p))


def _find_site(w, b, plan):
    """The nearest origin (2–10 blocks away) where the blueprint's volume is clear and its ground solid."""
    xs = [p[0] for p in plan]
    ys = [p[1] for p in plan]
    zs = [p[2] for p in plan]
    wx, wz = max(xs) - min(xs) + 1, max(zs) - min(zs) + 1
    h = max(ys) - min(0, min(ys)) + 1
    fx, fy, fz = _feet(b)
    R = 12
    a = w.region_blocks(fx - R - wx, fy - 4, fz - R - wz, fx + R + wx + 1, fy + 4 + h + 1, fz + R + wz + 1)
    solid = B.np_solid[a]
    clear = np.array([b_["replaceable"] and not b_["liquid"] or b_["name"] == "air" for b_ in B.BLOCKS])[a]
    best = None
    for dx in range(-R, R + 1):
        for dz in range(-R, R + 1):
            ox, oz = fx + dx - min(xs), fz + dz - min(zs)
            # the body must not stand inside the footprint
            if ox <= fx <= ox + wx - 1 + min(xs) and oz <= fz <= oz + wz - 1 + min(zs):
                if min(xs) + ox <= fx <= max(xs) + ox and min(zs) + oz <= fz <= max(zs) + oz:
                    continue
            d = math.hypot(dx + wx / 2, dz + wz / 2)
            if d < 2 or (best is not None and d >= best[0]):
                continue
            ix = ox + min(xs) - (fx - R - wx)
            iz = oz + min(zs) - (fz - R - wz)
            for gy in range(fy - 2, fy + 3):
                iy = gy - (fy - 4)
                if iy - 1 < 0 or iy + h > a.shape[0]:
                    continue
                ground = solid[iy - 1, iz:iz + wz, ix:ix + wx]
                vol = clear[iy:iy + h, iz:iz + wz, ix:ix + wx]
                if ground.all() and vol.all():
                    best = (d, (ox, gy, oz))
                    break
    if best is not None:
        return best[1]
    # nothing at my level (e.g. I'm down a mine): look for flat open ground on the surface nearby
    ylo, yhi = max(1, fy - 8), min(250, fy + 48)
    a = w.region_blocks(fx - R - wx, ylo, fz - R - wz, fx + R + wx + 1, yhi + h + 1, fz + R + wz + 1)
    ground_ok = B.np_solid[a] & ~np.isin(a, B.LEAVES)
    clear = np.array([b_["replaceable"] and not b_["liquid"] or b_["name"] == "air" for b_ in B.BLOCKS])[a]
    rev = ground_ok[:yhi - ylo + 1][::-1]
    top = (yhi - ylo) - np.argmax(rev, axis=0)          # index of the highest ground block per column
    has = rev.any(axis=0)
    for d_ in range(2, R + 1):
        for dx in range(-d_, d_ + 1):
            for dz in range(-d_, d_ + 1):
                if max(abs(dx), abs(dz)) != d_:
                    continue
                ix, iz = dx + R + wx - min(xs), dz + R + wz - min(zs)
                if ix < 0 or iz < 0 or ix + wx > a.shape[2] or iz + wz > a.shape[1]:
                    continue
                cols = top[iz:iz + wz, ix:ix + wx]
                if not has[iz:iz + wz, ix:ix + wx].all() or cols.max() != cols.min():
                    continue
                iy = int(cols.max()) + 1
                if iy + h > a.shape[0] or not clear[iy:iy + h, iz:iz + wz, ix:ix + wx].all():
                    continue
                return (fx + dx - min(xs), ylo + iy, fz + dz - min(zs))
    return None


def sk_build(sk, w, b, blueprint, pos=None, material=None):
    if isinstance(blueprint, str):
        if blueprint not in BLUEPRINTS:
            raise Fail(f"I don't know a blueprint called {blueprint}. I know: {', '.join(BLUEPRINTS)}.")
        plan = [list(p) for p in BLUEPRINTS[blueprint]]
    else:
        plan = []
        for p in blueprint:
            if isinstance(p, dict):
                p = [p.get("dx", p.get("x")), p.get("dy", p.get("y")), p.get("dz", p.get("z")), p.get("block")]
            if not (isinstance(p, (list, tuple)) and len(p) == 4):
                raise Fail("A blueprint is a list of [dx, dy, dz, block].")
            plan.append([int(p[0]), int(p[1]), int(p[2]), str(p[3])])
    if not plan:
        raise Fail("The blueprint is empty.")
    mat = _pick_material(b, material)
    items_needed = {}
    for p in plan:
        blk = p[3]
        if blk.startswith("#"):
            if mat is None:
                raise Fail("I have no building blocks.")
            blk = mat
        else:
            blk = _item_name(blk, "block")
        p[3] = blk
        items_needed[blk] = items_needed.get(blk, 0) + 1
    if pos is None:
        pos = _find_site(w, b, plan)
        if pos is None:
            raise Fail("I can't find a clear, flat spot nearby to build that.")
    ox, oy, oz = pos
    cells = []
    for dx, dy, dz, blk in plan:
        cells.append(((ox + dx, oy + dy, oz + dz), blk))
    # skip what is already there
    todo = [(p, blk) for p, blk in cells if w.get(*p) != IT.place_block(blk) and
            not (blk == "door" and B.BASE[w.get(*p)] == "door")]
    need = {}
    for _, blk in todo:
        need[blk] = need.get(blk, 0) + 1
    for blk, n in need.items():
        have = b.count(blk)
        if have < n:
            steps, _, needs_table, _miss = plan_craft(b.items(), blk, n - have)
            if steps is None:
                raise Fail(f"I need {n} {IT.pretty(blk)} for that but have {have}.", needed=need)
            sk.status = f"crafting {IT.pretty(blk)}"
            if needs_table:
                yield from ensure_station(sk, w, b, "crafting_table")
            for rec, times in steps:
                if not _apply_recipe(w, b, rec, times, sk):
                    raise Fail(f"I need {n} {IT.pretty(blk)} for that but have {have}.", needed=need)
                yield
    yield from pick_up_placed(sk, w, b, "crafting_table")
    for blk, n in need.items():
        if b.count(blk) < n:
            raise Fail(f"I need {n} {IT.pretty(blk)} for that but have {b.count(blk)}.", needed=need)
    footprint = {(p[0], p[2]) for p, _ in cells}
    total = len(todo)
    scaffold = []
    placed = 0
    stuck = 0
    # clear anything in the way first (grass, flowers, snow layers…)
    while todo:
        sk.progress = placed / max(1, total)
        # next: the lowest supported placement
        todo.sort(key=lambda c: (c[0][1], 0 if c[1] != "door" else 1, abs(c[0][0] - b.x) + abs(c[0][2] - b.z)))
        pick = None
        for p, blk in todo:
            bid = IT.place_block(blk)
            cur = w.get(*p)
            if cur != AIR and not B.REPLACEABLE[cur]:
                pick = (p, blk, "clear")
                break
            ok, why = w.can_place(*p, bid)
            if ok or "standing" in why:
                pick = (p, blk, "place")
                break
        if pick is None:
            # nothing supported: scaffold under the lowest one
            p, blk = todo[0]
            q = (p[0], p[1] - 1, p[2])
            col = []
            while w.get(*q) == AIR and q[1] > p[1] - 6:
                col.append(q)
                q = (q[0], q[1] - 1, q[2])
            if not col or not b.has(mat or "dirt"):
                raise Fail("Part of the blueprint has nothing to rest on.")
            for c in reversed(col):
                yield from place_item(sk, w, b, mat, c)
                scaffold.append(c)
            continue
        p, blk, act = pick
        sk.status = f"building ({placed}/{total})"
        if act == "clear":
            if not in_reach(b, p):
                yield from navigate(sk, w, b, reach=p, reach_dist=REACH - 0.6)
            yield from dig_block(sk, w, b, p, collect=True)
            continue

        def outside(x, y, z):
            return (x, z) not in footprint
        try:
            if not in_reach(b, p, REACH - 0.3) or b.overlaps_cell(*p) or (blk == "door" and
                                                                         b.overlaps_cell(p[0], p[1] + 1, p[2])):
                yield from navigate(sk, w, b, reach=p, reach_dist=REACH - 0.6, goal_fn=outside)
            yield from place_item(sk, w, b, blk, p, walk=False)
            todo.remove((p, blk))
            placed += 1
            stuck = 0
        except Fail as f:
            stuck += 1
            if stuck > 3:
                raise Fail(f"I got stuck building: {f.text}", placed=placed)
            # try a different order next time
            todo.append(todo.pop(todo.index((p, blk))))
            yield
    for c in reversed(scaffold):
        if not in_reach(b, c):
            try:
                yield from navigate(sk, w, b, reach=c, reach_dist=REACH - 0.6)
            except Fail:
                continue
        yield from dig_block(sk, w, b, c, collect=True)
    sk.progress = 1.0
    return Result(True, f"Built it ({placed} blocks) at {ox}, {oy}, {oz}.", {"origin": [ox, oy, oz],
                                                                            "placed": placed})


# ====================================================================== argument parsers
def _p_go_to(w, b, a):
    t = a.get("target", a.get("pos", a.get("entity", a.get("place"))))
    if t is None and all(k in a for k in ("x", "y", "z")):
        t = [a["x"], a["y"], a["z"]]
    if t is None:
        raise Fail("Go where?")
    if isinstance(t, str) and len(_NUMS.findall(t)) >= 3:
        t = list(parse_pos(t))
    return {"target": t, "distance": _num(a.get("distance"), "distance", float, 1.5), "dig": bool(a.get("dig"))}


def _p_look(w, b, a):
    t = a.get("target", a.get("pos", a.get("entity")))
    if t is None and all(k in a for k in ("x", "y", "z")):
        t = [a["x"], a["y"], a["z"]]
    if t is None:
        raise Fail("Look at what?")
    return {"target": t}


def _p_pos(w, b, a):
    p = parse_pos(a.get("pos", a.get("target")), a)
    if p is None:
        raise Fail("Which position?")
    return {"pos": p}


def _p_mine_nearest(w, b, a):
    blk = a.get("block", a.get("target", a.get("item", a.get("name"))))
    if not blk:
        raise Fail("Mine what?")
    resolve_blocks(blk)
    n = _num(a.get("count"), "count", int, 1)
    if n < 1 or n > 256:
        raise Fail("The count must be between 1 and 256.")
    return {"block": str(blk), "count": n}


def _p_place(w, b, a):
    item = _item_name(a.get("block", a.get("item")), "block")
    if IT.place_block(item) is None:
        raise Fail(f"A {IT.pretty(item)} can't be placed.")
    return {"block": item, "pos": parse_pos(a.get("pos"), a)}


def _p_build(w, b, a):
    bp = a.get("blueprint", a.get("name"))
    if bp is None:
        raise Fail("Build what? Give a blueprint.")
    mat = a.get("material")
    return {"blueprint": bp, "pos": parse_pos(a.get("pos", a.get("origin")), a),
            "material": _item_name(mat, "material") if mat else None}


def _p_craft(w, b, a):
    item = _item_name(a.get("item", a.get("name")))
    n = _num(a.get("count"), "count", int, 1)
    if n < 1 or n > 640:
        raise Fail("The count must be between 1 and 640.")
    return {"item": item, "count": n}


def _p_smelt(w, b, a):
    item = _item_name(a.get("item", a.get("name")))
    c = a.get("count")
    fuel = a.get("fuel")
    return {"item": item, "count": _num(c, "count", int) if c is not None else None,
            "fuel": _item_name(fuel, "fuel") if fuel else None}


def _p_chest(w, b, a):
    item = a.get("item")
    c = a.get("count")
    return {"chest": a.get("chest", a.get("pos")), "item": _item_name(item) if item else None,
            "count": _num(c, "count", int) if c is not None else None}


def _p_put(w, b, a):
    d = _p_chest(w, b, a)
    if d["item"] is None:
        raise Fail("Put what in the chest?")
    return d


def _p_eat(w, b, a):
    item = a.get("item", a.get("food"))
    return {"item": _item_name(item) if item else None}


def _p_target(w, b, a):
    t = a.get("target", a.get("entity", a.get("name", a.get("id"))))
    if t is None:
        raise Fail("Who?")
    return {"target": t}


def _p_follow(w, b, a):
    d = _p_target(w, b, a)
    d["distance"] = _num(a.get("distance"), "distance", float, 3.0)
    d["seconds"] = _num(a.get("seconds"), "seconds", float, 0.0)
    return d


def _p_give(w, b, a):
    d = _p_target(w, b, a)
    d["item"] = _item_name(a.get("item"))
    d["count"] = _num(a.get("count"), "count", int, 1)
    return d


def _p_plant(w, b, a):
    seed = _item_name(a.get("seed", a.get("item", "wheat_seeds")))
    return {"seed": seed, "pos": parse_pos(a.get("pos"), a), "count": _num(a.get("count"), "count", int, 1)}


def _p_till(w, b, a):
    return {"pos": parse_pos(a.get("pos"), a), "count": _num(a.get("count"), "count", int, 1)}


def _p_harvest(w, b, a):
    c = a.get("count")
    return {"pos": parse_pos(a.get("pos"), a), "count": _num(c, "count", int) if c is not None else None}


def _p_say(w, b, a):
    t = a.get("text", a.get("message"))
    if not t:
        raise Fail("Say what?")
    return {"text": str(t)[:300]}


def _p_wait(w, b, a):
    s = _num(a.get("seconds", a.get("time")), "seconds", float, 3.0)
    return {"seconds": max(0.05, min(s, 600.0))}


def _p_equip(w, b, a):
    return {"item": _item_name(a.get("item"))}


def _p_drop(w, b, a):
    return {"item": _item_name(a.get("item")), "count": _num(a.get("count"), "count", int, 1)}


_IMPL = {"go_to": sk_go_to, "look_at": sk_look_at, "mine": sk_mine, "mine_nearest": sk_mine_nearest,
         "place": sk_place, "build": sk_build, "craft": sk_craft, "smelt": sk_smelt, "use": sk_use, "put": sk_put,
         "take": sk_take, "eat": sk_eat, "attack": sk_attack, "follow": sk_follow, "give": sk_give,
         "plant": sk_plant, "till": sk_till, "harvest": sk_harvest, "sleep": sk_sleep, "say": sk_say,
         "wait": sk_wait, "stop": sk_stop, "equip": sk_equip, "drop": sk_drop}
_PARSE = {"go_to": _p_go_to, "look_at": _p_look, "mine": _p_pos, "mine_nearest": _p_mine_nearest, "place": _p_place,
          "build": _p_build, "craft": _p_craft, "smelt": _p_smelt, "use": _p_pos, "put": _p_put, "take": _p_chest,
          "eat": _p_eat, "attack": _p_target, "follow": _p_follow, "give": _p_give, "plant": _p_plant,
          "till": _p_till, "harvest": _p_harvest, "say": _p_say, "wait": _p_wait, "equip": _p_equip,
          "drop": _p_drop}
assert set(_IMPL) == set(SKILLS)
