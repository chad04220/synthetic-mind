"""What exists in Zen's world and what is true about it.

One table serves both halves of the system: the World (``ada/world``) simulates these kinds and
names them in words, and the Academy turns the same facts into concept drills and tests. So the
words Zen studies are the words for the things it meets, and every fact here is true in the World.

Every kind of thing is here: things you can carry (food, materials, tools), objects that stay put
(furniture, a beehive, a nest), animals, the static features of the land (trees, bushes, rocks,
walls…) and the biomes themselves.

Physics keys the World reads:
- ``portable``: can be carried (hands hold up to 4 things);
- ``food``: energy restored by eating it; ``drink``: water restored; ``poison``: health lost;
- ``cooks_to``: what it becomes when cooked at a lit fire;
- ``fuel``: seconds of fire one piece gives; ``light``: light radius when lit; ``warmth``: °C added nearby;
- ``vessel``: drinks of water it holds; ``container``: things it holds;
- ``blocks``: a feature or object that stops walking;
- ``fruit`` / ``season``: what a plant gives when picked, and in which seasons;
- ``creature``: an animal; ``night``: active at night (sleeps by day).
"""
from __future__ import annotations


def K(noun, glyph, is_a, color, props, **kw):
    return dict(noun=noun, glyph=glyph, is_a=is_a, color=color, props=props, **kw)


KINDS: dict[str, dict] = {
    # ---------------------------------------------------------------- food
    "berries": K("some berries", "🫐", "fruit", "blue", ["small", "sweet"], found="berry bush", used_for="eating",
                 portable=True, food=9, hex="#4a5bd4"),
    "apple": K("an apple", "🍎", "fruit", "red", ["sweet", "round", "crunchy"], found="apple tree",
               used_for="eating", portable=True, food=13, cooks_to="baked apple", hex="#d9433b"),
    "baked apple": K("a baked apple", "🍎", "food", "brown", ["soft", "sweet", "warm"], made_of="apple",
                     used_for="eating", portable=True, food=20, hex="#a44a3f"),
    "mushroom": K("a mushroom", "🍄", "fungus", "brown", ["soft", "earthy"], found="forest", used_for="eating",
                  portable=True, food=6, cooks_to="roast mushroom", hex="#b5651d"),
    "roast mushroom": K("a roast mushroom", "🍄", "food", "brown", ["warm", "tasty"], made_of="mushroom",
                        used_for="eating", portable=True, food=14, hex="#8b4513"),
    "toadstool": K("a red toadstool", "🍄", "fungus", "red", ["spotted", "poisonous"], found="forest",
                   used_for="nothing", portable=True, food=2, poison=14, hex="#d62828"),
    "coconut": K("a coconut", "🥥", "fruit", "brown", ["hard", "hairy"], found="palm", used_for="eating",
                 portable=True, food=16, drink=8, hex="#7f5539"),
    "banana": K("a banana", "🍌", "fruit", "yellow", ["soft", "sweet", "long"], found="jungle", used_for="eating",
                portable=True, food=15, hex="#f4d35e"),
    "cactus fruit": K("a cactus fruit", "🍐", "fruit", "pink", ["juicy", "prickly"], found="cactus",
                      used_for="eating", portable=True, food=8, drink=6, hex="#e56b6f"),
    "egg": K("an egg", "🥚", "food", "white", ["smooth", "fragile"], found="nest", used_for="cooking",
             portable=True, food=5, cooks_to="cooked egg", hex="#f1ede4"),
    "cooked egg": K("a cooked egg", "🍳", "food", "white", ["warm", "firm"], made_of="egg", used_for="eating",
                    portable=True, food=16, hex="#fff3d6"),
    "honey": K("some honey", "🍯", "food", "gold", ["sticky", "sweet"], found="beehive", used_for="eating",
               portable=True, food=16, hex="#f2b134"),
    "raw fish": K("a raw fish", "🐟", "food", "silver", ["slippery", "wet"], found="lake", used_for="cooking",
                  portable=True, food=5, cooks_to="cooked fish", hex="#9db4c0"),
    "cooked fish": K("a cooked fish", "🍢", "food", "brown", ["warm", "tasty"], made_of="fish", used_for="eating",
                     portable=True, food=30, hex="#a0522d"),
    # ---------------------------------------------------------------- materials
    "stick": K("a stick", "🥢", "wood", "brown", ["thin", "dry"], found="forest", used_for="making fire",
               portable=True, fuel=60, hex="#8d6e4a"),
    "log": K("a log", "🪵", "wood", "brown", ["heavy", "round"], made_of="wood", found="woodpile",
             used_for="making fire", portable=True, fuel=240, hex="#7f5539"),
    "pinecone": K("a pinecone", "🌰", "seed", "brown", ["dry", "scaly"], found="pine forest",
                  used_for="making fire", portable=True, fuel=30, hex="#8c5e3c"),
    "stone": K("a stone", "🪨", "stone", "grey", ["hard", "heavy"], found="mountain", used_for="building",
               portable=True, hex="#8d8d8d"),
    "flint": K("a flint", "🔥", "stone", "black", ["hard", "sharp"], found="rocky land", used_for="lighting fires",
               portable=True, hex="#3a3a3a"),
    "clay": K("a lump of clay", "🟤", "earth", "brown", ["soft", "wet"], found="river", used_for="sculpting",
              portable=True, hex="#c2703d"),
    "feather": K("a feather", "🪶", "thing", "white", ["light", "soft"], found="meadow", used_for="writing",
                 portable=True, hex="#f0efeb"),
    "shell": K("a shell", "🐚", "thing", "white", ["smooth", "curly"], found="beach", used_for="decoration",
               portable=True, hex="#f6e7d8"),
    "flower": K("a flower", "🌼", "plant", "yellow", ["pretty", "fragrant"], found="meadow", used_for="smelling",
                portable=True, hex="#ffd166"),
    "crystal": K("a crystal", "💎", "stone", "purple", ["shiny", "clear"], found="cave", used_for="decoration",
                 portable=True, hex="#b39ddb"),
    "bone": K("a bone", "🦴", "thing", "white", ["dry", "hard"], found="desert", used_for="nothing",
              portable=True, hex="#efe6d2"),
    "paper": K("a sheet of paper", "📄", "thing", "white", ["thin", "flat"], made_of="wood", found="cabin",
               used_for="painting", portable=True, hex="#fbf8ef"),
    # ---------------------------------------------------------------- tools
    "book": K("a book", "📖", "thing", "brown", ["old", "full of words"], found="bookshelf", used_for="reading",
              portable=True, hex="#8c5a3c"),
    "cup": K("a cup", "☕", "tool", "white", ["small"], found="chest", used_for="drinking", portable=True,
             vessel=1, hex="#f8f9fa"),
    "bucket": K("a bucket", "🪣", "tool", "grey", ["round"], found="cabin", used_for="carrying water",
                portable=True, vessel=4, hex="#8d99ae"),
    "axe": K("an axe", "🪓", "tool", "grey", ["sharp", "heavy"], found="cabin", used_for="chopping trees",
             portable=True, hex="#6c757d"),
    "lantern": K("a lantern", "🏮", "tool", "gold", ["bright"], found="chest", used_for="seeing in the dark",
                 portable=True, light=4, fuel=900, hex="#e9c46a"),
    # ---------------------------------------------------------------- objects that stay put
    "bed": K("my bed", "🛏️", "furniture", "blue", ["soft", "warm"], found="cabin", used_for="sleeping",
             hex="#5c7aa6"),
    "fireplace": K("the fireplace", "🔥", "furniture", "grey", ["stone", "warm when lit"], found="cabin",
                   used_for="making fire", blocks=True, light=5, warmth=12, hex="#6b4f3a"),
    "campfire": K("a campfire", "🔥", "fire", "orange", ["hot", "bright"], made_of="wood", used_for="keeping warm",
                  blocks=True, light=4, warmth=10, hex="#f77f00"),
    "woodpile": K("the woodpile", "🪵", "furniture", "brown", ["stacked"], found="cabin", used_for="keeping logs",
                  blocks=True, hex="#7f5539"),
    "table": K("the table", "🪑", "furniture", "brown", ["wooden", "flat"], found="cabin",
               used_for="putting things on", blocks=True, hex="#9c6644"),
    "bookshelf": K("the bookshelf", "📚", "furniture", "brown", ["tall", "full of books"], found="cabin",
                   used_for="keeping books", blocks=True, container=12, hex="#6f4e37"),
    "easel": K("the easel", "🎨", "furniture", "brown", ["wooden", "tall"], found="cabin", used_for="painting",
               blocks=True, hex="#b08968"),
    "piano": K("the piano", "🎹", "instrument", "black", ["big", "musical"], found="cabin",
               used_for="making music", blocks=True, hex="#22223b"),
    "desk": K("the desk", "✍️", "furniture", "brown", ["wooden", "flat"], found="cabin", used_for="writing",
              blocks=True, hex="#8b5e34"),
    "chest": K("a chest", "🧰", "furniture", "brown", ["wooden", "heavy"], found="cabin", used_for="keeping things",
               blocks=True, container=8, hex="#9c6644"),
    "beehive": K("a beehive", "🐝", "home", "gold", ["humming", "busy"], found="meadow", used_for="making honey",
                 blocks=True, hex="#e9c46a"),
    "nest": K("a bird's nest", "🪺", "home", "brown", ["round", "woven"], found="forest", used_for="keeping eggs",
              hex="#a47148"),
    # ---------------------------------------------------------------- animals
    "deer": K("a deer", "🦌", "animal", "brown", ["shy", "fast"], found="forest", can="run", creature=True,
              hex="#a0522d"),
    "rabbit": K("a rabbit", "🐇", "animal", "grey", ["small", "quick"], found="meadow", can="hop", creature=True,
                hex="#b7b7a4"),
    "fox": K("a fox", "🦊", "animal", "orange", ["clever", "quiet"], found="forest", can="hunt", creature=True,
             hex="#e76f51"),
    "bird": K("a bird", "🐦", "animal", "brown", ["small", "noisy"], found="forest", can="fly", creature=True,
              hex="#bc6c25"),
    "fish": K("a fish", "🐟", "animal", "silver", ["slippery"], found="lake", can="swim", creature=True,
              hex="#9db4c0"),
    "frog": K("a frog", "🐸", "animal", "green", ["small", "wet"], found="swamp", can="jump", creature=True,
              night=True, hex="#55a630"),
    "owl": K("an owl", "🦉", "bird", "brown", ["wise", "silent"], found="forest", can="see in the dark",
             creature=True, night=True, hex="#7f5539"),
    "fireflies": K("some fireflies", "✨", "insect", "yellow", ["glowing", "tiny"], found="meadow", can="glow",
                   creature=True, night=True, hex="#f9f871"),
    "bees": K("some bees", "🐝", "insect", "yellow", ["buzzing", "busy"], found="beehive", can="sting",
              creature=True, hex="#f2b134"),
    "bear": K("a bear", "🐻", "animal", "brown", ["big", "strong", "dangerous"], found="pine forest",
              can="swipe", creature=True, hex="#5e3a1d"),
    "lizard": K("a lizard", "🦎", "animal", "green", ["small", "quick"], found="desert", can="climb",
                creature=True, hex="#90a955"),
    "goat": K("a goat", "🐐", "animal", "white", ["sure-footed", "hairy"], found="mountain", can="climb",
              creature=True, hex="#e9e3d5"),
    # ---------------------------------------------------------------- features of the land
    "oak": K("an oak tree", "🌳", "tree", "green", ["tall", "strong"], found="forest", used_for="wood",
             blocks=True, tree=True, hex="#2d6a4f"),
    "birch": K("a birch tree", "🌳", "tree", "white", ["slim", "white-barked"], found="forest", used_for="wood",
               blocks=True, tree=True, hex="#95d5b2"),
    "pine": K("a pine tree", "🌲", "tree", "green", ["tall", "evergreen"], found="pine forest", used_for="wood",
              blocks=True, tree=True, hex="#1b4332"),
    "palm": K("a palm tree", "🌴", "tree", "green", ["tall", "slender"], found="beach", used_for="growing coconuts",
              blocks=True, tree=True, fruit="coconut", season=["spring", "summer", "autumn", "winter"],
              hex="#52b788"),
    "jungle tree": K("a jungle tree", "🌳", "tree", "green", ["huge", "leafy"], found="jungle",
                     used_for="growing bananas", blocks=True, tree=True, fruit="banana",
                     season=["spring", "summer", "autumn", "winter"], hex="#2b9348"),
    "dead tree": K("a dead tree", "🪾", "tree", "grey", ["bare", "dry"], found="swamp", used_for="wood",
                   blocks=True, tree=True, hex="#6c584c"),
    "apple tree": K("an apple tree", "🌳", "tree", "green", ["leafy", "old"], found="meadow",
                    used_for="growing apples", blocks=True, tree=True, fruit="apple", season=["summer", "autumn"],
                    hex="#40916c"),
    "acacia": K("an acacia tree", "🌳", "tree", "green", ["flat-topped", "thorny"], found="savanna",
                used_for="shade", blocks=True, tree=True, hex="#6a994e"),
    "stump": K("a tree stump", "🪵", "wood", "brown", ["low", "round"], made_of="wood", found="forest",
               used_for="sitting", hex="#8d6e4a"),
    "berry bush": K("a berry bush", "🌿", "plant", "green", ["leafy", "low"], found="meadow",
                    used_for="growing berries", blocks=True, fruit="berries", season=["summer", "autumn"],
                    hex="#386641"),
    "bush": K("a bush", "🌿", "plant", "green", ["leafy", "low"], found="forest", used_for="shelter for birds",
              blocks=True, hex="#4f772d"),
    "cactus": K("a cactus", "🌵", "plant", "green", ["prickly", "tough"], found="desert", used_for="storing water",
                blocks=True, fruit="cactus fruit", season=["summer"], hex="#588157"),
    "rock": K("a rock", "🪨", "stone", "grey", ["hard", "big"], found="mountain", used_for="climbing",
              blocks=True, hex="#8d8d8d"),
    "boulder": K("a boulder", "🪨", "stone", "grey", ["huge", "heavy"], found="mountain", used_for="nothing",
                 blocks=True, hex="#6c757d"),
    "tall grass": K("tall grass", "🌾", "plant", "green", ["tall", "soft"], found="grassland", used_for="hiding",
                    hex="#90be6d"),
    "flowers": K("flowers", "🌸", "plant", "pink", ["pretty", "fragrant"], found="meadow", used_for="bees",
                 fruit="flower", season=["spring", "summer"], hex="#f7a1c4"),
    "reeds": K("reeds", "🌾", "plant", "green", ["tall", "thin"], found="lake", used_for="weaving", hex="#a3b18a"),
    "fern": K("a fern", "🌿", "plant", "green", ["feathery", "soft"], found="forest", used_for="nothing",
              hex="#2a9d8f"),
    "snow drift": K("a snow drift", "❄️", "snow", "white", ["deep", "cold"], found="tundra", used_for="nothing",
                    hex="#f1f5f9"),
    "wall": K("a wall", "🧱", "building part", "brown", ["wooden", "solid"], found="cabin",
              used_for="keeping out the cold", blocks=True, hex="#6f4e37"),
    "door": K("the door", "🚪", "building part", "brown", ["wooden"], found="cabin", used_for="going in and out",
              hex="#8b5e34"),
    "floor": K("the floor", "🟫", "building part", "brown", ["wooden", "dry"], found="cabin", used_for="walking",
               hex="#b08968"),
    "stone wall": K("a stone wall", "🧱", "building part", "grey", ["old", "mossy"], found="ruins",
                    used_for="nothing now", blocks=True, hex="#8d8d8d"),
    "rubble": K("rubble", "🪨", "stone", "grey", ["broken", "loose"], found="ruins", used_for="nothing",
                hex="#a5a58d"),
    "cave wall": K("the cave wall", "🪨", "stone", "grey", ["cold", "damp"], found="cave", used_for="nothing",
                   blocks=True, hex="#495057"),
    "cave floor": K("the cave floor", "⬛", "stone", "grey", ["dark", "dry"], found="cave", used_for="shelter",
                    hex="#343a40"),
    "standing stone": K("a standing stone", "🗿", "stone", "grey", ["tall", "ancient", "carved"], found="stones",
                        used_for="remembering", blocks=True, hex="#7d8597"),
    "well": K("an old well", "🪣", "water", "grey", ["deep", "round"], found="meadow", used_for="drinking",
              blocks=True, hex="#6c757d"),
    "cairn": K("a cairn", "🗻", "stone", "grey", ["piled", "high"], found="hill", used_for="looking far",
               blocks=True, hex="#8d8d8d"),
    "spring": K("a spring", "💧", "water", "clear", ["fresh", "cold", "bubbling"], found="hills",
                used_for="drinking", hex="#90e0ef"),
    "river": K("a stream", "🌊", "water", "blue", ["flowing", "fresh"], found="valley", used_for="drinking",
               hex="#4ea8de"),
    # ---------------------------------------------------------------- places
    "cabin": K("a cabin", "🏠", "building", "brown", ["small", "wooden", "dry inside"], found="meadow",
               used_for="shelter", hex="#9c6644"),
    "ruins": K("ruins", "🏚️", "place", "grey", ["old", "broken"], found="wild", used_for="exploring",
               hex="#8d8d8d"),
    "cave": K("a cave", "🕳️", "place", "grey", ["dark", "dry", "cool"], found="mountain", used_for="shelter",
              hex="#343a40"),
    "stones": K("a stone circle", "🗿", "place", "grey", ["ancient", "quiet"], found="meadow",
                used_for="remembering", hex="#7d8597"),
    "lookout": K("a lookout hill", "⛰️", "place", "green", ["high", "windy"], found="wild", used_for="looking far",
                 hex="#6a994e"),
    # ---------------------------------------------------------------- biomes
    "sea": K("the sea", "🌊", "water", "blue", ["salty", "deep", "wide"], found="coast", used_for="fish",
             hex="#1d4e89"),
    "lake": K("a lake", "💧", "water", "blue", ["fresh", "still"], found="valley", used_for="drinking",
              hex="#3a86ff"),
    "beach": K("a beach", "🏖️", "land", "yellow", ["sandy", "sunny"], found="coast", used_for="finding shells",
               hex="#e9d8a6"),
    "meadow": K("a meadow", "🌼", "land", "green", ["grassy", "flowery"], found="lowland", used_for="walking",
                hex="#95d5b2"),
    "grassland": K("grassland", "🌾", "land", "green", ["open", "grassy"], found="plain", used_for="grazing",
                   hex="#a7c957"),
    "forest": K("a forest", "🌳", "land", "green", ["shady", "leafy"], found="lowland", used_for="wood",
                hex="#2d6a4f"),
    "pine forest": K("a pine forest", "🌲", "land", "green", ["dark", "cool"], found="hills", used_for="wood",
                     hex="#1b4332"),
    "jungle": K("a jungle", "🌴", "land", "green", ["hot", "wet", "thick"], found="tropics", used_for="bananas",
                hex="#007f5f"),
    "swamp": K("a swamp", "🪷", "land", "brown", ["wet", "muddy"], found="lowland", used_for="frogs",
               hex="#606c38"),
    "desert": K("a desert", "🏜️", "land", "yellow", ["hot", "dry", "sandy"], found="tropics",
                used_for="nothing much", hex="#e9c46a"),
    "savanna": K("a savanna", "🌾", "land", "yellow", ["hot", "grassy"], found="tropics", used_for="grazing",
                 hex="#d4a373"),
    "tundra": K("tundra", "🧊", "land", "grey", ["cold", "bare"], found="north", used_for="nothing much",
                hex="#adb5bd"),
    "snowfield": K("a snowfield", "🏔️", "land", "white", ["cold", "white"], found="mountain", used_for="nothing much",
                   hex="#f1f5f9"),
    "mountain": K("a mountain", "⛰️", "land", "grey", ["high", "steep"], found="highlands", used_for="climbing",
                  hex="#6c757d"),
    "rocky land": K("rocky land", "🪨", "land", "grey", ["stony", "bare"], found="highlands", used_for="flint",
                    hex="#8d8d8d"),
}

# terrain names -> kind keys
BIOME_KIND = {"ocean": "sea", "lake": "lake", "beach": "beach", "meadow": "meadow", "grassland": "grassland",
              "forest": "forest", "pine_forest": "pine forest", "jungle": "jungle", "swamp": "swamp",
              "desert": "desert", "savanna": "savanna", "tundra": "tundra", "snow": "snowfield",
              "mountain": "mountain", "rock": "rocky land"}
FEATURE_KIND = {f: f.replace("_", " ") for f in (
    "oak", "birch", "pine", "palm", "cactus", "jungle_tree", "dead_tree", "apple_tree", "acacia", "stump",
    "berry_bush", "bush", "rock", "boulder", "tall_grass", "flowers", "reeds", "fern", "snow_drift", "wall", "door",
    "floor", "stone_wall", "rubble", "cave_wall", "cave_floor", "standing_stone", "well", "cairn", "spring")}

# A few general truths beyond the World, so concepts reach past it.
GENERAL_FACTS = [
    ("sun", "is", "hot"), ("sun", "is", "bright"), ("snow", "is", "cold"), ("snow", "color", "white"),
    ("sky", "color", "blue"), ("grass", "color", "green"), ("night", "is", "dark"), ("rain", "is", "wet"),
    ("fire", "is", "hot"), ("ice", "is", "cold"), ("water", "is", "wet"), ("moon", "is", "bright"),
    ("ice", "made of", "water"), ("paper", "made of", "wood"), ("ash", "made of", "wood"),
    ("winter", "is", "cold"), ("summer", "is", "warm"), ("leaf", "color", "green"), ("sea", "is", "salty"),
    ("fire", "used for", "keeping warm"), ("fire", "used for", "cooking"), ("roof", "used for", "keeping dry"),
    ("bee", "can", "make honey"), ("bird", "can", "build a nest"), ("fish", "can", "swim"),
]

# Things that happen, as cause and effect: the World makes these true.
CAUSES = [
    ("fire", "makes", "the room warm"), ("fire", "makes", "the dark bright"), ("rain", "makes", "things wet"),
    ("rain", "makes", "mushrooms grow"), ("cold", "makes", "you weak"), ("food", "makes", "you strong"),
    ("sleep", "makes", "you rested"), ("bees", "make", "honey"), ("an axe", "makes", "a tree into logs"),
    ("flint", "makes", "a spark"), ("sea water", "makes", "you thirsty"), ("a toadstool", "makes", "you sick"),
]


def triples(synth: str = "Zen") -> list[tuple[str, str, str]]:
    """Every fact the World itself makes true, plus the general facts."""
    out = []
    for kind, k in KINDS.items():
        out.append((kind, "is a", k["is_a"]))
        out.append((kind, "color", k["color"]))
        for p in k.get("props", []):
            out.append((kind, "is", p))
        for rel, key in (("made of", "made_of"), ("used for", "used_for"), ("found in", "found"), ("can", "can")):
            if k.get(key) and k[key] not in ("nothing", "nothing much", "nothing now"):
                out.append((kind, rel, k[key]))
        if k.get("fruit"):
            out.append((kind, "can", f"give {KINDS[k['fruit']]['noun'].split(' ', 1)[-1]}"))
    out += [(synth, "is a", "synth"), (synth, "can", "learn"), (synth, "found in", "cabin"),
            ("Sprite", "is a", "spirit"), ("Sprite", "can", "answer questions"), ("Sprite", "is", "glowing")]
    out.extend(GENERAL_FACTS)
    return out
