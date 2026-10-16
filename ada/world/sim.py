"""The World Ada lives in: a valley with a cottage, a garden, an orchard, a meadow, a forest, a lake,
a village (bakery, library, workshop, the Oracle's shrine) and an observatory on the hill.

Time passes in days and nights (nights are when she sleeps and the Academy studies), seasons turn
every few days and the weather changes. Ada has six needs; things grow, ripen and regrow; three
villagers keep their own routines; animals wander. Everything she can sense is written in plain
first-person sentences, and everything she can do is a verb with an object, so her own words can
drive what she does.
"""
from __future__ import annotations

import heapq
import math
import random
import time
from dataclasses import dataclass, field

from ..ontology import KINDS, NPCS

W, H = 64, 40
GRASS, WATER, SAND, TREE, ROCK, FLOWERS, PATH, FLOOR, WALL, DOOR, SOIL = range(11)
TERRAIN = ["grass", "water", "sand", "a tree", "a rock", "flowers", "a path", "a floor", "a wall", "a door", "soil"]
BLOCKING = {WATER, TREE, ROCK, WALL}
SEASONS = ["spring", "summer", "autumn", "winter"]
DIRS = {"north": (0, -1), "south": (0, 1), "west": (-1, 0), "east": (1, 0)}
NEEDS = ["energy", "water", "rest", "warmth", "company", "fun"]


@dataclass
class Being:
    """Ada, the villagers and you share this shape."""
    name: str
    x: int
    y: int
    facing: str = "south"
    carrying: list = field(default_factory=list)   # entity dicts
    said: str = ""
    said_until: float = 0.0
    sleeping: bool = False

    def say(self, text: str, seconds: float = 7.0):
        self.said, self.said_until = text[:200], time.time() + seconds


class World:
    def __init__(self, seed: int | None = None):
        self.rng = random.Random(seed)
        self.terrain = [[GRASS] * W for _ in range(H)]
        self.region = [["meadow"] * W for _ in range(H)]
        self.terrain_v = self.rng.randrange(1 << 30)
        self.entities: dict[int, dict] = {}
        self.next_id = 1
        self.anchors: dict[str, tuple[int, int]] = {}   # where to stand to "be at" a place
        self.dirty: set[int] = set()
        self.removed: set[int] = set()
        self.log: list[str] = []
        # time
        self.tick_n = 0
        self.day = 1
        self.phase = "day"
        self.phase_t = 0.0          # seconds into the current phase
        self.weather = "clear"
        self.weather_left = 180.0
        self.trees_chopped: dict[tuple[int, int], int] = {}
        self._generate()
        hx, hy = self.anchors["home"]
        self.ada = Being("Ada", hx, hy)
        self.needs = {n: 75.0 for n in NEEDS}
        self.visited: set[str] = set()
        self.firsts: set[str] = set()
        self.read_books: set[int] = set()
        # villagers work a few steps inside their buildings so they never block the door
        self.posts = {n: (self.anchors[p["home"]][0], self.anchors[p["home"]][1] + (-2 if p["home"] != "workshop" else 2))
                      for n, p in NPCS.items()}
        self.people = {n: Being(n, *self.posts[n]) for n in NPCS}
        self.visitor: Being | None = None
        self.heard: list[tuple[float, str, str]] = []   # (time, who, words) said near Ada

    # ================================================================== generation
    def _rect(self, x0, y0, x1, y1, t, region=None):
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                if 0 <= x < W and 0 <= y < H:
                    self.terrain[y][x] = t
                    if region:
                        self.region[y][x] = region

    def _building(self, name, x0, y0, x1, y1, door):
        self._rect(x0, y0, x1, y1, WALL, name)
        self._rect(x0 + 1, y0 + 1, x1 - 1, y1 - 1, FLOOR, name)
        dx, dy = door
        self.terrain[dy][dx] = DOOR
        self.region[dy][dx] = name
        inside = (dx, dy + 1) if dy == y0 else (dx, dy - 1)
        self.anchors[name] = inside

    def _path(self, a, b):
        (x, y), (tx, ty) = a, b
        while (x, y) != (tx, ty):
            if self.terrain[y][x] in (GRASS, FLOWERS, SAND):
                self.terrain[y][x] = PATH
            if x != tx and (y == ty or self.rng.random() < 0.6):
                x += 1 if tx > x else -1
            else:
                y += 1 if ty > y else -1

    def _generate(self):
        r = self.rng
        # regions of open land
        for y in range(H):
            for x in range(W):
                if y >= 23 and x <= 22:
                    self.region[y][x] = "forest"
                elif 13 <= x <= 23 and 2 <= y <= 10:
                    self.region[y][x] = "orchard"
                elif x >= 30 and 3 <= y <= 20:
                    self.region[y][x] = "village"
        # lake
        cx, cy = 49, 30
        for y in range(H):
            for x in range(W):
                d = math.hypot((x - cx) / 10.5, (y - cy) / 6.5)
                if d < 1.0:
                    self.terrain[y][x], self.region[y][x] = WATER, "lake"
                elif d < 1.25:
                    self.terrain[y][x], self.region[y][x] = SAND, "lake"
        # forest
        for y in range(23, H):
            for x in range(0, 23):
                if r.random() < 0.42 and not (8 <= x <= 11):
                    self.terrain[y][x] = TREE
        # orchard: rows of apple trees
        for y in range(3, 11, 3):
            for x in range(14, 24, 3):
                self.terrain[y][x] = TREE
        # meadow flowers and a few rocks
        for _ in range(60):
            x, y = r.randrange(12, 30), r.randrange(11, 23)
            if self.terrain[y][x] == GRASS:
                self.terrain[y][x] = FLOWERS
        for _ in range(14):
            x, y = r.randrange(W), r.randrange(H)
            if self.terrain[y][x] == GRASS and self.region[y][x] in ("meadow", "forest"):
                self.terrain[y][x] = ROCK
        # buildings
        self._building("home", 3, 3, 10, 9, (6, 9))
        self._rect(3, 12, 10, 16, SOIL, "garden")
        self.anchors["garden"] = (6, 11)
        self._building("bakery", 32, 3, 38, 8, (35, 8))
        self._building("library", 45, 3, 52, 8, (48, 8))
        self._building("workshop", 32, 14, 38, 19, (35, 14))
        self._building("shrine", 45, 14, 50, 19, (47, 14))
        self._building("observatory", 56, 2, 62, 8, (59, 8))
        self._rect(39, 9, 44, 13, PATH, "village")   # the square
        # paths between places
        for a, b in [((6, 10), (39, 11)), ((35, 9), (39, 10)), ((48, 9), (44, 10)), ((35, 13), (39, 12)),
                     ((47, 13), (44, 12)), ((59, 9), (44, 9)), ((42, 14), (44, 22)), ((6, 17), (9, 24)),
                     ((22, 15), (39, 12))]:
            self._path(a, b)
        self.anchors.update({"village": (41, 11), "meadow": (22, 16), "orchard": (18, 7), "forest": (10, 30),
                             "lake": (42, 24)})
        for name, (x, y) in list(self.anchors.items()):
            if self.terrain[y][x] in BLOCKING:
                self.terrain[y][x] = PATH
        # furniture and fixtures
        for kind, x, y in [("bed", 4, 4), ("lamp", 9, 4), ("music box", 4, 8), ("chest", 9, 8), ("bucket", 8, 8),
                           ("oven", 33, 4), ("bread", 37, 5), ("bread", 36, 4),
                           ("book", 46, 4), ("book", 47, 4), ("book", 49, 4), ("book", 51, 4), ("book", 46, 7),
                           ("workbench", 33, 15), ("axe", 37, 15), ("seed", 34, 18), ("seed", 33, 18),
                           ("shrine", 47, 18), ("telescope", 59, 3), ("well", 42, 10), ("fire pit", 40, 12),
                           ("bucket", 43, 10), ("coin", 41, 13), ("coin", 44, 9), ("sign", 39, 9),
                           ("seed", 4, 13), ("seed", 8, 15), ("ball", 22, 17), ("cat", 6, 6), ("dog", 41, 12),
                           ("bird", 20, 14), ("bird", 26, 18), ("fish", 47, 29), ("fish", 52, 31)]:
            extra = {"text": "Welcome to the village! The well gives water. The Oracle answers questions."} \
                if kind == "sign" else {}
            self.add(kind, x, y, **extra)
        for _ in range(6):
            self.spawn_near("apple", "orchard")
        for kind, n in (("berry", 5), ("mushroom", 5), ("wood", 4)):
            for _ in range(n):
                self.spawn_near(kind, "forest")
        for _ in range(5):
            self.spawn_near("stone", "lake", on=SAND)
        for _ in range(5):
            self.spawn_near("flower", "meadow")

    def add(self, kind: str, x: int, y: int, **state) -> dict:
        e = {"id": self.next_id, "kind": kind, "x": x, "y": y, **state}
        self.entities[self.next_id] = e
        self.dirty.add(self.next_id)
        self.next_id += 1
        return e

    def remove(self, e: dict):
        if self.entities.pop(e["id"], None) is not None:
            self.removed.add(e["id"])
            self.dirty.discard(e["id"])

    def touch(self, e: dict):
        if e["id"] in self.entities:
            self.dirty.add(e["id"])

    def spawn_near(self, kind: str, region: str, on: int | None = None) -> dict | None:
        cells = [(x, y) for y in range(H) for x in range(W)
                 if self.region[y][x] == region and self.walkable(x, y)
                 and (on is None or self.terrain[y][x] == on) and not self.at(x, y)]
        if not cells:
            return None
        return self.add(kind, *self.rng.choice(cells))

    # ================================================================== geometry
    def walkable(self, x, y) -> bool:
        return 0 <= x < W and 0 <= y < H and self.terrain[y][x] not in BLOCKING

    def at(self, x, y) -> list[dict]:
        return [e for e in self.entities.values() if e["x"] == x and e["y"] == y]

    def place_of(self, x, y) -> str:
        return self.region[y][x]

    def occupied(self, x, y, me: Being | None = None) -> bool:
        for b in self.beings():
            if b is not me and (b.x, b.y) == (x, y):
                return True
        return False

    def beings(self) -> list[Being]:
        out = [self.ada] + list(self.people.values())
        if self.visitor:
            out.append(self.visitor)
        return out

    def path(self, start, goal, me: Being | None = None, adjacent: bool = False, limit: int = 4000,
             avoid: bool = True):
        """A* over the grid. With adjacent=True, stop next to the goal (for things you can't stand on).
        With avoid=False, people are not obstacles (they step aside when you reach them)."""
        sx, sy = start
        gx, gy = goal
        if adjacent and abs(sx - gx) + abs(sy - gy) == 1:
            return []
        if not adjacent and (sx, sy) == (gx, gy):
            return []
        openq = [(abs(sx - gx) + abs(sy - gy), 0, (sx, sy))]
        came = {(sx, sy): None}
        cost = {(sx, sy): 0}
        while openq and len(came) < limit:
            _, g, cur = heapq.heappop(openq)
            cx, cy = cur
            done = (abs(cx - gx) + abs(cy - gy) == 1) if adjacent else (cur == (gx, gy))
            if done:
                out = []
                while cur != (sx, sy):
                    out.append(cur)
                    cur = came[cur]
                return out[::-1]
            for dx, dy in DIRS.values():
                nx, ny = cx + dx, cy + dy
                if not self.walkable(nx, ny) or (nx, ny) in cost and cost[(nx, ny)] <= g + 1:
                    continue
                if avoid and self.occupied(nx, ny, me) and (nx, ny) != (gx, gy):
                    continue
                cost[(nx, ny)] = g + 1
                came[(nx, ny)] = cur
                heapq.heappush(openq, (g + 1 + abs(nx - gx) + abs(ny - gy), g + 1, (nx, ny)))
        return None

    def nearest(self, kinds, frm: tuple[int, int], where=None) -> dict | None:
        kinds = {kinds} if isinstance(kinds, str) else set(kinds)
        best, bd = None, 1e9
        for e in self.entities.values():
            if e["kind"] in kinds and (where is None or where(e)):
                d = abs(e["x"] - frm[0]) + abs(e["y"] - frm[1])
                if d < bd:
                    best, bd = e, d
        return best

    def nearest_tile(self, kind: int, frm, need_neighbour_walkable=True):
        best, bd = None, 1e9
        for y in range(H):
            for x in range(W):
                if self.terrain[y][x] == kind:
                    if need_neighbour_walkable and not any(self.walkable(x + dx, y + dy) for dx, dy in DIRS.values()):
                        continue
                    d = abs(x - frm[0]) + abs(y - frm[1])
                    if d < bd:
                        best, bd = (x, y), d
        return best

    # ================================================================== time, weather, seasons
    @property
    def season(self) -> str:
        return SEASONS[((self.day - 1) // 3) % 4]

    def time_of_day(self, day_seconds: float) -> str:
        if self.phase == "night":
            return "night"
        f = self.phase_t / max(day_seconds, 1)
        return "dawn" if f < 0.1 else "morning" if f < 0.4 else "noon" if f < 0.55 else \
            "afternoon" if f < 0.85 else "evening"

    def light(self, day_seconds: float) -> float:
        if self.phase == "night":
            return 0.25
        f = self.phase_t / max(day_seconds, 1)
        if f < 0.1:            # dawn brightens
            return 0.55 + 0.45 * f / 0.1
        if f > 0.85:           # evening dims
            return 0.55 + 0.45 * max(0.0, 1 - f) / 0.15
        return 1.0

    def temperature(self) -> float:
        t = {"spring": 14, "summer": 24, "autumn": 11, "winter": 1}[self.season]
        t -= 8 if self.phase == "night" else 0
        t -= 4 if self.weather in ("rain", "snow") else 0
        return t

    def advance(self, dt: float):
        """Weather, growth, regrowth and the animals: everything that happens on its own."""
        self.tick_n += 1
        self.phase_t += dt
        self.weather_left -= dt
        r = self.rng
        if self.weather_left <= 0:
            opts = ["clear", "clear", "cloudy", "rain"] if self.season != "winter" else ["clear", "cloudy", "snow"]
            self.weather = r.choice(opts)
            self.weather_left = r.uniform(120, 360)
        if self.tick_n % 4:
            return
        counts: dict[str, int] = {}
        for e in list(self.entities.values()):
            counts[e["kind"]] = counts.get(e["kind"], 0) + 1
            k = e["kind"]
            if k == "sprout":
                e["growth"] = e.get("growth", 0) + (2 if e.get("watered") or self.weather == "rain" else 0.5)
                if e["growth"] >= 100:
                    e["kind"], e["growth"] = "wheat", None
                self.touch(e)
            elif k == "fire pit" and e.get("lit"):
                e["lit"] -= 1
                if e["lit"] <= 0:
                    e["lit"] = 0
                    self.note("The fire in the fire pit goes out.")
                self.touch(e)
            elif KINDS.get(k, {}).get("creature"):
                self._wander(e)
        for kind, region, cap in (("apple", "orchard", 6), ("berry", "forest", 5), ("mushroom", "forest", 5),
                                  ("wood", "forest", 3), ("stone", "lake", 4), ("flower", "meadow", 6),
                                  ("coin", "village", 3)):
            if counts.get(kind, 0) < cap and r.random() < 0.02:
                self.spawn_near(kind, region, on=SAND if kind == "stone" else None)
        for name, p in self.people.items():
            self._villager(name, p)

    def _wander(self, e: dict):
        r = self.rng
        k = e["kind"]
        if k == "fish":
            dx, dy = r.choice(list(DIRS.values()))
            nx, ny = e["x"] + dx, e["y"] + dy
            if 0 <= nx < W and 0 <= ny < H and self.terrain[ny][nx] == WATER:
                e["x"], e["y"] = nx, ny
                self.touch(e)
            return
        if k == "dog" and r.random() < 0.4:   # dogs like company
            a = self.ada
            if abs(a.x - e["x"]) + abs(a.y - e["y"]) > 3:
                p = self.path((e["x"], e["y"]), (a.x, a.y), adjacent=True, limit=400)
                if p:
                    e["x"], e["y"] = p[0]
                    self.touch(e)
                return
        if r.random() < (0.7 if k == "bird" else 0.3):
            dx, dy = r.choice(list(DIRS.values()))
            nx, ny = e["x"] + dx, e["y"] + dy
            if self.walkable(nx, ny) and not self.occupied(nx, ny) and self.terrain[ny][nx] != DOOR:
                e["x"], e["y"] = nx, ny
                self.touch(e)

    def _villager(self, name: str, p: Being):
        home = self.posts[name]
        if self.phase == "night":
            p.sleeping = True
            target = home
        else:
            p.sleeping = False
            # most of the day at work, with walks to the village square
            target = home if (self.day + self.tick_n // 600 + sum(map(ord, name))) % 3 else self.anchors["village"]
        if (p.x, p.y) != target and self.rng.random() < 0.5:
            route = self.path((p.x, p.y), target, me=p, limit=1500)
            if route:
                nx, ny = route[0]
                p.facing = _facing(p.x, p.y, nx, ny)
                p.x, p.y = nx, ny

    def note(self, text: str):
        self.log.append(text)
        del self.log[:-40]

    # ================================================================== senses
    def _rel(self, x, y) -> str:
        a = self.ada
        dx, dy = x - a.x, y - a.y
        if dx == 0 and dy == 0:
            return "here"
        parts = []
        if dy:
            parts.append(f"{abs(dy)} {'north' if dy < 0 else 'south'}")
        if dx:
            parts.append(f"{abs(dx)} {'west' if dx < 0 else 'east'}")
        return " and ".join(parts)

    def feelings(self) -> list[str]:
        n = self.needs
        out = []
        for need, low, word in (("energy", 35, "hungry"), ("water", 35, "thirsty"), ("rest", 25, "tired"),
                                ("warmth", 35, "cold"), ("company", 30, "lonely"), ("fun", 30, "bored")):
            if n[need] < low:
                out.append(("very " if n[need] < low / 2 else "") + word)
        if not out and min(n.values()) > 70:
            out.append("happy")
        return out

    def perceive(self, day_seconds: float, radius: int = 7) -> str:
        """Everything Ada senses, in her own words."""
        a = self.ada
        place = self.place_of(a.x, a.y)
        s = [f"It is {self.time_of_day(day_seconds)} on day {self.day}, in {self.season}. "
             f"The weather is {self.weather}. I am {where(place)}."]
        f = self.feelings()
        s.append("I feel " + " and ".join(f) + "." if f else "I feel fine.")
        if a.carrying:
            s.append("I carry " + _and([KINDS[e["kind"]]["noun"] for e in a.carrying]) + ".")
        seen = []
        for e in sorted(self.entities.values(), key=lambda e: abs(e["x"] - a.x) + abs(e["y"] - a.y)):
            d = abs(e["x"] - a.x) + abs(e["y"] - a.y)
            if d > radius or len(seen) >= 4:
                break
            k = e["kind"]
            label = KINDS[k]["noun"] + (" that is burning" if k == "fire pit" and e.get("lit") else "")
            seen.append(f"{label} {self._rel(e['x'], e['y'])}")
        if seen:
            s.append("I see " + "; ".join(seen) + ".")
        for b in self.beings()[1:]:
            d = abs(b.x - a.x) + abs(b.y - a.y)
            if d <= radius:
                who = "my friend" if b is self.visitor else f"{b.name} the {NPCS[b.name]['role']}"
                s.append(f"{_cap(who)} is {'right next to me' if d == 1 else self._rel(b.x, b.y)}.")
        now = time.time()
        for t, who, words in self.heard[-2:]:
            if now - t < 30:
                s.append(f'{_cap(who)} said: "{words}"')
        return " ".join(s)

    def hear(self, who: str, words: str):
        self.heard.append((time.time(), who, words[:200]))
        del self.heard[:-6]

    # ================================================================== needs
    def update_needs(self, dt: float):
        n, a = self.needs, self.ada
        indoors = self.terrain[a.y][a.x] in (FLOOR, DOOR)
        near_fire = any(e["kind"] == "fire pit" and e.get("lit") and abs(e["x"] - a.x) + abs(e["y"] - a.y) <= 3
                        for e in self.entities.values())
        k = dt / 0.25
        n["energy"] -= (0.03 if a.sleeping else 0.07) * k
        n["water"] -= (0.03 if a.sleeping else 0.09) * k
        n["rest"] += (0.5 if a.sleeping else -0.04) * k
        warm_target = 22 if (indoors or near_fire) else self.temperature()
        n["warmth"] += (0.25 if warm_target >= 12 else -0.12 * (12 - warm_target) / 12) * k
        n["company"] -= 0.04 * k
        n["fun"] -= (0.0 if a.sleeping else 0.05) * k
        for key in n:
            n[key] = max(0.0, min(100.0, n[key]))

    def wellbeing(self) -> float:
        return sum(min(v, 80) for v in self.needs.values()) / (80 * len(self.needs))

    # ================================================================== you
    def join(self) -> Being:
        if not self.visitor:
            a = self.ada
            for r in range(1, 12):
                spots = [(a.x + dx, a.y + dy) for dx in range(-r, r + 1) for dy in range(-r, r + 1)
                         if abs(dx) + abs(dy) == r]
                spots = [s for s in spots if self.walkable(*s) and not self.occupied(*s)]
                if spots:
                    self.visitor = Being("you", *spots[0])
                    break
            self.note("My friend arrives!")
        return self.visitor

    def leave(self):
        v = self.visitor
        if v:
            for e in v.carrying:
                e["x"], e["y"] = v.x, v.y
                self.entities[e["id"]] = e
                self.touch(e)
            self.note("My friend waves goodbye and leaves.")
        self.visitor = None

    # ================================================================== serialisation
    def snapshot(self, full: bool = False, day_seconds: float = 600.0) -> dict:
        def being(b: Being | None):
            if b is None:
                return None
            return {"name": b.name, "x": b.x, "y": b.y, "facing": b.facing, "sleeping": b.sleeping,
                    "carrying": [e["kind"] for e in b.carrying],
                    "said": b.said if time.time() < b.said_until else ""}

        out = {
            "tick": self.tick_n, "day": self.day, "phase": self.phase, "season": self.season,
            "weather": self.weather, "time": self.time_of_day(day_seconds), "light": round(self.light(day_seconds), 3),
            "temperature": self.temperature(), "terrain_v": self.terrain_v,
            "ada": being(self.ada) | {"place": self.place_of(self.ada.x, self.ada.y),
                                       "needs": {k: round(v, 1) for k, v in self.needs.items()},
                                       "feelings": self.feelings()},
            "visitor": being(self.visitor),
            "people": [being(p) | {"role": NPCS[n]["role"]} for n, p in self.people.items()],
            "log": self.log[-14:],
        }
        if full:
            out["full"] = True
            out["terrain"] = self.terrain
            out["regions"] = self.region
            out["places"] = {k: list(v) for k, v in self.anchors.items()}
            out["ents"] = list(self.entities.values())
            out["removed"] = []
            self.dirty.clear()
            self.removed.clear()
        else:
            out["ents"] = [self.entities[i] for i in self.dirty if i in self.entities]
            out["removed"] = list(self.removed)
            self.dirty.clear()
            self.removed.clear()
        return out

    def state(self) -> dict:
        a = self.ada
        return {"terrain": self.terrain, "entities": list(self.entities.values()), "next_id": self.next_id,
                "tick": self.tick_n, "day": self.day, "phase": self.phase, "phase_t": self.phase_t,
                "weather": self.weather, "needs": self.needs, "visited": sorted(self.visited),
                "firsts": sorted(self.firsts), "read": sorted(self.read_books), "ada": {"x": a.x, "y": a.y, "carrying": a.carrying,
                                                       "sleeping": a.sleeping}}

    def load_state(self, s: dict):
        self.terrain = s["terrain"]
        self.terrain_v += 1
        self.entities = {e["id"]: e for e in s["entities"]}
        self.next_id, self.tick_n, self.day = s["next_id"], s["tick"], s["day"]
        self.phase, self.phase_t, self.weather = s["phase"], s["phase_t"], s["weather"]
        self.needs.update(s["needs"])
        self.visited, self.firsts = set(s["visited"]), set(s["firsts"])
        self.read_books = set(s.get("read", []))
        a = s["ada"]
        self.ada.x, self.ada.y, self.ada.carrying, self.ada.sleeping = a["x"], a["y"], a["carrying"], a["sleeping"]


def where(place: str) -> str:
    """'home' -> 'at home', 'lake' -> 'by the lake', 'bakery' -> 'in the bakery'."""
    return {"home": "at home", "lake": "by the lake", "shrine": "at the shrine"}.get(place, f"in the {place}")


def _facing(x, y, nx, ny) -> str:
    return "east" if nx > x else "west" if nx < x else "south" if ny > y else "north"


def _and(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]
