"""Art: what the synth and its companion make, how it is composed, and how skill grows.

Every work is an exact recipe (a "spec") that the browser renders the same way every time and that is
kept for good among the homestead's keepsakes:

- a painting is a small scene graph: canvas shape, style, palette, light, sky, landscape layers from
  back to front, and objects placed in the picture;
- a song is a composition: key and mode, tempo and metre, chord progressions for each section, a
  melody of scale degrees built from a motif, instruments, a form such as AABA;
- a sculpture is a subject made of shaped parts in a material, with a finish;
- a poem is lines in a form.

Who made it shows. Each creator has a skill for each medium that grows with practice (each work,
each piece of feedback, each work of the other's admired). Skill decides the craft: how carefully a
painting is composed (thirds, layering, a harmonious palette) and how cleanly it is drawn, whether a
song has harmony, sections and cadences, how true a sculpture's form is. The synth's skill is also
held back by how far its language has come, so its first works are naive scribbles and tunes, and
they grow up with it. Wren starts as a fair artist and gets better.

What a work is *about* comes from its maker: the synth's own words ("I paint the moon over the pond.")
or Wren's plan, written by its language model ("plan" dicts below). Everything else is composed here.
"""
from __future__ import annotations

import math
import random
import re

MEDIA = ("painting", "music", "sculpture", "poem")

# ====================================================================== skill
def effective_skill(practice: float, maker: str, stage: int = 0) -> float:
    """How well a maker works. The synth: practice, held back by its language; Wren: a fair start."""
    practice = max(0.0, min(1.0, practice))
    if maker == "companion":
        return round(0.6 + 0.4 * practice, 3)
    lang = max(0.0, min(1.0, stage / 6))
    return round(min(1.0, 0.08 + 0.5 * practice + 0.42 * lang), 3)


def grow(practice: float, how: str) -> float:
    """Practice grows with diminishing returns."""
    gain = {"work": 0.035, "feedback": 0.012, "admire": 0.006, "together": 0.02}.get(how, 0.01)
    return round(min(1.0, practice + gain * (1.0 - practice)), 4)


# ====================================================================== painting
STYLES = ["naive", "watercolor", "impressionist", "oil", "pastel", "ink", "pointillist"]
LAYER_KINDS = ("mountains", "hills", "forest", "water", "field", "meadow", "garden", "path", "snowfield", "beach", "room")
# object -> where it lives in a picture: sky | far | ground | water | air | table
OBJECTS = {
    "sun": "sky", "moon": "sky", "star": "sky", "cloud": "sky", "rainbow": "sky", "bird": "air", "kite": "air",
    "butterfly": "air", "fireflies": "air", "bee": "air",
    "tree": "ground", "pine": "ground", "apple tree": "ground", "house": "far", "barn": "far", "greenhouse": "far",
    "fence": "ground", "bench": "ground", "lamp": "ground", "beehive": "ground", "scarecrow": "ground",
    "flower": "ground", "sunflower": "ground", "pumpkin": "ground", "mushroom": "ground", "rock": "ground",
    "snowman": "ground", "cat": "ground", "hen": "ground", "deer": "ground", "figure": "ground", "path": "ground",
    "duck": "water", "boat": "water", "jetty": "water", "reeds": "water",
    "table": "table", "vase": "table", "teapot": "table", "apple": "table", "bread": "table", "candle": "table",
    "window": "table", "cup": "table", "book": "table",
}
WORDS = {   # words a mind might use -> picture objects or layers
    "moon": "moon", "sun": "sun", "stars": "star", "star": "star", "sky": "cloud", "clouds": "cloud", "cloud": "cloud",
    "rainbow": "rainbow", "bird": "bird", "birds": "bird", "robin": "bird", "owl": "bird", "kite": "kite",
    "butterfly": "butterfly", "butterflies": "butterfly", "fireflies": "fireflies", "bees": "bee", "bee": "bee",
    "tree": "tree", "trees": "tree", "pine": "pine", "pines": "pine", "apple tree": "apple tree", "orchard": "apple tree",
    "house": "house", "home": "house", "barn": "barn", "coop": "barn", "greenhouse": "greenhouse", "fence": "fence",
    "bench": "bench", "lamp": "lamp", "hive": "beehive", "beehive": "beehive", "scarecrow": "scarecrow",
    "flower": "flower", "flowers": "flower", "sunflower": "sunflower", "pumpkin": "pumpkin", "mushroom": "mushroom",
    "mushrooms": "mushroom", "rock": "rock", "stone": "rock", "snowman": "snowman", "cat": "cat", "moss": "cat",
    "hen": "hen", "hens": "hen", "chicken": "hen", "deer": "deer", "duck": "duck", "ducks": "duck", "boat": "boat",
    "jetty": "jetty", "reeds": "reeds", "table": "table", "vase": "vase", "teapot": "teapot", "kettle": "teapot",
    "apple": "apple", "apples": "apple", "bread": "bread", "candle": "candle", "window": "window", "cup": "cup",
    "book": "book", "zen": "figure", "wren": "figure", "me": "figure", "friend": "figure",
    "mountains": "mountains", "hills": "hills", "hill": "hills", "woods": "forest", "forest": "forest",
    "pond": "water", "lake": "water", "stream": "water", "river": "water", "water": "water", "sea": "water",
    "field": "field", "fields": "field", "meadow": "meadow", "garden": "garden", "path": "path", "snow": "snowfield",
    "beach": "beach", "room": "room", "kitchen": "room",
}
SCENES = {   # place -> (layers back to front, objects it usually has)
    "pond": (["hills", "water"], ["duck", "reeds", "jetty", "tree"]),
    "stream": (["hills", "forest", "water"], ["rock", "reeds", "tree"]),
    "woods": (["hills", "forest", "path"], ["pine", "mushroom", "deer", "tree"]),
    "orchard": (["hills", "field"], ["apple tree", "apple tree", "fence", "bird"]),
    "meadow": (["hills", "meadow"], ["flower", "beehive", "butterfly", "tree"]),
    "garden": (["hills", "garden"], ["scarecrow", "pumpkin", "sunflower", "fence"]),
    "coop": (["hills", "field"], ["barn", "hen", "fence"]),
    "lookout": (["mountains", "hills"], ["star", "moon", "pine"]),
    "yard": (["hills", "field", "path"], ["house", "tree", "fence", "bench"]),
    "porch": (["hills", "field", "path"], ["house", "bench", "lamp", "cat"]),
    "greenhouse": (["field", "garden"], ["greenhouse", "sunflower", "flower"]),
    "room": (["room"], ["table", "vase", "window", "cat", "teapot", "apple", "candle"]),
}
INDOOR = {"living room", "kitchen", "little bedroom", "big bedroom", "washroom", "workshop"}
SKY = {"dawn": ("#f6b7a3", "#ffd6a5"), "morning": ("#9ecbea", "#e8f4fa"), "noon": ("#6fb6e6", "#d7eef9"),
       "afternoon": ("#7ab8e0", "#fbe5b6"), "evening": ("#5c4b8a", "#f4a261"), "night": ("#0b1630", "#2a3a68")}
LAND = {"spring": ["#7fb35a", "#a7cf6e", "#5d8f3d", "#f7c6d9"], "summer": ["#4f8f3a", "#86b84a", "#2f6b2f", "#f2d16b"],
        "autumn": ["#b5793a", "#d9a25c", "#8a5a2b", "#c0462e"], "winter": ["#dfe8ee", "#b8c6d1", "#8fa3b3", "#ffffff"]}
MOOD_TINT = {"calm": "#7fa7c9", "joyful": "#f2c14e", "lonely": "#6c7a99", "dreamy": "#b39ddb", "stormy": "#4a5568",
             "cosy": "#e08e45", "playful": "#ef6f6c", "peaceful": "#8fbf9f"}
COLOR_WORDS = {"golden": "#d9a93b", "gray": "#8d8d8d", "amber": "#e0a03a", "crimson": "#b8323c", "navy": "#24396b",
               "violet": "#8e5bb5", "lavender": "#b9a3d6", "cream": "#f3e9d2", "rust": "#b5582e", "sky": "#8ec5e8",
               "red": "#d64545", "blue": "#3f6fb5", "green": "#4f9a4f", "yellow": "#f2c94c", "orange": "#ef8a3a",
               "purple": "#8e5bb5", "pink": "#ee8fb2", "gold": "#d9a93b", "white": "#f4f1ea", "black": "#232323",
               "brown": "#8a5a2b", "grey": "#8d8d8d", "silver": "#b9c2cc", "teal": "#2a9d8f"}
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _hex(c: str, fallback: str) -> str:
    c = (c or "").strip().lower()
    if _HEX.match(c):
        return c
    return COLOR_WORDS.get(c, fallback)


def _mix(a: str, b: str, t: float) -> str:
    ca, cb = [int(a[i:i + 2], 16) for i in (1, 3, 5)], [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(ca, cb))


def words_to_plan(text: str, place: str = "", time: str = "noon", season: str = "spring", weather: str = "clear",
                  mood: str = "") -> dict:
    """A painting plan from a mind's own words ('I paint the moon over the pond.')."""
    t = re.sub(r"[^a-z ]", " ", (text or "").lower())
    elements, layers = [], []
    for w in sorted(WORDS, key=len, reverse=True):
        if re.search(rf"\b{w}\b", t):
            v = WORDS[w]
            (layers if v in LAYER_KINDS else elements).append(v)
            t = re.sub(rf"\b{w}\b", " ", t)
    colors = [c for c in COLOR_WORDS if re.search(rf"\b{c}\b", (text or "").lower())]
    scene = next((p for p, (ls, _) in SCENES.items() if p in (text or "").lower()), "")
    if "night" in t or "moon" in elements or "star" in elements:
        time = "night" if "sun" not in elements else time
    subject = re.sub(r"^\s*i\s+(?:paint|draw|make)\s+(?:a\s+picture\s+of\s+|a\s+painting\s+of\s+)?", "",
                     (text or "").strip(), flags=re.I).rstrip(".")
    return {"subject": subject[:120], "place": scene or place, "time": time, "season": season,
            "weather": weather, "mood": mood, "elements": elements[:8], "layers": layers[:3], "colors": colors[:4]}


def compose_painting(rng: random.Random, plan: dict, skill: float) -> dict:
    """Turn a plan into a painting spec. Skill decides the craft of the composition."""
    s = max(0.0, min(1.0, skill))
    place = plan.get("place") or "meadow"
    if place in INDOOR:
        place = "room" if rng.random() < 0.6 else rng.choice(["pond", "meadow", "orchard", "woods", "lookout"])
    scene_layers, scene_objects = SCENES.get(place, SCENES["meadow"])
    time = plan.get("time") if plan.get("time") in SKY else "noon"
    season = plan.get("season") if plan.get("season") in LAND else "spring"
    weather = plan.get("weather") or "clear"
    mood = (plan.get("mood") or "").lower() or rng.choice(list(MOOD_TINT))
    mood = mood if mood in MOOD_TINT else next((m for m in MOOD_TINT if m in mood), "calm")
    indoors = place == "room"
    # ---- style and canvas
    style = plan.get("style") if plan.get("style") in STYLES else None
    if style is None:
        style = "naive" if s < 0.3 else rng.choice(STYLES[1:] if s > 0.6 else ["naive", "watercolor", "pastel", "impressionist"])
    canvas = [3, 4] if indoors else rng.choice([[4, 3], [4, 3], [16, 9], [1, 1]] if s > 0.5 else [[4, 3]])
    # ---- palette: harmony grows with skill
    top, bottom = SKY[time]
    land = LAND[season]
    tint = MOOD_TINT[mood]
    wanted = [_hex(c, "") for c in plan.get("colors", []) if _hex(c, "")]
    if s < 0.3:
        palette = [rng.choice(list(COLOR_WORDS.values())) for _ in range(5)]
    else:
        palette = [_mix(top, tint, 0.15), _mix(bottom, tint, 0.1)] + [_mix(c, tint, 0.12 * (1 - s)) for c in land]
    palette = (wanted + palette)[:7]
    # ---- composition
    horizon = 0.5 if s < 0.35 else rng.choice([0.38, 0.62, 0.66, 0.34])
    if indoors:
        horizon = 0.62
    layers = []
    names = [l for l in plan.get("layers", []) if l in LAYER_KINDS] or scene_layers
    if weather == "snow" or season == "winter":
        names = ["snowfield" if l in ("field", "meadow", "garden") else l for l in names]
    n_layers = len(names)
    for i, name in enumerate(names):
        far = 1 - i / max(1, n_layers)                      # 1 = farthest
        y = horizon - (0.08 * far if name in ("mountains", "hills", "forest") else -0.02 - 0.1 * (1 - far))
        base = {"mountains": "#7d8aa5", "hills": land[2], "forest": land[2], "water": "#4a86b5", "field": land[0],
                "meadow": land[1], "garden": "#6b4a2f", "path": "#c9a77a", "snowfield": "#eef3f6", "beach": "#e8d7a9",
                "room": "#d9c3a5"}[name]
        color = _mix(base, top, 0.35 * far) if s > 0.4 else base       # aerial perspective, with skill
        layers.append({"type": name, "y": round(max(0.15, min(0.9, y)), 3),
                       "height": round(rng.uniform(0.12, 0.3) if name in ("mountains", "hills") else 0.0, 3),
                       "color": color, "detail": round(0.2 + 0.8 * s, 2), "seed": rng.randrange(1 << 20)})
    # objects: what the maker asked for first, then what the place has; more of them with skill
    want = [o for o in plan.get("elements", []) if o in OBJECTS]
    extra = [o for o in scene_objects if o not in want]
    rng.shuffle(extra)
    count = max(1, min(10, int(1 + s * 7 + (len(want) > 0))))
    names = (want + extra)[:count]
    if time == "night" and "moon" not in names and not indoors:
        names.append("moon")
        if s > 0.5:
            names.append("star")
    if weather == "clear" and time in ("morning", "noon", "afternoon") and not indoors and "sun" not in names and s > 0.4:
        names.append("sun")
    if plan.get("rainbow") or (weather in ("rain",) and s > 0.7 and rng.random() < 0.3):
        names.append("rainbow")
    thirds = [(1 / 3, 2 / 3), (2 / 3, 2 / 3), (1 / 3, 0.55), (2 / 3, 0.5)]
    objects, used = [], []
    for i, name in enumerate(names):
        zone = OBJECTS[name]
        focal = i == 0
        if s > 0.45 and focal and zone in ("ground", "far", "water", "table"):
            x = rng.choice(thirds)[0]
        else:
            x = rng.uniform(0.1, 0.9)
            for _ in range(8):                               # skilled hands keep things from crowding
                if s < 0.5 or all(abs(x - u) > 0.12 for u in used):
                    break
                x = rng.uniform(0.1, 0.9)
        used.append(x)
        if zone == "sky":
            y = rng.uniform(0.08, horizon - 0.12)
        elif zone == "air":
            y = rng.uniform(horizon - 0.25, horizon + 0.05)
        elif zone == "far":
            y = horizon + rng.uniform(0.0, 0.05)
        elif zone == "water":
            y = horizon + rng.uniform(0.06, 0.25)
        elif zone == "table":
            y = 0.72 if name != "window" else 0.3
        else:
            y = horizon + rng.uniform(0.05, 0.35)
        depth = (y - horizon) / max(0.1, 1 - horizon)        # nearer is bigger, if you know how
        size = (0.08 + 0.18 * max(0.0, depth)) if s > 0.35 else rng.uniform(0.08, 0.3)
        if name in ("house", "barn", "greenhouse", "apple tree", "tree", "pine"):
            size *= 1.6
        if name in ("sun", "moon"):
            size = 0.09 + 0.04 * rng.random()
        if name == "rainbow":
            size, y, x = 0.8, horizon, 0.5
        if focal and s > 0.45:
            size *= 1.25
        color = None
        if wanted and name not in ("sun", "moon", "star", "cloud", "rainbow"):
            color = rng.choice(wanted)
        o = {"type": name, "x": round(x, 3), "y": round(min(0.97, y), 3), "size": round(min(0.9, size), 3)}
        if color:
            o["color"] = color
        if name == "figure":
            o["label"] = plan.get("figure", "")
        objects.append(o)
    objects.sort(key=lambda o: o["y"])                      # back to front
    glow = {"dawn": 0.5, "evening": 0.7, "night": 0.3}.get(time, 0.15)
    return {"v": 2, "subject": plan.get("subject") or _scene_words(place, time), "place": place, "style": style,
            "canvas": canvas, "palette": palette, "mood": mood, "weather": weather, "season": season,
            "light": {"time": time, "glow": glow},
            "sky": {"top": top, "bottom": bottom, "clouds": round(rng.uniform(0.1, 0.6) if weather != "clear" else
                                                                  rng.uniform(0, 0.3), 2),
                    "stars": 0.8 if time == "night" else 0.0},
            "horizon": round(horizon, 3), "layers": layers, "objects": objects, "skill": round(s, 3),
            "seed": rng.randrange(1 << 30)}


WHEN = {"dawn": "at dawn", "morning": "in the morning", "noon": "at midday", "afternoon": "in the afternoon",
        "evening": "in the evening", "night": "at night"}


def _scene_words(place: str, time: str) -> str:
    where = {"room": "our room", "lookout": "the view from the lookout"}.get(place, f"the {place}")
    return f"{where} {WHEN.get(time, '')}".strip()


def describe_painting(d: dict) -> str:
    """A painting in plain words (what a mind sees when it looks at it)."""
    if d.get("v") != 2:
        return f"a painting of {d.get('subject', 'something')}"
    things = []
    for o in d.get("objects", []):
        if o["type"] not in things:
            things.append(o["type"])
    style = {"naive": "a simple", "watercolor": "a soft watercolor", "impressionist": "a dappled",
             "oil": "a rich oil", "pastel": "a gentle pastel", "ink": "an ink", "pointillist": "a dotted"}.get(d["style"], "a")
    subject = d.get("subject") or d.get("place", "somewhere")
    when = d.get("light", {}).get("time", "")
    light = f", {WHEN[when]}" if when in WHEN and WHEN[when] not in subject else ""
    named = ["the " + t if t in ("sun", "moon", "rainbow") else t if t in ("fireflies", "stars", "reeds", "bees") else
             ("an " if t[0] in "aeiou" else "a ") + t for t in things[:5]]
    listed = ", ".join(named[:-1]) + " and " + named[-1] if len(named) > 1 else "".join(named)
    return f"{style} painting of {subject}" + (f", with {listed}" if named else "") + light


# ====================================================================== music
SCALES = {"major": [0, 2, 4, 5, 7, 9, 11], "minor": [0, 2, 3, 5, 7, 8, 10], "dorian": [0, 2, 3, 5, 7, 9, 10],
          "mixolydian": [0, 2, 4, 5, 7, 9, 10], "lydian": [0, 2, 4, 6, 7, 9, 11], "pentatonic": [0, 2, 4, 7, 9]}
PROGRESSIONS = {
    "major": [["I", "V", "vi", "IV"], ["I", "IV", "V", "I"], ["I", "vi", "IV", "V"], ["I", "iii", "IV", "V"],
              ["IV", "I", "V", "vi"]],
    "minor": [["i", "iv", "V", "i"], ["i", "VI", "III", "VII"], ["i", "iv", "VII", "III"], ["i", "VII", "VI", "V"]],
    "dorian": [["i", "IV", "i", "VII"], ["i", "ii", "IV", "i"]],
    "mixolydian": [["I", "VII", "IV", "I"], ["I", "v", "IV", "I"]],
    "lydian": [["I", "II", "I", "vii"], ["I", "II", "V", "I"]],
    "pentatonic": [["I", "V", "vi", "IV"], ["I", "IV", "I", "V"]],
}
BRIDGES = {"major": [["IV", "V", "iii", "vi"], ["vi", "IV", "ii", "V"]], "minor": [["VI", "VII", "III", "V"]],
           "dorian": [["IV", "VII", "i", "V"]], "mixolydian": [["IV", "VII", "I", "V"]], "lydian": [["II", "V", "I", "V"]],
           "pentatonic": [["IV", "V", "vi", "V"]]}
NUMERALS = {"i": 0, "ii": 1, "iii": 2, "iv": 3, "v": 4, "vi": 5, "vii": 6}
INSTRUMENTS = ["piano", "music box", "flute", "strings", "bell", "guitar", "voice"]
MOOD_MUSIC = {"happy": ("major", 112), "joyful": ("major", 120), "playful": ("mixolydian", 126), "calm": ("pentatonic", 84),
              "peaceful": ("lydian", 78), "dreamy": ("lydian", 72), "sad": ("minor", 72), "lonely": ("minor", 68),
              "cosy": ("major", 88), "mysterious": ("dorian", 92), "stormy": ("minor", 132), "sleepy": ("pentatonic", 64)}


def _chord_degrees(numeral: str) -> list[int]:
    """Scale degrees of a triad on a roman numeral (0-based, in the 7-note scale)."""
    r = NUMERALS.get(numeral.lower().rstrip("°"), 0)
    return [r, r + 2, r + 4]


def _keep(deg: int, lo: int = -2, hi: int = 9) -> int:
    """Keep a melody singable: bounce back off the edges of its range instead of sticking to them."""
    if deg < lo:
        return lo + (lo - deg)
    if deg > hi:
        return hi - (deg - hi)
    return deg


def compose_music(rng: random.Random, plan: dict, skill: float) -> dict:
    """A song from a plan: harmony, sections and a melody grown from a motif, as far as skill allows."""
    s = max(0.0, min(1.0, skill))
    mood = (plan.get("mood") or "").lower()
    mode, tempo = MOOD_MUSIC.get(mood, (rng.choice(["major", "pentatonic", "dorian"]), rng.choice([84, 96, 108])))
    mode = plan.get("mode") if plan.get("mode") in SCALES else mode
    tempo = int(max(56, min(160, plan.get("tempo") or tempo)))
    lullaby = "lullaby" in (plan.get("idea", "") + plan.get("title", "")).lower() or mood == "sleepy"
    meter = 3 if lullaby or (s > 0.5 and rng.random() < 0.2) else 4
    root = rng.choice([55, 57, 60, 62, 64, 65]) if s > 0.3 else 60
    seven = mode != "pentatonic"
    # form and harmony: one wandering line at first; sections, chords and cadences with skill
    if s < 0.3:
        form, bars = ["A"], 4
    elif s < 0.55:
        form, bars = ["A", "A"], 4
    else:
        form = plan.get("form") if isinstance(plan.get("form"), list) and plan.get("form") else \
            rng.choice([["A", "A", "B", "A"], ["A", "B", "A", "B"], ["A", "B", "A"], ["A", "A", "B", "A", "B", "A"]])
        form = [x for x in form if x in ("A", "B")][:8] or ["A", "B", "A"]
        bars = 8 if s > 0.75 else 4
    prog_a = rng.choice(PROGRESSIONS[mode])
    prog_b = rng.choice(BRIDGES[mode])
    beats_per_bar = meter
    # the motif: one bar of rhythm and contour, reused, varied and answered
    rhythms = {4: [[1, 1, 1, 1], [1.5, 0.5, 1, 1], [0.5, 0.5, 1, 2], [1, 0.5, 0.5, 2], [2, 1, 1]],
               3: [[1, 1, 1], [2, 1], [1.5, 0.5, 1], [1, 0.5, 0.5, 1]]}[meter]
    motif_r = rng.choice(rhythms)
    idea = (plan.get("idea") or "").lower()
    step_pool = [-2, -1, 1, 2] if "falling" not in idea and "rising" not in idea else \
        ([1, 2, 1, -1] if "rising" in idea else [-1, -2, -1, 1])
    motif_c = [rng.choice(step_pool) for _ in motif_r]

    def section(prog: list[str], answer: bool) -> dict:
        chords = (prog * ((bars + len(prog) - 1) // len(prog)))[:bars]
        if s > 0.5:                                         # end on home, with a cadence
            chords[-1] = "I" if mode in ("major", "lydian", "mixolydian", "pentatonic") else "i"
            if bars >= 4:
                chords[-2] = "V" if mode in ("major", "minor", "pentatonic") else chords[-2]
        melody, deg = [], 4 if answer else 2
        for b, ch in enumerate(chords):
            tones = _chord_degrees(ch)
            if s < 0.3:                                     # a wandering line, uneven rhythm
                for _ in range(rng.randint(2, 4)):
                    deg = _keep(deg + rng.choice([-2, -1, 0, 1, 2, 3]))
                    melody.append([deg if rng.random() > 0.1 else None, rng.choice([0.5, 1, 1, 1.5])])
                continue
            r = motif_r if (b % 2 == 0 or rng.random() > s) else rng.choice(rhythms)
            contour = motif_c if b % 4 != 2 else [-c for c in motif_c]          # an answer: the motif inverted
            for i, beats in enumerate(r):
                if i == 0 and rng.random() < 0.3 + 0.6 * s:     # strong beats land on the chord, with skill
                    deg = min(tones + [t + 7 for t in tones] + [t - 7 for t in tones], key=lambda t: abs(t - deg))
                else:
                    deg += contour[i % len(contour)]
                deg = _keep(deg)
                melody.append([deg, beats])
        if s > 0.4 and melody:                              # land home at the end
            melody[-1] = [0 if not answer or s > 0.6 else 4, max(melody[-1][1], 2)]
        total = sum(b for _, b in melody)
        want = bars * beats_per_bar
        if s >= 0.3 and abs(total - want) > 1e-6 and melody:
            melody[-1][1] = round(max(0.5, melody[-1][1] + want - total), 2)
        return {"chords": chords, "melody": melody}

    sections = {"A": section(prog_a, False)}
    if "B" in form:
        sections["B"] = section(prog_b, True)
    instrument = plan.get("instrument") if plan.get("instrument") in INSTRUMENTS else \
        ("music box" if lullaby else rng.choice(["piano", "flute", "strings", "bell", "guitar"]) if s > 0.4 else "piano")
    harmony = "none" if s < 0.3 else ("piano" if instrument != "piano" else rng.choice(["strings", "guitar", "piano"]))
    spec = {"v": 2, "title": plan.get("title", ""), "root": root, "mode": mode, "seven": seven, "tempo": tempo,
            "meter": meter, "bars": bars, "form": form, "sections": sections,
            "instruments": {"melody": instrument, "harmony": harmony, "bass": "bass" if s > 0.55 else "none",
                            "percussion": "soft" if s > 0.7 and mood in ("joyful", "playful", "happy") else "none"},
            "dynamics": "soft" if lullaby or mood in ("calm", "dreamy", "lonely", "sleepy") else "medium",
            "reverb": round(0.25 + 0.35 * (mood in ("dreamy", "peaceful", "calm", "lonely")), 2),
            "swing": round(rng.uniform(0, 0.25) if mood in ("playful", "joyful") else 0, 2),
            "mood": mood or "calm", "skill": round(s, 3)}
    spec["notes"] = melody_notes(spec)
    return spec


def degree_to_midi(deg: int, root: int, mode: str) -> int:
    steps = SCALES.get(mode, SCALES["major"])
    octave, idx = divmod(deg, len(steps))
    return root + 12 * octave + steps[idx]


def melody_notes(spec: dict) -> list:
    """The whole melody as [midi, beats] (0 = a rest): for simple players and the piano roll."""
    out = []
    for name in spec.get("form", ["A"]):
        for deg, beats in spec["sections"].get(name, {}).get("melody", []):
            out.append([0 if deg is None else degree_to_midi(int(deg), spec["root"], spec["mode"]), beats])
    return out


def describe_music(d: dict) -> str:
    if d.get("v") != 2:
        return "a little tune"
    feel = {"major": "bright", "minor": "wistful", "dorian": "mysterious", "pentatonic": "simple", "lydian": "dreamy",
            "mixolydian": "playful"}[d["mode"]]
    shape = "-".join(d["form"]) if len(d["form"]) > 1 else "one short line"
    return f"a {feel} song for the {d['instruments']['melody']}, {d['tempo']} beats a minute, in the form {shape}"


# ====================================================================== sculpture
SUBJECTS = ["cat", "bird", "hen", "owl", "fish", "figure", "tree", "mushroom", "heart", "moon", "spiral", "wave",
            "tower", "flower", "rabbit", "snail", "apple"]
SUBJECT_WORDS = {"apple": "apple", "pear": "apple", "plum": "apple", "fruit": "apple", "kitten": "cat", "moss": "cat",
                 "chicken": "hen", "rooster": "hen", "duck": "bird", "robin": "bird", "sparrow": "bird",
                 "person": "figure", "girl": "figure", "boy": "figure", "zen": "figure", "wren": "figure",
                 "child": "figure", "bunny": "rabbit", "hare": "rabbit", "rose": "flower", "sunflower": "flower",
                 "tulip": "flower", "pine": "tree", "oak": "tree", "toadstool": "mushroom", "shell": "spiral",
                 "love": "heart", "crescent": "moon", "water": "wave", "stones": "tower", "cairn": "tower"}
MATERIALS = {"clay": ["#c2703d", "#e09f6b", "#9c4a2a"], "wood": ["#a47148", "#c08552", "#7f5539"],
             "stone": ["#a8a29e", "#d6d3d1", "#78716c"]}
CREATURES = ("cat", "bird", "hen", "owl", "fish", "figure", "rabbit", "snail")
GLAZES = ["#3d7ea6", "#6a994e", "#d4a373", "#b5838d", "#e9c46a", "#f4f1de"]


def _p(shape, pos, scale, rot=(0, 0, 0), tone=0):
    return {"shape": shape, "pos": list(pos), "scale": list(scale), "rot": list(rot), "tone": tone}


def _template(subject: str, pose: str) -> list[dict]:
    """Parts in a unit space: y up, about one unit tall. tone: 0 base colour, 1 light, 2 dark."""
    P = _p
    if subject == "cat":
        if pose == "sleeping":
            return [P("sphere", (0, .22, 0), (.42, .22, .3)), P("sphere", (.32, .26, .05), (.16, .14, .14)),
                    P("cone", (.36, .38, .0), (.05, .08, .04), (0, 0, -.3)), P("cone", (.28, .39, .1), (.05, .08, .04), (0, 0, .2)),
                    P("torus", (-.1, .16, .22), (.22, .22, .06), (1.4, 0, 0), 2)]
        return [P("sphere", (0, .28, 0), (.24, .28, .2)), P("sphere", (0, .64, .02), (.17, .16, .15)),
                P("cone", (-.09, .8, 0), (.05, .1, .04), (0, 0, .25)), P("cone", (.09, .8, 0), (.05, .1, .04), (0, 0, -.25)),
                P("cylinder", (.16, .2, -.14), (.04, .3, .04), (.6, 0, -.6), 2), P("sphere", (-.05, .66, .15), (.02, .02, .02), tone=2),
                P("sphere", (.05, .66, .15), (.02, .02, .02), tone=2)]
    if subject in ("bird", "hen", "owl"):
        body = (.22, .2, .26) if subject != "owl" else (.22, .3, .2)
        parts = [P("sphere", (0, .3, 0), body), P("sphere", (0, .58 if subject != "owl" else .66, .1), (.13, .13, .13)),
                 P("cone", (0, .57 if subject != "owl" else .62, .25), (.04, .08, .04), (1.57, 0, 0), 2),
                 P("sphere", (-.2, .32, -.02), (.05, .14, .18), (0, 0, .4), 1), P("sphere", (.2, .32, -.02), (.05, .14, .18), (0, 0, -.4), 1)]
        if subject == "hen":
            parts += [P("cone", (0, .72, .1), (.05, .08, .03), tone=2), P("cone", (0, .38, -.3), (.12, .2, .06), (-.9, 0, 0), 1)]
        if subject == "owl":
            parts += [P("cone", (-.08, .8, .05), (.04, .1, .04)), P("cone", (.08, .8, .05), (.04, .1, .04)),
                      P("sphere", (-.05, .68, .2), (.04, .04, .02), tone=1), P("sphere", (.05, .68, .2), (.04, .04, .02), tone=1)]
        if pose == "flying":
            parts[3]["scale"], parts[4]["scale"] = [.4, .04, .16], [.4, .04, .16]
            parts[3]["pos"], parts[4]["pos"] = [-.42, .36, 0], [.42, .36, 0]
        return parts
    if subject == "apple":
        return [P("sphere", (0, .34, 0), (.34, .32, .34)), P("cylinder", (0, .7, 0), (.025, .12, .025), (0, 0, .2), 2),
                P("sphere", (.1, .72, 0), (.1, .025, .05), (0, 0, -.4), 1)]
    if subject == "fish":
        return [P("sphere", (0, .4, 0), (.36, .18, .1)), P("cone", (-.42, .4, 0), (.14, .16, .04), (0, 0, 1.57), 1),
                P("cone", (.05, .58, 0), (.1, .12, .02), tone=1), P("cylinder", (0, .12, 0), (.03, .2, .03), tone=2)]
    if subject == "figure":
        return [P("cylinder", (0, .25, 0), (.18, .5, .14)), P("sphere", (0, .62, 0), (.15, .15, .15)),
                P("cylinder", (-.2, .32, 0), (.05, .3, .05), (0, 0, .35)), P("cylinder", (.2, .32, 0), (.05, .3, .05), (0, 0, -.35)),
                P("sphere", (0, .64, .13), (.03, .03, .03), tone=2)]
    if subject == "tree":
        return [P("cylinder", (0, .25, 0), (.07, .5, .07), tone=2), P("sphere", (0, .62, 0), (.3, .26, .3), tone=1),
                P("sphere", (-.17, .52, .05), (.18, .16, .18), tone=1), P("sphere", (.18, .55, -.03), (.18, .16, .18), tone=1)]
    if subject == "mushroom":
        return [P("cylinder", (0, .2, 0), (.09, .4, .09), tone=1), P("sphere", (0, .44, 0), (.3, .14, .3)),
                P("sphere", (-.1, .53, .12), (.04, .03, .04), tone=1), P("sphere", (.12, .5, .1), (.03, .02, .03), tone=1)]
    if subject == "heart":
        return [P("sphere", (-.12, .55, 0), (.18, .18, .14)), P("sphere", (.12, .55, 0), (.18, .18, .14)),
                P("cone", (0, .32, 0), (.27, .32, .14), (3.14, 0, 0))]
    if subject == "moon":
        return [P("torus", (0, .45, 0), (.3, .3, .1), (0, 0, .5)), P("box", (0, .08, 0), (.3, .12, .2), tone=2)]
    if subject == "rabbit":
        return [P("sphere", (0, .24, 0), (.22, .22, .26)), P("sphere", (0, .5, .14), (.13, .13, .13)),
                P("capsule", (-.05, .75, .1), (.04, .14, .03), (0, 0, .15)), P("capsule", (.05, .75, .1), (.04, .14, .03), (0, 0, -.15)),
                P("sphere", (0, .22, -.24), (.07, .07, .07), tone=1)]
    if subject == "snail":
        return [P("capsule", (0, .1, .05), (.08, .3, .08), (1.57, 0, 0)), P("torus", (0, .3, -.05), (.18, .18, .1), (0, 1.57, 0), 1),
                P("sphere", (0, .3, -.05), (.12, .12, .1), tone=1), P("cylinder", (-.03, .26, .3), (.015, .14, .015), (.4, 0, .2), 2)]
    if subject == "flower":
        parts = [P("cylinder", (0, .3, 0), (.03, .6, .03), tone=2), P("sphere", (0, .62, 0), (.07, .07, .05), tone=1)]
        for i in range(6):
            a = i * math.pi / 3
            parts.append(P("sphere", (math.cos(a) * .12, .62 + math.sin(a) * .12, 0), (.07, .05, .03), (0, 0, a)))
        return parts
    if subject == "spiral":
        return [P("box", (math.cos(i * .6) * .08, .06 + i * .085, math.sin(i * .6) * .08), (.36 - i * .022, .07, .12),
                  (0, i * .5, 0), i % 2) for i in range(12)]
    if subject == "wave":
        return [P("torus", (0, .35, 0), (.32, .32, .08), (0, 0, 0)), P("sphere", (.2, .55, 0), (.12, .08, .08), tone=1),
                P("box", (0, .05, 0), (.5, .1, .2), tone=2)]
    # tower: stacked stones
    return [P("sphere", (0, .06 + i * .14, 0), (.24 - i * .03, .08, .2 - i * .025), (0, i * .7, 0), i % 2) for i in range(6)]


def compose_sculpture(rng: random.Random, plan: dict, skill: float, material: str = "clay") -> dict:
    s = max(0.0, min(1.0, skill))
    subject = plan.get("subject") if plan.get("subject") in SUBJECTS else None
    if subject is None:
        text = (plan.get("about") or "").lower()
        subject = next((x for x in SUBJECTS if x in text), None) or rng.choice(SUBJECTS if s > 0.4 else
                                                                               ["tower", "heart", "moon", "mushroom", "cat"])
    pose = plan.get("pose") or rng.choice(["sitting", "sitting", "sleeping"] + (["flying"] * 2 if subject in ("bird", "owl") else []))
    if subject not in CREATURES:
        pose = "standing"
    elif pose == "flying" and subject not in ("bird", "owl", "hen"):
        pose = "sitting"
    parts = _template(subject, pose)
    wobble = 0.22 * (1 - s)                                  # unsure hands: lopsided, lumpy
    for p in parts:
        p["pos"] = [round(v + rng.uniform(-wobble, wobble) * 0.25, 3) for v in p["pos"]]
        p["scale"] = [round(max(0.01, v * (1 + rng.uniform(-wobble, wobble))), 3) for v in p["scale"]]
        p["rot"] = [round(v + rng.uniform(-wobble, wobble), 3) for v in p["rot"]]
    if s < 0.3 and len(parts) > 3:
        parts = parts[:3]                                    # the details come later
    material = material if material in MATERIALS else "clay"
    colors = list(MATERIALS[material])
    finish = "rough" if s < 0.35 else "smooth" if s < 0.75 else "polished"
    glaze = None
    if material == "clay" and s > 0.6 and rng.random() < 0.6:
        glaze = plan.get("glaze") if _HEX.match(str(plan.get("glaze", ""))) else rng.choice(GLAZES)
    height = max(p["pos"][1] + p["scale"][1] for p in parts)
    return {"v": 2, "subject": subject, "pose": pose, "material": material, "finish": finish, "glaze": glaze,
            "colors": colors, "parts": parts, "height": round(height, 3), "skill": round(s, 3),
            "seed": rng.randrange(1 << 30)}


def describe_sculpture(d: dict) -> str:
    if d.get("v") != 2:
        return f"a sculpture in {d.get('material', 'clay')}"
    pose = {"sleeping": "a sleeping ", "flying": "a flying "}.get(d.get("pose"), "an " if d["subject"][0] in "aeiou" else "a ")
    glaze = " with a coloured glaze" if d.get("glaze") else ""
    return f"{pose}{d['subject']} made of {d['material']}, {d['finish']}{glaze}"


# ====================================================================== poems
FORMS = ["haiku", "quatrain", "free verse", "lullaby", "couplets"]


def poem_spec(text: str, form: str = "", about: str = "") -> dict:
    lines = [l.strip() for l in re.split(r"\n|(?<=[.!?])\s+(?=[A-Z])", text or "") if l.strip()][:16]
    return {"v": 2, "form": form if form in FORMS else ("haiku" if len(lines) == 3 else "free verse"),
            "lines": lines, "about": about[:80]}


POEM_SEEDS = {
    "spring": ["new leaves", "the first bees", "rain on the seedlings", "lambs of cloud"],
    "summer": ["warm stones", "the long light", "bees in the lavender", "the pond asleep in the sun"],
    "autumn": ["red leaves", "apples in the grass", "woodsmoke", "the geese going south"],
    "winter": ["snow on the roof", "the fire's glow", "frost on the window", "the quiet woods"]}
POEM_TIME = {"dawn": "the sky turns pink", "morning": "the hens wake up", "noon": "the shadows hide",
             "afternoon": "the bees hum slow", "evening": "the lamps are lit", "night": "the stars come out"}


def small_poem(rng: random.Random, season: str = "spring", time: str = "noon", about: str = "", synth: str = "Zen",
               form: str = "") -> dict:
    """A small poem from the day itself, when no language model is at hand."""
    seed = about or rng.choice(POEM_SEEDS.get(season, POEM_SEEDS["spring"]))
    when = POEM_TIME.get(time, "the day goes by")
    form = form if form in FORMS else rng.choice(["haiku", "quatrain", "lullaby", "couplets"])
    if form == "haiku":
        lines = [f"{seed.capitalize()}", f"{when}, soft and slow", f"{synth} is watching too"]
    elif form == "lullaby":
        lines = [f"Hush now, {synth}, {when},", f"{seed.capitalize()} will keep till day.",
                 "Close your eyes, the house is warm,", "and I am here to stay."]
    elif form == "couplets":
        lines = [f"I saw {seed} today,", "and wished that it would stay.", f"Then {when} for {synth} and me,",
                 "as quiet as can be."]
    else:
        lines = [f"Today I saw {seed},", f"and then {when}.", f"{synth} held my hand", "and the hollow was ours."]
    return {"title": seed.capitalize() if not seed.startswith("the ") else seed[4:].capitalize(), "form": form,
            "about": seed, "text": "\n".join(lines)}


# ====================================================================== titles and words
def default_title(kind: str, data: dict, rng: random.Random) -> str:
    if kind == "painting":
        subj = str(data.get("subject") or "a picture").strip()
        things = [o["type"] for o in data.get("objects", []) if isinstance(o, dict) and o.get("type")]
        if things and rng.random() < 0.35:
            a = rng.choice(things)
            subj = f"the {a}" + (f" and the {things[-1]}" if things[-1] != a else "")
        bare = re.sub(r"^(the|a|an|our|my)\s+", "", subj, flags=re.I)
        return (rng.choice([bare.capitalize(), "The " + bare, "My " + bare]) if bare != subj else subj[:1].upper() + subj[1:])[:60]
    if kind == "music":
        return rng.choice(["Song of", "Tune for", "Little piece for", "Melody of"]) + " " + \
            rng.choice(["the morning", "the pond", "Moss", "the stars", "the rain", "the kitchen", "spring", "the hens"])
    if kind == "sculpture":
        return f"{str(data.get('subject', 'Form')).capitalize()} in {data.get('material', 'clay')}"
    return kind.capitalize()


def describe(kind: str, data: dict) -> str:
    return {"painting": describe_painting, "music": describe_music, "sculpture": describe_sculpture}.get(
        kind, lambda d: f"a {kind}")(data)


# ---- the old (v1) composers, kept so older keepsakes still make sense
def painting(rng, place, season, time_of_day, weather, mood) -> dict:
    return compose_painting(rng, {"place": place, "time": time_of_day, "season": season, "weather": weather,
                                  "mood": mood}, 0.6)


def melody(rng, mood, season, instrument="piano") -> dict:
    return compose_music(rng, {"mood": mood, "instrument": instrument}, 0.6)


def sculpture(rng, material) -> dict:
    return compose_sculpture(rng, {}, 0.6, material)


# ====================================================================== plans from a language model
def clean_plan(kind: str, raw: dict, place: str = "", time: str = "noon", season: str = "spring",
               weather: str = "clear", mood: str = "") -> dict:
    """Wren's mind returns loose JSON; keep only what the composers understand, in range."""
    raw = raw if isinstance(raw, dict) else {}

    def s(k, n=120):
        v = raw.get(k)
        return re.sub(r"\s+", " ", str(v)).strip()[:n] if isinstance(v, (str, int, float)) and str(v).strip() else ""

    plan = {"title": s("title", 60).strip('"'), "mood": s("mood", 30).lower()}
    if kind == "painting":
        words = " ".join([s("subject", 200)] + [str(x) for x in raw.get("elements", []) if isinstance(x, str)][:12])
        base = words_to_plan(words, place, time, season, weather, plan["mood"] or mood)
        base["subject"] = s("subject", 120) or base["subject"]
        if s("style", 20).lower() in STYLES:
            base["style"] = s("style", 20).lower()
        if s("time", 12).lower() in SKY:
            base["time"] = s("time", 12).lower()
        cols = [c for c in raw.get("colors", []) if isinstance(c, str) and _hex(c, "")][:4]
        base["colors"] = (cols + base["colors"])[:4]
        plan.update({k: v for k, v in base.items() if k != "mood" or not plan["mood"]})
    elif kind == "music":
        mode = s("mode", 16).lower()
        if mode in SCALES:
            plan["mode"] = mode
        try:
            plan["tempo"] = int(max(56, min(160, float(raw.get("tempo")))))
        except (TypeError, ValueError):
            pass
        inst = s("instrument", 20).lower()
        if inst in INSTRUMENTS:
            plan["instrument"] = inst
        form = raw.get("form")
        if isinstance(form, str):
            form = [c for c in form.upper() if c in "AB"]
        if isinstance(form, list):
            form = [str(x).upper() for x in form if str(x).upper() in ("A", "B")][:8]
            if len(form) >= 2:
                plan["form"] = form
        plan["idea"] = s("idea", 160)
        plan["subject"] = s("subject", 120) or plan["idea"]
    elif kind == "sculpture":
        subj = s("subject", 40).lower()
        plan["subject"] = next((x for x in SUBJECTS if re.search(rf"\b{x}", subj)), "") or \
            next((v for k, v in SUBJECT_WORDS.items() if re.search(rf"\b{k}", subj)), "") or None
        plan["about"] = subj
        pose = s("pose", 16).lower()
        pose = {"resting": "sleeping", "asleep": "sleeping", "curled": "sleeping", "lying": "sleeping",
                "sat": "sitting", "perched": "sitting", "soaring": "flying"}.get(pose, pose)
        if pose in ("sitting", "sleeping", "flying", "standing"):
            plan["pose"] = pose
        g = s("glaze", 16)
        if _hex(g, ""):
            plan["glaze"] = _hex(g, "")
        if plan["subject"] is None:
            del plan["subject"]
    elif kind == "poem":
        text = str(raw.get("text") or "").strip()
        text = re.sub(r"[*_#`]+|[\U0001F000-\U0001FFFF\u2600-\u27BF\uFE0F]", "", text)
        text = "\n".join(re.sub(r"\s+([.,!?])", r"\1", re.sub(r"([.!?])\s*\.", r"\1", re.sub(r"[ \t]{2,}", " ", l))).strip()
                         for l in text.split("\n") if l.strip())[:900]
        plan.update({"text": text, "form": s("form", 16).lower() if s("form", 16).lower() in FORMS else "",
                     "about": s("about", 80) or s("subject", 80)})
        plan["subject"] = plan["about"]
    return {k: v for k, v in plan.items() if v not in ("", None, [])}
