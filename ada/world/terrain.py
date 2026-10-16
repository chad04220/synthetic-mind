"""Endless, deterministic terrain from a seed.

The world is an unbounded grid of integer tiles (x grows east, y grows south), cut into 32×32
chunks (``cx = x // 32``). Everything here is a pure function of ``(seed, x, y)``: the same seed
gives the same world on every machine and every run. Python's ``hash()`` is never used (it is
salted per process); all randomness comes from a stable 64-bit integer hash.

Per tile:
- ``h``      height in decimetres (negative under water),
- ``biome``  an index into ``BIOMES``,
- ``water``  0 none, 1 shallow (wadeable), 2 deep (blocks), 3 river (wadeable, flowing),
- ``feat``   an index into ``FEATURES`` (0 none): trees, bushes, rocks, grass, walls…,
- ``temp``   the base air temperature in °C (before season, time of day and weather).

Points of interest (ruins, cabins, caves, standing stones, springs, lookout hills, beehives,
nests, wells) are placed by hashed chance per chunk, entirely inside their chunk, each with a
generated name. Home, a small cabin at the origin on a meadow by a pond, is stamped on top.

Feature changes made by the World (a felled tree becomes a stump) are kept as diffs here, apart
from the generated data, so they persist and the generator stays pure.
"""
from __future__ import annotations

import random
from collections import OrderedDict

import numpy as np

CHUNK = 32
AREA = CHUNK * CHUNK

BIOMES = ["ocean", "lake", "beach", "meadow", "grassland", "forest", "pine_forest", "jungle", "swamp",
          "desert", "savanna", "tundra", "snow", "mountain", "rock"]
B = {name: i for i, name in enumerate(BIOMES)}

FEATURES = ["none", "oak", "birch", "pine", "palm", "cactus", "jungle_tree", "dead_tree", "apple_tree", "acacia",
            "stump", "berry_bush", "bush", "rock", "boulder", "tall_grass", "flowers", "reeds", "fern", "snow_drift",
            "wall", "door", "floor", "stone_wall", "rubble", "cave_wall", "cave_floor", "standing_stone", "well",
            "cairn", "spring"]
F = {name: i for i, name in enumerate(FEATURES)}

TREES = {F[k] for k in ("oak", "birch", "pine", "palm", "jungle_tree", "dead_tree", "apple_tree", "acacia")}
BLOCKING = TREES | {F[k] for k in ("cactus", "berry_bush", "bush", "rock", "boulder", "wall", "stone_wall",
                                    "cave_wall", "standing_stone", "well", "cairn")}
SHELTER = {F["floor"], F["cave_floor"]}       # roofed: dry, sheltered from wind
WATER_NONE, WATER_SHALLOW, WATER_DEEP, WATER_RIVER = 0, 1, 2, 3

HOME = (0, 0)
HOME_NAME = "my cabin"

# ---------------------------------------------------------------------- stable hashing
_M64 = (1 << 64) - 1


def shash(*vals) -> int:
    """A stable 64-bit hash of integers and strings (same on every platform and run)."""
    h = 0x243F6A8885A308D3
    for v in vals:
        if isinstance(v, str):
            for ch in v.encode():
                h = ((h ^ ch) * 0x100000001B3) & _M64
            v = len(v)
        h = (h ^ (int(v) & _M64)) & _M64
        h = (h * 0x9E3779B97F4A7C15) & _M64
        h ^= h >> 31
        h = (h * 0xBF58476D1CE4E5B9) & _M64
        h ^= h >> 29
    return h


_U = np.uint64


def _hash2(ix: np.ndarray, iy: np.ndarray, salt: int) -> np.ndarray:
    h = ix.astype(_U) * _U(0x9E3779B97F4A7C15) ^ iy.astype(_U) * _U(0xC2B2AE3D27D4EB4F) ^ _U(salt & _M64)
    h ^= h >> _U(31)
    h *= _U(0xBF58476D1CE4E5B9)
    h ^= h >> _U(29)
    h *= _U(0x94D049BB133111EB)
    h ^= h >> _U(32)
    return h


def _unit(h: np.ndarray) -> np.ndarray:
    return (h >> _U(11)).astype(np.float64) * (1.0 / 9007199254740992.0)


def _value_noise(X: np.ndarray, Y: np.ndarray, salt: int) -> np.ndarray:
    x0, y0 = np.floor(X), np.floor(Y)
    fx, fy = X - x0, Y - y0
    ix, iy = x0.astype(np.int64), y0.astype(np.int64)
    sx, sy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    a = _unit(_hash2(ix, iy, salt))
    b = _unit(_hash2(ix + 1, iy, salt))
    c = _unit(_hash2(ix, iy + 1, salt))
    d = _unit(_hash2(ix + 1, iy + 1, salt))
    return a + (b - a) * sx + (c - a) * sy + (a - b - c + d) * sx * sy


def _fbm(x: np.ndarray, y: np.ndarray, freq: float, octaves: int, salt: int) -> np.ndarray:
    total, amp, norm = 0.0, 1.0, 0.0
    for o in range(octaves):
        total = total + amp * _value_noise(x * freq + o * 17.13, y * freq - o * 31.7, salt + o * 7919)
        norm += amp
        amp *= 0.5
        freq *= 2.03
    return total / norm


# Quantiles of each fBm (measured over 400k random points) so every field is ~uniform in [0, 1].
_Q = np.linspace(0, 1, 21)
_Q_ELEV = np.array([0.1298, 0.3387, 0.372, 0.3955, 0.4147, 0.4314, 0.4466, 0.4609, 0.4744, 0.4876, 0.5006,
                    0.5136, 0.5266, 0.5401, 0.5543, 0.5695, 0.5862, 0.6056, 0.6294, 0.6633, 0.8691])
_Q_CONT = np.array([0.0557, 0.2702, 0.3155, 0.3483, 0.375, 0.3993, 0.4214, 0.4424, 0.4624, 0.4818, 0.5009,
                    0.52, 0.5397, 0.5595, 0.5803, 0.6022, 0.6264, 0.6539, 0.6862, 0.7319, 0.9523])
_Q_MOIST = np.array([0.0766, 0.2836, 0.3267, 0.3573, 0.3827, 0.4054, 0.4261, 0.4458, 0.4645, 0.4826, 0.5006,
                     0.5184, 0.5366, 0.5553, 0.5747, 0.5953, 0.618, 0.6434, 0.6741, 0.7166, 0.9333])
_Q_TEMP = np.array([0.0347, 0.2687, 0.3142, 0.3475, 0.3748, 0.3989, 0.4209, 0.4417, 0.4616, 0.4812, 0.5005,
                    0.5197, 0.5392, 0.5592, 0.5798, 0.6019, 0.626, 0.6529, 0.6855, 0.7309, 0.9545])

SEA = 0.20            # uniform elevation below which there is water
DEEP = 0.165          # below which the water is deep
OCEAN_C = 0.32        # low continentalness: water there is the sea, elsewhere lakes

# feature probabilities per biome (cumulative bands drawn from one per-tile random number)
BIOME_FEATURES = {
    "meadow": [("flowers", 0.10), ("tall_grass", 0.12), ("oak", 0.02), ("birch", 0.01), ("apple_tree", 0.006),
               ("berry_bush", 0.015), ("bush", 0.02), ("rock", 0.008)],
    "grassland": [("tall_grass", 0.22), ("flowers", 0.03), ("bush", 0.02), ("oak", 0.01), ("rock", 0.01),
                  ("berry_bush", 0.008)],
    "forest": [("oak", 0.26), ("birch", 0.08), ("apple_tree", 0.008), ("berry_bush", 0.03), ("bush", 0.03),
               ("fern", 0.08), ("rock", 0.006)],
    "pine_forest": [("pine", 0.34), ("berry_bush", 0.02), ("rock", 0.02), ("fern", 0.04), ("boulder", 0.006)],
    "jungle": [("jungle_tree", 0.32), ("palm", 0.04), ("fern", 0.15), ("bush", 0.04), ("flowers", 0.03)],
    "swamp": [("reeds", 0.18), ("dead_tree", 0.05), ("bush", 0.03), ("tall_grass", 0.10), ("berry_bush", 0.008)],
    "desert": [("cactus", 0.03), ("rock", 0.02), ("dead_tree", 0.004), ("boulder", 0.004)],
    "savanna": [("tall_grass", 0.16), ("acacia", 0.03), ("bush", 0.02), ("rock", 0.01)],
    "beach": [("palm", 0.015), ("rock", 0.01)],
    "tundra": [("rock", 0.03), ("snow_drift", 0.04), ("bush", 0.02), ("berry_bush", 0.012), ("tall_grass", 0.03)],
    "snow": [("snow_drift", 0.10), ("rock", 0.02), ("pine", 0.015)],
    "mountain": [("rock", 0.12), ("boulder", 0.06), ("pine", 0.03)],
    "rock": [("boulder", 0.05), ("rock", 0.10)],
}
_BF = {B[b]: [(F[f], p) for f, p in lst] for b, lst in BIOME_FEATURES.items()}

# ---------------------------------------------------------------------- books
BOOKS = [
    ("The Water Cycle", "The sun warms the sea and lakes, and water rises into the air as vapour. High up it cools "
     "and becomes clouds. When the drops in a cloud grow heavy, they fall as rain or snow. The rain runs into "
     "streams, the streams into rivers, and the rivers back to the sea. Then it all begins again."),
    ("The Tortoise and the Hare", "A hare laughed at a slow tortoise, so the tortoise asked for a race. The hare "
     "ran far ahead, then lay down to nap, sure he would win. The tortoise walked on and on without stopping. "
     "When the hare woke, the tortoise was already at the finish. Slow and steady wins the race."),
    ("How to Make a Fire", "A fire needs three things: fuel, air and heat. Put dry wood in the fireplace. Hold a "
     "flint and strike it near the wood, and a spark will catch. Add more wood before the fire burns out. Wet "
     "wood will not burn, and rain puts out a fire in the open."),
    ("Who Has Seen the Wind?", "Who has seen the wind? Neither I nor you: but when the leaves hang trembling, the "
     "wind is passing through. Who has seen the wind? Neither you nor I: but when the trees bow down their "
     "heads, the wind is passing by. (Christina Rossetti)"),
    ("The Fox and the Grapes", "A hungry fox saw ripe grapes hanging high on a vine. She jumped and jumped, but "
     "could not reach them. At last she walked away and said, \"They were sour anyway.\" It is easy to scorn "
     "what you cannot have."),
    ("Mushrooms", "Mushrooms grow in the forest and the swamp, most of all after rain. A brown mushroom is good to "
     "eat, and better roasted on a fire. A red toadstool with white spots is poison: never eat it. When in "
     "doubt, leave a mushroom where it grows."),
    ("The Seasons", "The year has four seasons. In spring the flowers open and birds build nests. In summer the "
     "days are warm and berries ripen. In autumn apples fall and the leaves turn gold. In winter it is cold, "
     "snow falls, and a warm fire and a roof keep you alive."),
    ("The Star", "Twinkle, twinkle, little star, how I wonder what you are! Up above the world so high, like a "
     "diamond in the sky. When the blazing sun is gone, when he nothing shines upon, then you show your little "
     "light, twinkle, twinkle, all the night. (Jane Taylor)"),
    ("The Ant and the Grasshopper", "All summer the grasshopper sang while the ant carried grain to her nest. "
     "\"Why work so hard?\" laughed the grasshopper. When winter came, the grasshopper had nothing to eat, and "
     "the ant had plenty. There is a time for work and a time for play."),
    ("Salt Water", "The sea is salty. Drinking sea water makes you more thirsty, not less. Drink from lakes, "
     "rivers, springs and wells: their water is fresh. A bucket filled at a stream carries water home."),
    ("Bees", "Bees fly from flower to flower and carry nectar home to the hive. There they make it into honey "
     "and store it in wax cells. Honey is sweet and keeps for a very long time. If you take honey from a hive, "
     "the bees may sting you."),
    ("The Moon", "The moon has no light of its own. It shines because the sun lights it. Night by night the bright "
     "part grows and shrinks: new moon, half moon, full moon, and back again. On a clear night with a full "
     "moon you can see a little in the dark."),
    ("The Crow and the Pitcher", "A thirsty crow found a pitcher with a little water at the bottom, too low to "
     "reach. She dropped in pebbles, one by one, and the water rose until she could drink. Little by little "
     "does the trick."),
    ("Rain", "The rain is raining all around, it falls on field and tree, it rains on the umbrellas here, and on "
     "the ships at sea. (Robert Louis Stevenson)"),
    ("Trees", "An oak grows from an acorn and can live for hundreds of years. Birch trees have white bark. Pines "
     "keep their needles all winter. Apple trees give apples in summer and autumn. With an axe you can chop a "
     "tree into logs, and logs burn well in a fire."),
    ("The North Wind and the Sun", "The north wind and the sun argued about who was stronger. They saw a "
     "traveller in a cloak. The wind blew hard, but the man held his cloak tighter. Then the sun shone warmly, "
     "and the man took his cloak off. Kindness works better than force."),
    ("Staying Warm", "Cold air takes warmth from the body, and wet clothes take it faster. Out of the wind and rain "
     "a roof keeps you dry. A fire warms a room. Sleeping in a bed is warmer than sleeping on the ground. In "
     "winter, stay near shelter at night."),
    ("Hope", "Hope is the thing with feathers that perches in the soul, and sings the tune without the words, and "
     "never stops at all. (Emily Dickinson)"),
    ("Rivers and Lakes", "Rivers begin as small streams in the hills and grow as they flow. Shallow water can be "
     "waded, but deep water is dangerous and must be walked around. Reeds grow at the edges of lakes, and "
     "fish swim in the water."),
    ("The Lion and the Mouse", "A lion caught a little mouse and was about to eat it. \"Let me go, and one day I "
     "will help you,\" said the mouse. The lion laughed and let it go. Later the lion was caught in a net, and "
     "the mouse gnawed the ropes and set him free. Little friends may prove great friends."),
    ("Daffodils", "I wandered lonely as a cloud that floats on high over vales and hills, when all at once I saw a "
     "crowd, a host, of golden daffodils; beside the lake, beneath the trees, fluttering and dancing in the "
     "breeze. (William Wordsworth)"),
    ("Animals of the Wild", "Deer and rabbits eat grass and run from danger. Foxes hunt at dusk. Owls fly at night "
     "and sleep by day. Frogs sing near water on warm nights. Bears are big and strong: they live far from "
     "people and should be left alone."),
    ("The Desert", "In the desert there is little rain and the sun is hot. Cactus plants store water in their thick "
     "stems, and in summer some give a sweet fruit. Nights in the desert can be cold. Carry water when you go "
     "there."),
    ("The Snow Country", "High on the mountains and far in the cold lands, snow lies all year. Little grows there "
     "but moss and small berry bushes. The wind is sharp. Without a fire and shelter, the cold is deadly."),
    ("My Shadow", "I have a little shadow that goes in and out with me, and what can be the use of him is more "
     "than I can see. He is very, very like me from the heels up to the head; and I see him jump before me, "
     "when I jump into my bed. (Robert Louis Stevenson)"),
    ("Light and Dark", "By day the sun lights the world. At night it is dark, and you can see only what is near. A "
     "fire gives light as well as warmth, and a lit lantern lets you see further. Stars are suns so far away "
     "that they look like tiny points of light."),
    ("Seeds", "A seed holds a tiny plant and food for it to start. Given soil, water and sun, it sprouts, grows "
     "leaves and reaches for the light. Flowers make new seeds, and the wind, birds and bees carry them far."),
]
HOME_BOOKS = [2, 6, 9, 5]            # the home bookshelf: fire, seasons, salt water, mushrooms

# ---------------------------------------------------------------------- places
POI_KINDS = ["ruins", "cabin", "cave", "stones", "spring", "lookout", "beehive", "nest", "well"]
_NAMES = {
    "ruins": ("the {} Ruins", ["Grey", "Mossy", "Fallen", "Silent", "Old", "Broken", "Sunken", "Ivy", "Forgotten"]),
    "cabin": ("the {} Cabin", ["Empty", "Mossy", "Crooked", "Lonely", "Hunter's", "Old", "Quiet", "Woodcutter's"]),
    "cave": ("{} Cave", ["Echo", "Bear", "Fox", "Crystal", "Dripping", "Dark", "Wind", "Bat"]),
    "stones": ("the {} Stones", ["Whispering", "Seven", "Grey", "Sleeping", "Tall", "Moon", "Ring", "Old"]),
    "spring": ("the {} Spring", ["Clear", "Bright", "Cold", "Singing", "Silver", "Hidden", "Sweet"]),
    "lookout": ("{} Hill", ["Windy", "Eagle", "Sunset", "Lookout", "High", "Cloud", "Star", "Lone"]),
    "beehive": ("the {} Hive", ["Humming", "Golden", "Busy", "Honey", "Wild", "Buzzing"]),
    "nest": ("the {} Nest", ["Robin's", "High", "Hidden", "Twig", "Feather", "Mossy"]),
    "well": ("the {} Well", ["Old", "Wishing", "Deep", "Stone", "Mossy", "Dry-Stone"]),
}
POI_RADIUS = {"ruins": 5, "cabin": 5, "cave": 5, "stones": 5, "spring": 3, "lookout": 5, "beehive": 3,
              "nest": 3, "well": 3, "home": 6, "pond": 5}
STONE_TEXTS = ["Carved on it: a sun with seven rays.", "Carved on it: a moon and three stars.",
               "Carved on it: a spiral, like a snail shell.", "Carved on it: a river running to the sea.",
               "Carved on it: a deer leaping over a hill.", "Carved on it: two hands holding a seed."]


class Chunk:
    """The generated data of one 32×32 chunk. Lists are row-major: index = (y - y0) * 32 + (x - x0)."""
    __slots__ = ("cx", "cy", "h", "biome", "water", "feat", "temp", "pois", "spawns", "dominant", "fruit",
                 "_spawn_done")

    def __init__(self, cx, cy):
        self.cx, self.cy = cx, cy
        self.pois: list[dict] = []
        self.spawns: list[tuple] = []      # (kind, x, y, state) of things placed with a structure
        self.fruit: list[tuple] = []       # (x, y, feature) tiles that bear fruit
        self._spawn_done = False


def _home_layout():
    """The cabin at the origin, its furniture and the pond and garden around it."""
    feat, water, spawns = {}, {}, []
    for x in range(-4, 5):
        for y in range(-3, 4):
            feat[(x, y)] = F["wall"] if x in (-4, 4) or y in (-3, 3) else F["floor"]
    feat[(0, 3)] = F["door"]
    for x in range(-7, 8):                 # a clear yard around the cabin
        for y in range(-6, 8):
            feat.setdefault((x, y), 0)
    # the pond, east of the cabin
    for x in range(5, 17):
        for y in range(-4, 5):
            q = ((x - 10.5) / 3.8) ** 2 + ((y - 0.3) / 2.8) ** 2
            if q < 1.0:
                water[(x, y)] = WATER_DEEP if q < 0.3 else WATER_SHALLOW
                feat[(x, y)] = F["reeds"] if q > 0.75 and (x * 7 + y * 3) % 5 == 0 else 0
            elif q < 1.6:
                feat[(x, y)] = 0
    for p in ((-8, -4), (6, -7), (-10, 2), (-5, 10)):
        feat[p] = F["apple_tree"]
    for p in ((-6, 6), (-7, 7), (4, 8), (-2, 9), (8, -5), (13, 5), (-9, -1), (-6, 4), (6, 5), (5, -5),
              (-6, -5), (-3, 6), (3, 6)):
        feat[p] = F["berry_bush"]
    for p in ((-11, -6), (-12, -3), (9, 9), (12, -7), (-3, -9), (2, -10)):
        feat[p] = F["oak"]
    for p in ((-12, 6), (15, -5)):
        feat[p] = F["birch"]
    for p in ((-6, -8), (7, 11)):
        feat[p] = F["rock"]
    for x in range(-17, -10):              # the Humming Hive under an old oak, among flowers
        for y in range(6, 13):
            feat[(x, y)] = F["flowers"] if (x + 2 * y) % 3 == 0 else 0
    feat[(-14, 8)] = F["oak"]
    spawns.append(("beehive", -14, 9, {"honey": 2}))
    S = spawns.append
    S(("bookshelf", -3, -2, {"items": [("book", {"book": b}) for b in HOME_BOOKS]}))
    S(("woodpile", -1, -2, {"count": 6}))
    S(("fireplace", 0, -2, {"lit": False, "fuel": 240.0}))
    S(("piano", 2, -2, {}))
    S(("easel", 3, -2, {"paper": 5}))
    S(("desk", 3, 0, {"paper": 5}))
    S(("chest", -3, -1, {"open": False, "items": [("cup", {"water": 0}), ("paper", {})]}))
    S(("bed", -3, 1, {}))
    S(("table", 2, 1, {}))
    S(("flint", 2, 1, {}))
    S(("apple", 2, 1, {}))
    S(("apple", 2, 1, {}))
    S(("bucket", 3, 2, {"water": 0}))
    S(("axe", -2, 2, {}))
    S(("rain barrel", 2, 4, {"water": 20}))
    for p in ((7, 3), (14, -2), (11, 4)):
        S(("clay", p[0], p[1] + (1 if p[1] > 0 else -1), {}))
    S(("stick", -6, -3, {}))
    S(("stick", 5, 9, {}))
    S(("stone", -4, 7, {}))
    return feat, water, spawns


_HOME_FEAT, _HOME_WATER, _HOME_SPAWNS = _home_layout()
HOME_POIS = [{"kind": "home", "name": HOME_NAME, "x": 0, "y": 0},
             {"kind": "pond", "name": "the Home Pond", "x": 10, "y": 0},
             {"kind": "beehive", "name": "the Humming Hive", "x": -14, "y": 9}]
HOME_EXTENT = 60      # tiles from the origin where the home meadow blends into the wild


def classify(e, m, t, c):
    """Biome indices (before water) and effective temperature from the uniform fields."""
    te = 0.20 + 0.72 * t - np.maximum(0.0, e - 0.62) * 0.8
    biome = np.full(e.shape, B["meadow"], dtype=np.int64)
    temperate = (te >= 0.40) & (te < 0.70)
    hot = te >= 0.70
    cold = te < 0.40
    biome[temperate & (m < 0.20)] = B["grassland"]
    biome[temperate & (m >= 0.20) & (m < 0.46)] = B["meadow"]
    biome[temperate & (m >= 0.46)] = B["forest"]
    biome[temperate & (m >= 0.80) & (e < 0.40)] = B["swamp"]
    biome[hot & (m < 0.28)] = B["desert"]
    biome[hot & (m >= 0.28) & (m < 0.50)] = B["savanna"]
    biome[hot & (m >= 0.50) & (m < 0.62)] = B["grassland"]
    biome[hot & (m >= 0.62)] = B["jungle"]
    biome[hot & (m >= 0.86) & (e < 0.40)] = B["swamp"]
    biome[cold & (te >= 0.30) & (m >= 0.30)] = B["pine_forest"]
    biome[cold & (te >= 0.30) & (m < 0.30)] = B["grassland"]
    biome[cold & (te < 0.30)] = B["tundra"]
    biome[cold & (te < 0.30) & (te >= 0.20) & (m >= 0.55)] = B["pine_forest"]
    biome[cold & (te < 0.17)] = B["snow"]
    biome[(e > 0.80) & (m < 0.45)] = B["rock"]
    biome[e > 0.86] = B["mountain"]
    biome[(e > 0.94) | ((e > 0.86) & (te < 0.30))] = B["snow"]
    coast = (e < SEA + 0.03) & (c < OCEAN_C + 0.04)
    biome[coast & (te >= 0.30)] = B["beach"]
    return biome, te


class Terrain:
    def __init__(self, seed: int, cache: int = 768):
        self.seed = int(seed)
        self.cache: OrderedDict[tuple[int, int], Chunk] = OrderedDict()
        self.cache_size = cache
        self.diffs: dict[tuple[int, int], int] = {}          # (x, y) -> feature index replacing the generated one
        s = self.seed
        self.salt = {k: shash(s, k) for k in ("cont", "detail", "moist", "temp", "river", "feat", "sub", "wet")}

    # ------------------------------------------------------------------ chunk cache
    def chunk(self, cx: int, cy: int) -> Chunk:
        key = (cx, cy)
        c = self.cache.get(key)
        if c is not None:
            self.cache.move_to_end(key)
            return c
        c = self._generate(cx, cy)
        self.cache[key] = c
        if len(self.cache) > self.cache_size:
            self.cache.popitem(last=False)
        return c

    # ------------------------------------------------------------------ tile queries (diffs applied)
    def feature(self, x: int, y: int) -> int:
        d = self.diffs.get((x, y))
        if d is not None:
            return d
        return self.chunk(x >> 5, y >> 5).feat[((y & 31) << 5) | (x & 31)]

    def base_feature(self, x: int, y: int) -> int:
        return self.chunk(x >> 5, y >> 5).feat[((y & 31) << 5) | (x & 31)]

    def set_feature(self, x: int, y: int, f: int):
        if f == self.base_feature(x, y):
            self.diffs.pop((x, y), None)
        else:
            self.diffs[(x, y)] = f

    def biome(self, x: int, y: int) -> int:
        return self.chunk(x >> 5, y >> 5).biome[((y & 31) << 5) | (x & 31)]

    def water(self, x: int, y: int) -> int:
        return self.chunk(x >> 5, y >> 5).water[((y & 31) << 5) | (x & 31)]

    def height(self, x: int, y: int) -> int:
        return self.chunk(x >> 5, y >> 5).h[((y & 31) << 5) | (x & 31)]

    def base_temp(self, x: int, y: int) -> float:
        return self.chunk(x >> 5, y >> 5).temp[((y & 31) << 5) | (x & 31)]

    def tile(self, x: int, y: int) -> tuple[int, int, int]:
        """(biome, water, feature) with diffs applied."""
        c = self.chunk(x >> 5, y >> 5)
        i = ((y & 31) << 5) | (x & 31)
        f = self.diffs.get((x, y))
        return c.biome[i], c.water[i], (c.feat[i] if f is None else f)

    def walkable(self, x: int, y: int) -> bool:
        b, w, f = self.tile(x, y)
        return w != WATER_DEEP and f not in BLOCKING

    def payload(self, cx: int, cy: int) -> dict:
        c = self.chunk(cx, cy)
        feat = c.feat
        x0, y0 = cx * CHUNK, cy * CHUNK
        if self.diffs:
            feat = list(feat)
            for (x, y), f in self.diffs.items():
                if x0 <= x < x0 + CHUNK and y0 <= y < y0 + CHUNK:
                    feat[(y - y0) * CHUNK + (x - x0)] = f
        return {"cx": cx, "cy": cy, "size": CHUNK, "h": c.h, "biome": c.biome, "water": c.water, "feat": feat,
                "meta": {"pois": [{"kind": p["kind"], "name": p["name"], "x": p["x"], "y": p["y"]} for p in c.pois]}}

    # ------------------------------------------------------------------ persistence of changes
    def diff_state(self) -> list:
        return [[x, y, f] for (x, y), f in sorted(self.diffs.items())]

    def load_diffs(self, rows):
        self.diffs = {(int(x), int(y)): int(f) for x, y, f in rows or []}

    # ------------------------------------------------------------------ generation
    def fields(self, xs: np.ndarray, ys: np.ndarray):
        """Uniform elevation, moisture, temperature, continentalness and the river field at points."""
        s = self.salt
        cont = _fbm(xs, ys, 1 / 700, 3, s["cont"])
        detail = _fbm(xs, ys, 1 / 110, 5, s["detail"])
        e = np.interp(0.6 * cont + 0.4 * detail, _Q_ELEV, _Q)
        m = np.interp(_fbm(xs, ys, 1 / 220, 4, s["moist"]), _Q_MOIST, _Q)
        t = np.interp(_fbm(xs, ys, 1 / 380, 3, s["temp"]), _Q_TEMP, _Q)
        c = np.interp(cont, _Q_CONT, _Q)
        r = _fbm(xs, ys, 1 / 170, 3, s["river"])
        # home: a pleasant, temperate meadow that blends into the wild
        d = np.sqrt(xs * xs + ys * ys)
        # the lands around home lean temperate and dry-footed; the extremes are further out
        far = np.exp(-d / 500.0) * 0.65
        t = t + (0.5 - t) * far
        c = c + (0.62 - c) * far
        e = e + (0.45 - e) * far * 0.6
        w = np.clip(1.0 - (d - 16.0) / (HOME_EXTENT - 16.0), 0.0, 1.0)
        w = w * w * (3 - 2 * w)
        if w.any():
            e = e + (0.42 - e) * w
            m = m + (0.40 + 0.25 * (m - 0.5) - m) * w
            t = t + (0.55 - t) * w
            c = c + (0.7 - c) * w
            r = r + np.where(r >= 0.5, 1.0, -1.0) * 0.06 * w      # no river through the yard
        return e, m, t, c, r

    def _generate(self, cx: int, cy: int) -> Chunk:
        x0, y0 = cx * CHUNK, cy * CHUNK
        ly, lx = np.divmod(np.arange(AREA), CHUNK)
        xs = (x0 + lx).astype(np.float64)
        ys = (y0 + ly).astype(np.float64)
        e, m, t, c, r = self.fields(xs, ys)
        biome, te = classify(e, m, t, c)
        # water
        water = np.zeros(AREA, dtype=np.int64)
        wet = e < SEA
        ocean = wet & (c < OCEAN_C)
        biome[wet] = B["lake"]
        biome[ocean] = B["ocean"]
        water[wet] = WATER_SHALLOW
        water[e < DEEP] = WATER_DEEP
        frozen_lake = wet & (te < 0.12) & (e >= DEEP)
        water[frozen_lake] = WATER_SHALLOW
        # rivers: thin bands along the mid-level line of a slow noise field
        width = 0.006 + 0.004 * np.clip((0.6 - e) / 0.4, 0, 1)
        river = (np.abs(r - 0.5) < width) & ~wet & (e < 0.84)
        water[river] = WATER_RIVER
        # swamp pools
        pools = (biome == B["swamp"]) & (water == 0) & (_fbm(xs, ys, 1 / 9, 2, self.salt["wet"]) > 0.6)
        water[pools] = WATER_SHALLOW
        # height (decimetres)
        h = np.round((e - SEA) * 2600.0).astype(np.int64)
        h[river] -= 6
        h[pools] -= 3
        # features
        rf = _unit(_hash2(xs.astype(np.int64), ys.astype(np.int64), self.salt["feat"]))
        feat = np.zeros(AREA, dtype=np.int64)
        land = water == 0
        for b in np.unique(biome):
            bands = _BF.get(int(b))
            if not bands:
                continue
            mask = (biome == b) & land
            lo = 0.0
            for f, p in bands:
                feat[mask & (rf >= lo) & (rf < lo + p)] = f
                lo += p
        edge = (water == WATER_SHALLOW) | (water == WATER_RIVER)
        reedy = edge & ((biome == B["lake"]) | (biome == B["swamp"]) | river) & (rf < 0.12) & (te > 0.3)
        feat[reedy] = F["reeds"]
        temp = np.round(-16.0 + 60.0 * te - np.maximum(0.0, e - 0.7) * 25.0, 1)
        ch = Chunk(cx, cy)
        ch.h, ch.biome, ch.water, ch.feat, ch.temp = h.tolist(), biome.tolist(), water.tolist(), feat.tolist(), \
            temp.tolist()
        self._stamp_home(ch, x0, y0)
        self._place_poi(ch, x0, y0)
        ch.dominant = int(np.bincount(np.array(ch.biome), minlength=len(BIOMES)).argmax())
        fr = {F["berry_bush"], F["apple_tree"], F["palm"], F["jungle_tree"], F["cactus"], F["flowers"]}
        ch.fruit = [(x0 + (i & 31), y0 + (i >> 5), f) for i, f in enumerate(ch.feat) if f in fr]
        return ch

    def _stamp_home(self, ch: Chunk, x0: int, y0: int):
        if not (x0 <= 20 and x0 + CHUNK > -20 and y0 <= 16 and y0 + CHUNK > -16):
            return
        for (x, y), f in _HOME_FEAT.items():
            if x0 <= x < x0 + CHUNK and y0 <= y < y0 + CHUNK:
                i = (y - y0) * CHUNK + (x - x0)
                ch.feat[i] = f
                ch.water[i] = _HOME_WATER.get((x, y), 0)
                ch.biome[i] = B["lake"] if (x, y) in _HOME_WATER else B["meadow"]
                if (x, y) in _HOME_WATER:            # the pond: a flat surface just below the meadow
                    ch.h[i] = ch.h[i] - (9 if _HOME_WATER[(x, y)] == WATER_DEEP else 6)
        for k, x, y, st in _HOME_SPAWNS:
            if x0 <= x < x0 + CHUNK and y0 <= y < y0 + CHUNK:
                ch.spawns.append((k, x, y, st))
        for p in HOME_POIS:
            if x0 <= p["x"] < x0 + CHUNK and y0 <= p["y"] < y0 + CHUNK:
                ch.pois.append(dict(p))

    # ------------------------------------------------------------------ points of interest
    def _place_poi(self, ch: Chunk, x0: int, y0: int):
        cx, cy = ch.cx, ch.cy
        ring = max(abs(cx), abs(cy))
        if ring == 0:
            return
        rng = random.Random(shash(self.seed, cx, cy, "poi"))
        if rng.random() >= (0.45 if ring == 1 else 0.32 if ring <= 3 else 0.16):
            return
        for _ in range(4):
            lx, ly = rng.randint(7, 24), rng.randint(7, 24)
            i = ly * CHUNK + lx
            b = BIOMES[ch.biome[i]]
            if ch.water[i] or b in ("ocean", "lake"):
                continue
            kinds = {"ruins": 3, "cabin": 2, "stones": 2, "spring": 2, "well": 2, "nest": 2, "beehive": 2,
                     "lookout": 2, "cave": 1}
            if b in ("mountain", "rock", "snow", "tundra"):
                kinds.update(cave=6, lookout=4, beehive=0, nest=1, spring=1)
            if b in ("forest", "pine_forest", "jungle"):
                kinds.update(nest=4, beehive=3, cabin=3)
            if b in ("meadow", "grassland", "savanna"):
                kinds.update(beehive=4, stones=3, well=3)
            if b in ("desert", "beach"):
                kinds.update(ruins=5, well=4, beehive=0, nest=1)
            names = sorted(kinds)
            kind = rng.choices(names, weights=[kinds[k] for k in names])[0]
            fmt, adj = _NAMES[kind]
            name = fmt.format(rng.choice(adj))
            x, y = x0 + lx, y0 + ly
            ch.pois.append({"kind": kind, "name": name, "x": x, "y": y})
            getattr(self, "_poi_" + kind)(ch, rng, lx, ly, x, y)
            return

    def _set(self, ch: Chunk, lx: int, ly: int, f: int, dry: bool = True):
        if 0 <= lx < CHUNK and 0 <= ly < CHUNK:
            i = ly * CHUNK + lx
            ch.feat[i] = f
            if dry and ch.water[i]:
                ch.water[i] = 0
                if ch.biome[i] in (B["ocean"], B["lake"]):
                    ch.biome[i] = B["meadow"] if ch.temp[i] > 0 else B["tundra"]
                ch.h[i] = max(ch.h[i], 2)

    def _clear(self, ch, lx, ly, r):
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                self._set(ch, lx + dx, ly + dy, 0)

    def _poi_ruins(self, ch, rng, lx, ly, x, y):
        self._clear(ch, lx, ly, 4)
        for d in range(-3, 4):
            for (ax, ay) in ((lx + d, ly - 3), (lx + d, ly + 3), (lx - 3, ly + d), (lx + 3, ly + d)):
                if rng.random() < 0.72:
                    self._set(ch, ax, ay, F["stone_wall"])
                elif rng.random() < 0.6:
                    self._set(ch, ax, ay, F["rubble"])
        for ax, ay in ((lx, ly + 3), (lx, ly - 3), (lx + 3, ly), (lx - 3, ly)):
            self._set(ch, ax, ay, F["rubble"])      # gaps: always a way in
        for _ in range(3):
            self._set(ch, lx + rng.randint(-2, 2), ly + rng.randint(-2, 2), F["rubble"])
        self._set(ch, lx, ly - 2, 0)
        items = [("book", {"book": rng.randrange(len(BOOKS))})]
        items.append(rng.choice([("axe", {}), ("lantern", {"lit": False}), ("flint", {}), ("crystal", {})]))
        if rng.random() < 0.5:
            items.append(("paper", {}))
        ch.spawns.append(("chest", x, y - 2, {"open": False, "items": items}))
        ch.spawns.append(("book", x + rng.choice((-1, 1)), y + 1, {"book": rng.randrange(len(BOOKS))}))
        ch.spawns.append(("stone", x + 2, y + 2, {}))

    def _poi_cabin(self, ch, rng, lx, ly, x, y):
        self._clear(ch, lx, ly, 4)
        for dx in range(-3, 4):
            for dy in range(-2, 3):
                edge = dx in (-3, 3) or dy in (-2, 2)
                self._set(ch, lx + dx, ly + dy, F["wall"] if edge else F["floor"])
        self._set(ch, lx, ly + 2, F["door"])
        ch.spawns.append(("bed", x - 2, y - 1, {}))
        ch.spawns.append(("fireplace", x, y - 1, {"lit": False, "fuel": 0.0}))
        ch.spawns.append(("woodpile", x + 1, y - 1, {"count": rng.randint(1, 4)}))
        items = [("flint", {}), ("paper", {})]
        items.append(rng.choice([("lantern", {"lit": False}), ("cup", {"water": 0}), ("axe", {})]))
        if rng.random() < 0.7:
            items.append(("book", {"book": rng.randrange(len(BOOKS))}))
        ch.spawns.append(("chest", x + 2, y + 1, {"open": False, "items": items}))
        ch.spawns.append(("table", x - 2, y + 1, {}))

    def _poi_cave(self, ch, rng, lx, ly, x, y):
        self._clear(ch, lx, ly, 4)
        for dx in range(-3, 4):
            for dy in range(-3, 3):
                edge = dx in (-3, 3) or dy in (-3, 2)
                self._set(ch, lx + dx, ly + dy, F["cave_wall"] if edge else F["cave_floor"])
        self._set(ch, lx, ly + 2, F["cave_floor"])          # the mouth faces south
        self._set(ch, lx + rng.choice((-1, 1)), ly + 2, F["cave_floor"])
        ch.spawns.append(("crystal", x + rng.randint(-2, 2), y - 2, {}))
        if rng.random() < 0.6:
            ch.spawns.append(("mushroom", x - 2, y, {}))
        if rng.random() < 0.5:
            ch.spawns.append(("bone", x + 2, y, {}))
        ch.spawns.append(("flint", x + 1, y + 1, {}))

    def _poi_stones(self, ch, rng, lx, ly, x, y):
        self._clear(ch, lx, ly, 4)
        n = rng.randint(6, 8)
        import math
        for k in range(n):
            a = 2 * math.pi * k / n
            self._set(ch, lx + int(round(3 * math.cos(a))), ly + int(round(3 * math.sin(a))), F["standing_stone"])
        self._set(ch, lx, ly, F["standing_stone"])
        self._set(ch, lx, ly + 1, F["flowers"])

    def _poi_spring(self, ch, rng, lx, ly, x, y):
        self._clear(ch, lx, ly, 2)
        self._set(ch, lx, ly, F["spring"])
        ch.water[ly * CHUNK + lx] = WATER_SHALLOW
        for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1), (0, 2)):
            self._set(ch, lx + dx, ly + dy, rng.choice([F["reeds"], F["flowers"], F["fern"], 0]))
        ch.spawns.append(("clay", x + 1, y, {}))

    def _poi_lookout(self, ch, rng, lx, ly, x, y):
        self._clear(ch, lx, ly, 2)
        for dy in range(-6, 7):
            for dx in range(-6, 7):
                d = (dx * dx + dy * dy) ** 0.5
                if d <= 6 and 0 <= lx + dx < CHUNK and 0 <= ly + dy < CHUNK:
                    i = (ly + dy) * CHUNK + lx + dx
                    if not ch.water[i]:
                        ch.h[i] += int(90 * (1 - d / 6.5))
        self._set(ch, lx, ly, F["cairn"])
        ch.spawns.append(("stone", x + 1, y + 1, {}))

    def _poi_beehive(self, ch, rng, lx, ly, x, y):
        self._clear(ch, lx, ly, 2)
        self._set(ch, lx, ly - 1, F["oak"])
        for dx, dy in ((-2, 0), (2, 1), (-1, 2), (1, -2)):
            self._set(ch, lx + dx, ly + dy, F["flowers"])
        ch.spawns.append(("beehive", x, y, {"honey": 2}))

    def _poi_nest(self, ch, rng, lx, ly, x, y):
        self._clear(ch, lx, ly, 1)
        tree = F["pine"] if BIOMES[ch.biome[ly * CHUNK + lx]] in ("pine_forest", "tundra", "snow", "mountain") \
            else F["oak"]
        self._set(ch, lx, ly - 1, tree)
        ch.spawns.append(("nest", x, y, {"eggs": 2}))
        ch.spawns.append(("feather", x + 1, y + 1, {}))

    def _poi_well(self, ch, rng, lx, ly, x, y):
        self._clear(ch, lx, ly, 2)
        self._set(ch, lx, ly, F["well"])
        for dx, dy in ((-2, -1), (2, 1), (1, -2)):
            self._set(ch, lx + dx, ly + dy, F["rubble"])

    # ------------------------------------------------------------------ loose things
    def spawns(self, cx: int, cy: int) -> list[tuple]:
        """Every thing generated in a chunk: (kind, x, y, state). Deterministic; the World gives each an id."""
        ch = self.chunk(cx, cy)
        out = list(ch.spawns)
        rng = random.Random(shash(self.seed, cx, cy, "things"))
        x0, y0 = cx * CHUNK, cy * CHUNK
        feat, water, biome = ch.feat, ch.water, ch.biome
        taken = {(s[1], s[2]) for s in out}
        home = -12 <= x0 + 16 <= 28 and -12 <= y0 + 16 <= 28 and abs(cx) <= 1 and abs(cy) <= 1
        for i in range(AREA):
            f, w = feat[i], water[i]
            if w or f in BLOCKING or f >= F["wall"]:
                continue
            x, y = x0 + (i & 31), y0 + (i >> 5)
            if home and -5 <= x <= 5 and -4 <= y <= 4:
                continue
            b = BIOMES[biome[i]]
            table = _LOOSE.get(b)
            r = rng.random()
            if not table:
                continue
            lo = 0.0
            kind = None
            for k, p in table:
                lo += p
                if r < lo:
                    kind = k
                    break
            if kind is None:
                # things that depend on neighbours: clay and stones by water, fruit under trees
                lx, ly = i & 31, i >> 5
                near_w = near_t = 0
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = lx + dx, ly + dy
                    if 0 <= nx < CHUNK and 0 <= ny < CHUNK:
                        j = ny * CHUNK + nx
                        if water[j] and biome[j] != B["ocean"]:
                            near_w = 1
                        if feat[j] in TREES:
                            near_t = feat[j]
                r2 = rng.random()
                if near_w and r2 < 0.05:
                    kind = "clay" if r2 < 0.035 else "stone"
                elif near_t == F["apple_tree"] and r2 < 0.25:
                    kind = "apple"
                elif near_t == F["palm"] and r2 < 0.15:
                    kind = "coconut"
                elif near_t == F["jungle_tree"] and r2 < 0.03:
                    kind = "banana"
                elif near_t and r2 < 0.03:
                    kind = "stick"
            if kind and (x, y) not in taken:
                out.append((kind, x, y, {}))
        return out


_LOOSE = {
    "forest": [("stick", 0.010), ("mushroom", 0.004), ("toadstool", 0.002), ("feather", 0.001), ("stone", 0.002),
               ("flint", 0.0005)],
    "pine_forest": [("stick", 0.010), ("pinecone", 0.008), ("mushroom", 0.003), ("toadstool", 0.002),
                    ("stone", 0.003)],
    "meadow": [("stone", 0.003), ("feather", 0.002), ("stick", 0.002)],
    "grassland": [("stone", 0.003), ("feather", 0.002)],
    "savanna": [("stick", 0.004), ("stone", 0.004), ("feather", 0.002), ("bone", 0.001)],
    "jungle": [("stick", 0.008), ("feather", 0.003), ("mushroom", 0.003), ("toadstool", 0.002)],
    "swamp": [("mushroom", 0.005), ("toadstool", 0.006), ("clay", 0.01), ("stick", 0.004)],
    "desert": [("stone", 0.006), ("flint", 0.001), ("bone", 0.002)],
    "beach": [("shell", 0.03), ("stone", 0.006), ("flint", 0.003), ("stick", 0.004)],
    "tundra": [("stone", 0.006), ("feather", 0.002), ("bone", 0.001)],
    "snow": [("stone", 0.003)],
    "mountain": [("stone", 0.02), ("flint", 0.006), ("crystal", 0.0008)],
    "rock": [("stone", 0.02), ("flint", 0.008)],
}


def book_text(i: int) -> tuple[str, str]:
    return BOOKS[i % len(BOOKS)]
