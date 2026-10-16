"""The World: physics and consequences for Zen, in an endless land.

Nothing here decides anything for Zen. Zen's brain picks a motor word; ``act`` carries it out and
says, in plain egocentric English, what happened, with a reward computed from what changed:

    reward = 12·Δwellbeing + novelty + pain + events          (clamped to [-1, 1] per action)

where wellbeing ∈ [0, 1] is a weighted mean of concave need utilities (health counts double), so
relieving a real need is worth more than topping up a full one; novelty is +0.01 per new tile,
+0.25 per new kind of thing seen, +0.1 per new chunk, +0.5 per new named place; pain is −0.02 for
bumping into something, −0.01 for an action that does not work, −0.2 per point of health lost;
events are +0.3 the first time a motor word works, +0.1 the first time it works on a new kind of
thing, +0.4 when the Sprite's answer arrives. Time passing (``advance``) accumulates the same
terms (getting colder, hungrier, hurt) for ``reward_since_last()``.

Coordinates: x grows east, y grows south. Facing: 0 = north, 1 = east, 2 = south, 3 = west.
"""
from __future__ import annotations

import math
import random

from ..ontology import BIOME_KIND, FEATURE_KIND, KINDS
from . import terrain as T
from .terrain import BIOMES, BLOCKING, CHUNK, FEATURES, SHELTER, TREES, WATER_DEEP, WATER_RIVER, F, Terrain, shash

MOTOR = ["forward", "back", "left", "right", "wait", "take", "drop", "eat", "drink", "use", "sleep", "look",
         "speak", "ask"]
DIRS = [(0, -1), (1, 0), (0, 1), (-1, 0)]
DIR_NAMES = ["north", "east", "south", "west"]
SEASONS = ["spring", "summer", "autumn", "winter"]
WEATHERS = ["clear", "cloudy", "rain", "storm", "snow", "fog", "wind"]
NEEDS = ["energy", "water", "rest", "warmth", "health"]
MAX_HANDS = 4
PLACEABLE = ["berries", "apple", "banana", "coconut", "honey", "mushroom", "egg", "raw fish", "cooked fish", "stick",
             "log", "stone", "flint", "clay", "flower", "feather", "shell", "crystal", "book", "paper", "cup",
             "bucket", "axe", "lantern", "campfire"]
MEDIA = ("painting", "music", "sculpture", "poem")

WB_GAIN = 12.0            # reward per unit of wellbeing (0.6 × 20)
SIGHT_DAY = 7
ENT_RANGE = 48
GEN_BASE = 1 << 45        # generated things have ids at or above this; things made later count up from 1
ANIMAL_BASE = 1 << 44
REGROW = 1800.0           # seconds of world time before a picked plant bears again

_WEATHER_W = {   # season -> weights for the next weather (clear, cloudy, rain, storm, snow, fog, wind)
    "spring": [4, 3, 3, 0.5, 0, 1, 1.5], "summer": [6, 2, 1.5, 1, 0, 0.5, 1],
    "autumn": [3, 3, 3, 1, 0.3, 2, 2], "winter": [3, 3, 1, 0.5, 3, 1.5, 2]}
_WEATHER_T = {"clear": 0, "cloudy": -1, "rain": -3, "storm": -5, "snow": -3, "fog": -2, "wind": -3}
_SEASON_T = {"spring": 0, "summer": 6, "autumn": -3, "winter": -12}
_GROUND = {"ocean": "sand", "lake": "mud", "beach": "sand", "meadow": "grass", "grassland": "grass",
           "forest": "fallen leaves", "pine_forest": "pine needles", "jungle": "damp earth", "swamp": "mud",
           "desert": "sand", "savanna": "dry grass", "tundra": "moss", "snow": "snow", "mountain": "stone",
           "rock": "bare rock"}
_FURNITURE = {"rain barrel", "bed", "fireplace", "campfire", "woodpile", "table", "bookshelf", "easel", "piano", "desk", "chest",
              "beehive", "nest"}
_ANIMALS = {   # biome -> [(kind, chance per chunk, max count)]
    "meadow": [("rabbit", 0.7, 3), ("bird", 0.7, 3), ("deer", 0.3, 2), ("fox", 0.15, 1)],
    "grassland": [("rabbit", 0.6, 3), ("bird", 0.5, 2), ("deer", 0.4, 3), ("fox", 0.2, 1)],
    "forest": [("deer", 0.6, 3), ("bird", 0.8, 3), ("rabbit", 0.4, 2), ("fox", 0.3, 1), ("owl", 0.5, 1)],
    "pine_forest": [("deer", 0.5, 2), ("bird", 0.5, 2), ("fox", 0.3, 1), ("owl", 0.5, 1), ("bear", 0.08, 1)],
    "jungle": [("bird", 0.9, 4), ("frog", 0.6, 3), ("lizard", 0.4, 2)],
    "swamp": [("frog", 0.9, 4), ("bird", 0.5, 2), ("owl", 0.3, 1)],
    "desert": [("lizard", 0.7, 3)],
    "savanna": [("deer", 0.5, 3), ("bird", 0.5, 2), ("lizard", 0.4, 2)],
    "beach": [("bird", 0.8, 3)],
    "tundra": [("fox", 0.3, 1), ("rabbit", 0.4, 2), ("bird", 0.3, 1)],
    "snow": [("fox", 0.15, 1)],
    "mountain": [("goat", 0.6, 3), ("bird", 0.3, 1), ("bear", 0.05, 1)],
    "rock": [("goat", 0.5, 2), ("lizard", 0.2, 1)],
}
_FLEE = {"deer": 4, "rabbit": 3, "fox": 4, "bird": 2, "goat": 3, "lizard": 2, "bear": 4, "frog": 2, "owl": 2,
         "fish": 1}
_NIGHT = {"owl", "frog", "fireflies"}
_FRUIT_WITH = {"berry bush": "berries", "apple tree": "apples", "palm": "coconuts", "jungle tree": "bananas",
               "cactus": "fruit", "flowers": ""}
_MASS = {"furniture", "wood", "food", "land", "water", "earth", "snow", "fire"}
_NUM = {2: "two", 3: "three", 4: "four"}


def plural(n: str) -> str:
    """'an apple' -> 'apples', 'a sheet of paper' -> 'sheets of paper'."""
    for a in ("an ", "a ", "the "):
        if n.startswith(a):
            n = n[len(a):]
            break
    head, sep, tail = n.partition(" of ")
    words = head.split(" ")
    w = words[-1]
    if w not in ("fish",):
        w = w[:-1] + "ies" if w.endswith("y") and w[-2:-1] not in "aeiou" else \
            w + "es" if w.endswith(("s", "sh", "ch", "x")) else w + "s"
    words[-1] = w
    return " ".join(words) + sep + tail


def count_list(nouns: list[str]) -> str:
    """'an apple', 'an apple', 'a stick' -> 'two apples and a stick' (order of first appearance)."""
    order, counts = [], {}
    for n in nouns:
        if n not in counts:
            order.append(n)
        counts[n] = counts.get(n, 0) + 1
    return and_list([n if counts[n] == 1 or n.startswith("some ") else f"{_NUM.get(counts[n], counts[n])} {plural(n)}"
                     for n in order])


class Body:
    """Zen, the Sprite and you: attributes you can also read like a dict (``w.zen.x`` or ``w.zen["x"]``)."""

    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __getitem__(self, k):
        return getattr(self, k)

    def __setitem__(self, k, v):
        setattr(self, k, v)

    def __contains__(self, k):
        return k in self.__dict__

    def get(self, k, default=None):
        return getattr(self, k, default)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


# ---------------------------------------------------------------------- words
def noun_of(kind: str) -> str:
    return KINDS.get(kind, {}).get("noun", kind)


def the(n: str) -> str:
    for a in ("an ", "a ", "some "):
        if n.startswith(a):
            return "the " + n[len(a):]
    return n


def cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def and_list(items: list[str]) -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def temp_word(c: float) -> str:
    return "freezing" if c < 0 else "cold" if c < 8 else "cool" if c < 15 else "mild" if c < 22 else \
        "warm" if c < 29 else "hot"


def rel_phrase(fwd: int, rt: int) -> str:
    parts = []
    if fwd > 0:
        parts.append(f"{fwd} ahead")
    elif fwd < 0:
        parts.append(f"{-fwd} behind")
    if rt:
        side = "right" if rt > 0 else "left"
        parts.append(f"{abs(rt)} {side}" if parts else f"{abs(rt)} to the {side}")
    return " and ".join(parts)


def _utility(n: float) -> float:
    d = 1.0 - max(0.0, min(100.0, n)) / 100.0
    return 1.0 - d * d


class World:
    def __init__(self, seed: int | None = 11, **_ignored):
        self.seed = int(seed if seed is not None else 11)
        self.terrain = Terrain(self.seed)
        self.rng = random.Random(shash(self.seed, "world"))
        # time
        self.t = 0.0
        self.tick_n = 0
        self.day = 1
        self.phase = "day"
        self.phase_t = 60.0
        self.day_seconds = 600.0
        self.night_seconds = 1200.0
        self.base_weather = "clear"
        self.weather_left = 300.0
        self.last_rain_t = -1e9
        self._regen_t = 0.0
        # things
        self.ents: dict[int, dict] = {}
        self.cidx: dict[tuple, set] = {}
        self.tidx: dict[tuple, list] = {}
        self.alive: set[int] = set()
        self.spawned: set[tuple] = set()
        self.gone: set[int] = set()
        self.mod: set[int] = set()
        self.next_id = 1
        self.fires: set[int] = set()
        self.picked: dict[tuple, float] = {}
        self.chops: dict[tuple, int] = {}
        # beings
        self.zen = Body(x=0, y=0, fx=0.0, fy=0.0, facing=2, hands=[], sleeping=False, in_bed=False, said="",
                        said_t=-1e9, activity="", activity_t=0.0, waiting=False, wet=0.0, voluntary=False,
                        needs={"energy": 80.0, "water": 80.0, "rest": 90.0, "warmth": 75.0, "health": 100.0})
        self.sprite = Body(x=-1, y=-1, fx=-1.0, fy=-1.0, state="idle", said="", said_t=-1e9)
        self.visitor: Body | None = None
        self.animals: dict[int, dict] = {}
        self.animal_at: dict[tuple, int] = {}
        self.animal_chunks: set[tuple] = set()
        self.next_animal = ANIMAL_BASE
        self.zen_stage = 0
        # memory of the journey
        self.visited: dict[tuple, int] = {}
        self.explored: set[tuple] = set()
        self.seen: set[str] = set()
        self.firsts: set[str] = set()
        self.places: dict[str, dict] = {}
        self.read_books: set[int] = set()
        self.trail: list[list[int]] = [[0, 0]]
        self.faints = 0
        # art
        self.creations: list[dict] = []
        self.new_creations: list[dict] = []
        self.next_cid = 1
        self.practice: dict[str, float] = {m: 0.0 for m in MEDIA}
        self.studio: dict | None = None
        self._studio_changed = False
        # bookkeeping
        self.log: list[str] = []
        self.events: list[dict] = []
        self._passive = 0.0
        self._bonus = 0.0
        self.last_action = ""
        self.steps = 0
        self.reward_rate = 0.0
        self._sent: set[int] = set()
        self._dirty: set[int] = set()
        self._removed: set[int] = set()
        self._area_key = None
        self._look_bonus = 0.0
        self._ensure_area()
        self._mark_visit()
        self._notice()          # what Zen sees at the start is not a reward later
        self._passive = 0.0

    # ================================================================== time and sky
    @property
    def season(self) -> str:
        return SEASONS[((self.day - 1) // 4) % 4]

    @property
    def weather(self) -> str:
        return self.weather_at(self.zen.x, self.zen.y)

    def weather_at(self, x: int, y: int) -> str:
        w = self.base_weather
        b = BIOMES[self.terrain.biome(x, y)]
        t = self.terrain.base_temp(x, y) + _SEASON_T[self.season]
        if w in ("rain", "storm") and t < 1:
            return "snow"
        if w == "snow" and t > 3:
            return "rain"
        if b == "desert" and w in ("rain", "storm", "fog"):
            return "cloudy"
        if b == "swamp" and w == "cloudy":
            return "fog"
        return w

    def time_of_day(self, *_ignored) -> str:
        if self.phase == "day":
            f = self.phase_t / max(1.0, self.day_seconds)
            return "dawn" if f < 0.07 else "morning" if f < 0.38 else "midday" if f < 0.58 else \
                "afternoon" if f < 0.82 else "evening" if f < 0.94 else "dusk"
        f = self.phase_t / max(1.0, self.night_seconds)
        return "night" if f < 0.4 else "midnight" if f < 0.6 else "late night"

    def daylight(self) -> float:
        """0..1 sky light at the moment (before fires and lanterns)."""
        if self.phase == "day":
            f = min(1.0, self.phase_t / max(1.0, self.day_seconds))
            light = 0.3 + 0.7 * math.sin(math.pi * f) ** 0.5
            return light * {"storm": 0.55, "rain": 0.75, "cloudy": 0.85, "fog": 0.7, "snow": 0.8}.get(
                self.base_weather, 1.0)
        return 0.18 * self.moon() * (1.0 if self.base_weather in ("clear", "wind") else 0.3)

    def moon(self) -> float:
        p = self.day % 8
        return 1.0 - abs(4 - p) / 4.0

    def air_temp(self, x: int, y: int) -> float:
        """Air temperature (°C) at a tile: land, season, time, weather, shelter and fires nearby."""
        c = self.terrain.base_temp(x, y) + _SEASON_T[self.season]
        if self.phase == "day":
            f = self.phase_t / max(1.0, self.day_seconds)
            c += 4.0 * math.sin(math.pi * min(1.0, f)) - 1.0
        else:
            c -= 5.0
        f_here = self.terrain.feature(x, y)
        inside = f_here in SHELTER
        if inside:
            c = 0.4 * c + 0.6 * 13.0
        else:
            c += _WEATHER_T[self.weather_at(x, y)]
            if self.phase == "night" and self.base_weather == "clear":
                c -= 2.0
        for fid in self.fires:
            e = self.ents.get(fid)
            if not e or not e.get("lit"):
                continue
            d = max(abs(e["x"] - x), abs(e["y"] - y))
            if e["kind"] == "fireplace" and inside and d <= 5 and f_here == F["floor"]:
                c = max(c + 12.0, 21.0)
            elif e["kind"] == "campfire" and d <= 2:
                c += 10.0 * (1.0 - d / 3.0)
            elif e["kind"] == "fireplace" and d <= 1:
                c += 6.0
        return c

    def light_at(self, x: int, y: int) -> float:
        light = self.daylight()
        if self.terrain.feature(x, y) in SHELTER and self.phase == "day":
            light *= 0.7
        for fid in self.fires:
            e = self.ents.get(fid)
            if e and e.get("lit"):
                d = max(abs(e["x"] - x), abs(e["y"] - y))
                r = KINDS[e["kind"]].get("light", 4)
                if d <= r:
                    light = max(light, 0.8 - 0.4 * d / (r + 1))
        if (x, y) == (self.zen.x, self.zen.y) and any(h["kind"] == "lantern" and h.get("lit") for h in self.zen.hands):
            light = max(light, 0.6)
        return light

    def sight_radius(self) -> int:
        light = self.light_at(self.zen.x, self.zen.y)
        r = 7 if light >= 0.5 else 5 if light >= 0.3 else 3 if light >= 0.12 else 1
        w = self.weather
        if w == "fog":
            r = min(r, 3)
        elif w in ("storm", "snow"):
            r = min(r, 5)
        if self.terrain.feature(self.zen.x, self.zen.y) in SHELTER:
            r = min(r, 6)
        return r

    # ================================================================== things
    def _gen_id(self, cx: int, cy: int, n: int) -> int:
        return GEN_BASE + ((((cx & 0xFFFF) << 16) | (cy & 0xFFFF)) << 12) + n

    def make(self, kind: str, **state) -> dict:
        e = {"id": self.next_id, "kind": kind, "x": 0, "y": 0}
        e.update(state)
        self.next_id += 1
        self.alive.add(e["id"])
        self.mod.add(e["id"])
        return e

    def place(self, e: dict, x: int, y: int):
        e["x"], e["y"] = x, y
        self.ents[e["id"]] = e
        self.cidx.setdefault((x >> 5, y >> 5), set()).add(e["id"])
        self.tidx.setdefault((x, y), []).append(e["id"])
        self.alive.add(e["id"])
        self._dirty.add(e["id"])
        if e["kind"] in ("fireplace", "campfire"):
            self.fires.add(e["id"])

    def unplace(self, e: dict):
        i = e["id"]
        if self.ents.pop(i, None) is None:
            return
        s = self.cidx.get((e["x"] >> 5, e["y"] >> 5))
        if s:
            s.discard(i)
        lst = self.tidx.get((e["x"], e["y"]))
        if lst and i in lst:
            lst.remove(i)
            if not lst:
                del self.tidx[(e["x"], e["y"])]
        self.fires.discard(i)
        self._removed.add(i)
        self._dirty.discard(i)

    def destroy(self, e: dict):
        """A thing is used up (eaten, burned): it is gone for good."""
        self.unplace(e)
        i = e["id"]
        self.alive.discard(i)
        self.mod.discard(i)
        if i >= GEN_BASE:
            self.gone.add(i)

    def touch(self, e: dict):
        self.mod.add(e["id"])
        if e["id"] in self.ents:
            self._dirty.add(e["id"])

    def at(self, x: int, y: int) -> list[dict]:
        ids = self.tidx.get((x, y))
        return [self.ents[i] for i in ids] if ids else []

    def find(self, eid: int) -> dict | None:
        return self.ents.get(eid)

    def _ensure_chunk(self, cx: int, cy: int):
        key = (cx, cy)
        if key in self.spawned:
            return
        self.spawned.add(key)
        k = 2048
        for n, (kind, x, y, st) in enumerate(self.terrain.spawns(cx, cy)):
            items = st.get("items")
            i = self._gen_id(cx, cy, n)
            st = {a: b for a, b in st.items() if a != "items"}
            made_items = []
            for ik, ist in items or []:
                ii = self._gen_id(cx, cy, k)
                k += 1
                if ii not in self.gone and ii not in self.alive:
                    made_items.append(dict({"id": ii, "kind": ik, "x": x, "y": y}, **ist))
            if i in self.gone or i in self.alive:
                continue
            e = dict({"id": i, "kind": kind, "x": x, "y": y}, **st)
            if items is not None:
                e["items"] = made_items
                for it in made_items:
                    self.alive.add(it["id"])
            self.place(e, x, y)

    def _ensure_area(self):
        """Things and animals exist around Zen and you."""
        keys = [(self.zen.x >> 5, self.zen.y >> 5)]
        if self.visitor:
            keys.append((self.visitor.x >> 5, self.visitor.y >> 5))
        key = tuple(keys)
        if key == self._area_key:
            return
        self._area_key = key
        for cx, cy in keys:
            for dx in (-2, -1, 0, 1, 2):
                for dy in (-2, -1, 0, 1, 2):
                    self._ensure_chunk(cx + dx, cy + dy)
        active = {(cx + dx, cy + dy) for cx, cy in keys for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
        for k in list(self.animal_chunks - active):
            self._despawn_animals(k)
        for k in sorted(active - self.animal_chunks):
            self._spawn_animals(k)

    # ================================================================== tiles
    def walkable(self, x: int, y: int) -> bool:
        b, w, f = self.terrain.tile(x, y)
        if w == WATER_DEEP or f in BLOCKING:
            return False
        for e in self.at(x, y):
            if KINDS.get(e["kind"], {}).get("blocks"):
                return False
        return True

    def _blocker(self, x: int, y: int) -> str | None:
        b, w, f = self.terrain.tile(x, y)
        if f in BLOCKING:
            return noun_of(FEATURE_KIND[FEATURES[f]])
        if w == WATER_DEEP:
            return "the sea" if BIOMES[b] == "ocean" else "deep water"
        for e in self.at(x, y):
            if KINDS.get(e["kind"], {}).get("blocks"):
                return self.ent_noun(e)
        a = self.animal_at.get((x, y))
        if a is not None and a in self.animals:
            return noun_of(self.animals[a]["kind"])
        return None

    def has_fruit(self, x: int, y: int, f: int | None = None) -> bool:
        f = self.terrain.feature(x, y) if f is None else f
        k = KINDS.get(FEATURE_KIND.get(FEATURES[f], ""), {})
        if not k.get("fruit") or self.season not in k.get("season", ()):
            return False
        if f in (F["palm"], F["jungle_tree"]) and shash(self.seed, x, y, "bears") % 3 == 0:
            return False
        p = self.picked.get((x, y))
        return p is None or self.t - p >= REGROW

    def ent_noun(self, e: dict) -> str:
        k = e["kind"]
        n = noun_of(k)
        if k in ("bucket", "cup") and e.get("water"):
            return f"a {k} of {'sea ' if e.get('salty') else ''}water"
        if k == "lantern" and e.get("lit"):
            return "a lit lantern"
        if k == "fireplace" and e.get("lit"):
            return "the fireplace with a fire burning"
        if k == "campfire":
            return "a burning campfire" if e.get("lit") else "a cold campfire"
        if k == "chest" and e.get("open"):
            return "an open chest"
        if k == "bed" and (e["x"], e["y"]) == (-3, 1):
            return "my bed"
        return n

    def tile_word(self, x: int, y: int, me: tuple | None = None) -> str:
        """The most noticeable thing at a tile, as a noun phrase."""
        a = self.animal_at.get((x, y))
        if a is not None and a in self.animals:
            an = self.animals[a]
            return ("a sleeping " + an["kind"]) if an["state"] == "sleep" and an["kind"] not in ("fish",) \
                else noun_of(an["kind"])
        ents = self.at(x, y)
        if ents:
            furn = [e for e in ents if e["kind"] in _FURNITURE]
            loose = [e for e in ents if e["kind"] not in _FURNITURE]
            if furn:
                n = self.ent_noun(furn[0])
                if loose:
                    n += " with " + count_list([self.ent_noun(e) for e in loose[-3:]])
                return n
            return count_list([self.ent_noun(e) for e in loose[-3:]])
        b, w, f = self.terrain.tile(x, y)
        if f:
            name = FEATURES[f]
            if name == "spring":
                return "a spring"
            n = noun_of(FEATURE_KIND[name])
            if _FRUIT_WITH.get(FEATURE_KIND[name]) and self.has_fruit(x, y, f):
                n += " with " + _FRUIT_WITH[FEATURE_KIND[name]]
            if not w:
                return n
        if w:
            ocean = BIOMES[b] == "ocean"
            if w == WATER_RIVER:
                return "a stream"
            if w == WATER_DEEP:
                return "the deep sea" if ocean else "deep water"
            if self._frozen(x, y):
                return "ice"
            return "shallow sea water" if ocean else "shallow water"
        if self.season == "winter" and self.terrain.base_temp(x, y) + _SEASON_T["winter"] < 2:
            return "snow"
        return _GROUND[BIOMES[b]]

    def _frozen(self, x: int, y: int) -> bool:
        return self.terrain.base_temp(x, y) + _SEASON_T[self.season] < -4

    # ================================================================== places
    def _pois_near(self, x: int, y: int, r: int) -> list[dict]:
        out = []
        for cx in range((x - r) >> 5, ((x + r) >> 5) + 1):
            for cy in range((y - r) >> 5, ((y + r) >> 5) + 1):
                for p in self.terrain.chunk(cx, cy).pois:
                    if abs(p["x"] - x) <= r and abs(p["y"] - y) <= r:
                        out.append(p)
        return out

    def place_at(self, x: int, y: int) -> dict | None:
        best = None
        for p in self._pois_near(x, y, 8):
            d = max(abs(p["x"] - x), abs(p["y"] - y))
            if d <= T.POI_RADIUS.get(p["kind"], 4) and (best is None or d < best[0]):
                best = (d, p)
        return best[1] if best else None

    def _know_place(self, p: dict, visit: bool = True) -> float:
        """Learn of a named place: +0.25 for seeing it from afar, +0.5 in all for reaching it."""
        k = self.places.get(p["name"])
        if k and (k.get("visited") or not visit):
            return 0.0
        gain = 0.0 if p["kind"] == "home" else (0.5 if not k else 0.25) if visit else 0.25
        self.places[p["name"]] = {"name": p["name"], "kind": p["kind"], "x": p["x"], "y": p["y"], "visited": visit}
        if visit and p["kind"] != "home":
            self.note(f"I find {p['name']}.", "place", name=p["name"])
        return gain

    # ================================================================== beings: animals
    def _spawn_animals(self, key: tuple):
        cx, cy = key
        self.animal_chunks.add(key)
        ch = self.terrain.chunk(cx, cy)
        rng = random.Random(shash(self.seed, cx, cy, self.day, self.phase, "animals"))
        b = BIOMES[ch.dominant]
        far = max(abs(cx), abs(cy)) >= 6
        night = self.phase == "night"
        kinds = [(k, p, n) for k, p, n in _ANIMALS.get(b, []) if k != "bear" or far]
        if any(ch.water[i] for i in range(0, CHUNK * CHUNK, 37)):
            kinds.append(("fish", 0.9, 4))
            if self.season != "winter":
                kinds.append(("frog", 0.5, 2))
        if night and self.season == "summer" and b in ("meadow", "forest", "swamp", "grassland", "jungle"):
            kinds.append(("fireflies", 0.8, 2))
        for kind, p, n in kinds:
            if rng.random() >= p:
                continue
            for _ in range(rng.randint(1, n)):
                for _try in range(12):
                    x, y = cx * CHUNK + rng.randrange(CHUNK), cy * CHUNK + rng.randrange(CHUNK)
                    if self._animal_ok(kind, x, y):
                        self._add_animal(kind, x, y, key, rng)
                        break
        for i in self.cidx.get(key, ()):
            e = self.ents.get(i)
            if e and e["kind"] == "beehive":
                for _ in range(2):
                    self._add_animal("bees", e["x"] + rng.choice((-1, 1)), e["y"] + rng.choice((-1, 0, 1)), key, rng,
                                     hx=e["x"], hy=e["y"])

    def _add_animal(self, kind, x, y, key, rng, **kw):
        if (x, y) in self.animal_at:
            return
        a = {"id": self.next_animal, "kind": kind, "x": x, "y": y, "fx": float(x), "fy": float(y),
             "facing": rng.randrange(4), "state": "idle", "chunk": key, "timer": rng.uniform(0.5, 3.0), "cool": 0.0}
        a.update(kw)
        self.next_animal += 1
        self.animals[a["id"]] = a
        self.animal_at[(x, y)] = a["id"]

    def _remove_animal(self, a: dict):
        self.animals.pop(a["id"], None)
        if self.animal_at.get((a["x"], a["y"])) == a["id"]:
            del self.animal_at[(a["x"], a["y"])]

    def _despawn_animals(self, key: tuple):
        self.animal_chunks.discard(key)
        for a in [a for a in self.animals.values() if a["chunk"] == key]:
            self._remove_animal(a)

    def _animal_ok(self, kind: str, x: int, y: int) -> bool:
        if (x, y) in self.animal_at or (x, y) == (self.zen.x, self.zen.y):
            return False
        b, w, f = self.terrain.tile(x, y)
        if kind == "fish":
            return w != 0 and not self._frozen(x, y)
        if kind == "frog" and (BIOMES[b] == "ocean" or self.terrain.base_temp(x, y) + _SEASON_T[self.season] < 6):
            return False
        if kind in ("bees", "fireflies", "bird"):
            return w != WATER_DEEP and f not in (F["wall"], F["stone_wall"], F["cave_wall"]) and \
                f not in SHELTER
        if w == WATER_DEEP or (w and kind not in ("frog",)) or f in BLOCKING or f in SHELTER:
            return False
        if self.tidx.get((x, y)) and not self.walkable(x, y):
            return False
        return True

    def _animals(self, dt: float):
        zx, zy = self.zen.x, self.zen.y
        others = [(zx, zy)] + ([(self.visitor.x, self.visitor.y)] if self.visitor else [])
        night = self.phase == "night"
        k = min(1.0, dt * 5.0)
        for a in list(self.animals.values()):
            a["fx"] += (a["x"] - a["fx"]) * k
            a["fy"] += (a["y"] - a["fy"]) * k
            a["timer"] -= dt
            a["cool"] = max(0.0, a["cool"] - dt)
            if a["timer"] > 0:
                continue
            kind = a["kind"]
            rng = self.rng
            sleepy = (kind in _NIGHT) != night and kind not in ("fish",)
            near = min(max(abs(a["x"] - ox), abs(a["y"] - oy)) for ox, oy in others)
            flee = _FLEE.get(kind, 0)
            if near <= flee and not (sleepy and near > 1) and kind not in ("bees", "fireflies"):
                a["state"] = "flee"
                a["timer"] = 0.35 if kind != "bear" else 0.6
                if not self._step_animal(a, others, away=True) and kind == "bear" and near <= 1 \
                        and a["cool"] <= 0 and not self.zen.sleeping:
                    a["cool"] = 6.0
                    self._hurt(15, "A bear swipes at me! It hurts.", "bear")
                continue
            if sleepy:
                a["state"] = "sleep"
                a["timer"] = rng.uniform(4, 10)
                continue
            a["timer"] = rng.uniform(0.8, 3.5)
            if rng.random() < 0.55:
                a["state"] = "walk"
                self._step_animal(a, others)
            else:
                a["state"] = "idle"

    def _step_animal(self, a: dict, others, away: bool = False) -> bool:
        opts = []
        for d, (dx, dy) in enumerate(DIRS):
            nx, ny = a["x"] + dx, a["y"] + dy
            if not self._animal_ok(a["kind"], nx, ny) or any((nx, ny) == o for o in others):
                continue
            if a["kind"] == "bees" and max(abs(nx - a.get("hx", nx)), abs(ny - a.get("hy", ny))) > 3:
                continue
            if away:
                gain = min(abs(nx - ox) + abs(ny - oy) for ox, oy in others) - \
                    min(abs(a["x"] - ox) + abs(a["y"] - oy) for ox, oy in others)
                if gain <= 0:
                    continue
                opts.append((-gain, d, nx, ny))
            else:
                opts.append((self.rng.random(), d, nx, ny))
        if not opts:
            return False
        opts.sort()
        _, d, nx, ny = opts[0]
        if self.animal_at.get((a["x"], a["y"])) == a["id"]:
            del self.animal_at[(a["x"], a["y"])]
        a["x"], a["y"], a["facing"] = nx, ny, d
        self.animal_at[(nx, ny)] = a["id"]
        return True

    # ================================================================== time passes
    def advance(self, dt: float, day_seconds: float | None = None, night_seconds: float | None = None):
        """Time passes: sky, weather, fires, regrowth, animals, Zen's body, the Sprite."""
        if day_seconds:
            self.day_seconds = float(day_seconds)
        if night_seconds:
            self.night_seconds = float(night_seconds)
        self.tick_n += 1
        self.t += dt
        self.phase_t += dt
        span = self.day_seconds if self.phase == "day" else self.night_seconds
        if self.phase_t >= span:
            self.phase_t -= span
            self._turn_phase()
        self.weather_left -= dt
        if self.weather_left <= 0:
            self._change_weather()
        if self.base_weather in ("rain", "storm"):
            self.last_rain_t = self.t
        self._fires(dt)
        if self.t - self._regen_t >= 30.0:
            self._regen_t = self.t
            self._regrow()
        self._animals(dt)
        wb0 = self.wellbeing()
        h0 = self.zen.needs["health"]
        self._body(dt)
        lost = max(0.0, h0 - self.zen.needs["health"])
        self._passive += WB_GAIN * (self.wellbeing() - wb0) - 0.2 * lost
        self._move_sprite(dt)
        z = self.zen
        k = min(1.0, dt * 8.0)
        z.fx += (z.x - z.fx) * k
        z.fy += (z.y - z.fy) * k
        if self.visitor and self.t - self.visitor.said_t > 10:
            self.visitor.said = ""
        if z.said and self.t - z.said_t > 10:
            z.said = ""
        if self.sprite.said and self.t - self.sprite.said_t > 20 and self.sprite.state != "answering":
            self.sprite.said = ""
        if z.activity and not self.studio and self.t - z.activity_t > 2.5 and not z.sleeping:
            z.activity = ""

    def _turn_phase(self):
        if self.phase == "day":
            self.phase = "night"
            self.note("The sun sets. Night falls.", "phase")
        else:
            self.phase = "day"
            self.day += 1
            self.note(f"The sun rises. It is day {self.day}, {self.season}.", "phase")
            self._new_day()
        for k in list(self.animal_chunks):
            self._despawn_animals(k)
            self._spawn_animals(k)

    def _new_day(self):
        for e in self.ents.values():
            k = e["kind"]
            if k in ("easel", "desk") and e.get("paper", 0) < 5:
                e["paper"] = e.get("paper", 0) + 1
                self.touch(e)
            elif k == "beehive" and e.get("honey", 0) < 3 and self.season != "winter":
                e["honey"] = e.get("honey", 0) + 1
                self.touch(e)
            elif k == "nest" and e.get("eggs", 0) < 3 and self.season in ("spring", "summer"):
                e["eggs"] = e.get("eggs", 0) + 1
                self.touch(e)

    def _change_weather(self):
        r = self.rng
        was = self.base_weather
        self.base_weather = r.choices(WEATHERS, weights=_WEATHER_W[self.season])[0]
        self.weather_left = r.uniform(150.0, 420.0)
        if self.base_weather != was:
            w = self.weather
            self.note({"rain": "It starts to rain.", "storm": "Thunder rumbles. A storm comes.",
                       "snow": "Snow begins to fall.", "fog": "Fog rolls in.", "wind": "The wind picks up.",
                       "clear": "The sky clears.", "cloudy": "Clouds cover the sky."}[w], "weather")

    def _fires(self, dt: float):
        for fid in list(self.fires):
            e = self.ents.get(fid)
            if not e or not e.get("lit"):
                continue
            e["fuel"] = max(0.0, e.get("fuel", 0.0) - dt)
            if e["kind"] == "campfire" and self.weather_at(e["x"], e["y"]) in ("rain", "storm", "snow") \
                    and self.terrain.feature(e["x"], e["y"]) not in SHELTER:
                e["fuel"] = max(0.0, e["fuel"] - 4 * dt)
            if e["fuel"] <= 0:
                e["lit"] = False
                if max(abs(e["x"] - self.zen.x), abs(e["y"] - self.zen.y)) <= 8:
                    self.note(f"The fire in {the(self.ent_noun(e)).replace(' with a fire burning', '')} "
                              f"goes out." if e["kind"] == "fireplace" else "The campfire goes out.", "fire")
            if self.tick_n % 8 == 0 or not e["lit"]:
                self.touch(e)
        for h in self.zen.hands:
            if h["kind"] == "lantern" and h.get("lit"):
                h["fuel"] = max(0.0, h.get("fuel", 900.0) - dt)
                if h["fuel"] <= 0:
                    h["lit"] = False
                    self.note("My lantern goes out.", "fire")

    def _regrow(self):
        """Every half minute, near Zen: apples fall, mushrooms come up after rain, sticks drop."""
        rng = self.rng
        cx0, cy0 = self.zen.x >> 5, self.zen.y >> 5
        season = self.season
        rained = self.t - self.last_rain_t < 900 and season != "winter"
        if self.base_weather in ("rain", "storm"):
            for fid in self.cidx.get((0, 0), ()):
                e = self.ents[fid]
                if e["kind"] == "rain barrel" and e.get("water", 0) < 20:
                    e["water"] = min(20, e.get("water", 0) + 2)
                    self.touch(e)
        for cx in (cx0 - 1, cx0, cx0 + 1):
            for cy in (cy0 - 1, cy0, cy0 + 1):
                ch = self.terrain.chunk(cx, cy)
                ids = self.cidx.get((cx, cy), ())
                loose = sum(1 for i in ids if self.ents[i]["kind"] in ("apple", "mushroom", "toadstool", "stick"))
                if loose >= 14:
                    continue
                for x, y, f in ch.fruit:
                    if f == F["apple_tree"] and season in ("summer", "autumn") and rng.random() < 0.03:
                        self._drop_near(x, y, "apple")
                b = BIOMES[ch.dominant]
                if rained and b in ("forest", "pine_forest", "swamp", "jungle", "meadow") and rng.random() < 0.25:
                    x, y = cx * CHUNK + rng.randrange(CHUNK), cy * CHUNK + rng.randrange(CHUNK)
                    if self.terrain.feature(x, y) in TREES:
                        self._drop_near(x, y, "toadstool" if rng.random() < 0.25 else "mushroom")
                if b in ("forest", "pine_forest", "jungle") and rng.random() < 0.08:
                    x, y = cx * CHUNK + rng.randrange(CHUNK), cy * CHUNK + rng.randrange(CHUNK)
                    if self.terrain.feature(x, y) in TREES:
                        self._drop_near(x, y, "stick")

    def _drop_near(self, x: int, y: int, kind: str):
        for dx, dy in ((0, 1), (1, 0), (-1, 0), (0, -1), (1, 1), (-1, 1)):
            nx, ny = x + dx, y + dy
            b, w, f = self.terrain.tile(nx, ny)
            if not w and f not in BLOCKING and f not in SHELTER and f < F["wall"] and not self.tidx.get((nx, ny)):
                self.place(self.make(kind), nx, ny)
                return

    # ================================================================== Zen's body
    def _body(self, dt: float):
        z, n = self.zen, self.zen.needs
        b, w, f = self.terrain.tile(z.x, z.y)
        inside = f in SHELTER
        weather = self.weather
        near_fire = self._near_fire(z.x, z.y)
        # wet and dry
        if w and not self._frozen(z.x, z.y):
            z.wet = 1.0
        elif not inside and weather in ("rain", "storm"):
            z.wet = min(1.0, z.wet + (0.02 if weather == "rain" else 0.04) * dt)
        elif not inside and weather == "snow":
            z.wet = min(1.0, z.wet + 0.006 * dt)
        else:
            dry = 0.03 if near_fire else 0.008 if (self.phase == "day" and weather == "clear" and not inside) \
                else 0.004 if inside else 0.002
            z.wet = max(0.0, z.wet - dry * dt)
        # needs
        if z.sleeping:
            n["rest"] += (0.22 if z.in_bed else 0.15) * dt
            n["energy"] -= 0.010 * dt
            n["water"] -= 0.012 * dt
        else:
            n["rest"] -= 0.05 * dt
            n["energy"] -= 0.02 * dt
            n["water"] -= 0.03 * dt
        felt = self.air_temp(z.x, z.y) - 6.0 * z.wet + (8.0 if z.sleeping and z.in_bed else 0.0)
        target = max(0.0, min(100.0, 50.0 + (felt - 10.0) * 4.5))
        n["warmth"] += (target - n["warmth"]) * min(1.0, dt / 90.0)
        for k in NEEDS:
            n[k] = max(0.0, min(100.0, n[k]))
        # health
        dmg = (0.06 if n["energy"] <= 0.5 else 0.0) + (0.09 if n["water"] <= 0.5 else 0.0) + \
            (0.12 * (1.0 - n["warmth"] / 10.0) if n["warmth"] < 10 else 0.0)
        if dmg:
            n["health"] = max(0.0, n["health"] - dmg * dt)
        elif n["energy"] > 25 and n["water"] > 25 and n["warmth"] > 25:
            n["health"] = min(100.0, n["health"] + (0.05 if z.sleeping else 0.02) * dt)
        if n["health"] <= 0:
            self._faint()
            return
        # sleep and waking
        if z.sleeping:
            day = self.phase == "day"
            morning = day and self.phase_t < 60
            if (day and n["rest"] >= 98) or (morning and n["rest"] >= 60) or (dmg and n["rest"] > 25):
                z.sleeping = False
                z.in_bed = False
                z.activity = ""
                why = "" if not dmg else " I am " + and_list(self.feelings()[:2]) + "." if self.feelings() else ""
                self.note("I wake up." + why, "wake")
        elif n["rest"] <= 0:
            self._fall_asleep(voluntary=False)

    def _near_fire(self, x: int, y: int) -> bool:
        for fid in self.fires:
            e = self.ents.get(fid)
            if e and e.get("lit") and max(abs(e["x"] - x), abs(e["y"] - y)) <= (4 if e["kind"] == "fireplace" else 2):
                return True
        return False

    def _fall_asleep(self, voluntary: bool):
        z = self.zen
        z.sleeping = True
        z.voluntary = voluntary
        z.in_bed = any(e["kind"] == "bed" for e in self.at(z.x, z.y))
        z.activity = "sleeping"
        if not voluntary:
            self.note("I am so tired that I fall asleep" + (" in my bed." if z.in_bed else " on the ground."), "sleep")

    def _hurt(self, points: float, text: str, why: str):
        n = self.zen.needs
        lost = min(points, n["health"])
        wb0 = self.wellbeing()
        n["health"] -= lost
        self._passive += WB_GAIN * (self.wellbeing() - wb0) - 0.2 * lost
        self.note(text, "hurt", why=why)
        if n["health"] <= 0:
            self._faint()

    def _faint(self):
        z, n = self.zen, self.zen.needs
        wb0 = self.wellbeing()
        for e in z.hands:
            if self.terrain.water(z.x, z.y) == WATER_DEEP:
                self.destroy(e)
            else:
                self.place(e, z.x, z.y)
                self.touch(e)
        z.hands = []
        z.x, z.y, z.facing = -3, 1, 1
        z.fx, z.fy = float(z.x), float(z.y)
        n["health"] = 35.0
        n["energy"] = max(n["energy"], 35.0)
        n["water"] = max(n["water"], 35.0)
        n["rest"] = max(n["rest"], 50.0)
        n["warmth"] = 70.0
        z.wet = 0.0
        z.sleeping = False
        z.in_bed = False
        z.activity = ""
        self.faints += 1
        self._passive -= 1.0 + WB_GAIN * (self.wellbeing() - wb0)      # waking up restored is no gift
        self.sprite.fx, self.sprite.fy = float(z.x + 1), float(z.y)
        self._ensure_area()
        self.note("Everything goes dark and I faint. I wake up in my bed at home.", "faint")

    def wellbeing(self) -> float:
        n = self.zen.needs
        return (_utility(n["energy"]) + _utility(n["water"]) + _utility(n["rest"]) + _utility(n["warmth"]) +
                2 * _utility(n["health"])) / 6.0

    def feelings(self) -> list[str]:
        n, out = self.zen.needs, []
        for need, low, word in (("energy", 40, "hungry"), ("water", 40, "thirsty"), ("rest", 30, "tired"),
                                ("warmth", 35, "cold"), ("health", 50, "hurt")):
            if n[need] < low:
                out.append(("very " if n[need] < low * 0.4 else "") + word)
        if self.zen.wet > 0.5:
            out.append("wet")
        if n["warmth"] > 97 and self.air_temp(self.zen.x, self.zen.y) > 30:
            out.append("hot")
        return out

    # ================================================================== the Sprite and you
    def _move_sprite(self, dt: float):
        z, s = self.zen, self.sprite
        fx, fy = DIRS[z.facing]
        lx, ly = fy, -fx
        tx, ty = z.x + lx - fx, z.y + ly - fy
        if max(abs(s.fx - z.x), abs(s.fy - z.y)) > 4:
            s.fx, s.fy = float(tx), float(ty)
        k = min(1.0, dt * 2.0)
        s.fx += (tx - s.fx) * k
        s.fy += (ty - s.fy) * k
        s.x, s.y = int(round(s.fx)), int(round(s.fy))

    def sprite_say(self, text: str):
        self.sprite.said = (text or "")[:400]
        self.sprite.said_t = self.t

    def sprite_state(self, state: str):
        if state in ("idle", "listening", "answering"):
            self.sprite.state = state

    def visitor_join(self) -> Body:
        if not self.visitor:
            z = self.zen
            spot = (z.x, z.y + 1)
            for r in range(1, 10):
                ring = [(z.x + dx, z.y + dy) for dx in range(-r, r + 1) for dy in range(-r, r + 1)
                        if max(abs(dx), abs(dy)) == r]
                ok = [p for p in ring if self.walkable(*p)]
                if ok:
                    spot = ok[0]
                    break
            self.visitor = Body(x=spot[0], y=spot[1], fx=float(spot[0]), fy=float(spot[1]), facing=0, hands=[],
                                said="", said_t=-1e9)
            self._ensure_area()
            self.note("My friend comes to visit.", "visitor")
        return self.visitor

    def visitor_leave(self):
        v = self.visitor
        if v:
            for e in v.hands:
                self.place(e, v.x, v.y)
                self.touch(e)
            self.visitor = None
            self._area_key = None
            self._ensure_area()
            self.note("My friend leaves.", "visitor")

    def visitor_move(self, x: float, y: float, facing=None):
        v = self.visitor or self.visitor_join()
        tx, ty = int(round(x)), int(round(y))
        if (tx, ty) == (v.x, v.y) or self.walkable(tx, ty):
            v.fx, v.fy, v.x, v.y = float(x), float(y), tx, ty
        if isinstance(facing, str) and facing in DIR_NAMES:
            facing = DIR_NAMES.index(facing)
        if isinstance(facing, (int, float)):
            v.facing = int(facing) % 4
        self._ensure_area()

    def visitor_say(self, text: str) -> bool:
        """You say something. Returns True if Zen is close enough (8 tiles) to hear it."""
        v = self.visitor or self.visitor_join()
        v.said, v.said_t = (text or "")[:400], self.t
        heard = max(abs(v.x - self.zen.x), abs(v.y - self.zen.y)) <= 8
        if heard:
            self.note(f'My friend says: "{v.said}"', "visitor_said", said=v.said)
        return heard

    def visitor_give(self) -> dict | None:
        """Give your last held thing to Zen if you are next to it."""
        v, z = self.visitor, self.zen
        if not v or not v.hands or max(abs(v.x - z.x), abs(v.y - z.y)) > 1:
            return None
        e = v.hands.pop()
        self.touch(e)
        if len(z.hands) < MAX_HANDS and not z.sleeping:
            z.hands.append(e)
            self.note(f"My friend gives me {self.ent_noun(e)}.", "gift", kind=e["kind"])
        else:
            self.place(e, z.x, z.y)
            self.note(f"My friend puts {self.ent_noun(e)} down by me.", "gift", kind=e["kind"])
        return e

    def visitor_take(self, entity_id: int) -> dict | None:
        v = self.visitor
        e = self.ents.get(entity_id)
        if not v or not e or len(v.hands) >= 6 or not KINDS.get(e["kind"], {}).get("portable"):
            return None
        if max(abs(e["x"] - v.x), abs(e["y"] - v.y)) > 2:
            return None
        self.unplace(e)
        self.touch(e)
        v.hands.append(e)
        return e

    def visitor_place(self, kind: str, x: int | None = None, y: int | None = None) -> dict | None:
        """Place a new thing (from ``PLACEABLE``) on a free tile near where you say."""
        if kind not in PLACEABLE:
            return None
        v = self.visitor
        x = int(round(x if x is not None else (v.x if v else self.zen.x)))
        y = int(round(y if y is not None else (v.y if v else self.zen.y + 1)))
        if (x, y) == (self.zen.x, self.zen.y) and kind == "campfire":
            return None
        if not self.walkable(x, y) or self.terrain.water(x, y):
            return None
        st = {"lit": False, "fuel": 0.0} if kind == "campfire" else {"water": 0} if kind in ("cup", "bucket") else \
            {"book": self.rng.randrange(len(T.BOOKS))} if kind == "book" else \
            {"lit": False, "fuel": 900.0} if kind == "lantern" else {}
        e = self.make(kind, **st)
        self.place(e, x, y)
        self.note(f"My friend puts {self.ent_noun(e)} on the ground.", "placed", kind=kind)
        return e

    # ================================================================== hearing and the Sprite's answers
    def heard(self, text: str) -> bool:
        """Zen said something aloud. Returns True if you (the visitor) are near enough to hear it."""
        z = self.zen
        z.said, z.said_t = (text or "")[:400], self.t
        self.log_line(f'I say: "{z.said}"')
        v = self.visitor
        return bool(v and max(abs(v.x - z.x), abs(v.y - z.y)) <= 8)

    def answer_arrived(self):
        self._bonus += 0.4

    def reward_since_last(self) -> float:
        r = self._passive + self._bonus
        self._passive = self._bonus = 0.0
        return round(r, 4)

    # ================================================================== the studio and art
    def set_studio(self, d: dict | None):
        self.studio = d
        self._studio_changed = True

    def create(self, kind: str, author: str = "Zen", data: dict | None = None, title: str = "") -> dict:
        c = {"id": self.next_cid, "kind": kind, "author": author, "title": title or kind.capitalize(),
             "day": self.day, "season": self.season, "t": round(self.t, 1), "data": data or {}, "loves": 0,
             "x": self.zen.x, "y": self.zen.y}
        self.next_cid += 1
        self.creations.append(c)
        self.new_creations.append(c)
        medium = {"paint": "painting", "compose": "music", "sculpt": "sculpture", "write": "poem"}.get(kind, kind)
        if medium in self.practice:
            from .art import grow
            self.practice[medium] = grow(self.practice[medium], "work")
        self.note(f"I finish {('a ' + kind) if kind not in ('music',) else 'a tune'}: {c['title']}.", "create",
                  id=c["id"])
        return c

    def love(self, creation_id: int) -> dict | None:
        c = next((c for c in self.creations if c["id"] == creation_id), None)
        if c:
            c["loves"] = c.get("loves", 0) + 1
            self.new_creations.append(c)
        return c

    def skills(self) -> dict:
        from .art import effective_skill
        return {m: effective_skill(self.practice.get(m, 0.0), "synth", self.zen_stage) for m in MEDIA}

    # ================================================================== log
    def log_line(self, text: str):
        self.log.append(text)
        del self.log[:-40]

    def note(self, text: str, ev: str = "note", /, **data):
        self.log_line(text)
        self.events.append(dict(data, kind=ev, text=text, t=round(self.t, 2), day=self.day))
        del self.events[:-80]

    def take_events(self) -> list[dict]:
        out, self.events = self.events, []
        return out

    # ================================================================== senses
    def _frame(self):
        z = self.zen
        fx, fy = DIRS[z.facing]
        rx, ry = -fy, fx
        return fx, fy, rx, ry

    def ahead(self, n: int = 1) -> tuple[int, int]:
        fx, fy = DIRS[self.zen.facing]
        return self.zen.x + fx * n, self.zen.y + fy * n

    def _sight(self):
        """What Zen can see: (candidates for naming, kinds seen)."""
        z = self.zen
        R = self.sight_radius()
        fx, fy, rx, ry = self._frame()
        inside = self.terrain.feature(z.x, z.y) in SHELTER
        near = {(z.x + fx, z.y + fy), (z.x - rx, z.y - ry), (z.x + rx, z.y + ry), (z.x, z.y)}
        best: dict[str, tuple] = {}
        kinds: set[str] = set()
        ter = self.terrain
        indoorish = SHELTER | {F["wall"], F["door"], F["cave_wall"]}
        for dy in range(-R, R + 1):
            y = z.y + dy
            for dx in range(-R, R + 1):
                if dx * dx + dy * dy > R * R + R:
                    continue
                x = z.x + dx
                b, w, f = ter.tile(x, y)
                if inside and f not in indoorish:
                    continue
                if not inside and f in SHELTER:
                    continue
                d = abs(dx) + abs(dy)
                named = (x, y) not in near
                cands = []
                kinds.add(BIOME_KIND[BIOMES[b]] if not w or b in (0, 1) else "lake")
                if w == WATER_RIVER:
                    kinds.add("river")
                    cands.append(("a stream", 2.0))
                elif w and not self._frozen(x, y):
                    cands.append(("the sea" if BIOMES[b] == "ocean" else "water", 2.0))
                if f:
                    fk = FEATURE_KIND[FEATURES[f]]
                    kinds.add(fk)
                    if _FRUIT_WITH.get(fk) and self.has_fruit(x, y, f):
                        cands.append((f"{noun_of(fk)} with {_FRUIT_WITH[fk]}", 3.0))
                    elif fk == "flowers" and self.has_fruit(x, y, f) and d <= 3:
                        cands.append(("flowers", 1.2))
                    elif fk in ("standing stone", "well", "cairn", "spring", "door", "apple tree", "cave floor"):
                        cands.append(("a cave" if fk == "cave floor" else noun_of(fk), 1.6))
                    elif fk in ("berry bush", "cactus", "palm", "boulder", "stone wall", "stump"):
                        cands.append((noun_of(fk), 1.0))
                ids = self.tidx.get((x, y))
                if ids:
                    for i in ids:
                        e = self.ents[i]
                        kinds.add(e["kind"])
                        k = KINDS.get(e["kind"], {})
                        s = 3.0 if (k.get("food") or k.get("drink")) and k.get("portable") else \
                            2.2 if k.get("portable") else 1.5
                        cands.append((self.ent_noun(e), s))
                a = self.animal_at.get((x, y))
                if a is not None and a in self.animals:
                    an = self.animals[a]
                    kinds.add(an["kind"])
                    cands.append((("a sleeping " + an["kind"]) if an["state"] == "sleep" and an["kind"] != "fish"
                                  else noun_of(an["kind"]), 3.5))
                if not named:
                    continue
                for phrase, s in cands:
                    key = phrase
                    cur = best.get(key)
                    if cur is None or (d, y, x) < (cur[1], cur[3], cur[2]):
                        best[key] = (s, d, x, y)
        out = []
        for phrase, (s, d, x, y) in best.items():
            ddx, ddy = x - z.x, y - z.y
            out.append((-s, d, y, x, phrase, ddx * fx + ddy * fy, ddx * rx + ddy * ry))
        out.sort()
        return out, kinds

    def _header(self) -> str:
        z = self.zen
        p = self.place_at(z.x, z.y)
        if p and p["kind"] == "home" and self.terrain.feature(z.x, z.y) != F["floor"]:
            p = None
        if p and p["kind"] in ("ruins", "cabin", "cave", "stones", "lookout", "home"):
            where = cap(p["name"])
        else:
            b, w, f = self.terrain.tile(z.x, z.y)
            where = cap(BIOME_KIND[BIOMES[b]]) if not (w and BIOMES[b] in ("lake", "ocean")) else \
                ("The sea" if BIOMES[b] == "ocean" else "Lake")
            if f == F["cave_floor"]:
                where = "A cave"
        return f"{where}, {self.time_of_day()}, {temp_word(self.air_temp(z.x, z.y))}, {self.weather}."

    def perceive(self, *_ignored) -> str:
        """What Zen senses now, in ≤ ~45 words: egocentric and deterministic."""
        z = self.zen
        if z.sleeping:
            return "I am asleep."
        fx, fy, rx, ry = self._frame()
        parts = [self._header()]
        if self.sight_radius() <= 1:
            parts.append("It is dark.")
        parts.append(f"Ahead: {self.tile_word(z.x + fx, z.y + fy)}. Left: {self.tile_word(z.x - rx, z.y - ry)}. "
                     f"Right: {self.tile_word(z.x + rx, z.y + ry)}. Here: {self._here_word()}.")
        cands, _ = self._sight()
        seen = [f"{c[4]} {rel_phrase(c[5], c[6])}" for c in cands[:3]]
        tail = []
        if z.hands:
            tail.append("I hold " + count_list([self.ent_noun(e) for e in z.hands]) + ".")
        f = self.feelings()
        if f:
            tail.append("I am " + and_list(f) + ".")
        while True:
            text = " ".join(parts + (["I see " + and_list(seen) + "."] if seen else []) + tail)
            if len(seen) <= 1 or len(text.split()) <= 45:
                return text
            seen.pop()

    def _here_word(self) -> str:
        z = self.zen
        ents = self.at(z.x, z.y)
        b, w, f = self.terrain.tile(z.x, z.y)
        if ents:
            return count_list([self.ent_noun(e) for e in ents[-3:]])
        if f == F["floor"]:
            return "the floor"
        return self.tile_word(z.x, z.y)

    def look(self) -> str:
        """A fuller description (≤ ~120 words): where I am, what is around and what things are."""
        z = self.zen
        fx, fy, rx, ry = self._frame()
        b, w, f = self.terrain.tile(z.x, z.y)
        p = self.place_at(z.x, z.y)
        bk = BIOME_KIND[BIOMES[b]]
        prep = "on" if bk in ("beach", "mountain", "snowfield", "rocky land", "tundra") else "in"
        if p and p["kind"] != "home":
            where = f"I am {'in' if p['kind'] in ('ruins', 'cabin', 'cave') else 'on' if p['kind'] == 'lookout' else 'at'} " \
                    f"{p['name']}"
        elif p and f == F["floor"]:
            where = "I am in my cabin"
        elif w:
            where = "I am in " + ("the sea" if bk == "sea" else "a stream" if w == WATER_RIVER else "the water")
        else:
            where = ("I am near my cabin, " if p else "I am ") + f"{prep} {noun_of(bk)}"
        temp = self.air_temp(z.x, z.y)
        out = [f"{where}. It is {self.time_of_day()} on day {self.day}, in {self.season}. "
               f"The weather is {self.weather} and the air is {temp_word(temp)}."]
        if self.sight_radius() <= 1:
            out.append("It is dark; I can see only what is next to me.")
        out.append(f"Ahead is {self.tile_word(z.x + fx, z.y + fy)}, left {self.tile_word(z.x - rx, z.y - ry)}, "
                   f"right {self.tile_word(z.x + rx, z.y + ry)}, behind {self.tile_word(z.x - fx, z.y - fy)}.")
        cands, _ = self._sight()
        seen = []
        for c in cands[:5]:
            phrase = c[4]
            kind = self._kind_of_phrase(phrase)
            gloss = ""
            if kind:
                k = KINDS[kind]
                ia = k["is_a"]
                gloss = f" ({ia if ia in _MASS else ('an ' if ia[0] in 'aeiou' else 'a ') + ia}"
                if k.get("can"):
                    gloss += f" that can {k['can']}"
                elif k.get("used_for") and k["used_for"] not in ("nothing", "nothing much", "nothing now"):
                    gloss += f", for {k['used_for']}"
                gloss += ")"
            seen.append(f"{phrase} {rel_phrase(c[5], c[6])}{gloss}")
        if seen:
            out.append("I see " + and_list(seen) + ".")
        far = []
        if self.daylight() >= 0.3 and self.terrain.feature(z.x, z.y) not in SHELTER:
            for poi in sorted(self._pois_near(z.x, z.y, 32), key=lambda q: (abs(q["x"] - z.x) + abs(q["y"] - z.y),
                                                                               q["name"])):
                if poi["kind"] == "home" and max(abs(z.x), abs(z.y)) < 8:
                    continue
                ddx, ddy = poi["x"] - z.x, poi["y"] - z.y
                far.append(f"{poi['name']} {rel_phrase(ddx * fx + ddy * fy, ddx * rx + ddy * ry)}")
                self._look_bonus += self._know_place(poi, visit=False)
                if len(far) == 2:
                    break
        if far:
            out.append("Further off: " + and_list(far) + ".")
        if z.hands:
            out.append("I hold " + count_list([self.ent_noun(e) for e in z.hands]) + ".")
        fl = self.feelings()
        out.append(("I feel " + and_list(fl) + ".") if fl else "I feel well.")
        return " ".join(out)

    def _kind_of_phrase(self, phrase: str) -> str | None:
        p = phrase.replace("a sleeping ", "").split(" with ")[0]
        p = {"water": "lake", "a stream": "river", "the sea": "sea", "a cave": "cave", "my bed": "bed",
             "an open chest": "chest", "a burning campfire": "campfire", "a cold campfire": "campfire",
             "a lit lantern": "lantern"}.get(p, p)
        for k, v in KINDS.items():
            if v["noun"] == p or k == p:
                return k
        if p.startswith(("a bucket", "a cup")):
            return p.split()[1]
        return None

    # ================================================================== novelty
    def _mark_visit(self) -> tuple[bool, bool]:
        z = self.zen
        key = (z.x >> 5, z.y >> 5)
        bit = 1 << (((z.y & 31) << 5) | (z.x & 31))
        m = self.visited.get(key)
        new_chunk = m is None
        m = m or 0
        new_tile = not (m & bit)
        self.visited[key] = m | bit
        for cx in ((z.x - 8) >> 5, (z.x + 8) >> 5):
            for cy in ((z.y - 8) >> 5, (z.y + 8) >> 5):
                self.explored.add((cx, cy))
        last = self.trail[-1]
        if abs(last[0] - z.x) + abs(last[1] - z.y) >= 3:
            self.trail.append([z.x, z.y])
            del self.trail[:-4000]
        return new_tile, new_chunk

    def _notice(self) -> tuple[float, list, list]:
        """Novelty after an action: new tiles, chunks, kinds of thing and named places."""
        r, events, texts = 0.0, [], []
        new_tile, new_chunk = self._mark_visit()
        if new_tile:
            r += 0.01
        if new_chunk:
            r += 0.1
            events.append({"kind": "new_chunk"})
        _, kinds = self._sight()
        for k in sorted(kinds - self.seen):
            self.seen.add(k)
            r += 0.25
            events.append({"kind": "new_kind", "what": k})
        p = self.place_at(self.zen.x, self.zen.y)
        if p is None:
            for q in self._pois_near(self.zen.x, self.zen.y, 7):
                if not self.places.get(q["name"], {}).get("visited"):
                    p = q
                    break
        if p:
            gain = self._know_place(p)
            if gain:
                r += gain
                texts.append(f"I find {p['name']}.")
                events.append({"kind": "new_place", "name": p["name"]})
        return r, events, texts

    # ================================================================== actions
    def act(self, word: str, context_text: str | None = None) -> dict:
        """Carry out one motor word. Returns {ok, text, reward, events[, needs_words]}."""
        z = self.zen
        if word not in MOTOR:
            return {"ok": False, "text": "I don't know how to do that.", "reward": -0.01, "events": []}
        if z.sleeping:
            return {"ok": False, "text": "I am asleep.", "reward": 0.0, "events": []}
        self.context_text = context_text or ""
        wb0 = self.wellbeing()
        h0 = z.needs["health"]
        res = getattr(self, "_do_" + word)()
        ok, text = res[0], res[1]
        extra = res[2] if len(res) > 2 else {}
        pain = 0.0
        if not ok:
            pain = -0.02 if extra.pop("blocked", False) else -0.01
        events = extra.pop("events", [])
        bonus = extra.pop("bonus", 0.0)
        lost = max(0.0, h0 - z.needs["health"])
        reward = WB_GAIN * (self.wellbeing() - wb0) + pain - 0.2 * lost + bonus
        if ok:
            what = extra.pop("what", None)
            if word not in self.firsts:
                self.firsts.add(word)
                reward += 0.3
                events.append({"kind": "first", "what": word})
            if what and f"{word}:{what}" not in self.firsts:
                self.firsts.add(f"{word}:{what}")
                reward += 0.1
        else:
            extra.pop("what", None)
        self._ensure_area()
        nov, ev2, texts = self._notice()
        reward += nov
        events += ev2
        if texts:
            text = (text + " " + " ".join(texts)).strip()
        reward = max(-1.0, min(1.0, reward))
        self.last_action = word
        self.steps += 1
        self.reward_rate += (reward - self.reward_rate) * 0.02
        out = {"ok": ok, "text": text, "reward": round(reward, 4), "events": events}
        out.update(extra)
        return out

    def _activity(self, s: str):
        self.zen.activity, self.zen.activity_t = s, self.t

    def _cost(self, energy: float, water: float, rest: float):
        n = self.zen.needs
        n["energy"] = max(0.0, n["energy"] - energy)
        n["water"] = max(0.0, n["water"] - water)
        n["rest"] = max(0.0, n["rest"] - rest)

    # ---- moving
    def _move(self, d: int, word: str):
        z = self.zen
        dx, dy = DIRS[d]
        nx, ny = z.x + dx, z.y + dy
        blk = self._blocker(nx, ny)
        if blk:
            return False, cap(blk) + " is in the way.", {"blocked": True}
        b0, w0, f0 = self.terrain.tile(z.x, z.y)
        b1, w1, f1 = self.terrain.tile(nx, ny)
        z.x, z.y = nx, ny
        self._cost(0.04, 0.03, 0.02)
        self._activity("walking")
        text = [f"I step {word}."]
        if w1 and not w0 and not self._frozen(nx, ny):
            text.append("I wade into the stream." if w1 == WATER_RIVER else "I wade into the water.")
        elif w0 and not w1:
            text.append("I step out of the water.")
        if f1 in SHELTER and f0 not in SHELTER:
            text.append("I go inside." if f1 == F["floor"] else "I go into the cave.")
        elif f0 in SHELTER and f1 not in SHELTER:
            text.append("I go outside.")
        elif not w1 and b1 != b0 and BIOMES[b1] not in ("lake", "ocean") and f1 not in SHELTER:
            text.append(f"I enter {the(noun_of(BIOME_KIND[BIOMES[b1]]))}.")
        return True, " ".join(text)

    def _do_forward(self):
        return self._move(self.zen.facing, "forward")

    def _do_back(self):
        return self._move((self.zen.facing + 2) % 4, "back")

    def _do_left(self):
        self.zen.facing = (self.zen.facing + 3) % 4
        return True, "I turn left."

    def _do_right(self):
        self.zen.facing = (self.zen.facing + 1) % 4
        return True, "I turn right."

    def _do_wait(self):
        self._activity("")
        return True, "I wait."

    def _do_look(self):
        self._activity("looking around")
        self._look_bonus = 0.0
        text = self.look()
        return True, text, {"bonus": self._look_bonus}

    def _do_speak(self):
        self._activity("speaking")
        return True, "", {"needs_words": "speak"}

    def _do_ask(self):
        self._activity("asking")
        return True, "", {"needs_words": "ask"}

    # ---- hands
    def _take_from(self, e: dict, where: str) -> str:
        z = self.zen
        self.unplace(e)
        self.touch(e)
        z.hands.append(e)
        return f"I take {the(self.ent_noun(e))}{where}."

    def _do_take(self):
        z = self.zen
        if len(z.hands) >= MAX_HANDS:
            return False, "My hands are full."
        ax, ay = self.ahead()
        for (x, y) in ((ax, ay), (z.x, z.y)):
            ents = self.at(x, y)
            furn = next((e for e in ents if e["kind"] in _FURNITURE), None)
            loose = [e for e in ents if KINDS.get(e["kind"], {}).get("portable")]
            if loose:
                e = loose[-1]
                where = f" from {the(self.ent_noun(furn))}" if furn and furn["kind"] != "bed" else ""
                self._activity("taking")
                return True, self._take_from(e, where), {"what": e["kind"]}
            if furn:
                r = self._take_furniture(furn)
                if r:
                    return r
            if (x, y) == (ax, ay):
                a = self.animal_at.get((x, y))
                if a is not None and self.animals.get(a, {}).get("kind") == "fish":
                    if self.rng.random() < 0.45:
                        self._remove_animal(self.animals[a])
                        e = self.make("raw fish")
                        z.hands.append(e)
                        self._cost(0.1, 0.05, 0.1)
                        return True, "I grab at the water and catch a fish!", {"what": "raw fish"}
                    return False, "The fish slips away."
            f = self.terrain.feature(x, y)
            fk = FEATURE_KIND.get(FEATURES[f]) if f else None
            if fk and KINDS[fk].get("fruit") and self.has_fruit(x, y, f):
                kind = KINDS[fk]["fruit"]
                self.picked[(x, y)] = self.t
                e = self.make(kind)
                z.hands.append(e)
                self._activity("picking")
                if fk == "flowers":
                    return True, "I pick a flower.", {"what": kind}
                return True, f"I pick {noun_of(kind)} from {the(noun_of(fk))}.", {"what": kind}
        return False, "There is nothing here to take."

    def _take_furniture(self, e: dict):
        z, k = self.zen, e["kind"]
        if k in ("chest", "bookshelf"):
            if k == "chest" and not e.get("open"):
                return False, "The chest is closed."
            if not e.get("items"):
                return False, f"{cap(the(noun_of(k)))} is empty."
            it = e["items"].pop()
            self.touch(e)
            self.touch(it)
            z.hands.append(it)
            return True, f"I take {the(self.ent_noun(it))} from {the(noun_of(k))}.", {"what": it["kind"]}
        give = {"woodpile": ("count", "log"), "beehive": ("honey", "honey"), "nest": ("eggs", "egg"),
                "easel": ("paper", "paper"), "desk": ("paper", "paper")}.get(k)
        if not give:
            return None
        key, kind = give
        if e.get(key, 0) <= 0:
            return False, {"woodpile": "The woodpile is empty.", "beehive": "There is no honey in the hive.",
                           "nest": "The nest is empty.", "easel": "There is no paper on the easel.",
                           "desk": "There is no paper on the desk."}[k]
        e[key] -= 1
        self.touch(e)
        it = self.make(kind)
        z.hands.append(it)
        text = f"I take {noun_of(kind)} from {the(noun_of(k))}."
        if k == "beehive" and self.rng.random() < 0.5:
            self._hurt(4, "A bee stings me!", "bee")
            text += " A bee stings me!"
        return True, text, {"what": kind}

    def _do_drop(self):
        z = self.zen
        if not z.hands:
            return False, "My hands are empty."
        e = z.hands[-1]
        ax, ay = self.ahead()
        target = next((t for t in self.at(ax, ay) if t["kind"] in _FURNITURE), None)
        k = e["kind"]
        if target:
            tk = target["kind"]
            if tk == "chest" and target.get("open") and len(target.get("items", [])) < 8:
                z.hands.pop()
                target.setdefault("items", []).append(e)
                self.touch(target)
                return True, f"I put {the(self.ent_noun(e))} in the chest.", {"what": k}
            if tk == "bookshelf" and k == "book":
                z.hands.pop()
                target.setdefault("items", []).append(e)
                self.touch(target)
                return True, "I put the book on the bookshelf.", {"what": k}
            if tk in ("easel", "desk") and k == "paper":
                z.hands.pop()
                self.destroy(e)
                target["paper"] = target.get("paper", 0) + 1
                self.touch(target)
                return True, f"I put the paper on {the(noun_of(tk))}.", {"what": k}
            if tk == "woodpile" and k == "log":
                z.hands.pop()
                self.destroy(e)
                target["count"] = target.get("count", 0) + 1
                self.touch(target)
                return True, "I put the log on the woodpile.", {"what": k}
            if tk in ("fireplace", "campfire") and KINDS[k].get("fuel") and k != "lantern":
                return self._fuel(target, e)
        z.hands.pop()
        w = self.terrain.water(z.x, z.y)
        if w and not self._frozen(z.x, z.y):
            if k == "raw fish":
                self.destroy(e)
                return True, "I drop the fish. It swims away.", {"what": k}
            if w == WATER_RIVER:
                self.destroy(e)
                return True, f"I drop {the(self.ent_noun(e))}. The stream carries it away.", {"what": k}
        self.place(e, z.x, z.y)
        self.touch(e)
        return True, f"I drop {the(self.ent_noun(e))}.", {"what": k}

    # ---- eating and drinking
    def _do_eat(self):
        z, n = self.zen, self.zen.needs
        target = None
        for e in reversed(z.hands):
            if KINDS.get(e["kind"], {}).get("food") is not None:
                target = ("held", e)
                break
        ax, ay = self.ahead()
        if not target:
            for (x, y) in ((ax, ay), (z.x, z.y)):
                for e in reversed(self.at(x, y)):
                    if KINDS.get(e["kind"], {}).get("food") is not None:
                        target = ("ground", e)
                        break
                if target:
                    break
        if not target:
            for (x, y) in ((ax, ay), (z.x, z.y)):
                f = self.terrain.feature(x, y)
                fk = FEATURE_KIND.get(FEATURES[f]) if f else None
                if fk and KINDS[fk].get("fruit") and KINDS[KINDS[fk]["fruit"]].get("food") and \
                        self.has_fruit(x, y, f):
                    target = ("plant", (x, y, fk))
                    break
        if not target:
            if z.hands:
                return False, f"I can't eat {the(self.ent_noun(z.hands[-1]))}."
            return False, "I have nothing to eat."
        if n["energy"] >= 97:
            return False, "I am too full to eat."
        hungry = n["energy"] < 40
        if target[0] == "plant":
            x, y, fk = target[1]
            kind = KINDS[fk]["fruit"]
            self.picked[(x, y)] = self.t
            text = f"I eat {noun_of(kind)} from {the(noun_of(fk))}."
        else:
            e = target[1]
            kind = e["kind"]
            if target[0] == "held":
                z.hands.remove(e)
            self.destroy(e)
            text = f"I eat {the(self.ent_noun(e))}."
        k = KINDS[kind]
        n["energy"] = min(100.0, n["energy"] + k.get("food", 0))
        n["water"] = min(100.0, n["water"] + k.get("drink", 0))
        self._activity("eating")
        if k.get("poison"):
            n["health"] = max(0.0, n["health"] - k["poison"])
            text += " It tastes bitter. I feel sick."
            if n["health"] <= 0:
                self._faint()
        elif kind in ("raw fish", "egg"):
            text += " It is raw and slimy."
        elif n["energy"] >= 90:
            text += " I am full."
        elif hungry:
            text += " I am less hungry."
        else:
            text += " It is good."
        return True, text, {"what": kind}

    def _do_drink(self):
        z, n = self.zen, self.zen.needs
        vessel = next((e for e in reversed(z.hands) if e["kind"] in ("cup", "bucket") and e.get("water")), None)
        source = None
        if vessel:
            source = "vessel"
        else:
            ax, ay = self.ahead()
            barrel = next((e for e in self.at(ax, ay) if e["kind"] == "rain barrel"), None)
            if barrel and barrel.get("water", 0) <= 0:
                return False, "The rain barrel is empty."
            if barrel:
                source = "barrel"
            for (x, y) in ((z.x, z.y), (ax, ay)) if not source else ():
                b, w, f = self.terrain.tile(x, y)
                if f == F["well"]:
                    source = "well"
                    break
                if w and not self._frozen(x, y):
                    source = "sea" if BIOMES[b] == "ocean" else "spring" if f == F["spring"] else "fresh"
                    break
                if w:
                    return False, "The water is frozen."
        if not source:
            return False, "There is no water here."
        if n["water"] >= 97 and source != "sea":
            return False, "I am not thirsty."
        thirsty = n["water"] < 40
        self._activity("drinking")
        if source == "vessel" and vessel.get("salty"):
            source = "sea"
            vessel["water"] -= 1
            self.touch(vessel)
            if vessel["water"] <= 0:
                vessel.pop("salty", None)
        if source == "sea":
            n["water"] = max(0.0, n["water"] - 6)
            return True, "I drink the sea water. It is salty. I am more thirsty.", {"what": "sea"}
        if source == "vessel":
            vessel["water"] -= 1
            self.touch(vessel)
            n["water"] = min(100.0, n["water"] + 30)
            text = f"I drink water from the {vessel['kind']}."
            what = vessel["kind"]
        else:
            t = self.terrain.base_temp(z.x, z.y) + _SEASON_T[self.season]
            word = "cold" if t < 12 or source in ("spring", "well") else "cool" if t < 24 else "warm"
            n["water"] = min(100.0, n["water"] + 30)
            if source == "barrel":
                barrel["water"] -= 1
                self.touch(barrel)
            text = {"well": f"I pull up water from the well and drink. It is {word}.",
                    "barrel": "I drink rainwater from the rain barrel.",
                    "spring": "I drink from the spring. The water is cold and clear."}.get(
                source, f"I drink the {word} water.")
            what = source
        text += " I am no longer thirsty." if n["water"] >= 90 else " I am less thirsty." if thirsty else ""
        return True, text, {"what": what}

    # ---- using things
    def _fuel(self, fire: dict, e: dict):
        z = self.zen
        z.hands.remove(e)
        self.destroy(e)
        fire["fuel"] = fire.get("fuel", 0.0) + KINDS[e["kind"]]["fuel"]
        self.touch(fire)
        where = "in the fireplace" if fire["kind"] == "fireplace" else "on the campfire"
        self._activity("tending the fire")
        return True, f"I put {the(noun_of(e['kind']))} {where}." + (" The fire burns brighter." if fire.get("lit")
                                                                     else ""), {"what": e["kind"]}

    def _held(self, kind: str) -> dict | None:
        return next((e for e in reversed(self.zen.hands) if e["kind"] == kind), None)

    def _do_use(self):
        z = self.zen
        ax, ay = self.ahead()
        ahead = self.at(ax, ay)
        furn = next((e for e in ahead if e["kind"] in _FURNITURE), None)
        if furn:
            r = self._use_thing(furn)
            if r:
                return r
        clay = self._held("clay")
        if clay:
            z.hands.remove(clay)
            self.destroy(clay)
            self._activity("sculpting")
            return True, "I knead the clay and begin to shape it.", {"needs_words": "sculpt", "what": "clay"}
        b, w, f = self.terrain.tile(ax, ay)
        r = self._use_feature(ax, ay, f, w, b)
        if r:
            return r
        for e in reversed(ahead):
            r = self._use_thing(e)
            if r:
                return r
        for e in reversed(self.at(z.x, z.y)):
            r = self._use_thing(e)
            if r:
                return r
        bh, wh, fh = self.terrain.tile(z.x, z.y)
        if wh:
            r = self._use_feature(z.x, z.y, fh, wh, bh)
            if r:
                return r
        if fh == F["stump"]:
            z.needs["rest"] = min(100.0, z.needs["rest"] + 2)
            return True, "I sit on the stump and rest a little.", {"what": "stump"}
        for e in reversed(z.hands):
            r = self._use_held(e)
            if r:
                return r
        if furn:
            return False, f"I can't use {the(self.ent_noun(furn))}."
        if f:
            return False, f"I can't use {the(noun_of(FEATURE_KIND[FEATURES[f]]))}."
        return False, "There is nothing here to use."

    def _use_thing(self, e: dict):
        z, k = self.zen, e["kind"]
        if k in ("fireplace", "campfire"):
            fuel = next((h for h in reversed(z.hands) if KINDS[h["kind"]].get("fuel") and h["kind"] != "lantern"),
                        None)
            cook = next((h for h in reversed(z.hands) if KINDS[h["kind"]].get("cooks_to")), None)
            name = the(noun_of(k))
            if e.get("lit") and cook:
                new = KINDS[cook["kind"]]["cooks_to"]
                old = cook["kind"]
                cook["kind"] = new
                self.touch(cook)
                self._activity("cooking")
                return True, f"I cook {the(noun_of(old))} on the fire. Now I have {noun_of(new)}.", {"what": old}
            if not e.get("lit") and self._held("flint") and e.get("fuel", 0) > 0:
                if k == "campfire" and self.weather in ("rain", "storm", "snow"):
                    return False, "I strike the flint, but the rain puts out the sparks."
                e["lit"] = True
                self.fires.add(e["id"])
                self.touch(e)
                self._activity("lighting a fire")
                return True, "I strike the flint. A spark catches and the fire burns.", {"what": k}
            if fuel:
                return self._fuel(e, fuel)
            if not e.get("lit") and self._held("flint"):
                return False, f"There is no wood in {name}."
            if e.get("lit"):
                z.needs["warmth"] = min(100.0, z.needs["warmth"] + 4)
                z.wet = max(0.0, z.wet - 0.2)
                return True, "I warm my hands at the fire.", {"what": k}
            if e.get("fuel", 0) > 0:
                return False, f"{cap(name)} is cold. I need a flint to light it."
            return False, f"{cap(name)} is cold. It needs wood and a flint."
        if k == "easel":
            paper = self._held("paper")
            if e.get("paper", 0) > 0:
                e["paper"] -= 1
                self.touch(e)
            elif paper:
                z.hands.remove(paper)
                self.destroy(paper)
            else:
                return False, "There is no paper on the easel."
            self._activity("painting")
            return True, "I stand at the easel with a brush and a clean sheet of paper.", \
                {"needs_words": "paint", "what": "easel"}
        if k == "rain barrel":
            vessel = next((h for h in reversed(z.hands) if h["kind"] in ("bucket", "cup")), None)
            if not vessel:
                return True, f"I look into the rain barrel. It is {'full' if e.get('water', 0) >= 15 else 'half full' if e.get('water', 0) >= 5 else 'nearly empty' if e.get('water') else 'empty'}.", {"what": k}
            if e.get("water", 0) <= 0:
                return False, "The rain barrel is empty."
            cap_ = KINDS[vessel["kind"]]["vessel"]
            if vessel.get("water", 0) >= cap_:
                return False, f"The {vessel['kind']} is already full."
            take = min(cap_ - vessel.get("water", 0), e["water"])
            e["water"] -= take
            vessel["water"] = vessel.get("water", 0) + take
            vessel.pop("salty", None)
            self.touch(e), self.touch(vessel)
            return True, f"I fill the {vessel['kind']} from the rain barrel.", {"what": vessel["kind"]}
        if k == "piano":
            self._activity("playing the piano")
            return True, "I sit down at the piano and put my hands on the keys.", \
                {"needs_words": "compose", "what": "piano"}
        if k == "desk":
            paper = self._held("paper")
            if e.get("paper", 0) > 0:
                e["paper"] -= 1
                self.touch(e)
            elif paper:
                z.hands.remove(paper)
                self.destroy(paper)
            else:
                return False, "There is no paper on the desk."
            self._activity("writing")
            return True, "I sit at the desk with a pen and a sheet of paper.", {"needs_words": "write", "what": "desk"}
        if k == "chest":
            e["open"] = not e.get("open")
            self.touch(e)
            if e["open"]:
                items = e.get("items", [])
                inside = ("Inside: " + and_list([self.ent_noun(i) for i in items]) + ".") if items else \
                    "It is empty."
                return True, f"I open the chest. {inside}", {"what": k}
            return True, "I close the chest.", {"what": k}
        if k == "bookshelf":
            books = [i for i in e.get("items", []) if i["kind"] == "book"]
            if not books:
                return False, "The bookshelf is empty."
            b = next((i for i in books if i.get("book") not in self.read_books), books[0])
            return self._read(b)
        if k == "book":
            return self._read(e)
        if k == "bed":
            return self._do_sleep()
        if k == "nest":
            n = e.get("eggs", 0)
            return True, f"I look into the nest. There {'is 1 egg' if n == 1 else f'are {n} eggs'}." if n else \
                "I look into the nest. It is empty.", {"what": k}
        if k == "beehive":
            return True, "I listen to the bees humming in the hive.", {"what": k}
        if k == "woodpile":
            return True, f"There are {e.get('count', 0)} logs on the woodpile.", {"what": k}
        if k in ("stick", "log", "pinecone") and self._held("flint"):
            if self.weather in ("rain", "storm", "snow") and self.terrain.feature(e["x"], e["y"]) not in SHELTER:
                return False, "I strike the flint, but the rain puts out the sparks."
            x, y = e["x"], e["y"]
            if (x, y) == (z.x, z.y):
                return False, "I need to put the wood in front of me first."
            fuel = KINDS[k]["fuel"]
            self.destroy(e)
            fire = self.make("campfire", lit=True, fuel=float(fuel))
            self.place(fire, x, y)
            self._activity("lighting a fire")
            return True, f"I strike the flint. The {k} catches fire. A campfire burns.", {"what": "campfire"}
        return None

    def _read(self, b: dict):
        i = int(b.get("book", 0)) % len(T.BOOKS)
        title, text = T.BOOKS[i]
        new = i not in self.read_books
        self.read_books.add(i)
        self._activity("reading")
        return True, f'I read "{title}". It says: "{text}"', {"what": "book", "events": [
            {"kind": "read", "book": title, "new": new}]}

    def _use_feature(self, x: int, y: int, f: int, w: int, b: int):
        z = self.zen
        vessel = next((e for e in reversed(z.hands) if e["kind"] in ("bucket", "cup")), None)
        name = FEATURES[f] if f else ""
        if (w or name == "well") and vessel:
            if w and self._frozen(x, y):
                return False, "The water is frozen."
            cap_ = KINDS[vessel["kind"]]["vessel"]
            if vessel.get("water", 0) >= cap_:
                return False, f"The {vessel['kind']} is already full."
            vessel["water"] = cap_
            salty = BIOMES[b] == "ocean" and name != "well"
            if salty:
                vessel["salty"] = True
            else:
                vessel.pop("salty", None)
            self.touch(vessel)
            self._activity("filling a " + vessel["kind"])
            return True, f"I fill the {vessel['kind']} with {'salty sea ' if salty else ''}water.", \
                {"what": vessel["kind"]}
        if not f:
            return None
        fk = FEATURE_KIND[name]
        if f in TREES:
            if not self._held("axe"):
                return False, f"I need an axe to chop {the(noun_of(fk))}."
            hits = self.chops.get((x, y), 0) + 1
            self._cost(0.4, 0.3, 0.4)
            self._activity("chopping wood")
            if hits < 3:
                self.chops[(x, y)] = hits
                return True, f"I chop {the(noun_of(fk))} with the axe. Chips fly.", {"what": fk}
            self.chops.pop((x, y), None)
            self.terrain.set_feature(x, y, F["stump"])
            self.picked.pop((x, y), None)
            for _ in range(2):
                self.place(self.make("log"), x, y)
            return True, f"I chop {the(noun_of(fk))} with the axe. It falls! Two logs lie by the stump.", \
                {"what": fk}
        if name == "standing_stone":
            carving = T.STONE_TEXTS[shash(self.seed, x, y, "carving") % len(T.STONE_TEXTS)]
            return True, f"I touch the standing stone. It is cold and old. {carving}", {"what": fk}
        if name == "cairn":
            return self._lookout(x, y)
        if name == "well":
            return True, "I look down the well. Water glints far below.", {"what": fk}
        if name == "flowers":
            return True, "I smell the flowers. They smell sweet.", {"what": fk}
        if name == "stump":
            z.needs["rest"] = min(100.0, z.needs["rest"] + 2)
            return True, "I sit on the stump and rest a little.", {"what": fk}
        return None

    def _lookout(self, x: int, y: int):
        z = self.zen
        if self.daylight() < 0.3:
            return False, "I climb the cairn, but it is too dark to see far."
        fx, fy, rx, ry = self._frame()
        seen, events, bonus = [], [], 0.0
        for p in sorted(self._pois_near(x, y, 96), key=lambda q: abs(q["x"] - x) + abs(q["y"] - y)):
            if p["kind"] == "home" and p["name"] in self.places:
                continue
            ddx, ddy = p["x"] - z.x, p["y"] - z.y
            dirn = ("north" if ddy < -abs(ddx) / 2 else "south" if ddy > abs(ddx) / 2 else "") + \
                ("west" if ddx < -abs(ddy) / 2 else "east" if ddx > abs(ddy) / 2 else "")
            seen.append(f"{p['name']} far to the {dirn or 'side'}")
            gain = self._know_place(p, visit=False)
            if gain:
                bonus += gain
                events.append({"kind": "seen_place", "name": p["name"]})
            if len(seen) >= 4:
                break
        self._activity("looking far")
        if not seen:
            return True, "I climb the cairn and look far. I see only land and sky.", {"what": "cairn"}
        return True, "I climb the cairn and look far. I see " + and_list(seen) + ".", {
            "what": "cairn", "events": events, "bonus": bonus}

    def _use_held(self, e: dict):
        k = e["kind"]
        if k == "book":
            return self._read(e)
        if k == "lantern":
            if e.get("lit"):
                e["lit"] = False
                self.touch(e)
                return True, "I put out the lantern.", {"what": k}
            if not self._held("flint"):
                return False, "I need a flint to light the lantern."
            if e.get("fuel", 900.0) <= 0:
                return False, "The lantern has no oil left."
            e["lit"] = True
            e.setdefault("fuel", 900.0)
            self.touch(e)
            return True, "I light the lantern. It glows.", {"what": k}
        if k == "flower":
            return True, "I smell the flower. It smells sweet.", {"what": k}
        if k == "shell":
            return True, "I hold the shell to my ear. It sounds like the sea.", {"what": k}
        return None

    def _do_sleep(self):
        z, n = self.zen, self.zen.needs
        if n["rest"] > 80 and self.phase == "day":
            return False, "I am not tired."
        ax, ay = self.ahead()
        here_bed = any(e["kind"] == "bed" for e in self.at(z.x, z.y))
        if not here_bed and any(e["kind"] == "bed" for e in self.at(ax, ay)) and self._blocker(ax, ay) is None:
            z.x, z.y = ax, ay
            here_bed = True
        self._fall_asleep(voluntary=True)
        return True, "I lie down in the bed and fall asleep." if here_bed else \
            "I lie down on the ground and fall asleep.", {"what": "bed" if here_bed else "ground"}

    # ================================================================== the page
    @staticmethod
    def public(e: dict) -> dict:
        out = {"id": e["id"], "kind": e["kind"], "x": e["x"], "y": e["y"]}
        for k in ("lit", "open", "water", "count", "paper", "honey", "eggs", "salty"):
            if k in e:
                out[k] = e[k]
        if "fuel" in e:
            out["fuel"] = round(e["fuel"])
        if "items" in e:
            out["contents"] = [i["kind"] for i in e["items"]]
        if e["kind"] == "book":
            out["title"] = T.BOOKS[int(e.get("book", 0)) % len(T.BOOKS)][0]
        return out

    def _in_range(self) -> set[int]:
        out = set()
        cs = [(self.zen.x, self.zen.y)] + ([(self.visitor.x, self.visitor.y)] if self.visitor else [])
        keys = {((x >> 5) + dx, (y >> 5) + dy) for x, y in cs for dx in (-2, -1, 0, 1, 2) for dy in (-2, -1, 0, 1, 2)}
        for key in keys:
            for i in self.cidx.get(key, ()):
                e = self.ents[i]
                if any(abs(e["x"] - x) <= ENT_RANGE and abs(e["y"] - y) <= ENT_RANGE for x, y in cs):
                    out.add(i)
        return out

    def snapshot(self, full: bool = False, **_ignored) -> dict:
        z, s = self.zen, self.sprite
        span = self.day_seconds if self.phase == "day" else self.night_seconds
        b = self.terrain.biome(z.x, z.y)
        p = self.place_at(z.x, z.y)
        out = {
            "tick": self.tick_n, "day": self.day, "phase": self.phase, "season": self.season,
            "weather": self.weather, "time": self.time_of_day(), "light": round(self.light_at(z.x, z.y), 3),
            "sun": round(min(1.0, self.phase_t / max(span, 1.0)), 4),
            "temperature": round(self.air_temp(z.x, z.y), 1),
            "zen": {"x": z.x, "y": z.y, "fx": round(z.fx, 2), "fy": round(z.fy, 2), "facing": z.facing,
                    "needs": {k: round(v, 1) for k, v in z.needs.items()}, "feelings": self.feelings(),
                    "hands": [h["kind"] for h in z.hands], "sleeping": z.sleeping, "activity": z.activity,
                    "said": z.said, "waiting": bool(z.waiting), "biome": BIOMES[b],
                    "place": p["name"] if p else "", "wet": round(z.wet, 2), "wellbeing": round(self.wellbeing(), 3)},
            "sprite": {"x": s.x, "y": s.y, "fx": round(s.fx, 2), "fy": round(s.fy, 2), "state": s.state,
                       "said": s.said},
            "visitor": None if not self.visitor else {
                "x": self.visitor.x, "y": self.visitor.y, "fx": round(self.visitor.fx, 2),
                "fy": round(self.visitor.fy, 2), "facing": self.visitor.facing,
                "hands": [h["kind"] for h in self.visitor.hands], "said": self.visitor.said},
            "animals": [{"id": a["id"], "kind": a["kind"], "x": a["x"], "y": a["y"], "fx": round(a["fx"], 2),
                         "fy": round(a["fy"], 2), "facing": a["facing"], "state": a["state"]}
                        for a in self.animals.values()],
            "home": {"x": 0, "y": 0},
            "places": list(self.places.values()),
            "mind": {"plan": "", "motor": {"last": self.last_action, "autonomy": 1, "entropy": None,
                                           "reward_rate": round(self.reward_rate, 4), "steps": self.steps}},
            "skills": self.skills(),
            "log": self.log[-14:],
        }
        rng_ids = self._in_range()
        if full:
            out["full"] = True
            out["ents"] = [self.public(self.ents[i]) for i in sorted(rng_ids)]
            out["removed"] = []
            out["creations"] = self.creations[-8:]
            out["studio"] = self.studio
        else:
            new = (rng_ids - self._sent) | (self._dirty & rng_ids)
            out["ents"] = [self.public(self.ents[i]) for i in sorted(new)]
            out["removed"] = sorted((self._sent - rng_ids) | (self._removed & self._sent))
            if self.new_creations:
                out["creations"] = self.new_creations[:]
            if self._studio_changed:
                out["studio"] = self.studio
        self._studio_changed = False
        self.new_creations.clear()
        self._sent = rng_ids
        self._dirty.clear()
        self._removed.clear()
        return out

    def chunk_payload(self, cx: int, cy: int) -> dict:
        return self.terrain.payload(int(cx), int(cy))

    def world_meta(self) -> dict:
        return {"BIOMES": BIOMES, "FEATURES": FEATURES, "seed": self.seed, "home": {"x": 0, "y": 0}}

    def atlas(self) -> dict:
        return {"explored": [[cx, cy, self.terrain.chunk(cx, cy).dominant] for cx, cy in sorted(self.explored)],
                "places": list(self.places.values()), "trail": self.trail[-2000:] + [[self.zen.x, self.zen.y]],
                "zen": {"x": self.zen.x, "y": self.zen.y}, "home": {"x": 0, "y": 0}}

    # ================================================================== saving
    def state(self) -> dict:
        z = self.zen
        return {
            "version": 4, "seed": self.seed, "t": self.t, "tick": self.tick_n, "day": self.day, "phase": self.phase,
            "phase_t": self.phase_t, "weather": self.base_weather, "weather_left": self.weather_left,
            "last_rain_t": self.last_rain_t, "next_id": self.next_id, "next_cid": self.next_cid,
            "zen": {"x": z.x, "y": z.y, "facing": z.facing, "hands": z.hands, "needs": z.needs,
                    "sleeping": z.sleeping, "in_bed": z.in_bed, "wet": z.wet, "voluntary": z.voluntary},
            "ents": [self.ents[i] for i in sorted(self.mod) if i in self.ents] +
                    [dict(e, x=self.visitor.x, y=self.visitor.y) for e in (self.visitor.hands if self.visitor else [])],
            "gone": sorted(self.gone), "diffs": self.terrain.diff_state(),
            "picked": [[x, y, round(t, 1)] for (x, y), t in self.picked.items()],
            "chops": [[x, y, n] for (x, y), n in self.chops.items()],
            "visited": {f"{cx},{cy}": format(m, "x") for (cx, cy), m in self.visited.items()},
            "explored": sorted(self.explored), "seen": sorted(self.seen), "firsts": sorted(self.firsts),
            "places": list(self.places.values()), "read": sorted(self.read_books), "trail": self.trail[-4000:],
            "faints": self.faints, "creations": self.creations, "practice": self.practice,
            "zen_stage": self.zen_stage, "log": self.log[-40:],
        }

    @classmethod
    def from_state(cls, d: dict) -> "World":
        w = cls(d.get("seed", 11))
        w.load_state(d)
        return w

    def load_state(self, d: dict):
        if d.get("version") != 4:
            return
        for e in list(self.ents.values()):
            self.unplace(e)
        self.ents.clear(), self.cidx.clear(), self.tidx.clear(), self.alive.clear(), self.spawned.clear()
        self.fires.clear()
        self.animals.clear(), self.animal_at.clear(), self.animal_chunks.clear()
        self.t, self.tick_n, self.day = d["t"], d.get("tick", 0), d["day"]
        self.phase, self.phase_t = d["phase"], d["phase_t"]
        self.base_weather, self.weather_left = d["weather"], d["weather_left"]
        self.last_rain_t = d.get("last_rain_t", -1e9)
        self.next_id, self.next_cid = d["next_id"], d.get("next_cid", 1)
        zs = d["zen"]
        z = self.zen
        z.x, z.y, z.facing = zs["x"], zs["y"], zs["facing"]
        z.fx, z.fy = float(z.x), float(z.y)
        z.hands, z.needs = list(zs["hands"]), dict(zs["needs"])
        z.sleeping, z.in_bed, z.wet = zs["sleeping"], zs.get("in_bed", False), zs.get("wet", 0.0)
        z.voluntary = zs.get("voluntary", False)
        self.gone = set(d.get("gone", []))
        self.mod = set()

        def mark(e):
            self.alive.add(e["id"])
            for it in e.get("items", []):
                mark(it)
        for e in z.hands:
            mark(e)
        for e in d.get("ents", []):
            e = dict(e)
            mark(e)
            self.mod.add(e["id"])
            self.place(e, e["x"], e["y"])
        for e in z.hands:
            self.mod.add(e["id"])
        self.terrain.load_diffs(d.get("diffs"))
        self.picked = {(x, y): t for x, y, t in d.get("picked", [])}
        self.chops = {(x, y): n for x, y, n in d.get("chops", [])}
        self.visited = {tuple(int(v) for v in k.split(",")): int(m, 16) for k, m in d.get("visited", {}).items()}
        self.explored = {tuple(e) for e in d.get("explored", [])}
        self.seen, self.firsts = set(d.get("seen", [])), set(d.get("firsts", []))
        self.places = {p["name"]: p for p in d.get("places", [])}
        self.read_books = set(d.get("read", []))
        self.trail = d.get("trail") or [[z.x, z.y]]
        self.faints = d.get("faints", 0)
        self.creations = d.get("creations", [])
        self.practice = dict({m: 0.0 for m in MEDIA}, **d.get("practice", {}))
        self.zen_stage = d.get("zen_stage", 0)
        self.log = d.get("log", [])
        self._area_key = None
        self._sent.clear(), self._dirty.clear(), self._removed.clear()
        self._ensure_area()
        self._move_sprite(10.0)
