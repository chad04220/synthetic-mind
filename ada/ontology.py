"""What exists in Ada's world and what is true about it.

One table serves both halves of the system: the World builds itself from it and describes it in
words, and the Academy turns the same facts into concept drills and concept tests. So the words
Ada studies are the words for the things she meets.
"""
from __future__ import annotations

# kind: properties. noun = how it is named in a sentence; is_a = category; found = place name.
KINDS: dict[str, dict] = {
    # food and drink
    "apple": dict(noun="an apple", glyph="🍎", is_a="fruit", color="red", props=["sweet", "round"],
                  found="orchard", used_for="eating", portable=True, food=30),
    "berry": dict(noun="some berries", glyph="🫐", is_a="fruit", color="blue", props=["small", "sweet"],
                  found="forest", used_for="eating", portable=True, food=12),
    "mushroom": dict(noun="a mushroom", glyph="🍄", is_a="fungus", color="brown", props=["soft"],
                     found="forest", used_for="cooking", portable=True, food=-10, cooked="cooked mushroom"),
    "cooked mushroom": dict(noun="a cooked mushroom", glyph="🍲", is_a="food", color="brown",
                            props=["warm", "tasty"], made_of="mushroom", used_for="eating", portable=True, food=35),
    "wheat": dict(noun="some wheat", glyph="🌾", is_a="grain", color="yellow", props=["dry"],
                  found="field", used_for="baking bread", portable=True),
    "bread": dict(noun="a loaf of bread", glyph="🍞", is_a="food", color="brown", props=["soft", "warm"],
                  made_of="wheat", found="bakery", used_for="eating", portable=True, food=45),
    "bucket": dict(noun="a bucket", glyph="🪣", is_a="tool", color="grey", props=["empty"],
                   made_of="wood", used_for="carrying water", portable=True),
    "water bucket": dict(noun="a bucket of water", glyph="💧", is_a="drink", color="blue", props=["wet", "cold"],
                         used_for="drinking", portable=True, drink=40),
    # materials and tools
    "wood": dict(noun="some wood", glyph="🪵", is_a="material", color="brown", props=["hard"],
                 found="forest", used_for="making fire", portable=True),
    "stone": dict(noun="a stone", glyph="🪨", is_a="material", color="grey", props=["hard", "heavy"],
                  found="lake", used_for="building", portable=True),
    "axe": dict(noun="an axe", glyph="🪓", is_a="tool", color="grey", props=["sharp"],
                made_of="wood and stone", found="workshop", used_for="chopping wood", portable=True),
    "seed": dict(noun="a seed", glyph="🌰", is_a="seed", color="brown", props=["small"],
                 found="field", used_for="planting", portable=True),
    "coin": dict(noun="a coin", glyph="🪙", is_a="money", color="gold", props=["shiny", "small"],
                 found="village", used_for="buying bread", portable=True),
    # things to enjoy and learn from
    "book": dict(noun="a book", glyph="📘", is_a="object", color="blue", props=["full of words"],
                 made_of="paper", found="library", used_for="reading", portable=True),
    "ball": dict(noun="a ball", glyph="⚽", is_a="toy", color="white", props=["round", "bouncy"],
                 found="meadow", used_for="playing", portable=True),
    "flower": dict(noun="a flower", glyph="🌷", is_a="plant", color="pink", props=["pretty", "fragrant"],
                   found="meadow", used_for="smelling", portable=True),
    "lamp": dict(noun="a lamp", glyph="💡", is_a="object", color="yellow", props=["bright"],
                 found="home", used_for="light"),
    "music box": dict(noun="a music box", glyph="🎵", is_a="object", color="gold", props=["musical"],
                      found="home", used_for="music"),
    "telescope": dict(noun="a telescope", glyph="🔭", is_a="tool", color="silver", props=["long"],
                      found="observatory", used_for="looking at stars"),
    "bed": dict(noun="a bed", glyph="🛏️", is_a="furniture", color="white", props=["soft"],
                found="home", used_for="sleeping"),
    "fire pit": dict(noun="a fire pit", glyph="🔥", is_a="place for fire", color="orange", props=["hot", "bright"],
                     found="village", used_for="cooking and warmth"),
    "oven": dict(noun="an oven", glyph="♨️", is_a="machine", color="black", props=["hot"],
                 found="bakery", used_for="baking bread"),
    "well": dict(noun="a well", glyph="⛲", is_a="place for water", color="grey", props=["deep"],
                 found="village", used_for="getting water"),
    "workbench": dict(noun="a workbench", glyph="🛠️", is_a="furniture", color="brown", props=["sturdy"],
                      found="workshop", used_for="making tools"),
    "shrine": dict(noun="the Oracle's shrine", glyph="🔮", is_a="place", color="purple", props=["wise", "glowing"],
                   found="village", used_for="asking questions"),
    "sign": dict(noun="a sign", glyph="🪧", is_a="object", color="brown", props=["full of words"],
                 used_for="reading"),
    "chest": dict(noun="a chest", glyph="🧰", is_a="furniture", color="brown", props=["heavy"],
                  found="home", used_for="keeping things"),
    "sprout": dict(noun="a little sprout", glyph="🌱", is_a="plant", color="green", props=["young", "small"],
                   found="field", used_for="growing wheat"),
    # animals
    "cat": dict(noun="a cat", glyph="🐈", is_a="animal", color="orange", props=["soft", "playful"],
                found="home", can="purr", sound="meow", creature=True),
    "dog": dict(noun="a dog", glyph="🐕", is_a="animal", color="brown", props=["friendly", "loyal"],
                found="village", can="bark", sound="woof", creature=True),
    "bird": dict(noun="a bird", glyph="🐦", is_a="animal", color="blue", props=["small", "quick"],
                 found="meadow", can="fly", sound="tweet", creature=True),
    "fish": dict(noun="a fish", glyph="🐟", is_a="animal", color="silver", props=["slippery"],
                 found="lake", can="swim", creature=True, in_water=True),
}

PLACES: dict[str, str] = {
    "home": "a small cottage with a bed, a lamp and a music box",
    "garden": "the field by the cottage where seeds can grow into wheat",
    "meadow": "a wide grassy meadow full of flowers",
    "orchard": "a grove of apple trees",
    "forest": "a dark forest of tall trees, with mushrooms and berries",
    "lake": "a cool blue lake with fish and smooth stones on the shore",
    "village": "the village square with a well and a fire pit",
    "bakery": "Mira's bakery, warm and smelling of bread",
    "library": "Theo's library, full of books",
    "workshop": "Rowan's workshop, where tools are made",
    "shrine": "the Oracle's shrine, a quiet place to ask questions",
    "observatory": "the observatory on the hill, with a telescope for the stars",
}

# The villagers. Their lines come from the Oracle when it is available; these are fallbacks.
NPCS: dict[str, dict] = {
    "Mira": dict(role="baker", home="bakery", glyph="👩‍🍳", color="#f4a261",
                 lines=["Good morning! The bread is warm today.", "Bring me wheat and I can bake bread.",
                        "Bread is made from wheat. The oven makes it hot and soft."]),
    "Theo": dict(role="librarian", home="library", glyph="🧑‍🏫", color="#8ecae6",
                 lines=["Books are full of words. Words carry ideas.", "Would you like to read a book?",
                        "Every day you can learn something new."]),
    "Rowan": dict(role="gardener and tool maker", home="workshop", glyph="🧑‍🌾", color="#90be6d",
                  lines=["Plant a seed in the garden and give it water.", "An axe is made of wood and stone.",
                         "Wood comes from trees. Use an axe to chop it."]),
}

# A few general truths beyond the world itself, so concepts reach past the garden.
GENERAL_FACTS = [
    ("sun", "is", "hot"), ("sun", "is", "bright"), ("snow", "is", "cold"), ("snow", "color", "white"),
    ("sky", "color", "blue"), ("grass", "color", "green"), ("night", "is", "dark"), ("rain", "is", "wet"),
    ("fire", "is", "hot"), ("ice", "is", "cold"), ("water", "is", "wet"), ("moon", "is", "bright"),
    ("dog", "is a", "animal"), ("rose", "is a", "flower"), ("carrot", "is a", "vegetable"),
    ("banana", "is a", "fruit"), ("banana", "color", "yellow"), ("orange", "is a", "fruit"),
    ("hammer", "is a", "tool"), ("chair", "is a", "furniture"), ("table", "is a", "furniture"),
    ("bird", "can", "fly"), ("fish", "can", "swim"), ("horse", "can", "run"), ("frog", "can", "jump"),
    ("cow", "is a", "animal"), ("cow", "can", "moo"), ("car", "used for", "driving"),
    ("pen", "used for", "writing"), ("cup", "used for", "drinking"), ("spoon", "used for", "eating"),
    ("house", "made of", "bricks"), ("bread", "made of", "wheat"), ("paper", "made of", "wood"),
]


def triples() -> list[tuple[str, str, str]]:
    """Every fact the world itself makes true, plus the general facts."""
    out = []
    for kind, k in KINDS.items():
        out.append((kind, "is a", k["is_a"]))
        out.append((kind, "color", k["color"]))
        for p in k.get("props", []):
            out.append((kind, "is", p))
        for rel, key in (("made of", "made_of"), ("used for", "used_for"), ("found in", "found"), ("can", "can")):
            if k.get(key):
                out.append((kind, rel, k[key]))
    for name, n in NPCS.items():
        out.append((name, "is a", n["role"]))
        out.append((name, "found in", n["home"]))
    out.extend(GENERAL_FACTS)
    return out
