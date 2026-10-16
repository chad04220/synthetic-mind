"""What exists at the homestead and what is true about it.

One table serves both halves of the system: the World builds itself from it, simulates it and
describes it in words, and the Academy turns the same facts into concept drills and concept tests.
So the words the synth studies are the words for the things it meets.

Things here have physical properties the World simulates:

- thermal things warm up and cool down towards their surroundings (a lit stove, the oven, the
  fireplace, the room, the weather), and cook, boil, bake or burn when hot enough for long enough;
- fresh things (food) slowly go stale and then rot, faster in the warm, slower in the pantry;
- things left out in the rain get wet and dry by the fire or in the sun; wet logs won't burn;
- containers hold other things (the pantry, the toy chest, the basket, the pot), and vessels hold
  water (the bucket, the watering can, the kettle, the pot, a cup);
- fires burn fuel, lamps and candles give light and burn down, some things make sounds.
"""
from __future__ import annotations


def K(noun, glyph, is_a, color, props, **kw):
    return dict(noun=noun, glyph=glyph, is_a=is_a, color=color, props=props, **kw)


# kind: properties. noun = how it is named in a sentence; is_a = category; found = where it is.
# portable: can be carried. food / drink: how much it restores. hex: colour for drawing.
# thermal: has a temperature. cooks: {in: station kinds, at: degrees, secs: seconds, to: product}.
# fresh: seconds it keeps at room temperature. container: how many things it holds.
# vessel: holds water (litres). fuel: seconds of fire per piece. light: radius when lit.
KINDS: dict[str, dict] = {
    # ---- fruit, vegetables and wild food
    "apple": K("an apple", "🍎", "fruit", "red", ["sweet", "round", "crunchy"], found="orchard", used_for="eating",
               portable=True, food=25, fresh=2400, thermal=True, bakes="baked apple", hex="#d9433b"),
    "pear": K("a pear", "🍐", "fruit", "green", ["sweet", "juicy"], found="orchard", used_for="eating",
              portable=True, food=22, fresh=1800, thermal=True, hex="#a7c957"),
    "plum": K("a plum", "🟣", "fruit", "purple", ["sweet", "soft"], found="orchard", used_for="eating",
              portable=True, food=15, fresh=1200, thermal=True, hex="#7b2cbf"),
    "berries": K("some berries", "🫐", "fruit", "blue", ["small", "sweet"], found="woods", used_for="making jam",
                 portable=True, food=10, fresh=900, thermal=True, hex="#4a5bd4"),
    "mushroom": K("a mushroom", "🍄", "fungus", "brown", ["soft", "earthy"], found="woods", used_for="soup",
                  portable=True, food=-5, fresh=900, thermal=True, hex="#b5651d"),
    "carrot": K("a carrot", "🥕", "vegetable", "orange", ["crunchy", "long"], found="garden", used_for="soup",
                portable=True, food=15, fresh=3000, thermal=True, grows_from="carrot seed", hex="#f08a24"),
    "potato": K("a potato", "🥔", "vegetable", "brown", ["round", "hard"], found="garden", used_for="roasting",
                portable=True, food=-5, fresh=6000, thermal=True, bakes="roast potato", grows_from="seed potato",
                hex="#c9a66b"),
    "tomato": K("a tomato", "🍅", "vegetable", "red", ["juicy", "round"], found="greenhouse", used_for="soup",
                portable=True, food=12, fresh=1500, thermal=True, grows_from="tomato seed", hex="#e63946"),
    "pumpkin": K("a pumpkin", "🎃", "vegetable", "orange", ["big", "round", "heavy"], found="garden",
                 used_for="soup", portable=True, food=5, fresh=9000, thermal=True, grows_from="pumpkin seed",
                 hex="#ef8a17"),
    "beans": K("some beans", "🫛", "vegetable", "green", ["long", "crisp"], found="garden", used_for="soup",
               portable=True, food=10, fresh=1500, thermal=True, grows_from="bean seed", hex="#6a994e"),
    "wheat": K("some wheat", "🌾", "grain", "gold", ["dry", "tall"], found="garden", used_for="making flour",
               portable=True, grows_from="wheat seed", hex="#e9c46a"),
    "mint": K("some mint", "🌿", "herb", "green", ["fresh", "fragrant"], found="garden", used_for="making tea",
              portable=True, fresh=1500, grows_from="mint seed", hex="#52b788"),
    "flower": K("a flower", "🌼", "plant", "yellow", ["pretty", "fragrant"], found="meadow", used_for="smelling",
                portable=True, fresh=1200, hex="#ffd166"),
    "egg": K("an egg", "🥚", "food", "white", ["smooth", "fragile"], found="coop", used_for="cooking",
             portable=True, food=0, fresh=6000, thermal=True, hex="#f1ede4"),
    "honey": K("a jar of honey", "🍯", "food", "gold", ["sticky", "sweet"], found="meadow", used_for="eating",
               portable=True, food=20, hex="#f2b134"),
    "raw fish": K("a fish", "🐟", "food", "silver", ["slippery", "wet"], found="pond", used_for="cooking",
                  portable=True, food=-5, fresh=600, thermal=True, bakes="baked fish", hex="#9db4c0"),
    "flour": K("a bag of flour", "🥡", "food", "white", ["soft", "dusty"], made_of="wheat", found="pantry",
               used_for="making dough", portable=True, hex="#f5f0e6"),
    "dough": K("some dough", "🫓", "food", "white", ["soft", "sticky"], made_of="flour", used_for="baking bread",
               portable=True, fresh=1800, thermal=True, bakes="bread", hex="#eadbc8"),
    # ---- cooked food and drinks
    "bread": K("a loaf of bread", "🍞", "food", "brown", ["soft", "warm"], made_of="dough", used_for="eating",
               portable=True, food=40, fresh=3000, thermal=True, hex="#c68b4e"),
    "apple pie": K("an apple pie", "🥧", "food", "gold", ["sweet", "warm"], made_of="apple", used_for="eating",
                   portable=True, food=55, fresh=3000, thermal=True, hex="#d98e3f"),
    "baked apple": K("a baked apple", "🍎", "food", "brown", ["soft", "sweet"], made_of="apple", used_for="eating",
                     portable=True, food=35, fresh=1500, thermal=True, hex="#a44a3f"),
    "roast potato": K("a roast potato", "🥔", "food", "gold", ["crispy", "warm"], made_of="potato",
                      used_for="eating", portable=True, food=35, fresh=1500, thermal=True, hex="#d4a373"),
    "baked fish": K("a baked fish", "🍢", "food", "brown", ["warm", "tasty"], made_of="fish", used_for="eating",
                    portable=True, food=45, fresh=1200, thermal=True, hex="#a0522d"),
    "boiled egg": K("a boiled egg", "🥚", "food", "white", ["warm", "firm"], made_of="egg", used_for="eating",
                    portable=True, food=25, fresh=3000, thermal=True, hex="#fff3d6"),
    "soup": K("a bowl of soup", "🍲", "food", "orange", ["hot", "tasty"], made_of="vegetables", used_for="eating",
              portable=True, food=50, drink=15, warm=20, fresh=1800, thermal=True, hex="#e76f51"),
    "jam": K("a jar of jam", "🫙", "food", "purple", ["sweet", "sticky"], made_of="berries", used_for="eating",
             portable=True, food=20, hex="#9d4edd"),
    "tea": K("a cup of tea", "🍵", "drink", "green", ["hot", "fragrant"], made_of="mint", used_for="drinking",
             portable=True, drink=35, warm=15, thermal=True, hex="#90be6d"),
    "cup of water": K("a cup of water", "🥛", "drink", "clear", ["cold", "wet"], used_for="drinking",
                      portable=True, drink=35, thermal=True, hex="#bde0fe"),
    "burnt food": K("some burnt food", "⬛", "food", "black", ["burnt", "smoky"], used_for="the compost",
                    portable=True, food=-10, hex="#2b2b2b"),
    "rotten food": K("some rotten food", "🤢", "food", "grey", ["smelly", "mushy"], used_for="the compost",
                     portable=True, food=-25, hex="#6c757d"),
    # ---- seeds
    "carrot seed": K("some carrot seeds", "🌰", "seed", "brown", ["tiny"], found="workshop", used_for="planting",
                     portable=True, grows="carrot", hex="#a47148"),
    "seed potato": K("a seed potato", "🥔", "seed", "brown", ["small"], found="workshop", used_for="planting",
                     portable=True, grows="potato", hex="#a68a64"),
    "tomato seed": K("some tomato seeds", "🌰", "seed", "yellow", ["tiny"], found="workshop", used_for="planting",
                     portable=True, grows="tomato", hex="#d4a373"),
    "pumpkin seed": K("some pumpkin seeds", "🌰", "seed", "white", ["flat"], found="workshop", used_for="planting",
                      portable=True, grows="pumpkin", hex="#e9edc9"),
    "bean seed": K("some bean seeds", "🌰", "seed", "white", ["smooth"], found="workshop", used_for="planting",
                   portable=True, grows="beans", hex="#e6ccb2"),
    "wheat seed": K("some wheat seeds", "🌰", "seed", "gold", ["tiny"], found="workshop", used_for="planting",
                    portable=True, grows="wheat", hex="#ddb892"),
    "mint seed": K("some mint seeds", "🌰", "seed", "brown", ["tiny"], found="workshop", used_for="planting",
                   portable=True, grows="mint", hex="#b08968"),
    # ---- plants in the ground (not carried; they grow through stages)
    "plant": K("a plant", "🌱", "plant", "green", ["growing", "alive"], found="garden", used_for="growing food",
               stages=["🌱", "🌿", "🪴", "🌼", "✨"], hex="#55a630"),
    "apple tree": K("an apple tree", "🌳", "tree", "green", ["tall", "old"], found="orchard",
                    used_for="growing apples", fruit="apple", season=["summer", "autumn"], hex="#2d6a4f"),
    "pear tree": K("a pear tree", "🌳", "tree", "green", ["tall"], found="orchard", used_for="growing pears",
                   fruit="pear", season=["autumn"], hex="#40916c"),
    "plum tree": K("a plum tree", "🌳", "tree", "green", ["small"], found="orchard", used_for="growing plums",
                   fruit="plum", season=["summer"], hex="#52796f"),
    "berry bush": K("a berry bush", "🌿", "plant", "green", ["prickly"], found="woods", used_for="growing berries",
                    fruit="berries", season=["summer", "autumn"], hex="#386641"),
    # ---- vessels and containers
    "pot": K("a cooking pot", "🥘", "tool", "black", ["heavy", "iron"], found="kitchen", used_for="cooking soup",
             portable=True, container=4, vessel=2.0, thermal=True, hex="#343a40"),
    "kettle": K("a kettle", "🫖", "tool", "silver", ["shiny"], found="kitchen", used_for="boiling water",
                portable=True, vessel=1.0, thermal=True, sound_when="whistling", hex="#adb5bd"),
    "cup": K("a cup", "☕", "tool", "white", ["small"], found="kitchen", used_for="drinking", portable=True,
             vessel=0.3, thermal=True, hex="#f8f9fa"),
    "bowl": K("a bowl", "🥣", "tool", "blue", ["round"], found="kitchen", used_for="eating soup", portable=True,
              hex="#4895ef"),
    "bucket": K("a bucket", "🪣", "tool", "grey", ["empty"], found="yard", used_for="carrying water",
                portable=True, vessel=8.0, hex="#8d99ae"),
    "watering can": K("a watering can", "🚿", "tool", "green", ["light"], found="garden", used_for="watering plants",
                      portable=True, vessel=6.0, hex="#2a9d8f"),
    "basket": K("a basket", "🧺", "tool", "brown", ["woven", "light"], found="kitchen", used_for="carrying things",
                portable=True, container=6, hex="#b08968"),
    "jar": K("a jar", "🫙", "tool", "clear", ["glass"], found="kitchen", used_for="keeping jam", portable=True,
             hex="#caf0f8"),
    "pantry": K("the pantry", "🗄️", "furniture", "white", ["cool", "dark"], found="kitchen",
                used_for="keeping food fresh", container=24, cool=True, hex="#e9ecef"),
    "toy chest": K("the toy chest", "🧰", "furniture", "red", ["wooden"], found="little bedroom",
                   used_for="keeping toys", container=10, hex="#c1121f"),
    "bookshelf": K("the bookshelf", "📚", "furniture", "brown", ["tall", "full"], found="living room",
                   used_for="keeping books", container=12, hex="#7f5539"),
    "nest box": K("the nest box", "🪺", "furniture", "brown", ["straw", "cosy"], found="coop",
                  used_for="laying eggs", container=6, hex="#bc8a5f"),
    "seed tin": K("the seed tin", "🥫", "furniture", "green", ["tin"], found="workshop", used_for="keeping seeds",
                  container=16, hex="#588157"),
    # ---- fire, light and heat
    "fireplace": K("the fireplace", "🔥", "furniture", "grey", ["stone", "warm"], found="living room",
                   used_for="making the house warm", heat=60, light=6, fuel_cap=6, sound_when="crackling",
                   hex="#6c584c"),
    "stove": K("the stove", "♨️", "furniture", "black", ["iron", "hot"], found="kitchen",
               used_for="cooking", heat=200, light=2, fuel_cap=4, hex="#212529"),
    "oven": K("the oven", "🍞", "furniture", "black", ["hot", "iron"], found="kitchen", used_for="baking bread",
              heat=200, part_of="stove", container=3, hex="#343a40"),
    "lamp": K("a lamp", "🪔", "light", "gold", ["bright", "warm"], found="living room", used_for="light",
              portable=True, light=5, burn=1500, hex="#ffbe0b"),
    "candle": K("a candle", "🕯️", "light", "white", ["small", "waxy"], found="little bedroom",
                used_for="light", portable=True, light=3, burn=900, hex="#fff1d6"),
    "matches": K("a box of matches", "🧯", "tool", "red", ["small", "dry"], found="living room",
                 used_for="lighting fires", portable=True, hex="#d00000"),
    "log": K("a log", "🪵", "material", "brown", ["hard", "heavy"], found="workshop", used_for="burning",
             portable=True, fuel=420, hex="#8b5a2b"),
    "stick": K("a stick", "🥢", "material", "brown", ["thin", "light"], found="woods", used_for="making kites",
               portable=True, fuel=40, hex="#a47148"),
    "ash": K("some ash", "🩶", "material", "grey", ["soft", "dusty"], made_of="wood", used_for="the compost",
             portable=True, hex="#9a8c98"),
    "woodpile": K("the woodpile", "🪵", "furniture", "brown", ["stacked"], found="workshop",
                  used_for="keeping logs dry", container=20, hex="#7f5539"),
    "chopping block": K("the chopping block", "🪓", "furniture", "brown", ["old", "round"], found="yard",
                        used_for="chopping logs", hex="#9c6644"),
    # ---- furniture and fixtures
    "bed": K("a bed", "🛏️", "furniture", "blue", ["soft", "warm"], found="little bedroom", used_for="sleeping",
             hex="#5390d9"),
    "sink": K("the sink", "🚰", "furniture", "white", ["wet"], found="kitchen", used_for="getting water",
              water_source=True, hex="#dee2e6"),
    "table": K("the table", "🪑", "furniture", "brown", ["wooden", "big"], found="kitchen",
               used_for="eating and making dough", hex="#9c6644"),
    "sofa": K("the sofa", "🛋️", "furniture", "green", ["soft", "comfy"], found="living room", used_for="resting",
              hex="#588157"),
    "piano": K("a piano", "🎹", "instrument", "black", ["shiny", "musical"], found="living room",
               used_for="playing music", sound_when="playing", hex="#2b2d42"),
    "music box": K("a music box", "🎶", "toy", "gold", ["small", "pretty"], found="little bedroom",
                   used_for="playing a tune", portable=True, sound_when="tinkling", hex="#f4a261"),
    "mirror": K("a mirror", "🪞", "furniture", "silver", ["shiny", "smooth"], found="washroom",
                used_for="seeing yourself", hex="#ced4da"),
    "bathtub": K("the bathtub", "🛁", "furniture", "white", ["big", "smooth"], found="washroom",
                 used_for="taking a bath", hex="#e9ecef"),
    "towel": K("a towel", "🧣", "thing", "blue", ["soft", "dry"], found="washroom", used_for="drying off",
               portable=True, hex="#90e0ef"),
    "desk": K("a desk", "🗒️", "furniture", "brown", ["wooden"], found="big bedroom", used_for="writing",
              hex="#7f5539"),
    "clock": K("a clock", "🕰️", "furniture", "brown", ["ticking"], found="living room", used_for="telling the time",
               sound_when="ticking", hex="#8d6e63"),
    "rug": K("a rug", "🟫", "furniture", "red", ["soft", "woven"], found="living room", used_for="sitting on",
             hex="#9d0208"),
    "window": K("a window", "🪟", "furniture", "clear", ["glass"], found="house", used_for="looking outside",
                hex="#bde0fe"),
    "cat bowl": K("the cat bowl", "🥣", "furniture", "blue", ["small"], found="kitchen", used_for="feeding the cat",
                  container=2, hex="#4cc9f0"),
    "quern": K("the quern", "🪨", "tool", "grey", ["stone", "heavy"], found="workshop",
               used_for="grinding wheat into flour", hex="#8d8d8d"),
    "workbench": K("the workbench", "🛠️", "furniture", "brown", ["sturdy"], found="workshop",
                   used_for="making things", hex="#8d6a4a"),
    "easel": K("an easel", "🖼️", "tool", "brown", ["wooden"], found="workshop", used_for="painting", hex="#c08552"),
    "water barrel": K("the water barrel", "🛢️", "furniture", "brown", ["round", "wooden"], found="garden",
                      used_for="catching rain", vessel=60.0, hex="#7f5539"),
    "compost bin": K("the compost bin", "🗑️", "furniture", "brown", ["smelly", "warm"], found="garden",
                     used_for="making soil", container=30, hex="#6f4e37"),
    "scarecrow": K("a scarecrow", "🧑‍🌾", "thing", "brown", ["straw", "funny"], found="garden",
                   used_for="scaring birds", hex="#bc8a5f"),
    "beehive": K("the beehive", "🐝", "thing", "yellow", ["buzzing", "busy"], found="meadow", used_for="making honey",
                 sound_when="buzzing", hex="#f2b134"),
    "bird feeder": K("the bird feeder", "🏠", "thing", "brown", ["small", "hanging"], found="garden",
                     used_for="feeding birds", container=3, hex="#a47148"),
    "swing": K("a swing", "🪢", "toy", "brown", ["fun", "high"], found="orchard", used_for="swinging", hex="#9c6644"),
    "bench": K("a bench", "🪑", "furniture", "brown", ["wooden"], found="porch", used_for="sitting", hex="#8d6a4a"),
    "telescope": K("a telescope", "🔭", "tool", "silver", ["long"], found="lookout", used_for="looking at the stars",
                   hex="#adb5bd"),
    "sign": K("a sign", "🪧", "thing", "brown", ["wooden"], found="yard", used_for="reading", hex="#a47148"),
    "stepping stone": K("a stepping stone", "⚪", "thing", "grey", ["flat", "wet"], found="stream",
                        used_for="crossing the stream", hex="#adb5bd"),
    # ---- toys, books and tools
    "ball": K("a ball", "⚽", "toy", "red", ["round", "bouncy"], found="little bedroom", used_for="playing",
              portable=True, hex="#e63946"),
    "blocks": K("some wooden blocks", "🧱", "toy", "red", ["square", "wooden"], found="little bedroom",
                used_for="building towers", portable=True, hex="#e76f51"),
    "teddy": K("a teddy bear", "🧸", "toy", "brown", ["soft", "cuddly"], found="little bedroom",
               used_for="cuddling", portable=True, hex="#b5835a"),
    "kite": K("a kite", "🪁", "toy", "red", ["light", "colourful"], made_of="paper", used_for="flying",
              portable=True, hex="#ef476f"),
    "book": K("a book", "📕", "book", "red", ["full of words"], found="living room", used_for="reading",
              portable=True, hex="#c1121f"),
    "picture book": K("a picture book", "📗", "book", "green", ["colourful", "full of pictures"],
                      found="little bedroom", used_for="reading", portable=True, hex="#2d6a4f"),
    "paper": K("some paper", "📄", "material", "white", ["thin", "flat"], found="big bedroom",
               used_for="writing and painting", portable=True, hex="#fdfdfd"),
    "pencil": K("a pencil", "✏️", "tool", "yellow", ["thin", "sharp"], found="big bedroom", used_for="writing",
                portable=True, hex="#ffbe0b"),
    "axe": K("an axe", "🪓", "tool", "grey", ["sharp", "heavy"], found="workshop", used_for="chopping logs",
             portable=True, hex="#6c757d"),
    "hammer": K("a hammer", "🔨", "tool", "grey", ["heavy"], found="workshop", used_for="building", portable=True,
                hex="#8d99ae"),
    "chisel": K("a chisel", "🪛", "tool", "grey", ["sharp"], found="workshop", used_for="carving", portable=True,
                hex="#adb5bd"),
    "fishing rod": K("a fishing rod", "🎣", "tool", "brown", ["long", "thin"], found="workshop",
                     used_for="catching fish", portable=True, hex="#a47148"),
    "clay": K("some clay", "🟤", "material", "brown", ["wet", "soft"], found="pond", used_for="sculpting",
              portable=True, hex="#b5651d"),
    "stone": K("a stone", "🪨", "material", "grey", ["hard", "smooth"], found="stream", used_for="skipping",
               portable=True, hex="#8d8d8d"),
    "feather": K("a feather", "🪶", "thing", "white", ["light", "soft"], found="coop", used_for="tickling",
                 portable=True, hex="#f1faee"),
    "leaf": K("a leaf", "🍂", "plant", "orange", ["light", "crinkly"], found="woods", used_for="the compost",
              portable=True, hex="#e85d04"),
    "pinecone": K("a pinecone", "🌰", "thing", "brown", ["spiky", "dry"], found="woods", used_for="lighting fires",
                  portable=True, fuel=30, hex="#7f5539"),
    "bouquet": K("a bouquet", "💐", "gift", "colourful", ["pretty"], made_of="flowers", used_for="giving",
                 portable=True, fresh=1500, hex="#ff70a6"),
    "snowman": K("a snowman", "⛄", "thing", "white", ["cold", "round"], made_of="snow", used_for="fun",
                 hex="#ffffff"),
    # ---- what gets made
    "painting": K("a painting", "🖼️", "art", "colourful", ["beautiful"], used_for="looking at", portable=True,
                  hex="#ffafcc"),
    "recording": K("a music recording", "📼", "art", "black", ["musical"], used_for="listening", portable=True,
                   hex="#3a0ca3"),
    "sculpture": K("a sculpture", "🗿", "art", "grey", ["carved", "solid"], used_for="looking at", hex="#a8a29e"),
    "poem": K("a poem", "📜", "art", "white", ["written"], used_for="reading", portable=True, hex="#fefae0"),
    "birdhouse": K("a birdhouse", "🏠", "building", "brown", ["small", "wooden"], made_of="wood",
                   used_for="birds to live in", hex="#bc6c25"),
    # ---- animals
    "cat": K("the cat", "🐈", "animal", "grey", ["furry", "soft"], found="living room", can="purr", sound="meow",
             creature=True, name="Moss", hex="#6c757d"),
    "hen": K("a hen", "🐔", "bird", "brown", ["feathery"], found="coop", can="lay eggs", sound="cluck",
             creature=True, hex="#bc6c25"),
    "rooster": K("the rooster", "🐓", "bird", "red", ["loud", "proud"], found="coop", can="crow",
                 sound="cock-a-doodle-doo", creature=True, hex="#9d0208"),
    "bee": K("a bee", "🐝", "insect", "yellow", ["buzzing", "busy"], found="meadow", can="make honey",
             sound="buzz", creature=True, hex="#f2b134"),
    "duck": K("a duck", "🦆", "bird", "brown", ["waddly"], found="pond", can="swim", sound="quack", creature=True,
              hex="#bc6c25"),
    "frog": K("a frog", "🐸", "animal", "green", ["slimy", "jumpy"], found="pond", can="jump", sound="ribbit",
              creature=True, hex="#55a630"),
    "fish": K("a fish", "🐟", "animal", "silver", ["slippery"], found="pond", can="swim", creature=True,
              hex="#9db4c0"),
    "deer": K("a deer", "🦌", "animal", "brown", ["shy", "quick"], found="woods", can="run", creature=True,
              hex="#a0522d"),
    "robin": K("a robin", "🐦", "bird", "red", ["small", "singing"], found="garden", can="fly", sound="tweet",
               creature=True, hex="#e85d04"),
    "owl": K("an owl", "🦉", "bird", "brown", ["wise", "quiet"], found="woods", can="see at night", sound="hoot",
             creature=True, hex="#7f5539"),
    "butterfly": K("a butterfly", "🦋", "insect", "blue", ["delicate", "colourful"], found="meadow", can="fly",
                   creature=True, hex="#4cc9f0"),
    "hedgehog": K("a hedgehog", "🦔", "animal", "brown", ["spiky", "small"], found="garden", can="curl up",
                  creature=True, hex="#7f5539"),
}

STAGE_NAMES = ["a seed", "a sprout", "a young plant", "a flowering plant", "ripe"]

PLACES: dict[str, str] = {
    "living room": "the living room with the fireplace, the sofa, the bookshelf and the piano",
    "kitchen": "the kitchen with the stove and oven, the sink, the table and the pantry",
    "little bedroom": "my little bedroom with my bed, my toy chest and my music box",
    "big bedroom": "the big bedroom where my companion sleeps, with a desk",
    "washroom": "the washroom with the bathtub and a mirror",
    "porch": "the porch in front of the house, with a bench",
    "workshop": "the workshop with the workbench, the tools, the quern and the woodpile",
    "greenhouse": "the glass greenhouse, warm even in winter, where tomatoes grow",
    "garden": "the vegetable garden with beds of soil, the water barrel and the scarecrow",
    "coop": "the chicken coop where the hens lay eggs",
    "orchard": "the little orchard of apple, pear and plum trees, with a swing",
    "pond": "the pond with ducks, frogs, fish and a little jetty",
    "stream": "the stream that runs down through the woods to the pond",
    "woods": "the woods of oaks and pines, with mushrooms, berries and deer",
    "meadow": "the meadow full of flowers, with the beehive and butterflies",
    "lookout": "the lookout on the hill, with a telescope for the stars",
    "yard": "the yard around the house",
}

# What can be made (no heat): (product, ingredients, station or None). A station is an entity kind.
RECIPES = [
    ("flour", ["wheat", "wheat"], "quern"),
    ("dough", ["flour", "egg"], "table"),
    ("kite", ["paper", "stick"], "workbench"),
    ("birdhouse", ["log"], "workbench"),
    ("bouquet", ["flower", "flower"], None),
]
# What heat makes. In the pot (with water, on a lit stove): ingredients -> product.
POT_RECIPES = [
    ({"berries"}, "jam"),
    ({"egg"}, "boiled egg"),
    # anything else from the garden or the woods makes soup
]
SOUP_THINGS = {"carrot", "potato", "tomato", "pumpkin", "beans", "mushroom"}
OVEN_RECIPES = [                          # ingredients in the oven -> product
    (("dough", "apple"), "apple pie"),
    (("dough",), "bread"),
    (("apple",), "baked apple"),
    (("potato",), "roast potato"),
    (("raw fish",), "baked fish"),
]
SCULPT_MATERIALS = ("clay", "log", "stone")

# A few general truths beyond the homestead, so concepts reach past it.
GENERAL_FACTS = [
    ("sun", "is", "hot"), ("sun", "is", "bright"), ("snow", "is", "cold"), ("snow", "color", "white"),
    ("sky", "color", "blue"), ("grass", "color", "green"), ("night", "is", "dark"), ("rain", "is", "wet"),
    ("fire", "is", "hot"), ("ice", "is", "cold"), ("water", "is", "wet"), ("moon", "is", "bright"),
    ("rose", "is a", "flower"), ("banana", "is a", "fruit"), ("banana", "color", "yellow"),
    ("orange", "is a", "fruit"), ("chair", "is a", "furniture"), ("horse", "can", "run"),
    ("pen", "used for", "writing"), ("spoon", "used for", "eating"), ("ice", "made of", "water"),
    ("bread", "made of", "flour"), ("paper", "made of", "wood"), ("tea", "is", "hot"), ("soup", "is", "hot"),
    ("water", "is", "clear"), ("steam", "made of", "water"), ("ash", "made of", "wood"),
    ("winter", "is", "cold"), ("summer", "is", "warm"), ("leaf", "color", "green"),
]

# Things that happen, as cause and effect: the World makes these true, and the drills say them.
CAUSES = [
    ("fire", "makes", "the room warm"), ("rain", "makes", "things wet"), ("the sun", "makes", "plants grow"),
    ("water", "makes", "plants grow"), ("heat", "makes", "water boil"), ("the oven", "makes", "dough into bread"),
    ("cold", "makes", "water freeze"), ("frost", "makes", "plants die"), ("a lamp", "makes", "the dark bright"),
    ("food", "makes", "you strong"), ("sleep", "makes", "you rested"), ("a bath", "makes", "you clean"),
    ("hens", "make", "eggs"), ("bees", "make", "honey"), ("the quern", "makes", "wheat into flour"),
]


def companion_facts(name: str, synth: str) -> list[tuple[str, str, str]]:
    return [(name, "is a", "companion"), (name, "found in", "house"), (name, "can", "talk"),
            (name, "can", "cook"), (synth, "is a", "synth"), (synth, "can", "learn")]


def triples(companion: str = "Wren", synth: str = "Zen") -> list[tuple[str, str, str]]:
    """Every fact the homestead itself makes true, plus the general facts."""
    out = []
    for kind, k in KINDS.items():
        out.append((kind, "is a", k["is_a"]))
        out.append((kind, "color", k["color"]))
        for p in k.get("props", []):
            out.append((kind, "is", p))
        for rel, key in (("made of", "made_of"), ("used for", "used_for"), ("found in", "found"), ("can", "can")):
            if k.get(key):
                out.append((kind, rel, k[key]))
    out.extend(companion_facts(companion, synth))
    out.extend(GENERAL_FACTS)
    return out
