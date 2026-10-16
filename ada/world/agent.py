"""How minds act at the homestead: words become deeds.

Each time the synth is free to choose, its brain writes an intention ("I eat the apple.", "I put
a log in the fireplace.", "I ask Wren why it rains."). `parse()` turns it into a Goal (a verb and
its object); if the world can make sense of it, the synth carries it out, and its own words have
moved its body. Its companion uses the same verbs and the same planner.

Goals can need other things first. To cook soup you need water in the pot, a vegetable in it, the
pot on the stove and the stove lit, which needs a dry log in it and the matches. `plan()` finds the
first missing step and plans that, keeping the rest for after (`Plan.then`), so a goal unfolds into
a sequence of small deeds, each with its own sentence ("I take the pot.", "I fill the pot at the
sink.", ...). Those sentences, next to what was sensed and how it turned out, are what the synth
studies; that is how it learns how things are done.

While its words can't yet steer it, its needs decide (`drives()`), with a reason ("I am hungry.").
Early on it does what a small child does and goes to its companion; as its language grows it
looks after itself.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

from ..ontology import KINDS, PLACES, RECIPES, SCULPT_MATERIALS, SOUP_THINGS
from . import art
from .sim import DOCK, SOIL, TREE, WATER, PINE, Being, World, _and, _cap, _facing, kind_of, where

VERBS = {
    "eat": ["eat", "eats", "ate", "eating", "taste", "munch", "bite"],
    "drink": ["drink", "drinks", "sip", "drinking"],
    "go": ["go", "goes", "walk", "run", "visit", "head", "return", "come", "move", "enter"],
    "take": ["take", "pick", "grab", "get", "collect", "gather", "fetch", "find", "carry"],
    "put": ["put", "place", "add", "store", "set"],
    "drop": ["drop", "leave"],
    "give": ["give", "hand", "offer", "share", "bring"],
    "feed": ["feed"],
    "talk": ["talk", "speak", "chat", "greet", "say", "tell", "call"],
    "ask": ["ask", "question", "wonder"],
    "read": ["read"],
    "play": ["play", "kick", "throw", "bounce", "dance", "swing"],
    "pet": ["pet", "stroke", "cuddle", "tickle"],
    "hug": ["hug", "hold"],
    "smell": ["smell", "sniff"],
    "plant": ["plant", "sow"],
    "water": ["water"],
    "fill": ["fill"],
    "harvest": ["harvest", "dig", "reap"],
    "chop": ["chop", "cut", "split"],
    "make": ["make", "craft", "create", "grind", "mix"],
    "build": ["build", "construct"],
    "light": ["light", "kindle", "start"],
    "cook": ["cook", "stew", "boil"],
    "bake": ["bake", "roast"],
    "brew": ["brew", "tea"],
    "look": ["look", "watch", "gaze", "observe", "see", "stargaze"],
    "listen": ["listen", "hear"],
    "sleep": ["sleep", "nap", "bed"],
    "rest": ["rest", "sit", "relax", "wait", "stay"],
    "wash": ["wash", "bath", "bathe", "clean", "scrub"],
    "dry": ["dry", "towel"],
    "warm": ["warm"],
    "explore": ["explore", "wander", "roam", "discover", "climb"],
    "fish": ["fish", "fishing", "catch"],
    "swim": ["swim", "swimming", "paddle"],
    "paint": ["paint", "painting", "draw"],
    "compose": ["compose", "record", "sing", "song", "melody"],
    "sculpt": ["sculpt", "carve", "sculpture", "mould", "mold"],
    "write": ["write", "poem", "story"],
    "fly": ["fly", "flying"],
    "follow": ["follow"],
    "show": ["show", "point"],
}
_VERB_OF = {}
for _v, _ws in VERBS.items():
    for _w in _ws:
        _VERB_OF.setdefault(_w, _v)
_OBJECTS = sorted(list(KINDS) + ["water", "fire", "stars", "sky", "friend", "you", "wood", "seeds", "seed",
                                 "plants", "garden", "eggs", "logs", "moss", "hens", "chickens", "birds", "food"],
                  key=len, reverse=True)
ALIASES = {"wood": "log", "logs": "log", "eggs": "egg", "seeds": "seed", "moss": "cat", "chickens": "hen",
           "hens": "hen", "birds": "robin", "plants": "plant", "fire": "fireplace", "chicken": "hen",
           "water bucket": "bucket", "tea cup": "cup", "bird": "robin", "kitty": "cat"}
HANDS = 4                                    # how many things a mind can carry
FOOD_ORDER = ["soup", "bread", "apple pie", "baked fish", "roast potato", "boiled egg", "baked apple", "apple",
              "pear", "plum", "carrot", "honey", "jam", "berries", "tomato", "beans"]


@dataclass
class Goal:
    verb: str
    obj: str = ""
    extra: str = ""          # where to (put), who to (give, talk, ask), the question (ask), where from (take)
    text: str = ""           # the intention as a sentence
    reason: str = ""         # why (for choices its needs made)
    source: str = "self"     # self: its own words | needs | you | companion (for the companion's own)


@dataclass
class Plan:
    goal: Goal
    target: tuple | None = None    # ("entity", id) | ("tile", (x, y), adjacent) | ("being", name) | None
    route: list = field(default_factory=list)
    ticks: int = 0
    perception: str = ""
    wellbeing_before: float = 0.0
    then: list = field(default_factory=list)      # goals waiting for this step to be done
    working: int = 0                               # ticks spent doing it once there
    depth: int = 0


# ====================================================================== words -> goals
def _norm(o: str) -> str:
    return ALIASES.get(o, o)


def _find_obj(rest: str, names: dict[str, str]) -> str:
    for name, real in names.items():
        if re.search(rf"\b{re.escape(name)}\b", rest):
            return real
    for o in _OBJECTS:
        if re.search(rf"\b{re.escape(o)}(?:s|es)?\b", rest):
            return _norm(o)
    for p in sorted(PLACES, key=len, reverse=True):
        if re.search(rf"\b{p}\b", rest):
            return p
    return ""


def parse(text: str, names: dict[str, str] | None = None) -> Goal | None:
    """Understand an intention, if it can be understood. `names` maps lower-case names to beings."""
    names = names or {}
    t = re.sub(r"[^a-z' ]+", " ", text.lower().strip())
    words = t.split()
    if not words:
        return None
    verbs = [(i, _VERB_OF[w]) for i, w in enumerate(words) if w in _VERB_OF]
    if not verbs:
        return None
    i, verb = verbs[0]
    if verb in ("go", "talk", "take") and len(verbs) > 1 and verbs[1][1] not in ("go", "take") \
            and not (verb == "take" and verbs[1][1] in ("put", "give")):
        if verb != "talk" or verbs[1][1] in ("ask",):
            i, verb = verbs[1]                    # "go and eat the apple", "go fishing"
    rest = " ".join(words[i + 1:])
    w0 = words[i]
    if verb == "water" and i > 0 and words[i - 1] in ("the", "some", "of", "cold", "warm", "drink"):
        verb = "drink"
    if verb == "fish" and w0 == "fish" and i > 0 and words[i - 1] in ("the", "a", "my", "some"):
        verb = "take"
    if verb == "brew" and w0 == "tea" and i > 0 and words[i - 1] in ("the", "a", "of", "some", "drink", "cup"):
        verb = "drink"
    if verb == "sleep" and w0 == "bed" and i > 0 and words[i - 1] not in ("to",):
        return None if not any(v == "sleep" for _, v in verbs[1:]) else Goal("sleep", "bed", text=text.strip())
    if verb == "hug" and w0 == "hold" and not any(n in rest for n in names):
        verb = "take"
    obj = _find_obj(rest, names)
    if obj == "you":
        obj = "friend"
    extra = ""
    m = re.search(r"\b(?:in|into|on|onto|inside)\s+(?:the\s+|my\s+|a\s+)?(.+)$", rest)
    if verb in ("put", "drop", "take", "give", "feed", "show") and m:
        dest = _find_obj(m.group(1), names)
        obj = _find_obj(rest[:m.start()], names) or obj
        if dest and dest != obj:
            extra = dest
            if verb == "drop":
                verb = "put"
    m2 = re.search(r"\b(?:from|out of)\s+(?:the\s+|my\s+)?(.+)$", rest)
    if verb == "take" and m2:
        src = _find_obj(m2.group(1), names)
        obj = _find_obj(rest[:m2.start()], names) or obj
        extra = src if src != obj else ""
    if verb in ("give", "show"):        # "give the apple to Wren": the thing, then who receives it
        item = next((_norm(o) for o in _OBJECTS if _norm(o) in KINDS and re.search(rf"\b{re.escape(o)}s?\b", rest)), "")
        who = next((real for name, real in names.items() if re.search(rf"\b{re.escape(name)}\b", rest)), "")
        who = who or ("friend" if re.search(r"\b(friend|you)\b", rest) else "")
        return Goal(verb, item, who, text.strip())
    if verb == "feed":
        who = next((real for name, real in names.items() if re.search(rf"\b{re.escape(name)}\b", rest)), "")
        target = who or ("cat" if re.search(r"\b(cat|moss|kitty)\b", rest) else
                         "hen" if re.search(r"\b(hen|hens|chicken|chickens)\b", rest) else
                         "robin" if re.search(r"\bbird", rest) else obj)
        food = next((_norm(o) for o in _OBJECTS if _norm(o) in KINDS and kind_of({"kind": _norm(o)}).get("is_a") in
                     ("fruit", "food", "vegetable", "grain", "seed") and re.search(rf"\b{re.escape(o)}s?\b", rest)), "")
        return Goal("feed", target, food, text.strip())
    if verb == "ask":
        who = next((real for name, real in names.items() if re.search(rf"\b{re.escape(name)}\b", rest)), "")
        q = re.sub(rf"^.*?\b(?:{'|'.join(map(re.escape, names)) or 'xyz'})\b\s*", "", rest) if who else rest
        return Goal("ask", who, q.strip(), text.strip())
    if verb == "play" and w0 == "swing":
        obj = "swing"
    if verb == "make" and w0 in ("grind",):
        obj = "flour"
    if verb == "make" and obj in ("", "tea") and "tea" in rest:
        verb, obj = "brew", "tea"
    if verb == "make" and obj == "soup":
        verb = "cook"
    if verb == "make" and obj in ("bread", "apple pie"):
        verb = "bake"
    if verb == "make" and "snowman" in rest:
        verb, obj = "build", "snowman"
    if verb == "cook" and w0 == "boil" and obj in ("water", "kettle", ""):
        verb, obj = "brew", "water"
    if verb == "fly" and not obj:
        obj = "kite"
    if verb == "look" and obj in ("stars", "sky") or verb == "look" and w0 == "stargaze":
        obj = "telescope"
    if verb == "brew":
        obj = obj if obj in ("water",) else "tea"
    if verb == "wash" and obj in ("", "bathtub"):
        obj = "bathtub"
    if verb == "light" and obj == "":
        obj = "fireplace"
    return Goal(verb, obj, extra, text.strip())


def say(goal: Goal, companion: str = "Wren") -> str:
    """The canonical sentence for a goal: what a mind learns to say before it does it."""
    v, o, x = goal.verb, goal.obj, goal.extra
    the = _the(o)
    who = (lambda n: "my friend" if n in ("friend", "") else n)
    return {
        "eat": f"I eat {the}.", "drink": "I drink some water." if o in ("", "water", "sink") else f"I drink {the}.",
        "go": f"I go to {o if o and o[0].isupper() else ('my friend' if o == 'friend' else 'the ' + o)}.",
        "take": f"I take {the}" + (f" from {_the(x)}." if x else "."),
        "put": f"I put {the} {'on' if x == 'stove' and o in ('pot', 'kettle') else 'in'} {_the(x)}.",
        "drop": f"I put down {the}.",
        "give": f"I give {the} to {who(x)}.", "show": f"I show {the} to {who(x)}.",
        "feed": f"I feed {o if o and o[0].isupper() else _the(o)}" + (f" {_a(x)}." if x and x in KINDS else "."),
        "talk": f"I talk to {who(o)}.",
        "ask": f"I ask {o or companion}" + (f" {x.rstrip('?')}?" if x else " a question."),
        "read": f"I read {the}.",
        "play": {"piano": "I play the piano.", "music box": "I play the music box.", "swing": "I play on the swing.",
                 "ball": "I play with the ball."}.get(o, f"I play with {the}." if o else "I play."),
        "pet": f"I pet {the}.", "hug": f"I hug {o if o and o[0].isupper() else the}.", "smell": f"I smell {the}.",
        "plant": f"I plant {_a(o) if o in KINDS else 'some seeds'} in the garden.",
        "water": "I water the plants.", "fill": f"I fill {the} with water.",
        "harvest": f"I harvest the {o}." if o else "I harvest the vegetables.",
        "chop": "I chop wood in the woods.", "make": f"I make {_a(o)}.",
        "light": f"I light {the}.", "cook": f"I cook {'soup' if o in ('', 'soup') else the}.",
        "bake": f"I bake {_a(o) if o else 'bread'} in the oven.",
        "brew": "I make a cup of tea." if o == "tea" else "I boil water in the kettle.",
        "look": {"telescope": "I look at the stars through the telescope.", "mirror": "I look in the mirror.",
                 "window": "I look out of the window."}.get(o, f"I look at {the}." if o else "I look around."),
        "listen": f"I listen to {the}." if o else "I listen.",
        "sleep": "I go to bed and sleep.", "rest": "I rest for a while.",
        "wash": "I take a bath.", "dry": "I dry myself with a towel.", "warm": "I warm myself by the fire.",
        "explore": f"I explore the {o}." if o else "I explore.",
        "fish": "I go fishing at the pond.", "swim": "I swim in the pond.",
        "paint": "I paint a picture at the easel.", "compose": "I play the piano and record a song.",
        "sculpt": f"I make a sculpture out of {o or 'clay'}.", "write": "I write a poem.",
        "build": f"I build {_a(o) if o else 'something'}.", "fly": "I fly my kite in the meadow.",
        "follow": f"I follow {who(o)}.", "tidy": f"I put {the} back.",
    }.get(v, f"I {v} {the}.")


def _the(o: str) -> str:
    if not o:
        return "it"
    if o[0].isupper() or o == "friend":
        return o if o != "friend" else "my friend"
    if o == "water":
        return "the water"
    n = KINDS.get(o, {}).get("noun", "the " + o)
    for art_ in ("an ", "a ", "some ", "the "):
        if n.startswith(art_):
            return "the " + n[len(art_):]
    return n


def _a(o: str) -> str:
    return KINDS.get(o, {}).get("noun", ("an " if o[:1] in "aeiou" else "a ") + o)


def noun(o: str) -> str:
    return KINDS.get(o, {}).get("noun", o)


def _recipe(product: str):
    return next(((p, ing, st) for p, ing, st in RECIPES if p == product), None)


def _conjugate(v: str) -> str:
    irregular = {"am": "is", "have": "has", "do": "does", "go": "goes", "carry": "carries", "try": "tries",
                 "can": "can", "can't": "can't", "could": "could", "fly": "flies", "dry": "dries"}
    if v in irregular:
        return irregular[v]
    if v.endswith(("s", "sh", "ch", "x", "z")):
        return v + "es"
    if v.endswith("y") and v[-2:-1] not in "aeiou":
        return v[:-1] + "ies"
    return v + "s"


_BASE_VERBS = set(_VERB_OF) | {"strike", "mix", "pour", "wait", "roll", "turn", "close", "lie", "wind", "shape", "scatter"}


def third(sentence: str, name: str) -> str:
    """'I strike a match and light the stove.' -> 'Wren strikes a match and lights the stove.'"""
    s = sentence.strip()
    if not s.startswith("I "):
        return s
    words = s[2:].split(" ")
    words[0] = _conjugate(words[0])
    for i in range(1, len(words) - 1):                 # "... and light the stove": the same subject goes on
        if words[i] == "and" and words[i + 1] in _BASE_VERBS:
            words[i + 1] = _conjugate(words[i + 1])
    rest = " ".join(words[1:])
    rest = re.sub(r"\bmy\b", "the", rest)
    rest = re.sub(r"\bmyself\b", "themself", rest)
    return f"{name} {words[0]}" + (f" {rest}" if rest else "")


# ====================================================================== what is where
def carried(me: Being, kind: str) -> dict | None:
    for e in me.carrying:
        if e["kind"] == kind:
            return e
    return None


def carried_any(me: Being, kinds) -> dict | None:
    for e in me.carrying:
        if e["kind"] in kinds:
            return e
    return None


def locate(w: World, me: Being, kind: str, near: tuple | None = None):
    """Where the nearest `kind` is: ("carried", e) | ("ground", e) | ("in", container, item) |
    ("tree", tree) | ("plant", ripe plant) | None."""
    e = carried(me, kind)
    if e:
        return ("carried", e)
    frm = near or (me.x, me.y)
    best, bd = None, 1e9

    def consider(d, val):
        nonlocal best, bd
        if d < bd:
            best, bd = val, d

    for x in w.entities.values():
        d = abs(x["x"] - frm[0]) + abs(x["y"] - frm[1])
        if x["kind"] == kind and kind_of(x).get("portable") and w.reach_ok(x["x"], x["y"]):
            consider(d, ("ground", x))
        if x.get("items") and x["kind"] not in ("pot", "oven") and not kind_of(x).get("portable"):
            for i in x["items"]:
                if i["kind"] == kind:
                    consider(d + 1, ("in", x, i))
                    break
        if x.get("fruit") and KINDS[x["kind"]].get("fruit") == kind:
            consider(d + 2, ("tree", x))
        if x["kind"] == "plant" and x.get("crop") == kind and x.get("stage", 0) >= 4:
            consider(d + 3, ("plant", x))
    return best


def _stove(w: World) -> dict | None:
    return w.nearest("stove", (28, 22))


def _on_stove(w: World, kind: str) -> dict | None:
    st = _stove(w)
    if not st:
        return None
    return next((e for e in w.entities.values() if e["kind"] == kind and e.get("on") == st["id"]), None)


def food_value(e: dict) -> float:
    return KINDS[e["kind"]].get("food", 0) + (5 if e.get("temp", 0) > 40 else 0)


# ====================================================================== needs -> goals
QUESTIONS = ["Why does it rain?", "What is the sun?", "Why is fire hot?", "What are stars?", "How do plants grow?",
             "Where does honey come from?", "Why does the kettle whistle?", "What is a word?", "Why is the sky blue?",
             "Where do eggs come from?", "Why does bread get hot in the oven?", "What does the cat dream about?",
             "Why do leaves fall?", "What is snow?", "Why do frogs sing at night?"]


def drives(w: World, rng: random.Random, me: Being | None = None, independence: float = 0.0,
           asked_recently: bool = False, companion: Being | None = None, recent: list | None = None) -> Goal:
    """What its needs and purposes suggest, most pressing first, with a reason.

    `independence` (0..1) grows with the synth's language: a small synth goes to its companion
    when it needs something; a bigger one gets it itself."""
    me = me or w.ada
    n = me.needs
    comp = companion or w.wren
    night = w.phase == "night" or w.time_of_day() == "evening"
    can_self = rng.random() < independence

    def need_help(what: str, why: str) -> Goal:
        if comp and abs(comp.x - me.x) + abs(comp.y - me.y) <= 2:
            return Goal("talk", comp.name, reason=why + f" I want {comp.name} to help me {what}.", source="needs")
        return Goal("go", comp.name, text=f"I go to {comp.name}.", reason=why + f" {comp.name} can help me {what}.",
                    source="needs")

    # sleep comes first at night
    if n["rest"] < 20 or (night and n["rest"] < 70 and w.time_of_day() == "night"):
        return Goal("sleep", "bed", reason="I am very tired." if n["rest"] < 20 else "It is night. I am sleepy.",
                    source="needs")
    if me.wet > 0.5 and w.indoors(me.x, me.y):
        return Goal("dry", "towel", reason="I am wet and cold.", source="needs")
    if me.wet > 0.4 and not w.indoors(me.x, me.y) and w.raining():
        return Goal("go", "living room", reason="It is raining and I am getting wet.", source="needs")
    if n["water"] < 35:
        for e in me.carrying:
            if KINDS[e["kind"]].get("drink"):
                return Goal("drink", e["kind"], reason="I am thirsty.", source="needs")
        if can_self or n["water"] < 12:
            return Goal("drink", "water", reason="I am thirsty.", source="needs")
        return need_help("get a drink", "I am thirsty.")
    if n["energy"] < 35:
        food = max((e for e in me.carrying if food_value(e) > 0), key=food_value, default=None)
        if food:
            return Goal("eat", food["kind"], reason="I am hungry.", source="needs")
        if can_self or n["energy"] < 10:
            pot = _on_stove(w, "pot")
            if pot and any(i["kind"] == "soup" for i in pot.get("items", [])):
                return Goal("take", "soup", "pot", reason="I am hungry. There is soup in the pot.", source="needs")
            for kind in FOOD_ORDER:
                loc = locate(w, me, kind)
                if loc and loc[0] in ("ground", "in", "tree"):
                    return Goal("eat", kind, reason="I am hungry.", source="needs")
        return need_help("find something to eat", "I am hungry.")
    if n["warmth"] < 35:
        fire = w.nearest("fireplace", (13, 23))
        if fire and fire.get("lit"):
            return Goal("warm", "fireplace", reason="I am cold.", source="needs")
        if can_self and fire and fire.get("fuel", 0) > 0:
            return Goal("light", "fireplace", reason="I am cold. A fire would warm the house.", source="needs")
        return need_help("light the fire", "I am cold.")
    if n["clean"] < 25:
        return Goal("wash", "bathtub", reason="I am dirty.", source="needs")
    if n["company"] < 40 and comp and not comp.sleeping:
        return Goal("talk", comp.name, reason="I feel lonely.", source="needs")
    if night:
        return Goal("sleep", "bed", reason="It is getting dark. I am sleepy.", source="needs")
    if not asked_recently and rng.random() < 0.15:
        q = rng.choice(QUESTIONS)
        return Goal("ask", comp.name, q, reason="I am curious.", source="needs")
    opts: list[tuple[float, Goal]] = []
    recent = recent or []

    def add(score, g):
        score -= 0.35 * recent.count(f"{g.verb}:{g.obj}")     # variety: not the same thing again and again
        opts.append((score + rng.random() * 0.4, g))

    bored = n["fun"] < 50
    if comp and not comp.sleeping and abs(comp.x - me.x) + abs(comp.y - me.y) > 3:
        # a small synth likes to stay close to its companion, and watches what it does
        add(1.1 - independence, Goal("go", comp.name, text=f"I go to {comp.name}.", reason=f"I want to be with {comp.name}.",
                                     source="needs"))
    add(0.9 if bored else 0.3, Goal("play", rng.choice(["ball", "blocks", "piano", "swing", "music box", "teddy"]),
                                     reason="I want to play.", source="needs"))
    add(0.5, Goal("pet", "cat", reason="I like Moss the cat.", source="needs"))
    add(0.15 + 0.3 * independence, Goal("explore", rng.choice(["woods", "meadow", "pond", "orchard", "garden", "stream"]),
                   reason="I want to see what is there.", source="needs"))
    add(0.4, Goal("read", "picture book", reason="I like the pictures.", source="needs"))
    add(0.35 if bored else 0.15, Goal("paint", "easel", reason="I want to make something.", source="needs"))
    add(0.3, Goal("look", "mirror", reason="I wonder what I look like.", source="needs"))
    add(0.35, Goal("smell", "flower", reason="Flowers smell nice.", source="needs"))
    if independence > 0.3:
        ripe = next((e for e in w.entities.values() if e["kind"] == "plant" and e["stage"] >= 4), None)
        if ripe:
            add(0.6, Goal("harvest", ripe["crop"], reason=f"The {ripe['crop']} is ripe.", source="needs"))
        thirsty = next((e for e in w.entities.values() if e["kind"] == "plant" and e.get("thirsty")), None)
        if thirsty:
            add(0.6, Goal("water", "plant", reason="The plants are thirsty.", source="needs"))
        box = w.nearest("nest box", (4, 29))
        if box and box.get("items"):
            add(0.5, Goal("take", "egg", "nest box", reason="The hens have laid eggs.", source="needs"))
        add(0.3, Goal("compose", "piano", reason="I want to make a song.", source="needs"))
        add(0.25, Goal("fish", "pond", reason="I want to catch a fish.", source="needs"))
    if w.season == "winter" and w.weather == "snow":
        add(0.6, Goal("build", "snowman", reason="There is snow!", source="needs"))
    if w.phase == "night" or w.time_of_day() == "evening":
        add(0.4, Goal("look", "telescope", reason="The stars are out.", source="needs"))
    opts.sort(key=lambda x: -x[0])
    return opts[0][1]


# ====================================================================== goals -> plans
def plan(w: World, g: Goal, me: Being | None = None, depth: int = 0) -> tuple[Plan | None, str]:
    """Find what to walk to. If something is needed first, plan that and keep `g` for after."""
    me = me or w.ada
    if depth > 6:
        return None, "That is too many steps for me."
    sub = prerequisite(w, g, me)
    if isinstance(sub, str):
        return None, sub
    if sub is not None:
        sub.source = g.source
        sub.reason = sub.reason or f"I need it to {say(g)[2:].rstrip('.').lower()}."
        p, why = plan(w, sub, me, depth + 1)
        if p:
            p.then.append(g)
            p.depth = depth + 1
        return p, why
    target, why = find_target(w, g, me)
    if target is False:
        return None, why
    return Plan(g, target), ""


def prerequisite(w: World, g: Goal, me: Being):
    """The first thing `g` needs that isn't there yet: a Goal to do first, a reason it can't be done
    (a string), or None when it can be done now."""
    v, o, x = g.verb, g.obj, g.extra
    full = len(me.carrying) >= HANDS
    if v == "eat":
        if o in ("", "food"):
            food = max((e for e in me.carrying if food_value(e) > 0), key=food_value, default=None)
            if food:
                g.obj = food["kind"]
                return None
            for kind in FOOD_ORDER:
                if locate(w, me, kind):
                    g.obj = o = kind
                    break
            else:
                return "There is no food I can find."
        if o not in KINDS or KINDS[o].get("food") is None:
            return f"I can't eat {_the(o) if o else 'that'}."
        if carried(me, o):
            return None
        if o == "soup":
            pot = _on_stove(w, "pot") or w.nearest("pot", (me.x, me.y))
            if pot and any(i["kind"] == "soup" for i in pot.get("items", [])):
                return Goal("take", "soup", "pot")
            return Goal("cook", "soup")
        if locate(w, me, o) is None:
            return f"There is no {o} here."
        return Goal("take", o) if not full else Goal("drop", me.carrying[0]["kind"])
    if v == "drink":
        if o in ("", "water", "sink"):
            return None
        if o not in KINDS or not KINDS[o].get("drink"):
            return f"I can't drink {_the(o)}."
        if carried(me, o):
            return None
        if o == "tea":
            return Goal("brew", "tea")
        if o == "cup of water":
            return Goal("fill", "cup")
        return Goal("take", o)
    if v in ("take", "harvest"):
        if v == "harvest" or (o in KINDS and not KINDS[o].get("portable") and o != "plant"):
            return None
        basket = carried(me, "basket")
        room = basket is not None and len(basket.get("items", [])) < KINDS["basket"]["container"]
        if full and not room:
            spare = next((e for e in me.carrying if e["kind"] != "basket"), me.carrying[0])
            return Goal("drop", spare["kind"], reason="My hands are full.")
        return None
    if v in ("put", "give", "show", "drop") and o:
        if o not in KINDS:
            return f"I don't know {o}."
        if v == "give" and not carried(me, o) and o == "cup of water":
            return Goal("fill", "cup")
        if v == "give" and not carried(me, o) and o == "tea":
            return Goal("brew", "tea")
        if not carried(me, o):
            if o == "log" and x in ("fireplace", "stove") and not locate(w, me, "log"):
                return Goal("chop", "log")
            if locate(w, me, o) is None:
                return f"I don't have {_the(o)}."
            return Goal("take", o)
        return None
    if v == "feed":
        target, food = o, x
        if target in ("cat", "hen", "robin"):
            food = food or {"cat": "egg", "hen": "wheat", "robin": "wheat seed"}[target]
            if target == "robin" and not locate(w, me, food):
                food = "wheat"
            g.extra = food
            if not carried(me, food):
                if locate(w, me, food) is None:
                    return f"There is no {food} to feed {_the(target)}."
                return Goal("take", food)
            return None
        # feeding someone: bring them good food
        if not food:
            have = max((e for e in me.carrying if food_value(e) > 0), key=food_value, default=None)
            if have:
                g.extra = have["kind"]
                return None
            pot = _on_stove(w, "pot")
            if pot and any(i["kind"] == "soup" for i in pot.get("items", [])):
                g.extra = "soup"
                return Goal("take", "soup", "pot")
            for kind in FOOD_ORDER:
                if KINDS[kind].get("food", 0) > 10 and locate(w, me, kind):
                    g.extra = kind
                    return Goal("take", kind)
            return "There is no food to give."
        if not carried(me, food):
            return Goal("take", food) if locate(w, me, food) else f"There is no {food}."
        return None
    if v == "plant":
        seed = o if o in KINDS and KINDS[o].get("grows") else ""
        if not seed:
            crop = o if o in KINDS and KINDS[o].get("grows_from") else ""
            seed = KINDS[crop]["grows_from"] if crop else ""
        if not seed:
            have = next((e for e in me.carrying if KINDS[e["kind"]].get("grows")), None)
            seed = have["kind"] if have else ""
        if not seed:
            box = w.nearest("seed tin", (36, 17))
            seed = box["items"][0]["kind"] if box and box.get("items") else ""
        if not seed:
            return "There are no seeds left."
        g.obj = seed
        if not carried(me, seed):
            return Goal("take", seed) if locate(w, me, seed) else f"There are no {noun(seed).split(' ', 1)[-1]}."
        return None
    if v == "water":
        can = carried(me, "watering can") or carried(me, "bucket")
        if not can:
            return Goal("take", "watering can") if locate(w, me, "watering can") else Goal("take", "bucket")
        if can.get("water", 0) < 0.5:
            return Goal("fill", can["kind"])
        return None
    if v == "fill":
        kind = o if o in KINDS and KINDS[o].get("vessel") and KINDS[o].get("portable") else ""
        if not kind:
            have = next((e for e in me.carrying if KINDS[e["kind"]].get("vessel")), None)
            kind = have["kind"] if have else "bucket"
            g.obj = kind
        if not carried(me, kind):
            return Goal("take", kind) if locate(w, me, kind) else f"There is no {kind}."
        return None
    if v == "chop":
        return None if carried(me, "axe") else Goal("take", "axe")
    if v == "light":
        o = g.obj = o if o in ("fireplace", "stove", "lamp", "candle") else "fireplace"
        thing = w.nearest(o, (me.x, me.y)) if o in ("fireplace", "stove") else (carried(me, o) or w.nearest(o, (me.x, me.y)))
        if thing is None:
            return f"There is no {o}."
        if thing.get("lit"):
            return f"{_cap(_the(o))} is already lit."
        if o in ("fireplace", "stove") and thing.get("fuel", 0) <= 0:
            return Goal("put", "log", o)
        if o in ("lamp", "candle") and thing.get("burn", 1) <= 0:
            return f"{_cap(_the(o))} has burnt down."
        if not carried(me, "matches"):
            return Goal("take", "matches")
        return None
    if v == "cook":
        return _cook_steps(w, g, me)
    if v == "bake":
        return _bake_steps(w, g, me)
    if v == "brew":
        return _tea_steps(w, g, me)
    if v == "make":
        r = _recipe(o)
        if not r:
            if o in ("soup",):
                return Goal("cook", o)
            if o in ("bread", "apple pie", "baked apple", "roast potato"):
                return Goal("bake", o)
            if o in ("tea",):
                return Goal("brew", "tea")
            return f"I don't know how to make {_a(o) if o else 'that'}."
        _, ings, _st = r
        have = [e["kind"] for e in me.carrying]
        for k in ings:
            if k in have:
                have.remove(k)
                continue
            if k == "flour" and not locate(w, me, "flour"):
                return Goal("make", "flour")
            if k == "dough" and not locate(w, me, "dough"):
                return Goal("make", "dough")
            if locate(w, me, k) is None:
                return f"I need {_a(k)} to make {_a(o)}."
            if len(me.carrying) >= HANDS:
                return Goal("drop", me.carrying[0]["kind"])
            return Goal("take", k)
        return None
    if v == "fish":
        return None if carried(me, "fishing rod") else Goal("take", "fishing rod")
    if v == "sculpt":
        mat = o if o in SCULPT_MATERIALS else next((m for m in SCULPT_MATERIALS if carried(me, m)), "clay")
        g.obj = mat
        if not carried(me, mat):
            return Goal("take", mat) if locate(w, me, mat) else f"There is no {mat}."
        if not carried(me, "chisel") and mat != "clay":
            return Goal("take", "chisel")
        return None
    if v == "write":
        for k in ("paper", "pencil"):
            if not carried(me, k):
                return Goal("take", k) if locate(w, me, k) else f"There is no {k}."
        return None
    if v == "fly":
        if not carried(me, "kite"):
            return Goal("take", "kite") if locate(w, me, "kite") else Goal("make", "kite")
        return None
    if v == "build":
        if o == "snowman":
            return None if w.season == "winter" else "There is no snow."
        if o in ("", "birdhouse"):
            g.obj = "birdhouse"
            return Goal("make", "birdhouse") if not carried(me, "birdhouse") else None
        return f"I don't know how to build {_a(o)}."
    if v == "play" and o in ("ball", "blocks", "teddy", "kite") and not carried(me, o):
        return Goal("take", o) if locate(w, me, o) else f"There is no {o}."
    if v == "read" and o in ("book", "picture book") and not carried(me, o):
        e = w.nearest(o, (me.x, me.y))
        if e is None:
            return Goal("take", o) if locate(w, me, o) else f"There is no {o}."
    if v == "dry" and o and o[0].isupper():
        return None if carried(me, "towel") else Goal("take", "towel")
    if v == "dry":
        if not carried(me, "towel") and not (w.nearest("towel", (me.x, me.y)) and
                                                abs(w.nearest("towel", (me.x, me.y))["x"] - me.x) <= 1):
            return None
    return None


def _cook_steps(w: World, g: Goal, me: Being):
    """Soup (or jam, or a boiled egg): water and something in the pot, the pot on a lit stove, then wait."""
    want = g.obj or "soup"
    ing_kinds = {"jam": {"berries"}, "boiled egg": {"egg"}}.get(want, SOUP_THINGS)
    pot = _on_stove(w, "pot")
    held = carried(me, "pot")
    pot = pot or held or w.nearest("pot", (me.x, me.y))
    if pot is None:
        loc = locate(w, me, "pot")
        if not loc:
            return "There is no pot."
        return Goal("take", "pot")
    if any(i["kind"] == want for i in pot.get("items", [])):
        return None                                    # it's ready: take some
    if pot.get("on") is None:
        if not held:
            return Goal("take", "pot")
        if held.get("water", 0) < 0.8:
            return Goal("fill", "pot")
        if not any(i["kind"] in ing_kinds for i in held.get("items", [])):
            veg = next((e for e in me.carrying if e["kind"] in ing_kinds), None)
            if veg:
                return Goal("put", veg["kind"], "pot")
            for k in sorted(ing_kinds, key=lambda k: k not in ("carrot", "potato")):
                if locate(w, me, k):
                    return Goal("take", k)
            return f"There is nothing to put in the {want}."
        return Goal("put", "pot", "stove")
    return _stove_ready(w)


def _stove_ready(w: World):
    """The stove lit, with wood enough to finish the job."""
    stove = _stove(w)
    if stove is None:
        return "There is no stove."
    if stove.get("fuel", 0) < 200:
        return Goal("put", "log", "stove", reason="The stove needs more wood.")
    if not stove.get("lit"):
        return Goal("light", "stove")
    return None


def _bake_steps(w: World, g: Goal, me: Being):
    want = g.obj if g.obj in ("bread", "apple pie", "baked apple", "roast potato", "baked fish") else "bread"
    g.obj = want
    oven = w.nearest("oven", (27, 22))
    if oven is None:
        return "There is no oven."
    if any(i["kind"] == want for i in oven.get("items", [])):
        return None
    need = {"bread": ["dough"], "apple pie": ["dough", "apple"], "baked apple": ["apple"],
            "roast potato": ["potato"], "baked fish": ["raw fish"]}[want]
    inside = [i["kind"] for i in oven.get("items", [])]
    for k in need:
        if k in inside:
            inside.remove(k)
            continue
        if carried(me, k):
            return Goal("put", k, "oven")
        if k == "dough" and not locate(w, me, "dough"):
            return Goal("make", "dough")
        if locate(w, me, k) is None:
            return f"There is no {k} for the {want}."
        return Goal("take", k)
    return _stove_ready(w)
    return None


def _tea_steps(w: World, g: Goal, me: Being):
    kettle = _on_stove(w, "kettle")
    held = carried(me, "kettle")
    if g.obj == "tea" and carried(me, "tea"):
        return None
    if kettle is None:
        k = held or w.nearest("kettle", (me.x, me.y))
        if k is None:
            return "There is no kettle."
        if not held:
            return Goal("take", "kettle")
        if held.get("water", 0) < 0.3:
            return Goal("fill", "kettle")
        return Goal("put", "kettle", "stove")
    ready = _stove_ready(w)
    if ready:
        return ready
    if g.obj == "tea":
        for k in ("cup", "mint"):
            if not carried(me, k):
                return Goal("take", k) if locate(w, me, k) else f"There is no {k} for tea."
    return None


def find_target(w: World, g: Goal, me: Being):
    """Where to go for a goal that can be done now: a target, or (False, why)."""
    v, o, x = g.verb, g.obj, g.extra
    here = (me.x, me.y)

    def ent(e):
        return ("entity", e["id"]), ""

    def nearest(kind):
        e = w.nearest(kind, here)
        return ent(e) if e else (False, f"There is no {kind} here.")

    if v in ("eat", "drink") and (carried(me, o) or v == "eat"):
        if carried(me, o):
            return None, ""
    if v == "drink":
        if carried(me, o):
            return None, ""
        sink = w.nearest("sink", here)
        if sink and (w.indoors(me.x, me.y) or abs(sink["x"] - me.x) + abs(sink["y"] - me.y) < 25):
            return ent(sink)
        water = w.nearest_tile(WATER, here)
        return (("tile", water, True), "") if water else (False, "There is no water.")
    if v == "take":
        if x:
            src = w.nearest(x, here) if x in KINDS else None
            if src is not None:
                return ent(src)
        loc = locate(w, me, o)
        if loc is None:
            return False, f"There is no {o} here."
        if loc[0] == "carried":
            return False, f"I already have {_the(o)}."
        return ("entity", (loc[1] if loc[0] != "in" else loc[1])["id"]), ""
    if v == "harvest":
        ripe = [e for e in w.entities.values() if e["kind"] == "plant" and e["stage"] >= 4 and (not o or e["crop"] == o)]
        if not ripe:
            return False, "Nothing is ripe yet."
        return ent(min(ripe, key=lambda e: abs(e["x"] - me.x) + abs(e["y"] - me.y)))
    if v in ("put",):
        if not x:
            return None, ""
        if x in ("ground", "floor") or carried(me, x):
            return None, ""
        dest = w.nearest(x, here) if x in KINDS else None
        if dest is None and x in KINDS and carried(me, x):
            return None, ""
        if dest is None:
            return False, f"There is no {x} here."
        return ent(dest)
    if v in ("drop",):
        return None, ""
    if v == "tidy":
        e = carried(me, o)
        if e is None or not e.get("home"):
            return False, "I don't know where that goes."
        return ("tile", tuple(e["home"]), not w.walkable(*e["home"])), ""
    if v in ("give", "show", "talk", "follow", "hug") and (x or o) and (v != "hug" or (o and o[0].isupper())):
        b = w.being(x if v in ("give", "show") else o)
        if b is None or b is me:
            return False, "Nobody by that name is here."
        return ("being", b.name), ""
    if v == "ask":
        b = w.being(o or w.wren.name)
        if b is None or b is me:
            return False, "Nobody is here to ask."
        return ("being", b.name), ""
    if v == "feed":
        if o and o[0].isupper():
            b = w.being(o)
            return (("being", b.name), "") if b and b is not me else (False, "Nobody by that name is here.")
        return nearest({"cat": "cat bowl", "hen": "hen", "robin": "bird feeder"}.get(o, "cat bowl"))
    if v == "go":
        if o and o[0].isupper() or o == "friend":
            b = w.being(o)
            return (("being", b.name), "") if b and b is not me else (False, "Nobody by that name is here.")
        if o in w.anchors:
            return ("tile", w.anchors[o], False), ""
        if o in KINDS:
            return nearest(o)
        return False, f"I don't know where {o or 'that'} is."
    if v == "explore":
        place = o if o in w.anchors else w.rng.choice(["woods", "meadow", "pond", "orchard", "stream", "lookout"])
        g.obj = place
        cells = [c for c in w.cells.get(place, []) if w.walkable(*c)]
        spot = w.rng.choice(cells) if cells else w.anchors[place]
        return ("tile", spot, False), ""
    if v == "plant":
        spots = [(px, py) for (px, py) in w.moisture if not w.at(px, py) and not w.occupied(px, py)]
        if o == "tomato seed" or w.season == "winter":
            gh = [s for s in spots if w.region[s[1]][s[0]] == "greenhouse"]
            spots = gh or spots
        if not spots:
            return False, "Every bed is full."
        return ("tile", min(spots, key=lambda s: abs(s[0] - me.x) + abs(s[1] - me.y)), True), ""
    if v == "water":
        plants = [e for e in w.entities.values() if e["kind"] == "plant"]
        if not plants:
            return False, "There are no plants to water."
        p = min(plants, key=lambda e: (w.moisture.get((e["x"], e["y"]), 1), abs(e["x"] - me.x) + abs(e["y"] - me.y)))
        return ent(p)
    if v == "fill":
        can = carried(me, o)
        if o in ("watering can", "bucket"):
            barrel = w.nearest("water barrel", here)
            if barrel and barrel.get("water", 0) > 2 and abs(barrel["x"] - me.x) + abs(barrel["y"] - me.y) < 26:
                return ent(barrel)
        sink = w.nearest("sink", here)
        if sink:
            return ent(sink)
        water = w.nearest_tile(WATER, here)
        return (("tile", water, True), "") if water and can else (False, "There is no water.")
    if v == "chop":
        tree = w.nearest_tile({TREE, PINE}, (32, 8))
        return (("tile", tree, True), "") if tree else (False, "There are no trees.")
    if v == "light":
        if o in ("lamp", "candle") and carried(me, o):
            return None, ""
        return nearest(o)
    if v == "cook":
        pot = _on_stove(w, "pot")
        return ent(pot) if pot else nearest("stove")
    if v == "bake":
        return nearest("oven")
    if v == "brew":
        k = _on_stove(w, "kettle")
        return ent(k) if k else nearest("stove")
    if v == "make":
        r = _recipe(o)
        if r and r[2]:
            return nearest(r[2])
        return None, ""
    if v == "sleep":
        role = me.role
        bed = w.nearest("bed", here, where=lambda e: e.get("owner") == role) or w.nearest("bed", here)
        return ent(bed) if bed else (False, "There is no bed.")
    if v == "rest":
        seat = w.nearest({"sofa", "bench"}, here)
        return ent(seat) if seat else (None, "")
    if v == "warm":
        fire = w.nearest("fireplace", here)
        return ent(fire) if fire else (False, "There is no fire.")
    if v == "wash":
        return nearest("bathtub")
    if v == "dry":
        if o and o[0].isupper():
            b = w.being(o)
            return (("being", b.name), "") if b and b is not me else (False, "Nobody by that name is here.")
        if carried(me, "towel"):
            return None, ""
        return nearest("towel")
    if v == "fish":
        spot = next(((x_, y_) for y_ in range(56) for x_ in range(72) if w.terrain[y_][x_] == DOCK
                     and w.region[y_][x_] == "pond"), None)
        if spot is None:
            water = w.nearest_tile(WATER, here)
            return (("tile", water, True), "") if water else (False, "There is no water.")
        return ("tile", max((s for s in [(x_, spot[1]) for x_ in range(spot[0], spot[0] + 6)]
                             if w.terrain[s[1]][s[0]] == DOCK), key=lambda s: s[0]), False), ""
    if v == "swim":
        return ("tile", w.anchors["pond"], False), ""
    if v in ("play", "read", "smell", "pet", "look", "listen", "hug", "compose", "paint", "sculpt", "write", "build", "fly"):
        o = {"compose": "piano", "paint": "easel", "write": "desk", "sculpt": "workbench"}.get(v, o)
        if v == "build" and g.obj == "snowman":
            return ("tile", w.anchors["yard"], False), ""
        if v == "build":
            spot = w.free_spot(*w.anchors["garden"], radius=4) or w.anchors["yard"]
            return ("tile", spot, False), ""
        if v == "fly":
            return ("tile", w.anchors["meadow"], False), ""
        if v == "look" and o in ("", "around"):
            return None, ""
        if v == "listen" and o in ("", "rain", "birds"):
            return None, ""
        if o and carried(me, o):
            return None, ""
        if o == "flower":
            loc = locate(w, me, "flower")
            return (ent(loc[1]) if loc and loc[0] == "ground" else
                    (("tile", w.nearest_tile({5}, here), True), "") if w.nearest_tile({5}, here) else (False, "No flowers."))
        if o in KINDS:
            e = w.nearest(o, here)
            if e:
                return ent(e)
            loc = locate(w, me, o)
            if loc and loc[0] == "in":
                return ent(loc[1])
            return False, f"There is no {o} here."
        return None, ""
    return None, ""


def target_pos(w: World, p: Plan):
    t = p.target
    if t is None:
        return None
    if t[0] == "entity":
        e = w.entities.get(t[1])
        if e is None:
            return None
        on = (e["x"], e["y"])
        blocking = not w.walkable(*on) or not kind_of(e).get("portable") or e["kind"] == "plant"
        return on[0], on[1], blocking
    if t[0] == "tile":
        return t[1][0], t[1][1], t[2]
    if t[0] == "being":
        b = w.being(t[1])
        return (b.x, b.y, True) if b else None
    return None


# ====================================================================== doing it
def act(w: World, p: Plan, me: Being | None = None):
    """Do the goal, now that `me` is there. Returns (ok, narration, info), or None while it takes time."""
    me = me or w.ada
    g = p.goal
    v, o, x = g.verb, g.obj, g.extra
    info: dict = {}
    k = me.needs
    other = w.wren if me is w.ada else w.ada
    here = w.entities.get(p.target[1]) if p.target and p.target[0] == "entity" else None

    def hold(e: dict) -> bool:
        if len(me.carrying) >= HANDS:
            basket = carried(me, "basket")
            if basket and len(basket.setdefault("items", [])) < KINDS["basket"]["container"]:
                basket["items"].append(e)
                return True
            return False
        me.carrying.append(e)
        return True

    def release(e: dict):
        me.carrying = [c for c in me.carrying if c is not e]

    if v == "eat":
        food = carried(me, o)
        if food is None:
            return False, f"I don't have {_the(o)}.", {}
        release(food)
        val = KINDS[o].get("food", 0)
        k["energy"] = min(100, k["energy"] + val)
        k["water"] = min(100, k["water"] + KINDS[o].get("drink", 0))
        if food.get("temp", 0) > 40:
            k["warmth"] = min(100, k["warmth"] + KINDS[o].get("warm", 8))
        if o == "soup":
            bowl = w.make("bowl")
            hold(bowl) or w.put(bowl, me.x, me.y)
        info["ate"] = o
        if val < 0:
            return True, f"I eat {_the(o)}. Yuck! It tastes bad raw. It should be cooked.", info
        if food.get("temp", 0) > 75:
            k["energy"] -= 2
            return True, f"I eat {_the(o)}. Ow, it is very hot! But it is good.", info
        taste = {"apple": "It is sweet and crunchy.", "soup": "It is warm and tasty.", "bread": "It is soft.",
                 "honey": "It is sweet and sticky.", "carrot": "It is crunchy.", "jam": "It is sweet.",
                 "rotten food": "It is horrible!", "burnt food": "It tastes of smoke."}.get(o, "It is good.")
        return True, f"I eat {_the(o)}. {taste}", info
    if v == "drink":
        cup = carried(me, o) if o not in ("", "water", "sink") else None
        if cup:
            release(cup)
            k["water"] = min(100, k["water"] + KINDS[o].get("drink", 30))
            if cup.get("temp", 0) > 40:
                k["warmth"] = min(100, k["warmth"] + KINDS[o].get("warm", 10))
            empty = w.make("cup")
            hold(empty) or w.put(empty, me.x, me.y)
            return True, f"I drink {_the(o)}." + (" It is warm and good." if cup.get("temp", 0) > 40 else ""), {}
        k["water"] = min(100, k["water"] + 40)
        src = "from the sink" if here and here["kind"] == "sink" else "from the " + w.place_of(me.x, me.y)
        return True, f"I drink cold water {src}.", {}
    if v == "take":
        src = here
        if src is None:
            return False, "It isn't here any more.", {}
        if o == "soup" and src["kind"] == "pot":
            soup = next((i for i in src.get("items", []) if i["kind"] == "soup"), None)
            if soup is None:
                return False, "There is no soup in the pot.", {}
            if not carried(me, "bowl") and not w.nearest("bowl", (me.x, me.y)):
                return False, "I need a bowl for the soup.", {}
            bowl = carried(me, "bowl")
            if bowl:
                release(bowl)
            else:
                b = w.nearest("bowl", (me.x, me.y))
                w.remove(b)
            src["items"].remove(soup)
            hold(soup)
            w.touch(src)
            return True, "I fill a bowl with hot soup from the pot.", {}
        if src.get("items") and (o in [i["kind"] for i in src["items"]] or not KINDS.get(src["kind"], {}).get("portable")):
            item = next((i for i in src["items"] if i["kind"] == o), None) if o else src["items"][-1]
            if item is None:
                return False, f"There is no {o} in {_the(src['kind'])}.", {}
            if not hold(item):
                return False, "My hands are full.", {}
            src["items"].remove(item)
            w.touch(src)
            hot = " It is hot!" if item.get("temp", 0) > 60 else ""
            if src["kind"] == "nest box":
                return True, f"I take {noun(item['kind'])} from the nest box. It is still warm.", {"took": item["kind"]}
            if src["kind"] == "oven":
                src["baked"] = False
            return True, f"I take {noun(item['kind'])} from {_the(src['kind'])}.{hot}", {"took": item["kind"]}
        if src.get("fruit") is not None:
            if src["fruit"] <= 0:
                return False, f"There is no fruit on {_the(src['kind'])}.", {}
            fruit = KINDS[src["kind"]]["fruit"]
            src["fruit"] -= 1
            w.touch(src)
            item = w.make(fruit)
            if not hold(item):
                w.put(item, me.x, me.y)
                return False, "My hands are full.", {}
            return True, f"I pick {noun(fruit)} from {_the(src['kind'])}.", {"took": fruit}
        if src["kind"] == "beehive":
            if src.get("honey", 0) <= 0:
                return False, "There is no honey in the hive yet.", {}
            src["honey"] -= 1
            w.touch(src)
            hold(w.make("honey"))
            if w.rng.random() < 0.25:
                k["fun"] = max(0, k["fun"] - 10)
                return True, "I take a jar of honey from the hive. Ouch! A bee stings me.", {"took": "honey"}
            return True, "I take a jar of honey from the hive. The bees buzz around me.", {"took": "honey"}
        if src["kind"] == "plant":
            return _harvest(w, me, src, hold)
        if KINDS[src["kind"]].get("creature"):
            return False, f"{_cap(_the(src['kind']))} doesn't want to be carried.", {}
        if not KINDS[src["kind"]].get("portable"):
            return False, f"{_cap(_the(src['kind']))} is too big to carry.", {}
        if not hold(src):
            return False, "My hands are full.", {}
        w.remove(src)
        src.pop("on", None)
        hot = " It is hot!" if src.get("temp", 0) > 60 else ""
        wet = " It is wet." if src.get("wet", 0) > 0.4 else ""
        return True, f"I pick up {noun(src['kind'])}.{hot}{wet}", {"took": src["kind"]}
    if v == "harvest":
        if here is None or here["kind"] != "plant":
            return False, "There is nothing to harvest here.", {}
        return _harvest(w, me, here, hold)
    if v == "tidy":
        e = carried(me, o)
        if e is None:
            return False, "I am not carrying that.", {}
        release(e)
        hx, hy = e.get("home", [me.x, me.y])
        spot = (hx, hy) if w.walkable(hx, hy) and not any(x_["kind"] == o for x_ in w.at(hx, hy)) else \
            (w.free_spot(hx, hy, 2) or (me.x, me.y))
        w.put(e, *spot)
        return True, f"I put {_the(o)} back where {'it belongs' if o != 'matches' else 'they belong'}.", {}
    if v == "drop" or (v == "put" and x in ("", "ground", "floor")):
        e = carried(me, o) if o else (me.carrying[-1] if me.carrying else None)
        if e is None:
            return False, "I am not carrying that.", {}
        release(e)
        spot = (me.x, me.y) if not w.at(me.x, me.y) else (w.free_spot(me.x, me.y, 2) or (me.x, me.y))
        w.put(e, *spot)
        return True, f"I put down {noun(e['kind'])}.", {}
    if v == "put":
        e = carried(me, o)
        if e is None:
            return False, f"I don't have {_the(o)}.", {}
        dest = here or carried(me, x)
        if dest is None:
            return False, f"There is no {x} here.", {}
        return _put_in(w, me, e, dest, release)
    if v in ("give", "show"):
        e = carried(me, o)
        b = w.being(x)
        if e is None or b is None:
            return False, "I can't do that.", {}
        if v == "show":
            info["showed"] = (o, b.name)
            return True, f"I show {noun(o)} to {w.describe(b) if b is not w.visitor else 'my friend'}.", info
        release(e)
        if len(b.carrying) < HANDS:
            b.carrying.append(e)
        else:
            w.put(e, b.x, b.y)
        info["gave"] = (o, b.name)
        w.bond = min(100.0, w.bond + 1.5)
        return True, f"I give {noun(o)} to {w.describe(b)}.", info
    if v == "feed":
        food = carried(me, x)
        if o and o[0].isupper():
            b = w.being(o)
            if b is None or food is None:
                return False, "I have nothing to give.", {}
            release(food)
            val = KINDS[food["kind"]].get("food", 0)
            b.needs["energy"] = min(100, b.needs["energy"] + val)
            b.needs["water"] = min(100, b.needs["water"] + KINDS[food["kind"]].get("drink", 0))
            if food.get("temp", 0) > 40:
                b.needs["warmth"] = min(100, b.needs["warmth"] + 10)
            w.bond = min(100.0, w.bond + 2)
            info["fed"] = (b.name, food["kind"])
            return True, f"I give {noun(food['kind'])} to {b.name}, and {b.name} eats it.", info
        if food is None:
            return False, f"I have nothing to feed {_the(o)}.", {}
        release(food)
        if o == "cat":
            bowl = here if here and here["kind"] == "cat bowl" else w.nearest("cat bowl", (me.x, me.y))
            bowl.setdefault("items", []).append(food)
            w.touch(bowl)
            return True, f"I put {noun(food['kind'])} in the cat bowl for Moss.", {}
        if o == "robin":
            feeder = here if here and here["kind"] == "bird feeder" else w.nearest("bird feeder", (me.x, me.y))
            feeder.setdefault("items", []).extend([food])
            w.touch(feeder)
            return True, "I fill the bird feeder. The birds will come.", {}
        w.sounds.append(("the hens clucking happily", me.x, me.y, 6))
        return True, "I scatter wheat for the hens. They peck it up, clucking.", {}
    if v in ("talk", "follow"):
        b = w.being(o)
        if b is None:
            return False, "Nobody is here.", {}
        if v == "follow":
            return True, f"I walk with {w.describe(b)}.", {}
        info["talk"] = b.name if b is not w.visitor else "friend"
        return True, f"I go up to {w.describe(b)} to talk.", info
    if v == "ask":
        b = w.being(o or w.wren.name)
        info["ask"] = x or w.rng.choice(QUESTIONS)
        info["to"] = b.name if b else w.wren.name
        return True, f"I ask {info['to']}: {info['ask']}", info
    if v == "hug":
        b = w.being(o) if o and o[0].isupper() else None
        if b:
            for n_ in (k, b.needs):
                n_["company"] = min(100, n_["company"] + 25)
            w.bond = min(100.0, w.bond + 3)
            info["hug"] = b.name
            return True, f"I hug {w.describe(b)}. It feels warm and safe.", info
        k["company"] = min(100, k["company"] + 10)
        k["fun"] = min(100, k["fun"] + 5)
        return True, f"I hug {_the(o or 'teddy')}. It is soft.", {}
    if v == "read":
        book = carried(me, o) or (here if here and here["kind"] in ("book", "picture book", "sign") else None)
        if book is None and here and here.get("items"):
            book = next((i for i in here["items"] if i["kind"] == o), None)
        if book is None:
            return False, "There is nothing to read here.", {}
        if book["kind"] == "sign":
            return True, f"I read the sign. It says: {book.get('text', '')}", {"read": book}
        k["fun"] = min(100, k["fun"] + 10)
        info["read"] = book
        return True, f"I open {noun(book['kind']).replace('a ', 'the ', 1)} and read.", info
    if v == "play":
        if o == "piano":
            if not p.working:
                me.activity = "playing the piano"
            p.working += 1
            w.sounds.append(("piano music", me.x, me.y, 12))
            if p.working < 16:
                return None
            me.activity = ""
            k["fun"] = min(100, k["fun"] + 30)
            return True, "I play the piano. Plink, plonk! The notes are high and low.", {}
        if o == "music box":
            w.sounds.append(("the music box tinkling", me.x, me.y, 6))
            k["fun"] = min(100, k["fun"] + 15)
            return True, "I wind up the music box. It plays a little tune.", {}
        if o == "swing":
            k["fun"] = min(100, k["fun"] + 25)
            return True, "I swing high on the swing. Whee! I can see over the fence.", {}
        k["fun"] = min(100, k["fun"] + 20)
        if other and abs(other.x - me.x) + abs(other.y - me.y) <= 3 and not other.sleeping:
            k["company"] = min(100, k["company"] + 10)
            info["played_with"] = other.name
            return True, {"ball": f"I throw the ball to {other.name}, and {other.name} throws it back!",
                          "blocks": f"I build a tower of blocks with {other.name}. It falls down!"}.get(
                o, f"I play with {_the(o or 'teddy')} with {other.name}."), info
        return True, {"ball": "I kick the ball. It bounces and rolls away.",
                      "blocks": "I build a tower of blocks. It is tall! Then it falls down.",
                      "teddy": "I play with my teddy bear."}.get(o, "I play."), {}
    if v == "pet":
        cat = w.nearest(o or "cat", (me.x, me.y))
        if cat is None or abs(cat["x"] - me.x) + abs(cat["y"] - me.y) > 1:
            return False, "It ran away.", {}
        k["company"] = min(100, k["company"] + 12)
        k["fun"] = min(100, k["fun"] + 8)
        if o in ("cat", ""):
            hungry = cat.get("hunger", 0) > 60
            w.sounds.append(("Moss purring" if not hungry else "Moss meowing", cat["x"], cat["y"], 3))
            return True, ("I pet Moss. Moss meows. I think Moss is hungry." if hungry
                          else "I pet Moss. The fur is soft and Moss purrs."), {}
        return True, f"I pet {_the(o)}. It says {KINDS[o].get('sound', 'nothing')}.", {}
    if v == "smell":
        k["fun"] = min(100, k["fun"] + 5)
        return True, {"flower": "I smell the flower. It smells sweet.", "bread": "I smell the bread. It smells warm.",
                      "soup": "I smell the soup. Mmm!", "rotten food": "I smell it. Yuck!",
                      "mint": "I smell the mint. It smells fresh."}.get(o, f"I smell {_the(o)}."), {}
    if v == "plant":
        seed = carried(me, o)
        tx, ty = p.target[1] if p.target and p.target[0] == "tile" else (me.x, me.y)
        if seed is None or w.terrain[ty][tx] != SOIL or any(e["kind"] == "plant" for e in w.at(tx, ty)):
            return False, "I can't plant here.", {}
        release(seed)
        crop = KINDS[o]["grows"]
        w.add("plant", tx, ty, crop=crop, stage=0.0, health=1.0, glyph="🌱")
        w.moisture[(tx, ty)] = max(w.moisture.get((tx, ty), 0), 0.3)
        k["clean"] = max(0, k["clean"] - 4)
        return True, f"I plant {noun(o)} in the soil. One day it will be {_a(crop)}.", {"planted": crop}
    if v == "water":
        can = carried(me, "watering can") or carried(me, "bucket")
        if can is None or can.get("water", 0) <= 0:
            return False, "My can is empty.", {}
        tx, ty = (here["x"], here["y"]) if here else (me.x, me.y)
        n = 0
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                if (tx + dx, ty + dy) in w.moisture and can["water"] > 0:
                    w.moisture[(tx + dx, ty + dy)] = min(1.0, w.moisture[(tx + dx, ty + dy)] + 0.7)
                    can["water"] = max(0.0, can["water"] - 0.3)
                    n += 1
        for e in w.at(tx, ty):
            e.pop("thirsty", None)
            w.touch(e)
        p.working += 1
        if can["water"] >= 0.4 and p.working < 6:        # on to the next dry bed, while the can has water
            dry = [e for e in w.entities.values() if e["kind"] == "plant" and w.moisture.get((e["x"], e["y"]), 1) < 0.35
                   and abs(e["x"] - me.x) + abs(e["y"] - me.y) <= 14]
            if dry:
                nxt = min(dry, key=lambda e: abs(e["x"] - me.x) + abs(e["y"] - me.y))
                p.target, p.route = ("entity", nxt["id"]), []
                return None
        if can["water"] < 0.4 and p.working < 6 and any(
                e["kind"] == "plant" and w.moisture.get((e["x"], e["y"]), 1) < 0.3 for e in w.entities.values()):
            p.then[:0] = [Goal("fill", can["kind"], reason="The can is empty."), Goal("water", "plant")]
        return True, "I water the plants. The soil gets dark and wet." if p.working > 1 or n > 1 else "I water the plant.", {}
    if v == "fill":
        vessel = carried(me, o)
        if vessel is None:
            return False, f"I don't have {_the(o)}.", {}
        cap = KINDS[o]["vessel"]
        src = here["kind"] if here else "pond"
        if here and here["kind"] == "water barrel":
            take = min(cap - vessel.get("water", 0), here.get("water", 0))
            here["water"] -= take
            vessel["water"] = vessel.get("water", 0) + take
            w.touch(here)
        else:
            vessel["water"] = cap
        if o == "cup":
            release(vessel)
            hold(w.make("cup of water"))
        vessel.pop("boiled", None)
        return True, f"I fill {_the(o)} with water from {_the(src) if src in KINDS else 'the pond'}.", {}
    if v == "chop":
        if not carried(me, "axe"):
            return False, "I need the axe.", {}
        if not p.working:
            me.activity = "chopping wood"
        p.working += 1
        w.sounds.append(("chopping: thock, thock", me.x, me.y, 14))
        if p.working < 10:
            return None
        me.activity = ""
        k["energy"] = max(0, k["energy"] - 4)
        got = 0
        for _ in range(2):
            log = w.make("log", wet=0.45)
            if hold(log):
                got += 1
            else:
                w.put(log, *(w.free_spot(me.x, me.y, 2) or (me.x, me.y)))
        return True, "I chop wood. Two logs! They are fresh and still a little wet. They should dry in the woodpile.", {}
    if v == "light":
        thing = carried(me, o) or here
        if thing is None:
            return False, f"There is no {o}.", {}
        if not carried(me, "matches"):
            return False, "I need the matches.", {}
        if o in ("fireplace", "stove") and thing.get("fuel", 0) <= 0:
            return False, f"There is no wood in {_the(o)}.", {}
        thing["lit"] = True
        w.touch(thing)
        info["lit"] = o
        return True, {"fireplace": "I strike a match and light the fire. It crackles. The room will get warm.",
                      "stove": "I strike a match and light the stove. Now it gets hot.",
                      "lamp": "I light the lamp. Now I can see.", "candle": "I light the candle. It glows."}[o], info
    if v in ("cook", "bake", "brew"):
        return _wait_for_cooking(w, me, p, hold, release)
    if v == "make":
        return _craft(w, me, o, hold, release)
    if v == "sleep":
        me.sleeping = True
        if here and here["kind"] == "bed":
            me.x, me.y = me.x, me.y
        return True, "I lie down in my bed and close my eyes.", {"slept": True}
    if v == "rest":
        k["rest"] = min(100, k["rest"] + 12)
        return True, f"I sit on {_the(here['kind']) if here else 'the ground'} and rest.", {}
    if v == "warm":
        k["warmth"] = min(100, k["warmth"] + 20)
        me.wet = max(0.0, me.wet - 0.3)
        return True, "I sit by the fire. It is warm. I feel cosy." if (here and here.get("lit")) \
            else "The fire is out. It is cold here.", {}
    if v == "wash":
        if not p.working:
            me.activity = "taking a bath"
        p.working += 1
        if p.working < 12:
            return None
        me.activity = ""
        k["clean"] = 100.0
        k["fun"] = min(100, k["fun"] + 10)
        me.wet = 1.0
        return True, "I take a bath. Splash! Now I am clean, but I am all wet. I need a towel.", {}
    if v == "dry" and o and o[0].isupper():
        b = w.being(o)
        if b is None:
            return False, "Nobody is here.", {}
        b.wet = 0.0
        b.needs["warmth"] = min(100, b.needs["warmth"] + 10)
        return True, f"I dry {b.name} with the soft towel. Now {b.name} is dry and warm.", {"dried": b.name}
    if v == "dry":
        me.wet = 0.0
        k["warmth"] = min(100, k["warmth"] + 8)
        return True, "I dry myself with the soft towel. Now I am dry.", {}
    if v == "look":
        if o == "mirror":
            info["mirror"] = True
            return True, f"I look in the mirror. I see someone looking back. That is me! I am {me.name}.", info
        if o == "window":
            return True, f"I look out of the window. The weather is {w.weather}.", {}
        if o == "telescope":
            if w.phase != "night" and w.time_of_day() != "evening":
                return True, "I look through the telescope. It is daytime: I see the hills far away.", {}
            info["stars"] = True
            k["fun"] = min(100, k["fun"] + 20)
            return True, "I look through the telescope at the stars. They twinkle. The moon is bright.", info
        if here:
            return True, f"I look at {w.describe_thing(here)}.", {"looked": here["kind"]}
        return True, w.perceive(me=me), {}
    if v == "listen":
        heard = w.hearing(me)
        return True, ("I listen. I hear " + _and(heard) + ".") if heard else "I listen. It is quiet.", {}
    if v == "explore":
        place = w.place_of(me.x, me.y)
        k["fun"] = min(100, k["fun"] + 10)
        return True, f"I explore {where(place).split(' ', 1)[-1] if place else 'around'}. " + \
            PLACES.get(place, "").capitalize().split(",")[0] + ".", {"explored": place}
    if v == "fish":
        if not carried(me, "fishing rod"):
            return False, "I need a fishing rod.", {}
        if not p.working:
            me.activity = "fishing"
        p.working += 1
        if p.working < 20:
            return None
        me.activity = ""
        fish = w.nearest("fish", (me.x, me.y))
        if fish and abs(fish["x"] - me.x) + abs(fish["y"] - me.y) < 8 and w.rng.random() < 0.6:
            w.remove(fish)
            hold(w.make("raw fish")) or w.put(w.make("raw fish"), me.x, me.y)
            return True, "I catch a fish! It wriggles and splashes.", {"caught": True}
        return True, "I wait and wait, but no fish bites. Maybe next time.", {}
    if v == "swim":
        if w.outdoor_temperature() < 18:
            me.wet = 1.0
            k["warmth"] = max(0, k["warmth"] - 25)
            return True, "I step into the pond. Brr! The water is far too cold.", {}
        me.wet = 1.0
        k["fun"] = min(100, k["fun"] + 30)
        k["clean"] = min(100, k["clean"] + 20)
        return True, "I swim in the pond. The water is cool. A duck swims by.", {}
    if v == "paint":
        if not p.working:
            me.activity = "painting"
        p.working += 1
        if p.working < 14:
            return None
        me.activity = ""
        data = art.painting(w.rng, w.place_of(me.x, me.y), w.season, w.time_of_day(), w.weather, " ".join(w.feelings(me)))
        e = w.make("painting")
        c = w.create("painting", me.name, data, art.default_title("painting", data, w.rng), e)
        hold(e) or w.put(e, me.x, me.y)
        k["fun"] = min(100, k["fun"] + 25)
        return True, f"I paint a picture of the {data['place']}.", {"created": c}
    if v == "compose":
        if not p.working:
            me.activity = "playing the piano"
        p.working += 1
        w.sounds.append(("piano music", me.x, me.y, 12))
        if p.working < 18:
            return None
        me.activity = ""
        data = art.melody(w.rng, " ".join(w.feelings(me)), w.season)
        e = w.make("recording")
        c = w.create("music", me.name, data, art.default_title("music", data, w.rng), e)
        hold(e) or w.put(e, me.x, me.y)
        k["fun"] = min(100, k["fun"] + 25)
        return True, "I play a little song on the piano and record it.", {"created": c}
    if v == "sculpt":
        mat = carried(me, o)
        if mat is None:
            return False, f"I need {_a(o)}.", {}
        if not p.working:
            me.activity = "sculpting"
        p.working += 1
        if p.working < 16:
            return None
        me.activity = ""
        release(mat)
        data = art.sculpture(w.rng, {"log": "wood"}.get(o, o))
        spot = w.free_spot(me.x, me.y, 2) or (me.x, me.y)
        e = w.add("sculpture", *spot)
        c = w.create("sculpture", me.name, data, art.default_title("sculpture", data, w.rng), e)
        return True, f"I shape {_the(o)} into a sculpture.", {"created": c}
    if v == "write":
        paper = carried(me, "paper")
        if paper is None:
            return False, "I need paper.", {}
        release(paper)
        e = w.make("poem")
        c = w.create("poem", me.name, {}, "", e)
        hold(e)
        return True, "I write on the paper with the pencil.", {"created": c, "write": True}
    if v == "build":
        if o == "snowman":
            spot = w.free_spot(me.x, me.y, 2) or (me.x, me.y)
            e = w.add("snowman", *spot)
            c = w.create("building", me.name, {"what": "snowman", "place": w.place_of(*spot)}, "Snowman", e)
            k["fun"] = min(100, k["fun"] + 30)
            k["warmth"] = max(0, k["warmth"] - 10)
            return True, "I roll the snow into big balls and build a snowman!", {"created": c}
        bh = carried(me, "birdhouse")
        if bh is None:
            return False, "I don't have a birdhouse.", {}
        release(bh)
        spot = w.free_spot(me.x, me.y, 2) or (me.x, me.y)
        w.put(bh, *spot)
        c = w.create("building", me.name, {"what": "birdhouse", "place": w.place_of(*spot)}, "Birdhouse", bh)
        return True, "I put up the birdhouse. Birds can live in it.", {"created": c}
    if v == "fly":
        if w.weather in ("windy", "clear", "cloudy") and not w.indoors(me.x, me.y):
            k["fun"] = min(100, k["fun"] + 30)
            return True, "I fly my kite. The wind lifts it high into the sky!" if w.weather == "windy" else \
                "I run with my kite. It flies a little.", {}
        return False, "There is no wind for the kite.", {}
    if v == "go":
        b = w.being(o) if o and o[0].isupper() else None
        if b:
            return True, f"I go to {w.describe(b)}.", {"near": b.name}
        return True, f"I go to the {o}." if o else "I go.", {}
    return False, f"I don't know how to {v}.", {}


def _harvest(w: World, me: Being, plant: dict, hold) -> tuple:
    if plant.get("stage", 0) < 4:
        return False, f"The {plant['crop']} is not ripe yet. It is {STAGE(plant)}.", {}
    crop = plant["crop"]
    n = {"carrot": 2, "potato": 3, "tomato": 3, "pumpkin": 1, "beans": 2, "wheat": 2, "mint": 2}.get(crop, 1)
    w.remove(plant)
    kept = 0
    for _ in range(n):
        item = w.make(crop)
        if hold(item):
            kept += 1
        else:
            w.put(item, *(w.free_spot(me.x, me.y, 2) or (me.x, me.y)))
    seed = KINDS[crop].get("grows_from")
    if seed:
        tin = w.nearest("seed tin", (36, 17))
        if tin is not None:
            tin.setdefault("items", []).append(w.make(seed))     # seeds saved for next time
    me.needs["clean"] = max(0, me.needs["clean"] - 6)
    many = f"{n} {crop}s" if crop not in ("beans", "wheat") and n > 1 else (noun(crop) if n == 1 else f"some {crop}")
    return True, f"I harvest the {crop}. I get {many}!" + (" My hands are full, so some are on the ground." if kept < n else ""), \
        {"harvested": crop}


def STAGE(plant: dict) -> str:
    from ..ontology import STAGE_NAMES
    return STAGE_NAMES[min(4, int(plant.get("stage", 0)))]


def _put_in(w: World, me: Being, e: dict, dest: dict, release) -> tuple:
    dk, ek = dest["kind"], e["kind"]
    the_e, the_d = _the(ek), _the(dk)
    if dk in ("fireplace", "stove") and KINDS[ek].get("fuel"):
        if e.get("wet", 0) > 0.3:
            return False, f"I put {the_e} in {the_d}, but it is too wet. It hisses and smokes. I take it out again.", {}
        release(e)
        dest["fuel"] = min(KINDS[dk]["fuel_cap"] * 420, dest.get("fuel", 0) + KINDS[ek]["fuel"])
        w.touch(dest)
        return True, f"I put {the_e} in {the_d}.", {}
    if dk == "stove" and ek in ("pot", "kettle"):
        release(e)
        e["on"] = dest["id"]
        w.put(e, dest["x"], dest["y"])
        e["on"] = dest["id"]
        return True, f"I put {the_e} on the stove.", {}
    if ek == "water" or dk in ("sink",):
        return False, "I can't put that there.", {}
    cap = KINDS[dk].get("container")
    if not cap:
        if dk == "compost bin":
            cap = 30
        else:
            return False, f"I can't put things in {the_d}.", {}
    items = dest.setdefault("items", [])
    if len(items) >= cap:
        return False, f"{_cap(the_d)} is full.", {}
    if dk == "pot" and ek not in SOUP_THINGS | {"berries", "egg", "honey"}:
        return False, f"{_cap(the_e)} doesn't go in the pot.", {}
    if dk == "oven" and ek not in ("dough", "apple", "potato", "raw fish"):
        return False, f"{_cap(the_e)} doesn't go in the oven.", {}
    release(e)
    if dk == "compost bin":
        w.touch(dest)
        dest["compost"] = dest.get("compost", 0) + 1
        return True, f"I put {the_e} in the compost. It will turn into good soil.", {}
    items.append(e)
    if dk == "oven":
        dest["bake"], dest["baked"] = 0.0, False
    w.touch(dest)
    extra = {"pantry": " It will stay fresh in the cool.", "woodpile": " It will dry out there."}.get(dk, "")
    return True, f"I put {the_e} in {the_d}.{extra}", {}


def _wait_for_cooking(w: World, me: Being, p: Plan, hold, release) -> tuple | None:
    """Everything is in place: watch it cook, then take the result."""
    v, o = p.goal.verb, p.goal.obj
    p.working += 1
    me.activity = {"cook": "cooking", "bake": "baking", "brew": "making tea"}[v]
    stove = _stove(w)
    if stove is not None and not stove.get("lit"):
        me.activity = ""
        return False, "The stove has gone out. It needs more wood.", {"stove_out": True}
    if v == "cook":
        pot = _on_stove(w, "pot")
        want = o or "soup"
        if pot is None:
            me.activity = ""
            return False, "The pot isn't on the stove.", {}
        if any(i["kind"] == want for i in pot.get("items", [])):
            me.activity = ""
            return True, f"The {want} is ready! It smells good.", {"cooked": want}
        if any(i["kind"] == "burnt food" for i in pot.get("items", [])):
            me.activity = ""
            return False, "Oh no, it burnt.", {}
        if p.working == 1:
            return None if pot.get("steam") else None
        return None if p.working < 720 else (False, "It is taking too long.", {})
    if v == "bake":
        oven = w.nearest("oven", (27, 22))
        item = next((i for i in oven.get("items", []) if i["kind"] == o), None)
        if item:
            oven["items"].remove(item)
            hold(item) or w.put(item, me.x, me.y)
            oven["baked"] = False
            w.touch(oven)
            me.activity = ""
            return True, f"I take {noun(o)} out of the oven. It is hot and smells wonderful!", {"baked": o}
        if any(i["kind"] == "burnt food" for i in oven.get("items", [])):
            me.activity = ""
            return False, "Oh no, it burnt in the oven.", {}
        return None if p.working < 900 else (False, "It is taking too long.", {})
    kettle = _on_stove(w, "kettle")
    if kettle is None:
        me.activity = ""
        return False, "The kettle isn't on the stove.", {}
    if kettle.get("temp", 0) >= 95:
        me.activity = ""
        if o == "water":
            return True, "The water is boiling. The kettle whistles.", {}
        cup, mint = carried(me, "cup"), carried(me, "mint")
        if not cup or not mint:
            return False, "I need a cup and some mint for tea.", {}
        release(cup)
        release(mint)
        kettle["water"] = max(0.0, kettle.get("water", 0) - 0.25)
        hold(w.make("tea", temp=85.0))
        return True, "I pour hot water on the mint in my cup. Now I have a cup of tea. It steams.", {"brewed": True}
    return None if p.working < 720 else (False, "The water won't boil.", {})


def _craft(w: World, me: Being, product: str, hold, release) -> tuple:
    r = _recipe(product)
    if not r:
        return False, f"I don't know how to make {_a(product)}.", {}
    _, ings, station = r
    used = []
    for k in ings:
        e = next((c for c in me.carrying if c["kind"] == k and c not in used), None)
        if e is None:
            return False, f"I need {_a(k)}.", {}
        used.append(e)
    for e in used:
        release(e)
    made = w.make(product)
    hold(made) or w.put(made, me.x, me.y)
    how = {"flour": "I grind the wheat with the quern. It turns into soft flour.",
           "dough": "I mix the flour and the egg with water on the table. Now it is dough.",
           "kite": "I make a kite from paper and a stick.", "birdhouse": "I make a birdhouse from the log.",
           "bouquet": "I put the flowers together into a bouquet."}.get(product, f"I make {_a(product)}.")
    return True, how, {"made": product}


def face(w: World, x: int, y: int, me: Being | None = None):
    a = me or w.ada
    if (x, y) != (a.x, a.y):
        a.facing = _facing(a.x, a.y, x, y)
