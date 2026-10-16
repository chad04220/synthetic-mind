"""The World the synth lives in: a homestead in a hollow, shared with its companion.

The house has a living room with a fireplace, a kitchen with a stove and oven, a pantry and a
sink, two bedrooms and a washroom. Around it are the porch, the workshop (tools, the quern, the
woodpile), the glass greenhouse, the vegetable garden with its water barrel, the chicken coop, a
small orchard with a swing, a pond with ducks and frogs, a stream through the woods, a meadow with
the beehive, and a lookout on the hill for the stars.

It is small, but it is deep. Rooms have a temperature that the fire raises and the night lowers.
Things warm and cool, cook, boil, bake and burn; food goes stale and rots (slower in the cool
pantry); rain wets what is outside and the fire dries it; wet logs won't burn; fires use up their
fuel and leave ash; lamps and candles light the dark and burn down; soil dries out, plants grow
through their stages if watered and warm and die in a frost; hens lay eggs in the morning, bees
make honey while flowers bloom, the cat looks for the warmest spot. Everything a mind can sense is
written as plain first-person sentences, so the synth learns words for what it lives through.
"""
from __future__ import annotations

import heapq
import math
import random
import time
from dataclasses import dataclass, field

from ..ontology import KINDS, OVEN_RECIPES, POT_RECIPES, SOUP_THINGS, STAGE_NAMES

W, H = 72, 56
# Tile codes are shared with the 3D view (web/world3d.js).
(GRASS, WATER, SAND, TREE, ROCK, FLOWERS, PATH, FLOOR, WALL, DOOR, SOIL, BRIDGE, PLAZA, CLIFF, SNOW,
 FENCE, DOCK, TALLGRASS, PINE, CAVE) = range(20)
TERRAIN = ["grass", "water", "sand", "a tree", "a rock", "flowers", "a path", "a floor", "a wall", "a door",
           "soil", "a bridge", "paving stones", "a cliff", "snow", "a fence", "a deck", "tall grass", "a pine tree",
           "the cave floor"]
BLOCKING = {WATER, TREE, ROCK, WALL, CLIFF, FENCE, PINE}
SEASONS = ["spring", "summer", "autumn", "winter"]
DIRS = {"north": (0, -1), "south": (0, 1), "west": (-1, 0), "east": (1, 0)}
NEEDS = ["energy", "water", "rest", "warmth", "company", "fun", "clean"]
WEATHER = {"spring": ["clear", "clear", "cloudy", "rain", "windy", "fog"],
           "summer": ["clear", "clear", "clear", "cloudy", "storm", "rain"],
           "autumn": ["clear", "cloudy", "rain", "windy", "fog", "rain", "storm"],
           "winter": ["clear", "cloudy", "snow", "snow", "fog"]}
WET_WEATHER = ("rain", "storm", "snow")
ROOMS = ("living room", "kitchen", "little bedroom", "big bedroom", "washroom")

# Buildings: name, label, rectangle (x0, y0, x1, y1), door, wall, roof and floor colours.
BUILDINGS = [
    ("house", "The house", (12, 15, 29, 26), (20, 26), "#efe0c4", "#8c3b2e", "#a47148"),
    ("workshop", "Workshop", (34, 16, 41, 22), (37, 22), "#a3b18a", "#3a5a40", "#7f6a5a"),
    ("greenhouse", "Greenhouse", (33, 31, 38, 36), (35, 31), "#e8f6ef", "#bfe3d4", "#6b4f3a"),
    ("coop", "Chicken coop", (3, 28, 7, 32), (5, 32), "#e9c46a", "#9c4a2a", "#c2a36b"),
]
# Rooms inside the house: name, rectangle (floor tiles), floor colour.
HOUSE_ROOMS = [
    ("little bedroom", (13, 16, 18, 20), "#c9a27e"), ("washroom", (20, 16, 22, 20), "#d9d4cf"),
    ("big bedroom", (24, 16, 28, 20), "#b08968"), ("living room", (13, 22, 21, 25), "#a47148"),
    ("kitchen", (23, 22, 28, 25), "#cdb79e"),
]
INSULATED = {"house": 4.0, "workshop": 3.0, "greenhouse": 0.0, "coop": 5.0}


@dataclass
class Being:
    """The synth, its companion and you share this shape."""
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
    wet: float = 0.0
    activity: str = ""                             # what it is doing right now ("playing the piano")
    role: str = ""                                 # "synth", "companion" or "visitor"
    rates: float = 1.0                             # how fast its needs fall

    def say(self, text: str, seconds: float = 8.0):
        self.said, self.said_until = text[:240], time.time() + seconds


def _noise(seed: int):
    """Smooth 2-D value noise in [0, 1]."""
    rng = random.Random(seed)
    n = 64
    grid = [[rng.random() for _ in range(n)] for _ in range(n)]

    def f(x: float, y: float) -> float:
        gx, gy = x / 6, y / 6
        x0, y0 = int(gx), int(gy)
        tx, ty = gx - x0, gy - y0
        tx, ty = tx * tx * (3 - 2 * tx), ty * ty * (3 - 2 * ty)
        x0, y0, x1, y1 = x0 % n, y0 % n, (x0 + 1) % n, (y0 + 1) % n
        a = grid[y0][x0] * (1 - tx) + grid[y0][x1] * tx
        b = grid[y1][x0] * (1 - tx) + grid[y1][x1] * tx
        return a * (1 - ty) + b * ty
    return f


def stream_x(y: int) -> int:
    return int(44 + 2.2 * math.sin(y / 4.5) + 1.2 * math.sin(y / 2.3) + max(0, y - 28) * 0.55)   # into the pond


POND = (52.0, 45.0, 8.0, 5.0)        # centre x, centre y, radius x, radius y


def kind_of(e: dict) -> dict:
    return KINDS.get(e["kind"], {})


class World:
    def __init__(self, seed: int | None = 11, name: str = "Zen", companion: str = "Wren"):
        self.rng = random.Random()
        self.seed = seed
        self.name, self.companion_name = name, companion
        self.terrain = [[GRASS] * W for _ in range(H)]
        self.height = [[0] * W for _ in range(H)]
        self.region = [["yard"] * W for _ in range(H)]
        self.terrain_v = random.randrange(1 << 30)
        self.entities: dict[int, dict] = {}
        self.next_id = 1
        self.anchors: dict[str, tuple[int, int]] = {}   # where to stand to "be at" a place
        self.buildings: list[dict] = []
        self.dirty: set[int] = set()
        self.removed: set[int] = set()
        self.log: list[str] = []
        self.events: list[dict] = []                    # things that happened, for the minds and the page
        # time and climate
        self.tick_n = 0
        self.day = 1
        self.phase = "day"
        self.phase_t = 0.0          # seconds into the current phase
        self.day_seconds = 600.0
        self.weather = "clear"
        self.weather_left = 240.0
        self.rainbow_until = 0.0
        self.indoor = {b: 16.0 for b in INSULATED}       # each building's air temperature
        self.moisture: dict[tuple[int, int], float] = {}
        self.sounds: list[tuple[str, int, int, int]] = []   # (what, x, y, how far it carries)
        self._generate(random.Random(seed))
        bx, by = self.anchors["little bedroom"]
        self.ada = Being(name, bx, by, role="synth")
        cx, cy = self.anchors["kitchen"]
        self.wren = Being(companion, cx, cy, role="companion", rates=0.6)
        self.wren.needs = {n: 85.0 for n in NEEDS}
        self.visitor: Being | None = None
        self.visited: set[str] = set()
        self.firsts: set[str] = set()
        self.read_books: set[int] = set()
        self.creations: list[dict] = []
        self.new_creations: list[dict] = []
        self.heard: list[tuple[float, str, str]] = []    # (time, who, words) said near the synth
        self.bond = 20.0                                  # how close the synth feels to its companion
        self.outdoor_t = self.outdoor_temperature()

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
        b = {"name": name, "label": label, "x0": x0, "y0": y0, "x1": x1, "y1": y1, "door": [dx, dy],
             "outside": list(outside), "wall": wall, "roof": roof, "floor": floor, "doors": [[dx, dy]]}
        if name == "greenhouse":
            b["glass"] = True
        self.buildings.append(b)
        return outside

    def _path(self, a, b, kind=PATH):
        """A winding path from a to b; over water it becomes a bridge."""
        (x, y), (tx, ty) = a, b
        r = self._prng
        while (x, y) != (tx, ty):
            t = self.terrain[y][x]
            if t == WATER:
                self.terrain[y][x] = BRIDGE
            elif t in (GRASS, FLOWERS, SAND, TALLGRASS, TREE, PINE, ROCK):
                self.terrain[y][x] = kind
            if x != tx and (y == ty or r.random() < 0.55):
                x += 1 if tx > x else -1
            else:
                y += 1 if ty > y else -1

    def _generate(self, r: random.Random):
        self._prng = r
        hills, detail = _noise(r.randrange(1 << 30)), _noise(r.randrange(1 << 30))
        px, py, prx, pry = POND
        # ---- land: gentle heights and broad regions
        for y in range(H):
            for x in range(W):
                h = hills(x, y) * 1.4 + detail(x * 2, y * 2) * 0.4
                if y < 14:
                    h += (14 - y) * 0.12                    # the woods climb the hillside
                h += max(0.0, 4.2 - math.hypot(x - 65, y - 6) * 0.42)    # the lookout's hill
                if 10 <= x <= 42 and 14 <= y <= 40:
                    h = min(h, 0.9)                         # the homestead sits on level ground
                self.height[y][x] = max(0, min(6, int(h)))
                if y < 13:
                    self.region[y][x] = "woods"
                elif x >= 46 and y <= 34:
                    self.region[y][x] = "meadow"
                elif x <= 12 and y >= 39:
                    self.region[y][x] = "orchard"
                elif math.hypot((x - px) / (prx + 3), (y - py) / (pry + 3)) < 1.0:
                    self.region[y][x] = "pond"
                else:
                    self.region[y][x] = "yard"
        for y in range(0, 13):
            for x in range(W):
                if math.hypot(x - 65, y - 6) < 6.5:
                    self.region[y][x] = "lookout"
        # ---- the stream and the pond
        for y in range(0, H):
            cx = stream_x(y)
            if math.hypot((cx - px) / prx, (y - py) / pry) < 1.0:
                break
            self._set(cx, y, WATER, "stream", 0)
            if y > 20:
                self._set(cx + 1, y, WATER, "stream", 0)
            for x in (cx - 1, cx + 2):
                if self.terrain[y][x] != WATER and r.random() < 0.4:
                    self._set(x, y, SAND, "stream", 0)
        for y in range(H):
            for x in range(W):
                d = math.hypot((x - px) / prx, (y - py) / pry)
                if d < 1.0:
                    self._set(x, y, WATER, "pond", 0)
                elif d < 1.2:
                    self._set(x, y, SAND, "pond", 0)
                elif d < 1.6:
                    self.height[y][x] = min(self.height[y][x], 1)
        # ---- buildings, then the rooms inside the house
        doors = {}
        for name, label, rect, door, wall, roof, floor in BUILDINGS:
            doors[name] = self._building(name, label, rect, door, wall, roof, floor)
        house = self.buildings[0]
        h0 = self.height[26][20]
        self._rect(13, 21, 28, 21, WALL, "house", h0)        # hall wall between the bedrooms and the rooms below
        self._rect(19, 16, 19, 20, WALL, "house", h0)
        self._rect(23, 16, 23, 20, WALL, "house", h0)
        self._rect(22, 22, 22, 25, WALL, "house", h0)
        for dx, dy in ((16, 21), (21, 21), (26, 21), (22, 24)):
            self._set(dx, dy, DOOR, None, h0)
        self._set(29, 24, DOOR, None, h0)                     # the kitchen door, to the yard
        house["doors"].append([29, 24])
        house["inner"] = "#f3e9d8"
        house["rooms"] = []
        for name, (x0, y0, x1, y1), floor in HOUSE_ROOMS:
            for y in range(y0, y1 + 1):
                for x in range(x0, x1 + 1):
                    if self.terrain[y][x] == FLOOR:
                        self.region[y][x] = name
            house["rooms"].append({"name": name, "x0": x0, "y0": y0, "x1": x1, "y1": y1, "floor": floor})
        for (dx, dy), name in (((16, 21), "little bedroom"), ((21, 21), "washroom"), ((26, 21), "big bedroom"),
                               ((22, 24), "kitchen"), ((20, 26), "living room"), ((29, 24), "kitchen")):
            self.region[dy][dx] = name
        self.anchors.update({"little bedroom": (15, 18), "washroom": (21, 18), "big bedroom": (26, 18),
                             "living room": (17, 24), "kitchen": (25, 23), "house": (20, 25)})
        # the greenhouse beds
        for y in range(33, 36):
            for x in range(34, 38):
                if x != 35:
                    self._set(x, y, SOIL, "greenhouse")
        # ---- the porch and the jetty
        for x in range(16, 25):
            for y in (27, 28):
                self._set(x, y, DOCK, "porch", h0)
        self.anchors["porch"] = (22, 27)
        for x in range(43, 47):
            self._set(x, 45, DOCK, "pond", 0)
        # ---- the garden: a fence, beds of soil and paths between them
        self._rect(13, 30, 30, 30, FENCE, "garden")
        self._rect(13, 30, 13, 41, FENCE, "garden")
        self._rect(13, 41, 30, 41, FENCE, "garden")
        self._rect(30, 30, 30, 41, FENCE, "garden")
        self._set(21, 30, PATH, "garden")                     # the gate
        self._rect(14, 31, 29, 40, GRASS, "garden", 0)
        for y in range(32, 40):
            for x in range(15, 29):
                self._set(x, y, SOIL if y in (32, 33, 35, 36, 38, 39) and x != 21 else PATH, "garden", 0)
        self.anchors["garden"] = (21, 34)
        # ---- the coop's run
        self._rect(1, 33, 9, 33, FENCE, "coop")
        self._rect(1, 33, 1, 38, FENCE, "coop")
        self._rect(1, 38, 9, 38, FENCE, "coop")
        self._rect(9, 33, 9, 38, FENCE, "coop")
        self._rect(2, 34, 8, 37, GRASS, "coop", 0)
        self._set(5, 33, GRASS, "coop")                       # the coop opens into its run
        self._set(9, 35, PATH, "coop")                        # the run's gate
        self.region[32][5] = "coop"
        # ---- the orchard
        self.trees = []
        for y in range(41, 54, 3):
            for x in range(2, 12, 3):
                self._set(x, y, TREE, "orchard")
                self.trees.append((x, y))
        # ---- the woods
        for y in range(0, 14):
            for x in range(W):
                if self.terrain[y][x] != GRASS or self.region[y][x] == "lookout":
                    continue
                trail = abs(x - (30 + y // 3)) <= 1 or abs(y - 8) <= 0 and x > 30
                if not trail and r.random() < 0.38 - (0.2 if y > 10 else 0):
                    self._set(x, y, PINE if r.random() < 0.5 else TREE, "woods")
        # ---- meadow flowers and tall grass, scattered trees and rocks
        for _ in range(260):
            x, y = r.randrange(W), r.randrange(H)
            if self.terrain[y][x] == GRASS and self.region[y][x] in ("meadow", "orchard"):
                self._set(x, y, FLOWERS if r.random() < 0.6 else TALLGRASS)
        for _ in range(50):
            x, y = r.randrange(W), r.randrange(H)
            if self.terrain[y][x] == GRASS and self.region[y][x] in ("yard", "meadow") and \
                    not (8 <= x <= 44 and 12 <= y <= 42):
                self._set(x, y, ROCK if r.random() < 0.25 else TREE)
        # ---- paths
        front = doors["house"]
        for a, b in [(front, (21, 29)), ((21, 29), (21, 31)), ((30, 24), (36, 24)), ((36, 24), doors["workshop"]),
                     ((36, 24), (36, 29)), ((36, 29), doors["greenhouse"]), ((21, 29), (11, 29)),
                     ((11, 29), (10, 35)), ((11, 29), doors["coop"]), ((11, 29), (11, 42)),
                     ((36, 29), (40, 42)), ((40, 42), (42, 45)), ((36, 24), (47, 24)), ((47, 24), (58, 24)),
                     ((30, 13), (34, 3)), ((24, 15), (30, 13)), ((34, 8), (58, 8)), ((58, 8), (63, 6))]:
            self._path(a, b)
        self._set(30, 24, PATH)
        # ---- places to stand
        self.anchors.update({"woods": (32, 7), "meadow": (58, 22), "orchard": (7, 46), "pond": (45, 45),
                             "stream": (stream_x(18) - 2, 18), "lookout": (64, 7), "yard": (24, 29),
                             "coop": (5, 35), "greenhouse": (35, 33), "workshop": (37, 20)})
        for name, (x, y) in list(self.anchors.items()):
            if self.terrain[y][x] in BLOCKING:
                self._set(x, y, PATH)
        self._furnish(r)
        self._index_cells()
        for (x, y), kind in zip(self.trees, ["apple tree", "pear tree", "plum tree", "apple tree", "apple tree",
                                             "pear tree", "plum tree", "apple tree", "apple tree", "plum tree",
                                             "pear tree", "apple tree", "apple tree", "plum tree", "pear tree"]):
            self.add(kind, x, y, fruit=0)
        for x, y in ((25, 4), (37, 10), (52, 6), (20, 9)):
            if self.walkable(x, y):
                self.add("berry bush", x, y, fruit=2)
        for y in range(H):
            for x in range(W):
                if self.terrain[y][x] == SOIL:
                    self.moisture[(x, y)] = 0.5
        creatures = [("hen", "coop", 3), ("rooster", "coop", 1), ("duck", "pond", 2), ("frog", "pond", 2),
                     ("fish", "pond", 5), ("butterfly", "meadow", 3), ("bee", "meadow", 2), ("robin", "garden", 1)]
        for kind, region, n in creatures:
            for _ in range(n):
                self.spawn_near(kind, region, on=WATER if kind in ("fish", "duck") else None)
        self.add("cat", 18, 24, name="Moss", hunger=20.0)
        for kind, region, n in (("mushroom", "woods", 3), ("stick", "woods", 4), ("pinecone", "woods", 3),
                                ("stone", "stream", 3), ("flower", "meadow", 6), ("clay", "pond", 2),
                                ("feather", "coop", 1), ("leaf", "woods", 2)):
            for _ in range(n):
                self.spawn_near(kind, region, on=SAND if kind in ("stone", "clay") else None)
        del self._prng

    def _furnish(self, r):
        """The house and the outbuildings, ready to live in."""
        fixed = [
            # living room
            ("fireplace", 13, 23, {"fuel": 240.0, "lit": False, "ash": 0}), ("sofa", 15, 25, {}),
            ("bookshelf", 21, 22, {}), ("piano", 19, 22, {}), ("rug", 16, 23, {}), ("clock", 13, 25, {}),
            ("lamp", 20, 25, {"lit": False, "burn": 1500.0}), ("matches", 14, 22, {}),
            # kitchen
            ("stove", 28, 22, {"fuel": 0.0, "lit": False, "ash": 0}), ("oven", 27, 22, {}), ("sink", 25, 22, {}),
            ("pantry", 23, 22, {}), ("table", 25, 24, {}), ("cat bowl", 23, 25, {}),
            ("pot", 26, 22, {"water": 0.0}), ("kettle", 28, 23, {"water": 0.0}), ("cup", 26, 24, {}),
            ("cup", 26, 25, {}), ("bowl", 24, 24, {}), ("bowl", 24, 25, {}), ("basket", 28, 25, {}),
            ("jar", 23, 24, {}),
            # bedrooms and the washroom
            ("bed", 13, 16, {"owner": "synth"}), ("toy chest", 18, 16, {}), ("music box", 14, 20, {}),
            ("candle", 18, 20, {"lit": False, "burn": 900.0}), ("picture book", 17, 17, {}),
            ("bed", 28, 16, {"owner": "companion"}), ("desk", 24, 16, {}), ("paper", 25, 16, {}),
            ("pencil", 24, 17, {}), ("candle", 28, 20, {"lit": False, "burn": 900.0}),
            ("bathtub", 20, 16, {}), ("mirror", 22, 16, {}), ("towel", 22, 18, {}),
            # outside
            ("bench", 18, 27, {}), ("sign", 23, 28, {"text": "Welcome home. The stove cooks, the fire warms, "
                                                          "the garden feeds us and the hens give eggs."}),
            ("chopping block", 39, 24, {}), ("bucket", 31, 25, {"water": 0.0}),
            ("workbench", 35, 17, {}), ("quern", 40, 17, {}), ("woodpile", 40, 21, {}), ("seed tin", 36, 17, {}),
            ("easel", 35, 21, {}), ("axe", 38, 17, {}), ("hammer", 39, 17, {}), ("chisel", 39, 18, {}),
            ("fishing rod", 40, 18, {}),
            ("water barrel", 14, 31, {"water": 30.0}), ("watering can", 15, 31, {"water": 0.0}),
            ("compost bin", 29, 40, {}), ("scarecrow", 21, 37, {}), ("bird feeder", 16, 40, {}),
            ("nest box", 4, 29, {}), ("beehive", 62, 24, {"honey": 1}), ("telescope", 65, 5, {}),
            ("swing", 6, 45, {}), ("bench", 47, 42, {}),
        ]
        for kind, x, y, st in fixed:
            e = self.add(kind, x, y, **st)
            if KINDS[kind].get("portable"):
                e["home"] = [x, y]                      # where it belongs, to put it back
        e = {k["kind"]: k for k in self.entities.values()}

        def fill(holder, *kinds):
            for k in kinds:
                holder.setdefault("items", []).append(self.make(k))

        fill(e["pantry"], "flour", "flour", "potato", "potato", "potato", "carrot", "carrot", "apple", "apple",
             "egg", "egg", "honey", "mint")
        fill(e["toy chest"], "ball", "blocks", "teddy")
        fill(e["bookshelf"], "book", "book", "book", "picture book")
        fill(e["woodpile"], *["log"] * 8)
        fill(e["seed tin"], "carrot seed", "carrot seed", "seed potato", "seed potato", "bean seed", "bean seed",
             "tomato seed", "pumpkin seed", "wheat seed", "wheat seed", "mint seed")
        fill(e["nest box"], "egg")
        fill(e["fireplace"])
        # a garden already under way
        for (x, y), crop, stage in (((16, 32), "carrot", 2.2), ((17, 32), "carrot", 2.0), ((22, 35), "potato", 1.4),
                                    ((23, 35), "potato", 1.5), ((26, 38), "beans", 3.1), ((34, 33), "tomato", 2.6),
                                    ((24, 32), "wheat", 3.6), ((25, 32), "wheat", 3.5)):
            self.add("plant", x, y, crop=crop, stage=stage, health=1.0)

    def _index_cells(self):
        """Tiles by region, keeping only those you can walk to from the house (and water, for fish)."""
        start = self.anchors["living room"]
        seen, todo = {start}, [start]
        while todo:
            x, y = todo.pop()
            for dx, dy in ((0, 1), (1, 0), (0, -1), (-1, 0)):
                n = (x + dx, y + dy)
                if n not in seen and self.walkable(*n):
                    seen.add(n)
                    todo.append(n)
        self.reachable = seen
        self.cells: dict[str, list[tuple[int, int]]] = {}
        for y in range(H):
            for x in range(W):
                if (x, y) in seen or self.terrain[y][x] == WATER:
                    self.cells.setdefault(self.region[y][x], []).append((x, y))

    # ================================================================== things
    def make(self, kind: str, **state) -> dict:
        """A new thing that isn't anywhere yet (held, or inside something)."""
        k = KINDS[kind]
        e = {"id": self.next_id, "kind": kind, "x": 0, "y": 0}
        if k.get("thermal"):
            e["temp"] = 18.0
        if k.get("fresh"):
            e["fresh"] = float(k["fresh"])
        if k.get("vessel") and "water" not in state:
            e["water"] = 0.0
        if kind == "log":
            e["wet"] = 0.0
        e.update(state)
        self.next_id += 1
        return e

    def add(self, kind: str, x: int, y: int, **state) -> dict:
        e = self.make(kind, **state)
        e["x"], e["y"] = x, y
        self.entities[e["id"]] = e
        self.dirty.add(e["id"])
        return e

    def put(self, e: dict, x: int, y: int):
        """Set something down on the ground."""
        e["x"], e["y"] = x, y
        e.pop("on", None)
        self.entities[e["id"]] = e
        self.dirty.add(e["id"])

    def remove(self, e: dict):
        if self.entities.pop(e["id"], None) is not None:
            self.removed.add(e["id"])
            self.dirty.discard(e["id"])

    def touch(self, e: dict):
        if e["id"] in self.entities:
            self.dirty.add(e["id"])

    def find(self, eid: int) -> dict | None:
        """A thing anywhere: on the ground, carried, or inside something."""
        if eid in self.entities:
            return self.entities[eid]
        for b in self.beings():
            for e in b.carrying:
                if e["id"] == eid:
                    return e
        for c in self.entities.values():
            for e in c.get("items", ()):
                if e["id"] == eid:
                    return e
        return None

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
            elif not self.walkable(x, y) or t in (DOOR, BRIDGE, DOCK, SOIL):
                continue
            if self.at(x, y):
                continue
            return self.add(kind, x, y)
        return None

    def count(self, kind: str) -> int:
        n = 0
        for e in self.entities.values():
            n += e["kind"] == kind
            n += sum(1 for i in e.get("items", ()) if i["kind"] == kind)
        return n

    # ================================================================== geometry
    def reach_ok(self, x: int, y: int) -> bool:
        """Something at (x, y) can be reached: you can stand on it or next to it."""
        r = self.reachable
        return (x, y) in r or any((x + dx, y + dy) in r for dx, dy in ((0, 1), (1, 0), (0, -1), (-1, 0)))

    def walkable(self, x, y) -> bool:
        return 0 <= x < W and 0 <= y < H and self.terrain[y][x] not in BLOCKING

    def at(self, x, y) -> list[dict]:
        return [e for e in self.entities.values() if e["x"] == x and e["y"] == y]

    def place_of(self, x, y) -> str:
        return self.region[y][x]

    def building_of(self, x, y) -> str | None:
        for b in self.buildings:
            if b["x0"] <= x <= b["x1"] and b["y0"] <= y <= b["y1"]:
                return b["name"]
        return None

    def indoors(self, x, y) -> bool:
        return self.building_of(x, y) is not None

    def occupied(self, x, y, me: Being | None = None) -> bool:
        return any(b is not me and (b.x, b.y) == (x, y) for b in self.beings())

    def beings(self) -> list[Being]:
        out = [self.ada, self.wren]
        if self.visitor:
            out.append(self.visitor)
        return out

    def being(self, name: str) -> Being | None:
        n = (name or "").lower()
        if n in (self.ada.name.lower(), "synth", "me"):
            return self.ada
        if n in (self.wren.name.lower(), "companion"):
            return self.wren
        if n in ("friend", "you", "my friend", "visitor"):
            return self.visitor
        return None

    def near(self, a: Being, b: Being | dict, d: int = 1) -> bool:
        bx, by = (b.x, b.y) if isinstance(b, Being) else (b["x"], b["y"])
        return abs(a.x - bx) + abs(a.y - by) <= d

    def path(self, start, goal, me: Being | None = None, adjacent: bool = False, limit: int = 6000,
             avoid: bool = True):
        """A* over the grid. With adjacent=True, stop next to the goal (for things you can't stand on)."""
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
                step = 1 if terrain[ny][nx] in (PATH, BRIDGE, DOCK, FLOOR, DOOR) else 1.3
                if terrain[ny][nx] == SOIL:
                    step = 2.5                               # mind the beds
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

    def holder_of(self, kind: str, frm: tuple[int, int]) -> tuple[dict | None, dict | None]:
        """The nearest container holding a `kind` (and the thing inside it)."""
        best, bd = (None, None), 1e9
        for c in self.entities.values():
            for i in c.get("items", ()):
                if i["kind"] == kind:
                    d = abs(c["x"] - frm[0]) + abs(c["y"] - frm[1])
                    if d < bd:
                        best, bd = (c, i), d
                    break
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

    def free_spot(self, x: int, y: int, radius: int = 3) -> tuple[int, int] | None:
        """An open tile next to (x, y) where something can be set down."""
        for r in range(1, radius + 1):
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    if abs(dx) + abs(dy) != r:
                        continue
                    nx, ny = x + dx, y + dy
                    if self.walkable(nx, ny) and self.terrain[ny][nx] not in (DOOR, BRIDGE) \
                            and not self.at(nx, ny) and not self.occupied(nx, ny):
                        return nx, ny
        return None

    # ================================================================== time, weather, climate
    @property
    def season(self) -> str:
        return SEASONS[((self.day - 1) // 3) % 4]

    def time_of_day(self, day_seconds: float | None = None) -> str:
        if self.phase == "night":
            return "night"
        f = self.phase_t / max(day_seconds or self.day_seconds, 1)
        return "dawn" if f < 0.1 else "morning" if f < 0.4 else "noon" if f < 0.55 else \
            "afternoon" if f < 0.85 else "evening"

    def light(self, day_seconds: float | None = None) -> float:
        if self.phase == "night":
            return 0.2
        f = self.phase_t / max(day_seconds or self.day_seconds, 1)
        if f < 0.1:
            return 0.5 + 0.5 * f / 0.1
        if f > 0.85:
            return 0.5 + 0.5 * max(0.0, 1 - f) / 0.15
        return 1.0

    def outdoor_temperature(self) -> float:
        t = {"spring": 13, "summer": 23, "autumn": 10, "winter": 0}[self.season]
        tod = self.time_of_day()
        t += {"night": -7, "dawn": -5, "morning": -1, "noon": 3, "afternoon": 3, "evening": -2}[tod]
        t -= {"rain": 3, "storm": 4, "snow": 3, "fog": 1, "windy": 2}.get(self.weather, 0)
        return float(t)

    def temperature_at(self, x: int, y: int) -> float:
        b = self.building_of(x, y)
        t = self.indoor[b] if b else self.outdoor_t
        for e in self.entities.values():                      # standing right by a fire
            if e.get("lit") and e["kind"] in ("fireplace", "stove") and abs(e["x"] - x) + abs(e["y"] - y) <= 2:
                t += 6 if e["kind"] == "fireplace" else 3
        return t

    def dark(self, x: int, y: int) -> bool:
        """Too dark to see well: night (or dusk) with no lit lamp, candle or fire close by."""
        if self.light() >= 0.6 and not self.indoors(x, y):
            return False
        if self.light() >= 0.9:
            return False
        b = self.building_of(x, y)
        for e in self.entities.values():
            if e.get("lit") and kind_of(e).get("light"):
                if abs(e["x"] - x) + abs(e["y"] - y) <= kind_of(e)["light"] and self.building_of(e["x"], e["y"]) == b:
                    return False
        for being in self.beings():
            for e in being.carrying:
                if e.get("lit") and abs(being.x - x) + abs(being.y - y) <= 3:
                    return False
        return True

    def raining(self) -> bool:
        return self.weather in WET_WEATHER

    # ================================================================== the world going on by itself
    def advance(self, dt: float):
        self.tick_n += 1
        self.phase_t += dt
        self.weather_left -= dt
        r = self.rng
        if self.weather_left <= 0:
            was = self.weather
            self.weather = r.choice(WEATHER[self.season])
            self.weather_left = r.uniform(150, 420)
            if was in ("rain", "storm") and self.weather in ("clear", "cloudy") and self.phase == "day":
                self.rainbow_until = time.time() + 90
                self.event("rainbow", "The rain stops. A rainbow arches over the hollow!")
            elif self.weather != was:
                self.event("weather", {"rain": "It starts to rain.", "storm": "Thunder rumbles. A storm is coming.",
                                       "snow": "Snow begins to fall.", "fog": "Fog rolls in.",
                                       "windy": "The wind picks up.", "clear": "The sky clears.",
                                       "cloudy": "Clouds cover the sky."}[self.weather])
        self.sounds = []
        if self.tick_n % 4 == 0:
            self.physics(dt * 4)
        self.animals(dt)

    def event(self, kind: str, text: str, **data):
        self.note(text)
        self.events.append({"kind": kind, "text": text, "t": time.time(), **data})
        del self.events[:-60]

    def physics(self, dt: float):
        """One second of heat, fire, water, growth, freshness and light."""
        r = self.rng
        self.outdoor_t = out = self.outdoor_temperature()
        fires = {e["kind"]: e for e in self.entities.values() if e["kind"] in ("fireplace", "stove")}
        # ---- rooms warm and cool
        for b, ins in INSULATED.items():
            target = out + ins
            if b == "house":
                if fires.get("fireplace", {}).get("lit"):
                    target = max(target + 6, 21.0)            # a fire makes the house cosy, not hot
                target += 2 if fires.get("stove", {}).get("lit") else 0
            if b == "greenhouse":
                target += {"clear": 14, "cloudy": 8, "windy": 9}.get(self.weather, 5) * self.light() + 4
            self.indoor[b] += (target - self.indoor[b]) * min(1.0, 0.006 * dt)
        # ---- fires use up their fuel
        for e in fires.values():
            if e.get("lit"):
                e["fuel"] = max(0.0, e.get("fuel", 0) - dt)
                if e["kind"] == "fireplace":
                    self.sounds.append(("the fire crackling", e["x"], e["y"], 6))
                if e["fuel"] <= 0:
                    e["lit"] = False
                    e["ash"] = min(5, e.get("ash", 0) + 1)
                    self.event("fire_out", f"The fire in {kind_of(e)['noun']} burns out.", thing=e["kind"])
                self.touch(e)
        stove_lit = bool(fires.get("stove", {}).get("lit"))
        # ---- lamps and candles burn down
        for holder in [list(self.entities.values())] + [b.carrying for b in self.beings()]:
            for e in holder:
                if e.get("lit") and e["kind"] in ("lamp", "candle"):
                    e["burn"] = e.get("burn", 0) - dt
                    if e["burn"] <= 0:
                        e["lit"], e["burn"] = False, 0
                        self.event("light_out", f"{kind_of(e)['noun'].capitalize()} flickers and goes out.")
                    self.touch(e)
        # ---- things: heat, cooking, freshness, wetness
        wet_out = self.raining() and self.weather != "snow"
        for e in list(self.entities.values()):
            k = kind_of(e)
            indoors = self.indoors(e["x"], e["y"])
            if wet_out and not indoors and (k.get("portable") or e["kind"] in ("bench", "swing")):
                e["wet"] = min(1.0, e.get("wet", 0) + 0.02 * dt)
                self.touch(e)
            elif e.get("wet"):
                dry = 0.004 + (0.01 if indoors and self.indoor.get(self.building_of(e["x"], e["y"]) or "", 0) > 18 else 0)
                e["wet"] = max(0.0, e["wet"] - dry * dt)
                self.touch(e)
            if e["kind"] == "water barrel" and wet_out:
                e["water"] = min(k["vessel"], e.get("water", 0) + 0.05 * dt)
            if e["kind"] in ("pot", "kettle"):
                self._vessel_heat(e, stove_lit and e.get("on") == fires["stove"]["id"], dt)
            elif e["kind"] == "oven":
                self._oven(e, stove_lit, dt)
            elif k.get("thermal"):
                self._cool(e, self.temperature_at(e["x"], e["y"]), dt)
            if k.get("fresh"):
                self._age(e, self.temperature_at(e["x"], e["y"]), dt)
            items = e.get("items")
            if items and e["kind"] not in ("oven",):
                cool = k.get("cool")
                for i in list(items):
                    if kind_of(i).get("thermal") and e["kind"] != "pot":
                        self._cool(i, self.temperature_at(e["x"], e["y"]) - (6 if cool else 0), dt)
                    if kind_of(i).get("fresh"):
                        here = self.temperature_at(e["x"], e["y"])
                        self._age(i, min(here - 8, 11.0) if cool else here, dt, inside=e)   # the pantry stays cool
                    if e["kind"] == "woodpile" and i.get("wet"):
                        i["wet"] = max(0.0, i["wet"] - 0.002 * dt)
        for b in self.beings():
            for i in b.carrying:
                if kind_of(i).get("thermal"):
                    self._cool(i, self.temperature_at(b.x, b.y), dt)
                if kind_of(i).get("fresh"):
                    self._age(i, self.temperature_at(b.x, b.y), dt, holder=b)
            self._being_weather(b, dt)
        # ---- soil and plants
        sun = self.light() * (1.0 if self.weather in ("clear", "windy") else 0.4)
        for pos in self.moisture:
            m = self.moisture[pos]
            in_gh = self.region[pos[1]][pos[0]] == "greenhouse"
            if wet_out and not in_gh:
                m += 0.01 * dt
            m -= (0.0003 + 0.0006 * sun * max(0.0, self.temperature_at(*pos) / 25)) * dt
            self.moisture[pos] = max(0.0, min(1.0, m))
        for e in list(self.entities.values()):
            if e["kind"] == "plant":
                self._grow(e, dt)
            elif e.get("fruit") is not None and k_season(e, self.season) and self.phase == "day" \
                    and r.random() < 0.0025 * dt and e["fruit"] < 5:
                e["fruit"] += 1
                self.touch(e)
            elif e.get("fruit") and not k_season(e, self.season) and r.random() < 0.004 * dt:
                e["fruit"] -= 1                       # the last fruit falls, out of season
                self.touch(e)
        # ---- the hens lay in the morning; the bees make honey while flowers bloom
        tod = self.time_of_day()
        if tod in ("dawn", "morning"):
            box = self.nearest("nest box", (4, 29))
            hens = [e for e in self.entities.values() if e["kind"] == "hen" and e.get("laid") != self.day]
            if box and hens and len(box.get("items", [])) < 6 and r.random() < 0.004 * dt * len(hens) \
                    and self.season != "winter":
                hens[0]["laid"] = self.day                     # one egg a day from each hen
                box.setdefault("items", []).append(self.make("egg"))
                self.event("egg", "A hen clucks proudly. There is a new egg in the nest box.")
                self.touch(box)
        hive = self.nearest("beehive", (62, 24))
        if hive and self.season in ("spring", "summer") and self.phase == "day" and r.random() < 0.0015 * dt:
            hive["honey"] = min(3, hive.get("honey", 0) + 1)
            self.touch(hive)
        # ---- wild things come and go
        if self.tick_n % 40 == 0:
            self._regrow()

    def _cool(self, e: dict, ambient: float, dt: float, rate: float = 0.01):
        t = e.get("temp", ambient)
        e["temp"] = t + (ambient - t) * min(1.0, rate * dt)
        if abs(t - e["temp"]) > 0.3:
            self.touch(e)

    def _vessel_heat(self, e: dict, on_fire: bool, dt: float):
        """A pot or kettle: heats on a lit stove, boils, cooks what's in it, boils dry and burns."""
        water = e.get("water", 0.0)
        if on_fire:
            cap = 100.0 if water > 0 else 260.0
            e["temp"] = min(cap, e.get("temp", 18) + (6.0 if water else 10.0) * dt / max(0.4, water + 0.3))
        else:
            ambient = self.temperature_at(e["x"], e["y"])
            e["temp"] = e.get("temp", ambient) + (ambient - e.get("temp", ambient)) * min(1.0, 0.012 * dt)
        e["steam"] = e["temp"] >= 80 and water > 0
        boiling = e["temp"] >= 99 and water > 0
        if boiling:
            e["water"] = max(0.0, water - 0.004 * dt)
            if e["kind"] == "kettle":
                self.sounds.append(("the kettle whistling", e["x"], e["y"], 8))
                if not e.get("boiled"):
                    e["boiled"] = True
                    self.event("boiled", "The kettle whistles. The water is boiling!")
            else:
                self.sounds.append(("the pot bubbling", e["x"], e["y"], 3))
        if e["kind"] == "pot":
            items = e.get("items", [])
            for i in items:
                i["temp"] = e["temp"]
            raw = [i for i in items if i["kind"] in SOUP_THINGS | {"berries", "egg"}]
            if boiling and raw:
                e["cook"] = e.get("cook", 0.0) + dt
                if e["cook"] >= 40:
                    kinds = {i["kind"] for i in raw}
                    product = next((p for need, p in POT_RECIPES if kinds <= need), None) or "soup"
                    n = len(raw) if product in ("boiled egg",) else max(1, (len(raw) + 1) // 2) if product == "jam" \
                        else len(raw) + 1
                    e["items"] = [i for i in items if i not in raw] + [self.make(product, temp=95.0) for _ in range(n)]
                    e["cook"] = 0.0
                    self.event("cooked", f"The {'soup' if product == 'soup' else product} in the pot is ready!",
                               product=product)
            elif on_fire and water <= 0 and items and e["temp"] > 150:
                e["burn"] = e.get("burn", 0.0) + dt
                if e["burn"] > 25:
                    e["items"] = [self.make("burnt food") for _ in items]
                    e["burn"] = 0.0
                    e["smoke"] = True
                    self.event("burnt", "Smoke! The pot boiled dry and the food burnt.")
        self.touch(e)

    def _oven(self, e: dict, lit: bool, dt: float):
        items = e.get("items", [])
        target = 200.0 if lit else self.temperature_at(e["x"], e["y"])
        e["temp"] = e.get("temp", 18.0) + (target - e.get("temp", 18.0)) * min(1.0, 0.02 * dt)
        if not items:
            return
        if e["temp"] > 150:
            e["bake"] = e.get("bake", 0.0) + dt
            kinds = [i["kind"] for i in items]
            if e["bake"] >= 60 and not e.get("baked"):
                out, left = [], list(kinds)
                for need, product in OVEN_RECIPES:
                    while all(left.count(n) >= need.count(n) for n in set(need)):
                        for n in need:
                            left.remove(n)
                        out.append(product)
                out += [k for k in left]
                e["items"] = [self.make(k, temp=180.0) for k in out]
                e["baked"] = True
                made = [k for k in out if k not in kinds]
                if made:
                    self.event("baked", f"A warm smell fills the kitchen: {_and([KINDS[k]['noun'] for k in made])} "
                                        f"{'is' if len(made) == 1 else 'are'} ready in the oven!", products=made)
            elif e["bake"] >= 170:
                e["items"] = [self.make("burnt food") for _ in items]
                e["bake"], e["baked"] = 0.0, False
                self.event("burnt", "Smoke comes out of the oven. Everything inside has burnt!")
        for i in e.get("items", []):
            i["temp"] = e["temp"]
        e["steam"] = bool(e.get("items")) and e["temp"] > 120
        self.touch(e)

    def _age(self, e: dict, temp: float, dt: float, inside: dict | None = None, holder: Being | None = None) -> bool:
        """Food keeps for a while, longer when cool. Returns True if it rotted."""
        rate = max(0.25, 1.0 + (temp - 18) / 12)
        e["fresh"] = e.get("fresh", 1000.0) - rate * dt
        if e["fresh"] > 0:
            return False
        rotten = self.make("rotten food")
        noun = KINDS[e["kind"]]["noun"]
        if inside is not None:
            inside["items"] = [rotten if i is e else i for i in inside["items"]]
        elif holder is not None:
            holder.carrying = [rotten if i is e else i for i in holder.carrying]
        else:
            self.remove(e)
            if e["kind"] != "flower":
                self.add("rotten food", e["x"], e["y"])
        self.event("rotted", f"{_cap(noun.replace('a ', 'the ', 1).replace('some ', 'the ', 1))} went bad.")
        return True

    def _being_weather(self, b: Being, dt: float):
        indoors = self.indoors(b.x, b.y) or self.terrain[b.y][b.x] == DOCK and self.region[b.y][b.x] == "porch"
        if self.raining() and not indoors and self.weather != "snow":
            b.wet = min(1.0, b.wet + 0.03 * dt)
            b.needs["clean"] = max(0.0, b.needs["clean"] - 0.02 * dt)     # muddy
        elif b.wet:
            warm = self.temperature_at(b.x, b.y)
            b.wet = max(0.0, b.wet - (0.004 + max(0.0, warm - 15) * 0.0015) * dt)

    def _grow(self, e: dict, dt: float):
        x, y = e["x"], e["y"]
        m = self.moisture.get((x, y), 0.0)
        t = self.temperature_at(x, y)
        before = int(e["stage"])
        if self.phase == "day" and m > 0.15 and t > 5 and e["stage"] < 4:
            e["stage"] = min(4.0, e["stage"] + 0.0045 * dt * (1.3 if m > 0.5 else 1.0) * (1.2 if t > 15 else 0.8))
        if m < 0.05 and self.phase == "day" and t > 12:
            e["health"] = max(0.0, e["health"] - 0.0006 * dt)
            e["thirsty"] = True
        else:
            e.pop("thirsty", None)
            e["health"] = min(1.0, e["health"] + 0.0005 * dt)
        if t < 0 and e["crop"] not in ("wheat",):
            e["health"] = max(0.0, e["health"] - 0.004 * dt)
        if e["health"] <= 0:
            self.remove(e)
            self.add("leaf", x, y) if self.walkable(x, y) else None
            self.event("plant_died", f"The {e['crop']} plant {'froze' if t < 0 else 'dried out'} and died.")
            return
        if int(e["stage"]) != before:
            e["glyph"] = KINDS["plant"]["stages"][int(e["stage"])] if e["stage"] < 4 else KINDS[e["crop"]]["glyph"]
            if e["stage"] >= 4:
                self.event("ripe", f"The {e['crop']} {'is' if e['crop'] not in ('beans',) else 'are'} ripe!", crop=e["crop"])
            self.touch(e)

    def _regrow(self):
        r = self.rng
        counts: dict[str, int] = {}
        for e in self.entities.values():
            counts[e["kind"]] = counts.get(e["kind"], 0) + 1
        s = self.season
        for kind, region, cap, chance, ok in (
                ("mushroom", "woods", 5, 0.2 if s == "autumn" or self.raining() else 0.05, s != "winter"),
                ("stick", "woods", 5, 0.1, True), ("pinecone", "woods", 4, 0.08, True),
                ("leaf", "woods", 6, 0.3 if s == "autumn" else 0.03, s != "winter"),
                ("flower", "meadow", 8, 0.15, s in ("spring", "summer")), ("stone", "stream", 4, 0.05, True),
                ("clay", "pond", 3, 0.05, True), ("feather", "coop", 2, 0.04, True)):
            if ok and counts.get(kind, 0) < cap and r.random() < chance:
                self.spawn_near(kind, region, on=SAND if kind in ("stone", "clay") else None)
        for e in [e for e in self.entities.values() if e.get("fruit") and e["kind"].endswith("tree")]:
            if r.random() < 0.02:                     # ripe fruit drops to the ground
                spot = self.free_spot(e["x"], e["y"], 1)
                if spot:
                    e["fruit"] -= 1
                    self.add(KINDS[e["kind"]]["fruit"], *spot)
                    self.touch(e)

    # ================================================================== animals
    def animals(self, dt: float):
        r = self.rng
        tod = self.time_of_day()
        night = self.phase == "night"
        if tod == "dawn" and not getattr(self, "_crowed", False) and self.phase_t > 5:
            self._crowed = True
            rooster = self.nearest("rooster", (5, 35))
            if rooster:
                self.sounds.append(("the rooster crowing", rooster["x"], rooster["y"], 40))
                self.event("rooster", "Cock-a-doodle-doo! The rooster greets the morning.")
        if tod != "dawn":
            self._crowed = False
        if self.tick_n % 2:
            return
        for e in list(self.entities.values()):
            k = e["kind"]
            if not KINDS.get(k, {}).get("creature"):
                continue
            if k == "cat":
                self._cat(e, dt)
            elif k in ("hen", "rooster"):
                if night:
                    self._step_toward(e, (5, 30), within=("coop",))
                elif r.random() < 0.3:
                    self._wander(e, ("coop",))
                if k == "hen" and not night and r.random() < 0.004:
                    self.sounds.append(("a hen clucking", e["x"], e["y"], 6))
            elif k in ("fish", "duck"):
                if r.random() < 0.4:
                    self._swim(e)
                if k == "duck" and r.random() < 0.003:
                    self.sounds.append(("a duck quacking", e["x"], e["y"], 10))
            elif k == "frog":
                if r.random() < 0.15:
                    self._wander(e, ("pond",))
                if tod in ("evening", "night") and r.random() < 0.01:
                    self.sounds.append(("frogs croaking", e["x"], e["y"], 12))
            elif k == "bee":
                if night or self.season == "winter" or self.raining():
                    self._step_toward(e, (62, 25))
                elif r.random() < 0.7:
                    self._wander(e, ("meadow",))
                    self.sounds.append(("bees buzzing", e["x"], e["y"], 3))
            elif k == "butterfly":
                if self.season in ("spring", "summer") and not night and r.random() < 0.7:
                    self._wander(e, ("meadow", "garden", "orchard"))
            elif k == "robin":
                feeder = self.nearest("bird feeder", (16, 40))
                if feeder and feeder.get("items") and r.random() < 0.02:
                    feeder["items"].pop()                      # a robin eats a seed
                    self.touch(feeder)
                if r.random() < 0.4:
                    self._wander(e, ("garden", "yard", "orchard"))
                if tod in ("dawn", "morning") and r.random() < 0.02:
                    self.sounds.append(("a robin singing", e["x"], e["y"], 14))
            elif k == "deer":
                close = any(abs(b.x - e["x"]) + abs(b.y - e["y"]) <= 4 for b in self.beings())
                if close or tod not in ("dawn", "evening"):
                    self.remove(e)                             # it bounds away into the trees
                    if close:
                        self.event("deer", "A deer looks up, then leaps away into the woods.")
                elif r.random() < 0.2:
                    self._wander(e, ("woods", "meadow"))
            elif k == "owl":
                if not night:
                    self.remove(e)
                elif r.random() < 0.01:
                    self.sounds.append(("an owl hooting", e["x"], e["y"], 20))
            elif k == "hedgehog":
                if not night:
                    self.remove(e)
                elif r.random() < 0.3:
                    self._wander(e, ("garden", "yard"))
        # visitors of dusk and night
        if tod in ("dawn", "evening") and not any(e["kind"] == "deer" for e in self.entities.values()) and r.random() < 0.004:
            self.spawn_near("deer", "woods")
        if night and not any(e["kind"] == "owl" for e in self.entities.values()) and r.random() < 0.01:
            self.spawn_near("owl", "woods")
        if night and self.season != "winter" and not any(e["kind"] == "hedgehog" for e in self.entities.values()) \
                and r.random() < 0.004:
            self.spawn_near("hedgehog", "garden")

    def _cat(self, e: dict, dt: float):
        """Moss: eats when hungry, then finds the warmest spot and sleeps; sometimes follows someone."""
        r = self.rng
        e["hunger"] = min(100.0, e.get("hunger", 30.0) + 0.04 * dt * 2)
        bowl = self.nearest("cat bowl", (23, 25))
        if e["hunger"] > 60:
            e["state"] = "hungry"
            if bowl and bowl.get("items"):
                if abs(bowl["x"] - e["x"]) + abs(bowl["y"] - e["y"]) <= 1:
                    food = bowl["items"].pop()
                    e["hunger"] = max(0.0, e["hunger"] - 60)
                    self.touch(bowl)
                    self.event("cat_ate", f"Moss eats {KINDS[food['kind']]['noun'].split(' ', 1)[-1]} from the bowl and licks its whiskers.")
                else:
                    self._step_toward(e, (bowl["x"], bowl["y"]))
            else:
                target = min(self.beings(), key=lambda b: abs(b.x - e["x"]) + abs(b.y - e["y"]))
                if abs(target.x - e["x"]) + abs(target.y - e["y"]) > 1:
                    self._step_toward(e, (target.x, target.y))
                if r.random() < 0.03:
                    self.sounds.append(("Moss meowing", e["x"], e["y"], 6))
            self.touch(e)
            return
        fire = self.nearest("fireplace", (13, 23))
        if fire and fire.get("lit"):
            e["state"] = "asleep by the fire"
            if abs(fire["x"] - e["x"]) + abs(fire["y"] - e["y"]) > 1:
                self._step_toward(e, (fire["x"] + 1, fire["y"]))
        elif self.phase == "night":
            e["state"] = "asleep"
        elif r.random() < 0.08:
            e["state"] = "exploring"
            self._wander(e, ("living room", "kitchen", "little bedroom", "porch", "yard", "garden"))
        elif r.random() < 0.01:
            e["state"] = "asleep in a sunny spot"
        self.touch(e)

    def _step_toward(self, e: dict, goal, within=None):
        p = self.path((e["x"], e["y"]), goal, adjacent=False, limit=400, avoid=True)
        if p:
            nx, ny = p[0]
            if within is None or self.region[ny][nx] in within or self.region[e["y"]][e["x"]] not in within:
                e["x"], e["y"] = nx, ny
                self.touch(e)

    def _wander(self, e: dict, regions):
        dx, dy = self.rng.choice(list(DIRS.values()))
        nx, ny = e["x"] + dx, e["y"] + dy
        if self.walkable(nx, ny) and not self.occupied(nx, ny) and self.terrain[ny][nx] not in (DOOR, SOIL) \
                and (self.region[ny][nx] in regions or self.region[e["y"]][e["x"]] not in regions):
            e["x"], e["y"] = nx, ny
            self.touch(e)

    def _swim(self, e: dict):
        dx, dy = self.rng.choice(list(DIRS.values()))
        nx, ny = e["x"] + dx, e["y"] + dy
        if 0 <= nx < W and 0 <= ny < H and self.terrain[ny][nx] == WATER and self.region[ny][nx] == "pond":
            e["x"], e["y"] = nx, ny
            self.touch(e)

    def note(self, text: str):
        self.log.append(text)
        del self.log[:-40]

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

    # ================================================================== the synth's own state
    @property
    def needs(self) -> dict:
        return self.ada.needs

    def describe(self, b: Being) -> str:
        if b is self.visitor:
            return "my friend"
        return b.name

    # ================================================================== senses
    def _rel(self, x, y, me: Being | None = None) -> str:
        a = me or self.ada
        dx, dy = x - a.x, y - a.y
        if dx == 0 and dy == 0:
            return "here"
        if abs(dx) + abs(dy) == 1:
            return "right next to me"
        parts = []
        if dy:
            parts.append(f"{abs(dy)} {'north' if dy < 0 else 'south'}")
        if dx:
            parts.append(f"{abs(dx)} {'west' if dx < 0 else 'east'}")
        return " and ".join(parts)

    def feelings(self, me: Being | None = None) -> list[str]:
        b = me or self.ada
        n = b.needs
        out = []
        for need, low, word in (("energy", 35, "hungry"), ("water", 35, "thirsty"), ("rest", 25, "tired"),
                                ("warmth", 35, "cold"), ("company", 30, "lonely"), ("fun", 30, "bored"),
                                ("clean", 25, "dirty")):
            if n[need] < low:
                out.append(("very " if n[need] < low / 2 else "") + word)
        if b.wet > 0.4:
            out.append("wet")
        if not out and min(n.values()) > 70:
            out.append("happy")
        return out

    def describe_thing(self, e: dict) -> str:
        """'a hot cup of tea', 'the stove (lit)', 'a wet log', 'a ripe carrot plant'."""
        k = kind_of(e)
        noun = k.get("noun", e["kind"])
        if e["kind"] == "plant":
            st = int(e.get("stage", 0))
            if st >= 4:
                return f"a ripe {e['crop']} plant" if e["crop"] not in ("beans", "wheat") else f"ripe {e['crop']}"
            base = f"{e['crop']} {'seedling' if st <= 1 else 'plant'}"
            return ("a thirsty " if e.get("thirsty") else "a ") + base
        if e["kind"] == "cat":
            return f"Moss the cat ({e.get('state', 'awake')})"
        words = []
        if e.get("temp") is not None and k.get("thermal"):
            t = e["temp"]
            if t >= 70:
                words.append("hot")
            elif t >= 35:
                words.append("warm")
            elif t <= 3:
                words.append("cold")
        if e.get("wet", 0) > 0.35:
            words.append("wet")
        if k.get("fresh") and e.get("fresh", 1e9) < k["fresh"] * 0.25:
            words.append("old" if k["is_a"] != "plant" else "wilted")
        if words and noun.split(" ", 1)[0] in ("a", "an", "some", "the"):
            art, rest = noun.split(" ", 1)
            art = "a" if art == "an" else art
            noun = f"{art} {' '.join(words)} {rest}"
            if art == "a" and words[0][0] in "aeiou":
                noun = "an" + noun[1:]
        if e.get("lit"):
            noun += " that is burning" if e["kind"] in ("fireplace", "stove", "candle") else " that is lit"
        if e.get("fruit"):
            fruit = KINDS[k["fruit"]]["noun"].split(" ", 1)[-1]
            noun += f" with {e['fruit']} {fruit}{'s' if e['fruit'] > 1 and not fruit.endswith('s') else ''}"
        if e["kind"] in ("pot", "kettle", "bucket", "watering can", "water barrel") and e.get("water", 0) > 0.05:
            noun += " of water" if e["kind"] not in ("water barrel",) else " full of rainwater"
        if e.get("steam"):
            noun += ", steaming"
        if e.get("items") and e["kind"] in ("pot", "oven", "basket", "cat bowl", "nest box", "bird feeder"):
            noun += " with " + _and([KINDS[i["kind"]]["noun"] for i in e["items"]][:4]) + " in it"
        return noun

    def perceive(self, day_seconds: float | None = None, radius: int = 6, me: Being | None = None) -> str:
        """Everything a mind senses, in its own words (the synth's by default)."""
        a = me or self.ada
        place = self.place_of(a.x, a.y)
        dark = self.dark(a.x, a.y)
        temp = self.temperature_at(a.x, a.y)
        feel = "cold" if temp < 8 else "cool" if temp < 15 else "warm" if temp < 26 else "hot"
        s = [f"It is {self.time_of_day(day_seconds)} on day {self.day}, in {self.season}. "
             f"{'Outside the' if self.indoors(a.x, a.y) else 'The'} weather is {self.weather}. "
             f"I am {where(place)}. It is {feel} here."]
        if dark:
            s.append("It is dark. I can't see much.")
            radius = 2
        f = self.feelings(a)
        s.append("I feel " + " and ".join(f) + "." if f else "I feel fine.")
        if a.carrying:
            s.append("I carry " + _and([self.describe_thing(e) for e in a.carrying]) + ".")
        seen = []
        b_here = self.building_of(a.x, a.y)
        for e in sorted(self.entities.values(), key=lambda e: abs(e["x"] - a.x) + abs(e["y"] - a.y)):
            d = abs(e["x"] - a.x) + abs(e["y"] - a.y)
            if d > radius or len(seen) >= 5:
                break
            if self.building_of(e["x"], e["y"]) != b_here and d > 1:
                continue                                   # walls hide what is on the other side
            if e["kind"] in ("rug", "window", "clock"):
                continue
            seen.append(f"{self.describe_thing(e)} {self._rel(e['x'], e['y'], a)}")
        if seen:
            s.append("I see " + "; ".join(seen) + ".")
        for b in self.beings():
            if b is a:
                continue
            d = abs(b.x - a.x) + abs(b.y - a.y)
            if d <= radius and (self.building_of(b.x, b.y) == b_here or d <= 2):
                doing = f", {b.activity}" if b.activity else (", asleep" if b.sleeping else "")
                s.append(f"{_cap(self.describe(b))} is {self._rel(b.x, b.y, a)}{doing}.")
        heard = self.hearing(a)
        if heard:
            s.append("I hear " + _and(heard) + ".")
        if self.rainbow_until > time.time() and not self.indoors(a.x, a.y):
            s.append("There is a rainbow in the sky.")
        now = time.time()
        for t, who, words in self.heard[-2:] if a is self.ada else []:
            if now - t < 30:
                s.append(f'{_cap(who)} said: "{words}"')
        return " ".join(s)

    def hearing(self, a: Being) -> list[str]:
        out = []
        b_here = self.building_of(a.x, a.y)
        for what, x, y, far in self.sounds:
            d = abs(x - a.x) + abs(y - a.y)
            if d <= far and (self.building_of(x, y) == b_here or d <= far // 2) and what not in out:
                out.append(what)
        if self.raining() and self.weather != "snow" and b_here:
            out.append("rain on the roof")
        if self.weather == "storm" and self.rng.random() < 0.3:
            out.append("thunder")
        for b in self.beings():
            if b is not a and b.activity.startswith("playing the piano") and abs(b.x - a.x) + abs(b.y - a.y) <= 12:
                out.append("piano music")
        return out[:4]

    def hear(self, who: str, words: str):
        self.heard.append((time.time(), who, words[:200]))
        del self.heard[:-6]

    # ================================================================== needs
    def update_needs(self, dt: float):
        for b in (self.ada, self.wren):
            self._needs(b, dt)

    def _needs(self, a: Being, dt: float):
        n = a.needs
        k = dt / 0.25 * a.rates
        n["energy"] -= (0.008 if a.sleeping else 0.022) * k
        n["water"] -= (0.008 if a.sleeping else 0.026) * k
        n["rest"] += (0.5 if a.sleeping else -0.015) * k
        warm = self.temperature_at(a.x, a.y) - a.wet * 8
        if a.sleeping and self.terrain[a.y][a.x] == FLOOR:
            warm += 6                                      # tucked in under a blanket
        n["warmth"] += (0.25 if warm >= 16 else -0.1 * (16 - warm) / 10) * k
        other = self.wren if a is self.ada else self.ada
        together = abs(other.x - a.x) + abs(other.y - a.y) <= 4 and not other.sleeping
        n["company"] += (0.05 if together else -0.02 if not a.sleeping else 0.0) * k
        if a.engaged is not None:
            n["company"] += 0.12 * k
        n["fun"] -= (0.0 if a.sleeping else 0.02) * k
        n["clean"] -= 0.006 * k
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
            self.event("visitor", "My friend comes to visit!")
        return self.visitor

    def move_visitor(self, fx: float, fy: float, facing: str | None = None):
        """You walk freely; your tile is the nearest walkable one to where you are."""
        v = self.visitor
        if not v:
            return
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
                self.put(e, v.x, v.y)
            self.event("visitor", "My friend waves goodbye and leaves.")
        self.visitor = None

    # ================================================================== serialisation
    def kinds_table(self) -> dict:
        out = {}
        for k, v in KINDS.items():
            out[k] = {"glyph": v["glyph"], "color": v.get("hex", "#cccccc"), "noun": v["noun"],
                      "size": "creature" if v.get("creature") else ("small" if v.get("portable") else "big")}
            if v.get("fruit"):
                out[k]["fruit"] = KINDS[v["fruit"]]["glyph"]
            if v.get("light"):
                out[k]["light"] = v["light"]
        return out

    @staticmethod
    def public(e: dict) -> dict:
        """An entity as the page sees it: what's inside is summarised, numbers rounded."""
        out = {k: v for k, v in e.items() if k != "items"}
        if "items" in e:
            out["contents"] = [i["kind"] for i in e["items"]]
        for k in ("temp", "wet", "fresh", "water", "stage", "health", "fuel", "burn", "hunger", "cook", "bake"):
            if isinstance(out.get(k), float):
                out[k] = round(out[k], 1 if k in ("temp", "fuel", "burn", "hunger") else 2)
        return out

    def snapshot(self, full: bool = False, day_seconds: float = 600.0, night_seconds: float = 1200.0) -> dict:
        now = time.time()

        def being(b: Being | None):
            if b is None:
                return None
            d = {"name": b.name, "x": b.x, "y": b.y, "facing": b.facing, "sleeping": b.sleeping,
                 "talking": b.engaged is not None, "wet": round(b.wet, 2), "activity": b.activity,
                 "carrying": [e["kind"] for e in b.carrying], "said": b.said if now < b.said_until else ""}
            if b.fx is not None:
                d["fx"], d["fy"] = round(b.fx, 2), round(b.fy, 2)
            return d

        span = day_seconds if self.phase == "day" else night_seconds
        a, wr = self.ada, self.wren
        out = {
            "tick": self.tick_n, "day": self.day, "phase": self.phase, "season": self.season,
            "weather": self.weather, "time": self.time_of_day(day_seconds), "light": round(self.light(day_seconds), 3),
            "sun": round(min(1.0, self.phase_t / max(span, 1)), 4),
            "temperature": round(self.outdoor_t, 1), "terrain_v": self.terrain_v,
            "env": {"outdoor": round(self.outdoor_t, 1), "rooms": {k: round(v, 1) for k, v in self.indoor.items()},
                    "rainbow": self.rainbow_until > now, "sounds": [s[0] for s in self.sounds][:8]},
            "ada": being(a) | {"place": self.place_of(a.x, a.y), "needs": {k: round(v, 1) for k, v in a.needs.items()},
                               "feelings": self.feelings(), "dark": self.dark(a.x, a.y),
                               "temp_here": round(self.temperature_at(a.x, a.y), 1)},
            "companion": being(wr) | {"place": self.place_of(wr.x, wr.y), "role": "companion",
                                      "needs": {k: round(v, 1) for k, v in wr.needs.items()},
                                      "feelings": self.feelings(wr)},
            "visitor": being(self.visitor),
            "people": [being(wr) | {"role": "companion", "color": "#7fb3a6", "hat": "#3d5a80", "glyph": "🧑‍🌾",
                                    "friendship": round(self.bond, 1)}],
            "bond": round(self.bond, 1),
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
                       kinds=self.kinds_table(), ents=[self.public(e) for e in self.entities.values()], removed=[],
                       creations=self.creations[-300:])
        else:
            out["ents"] = [self.public(self.entities[i]) for i in self.dirty if i in self.entities]
            out["removed"] = list(self.removed)
        self.dirty.clear()
        self.removed.clear()
        return out

    def state(self) -> dict:
        def being(b: Being):
            return {"x": b.x, "y": b.y, "carrying": b.carrying, "sleeping": b.sleeping, "needs": b.needs, "wet": b.wet}

        return {"version": 3, "W": W, "H": H, "terrain": self.terrain, "entities": list(self.entities.values()),
                "next_id": self.next_id, "tick": self.tick_n, "day": self.day, "phase": self.phase,
                "phase_t": self.phase_t, "weather": self.weather, "indoor": self.indoor,
                "moisture": [[x, y, round(m, 3)] for (x, y), m in self.moisture.items()],
                "visited": sorted(self.visited), "firsts": sorted(self.firsts), "read": sorted(self.read_books),
                "creations": self.creations, "bond": self.bond, "ada": being(self.ada), "wren": being(self.wren)}

    def load_state(self, s: dict):
        if s.get("version", 1) < 3 or s.get("W") != W or s.get("H") != H:
            # A world from before the homestead: keep what the synth has lived, not the old map.
            self.day = s.get("day", 1)
            self.firsts = set(s.get("firsts", []))
            self.creations = s.get("creations", [])
            self.event("moved", "We have moved to a new home in a quiet hollow, just the two of us.")
            return
        self.terrain = s["terrain"]
        self.terrain_v += 1
        self.entities = {e["id"]: e for e in s["entities"]}
        self.next_id, self.tick_n, self.day = s["next_id"], s["tick"], s["day"]
        self.phase, self.phase_t, self.weather = s["phase"], s["phase_t"], s["weather"]
        self.indoor.update(s.get("indoor", {}))
        for x, y, m in s.get("moisture", []):
            self.moisture[(x, y)] = m
        self.visited, self.firsts = set(s["visited"]), set(s["firsts"])
        self.read_books = set(s.get("read", []))
        self.creations = s.get("creations", [])
        self.bond = s.get("bond", self.bond)
        for b, d in ((self.ada, s.get("ada")), (self.wren, s.get("wren"))):
            if d:
                b.x, b.y, b.carrying, b.sleeping = d["x"], d["y"], d["carrying"], d["sleeping"]
                b.needs.update(d.get("needs", {}))
                b.wet = d.get("wet", 0.0)


def k_season(e: dict, season: str) -> bool:
    return season in KINDS[e["kind"]].get("season", [])


def where(place: str) -> str:
    """'kitchen' -> 'in the kitchen', 'pond' -> 'by the pond', 'porch' -> 'on the porch'."""
    return {"pond": "by the pond", "stream": "by the stream", "porch": "on the porch", "yard": "in the yard",
            "lookout": "at the lookout on the hill", "little bedroom": "in my little bedroom",
            "meadow": "in the meadow", "house": "in the house"}.get(place, f"in the {place}")


def _facing(x, y, nx, ny) -> str:
    return "east" if nx > x else "west" if nx < x else "south" if ny > y else "north"


def _and(items: list[str]) -> str:
    items = list(items)
    if not items:
        return ""
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]
