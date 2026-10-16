"""What exists in the synth's world and what is true about it.

One table serves both halves of the system: the World builds itself from it and describes it in
words, and the Academy turns the same facts into concept drills and concept tests. So the words
the synth studies are the words for the things it meets.
"""
from __future__ import annotations


def K(noun, glyph, is_a, color, props, **kw):
    return dict(noun=noun, glyph=glyph, is_a=is_a, color=color, props=props, **kw)


# kind: properties. noun = how it is named in a sentence; is_a = category; found = place name.
# portable: can be carried. food / drink: how much it restores. hex: colour for drawing.
KINDS: dict[str, dict] = {
    # ---- food and drink
    "apple": K("an apple", "🍎", "fruit", "red", ["sweet", "round"], found="orchard", used_for="eating",
               portable=True, food=30, value=2, hex="#d9433b"),
    "berry": K("some berries", "🫐", "fruit", "blue", ["small", "sweet"], found="forest", used_for="eating",
               portable=True, food=12, value=1, hex="#4a5bd4"),
    "mushroom": K("a mushroom", "🍄", "fungus", "brown", ["soft"], found="forest", used_for="cooking",
                  portable=True, food=-10, cooked="cooked mushroom", value=2, hex="#b5651d"),
    "cooked mushroom": K("a cooked mushroom", "🍲", "food", "brown", ["warm", "tasty"], made_of="mushroom",
                         used_for="eating", portable=True, food=35, value=4, hex="#8a5a2b"),
    "wheat": K("some wheat", "🌾", "grain", "yellow", ["dry"], found="farm", used_for="baking bread",
               portable=True, value=2, baked="bread", hex="#e9c46a"),
    "bread": K("a loaf of bread", "🍞", "food", "brown", ["soft", "warm"], made_of="wheat", found="bakery",
               used_for="eating", portable=True, food=45, value=5, price=4, hex="#c68b4e"),
    "carrot": K("a carrot", "🥕", "vegetable", "orange", ["crunchy"], found="farm", used_for="eating",
                portable=True, food=18, value=2, cooked="roasted carrot", hex="#f08a24"),
    "roasted carrot": K("a roasted carrot", "🍠", "food", "orange", ["warm", "sweet"], made_of="carrot",
                        used_for="eating", portable=True, food=30, value=4, hex="#d4691d"),
    "pumpkin": K("a pumpkin", "🎃", "vegetable", "orange", ["big", "round"], found="farm", used_for="baking pie",
                 portable=True, food=10, value=4, baked="pumpkin pie", hex="#ef8a17"),
    "pumpkin pie": K("a pumpkin pie", "🥧", "food", "orange", ["sweet", "warm"], made_of="pumpkin",
                     used_for="eating", portable=True, food=55, value=9, hex="#d98e3f"),
    "egg": K("an egg", "🥚", "food", "white", ["smooth", "fragile"], found="farm", used_for="cooking",
             portable=True, food=5, value=2, cooked="fried egg", hex="#f1ede4"),
    "fried egg": K("a fried egg", "🍳", "food", "yellow", ["warm", "tasty"], made_of="egg", used_for="eating",
                   portable=True, food=30, value=4, hex="#ffd166"),
    "milk": K("a jug of milk", "🥛", "drink", "white", ["cold", "creamy"], found="farm", used_for="drinking",
              portable=True, drink=35, food=10, value=3, hex="#f7f7f2"),
    "honey": K("a jar of honey", "🍯", "food", "gold", ["sticky", "sweet"], found="meadow", used_for="eating",
               portable=True, food=25, value=6, hex="#f2b134"),
    "raw fish": K("a raw fish", "🐟", "food", "silver", ["slippery", "wet"], found="lake", used_for="cooking",
                  portable=True, food=-5, cooked="grilled fish", value=3, hex="#9db4c0"),
    "grilled fish": K("a grilled fish", "🍢", "food", "brown", ["warm", "tasty"], made_of="fish", used_for="eating",
                      portable=True, food=45, value=6, hex="#a0522d"),
    "bucket": K("a bucket", "🪣", "tool", "grey", ["empty"], made_of="wood", used_for="carrying water",
                portable=True, value=2, price=3, hex="#8d99ae"),
    "water bucket": K("a bucket of water", "💧", "drink", "blue", ["wet", "cold"], used_for="drinking",
                      portable=True, drink=40, value=2, hex="#4ea8de"),
    # ---- materials
    "wood": K("some wood", "🪵", "material", "brown", ["hard"], found="forest", used_for="making fire",
              portable=True, value=1, hex="#8b5a2b"),
    "stone": K("a stone", "🪨", "material", "grey", ["hard", "heavy"], found="lake", used_for="building",
               portable=True, value=1, hex="#8d8d8d"),
    "ore": K("a lump of ore", "⛏️", "material", "dark grey", ["heavy", "rough"], found="mine",
             used_for="making tools", portable=True, value=4, hex="#5c5c66"),
    "crystal": K("a crystal", "💎", "gem", "blue", ["shiny", "sparkly"], found="mine", used_for="making lanterns",
                 portable=True, value=10, hex="#7fd3ff"),
    "clay": K("a lump of clay", "🟤", "material", "brown", ["soft", "wet"], found="river", used_for="sculpting",
              portable=True, value=1, hex="#a0522d"),
    "paper": K("a sheet of paper", "📄", "material", "white", ["thin", "light"], made_of="wood", found="library",
               used_for="writing", portable=True, value=1, price=2, hex="#f5f0e1"),
    "seed": K("a wheat seed", "🌰", "seed", "brown", ["small"], found="farm", used_for="planting wheat",
              portable=True, value=1, price=1, grows="wheat", hex="#8a6a3b"),
    "carrot seed": K("a carrot seed", "🫘", "seed", "brown", ["tiny"], found="market", used_for="planting carrots",
                     portable=True, value=1, price=2, grows="carrot", hex="#a0703b"),
    "pumpkin seed": K("a pumpkin seed", "🌱", "seed", "white", ["flat"], found="market",
                      used_for="planting pumpkins", portable=True, value=1, price=3, grows="pumpkin", hex="#e8dcb5"),
    "coin": K("a coin", "🪙", "money", "gold", ["shiny", "small"], found="village", used_for="buying things",
              portable=True, hex="#f2c14e"),
    # ---- tools and made things
    "axe": K("an axe", "🪓", "tool", "grey", ["sharp"], made_of="wood and stone", found="workshop",
             used_for="chopping wood", portable=True, value=6, price=8, hex="#9a9a9a"),
    "fishing rod": K("a fishing rod", "🎣", "tool", "brown", ["long", "bendy"], made_of="wood", found="dock",
                     used_for="fishing", portable=True, value=5, price=7, hex="#a47148"),
    "pickaxe": K("a pickaxe", "⚒️", "tool", "grey", ["heavy", "sharp"], made_of="wood and ore", found="mine",
                 used_for="mining", portable=True, value=7, price=10, hex="#7a7a85"),
    "chisel": K("a chisel", "🔧", "tool", "grey", ["sharp", "small"], made_of="wood and ore", found="workshop",
                used_for="sculpting", portable=True, value=5, price=6, hex="#8d99ae"),
    "hammer": K("a hammer", "🔨", "tool", "grey", ["heavy"], made_of="wood and stone", found="workshop",
                used_for="building", portable=True, value=5, price=6, hex="#6c757d"),
    "recording": K("a music recording", "💿", "music", "silver", ["musical", "shiny"], made_of="music",
                   found="music hall", used_for="listening", portable=True, value=6, hex="#c0c0ff"),
    "poem": K("a poem", "📜", "writing", "white", ["full of words", "beautiful"], made_of="paper",
              used_for="reading", portable=True, value=4, hex="#fff3d6"),
    "sculpture": K("a sculpture", "🗿", "art", "grey", ["beautiful", "solid"], made_of="stone, wood or clay",
                   found="park", used_for="admiring", hex="#b0a8a0", size="big"),
    "birdhouse": K("a birdhouse", "🏠", "building", "brown", ["small", "cosy"], made_of="wood", found="meadow",
                   used_for="birds", hex="#a47148", size="big"),
    "lamp post": K("a lamp post", "🏮", "building", "black", ["tall", "bright"], made_of="ore and wood",
                   found="village", used_for="light at night", hex="#343a40", size="big"),
    "fountain": K("a fountain", "⛲", "building", "grey", ["splashy", "pretty"], made_of="stone", found="park",
                  used_for="admiring", hex="#90a4ae", size="big"),
    "flower bed": K("a flower bed", "🌺", "garden", "pink", ["colourful", "fragrant"], made_of="stone and flowers",
                    found="village", used_for="admiring", hex="#ff8fab", size="big"),
    "kite": K("a kite", "🪁", "toy", "red", ["light", "colourful"], made_of="wood and paper", found="meadow",
              used_for="flying in the wind", portable=True, value=6, price=8, hex="#e63946"),
    "bouquet": K("a bouquet", "💐", "gift", "pink", ["pretty", "fragrant"], made_of="flowers", used_for="giving",
                 portable=True, value=5, hex="#ff8fab"),
    "lantern": K("a lantern", "🏮", "light", "red", ["glowing", "warm"], made_of="ore and crystal",
                 used_for="light at night", portable=True, value=14, hex="#ff6b35"),
    "painting": K("a painting", "🖼️", "art", "colourful", ["beautiful"], made_of="paint", found="studio",
                  used_for="looking at", portable=True, value=8, hex="#c77dff"),
    "snowman": K("a snowman", "⛄", "sculpture", "white", ["cold", "round"], made_of="snow", used_for="fun",
                 hex="#ffffff", size="big"),
    # ---- things to enjoy and learn from
    "book": K("a book", "📘", "object", "blue", ["full of words"], made_of="paper", found="library",
              used_for="reading", portable=True, value=3, price=5, hex="#3d5a80"),
    "ball": K("a ball", "⚽", "toy", "white", ["round", "bouncy"], found="park", used_for="playing",
              portable=True, value=2, price=3, hex="#ffffff"),
    "flower": K("a flower", "🌷", "plant", "pink", ["pretty", "fragrant"], found="meadow", used_for="smelling",
                portable=True, value=1, hex="#ff7eb6"),
    "lamp": K("a lamp", "💡", "object", "yellow", ["bright"], found="home", used_for="light", hex="#ffe66d"),
    "music box": K("a music box", "🎵", "object", "gold", ["musical"], found="home", used_for="music", hex="#e9c46a"),
    "piano": K("a piano", "🎹", "instrument", "black", ["musical", "big"], found="music hall",
               used_for="playing music", hex="#222222", size="big"),
    "easel": K("an easel", "🎨", "furniture", "brown", ["wooden"], found="studio", used_for="painting",
               hex="#b08968", size="big"),
    "blackboard": K("a blackboard", "📝", "furniture", "black", ["dusty"], found="school", used_for="learning",
                    hex="#2b2d42", size="big"),
    "telescope": K("a telescope", "🔭", "tool", "silver", ["long"], found="observatory",
                   used_for="looking at stars", hex="#c0c0c0", size="big"),
    "bed": K("a bed", "🛏️", "furniture", "white", ["soft"], found="home", used_for="sleeping", hex="#e0e0e0",
             size="big"),
    "bench": K("a bench", "🪑", "furniture", "brown", ["wooden"], found="park", used_for="sitting", hex="#8b5a2b",
               size="big", portable=False),
    "swing": K("a swing", "🎠", "toy", "red", ["fun", "high"], found="park", used_for="swinging", hex="#e76f51",
               size="big"),
    "fire pit": K("a fire pit", "🔥", "place for fire", "orange", ["hot", "bright"], found="village",
                  used_for="cooking and warmth", hex="#e85d04", size="big"),
    "oven": K("an oven", "♨️", "machine", "black", ["hot"], found="bakery", used_for="baking bread",
              hex="#3a3a3a", size="big"),
    "stove": K("a stove", "🍳", "machine", "black", ["hot"], found="home", used_for="cooking", hex="#444444",
               size="big"),
    "forge": K("a forge", "🔨", "machine", "red", ["very hot"], found="workshop", used_for="making metal tools",
               hex="#9d0208", size="big"),
    "well": K("a well", "⛲", "place for water", "grey", ["deep"], found="village", used_for="getting water",
              hex="#6c757d", size="big"),
    "workbench": K("a workbench", "🛠️", "furniture", "brown", ["sturdy"], found="workshop",
                   used_for="making tools", hex="#8b5a2b", size="big"),
    "shrine": K("the Oracle's shrine", "🔮", "place", "purple", ["wise", "glowing"], found="shrine",
                used_for="asking questions", hex="#9d4edd", size="big"),
    "sign": K("a sign", "🪧", "object", "brown", ["full of words"], used_for="reading", hex="#a47148", size="big"),
    "chest": K("a chest", "🧰", "furniture", "brown", ["heavy"], found="home", used_for="keeping things",
               hex="#7f5539", size="big"),
    "market stall": K("a market stall", "🏪", "shop", "striped", ["busy"], found="market",
                      used_for="buying and selling", hex="#e07a5f", size="big"),
    "beehive": K("a beehive", "🐝", "home for bees", "yellow", ["buzzing"], found="meadow", used_for="honey",
                 hex="#f4a261", size="big"),
    "ore vein": K("a vein of ore", "🪨", "rock", "dark grey", ["hard"], found="mine", used_for="mining ore",
                  hex="#495057", size="big"),
    "crystal cluster": K("a crystal cluster", "🔷", "rock", "blue", ["glittering"], found="mine",
                         used_for="mining crystals", hex="#48cae4", size="big"),
    "sprout": K("a little sprout", "🌱", "plant", "green", ["young", "small"], found="farm",
                used_for="growing food", hex="#70e000"),
    # ---- animals
    "cat": K("a cat", "🐈", "animal", "orange", ["soft", "playful"], found="home", can="purr", sound="meow",
             creature=True, hex="#f4a261"),
    "dog": K("a dog", "🐕", "animal", "brown", ["friendly", "loyal"], found="village", can="bark", sound="woof",
             creature=True, hex="#a0522d"),
    "bird": K("a bird", "🐦", "animal", "blue", ["small", "quick"], found="meadow", can="fly", sound="tweet",
              creature=True, hex="#4895ef"),
    "fish": K("a fish", "🐠", "animal", "silver", ["slippery"], found="lake", can="swim", creature=True,
              in_water=True, hex="#90e0ef"),
    "chicken": K("a chicken", "🐔", "animal", "white", ["feathery", "noisy"], found="farm", can="lay eggs",
                 sound="cluck", creature=True, hex="#ffffff"),
    "cow": K("a cow", "🐄", "animal", "black and white", ["big", "gentle"], found="farm", can="give milk",
             sound="moo", creature=True, hex="#f8f9fa"),
    "sheep": K("a sheep", "🐑", "animal", "white", ["woolly", "soft"], found="farm", can="grow wool",
               sound="baa", creature=True, hex="#f1f1f1"),
    "rabbit": K("a rabbit", "🐇", "animal", "grey", ["fluffy", "fast"], found="forest", can="hop",
                creature=True, hex="#adb5bd"),
    "deer": K("a deer", "🦌", "animal", "brown", ["shy", "graceful"], found="forest", can="leap",
              creature=True, hex="#9c6644"),
    "frog": K("a frog", "🐸", "animal", "green", ["slimy", "jumpy"], found="park", can="jump", sound="ribbit",
              creature=True, hex="#55a630"),
    "duck": K("a duck", "🦆", "animal", "brown", ["waddly"], found="lake", can="swim", sound="quack",
              creature=True, hex="#bc6c25"),
    "butterfly": K("a butterfly", "🦋", "insect", "blue", ["delicate", "colourful"], found="meadow", can="fly",
                   creature=True, hex="#4cc9f0"),
    "owl": K("an owl", "🦉", "bird", "brown", ["wise", "quiet"], found="forest", can="see at night",
             sound="hoot", creature=True, hex="#7f5539"),
}

PLACES: dict[str, str] = {
    "home": "my cosy cottage with a bed, a stove, a lamp and a music box",
    "farm": "the farm by my cottage, with fields for wheat, carrots and pumpkins, a barn and a chicken coop",
    "orchard": "a grove of apple trees",
    "meadow": "a wide meadow full of flowers, butterflies and beehives",
    "forest": "a deep forest of oaks and pines, with mushrooms, berries, rabbits and deer",
    "river": "a clear river that runs from the mountains down to the lake",
    "lake": "a big blue lake with fish, ducks and smooth stones on the beach",
    "dock": "Finn's dock on the lake, the place for fishing",
    "village": "the village square with a fountain-well and a fire pit",
    "bakery": "Mira's bakery, warm and smelling of bread",
    "library": "Theo's library, full of books",
    "workshop": "Rowan's workshop and forge, where tools are made",
    "market": "Juniper's market, where things are bought and sold",
    "school": "Sage's school, where words are learned",
    "music hall": "the music hall with a piano",
    "studio": "the painting studio with an easel",
    "park": "the park with swings, benches and a frog pond",
    "shrine": "the Oracle's shrine on the hill, a quiet place to ask questions",
    "mine": "the old mine in the mountain, with ore and crystals",
    "mountains": "high grey mountains with snow on top",
    "observatory": "the observatory on the hill, with a telescope for the stars",
}

# The villagers. Each one is voiced by its own small language model (a llama.cpp server) when
# that is running; the lines here are fallbacks. likes: gifts they love. sells: what they sell.
NPCS: dict[str, dict] = {
    "Mira": dict(role="baker", home="bakery", glyph="👩‍🍳", color="#f4a261", hat="#ffffff",
                 personality="warm, motherly and cheerful; she loves feeding people and making bread puns",
                 likes=["wheat", "honey", "flower", "bouquet"], sells=["bread", "pumpkin pie"],
                 wants=["wheat", "egg", "pumpkin", "honey"],
                 lines=["Good morning! The bread is warm today.", "Bring me wheat and I can bake bread.",
                        "Bread is made from wheat. The oven makes it hot and soft."]),
    "Theo": dict(role="librarian", home="library", glyph="🧑‍🏫", color="#8ecae6", hat="#264653",
                 personality="gentle, curious and bookish; he answers questions with stories and loves new words",
                 likes=["book", "paper", "crystal", "painting"], sells=["book", "paper"],
                 wants=["paper", "book", "crystal"],
                 lines=["Books are full of words. Words carry ideas.", "Would you like to read a book?",
                        "Every day you can learn something new."]),
    "Rowan": dict(role="toolmaker and smith", home="workshop", glyph="🧑‍🔧", color="#90be6d", hat="#3a5a40",
                  personality="gruff but kind and very practical; he explains how things are made, step by step",
                  likes=["ore", "wood", "stone", "crystal"], sells=["axe", "pickaxe", "fishing rod", "bucket"],
                  wants=["wood", "ore", "stone"],
                  lines=["An axe is made of wood and stone.", "Wood comes from trees. Use an axe to chop it.",
                         "Bring me ore from the mine and I can make strong tools."]),
    "Juniper": dict(role="merchant", home="market", glyph="🧑‍💼", color="#e9c46a", hat="#9b2226",
                    personality="lively, chatty and fair; she loves trading, counting coins and curious objects",
                    likes=["crystal", "honey", "painting", "lantern"],
                    sells=["seed", "carrot seed", "pumpkin seed", "kite", "ball", "bucket", "paper"],
                    wants=["honey", "crystal", "apple", "carrot"],
                    lines=["Buying or selling today? Everything has a price!", "A coin for your thoughts?",
                           "Seeds, kites and buckets, all here at my stall."]),
    "Finn": dict(role="fisher", home="dock", glyph="🧑‍✈️", color="#4ea8de", hat="#023e8a",
                 personality="calm and patient; he talks about the lake, the weather and the fish, slowly and kindly",
                 likes=["raw fish", "bread", "grilled fish", "lantern"], sells=["fishing rod"],
                 wants=["raw fish", "bread", "wood"],
                 lines=["The fish bite best in the morning.", "Fishing teaches you to be patient.",
                        "The lake is calm today. Look at the ripples."]),
    "Sage": dict(role="teacher", home="school", glyph="🧑‍🎓", color="#b5838d", hat="#6d597a",
                 personality="patient and encouraging; she teaches words, explains meanings and praises every try",
                 likes=["book", "flower", "apple", "bouquet"], sells=[],
                 wants=["apple", "book", "flower"],
                 lines=["Every word you learn is a new key.", "Let us practise: the sun is hot, the snow is cold.",
                        "Try to say it in a whole sentence!"]),
    "Pip": dict(role="child who loves to play", home="park", glyph="🧒", color="#ff70a6", hat="#ffd670",
                personality="bubbly, silly and playful, about eight years old; loves games, races and asking 'why?'",
                likes=["ball", "kite", "honey", "berry"], sells=[],
                wants=["ball", "berry", "kite"],
                lines=["Let's play tag!", "Why is the sky blue? Do you know?", "I can run faster than the dog!"]),
}

# How to make things: (product, ingredients, station or None). A station is an entity kind.
RECIPES = [
    ("axe", ["wood", "stone"], "workbench"),
    ("chisel", ["wood", "ore"], "forge"),
    ("hammer", ["wood", "stone"], "forge"),
    ("fishing rod", ["wood", "wood"], "workbench"),
    ("pickaxe", ["wood", "ore"], "workbench"),
    ("kite", ["wood", "paper"], "workbench"),
    ("lantern", ["ore", "crystal"], "forge"),
    ("bouquet", ["flower", "flower"], None),
]
# What can be built with a hammer, and from what. Built things stay where they are built.
BUILDS = {"bench": ["wood", "wood"], "birdhouse": ["wood"], "lamp post": ["ore", "wood"],
          "fountain": ["stone", "stone", "stone"], "flower bed": ["stone", "flower"]}
SCULPT_MATERIALS = ("stone", "wood", "clay")
COOKING_STATIONS = ("fire pit", "stove")      # cooking needs a lit fire pit or a stove
BAKING_STATIONS = ("oven",)

# A few general truths beyond the world itself, so concepts reach past the valley.
GENERAL_FACTS = [
    ("sun", "is", "hot"), ("sun", "is", "bright"), ("snow", "is", "cold"), ("snow", "color", "white"),
    ("sky", "color", "blue"), ("grass", "color", "green"), ("night", "is", "dark"), ("rain", "is", "wet"),
    ("fire", "is", "hot"), ("ice", "is", "cold"), ("water", "is", "wet"), ("moon", "is", "bright"),
    ("rose", "is a", "flower"), ("banana", "is a", "fruit"), ("banana", "color", "yellow"),
    ("orange", "is a", "fruit"), ("hammer", "is a", "tool"), ("chair", "is a", "furniture"),
    ("table", "is a", "furniture"), ("horse", "can", "run"), ("car", "used for", "driving"),
    ("pen", "used for", "writing"), ("cup", "used for", "drinking"), ("spoon", "used for", "eating"),
    ("house", "made of", "bricks"), ("bread", "made of", "wheat"), ("paper", "made of", "wood"),
    ("river", "found in", "valley"), ("mountain", "is", "high"), ("ice", "made of", "water"),
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
