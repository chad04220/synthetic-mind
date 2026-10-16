"""Creatures (DESIGN-v5 §2.3): passive, neutral and night creatures with simple, cheap AI.

Each creature is a Body with its own size and speed. AI decisions run every few ticks (staggered
by id); physics is skipped while a creature stands still. Hostiles avoid (and burn in) daylight
and are disabled by ``world.peaceful``.
"""
from __future__ import annotations

import math

from . import blocks as B
from .body import Body

I = B.ID
KINDS = {
    #          w     h    hp  speed  type       drops                                        tempt
    "chicken": (0.4, 0.7, 4, 0.6, "passive", [("feather", 1), ("raw_meat", 1)], ("wheat_seeds",)),
    "cow": (0.9, 1.4, 10, 0.5, "passive", [("leather", 1), ("raw_meat", 2)], ("wheat",)),
    "sheep": (0.9, 1.3, 8, 0.5, "passive", [("white_wool", 1), ("raw_meat", 1)], ("wheat",)),
    "pig": (0.9, 0.9, 10, 0.5, "passive", [("raw_meat", 2)], ("carrot", "potato")),
    "rabbit": (0.4, 0.5, 3, 0.8, "passive", [("raw_meat", 1)], ("carrot",)),
    "fish": (0.5, 0.3, 3, 0.6, "passive", [("raw_fish", 1)], ()),
    "bee": (0.7, 0.6, 10, 0.5, "passive", [], ()),
    "wolf": (0.6, 0.85, 8, 0.7, "neutral", [("bone", 1)], ("raw_meat",)),
    "bear": (1.4, 1.4, 30, 0.55, "neutral", [("leather", 2), ("raw_meat", 3)], ("berries",)),
    "slime": (1.0, 1.0, 8, 0.5, "hostile", [("slimeball", 1)], ()),
    "hollow": (0.6, 1.95, 20, 0.55, "hostile", [("bone", 2), ("string", 1)], ()),
}
DAMAGE = {"wolf": 4, "bear": 6, "slime": 2, "hollow": 3, "bee": 1}
_WATER = B.IS_WATER
_SOLID = B.SOLID


class Creature(Body):
    def __init__(self, world, kind, x, y, z, eid=None):
        w, h, hp, sp, typ, drops, tempt = KINDS[kind]
        super().__init__(world, x, y, z, kind=kind, eid=eid if eid is not None else world._new_id(), width=w,
                         height=h, eye=h * 0.85, max_health=hp, speed=sp)
        self.type = typ
        self.swims = kind == "fish"
        self.flies = kind == "bee"
        self.drops = drops
        self.tempt = tempt
        self.state = "idle"
        self.timer = world.rng.randint(10, 60)
        self.target = None          # (x, z) wander target
        self.foe = None             # entity being chased / fled
        self.angry = 0
        self.cool = 0
        self.home = (x, y, z)
        self.age = 0

    # ------------------------------------------------------------------ AI
    def think(self):
        w = self.world
        self.age += 1
        if self.cool > 0:
            self.cool -= 1
        if self.angry > 0:
            self.angry -= 1
        self.jump = self.descend = False
        hostile = (self.type == "hostile" or self.angry > 0) and not w.peaceful
        if (self.age + self.id) % 10 == 0:
            self._decide(hostile)
        st = self.state
        if st in ("chase", "flee", "follow") and self.foe is not None:
            f = self.foe
            if getattr(f, "dead", False) or f.world is not w:
                self.state, self.foe = "idle", None
                self.stop()
                return
            dx, dz = f.x - self.x, f.z - self.z
            d = math.hypot(dx, dz) or 1e-6
            if st == "flee":
                self.move_x, self.move_z = -dx / d, -dz / d
                self.sprint = True
            elif st == "follow":
                if d < 2.2:
                    self.move_x = self.move_z = 0.0
                else:
                    self.move_x, self.move_z = dx / d, dz / d
            else:
                self.move_x, self.move_z = dx / d, dz / d
                self.sprint = True
                if d < 0.5 + self.w / 2 + 0.6 and abs(f.y - self.y) < 2.0 and self.cool == 0:
                    self.cool = 20
                    f.hurt(DAMAGE.get(self.kind, 2), "attacked", self)
                    self.anim = "attack"
            self.face_dir(self.move_x, self.move_z)
        elif st == "wander" and self.target is not None:
            tx, tz = self.target
            dx, dz = tx - self.x, tz - self.z
            d = math.hypot(dx, dz)
            if d < 0.6 or self.timer <= 0:
                self.state = "idle"
                self.stop()
                self.timer = w.rng.randint(40, 140)
            else:
                self.move_x, self.move_z = dx / d, dz / d
                self.face_dir(dx, dz)
                if not self.flies and not self.swims and self.on_ground and self._danger_ahead(dx / d, dz / d):
                    self.state = "idle"
                    self.stop()
                    self.timer = w.rng.randint(20, 60)
        self.timer -= 1
        if self.collided_h and (self.on_ground or self.in_water) and (abs(self.move_x) + abs(self.move_z)) > 0:
            self.jump = True
        if self.in_water and not self.swims:
            self.jump = True
        if self.kind == "slime" and (abs(self.move_x) + abs(self.move_z)) > 0 and self.on_ground:
            self.jump = True
        if self.flies:
            gy = w.stand_y(self.x, self.z, self.y)
            if self.y < gy + 1.0:
                self.jump = True
            elif self.y > gy + 4.0:
                self.descend = True
        if self.swims and self.in_water and (self.age // 30) % 3 == 0:
            self.descend = (self.age // 90) % 2 == 0
            self.jump = not self.descend
        # hollows burn in daylight under the open sky
        if self.kind == "hollow" and w.sky_level() >= 12 and (self.age % 20 == 0):
            fx, fz = math.floor(self.x), math.floor(self.z)
            if self.y + self.h > w._chunk(fx >> 4, fz >> 4).top[fz & 15, fx & 15]:
                self.fire_ticks = max(self.fire_ticks, 60)

    def _decide(self, hostile):
        w = self.world
        if self.state == "flee" and self.timer > 0:
            return
        near = None
        bd = 1e9
        for p in w._players():
            if p.dead:
                continue
            d = (p.x - self.x) ** 2 + (p.z - self.z) ** 2 + (p.y - self.y) ** 2
            if d < bd:
                near, bd = p, d
        if self.attacker is not None and self.hurt_flash > 0:
            if self.type == "passive":
                self.state, self.foe, self.timer = "flee", self.attacker, 60
                return
            if self.type == "neutral":
                self.angry = 600
                self.state, self.foe = "chase", self.attacker
                return
        if hostile and near is not None and bd < 16 * 16:
            self.state, self.foe = "chase", near
            return
        if self.tempt and near is not None and bd < 8 * 8 and near.held() in self.tempt:
            self.state, self.foe = "follow", near
            return
        if self.state in ("chase", "follow", "flee"):
            self.state, self.foe = "idle", None
            self.stop()
            self.timer = w.rng.randint(20, 60)
        if self.state == "idle" and self.timer <= 0:
            r = 6 if not self.flies else 4
            if self.flies or self.swims:
                hx, hy, hz = self.home
                tx, tz = hx + w.rng.uniform(-r, r), hz + w.rng.uniform(-r, r)
            else:
                tx, tz = self.x + w.rng.uniform(-r, r), self.z + w.rng.uniform(-r, r)
            self.target = (tx, tz)
            self.state = "wander"
            self.timer = 160
            self.sprint = False

    def _danger_ahead(self, dx, dz):
        w = self.world
        ax, az = math.floor(self.x + dx * 0.8), math.floor(self.z + dz * 0.8)
        y = math.floor(self.y + 0.01)
        for k in range(0, 4):
            b = w.get(ax, y - k, az)
            if B.IS_LAVA[b] or b == I["fire"] or b == I["cactus"]:
                return True
            if _WATER[b]:
                return self.type != "neutral" or k > 0
            if _SOLID[b]:
                return False
        return True

    # ------------------------------------------------------------------ public / persistence
    def public(self):
        d = super().public()
        if self.angry > 0 or self.type == "hostile":
            d["hostile"] = True
        return d

    def to_dict(self):
        return {"kind": self.kind, "pos": [self.x, self.y, self.z], "yaw": self.yaw, "health": self.health,
                "home": list(self.home), "id": self.id}

    @classmethod
    def from_dict(cls, world, d):
        c = cls(world, d["kind"], *d["pos"], eid=d.get("id"))
        c.yaw = d.get("yaw", 0.0)
        c.health = d.get("health", c.max_health)
        c.home = tuple(d.get("home", d["pos"]))
        return c


def spawn_creature(world, kind, x, y, z):
    if kind not in KINDS:
        return None
    if KINDS[kind][4] == "hostile" and world.peaceful:
        return None
    c = Creature(world, kind, x, y, z)
    world.entities[c.id] = c
    return c


def on_creature_death(world, c, cause):
    for item, n in c.drops:
        world.spawn_item(c.x, c.y + 0.3, c.z, item, n)
    killer = c.attacker
    world.emit("creature_died", kind=c.kind, id=c.id, cause=cause, by=getattr(killer, "id", None),
               x=round(c.x, 1), y=round(c.y, 1), z=round(c.z, 1))


def melee(world, attacker, target):
    """A body hits a target with whatever it holds. Returns the damage dealt."""
    from . import items as IT
    held = attacker.held()
    it = IT.by_name.get(held) if held else None
    dmg = it["damage"] if it and it["tool"] else 1
    if target.hurt(dmg, "attacked", attacker):
        if it and it["tool"]:
            attacker.wear_tool()
        attacker.exhaustion += 0.1
        attacker.anim = "attack"
        return dmg
    return 0


_PASSIVE_BY_BIOME = {"plains": ["cow", "sheep", "pig", "chicken"], "forest": ["pig", "chicken", "sheep"],
                     "birch_forest": ["chicken", "sheep"], "savanna": ["cow", "sheep"], "jungle": ["chicken", "pig"],
                     "taiga": ["rabbit", "sheep", "wolf"], "snowy_tundra": ["rabbit"], "desert": ["rabbit"],
                     "swamp": ["chicken"], "mountains": ["sheep", "rabbit"]}


def population_tick(world):
    """Every 2 s: night spawns near players, despawning far/daylit hostiles, passive top-ups."""
    rng = world.rng
    players = world._players()
    cs = [e for e in world.entities.values() if isinstance(e, Creature)]
    hostile = [c for c in cs if c.type == "hostile"]
    for c in hostile:
        far = all((c.x - p.x) ** 2 + (c.z - p.z) ** 2 > 96 * 96 for p in players)
        if far or world.peaceful or (not world.is_night() and rng.random() < 0.05 and c.kind == "slime"):
            world.entities.pop(c.id, None)
    a = world.agent
    near = [c for c in cs if (c.x - a.x) ** 2 + (c.z - a.z) ** 2 < 64 * 64]
    if not world.peaceful and world.sky_level() < 8 and sum(c.type == "hostile" for c in near) < world.max_hostiles:
        for _ in range(3):
            p = players[rng.randrange(len(players))]
            ang = rng.uniform(0, 2 * math.pi)
            dist = rng.uniform(24, 40)
            x, z = p.x + math.cos(ang) * dist, p.z + math.sin(ang) * dist
            if (math.floor(x) >> 4, math.floor(z) >> 4) not in world.active:
                continue
            y = world.stand_y(x, z)
            fx, fz = math.floor(x), math.floor(z)
            if B.LIQUID[world.get(fx, y, fz)] or not _SOLID[world.get(fx, y - 1, fz)]:
                continue
            if world.light_at(fx, y, fz) >= 8:
                continue
            kind = "slime" if world.biome(x, z) == "swamp" and rng.random() < 0.5 else "hollow"
            spawn_creature(world, kind, fx + 0.5, y, fz + 0.5)
            break
    if world.t % 600 < 40 and not world.is_night() and sum(c.type != "hostile" for c in near) < 8:
        ang = rng.uniform(0, 2 * math.pi)
        dist = rng.uniform(20, 40)
        x, z = a.x + math.cos(ang) * dist, a.z + math.sin(ang) * dist
        if (math.floor(x) >> 4, math.floor(z) >> 4) in world.active:
            kinds = _PASSIVE_BY_BIOME.get(world.biome(x, z))
            if kinds:
                kind = kinds[rng.randrange(len(kinds))]
                for k in range(rng.randint(2, 3)):
                    xx, zz = x + rng.uniform(-2, 2), z + rng.uniform(-2, 2)
                    y = world.stand_y(xx, zz)
                    if world.get(math.floor(xx), y - 1, math.floor(zz)) == I["grass"]:
                        spawn_creature(world, kind, math.floor(xx) + 0.5, y, math.floor(zz) + 0.5)
