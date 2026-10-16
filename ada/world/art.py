"""Art: what the valley's minds make, and how it is described so the browser can show and play it.

Every work is a small, exact recipe, kept for good in the valley's gallery: a painting is a scene,
a palette and a seed (the browser paints it the same way every time), a recording is a melody
(notes and beats, played in the browser), a sculpture is a stack of shapes in its material, a
building is what was built and where, a piece of writing is its text. Titles and words come from
the mind that made it: a villager's own language model, or the synth's own brain.
"""
from __future__ import annotations

import random

SCENES = {
    "lake": ["water", "hills", "sky", "boat"], "dock": ["water", "boat", "sky"], "river": ["water", "trees", "sky"],
    "forest": ["trees", "trees", "mushrooms", "sky"], "orchard": ["trees", "apples", "hills", "sky"],
    "meadow": ["flowers", "hills", "sky", "butterflies"], "mountains": ["peaks", "snow", "sky"],
    "mine": ["crystals", "rock"], "village": ["houses", "sky", "people"], "market": ["houses", "stalls", "people"],
    "park": ["trees", "pond", "flowers", "sky"], "farm": ["fields", "barn", "sky"], "home": ["window", "lamp", "cat"],
    "observatory": ["stars", "moon", "peaks"], "shrine": ["glow", "hills", "stars"],
}
TIME_SKY = {"dawn": ["#ffb4a2", "#ffcdb2", "#6d6875"], "morning": ["#a8dadc", "#f1faee", "#457b9d"],
            "noon": ["#8ecae6", "#ffffff", "#219ebc"], "afternoon": ["#90e0ef", "#ffe8a3", "#0077b6"],
            "evening": ["#f4a261", "#e76f51", "#6a4c93"], "night": ["#0b132b", "#1c2541", "#5bc0be"]}
SEASON_LAND = {"spring": ["#80b918", "#ffafcc", "#55a630"], "summer": ["#2d6a4f", "#ffd166", "#40916c"],
               "autumn": ["#bc6c25", "#dda15e", "#9c6644"], "winter": ["#e9f5f9", "#adb5bd", "#90a4ae"]}
STYLES = ["calm", "bold", "dreamy", "bright", "stormy", "gentle", "playful"]


SCENIC = ["lake", "mountains", "meadow", "forest", "orchard", "village", "river", "park", "farm", "observatory", "dock"]


def painting(rng: random.Random, place: str, season: str, time_of_day: str, weather: str, mood: str) -> dict:
    # Indoors, at an easel, a painter paints a place from memory (or imagination).
    if place not in SCENES or place in ("studio", "home") and rng.random() < 0.8:
        place = rng.choice(SCENIC)
        time_of_day = rng.choice(["dawn", "morning", "noon", "afternoon", "evening", "night"])
    elements = list(SCENES.get(place, ["hills", "sky", "trees"]))
    if time_of_day == "night" and "stars" not in elements:
        elements.append("stars")
    if weather in ("rain", "snow", "fog"):
        elements.append(weather)
    style = "gentle" if mood == "happy" else "stormy" if "lonely" in mood or "cold" in mood else rng.choice(STYLES)
    palette = TIME_SKY.get(time_of_day, TIME_SKY["noon"]) + SEASON_LAND[season]
    return {"subject": f"{place} in the {time_of_day if time_of_day != 'night' else 'night'}", "place": place,
            "elements": elements, "palette": palette, "style": style, "seed": rng.randrange(1 << 30)}


SCALES = {"major": [0, 2, 4, 5, 7, 9, 11], "minor": [0, 2, 3, 5, 7, 8, 10], "pentatonic": [0, 2, 4, 7, 9],
          "dorian": [0, 2, 3, 5, 7, 9, 10]}


def melody(rng: random.Random, mood: str, season: str, instrument: str = "piano") -> dict:
    scale = "major" if mood in ("happy", "fine") else "minor" if any(w in mood for w in ("lonely", "cold", "tired")) \
        else rng.choice(["pentatonic", "dorian", "major"])
    steps, root = SCALES[scale], rng.choice([57, 60, 62, 64, 65])
    deg, notes = 0, []
    length = rng.choice([16, 20, 24, 32])
    motif = [rng.choice([-2, -1, 1, 2, 0, 3]) for _ in range(4)]
    for i in range(length):
        move = motif[i % 4] if i % 8 < 4 else rng.choice([-2, -1, 0, 1, 2])
        deg = max(-4, min(10, deg + move))
        octave, idx = divmod(deg, len(steps))
        pitch = root + 12 * octave + steps[idx]
        beats = rng.choice([0.5, 0.5, 1, 1, 1, 1.5, 2]) if i < length - 1 else 2
        notes.append([pitch if rng.random() > 0.06 else 0, beats])      # 0 = a rest
    return {"scale": scale, "root": root, "tempo": rng.choice([84, 96, 108, 120, 132]) - (12 if scale == "minor" else 0),
            "notes": notes, "instrument": instrument, "season": season}


MATERIAL_COLOURS = {"stone": ["#a8a29e", "#d6d3d1", "#78716c"], "wood": ["#a47148", "#c08552", "#7f5539"],
                    "clay": ["#c2703d", "#e09f6b", "#9c4a2a"]}


def sculpture(rng: random.Random, material: str) -> dict:
    shapes = ["sphere", "box", "cone", "cylinder", "torus", "octahedron"]
    parts, y = [], 0.0
    for i in range(rng.randint(2, 5)):
        h = round(rng.uniform(0.18, 0.5), 2)
        w = round(rng.uniform(0.2, 0.55) * (1.0 - i * 0.12), 2)
        parts.append({"shape": rng.choice(shapes), "w": w, "h": h, "y": round(y + h / 2, 2),
                      "rot": round(rng.uniform(0, 3.14), 2), "x": round(rng.uniform(-0.08, 0.08), 2)})
        y += h * rng.uniform(0.7, 1.0)
    return {"material": material, "colors": MATERIAL_COLOURS.get(material, MATERIAL_COLOURS["stone"]),
            "parts": parts, "height": round(y, 2)}


def default_title(kind: str, data: dict, rng: random.Random) -> str:
    if kind == "painting":
        return rng.choice(["", "The ", "My "]) + data["subject"].capitalize()
    if kind == "music":
        return rng.choice(["Song of", "Tune for", "Little piece for", "Melody of"]) + " " + \
            rng.choice(["the morning", "the lake", "my friends", "the stars", "the rain", "the bakery", "spring"])
    if kind == "sculpture":
        return rng.choice(["Standing", "Dreaming", "Balance", "Tower", "Little friend", "The wave"]) + \
            f" in {data['material']}"
    return kind.capitalize()
