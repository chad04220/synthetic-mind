"""The shared Body (DESIGN-v5 §3.1): the inhabitant, the visitor and (with other sizes) creatures.

AABB physics at 20 Hz: gravity, per-axis collision against block boxes (blocks may be shorter
than 1, e.g. farmland), step-up 0.6, jump, swimming, ladders, sprint and sneak (sneaking never
walks off an edge). Vitals: health/food/air with fall, lava, fire, drowning, suffocation and
starvation damage, and regeneration when fed. Inventory: 36 slots (0–8 are the hotbar) plus the
selected hotbar slot; a slot is ``None`` or ``{"item": name, "count": n}`` (+ ``"dur"`` for tools).

Conventions: x east, y up, z south. ``yaw`` (radians) turns about +y, yaw 0 looks north (−z),
yaw π/2 looks west (−x) — the three.js camera convention; ``pitch`` > 0 looks up.
Forward vector = (−sin yaw·cos pitch, sin pitch, −cos yaw·cos pitch).

Controls (set every tick by skills, the page or creature AI): ``move_x``/``move_z`` (desired
horizontal direction in world space, length ≤ 1), ``jump``, ``sneak``, ``sprint``, ``descend``.
"""
from __future__ import annotations

import math

from . import blocks as B
from . import items as IT

DT = 0.05
GRAVITY = 0.08
WALK = 4.317 * DT
EPS = 1e-4

SOLID = B.SOLID
HEIGHT = B.HEIGHT
IS_WATER = B.IS_WATER
IS_LAVA = B.IS_LAVA
CLIMB = B.CLIMBABLE
OPAQUE = B.OPAQUE
FIRE = B.ID["fire"]
CACTUS = B.ID["cactus"]
ICE = {B.ID["ice"], B.ID["packed_ice"]}
CAMPFIRE = B.ID["campfire"]


def _f(v):
    return math.floor(v)


class Body:
    is_player = False
    swims = False      # fish: lives in water
    flies = False      # bees

    def __init__(self, world, x, y, z, *, kind="person", name=None, eid=None, width=0.6, height=1.8, eye=1.62,
                 max_health=20.0, speed=1.0):
        self.world = world
        self.id = eid
        self.kind = kind
        self.name = name
        self.x, self.y, self.z = float(x), float(y), float(z)
        self.vx = self.vy = self.vz = 0.0
        self.yaw = 0.0
        self.pitch = 0.0
        self.w = width
        self.h = height
        self.eye_h = eye
        self.speed = speed
        self.on_ground = False
        self.in_water = self.in_lava = self.head_in_water = self.on_ladder = False
        self.collided_h = False
        self.max_health = float(max_health)
        self.health = float(max_health)
        self.food = 20.0
        self.air = 300
        self.exhaustion = 0.0
        self.fall = 0.0
        self.fire_ticks = 0
        self.invuln = 0
        self.hurt_flash = 0
        self.inv: list[dict | None] = [None] * 36
        self.selected = 0
        self.move_x = self.move_z = 0.0
        self.jump = self.sneak = self.sprint = self.descend = False
        self.anim = "idle"
        self.said = None
        self.said_until = 0
        self.sleeping = False
        self.dead = False
        self.spawn_point = (self.x, self.y, self.z)
        self._timers = {"regen": 0, "starve": 0, "drown": 0, "lava": 0, "fire": 0, "suff": 0}
        self._rest = 0
        self.last_damage = None
        self.attacker = None

    # ------------------------------------------------------------------ geometry
    def eye(self):
        return (self.x, self.y + self.eye_h, self.z)

    def look_vec(self):
        cp = math.cos(self.pitch)
        return (-math.sin(self.yaw) * cp, math.sin(self.pitch), -math.cos(self.yaw) * cp)

    def look_at(self, tx, ty, tz):
        ex, ey, ez = self.eye()
        dx, dy, dz = tx - ex, ty - ey, tz - ez
        self.yaw = math.atan2(-dx, -dz)
        self.pitch = math.atan2(dy, math.hypot(dx, dz) + 1e-9)

    def face_dir(self, dx, dz):
        if abs(dx) + abs(dz) > 1e-6:
            self.yaw = math.atan2(-dx, -dz)

    def feet_cell(self):
        return (_f(self.x), _f(self.y + 0.01), _f(self.z))

    def dist_to(self, x, y, z):
        return math.sqrt((self.x - x) ** 2 + (self.y - y) ** 2 + (self.z - z) ** 2)

    def overlaps_cell(self, bx, by, bz):
        hw = self.w / 2
        return (self.x - hw < bx + 1 and self.x + hw > bx and self.z - hw < bz + 1 and self.z + hw > bz
                and self.y < by + 1 and self.y + self.h > by)

    # ------------------------------------------------------------------ physics
    def stop(self):
        self.move_x = self.move_z = 0.0
        self.jump = self.sprint = self.descend = False

    def step(self):
        """One 50 ms physics tick."""
        w = self.world
        get = w.get
        moving = abs(self.move_x) + abs(self.move_z) > 1e-6 or self.jump or self.descend
        if (not moving and self.on_ground and abs(self.vx) < 1e-3 and abs(self.vz) < 1e-3 and not self.in_water
                and not self.in_lava and not self.on_ladder and not self.fire_ticks):
            self._rest += 1
            if self._rest > 4 and (self._rest % 10):
                return
        else:
            self._rest = 0
        x, y, z = self.x, self.y, self.z
        fx, fz = _f(x), _f(z)
        feet = get(fx, _f(y + 0.05), fz)
        mid = get(fx, _f(y + min(0.9, self.h * 0.5)), fz)
        head = get(fx, _f(y + self.eye_h), fz)
        self.in_water = IS_WATER[feet] or IS_WATER[mid]
        self.in_lava = IS_LAVA[feet] or IS_LAVA[mid]
        self.head_in_water = IS_WATER[head]
        self.on_ladder = (CLIMB[feet] and not SOLID[feet]) or (CLIMB[mid] and not SOLID[mid])
        liquid = self.in_water or self.in_lava
        # horizontal intent
        mx, mz = self.move_x, self.move_z
        ml = math.hypot(mx, mz)
        if ml > 1:
            mx, mz = mx / ml, mz / ml
        sp = WALK * self.speed
        if self.sprint and not self.sneak and (not self.is_player or self.food > 6):
            sp *= 1.3
        if self.sneak:
            sp *= 0.3
        if self.in_lava:
            sp *= 0.35
        elif self.in_water and not self.swims:
            sp *= 0.5
        tvx, tvz = mx * sp, mz * sp
        if self.on_ground:
            below = get(fx, _f(y - 0.05), fz)
            k = 0.1 if below in ICE else 0.6
        elif liquid:
            k = 0.35
        else:
            k = 0.25 if not self.flies else 0.5
        self.vx += (tvx - self.vx) * k
        self.vz += (tvz - self.vz) * k
        # vertical
        if self.flies:
            self.vy = 0.12 if self.jump else (-0.12 if self.descend else self.vy * 0.6)
        elif self.swims and self.in_water:
            self.vy = 0.08 if self.jump else (-0.08 if self.descend else self.vy * 0.7)
            if not IS_WATER[get(fx, _f(y + self.h + 0.1), fz)] and self.vy > 0:
                self.vy = 0.0
        elif liquid:
            if self.jump:
                self.vy = min(self.vy + 0.06, 0.13)
                if self.collided_h:
                    self.vy = 0.3       # climb out onto a bank
            elif self.descend:
                self.vy = max(self.vy - 0.04, -0.15)
            else:
                self.vy = (self.vy - 0.02) * 0.8
        elif self.on_ladder:
            if self.jump or (self.collided_h and ml > 0.1):
                self.vy = 0.12
            elif self.sneak:
                self.vy = 0.0
            elif self.descend:
                self.vy = -0.12
            else:
                self.vy = max(self.vy - GRAVITY, -0.15)
        else:
            if self.jump and self.on_ground:
                self.vy = 0.42
                self.exhaustion += 0.2 if self.sprint else 0.05
            self.vy = (self.vy - GRAVITY) * 0.98
            if self.vy < -3.9:
                self.vy = -3.9
        vy0 = self.vy
        ox, oy, oz = self.x, self.y, self.z
        self._move(self.vx, self.vy, self.vz)
        moved_h = math.hypot(self.x - ox, self.z - oz)
        if self.is_player:
            self.exhaustion += moved_h * (0.1 if self.sprint else 0.01)
        # falling
        if liquid or self.on_ladder or self.flies or self.swims:
            self.fall = 0.0
        elif vy0 < 0 and self.y < oy:
            self.fall += oy - self.y
        if self.on_ground:
            if self.fall > 3.0:
                dmg = math.ceil(self.fall - 3.0)
                landed = get(_f(self.x), _f(self.y - 0.05), _f(self.z))
                if B.BASE[landed] == "hay" or B.BASE[landed] == "bed":
                    dmg = dmg // 5
                if dmg > 0:
                    self.hurt(dmg, "fall")
            self.fall = 0.0
        if moved_h > 0.01:
            self.anim = "swim" if liquid else ("climb" if self.on_ladder else "walk")
        elif self.anim in ("walk", "swim", "climb"):
            self.anim = "idle"

    def _solid_box(self, bx, by, bz):
        bid = self.world.get(bx, by, bz)
        if SOLID[bid]:
            return HEIGHT[bid]
        return 0.0

    def _move(self, dx, dy, dz):
        hw = self.w / 2
        was_ground = self.on_ground
        # --- Y
        ndy = self._clip_y(self.x - hw, self.x + hw, self.y, self.y + self.h, self.z - hw, self.z + hw, dy)
        self.on_ground = dy < 0 and ndy > dy + EPS
        if ndy != dy:
            self.vy = 0.0
        self.y += ndy
        # sneak edge guard
        if self.sneak and (self.on_ground or was_ground) and not self.in_water:
            if dx and not self._has_floor(self.x + dx, self.z):
                dx = 0.0
                self.vx = 0.0
            if dz and not self._has_floor(self.x + dx, self.z + dz):
                dz = 0.0
                self.vz = 0.0
        # --- X then Z
        ndx = self._clip_x(self.x - hw, self.x + hw, self.y, self.y + self.h, self.z - hw, self.z + hw, dx)
        ndz = self._clip_z(self.x + ndx - hw, self.x + ndx + hw, self.y, self.y + self.h, self.z - hw,
                           self.z + hw, dz)
        blocked = (abs(ndx - dx) > EPS) or (abs(ndz - dz) > EPS)
        if blocked and (self.on_ground or was_ground) and not self.flies:
            # step-up: try lifting by up to 0.6, then moving, then settling down
            up = self._clip_y(self.x - hw, self.x + hw, self.y, self.y + self.h, self.z - hw, self.z + hw, 0.6)
            if up > 0.05:
                y2 = self.y + up
                sdx = self._clip_x(self.x - hw, self.x + hw, y2, y2 + self.h, self.z - hw, self.z + hw, dx)
                sdz = self._clip_z(self.x + sdx - hw, self.x + sdx + hw, y2, y2 + self.h, self.z - hw,
                                   self.z + hw, dz)
                down = self._clip_y(self.x + sdx - hw, self.x + sdx + hw, y2, y2 + self.h, self.z + sdz - hw,
                                    self.z + sdz + hw, -up)
                if sdx * sdx + sdz * sdz > ndx * ndx + ndz * ndz + 1e-6 and up + down <= 0.6 + EPS:
                    ndx, ndz = sdx, sdz
                    self.y = y2 + down
                    blocked = (abs(ndx - dx) > EPS) or (abs(ndz - dz) > EPS)
        self.collided_h = blocked
        if abs(ndx - dx) > EPS:
            self.vx = 0.0
        if abs(ndz - dz) > EPS:
            self.vz = 0.0
        self.x += ndx
        self.z += ndz

    def _has_floor(self, x, z):
        hw = self.w / 2 - 0.05
        y = _f(self.y - 0.1)
        for bx in (_f(x - hw), _f(x + hw)):
            for bz in (_f(z - hw), _f(z + hw)):
                if SOLID[self.world.get(bx, y, bz)]:
                    return True
        return False

    def _clip_y(self, x0, x1, y0, y1, z0, z1, d):
        if d == 0:
            return 0.0
        get = self.world.get
        xs = range(_f(x0 + EPS), _f(x1 - EPS) + 1)
        zs = range(_f(z0 + EPS), _f(z1 - EPS) + 1)
        if d < 0:
            lo = _f(y0 + d) - 0
            for by in range(_f(y0 - EPS), lo - 1, -1):
                for bx in xs:
                    for bz in zs:
                        bid = get(bx, by, bz)
                        if SOLID[bid]:
                            top = by + HEIGHT[bid]
                            if top <= y0 + EPS and top > y0 + d:
                                d = top - y0
                if by + 1 <= y0 + d:
                    break
            return d
        hi = _f(y1 + d)
        for by in range(_f(y1 - EPS) if y1 - _f(y1) > EPS else _f(y1), hi + 1):
            for bx in xs:
                for bz in zs:
                    bid = get(bx, by, bz)
                    if SOLID[bid] and by >= y1 - EPS and by < y1 + d:
                        d = by - y1
        return d

    def _clip_x(self, x0, x1, y0, y1, z0, z1, d):
        if d == 0:
            return 0.0
        get = self.world.get
        ys = range(_f(y0 + EPS) - (1 if y0 - _f(y0) < 0.5 else 0), _f(y1 - EPS) + 1)
        zs = range(_f(z0 + EPS), _f(z1 - EPS) + 1)
        if d > 0:
            for bx in range(_f(x1 - EPS) + (0 if x1 - _f(x1) > EPS else 0), _f(x1 + d) + 1):
                if bx < x1 - EPS:
                    continue
                for by in ys:
                    for bz in zs:
                        bid = get(bx, by, bz)
                        if SOLID[bid] and by + HEIGHT[bid] > y0 + EPS and by < y1 - EPS:
                            d = min(d, bx - x1)
            return max(d, 0.0)
        for bx in range(_f(x0 + EPS) - 1, _f(x0 + d) - 1, -1):
            if bx + 1 > x0 + EPS:
                continue
            for by in ys:
                for bz in zs:
                    bid = get(bx, by, bz)
                    if SOLID[bid] and by + HEIGHT[bid] > y0 + EPS and by < y1 - EPS:
                        d = max(d, bx + 1 - x0)
        return min(d, 0.0)

    def _clip_z(self, x0, x1, y0, y1, z0, z1, d):
        if d == 0:
            return 0.0
        get = self.world.get
        ys = range(_f(y0 + EPS) - (1 if y0 - _f(y0) < 0.5 else 0), _f(y1 - EPS) + 1)
        xs = range(_f(x0 + EPS), _f(x1 - EPS) + 1)
        if d > 0:
            for bz in range(_f(z1 - EPS), _f(z1 + d) + 1):
                if bz < z1 - EPS:
                    continue
                for by in ys:
                    for bx in xs:
                        bid = get(bx, by, bz)
                        if SOLID[bid] and by + HEIGHT[bid] > y0 + EPS and by < y1 - EPS:
                            d = min(d, bz - z1)
            return max(d, 0.0)
        for bz in range(_f(z0 + EPS) - 1, _f(z0 + d) - 1, -1):
            if bz + 1 > z0 + EPS:
                continue
            for by in ys:
                for bx in xs:
                    bid = get(bx, by, bz)
                    if SOLID[bid] and by + HEIGHT[bid] > y0 + EPS and by < y1 - EPS:
                        d = max(d, bz + 1 - z0)
        return min(d, 0.0)

    # ------------------------------------------------------------------ vitals
    def vitals(self):
        """Once per tick after physics: environment damage, air, food, regeneration."""
        w = self.world
        t = self._timers
        if self.invuln > 0:
            self.invuln -= 1
        if self.hurt_flash > 0:
            self.hurt_flash -= 1
        fx, fz = _f(self.x), _f(self.z)
        if self.in_lava:
            self.fire_ticks = max(self.fire_ticks, 300)
            t["lava"] += 1
            if t["lava"] >= 10:
                t["lava"] = 0
                self.hurt(4, "lava")
        else:
            t["lava"] = 0
        feet = w.get(fx, _f(self.y + 0.05), fz)
        if feet == FIRE or feet == CAMPFIRE:
            self.fire_ticks = max(self.fire_ticks, 80 if feet == FIRE else 0)
            if feet == CAMPFIRE and w.t % 20 == 0:
                self.hurt(1, "fire")
        if self.in_water or w.raining_on(self.x, self.y + self.h, self.z):
            self.fire_ticks = 0
        if self.fire_ticks > 0:
            self.fire_ticks -= 1
            t["fire"] += 1
            if t["fire"] >= 20:
                t["fire"] = 0
                self.hurt(1, "fire")
        # touching cactus
        if w.t % 10 == 0:
            for dx, dz in ((0.36, 0), (-0.36, 0), (0, 0.36), (0, -0.36)):
                if w.get(_f(self.x + dx), _f(self.y + 0.5), _f(self.z + dz)) == CACTUS:
                    self.hurt(1, "cactus")
                    break
        # breathing
        if self.swims:
            if not self.in_water:
                t["drown"] += 1
                if t["drown"] >= 40:
                    t["drown"] = 0
                    self.hurt(1, "suffocation")
            return
        if self.head_in_water and not self.flies:
            self.air -= 1
            if self.air <= -20:
                self.air = 0
                self.hurt(2, "drowning")
        else:
            self.air = min(300, self.air + 5)
        head = w.get(fx, _f(self.y + self.eye_h), fz)
        if OPAQUE[head] and SOLID[head]:
            t["suff"] += 1
            if t["suff"] >= 10:
                t["suff"] = 0
                self.hurt(1, "suffocation")
        if not self.is_player:
            return
        # food
        self.exhaustion += w.hunger_rate
        while self.exhaustion >= 4.0:
            self.exhaustion -= 4.0
            self.food = max(0.0, self.food - 1)
        if self.food >= 18 and self.health < self.max_health:
            t["regen"] += 1
            if t["regen"] >= 80:
                t["regen"] = 0
                self.health = min(self.max_health, self.health + 1)
                self.exhaustion += 1.5
        elif self.food <= 0:
            t["starve"] += 1
            if t["starve"] >= 80:
                t["starve"] = 0
                if self.health > 1:
                    self.hurt(1, "starvation")
        else:
            t["regen"] = 0

    def hurt(self, amount, cause="", attacker=None):
        if self.dead or amount <= 0:
            return False
        if self.invuln > 0 and cause not in ("drowning", "starvation", "suffocation", "fire", "lava"):
            return False
        self.health -= amount
        self.invuln = 10
        self.hurt_flash = 6
        self.last_damage = cause
        self.attacker = attacker
        if attacker is not None:
            dx, dz = self.x - attacker.x, self.z - attacker.z
            d = math.hypot(dx, dz) or 1.0
            self.vx += dx / d * 0.4
            self.vz += dz / d * 0.4
            self.vy = max(self.vy, 0.25)
        self.anim = "hurt"
        self.world.on_hurt(self, amount, cause, attacker)
        if self.health <= 0:
            self.health = 0
            self.world.on_death(self, cause)
        return True

    def eat(self, item):
        val = IT.FOOD.get(item, 0)
        if not val:
            return False
        if not self.remove(item, 1):
            return False
        self.food = min(20.0, self.food + val)
        self.exhaustion = 0.0
        if item == "mushroom_stew":
            self.add("bowl", 1)
        return True

    # ------------------------------------------------------------------ inventory
    def count(self, name):
        if name.startswith("#"):
            grp = set(IT.GROUPS.get(name[1:], ()))
            return sum(s["count"] for s in self.inv if s and s["item"] in grp)
        return sum(s["count"] for s in self.inv if s and s["item"] == name)

    def has(self, name, n=1):
        return self.count(name) >= n

    def items(self) -> dict:
        out = {}
        for s in self.inv:
            if s:
                out[s["item"]] = out.get(s["item"], 0) + s["count"]
        return out

    def add(self, name, count=1, dur=None) -> int:
        """Add items; returns how many did not fit."""
        it = IT.by_name.get(name)
        if it is None or count <= 0:
            return count
        stack = it["stack"]
        if stack > 1:
            for s in self.inv:
                if s and s["item"] == name and s["count"] < stack:
                    k = min(stack - s["count"], count)
                    s["count"] += k
                    count -= k
                    if not count:
                        return 0
        for i in range(36):
            if self.inv[i] is None:
                k = min(stack, count)
                slot = {"item": name, "count": k}
                if it["durability"]:
                    slot["dur"] = it["durability"] if dur is None else dur
                self.inv[i] = slot
                count -= k
                if not count:
                    return 0
        return count

    def remove(self, name, count=1) -> int:
        """Remove up to ``count`` (``#group`` allowed); returns how many were removed."""
        if name.startswith("#"):
            got = 0
            grp = IT.GROUPS.get(name[1:], ())
            # take from the most plentiful kind first
            for k in sorted(grp, key=lambda n: -self.count(n)):
                if got >= count:
                    break
                got += self.remove(k, count - got)
            return got
        got = 0
        for i in range(35, -1, -1):
            s = self.inv[i]
            if s and s["item"] == name:
                k = min(s["count"], count - got)
                s["count"] -= k
                got += k
                if s["count"] <= 0:
                    self.inv[i] = None
                if got >= count:
                    break
        return got

    def space_for(self, name) -> int:
        it = IT.by_name.get(name)
        if not it:
            return 0
        n = 0
        for s in self.inv:
            if s is None:
                n += it["stack"]
            elif s["item"] == name:
                n += it["stack"] - s["count"]
        return n

    def held(self):
        s = self.inv[self.selected]
        return s["item"] if s else None

    def find(self, name):
        for i, s in enumerate(self.inv):
            if s and (s["item"] == name or (name.startswith("#") and s["item"] in IT.GROUPS.get(name[1:], ()))):
                return i
        return None

    def select_slot(self, i):
        if 0 <= i < 36:
            if i >= 9:
                # bring it to the hotbar
                j = self.selected
                self.inv[i], self.inv[j] = self.inv[j], self.inv[i]
            else:
                self.selected = i

    def select(self, name) -> bool:
        if name is None:
            for i in range(9):
                if self.inv[i] is None:
                    self.selected = i
                    return True
            return True
        i = self.find(name)
        if i is None:
            return False
        self.select_slot(i)
        return True

    def best_tool(self, bid):
        """Slot index of the best tool for breaking block ``bid`` (None = bare hands)."""
        b = B.BLOCKS[bid]
        best, best_t = None, self.break_time(bid, None)
        for i, s in enumerate(self.inv):
            if not s:
                continue
            it = IT.by_name.get(s["item"])
            if not it or not it["tool"]:
                continue
            t = self.break_time(bid, s["item"])
            harvest_ok = _can_harvest(b, it)
            if best is not None:
                cur = IT.by_name[self.inv[best]["item"]]
                if _can_harvest(b, cur) and not harvest_ok:
                    continue
            if t < best_t - 1e-6 or (harvest_ok and best is None and b["tool_level"] > 0):
                best, best_t = i, t
        return best

    def break_time(self, bid, tool_item):
        b = B.BLOCKS[bid]
        h = b["hardness"]
        if h < 0:
            return math.inf
        if h == 0:
            return 0.05
        it = IT.by_name.get(tool_item) if tool_item else None
        speed = 1.0
        if it and it["tool"] and (it["tool"] == b["tool"] or (it["tool"] == "sword" and b["base"] == "vines")):
            speed = it["speed"]
        if it and it["tool"] == "shears" and (b["base"].endswith("leaves") or b["base"].endswith("wool")):
            speed = it["speed"]
        t = h / speed
        if not _can_harvest(b, it):
            t *= 3.3
        if self.in_water and not self.on_ground:
            t *= 2
        return max(0.05, t)

    def wear_tool(self, slot_index=None):
        i = self.selected if slot_index is None else slot_index
        s = self.inv[i]
        if s and "dur" in s:
            s["dur"] -= 1
            if s["dur"] <= 0:
                self.inv[i] = None
                self.world.emit("tool_broke", who=self.id, name=self.name, item=s["item"])

    # ------------------------------------------------------------------ public / persistence
    def public(self):
        d = {"id": self.id, "kind": self.kind, "x": round(self.x, 3), "y": round(self.y, 3), "z": round(self.z, 3),
             "yaw": round(self.yaw, 3), "pitch": round(self.pitch, 3), "anim": self.anim}
        if self.name:
            d["name"] = self.name
        if self.said and self.world.t < self.said_until:
            d["said"] = self.said
        if self.is_player or self.kind in ("wolf", "bear"):
            d["health"] = round(self.health, 1)
        h = self.held()
        if h:
            d["held"] = h
        if self.hurt_flash:
            d["hurt"] = True
        if self.sleeping:
            d["anim"] = "sleep"
        return d

    def status(self):
        return {**self.public(), "health": round(self.health, 1), "food": round(self.food, 1), "air": self.air,
                "selected": self.selected, "inventory": [[s["item"], s["count"]] if s else None for s in self.inv],
                "on_ground": self.on_ground, "in_water": self.in_water, "in_lava": self.in_lava,
                "on_fire": self.fire_ticks > 0, "sleeping": self.sleeping}

    def to_dict(self):
        return {"kind": self.kind, "name": self.name, "pos": [self.x, self.y, self.z], "yaw": self.yaw,
                "pitch": self.pitch, "health": self.health, "food": self.food, "air": self.air,
                "inv": self.inv, "selected": self.selected, "spawn": list(self.spawn_point),
                "exhaustion": self.exhaustion}

    def load_dict(self, d):
        self.x, self.y, self.z = d["pos"]
        self.yaw, self.pitch = d.get("yaw", 0.0), d.get("pitch", 0.0)
        self.health, self.food, self.air = d.get("health", 20.0), d.get("food", 20.0), d.get("air", 300)
        self.inv = list(d.get("inv") or [None] * 36) + [None] * max(0, 36 - len(d.get("inv") or []))
        self.inv = self.inv[:36]
        self.selected = d.get("selected", 0)
        self.spawn_point = tuple(d.get("spawn", (self.x, self.y, self.z)))
        self.exhaustion = d.get("exhaustion", 0.0)


def _can_harvest(b, it):
    need = b["tool_level"]
    if need <= 0:
        return True
    if not it or it["tool"] != b["tool"]:
        return False
    return it["tool_level"] >= need
