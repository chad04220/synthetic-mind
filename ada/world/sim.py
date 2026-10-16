"""The World the synth lives in: a valley between mountains and a lake.

North are the mountains, with an old mine full of ore and crystals and a snowy peak. A river runs
from them through the valley to a big lake with a beach and Finn's dock. In the middle is the
village: a plaza with a well and a fire pit, the bakery, the library, the school, the workshop and
forge, the market, the music hall, the painting studio, a park with swings and a frog pond, and
the Oracle's shrine on its hill. West is the synth's cottage with its farm (fields, a barn, a
chicken coop and a pasture) and an apple orchard; east is a wide meadow with beehives and the
observatory; south-west is a deep forest.

Time passes in days and nights (nights are when the synth sleeps and the Academy can study),
seasons turn every few days and the weather changes. The synth has six needs, a purse of coins,
friendships with the seven villagers and the quests they ask of it. Everything it can sense is
written in plain first-person sentences, and everything it can do is a verb with an object, so its
own words can drive what it does.
"""
from __future__ import annotations

import heapq
import math
import random
import time
from dataclasses import dataclass, field

from ..ontology import KINDS, NPCS

W, H = 128, 96
(GRASS, WATER, SAND, TREE, ROCK, FLOWERS, PATH, FLOOR, WALL, DOOR, SOIL, BRIDGE, PLAZA, CLIFF, SNOW,
 FENCE, DOCK, TALLGRASS, PINE, CAVE) = range(20)
TERRAIN = ["grass", "water", "sand", "a tree", "a rock", "flowers", "a path", "a floor", "a wall", "a door",
           "soil", "a bridge", "paving stones", "a cliff", "snow", "a fence", "a dock", "tall grass", "a pine tree",
           "the cave floor"]
BLOCKING = {WATER, TREE, ROCK, WALL, CLIFF, FENCE, PINE}
INDOORS = {FLOOR, DOOR, CAVE}
SEASONS = ["spring", "summer", "autumn", "winter"]
DIRS = {"north": (0, -1), "south": (0, 1), "west": (-1, 0), "east": (1, 0)}
NEEDS = ["energy", "water", "rest", "warmth", "company", "fun"]
WEATHER = {"spring": ["clear", "clear", "cloudy", "rain", "windy", "fog"],
           "summer": ["clear", "clear", "clear", "cloudy", "windy", "rain"],
           "autumn": ["clear", "cloudy", "rain", "windy", "fog", "rain"],
           "winter": ["clear", "cloudy", "snow", "snow", "fog"]}

# Buildings: name, label, rectangle (x0, y0, x1, y1), door, wall, roof and floor colours.
BUILDINGS = [
    ("home", "Cottage", (8, 34, 17, 41), (12, 41), "#e8d5b5", "#b5543c", "#a47148"),
    ("barn", "Barn", (28, 46, 35, 52), (28, 49), "#b23a2e", "#5c2a22", "#8d6a4a"),
    ("bakery", "Mira's Bakery", (43, 27, 50, 33), (47, 33), "#f2d0a4", "#c0563b", "#a0754d"),
    ("library", "Theo's Library", (53, 26, 61, 33), (57, 33), "#cdb4db", "#5e548e", "#8d6a4a"),
    ("school", "Sage's School", (64, 27, 72, 33), (68, 33), "#ffe5a0", "#3d5a80", "#a47148"),
    ("workshop", "Rowan's Workshop", (39, 39, 46, 46), (46, 42), "#a3b18a", "#3a5a40", "#7f6a5a"),
    ("music hall", "Music Hall", (50, 49, 57, 55), (53, 49), "#ffd6e0", "#9d4edd", "#a47148"),
    ("studio", "Painting Studio", (61, 49, 67, 54), (64, 49), "#bde0fe", "#2a6f97", "#a47148"),
    ("shrine", "The Oracle's Shrine", (55, 17, 61, 22), (58, 22), "#e0d1ff", "#5a189a", "#c8b6ff"),
    ("observatory", "Observatory", (107, 15, 114, 21), (110, 21), "#dee2e6", "#495057", "#adb5bd"),
    ("boathouse", "Finn's Boathouse", (84, 64, 89, 68), (86, 68), "#caf0f8", "#03045e", "#8d6a4a"),
]


@dataclass
class Being:
    """The synth, the villagers and you share this shape."""
    name: str
    x: int
    y: int
    facing: str = "south"
    carrying: list = field(default_factory=list)   # entity dicts
    said: str = ""
    said_until: float = 0.0
    sleeping: bool = False
    fx: float | None = None                        # continuous position (only you)
    fy: float | None = None
    route: list = field(default_factory=list)
    goal: tuple | None = None
    engaged: int | None = None                     # in a conversation (its id): stays put, faces the other
    needs: dict = field(default_factory=lambda: {n: 75.0 for n in NEEDS})
    coins: int = 3
    friends: dict = field(default_factory=dict)    # name -> 0..100
    role: str = ""                                 # "synth", a villager's job, or "visitor"

    def say(self, text: str, seconds: float = 8.0):
        self.said, self.said_until = text[:220], time.time() + seconds


def _noise(seed: int):
    """Smooth 2-D value noise in [0, 1]."""
    rng = random.Random(seed)
    n = 64
    grid = [[rng.random() for _ in range(n)] for _ in range(n)]

    def f(x: float, y: float) -> float:
        gx, gy = x / 8, y / 8
        x0, y0 = int(gx), int(gy)
        tx, ty = gx - x0, gy - y0
        tx, ty = tx * tx * (3 - 2 * tx), ty * ty * (3 - 2 * ty)
        x0, y0, x1, y1 = x0 % n, y0 % n, (x0 + 1) % n, (y0 + 1) % n
        a = grid[y0][x0] * (1 - tx) + grid[y0][x1] * tx
        b = grid[y1][x0] * (1 - tx) + grid[y1][x1] * tx
        return a * (1 - ty) + b * ty
    return f


def ridge(x: int) -> int:
    """Where the mountains end, going south."""
    return int(13 + 2.5 * math.sin(x / 9.0) + 1.5 * math.sin(x / 4.3))


def river_x(y: int) -> int:
    bend = max(0, y - 58) * 0.8                    # it turns east, into the lake
    return int(80 + 4 * math.sin(y / 7.0) + 2 * math.sin(y / 3.1) + bend)


class World:
    def __init__(self, seed: int | None = 7, name: str = "Zen"):
        self.rng = random.Random()
        self.seed = seed
        self.name = name
        self.terrain = [[GRASS] * W for _ in range(H)]
        self.height = [[0] * W for _ in range(H)]
        self.region = [["meadow"] * W for _ in range(H)]
        self.terrain_v = random.randrange(1 << 30)
        self.entities: dict[int, dict] = {}
        self.next_id = 1
        self.anchors: dict[str, tuple[int, int]] = {}   # where to stand to "be at" a place
        self.buildings: list[dict] = []
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
        self._generate(random.Random(seed))
        hx, hy = self.anchors["home"]
        self.ada = Being(name, hx, hy, role="synth", friends={n: 10.0 for n in NPCS})
        self.visited: set[str] = set()
        self.firsts: set[str] = set()
        self.read_books: set[int] = set()
        self.quests: list[dict] = []
        self.quest_seq = 1
        self.done_quests = 0
        self.creations: list[dict] = []                   # the valley's gallery: everything anyone made
        self.new_creations: list[dict] = []               # not yet sent to the browser
        self.people = {}
        r = random.Random(seed)
        for n, p in NPCS.items():
            b = Being(n, *self.posts[n], role=p["role"], coins=12 + r.randrange(10))
            b.friends = {m: 30.0 + r.randrange(30) for m in NPCS if m != n} | {name: 10.0}
            b.needs = {k: 60.0 + r.randrange(35) for k in NEEDS}
            self.people[n] = b
        self.visitor: Being | None = None
        self.heard: list[tuple[float, str, str]] = []   # (time, who, words) said near the synth

    # ================================================================== generation
    def _set(self, x, y, t, region=None, h=None):
        if 0 <= x < W and 0 <= y < H:
            self.terrain[y][x] = t
            if region:
                self.region[y][x] = region
            if h is not None:
                self.height[y][x] = h

    def _rect(self, x0, y0, x1, y1, t, region=None, h=None):
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                self._set(x, y, t, region, h)

    def _building(self, name, label, rect, door, wall, roof, floor):
        x0, y0, x1, y1 = rect
        h = self.height[door[1]][door[0]]
        self._rect(x0 - 1, y0 - 1, x1 + 1, y1 + 1, GRASS, None, h)   # a level lot with a margin
        self._rect(x0, y0, x1, y1, WALL, name, h)
        self._rect(x0 + 1, y0 + 1, x1 - 1, y1 - 1, FLOOR, name, h)
        dx, dy = door
        self._set(dx, dy, DOOR, name, h)
        if dy == y1:
            inside, outside = (dx, dy - 1), (dx, dy + 1)
        elif dy == y0:
            inside, outside = (dx, dy + 1), (dx, dy - 1)
        elif dx == x0:
            inside, outside = (dx + 1, dy), (dx - 1, dy)
        else:
            inside, outside = (dx - 1, dy), (dx + 1, dy)
        self.anchors[name] = inside
        self.buildings.append({"name": name, "label": label, "x0": x0, "y0": y0, "x1": x1, "y1": y1,
                               "door": [dx, dy], "outside": list(outside), "wall": wall, "roof": roof, "floor": floor})
        return outside

    def _path(self, a, b, kind=PATH):
        """A winding path from a to b; over water it becomes a bridge."""
        (x, y), (tx, ty) = a, b
        r = self._prng
        while (x, y) != (tx, ty):
            t = self.terrain[y][x]
            if t == WATER:
                self.terrain[y][x] = BRIDGE
            elif t in (GRASS, FLOWERS, SAND, TALLGRASS, TREE, PINE, ROCK, CLIFF, SNOW):
                self.terrain[y][x] = kind
            if x != tx and (y == ty or r.random() < 0.55):
                x += 1 if tx > x else -1
            else:
                y += 1 if ty > y else -1

    def _generate(self, r: random.Random):
        self._prng = r
        hills, detail = _noise(r.randrange(1 << 30)), _noise(r.randrange(1 << 30))
        # ---- land: heights and broad regions
        for y in range(H):
            for x in range(W):
                rg = ridge(x)
                h = hills(x, y) * 2.2 + detail(x * 2, y * 2) * 0.6
                if y < rg + 6:                              # foothills rise towards the mountains
                    h += (rg + 6 - y) * 0.55
                if x > 98 and y < 30:                       # the observatory's hill
                    h += max(0.0, 3.2 - math.hypot(x - 110, y - 19) * 0.3)
                if 52 <= x <= 64 and 15 <= y <= 25:         # the shrine's hill
                    h += max(0.0, 2.0 - math.hypot(x - 58, y - 20) * 0.25)
                self.height[y][x] = max(0, min(8, int(h)))
                if y < rg:
                    self.region[y][x] = "mountains"
                elif y >= 62 and x <= 46:
                    self.region[y][x] = "forest"
                elif x <= 34 and 16 <= y <= 31:
                    self.region[y][x] = "orchard"
                elif x <= 38 and 43 <= y <= 62:
                    self.region[y][x] = "farm"
                elif 38 <= x <= 76 and 24 <= y <= 57:
                    self.region[y][x] = "village"
                elif 46 <= x <= 76 and 57 < y <= 72:
                    self.region[y][x] = "park"
                else:
                    self.region[y][x] = "meadow"
        # ---- mountains: cliffs, snow and a few walkable shelves
        for x in range(W):
            rg = ridge(x)
            for y in range(0, rg):
                depth = rg - y
                if depth <= 2:
                    t = ROCK if r.random() < 0.25 else GRASS
                elif depth <= 7:
                    t = CLIFF
                else:
                    t = SNOW if r.random() < 0.92 else CLIFF
                self._set(x, y, t, "mountains", min(8, 3 + depth // 2))
        # the mine, dug into the mountain
        for y in range(4, 12):
            for x in range(30, 44):
                if 31 <= x <= 42 and 5 <= y <= 11:
                    self._set(x, y, CAVE, "mine", 3)
        # a trail up to the snowy peak
        for y in range(1, ridge(96) + 2):
            self._set(96, y, PATH, None, None)
            self._set(97, y, PATH, None, None)
        # ---- the river and the lake
        lake_c = (101, 79)
        for y in range(ridge(80) - 2, H):
            cx = river_x(y)
            wid = 1 if y < 40 else 2
            if math.hypot((cx - lake_c[0]) / 21, (y - lake_c[1]) / 12) < 1.0:
                break
            for x in range(cx - wid + 1, cx + wid + 1):
                self._set(x, y, WATER, "river", 0)
            for x in (cx - wid, cx + wid + 1):
                if self.terrain[y][x] not in (WATER,) and r.random() < 0.6:
                    self._set(x, y, SAND, "river", 0)
        for y in range(H):
            for x in range(W):
                d = math.hypot((x - lake_c[0]) / 21, (y - lake_c[1]) / 12)
                if d < 1.0:
                    self._set(x, y, WATER, "lake", 0)
                elif d < 1.22:
                    self._set(x, y, SAND, "lake", 0)
                elif d < 1.6:
                    self.height[y][x] = min(self.height[y][x], 1)
        # the frog pond in the park
        for y in range(63, 67):
            for x in range(66, 72):
                if math.hypot((x - 68.5) / 3.2, (y - 64.5) / 2.2) < 1:
                    self._set(x, y, WATER, "park", 0)
        # ---- the village: flatten it, then the plaza and the market
        for y in range(24, 58):
            for x in range(38, 77):
                if self.terrain[y][x] == GRASS:
                    self.height[y][x] = 0 if y > 26 else self.height[y][x]
        self._rect(49, 36, 63, 45, PLAZA, "village", 0)
        self._rect(65, 37, 74, 45, PLAZA, "market", 0)
        # ---- buildings (and paths from their doors)
        doors = {}
        for name, label, rect, door, wall, roof, floor in BUILDINGS:
            doors[name] = self._building(name, label, rect, door, wall, roof, floor)
        # ---- the farm: fenced fields, a pen and the coop
        self._rect(6, 46, 24, 46, FENCE, "farm")
        self._rect(6, 46, 6, 58, FENCE, "farm")
        self._rect(6, 58, 24, 58, FENCE, "farm")
        self._rect(24, 46, 24, 58, FENCE, "farm")
        self._set(15, 46, PATH, "farm")                       # the gate
        for y in range(48, 57):
            for x in range(8, 23):
                if y % 3 != 1:
                    self._set(x, y, SOIL, "farm", 0)
                else:
                    self._set(x, y, PATH, "farm", 0)
        self._rect(27, 55, 37, 55, FENCE, "farm")
        self._rect(27, 55, 27, 62, FENCE, "farm")
        self._rect(27, 62, 37, 62, FENCE, "farm")
        self._rect(37, 55, 37, 62, FENCE, "farm")
        self._set(32, 55, PATH, "farm")
        self._rect(28, 56, 36, 61, GRASS, "farm", 0)
        # ---- the orchard: rows of apple trees
        for y in range(18, 31, 3):
            for x in range(6, 33, 3):
                if self.terrain[y][x] == GRASS:
                    self._set(x, y, TREE, "orchard")
        # ---- the forest
        for y in range(62, H):
            for x in range(0, 47):
                if self.terrain[y][x] != GRASS:
                    continue
                clearing = math.hypot(x - 24, y - 79) < 5
                trail = abs(x - 14 - (y - 62) // 6) <= 1
                if not clearing and not trail and r.random() < 0.46:
                    self._set(x, y, PINE if r.random() < 0.45 else TREE, "forest")
        # ---- meadow flowers, tall grass, rocks and scattered trees
        for _ in range(420):
            x, y = r.randrange(W), r.randrange(H)
            if self.terrain[y][x] == GRASS and self.region[y][x] in ("meadow", "park", "orchard"):
                self._set(x, y, FLOWERS if r.random() < 0.55 else TALLGRASS)
        for _ in range(140):
            x, y = r.randrange(W), r.randrange(H)
            if self.terrain[y][x] == GRASS and self.region[y][x] in ("meadow", "forest", "mountains"):
                self._set(x, y, ROCK if r.random() < 0.3 else (TREE if r.random() < 0.6 else PINE))
        for _ in range(160):
            x, y = r.randrange(0, 47), r.randrange(62, H)
            if self.terrain[y][x] == GRASS:
                self._set(x, y, TALLGRASS)
        # the park: lawns, flower beds and a path round the pond
        for y in range(59, 71):
            for x in range(48, 75):
                if self.terrain[y][x] in (TREE, PINE, ROCK):
                    self._set(x, y, GRASS)
        # ---- the dock
        for x in range(81, 88):
            self._set(x, 72, DOCK, "dock", 0)
            self._set(x, 73, DOCK, "dock", 0)
        # ---- paths
        home_out = doors["home"]
        plaza_w, plaza_n, plaza_s, plaza_e = (49, 41), (56, 36), (56, 45), (74, 41)
        for a, b in [(home_out, plaza_w), (doors["barn"], (26, 44)), ((15, 45), (15, 43)), ((15, 43), home_out),
                     (doors["bakery"], (47, 36)), (doors["library"], (57, 36)), (doors["school"], (68, 37)),
                     (doors["workshop"], (49, 42)), (doors["music hall"], (53, 46)),
                     (doors["studio"], (64, 46)), (doors["shrine"], plaza_n), (plaza_e, (90, 41)),
                     ((90, 41), doors["observatory"]), (plaza_s, (58, 60)), ((58, 60), (80, 71)),
                     ((80, 71), doors["boathouse"]), ((15, 59), (14, 63)), ((14, 63), (22, 94)),
                     ((24, 74), (24, 79)), ((32, 59), (32, 56)), ((35, 31), (37, 13)), ((37, 13), (37, 11)),
                     ((20, 31), home_out), ((90, 41), (96, ridge(96) + 1)), ((40, 56), (32, 56)),
                     ((49, 41), (40, 56))]:
            self._path(a, b)
        # the mine's mouth
        for y in range(11, ridge(37) + 1):
            self._set(36, y, CAVE, "mine", 3)
            self._set(37, y, CAVE, "mine", 3)
        # ---- places to stand
        self.anchors.update({"village": (56, 40), "market": (69, 41), "farm": (15, 50), "orchard": (19, 24),
                             "meadow": (100, 45), "forest": (24, 79), "lake": (90, 70), "dock": (86, 72),
                             "river": (river_x(55) - 2, 55), "park": (58, 62), "mine": (36, 8),
                             "mountains": (96, 3)})
        for name, (x, y) in list(self.anchors.items()):
            if self.terrain[y][x] in BLOCKING:
                self._set(x, y, PATH)
        # villagers work a step or two inside their buildings, or at their open-air posts
        self.posts = {}
        for n, p in NPCS.items():
            ax, ay = self.anchors[p["home"]]
            b = next((b for b in self.buildings if b["name"] == p["home"]), None)
            if b:
                cx, cy = (b["x0"] + b["x1"]) // 2, (b["y0"] + b["y1"]) // 2
                spot = (cx, cy) if (cx, cy) != (ax, ay) else (cx + 1, cy)
            else:
                spot = {"Juniper": (70, 40), "Finn": (87, 73), "Pip": (56, 63)}.get(n, (ax, ay))
            self.posts[n] = spot
        # ---- furniture, fixtures and things
        fixed = [("bed", 9, 35), ("lamp", 16, 35), ("music box", 9, 40), ("chest", 16, 40), ("stove", 13, 35),
                 ("bucket", 15, 40), ("cat", 11, 38), ("book", 10, 37),
                 ("oven", 44, 28), ("bread", 49, 28), ("bread", 48, 28),
                 ("book", 54, 27), ("book", 55, 27), ("book", 56, 27), ("book", 59, 27), ("book", 60, 27),
                 ("book", 54, 31), ("blackboard", 68, 28), ("book", 65, 31),
                 ("workbench", 40, 40), ("forge", 40, 45), ("axe", 43, 40), ("pickaxe", 44, 40),
                 ("fishing rod", 45, 44), ("bucket", 42, 45),
                 ("piano", 53, 50), ("easel", 63, 50), ("easel", 65, 52),
                 ("shrine", 58, 18), ("telescope", 110, 16),
                 ("well", 56, 40), ("fire pit", 59, 43), ("bench", 52, 37), ("bench", 61, 37),
                 ("market stall", 67, 38), ("market stall", 71, 38), ("market stall", 67, 44), ("market stall", 73, 44),
                 ("sign", 49, 39), ("sign", 15, 44), ("sign", 37, 14),
                 ("bench", 52, 61), ("bench", 62, 61), ("swing", 54, 66), ("swing", 56, 66), ("ball", 59, 64),
                 ("fire pit", 24, 79), ("beehive", 104, 36), ("beehive", 108, 52), ("beehive", 97, 58),
                 ("fishing rod", 85, 66), ("bucket", 86, 66)]
        texts = {(49, 39): "Welcome to the village! The well gives water. Juniper buys and sells at the market. "
                           "The Oracle answers questions at the shrine on the hill.",
                 (15, 44): "The farm. Plant seeds in the soil, water them, and harvest when they are ripe.",
                 (37, 14): "The old mine. Bring a pickaxe: there is ore and there are crystals inside."}
        for kind, x, y in fixed:
            self.add(kind, x, y, **({"text": texts[(x, y)]} if (x, y) in texts else {}))
        for x, y in [(32, 6), (34, 9), (39, 6), (41, 10), (33, 11)]:
            self.add("ore vein", x, y, left=5)
        for x, y in [(36, 5), (42, 7)]:
            self.add("crystal cluster", x, y, left=3)
        creatures = [("chicken", "farm", 4), ("cow", "farm", 2), ("sheep", "farm", 3), ("dog", "village", 1),
                     ("bird", "meadow", 4), ("butterfly", "meadow", 5), ("rabbit", "forest", 3), ("deer", "forest", 2),
                     ("owl", "forest", 1), ("duck", "lake", 3), ("frog", "park", 2), ("fish", "lake", 6),
                     ("fish", "river", 2)]
        self._index_cells()
        for kind, region, n in creatures:
            for _ in range(n):
                if kind == "fish":
                    self.spawn_near(kind, region, on=WATER)
                elif kind in ("cow", "sheep"):
                    self.add(kind, r.randrange(29, 36), r.randrange(57, 61))
                else:
                    self.spawn_near(kind, region)
        for kind, region, n in (("apple", "orchard", 8), ("berry", "forest", 6), ("mushroom", "forest", 6),
                                ("wood", "forest", 4), ("stone", "lake", 6), ("flower", "meadow", 8),
                                ("seed", "farm", 3), ("egg", "farm", 2), ("coin", "village", 2), ("clay", "river", 3)):
            for _ in range(n):
                self.spawn_near(kind, region, on=SAND if kind in ("stone", "clay") else None)
        del self._prng

    def _index_cells(self):
        """Tiles by region, keeping only those you can walk to from home (and water, for fish)."""
        start = self.anchors["home"]
        seen, todo = {start}, [start]
        while todo:
            x, y = todo.pop()
            for dx, dy in ((0, 1), (1, 0), (0, -1), (-1, 0)):
                n = (x + dx, y + dy)
                if n not in seen and self.walkable(*n):
                    seen.add(n)
                    todo.append(n)
        self.cells: dict[str, list[tuple[int, int]]] = {}
        for y in range(H):
            for x in range(W):
                if (x, y) in seen or self.terrain[y][x] == WATER:
                    self.cells.setdefault(self.region[y][x], []).append((x, y))

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

    def spawn_near(self, kind: str, region: str, on: int | None = None, near: tuple | None = None) -> dict | None:
        cells = self.cells.get(region, [])
        for _ in range(60):
            if not cells:
                return None
            x, y = self.rng.choice(cells)
            if near is not None:
                x, y = near[0] + self.rng.randint(-2, 2), near[1] + self.rng.randint(-2, 2)
            t = self.terrain[y][x] if 0 <= x < W and 0 <= y < H else WATER
            if on is not None:
                if t != on:
                    continue
            elif not self.walkable(x, y) or t in (DOOR, BRIDGE, DOCK):
                continue
            if self.at(x, y):
                continue
            return self.add(kind, x, y)
        return None

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

    def path(self, start, goal, me: Being | None = None, adjacent: bool = False, limit: int = 12000,
             avoid: bool = True):
        """A* over the grid. With adjacent=True, stop next to the goal (for things you can't stand on).
        With avoid=False, people are not obstacles (they step aside when you reach them)."""
        sx, sy = start
        gx, gy = goal
        if adjacent and abs(sx - gx) + abs(sy - gy) == 1:
            return []
        if not adjacent and (sx, sy) == (gx, gy):
            return []
        busy = {(b.x, b.y) for b in self.beings() if b is not me} if avoid else set()
        openq = [(abs(sx - gx) + abs(sy - gy), 0, (sx, sy))]
        came = {(sx, sy): None}
        cost = {(sx, sy): 0}
        terrain = self.terrain
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
            for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
                nx, ny = cx + dx, cy + dy
                if not (0 <= nx < W and 0 <= ny < H) or terrain[ny][nx] in BLOCKING:
                    continue
                step = 1 if terrain[ny][nx] in (PATH, PLAZA, BRIDGE, DOCK, FLOOR, DOOR) else 1.4
                ng = g + step
                if (nx, ny) in cost and cost[(nx, ny)] <= ng:
                    continue
                if (nx, ny) in busy and (nx, ny) != (gx, gy):
                    continue
                cost[(nx, ny)] = ng
                came[(nx, ny)] = cur
                heapq.heappush(openq, (ng + abs(nx - gx) + abs(ny - gy), ng, (nx, ny)))
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

    def nearest_tile(self, kinds, frm, need_neighbour_walkable=True):
        kinds = {kinds} if isinstance(kinds, int) else set(kinds)
        best, bd = None, 1e9
        fx, fy = frm
        for r in range(1, max(W, H)):
            if r > bd:
                break
            for y in range(max(0, fy - r), min(H, fy + r + 1)):
                for x in (fx - r, fx + r) if abs(y - fy) != r else range(max(0, fx - r), min(W, fx + r + 1)):
                    if 0 <= x < W and self.terrain[y][x] in kinds:
                        if need_neighbour_walkable and not any(self.walkable(x + dx, y + dy) for dx, dy in DIRS.values()):
                            continue
                        d = abs(x - fx) + abs(y - fy)
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
        """Weather, growth, regrowth, the animals and the villagers: everything that happens on its own."""
        self.tick_n += 1
        self.phase_t += dt
        self.weather_left -= dt
        r = self.rng
        if self.weather_left <= 0:
            self.weather = r.choice(WEATHER[self.season])
            self.weather_left = r.uniform(120, 360)
        for name, p in self.people.items():
            self._villager(name, p)
        if self.tick_n % 4:
            return
        counts: dict[str, int] = {}
        for e in list(self.entities.values()):
            k = e["kind"]
            counts[k] = counts.get(k, 0) + 1
            if k == "sprout":
                e["growth"] = e.get("growth", 0) + (1.6 if e.get("watered") or self.weather == "rain" else 0.5) \
                    * (0.4 if self.season == "winter" else 1.0)
                if e["growth"] >= 100:
                    e["kind"], e["growth"] = e.get("crop", "wheat"), None
                    e.pop("watered", None)
                self.touch(e)
            elif k == "fire pit" and e.get("lit"):
                e["lit"] -= 1
                if e["lit"] <= 0:
                    e["lit"] = 0
                    self.note("The fire in the fire pit goes out.")
                self.touch(e)
            elif k in ("ore vein", "crystal cluster") and e.get("left", 0) < (5 if k == "ore vein" else 3) \
                    and r.random() < 0.004:
                e["left"] = e.get("left", 0) + 1
                self.touch(e)
            elif KINDS.get(k, {}).get("creature"):
                self._wander(e)
        for kind, region, cap, chance in (("apple", "orchard", 8, 0.03), ("berry", "forest", 6, 0.03),
                                          ("mushroom", "forest", 6, 0.02), ("wood", "forest", 4, 0.02),
                                          ("stone", "lake", 5, 0.02), ("flower", "meadow", 8, 0.03),
                                          ("coin", "village", 2, 0.01), ("seed", "farm", 2, 0.01),
                                          ("clay", "river", 4, 0.02)):
            if counts.get(kind, 0) < cap and r.random() < chance and not (kind == "apple" and self.season == "winter"):
                self.spawn_near(kind, region, on=SAND if kind in ("stone", "clay") else None)
        if counts.get("egg", 0) < 3 and r.random() < 0.015:
            hen = self.nearest("chicken", self.anchors["farm"])
            if hen:
                self.spawn_near("egg", "farm", near=(hen["x"], hen["y"]))
        if counts.get("honey", 0) < 2 and r.random() < 0.006 and self.season != "winter":
            hive = r.choice([e for e in self.entities.values() if e["kind"] == "beehive"] or [None])
            if hive:
                self.spawn_near("honey", "meadow", near=(hive["x"], hive["y"]))
        if self.tick_n % 240 == 0:
            self._maybe_quest()

    def _wander(self, e: dict):
        r = self.rng
        k = e["kind"]
        if k in ("fish", "duck"):
            if r.random() < 0.5:
                dx, dy = r.choice(list(DIRS.values()))
                nx, ny = e["x"] + dx, e["y"] + dy
                if 0 <= nx < W and 0 <= ny < H and (self.terrain[ny][nx] == WATER or
                                                   (k == "duck" and self.terrain[ny][nx] == SAND)):
                    e["x"], e["y"] = nx, ny
                    self.touch(e)
            return
        if k == "dog" and r.random() < 0.4:   # dogs like company
            a = self.ada
            if abs(a.x - e["x"]) + abs(a.y - e["y"]) > 3 and abs(a.x - e["x"]) + abs(a.y - e["y"]) < 30:
                p = self.path((e["x"], e["y"]), (a.x, a.y), adjacent=True, limit=500)
                if p:
                    e["x"], e["y"] = p[0]
                    self.touch(e)
                return
        if k == "owl" and self.phase == "day":
            return
        home = KINDS[k].get("found")
        if r.random() < {"bird": 0.7, "butterfly": 0.8, "rabbit": 0.5, "deer": 0.3}.get(k, 0.25):
            dx, dy = r.choice(list(DIRS.values()))
            nx, ny = e["x"] + dx, e["y"] + dy
            if self.walkable(nx, ny) and not self.occupied(nx, ny) and self.terrain[ny][nx] not in (DOOR, FLOOR) \
                    and (self.region[ny][nx] == home or self.region[e["y"]][e["x"]] != home):
                e["x"], e["y"] = nx, ny
                self.touch(e)

    def _villager(self, name: str, p: Being):
        """Villagers keep their routines: work, a stroll to the plaza, home to sleep."""
        if p.engaged is not None:
            return                                        # talking: the conversation moves it, if at all
        if self.tick_n % 2:
            return
        post = self.posts[name]
        if self.phase == "night":
            p.sleeping = (p.x, p.y) == post
            target = post
        else:
            p.sleeping = False
            slot = (self.day * 7 + self.tick_n // 480 + sum(map(ord, name))) % 5
            if name == "Pip":
                target = [post, self.anchors["park"], self.anchors["village"], (60, 64), self.anchors["meadow"]][slot]
            else:
                target = post if slot else self.anchors["village"]
        if (p.x, p.y) == target:
            p.route, p.goal = [], target
            return
        if p.goal != target or not p.route:
            p.goal = target
            p.route = self.path((p.x, p.y), target, me=p, limit=6000, avoid=False) or []
        if p.route:
            nx, ny = p.route[0]
            if self.occupied(nx, ny, p):
                if self.rng.random() < 0.3:
                    p.route = []                          # wait a moment, then find another way
                return
            p.route.pop(0)
            p.facing = _facing(p.x, p.y, nx, ny)
            p.x, p.y = nx, ny

    def note(self, text: str):
        self.log.append(text)
        del self.log[:-40]

    # ================================================================== quests and friends
    def _maybe_quest(self):
        if len(self.quests) >= 3:
            return
        free = [n for n in NPCS if not any(q["giver"] == n for q in self.quests)]
        if not free:
            return
        giver = self.rng.choice(free)
        want = self.rng.choice(NPCS[giver]["wants"])
        count = 1 if KINDS[want].get("value", 1) >= 4 else self.rng.choice([1, 2])
        reward = max(2, KINDS[want].get("value", 1) * count + self.rng.randint(1, 3))
        noun = KINDS[want]["noun"] if count == 1 else f"{count} of {want}"
        q = {"id": self.quest_seq, "giver": giver, "want": want, "count": count, "got": 0, "reward": reward,
             "text": f"{giver} needs {noun}.", "day": self.day}
        self.quest_seq += 1
        self.quests.append(q)
        self.note(f"New quest: {q['text']} (reward: {reward} coins)")

    # ================================================================== the gallery
    def create(self, kind: str, author: str, data: dict, title: str = "", entity: dict | None = None) -> dict:
        c = {"id": len(self.creations) + 1, "kind": kind, "author": author, "title": title, "text": "",
             "day": self.day, "season": self.season, "data": data, "t": time.time(),
             "entity": entity["id"] if entity else None}
        self.creations.append(c)
        self.new_creations.append(c)
        if entity is not None:
            entity["work"] = c["id"]
            self.touch(entity)
        return c

    def update_creation(self, cid: int, **fields):
        c = next((c for c in self.creations if c["id"] == cid), None)
        if c:
            c.update({k: v for k, v in fields.items() if v})
            self.new_creations.append(c)
        return c

    def free_spot(self, x: int, y: int, radius: int = 3) -> tuple[int, int] | None:
        """An open tile next to (x, y) where something can be built or set down."""
        for r in range(1, radius + 1):
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    if abs(dx) + abs(dy) != r:
                        continue
                    nx, ny = x + dx, y + dy
                    if self.walkable(nx, ny) and self.terrain[ny][nx] not in (DOOR, BRIDGE, DOCK) \
                            and not self.at(nx, ny) and not self.occupied(nx, ny):
                        return nx, ny
        return None

    # The synth's own state, kept on its Being like everyone else's.
    @property
    def needs(self) -> dict:
        return self.ada.needs

    @property
    def coins(self) -> int:
        return self.ada.coins

    @coins.setter
    def coins(self, v: int):
        self.ada.coins = v

    @property
    def friends(self) -> dict:
        return self.ada.friends

    def being(self, name: str) -> Being | None:
        if name == self.ada.name or name == "synth":
            return self.ada
        if name in ("friend", "you", "my friend"):
            return self.visitor
        return self.people.get(name)

    def befriend(self, name: str, amount: float, me: Being | None = None) -> float:
        """Friendship grows both ways."""
        me = me or self.ada
        other = self.being(name)
        if other is None or other is me or other is self.visitor:
            return 0.0
        me.friends[other.name] = max(0.0, min(100.0, me.friends.get(other.name, 10.0) + amount))
        other.friends[me.name] = max(0.0, min(100.0, other.friends.get(me.name, 10.0) + amount))
        return me.friends[other.name]

    def friendship_word(self, name: str, me: Being | None = None) -> str:
        f = (me or self.ada).friends.get(name, 0)
        return "a new acquaintance" if f < 25 else "a friend" if f < 55 else "a good friend" if f < 80 else "a best friend"

    def describe(self, b: Being) -> str:
        if b is self.visitor:
            return "my friend"
        if b is self.ada:
            return f"{b.name} the synth"
        return f"{b.name} the {b.role}"

    # ================================================================== senses
    def _rel(self, x, y, me: Being | None = None) -> str:
        a = me or self.ada
        dx, dy = x - a.x, y - a.y
        if dx == 0 and dy == 0:
            return "here"
        parts = []
        if dy:
            parts.append(f"{abs(dy)} {'north' if dy < 0 else 'south'}")
        if dx:
            parts.append(f"{abs(dx)} {'west' if dx < 0 else 'east'}")
        return " and ".join(parts)

    def feelings(self, me: Being | None = None) -> list[str]:
        n = (me or self.ada).needs
        out = []
        for need, low, word in (("energy", 35, "hungry"), ("water", 35, "thirsty"), ("rest", 25, "tired"),
                                ("warmth", 35, "cold"), ("company", 30, "lonely"), ("fun", 30, "bored")):
            if n[need] < low:
                out.append(("very " if n[need] < low / 2 else "") + word)
        if not out and min(n.values()) > 70:
            out.append("happy")
        return out

    def perceive(self, day_seconds: float, radius: int = 7, me: Being | None = None) -> str:
        """Everything a mind senses, in its own words (the synth's by default)."""
        a = me or self.ada
        place = self.place_of(a.x, a.y)
        s = [f"It is {self.time_of_day(day_seconds)} on day {self.day}, in {self.season}. "
             f"The weather is {self.weather}. I am {where(place)}."]
        f = self.feelings(a)
        s.append("I feel " + " and ".join(f) + "." if f else "I feel fine.")
        if a.carrying:
            s.append("I carry " + _and([KINDS[e["kind"]]["noun"] for e in a.carrying]) + ".")
        if a.coins:
            s.append(f"I have {a.coins} coin{'s' if a.coins != 1 else ''}.")
        seen = []
        for e in sorted(self.entities.values(), key=lambda e: abs(e["x"] - a.x) + abs(e["y"] - a.y)):
            d = abs(e["x"] - a.x) + abs(e["y"] - a.y)
            if d > radius or len(seen) >= 4:
                break
            k = e["kind"]
            label = KINDS[k]["noun"] + (" that is burning" if k == "fire pit" and e.get("lit") else "")
            seen.append(f"{label} {self._rel(e['x'], e['y'], a)}")
        if seen:
            s.append("I see " + "; ".join(seen) + ".")
        for b in self.beings():
            if b is a:
                continue
            d = abs(b.x - a.x) + abs(b.y - a.y)
            if d <= radius:
                s.append(f"{_cap(self.describe(b))} is {'right next to me' if d == 1 else self._rel(b.x, b.y, a)}.")
        if a is self.ada:
            for q in self.quests:
                p = self.people.get(q["giver"])
                if p and abs(p.x - a.x) + abs(p.y - a.y) <= radius:
                    s.append(q["text"])
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
        for b in [self.ada] + list(self.people.values()):
            self._needs(b, dt)

    def _needs(self, a: Being, dt: float):
        n = a.needs
        indoors = self.terrain[a.y][a.x] in INDOORS
        near_fire = any(e["kind"] in ("fire pit", "stove") and (e.get("lit") or e["kind"] == "stove")
                        and abs(e["x"] - a.x) + abs(e["y"] - a.y) <= 3 for e in self.entities.values()) \
            if not indoors else True
        lantern = any(e["kind"] == "lantern" for e in a.carrying)
        k = dt / 0.25
        # Gentle rates: a day (10 minutes by default) has room for meals, work, art and long talks.
        n["energy"] -= (0.012 if a.sleeping else 0.03) * k
        n["water"] -= (0.012 if a.sleeping else 0.036) * k
        n["rest"] += (0.5 if a.sleeping else -0.016) * k
        warm_target = 22 if (indoors or near_fire) else self.temperature() + (6 if lantern else 0)
        n["warmth"] += (0.25 if warm_target >= 12 else -0.12 * (12 - warm_target) / 12) * k
        n["company"] -= (0.0 if a.engaged is not None else 0.02) * k
        if a.engaged is not None:
            n["company"] += 0.15 * k
        n["fun"] -= (0.0 if a.sleeping else 0.022) * k
        for key in n:
            n[key] = max(0.0, min(100.0, n[key]))

    def wellbeing(self, me: Being | None = None) -> float:
        n = (me or self.ada).needs
        return sum(min(v, 80) for v in n.values()) / (80 * len(n))

    # ================================================================== you
    def join(self) -> Being:
        if not self.visitor:
            a = self.ada
            for r in range(1, 12):
                spots = [(a.x + dx, a.y + dy) for dx in range(-r, r + 1) for dy in range(-r, r + 1)
                         if abs(dx) + abs(dy) == r]
                spots = [s for s in spots if self.walkable(*s) and not self.occupied(*s)]
                if spots:
                    self.visitor = Being("you", *spots[0], role="visitor")
                    self.visitor.fx, self.visitor.fy = float(spots[0][0]), float(spots[0][1])
                    break
            self.note("My friend arrives!")
        return self.visitor

    def move_visitor(self, fx: float, fy: float, facing: str | None = None):
        """You walk freely; your tile is the nearest walkable one to where you are."""
        v = self.visitor
        if not v:
            return
        # Continuous position in tiles, where a whole number is a tile's centre (as the 3D view counts).
        fx, fy = max(-0.49, min(W - 0.51, fx)), max(-0.49, min(H - 0.51, fy))
        tx, ty = int(round(fx)), int(round(fy))
        if self.walkable(tx, ty):
            v.fx, v.fy, v.x, v.y = fx, fy, tx, ty
        if facing in DIRS:
            v.facing = facing

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
    def kinds_table(self) -> dict:
        return {k: {"glyph": v["glyph"], "color": v.get("hex", "#cccccc"),
                    "size": "creature" if v.get("creature") else ("small" if v.get("portable") else "big")}
                for k, v in KINDS.items()}

    def snapshot(self, full: bool = False, day_seconds: float = 600.0, night_seconds: float = 1200.0) -> dict:
        now = time.time()

        def being(b: Being | None):
            if b is None:
                return None
            d = {"name": b.name, "x": b.x, "y": b.y, "facing": b.facing, "sleeping": b.sleeping,
                 "talking": b.engaged is not None,
                 "carrying": [e["kind"] for e in b.carrying], "said": b.said if now < b.said_until else ""}
            if b.fx is not None:
                d["fx"], d["fy"] = round(b.fx, 2), round(b.fy, 2)
            return d

        span = day_seconds if self.phase == "day" else night_seconds
        out = {
            "tick": self.tick_n, "day": self.day, "phase": self.phase, "season": self.season,
            "weather": self.weather, "time": self.time_of_day(day_seconds), "light": round(self.light(day_seconds), 3),
            "sun": round(min(1.0, self.phase_t / max(span, 1)), 4),
            "temperature": self.temperature(), "terrain_v": self.terrain_v,
            "ada": being(self.ada) | {"place": self.place_of(self.ada.x, self.ada.y),
                                       "needs": {k: round(v, 1) for k, v in self.needs.items()},
                                       "feelings": self.feelings(), "coins": self.coins},
            "visitor": being(self.visitor),
            "people": [being(p) | {"role": NPCS[n]["role"], "color": NPCS[n]["color"], "hat": NPCS[n]["hat"],
                                   "glyph": NPCS[n]["glyph"], "friendship": round(self.friends.get(n, 0), 1)}
                       for n, p in self.people.items()],
            "quests": self.quests,
            "log": self.log[-14:],
        }
        if self.new_creations and not full:
            out["creations"] = self.new_creations[:]
        self.new_creations.clear()
        if full:
            names = sorted({r for row in self.region for r in row})
            index = {n: i for i, n in enumerate(names)}
            out.update(full=True, W=W, H=H, terrain=self.terrain, height=self.height,
                       regions=[[index[r] for r in row] for row in self.region], region_names=names,
                       places={k: list(v) for k, v in self.anchors.items()}, buildings=self.buildings,
                       kinds=self.kinds_table(), ents=list(self.entities.values()), removed=[],
                       creations=self.creations[-300:])
        else:
            out["ents"] = [self.entities[i] for i in self.dirty if i in self.entities]
            out["removed"] = list(self.removed)
        self.dirty.clear()
        self.removed.clear()
        return out

    def state(self) -> dict:
        a = self.ada
        return {"version": 2, "W": W, "H": H, "terrain": self.terrain, "entities": list(self.entities.values()),
                "next_id": self.next_id, "tick": self.tick_n, "day": self.day, "phase": self.phase,
                "phase_t": self.phase_t, "weather": self.weather, "needs": self.needs, "coins": self.coins,
                "people": {n: {"x": p.x, "y": p.y, "needs": p.needs, "coins": p.coins, "friends": p.friends,
                               "carrying": p.carrying} for n, p in self.people.items()},
                "visited": sorted(self.visited), "firsts": sorted(self.firsts), "read": sorted(self.read_books),
                "friends": self.friends, "quests": self.quests, "quest_seq": self.quest_seq,
                "done_quests": self.done_quests, "creations": self.creations,
                "ada": {"x": a.x, "y": a.y, "carrying": a.carrying, "sleeping": a.sleeping}}

    def load_state(self, s: dict):
        if s.get("version", 1) < 2 or s.get("W") != W or s.get("H") != H:
            # A world from before the valley grew: keep what the synth has lived, not the old map.
            self.day = s.get("day", 1)
            self.needs.update(s.get("needs", {}))
            self.firsts = set(s.get("firsts", []))
            self.note("The valley has grown much bigger! There is so much to explore.")
            return
        self.terrain = s["terrain"]
        self.terrain_v += 1
        self.entities = {e["id"]: e for e in s["entities"]}
        self.next_id, self.tick_n, self.day = s["next_id"], s["tick"], s["day"]
        self.phase, self.phase_t, self.weather = s["phase"], s["phase_t"], s["weather"]
        self.needs.update(s["needs"])
        self.coins = s.get("coins", self.coins)
        self.visited, self.firsts = set(s["visited"]), set(s["firsts"])
        self.read_books = set(s.get("read", []))
        self.friends.update(s.get("friends", {}))
        for n, d in s.get("people", {}).items():
            p = self.people.get(n)
            if p:
                p.x, p.y = d.get("x", p.x), d.get("y", p.y)
                p.needs.update(d.get("needs", {}))
                p.coins = d.get("coins", p.coins)
                p.friends.update(d.get("friends", {}))
                p.carrying = d.get("carrying", [])
        self.quests = s.get("quests", [])
        self.quest_seq = s.get("quest_seq", 1)
        self.done_quests = s.get("done_quests", 0)
        self.creations = s.get("creations", [])
        a = s["ada"]
        self.ada.x, self.ada.y, self.ada.carrying, self.ada.sleeping = a["x"], a["y"], a["carrying"], a["sleeping"]


def where(place: str) -> str:
    """'home' -> 'at home', 'lake' -> 'by the lake', 'bakery' -> 'in the bakery'."""
    return {"home": "at home", "lake": "by the lake", "river": "by the river", "shrine": "at the shrine",
            "dock": "on the dock", "farm": "on the farm", "mountains": "in the mountains",
            "market": "at the market"}.get(place, f"in the {place}")


def _facing(x, y, nx, ny) -> str:
    return "east" if nx > x else "west" if nx < x else "south" if ny > y else "north"


def _and(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]
