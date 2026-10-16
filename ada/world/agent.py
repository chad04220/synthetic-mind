"""How the synth acts: words become deeds.

Each time it is free to choose, its brain writes an intention ("I eat the apple.", "I go fishing
at the dock.", "I ask the Oracle why the sky is blue."). `parse()` turns it into a Goal (a verb and
its object); if the world can make sense of it, the synth carries it out, and its own words have
moved its body.

While its words can't yet do that, its needs and purposes decide (`drives()`): hunger, thirst,
tiredness, cold, loneliness, boredom, curiosity, the villagers' quests, an empty purse, the farm
that needs tending. Each proposes something sensible, with a reason ("I am hungry."). Those choices
go into its journal next to what it sensed and how it turned out, so the Academy teaches its
brain to make them itself. The share of actions that come from its own words is the clearest
sign that its language is grounded.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

from ..ontology import BAKING_STATIONS, BUILDS, COOKING_STATIONS, KINDS, NPCS, PLACES, RECIPES, SCULPT_MATERIALS
from . import art
from .sim import DOCK, SOIL, WATER, World, _facing, where

VERBS = {
    "eat": ["eat", "eats", "ate", "eating", "taste", "munch"],
    "drink": ["drink", "drinks", "sip", "drinking"],
    "go": ["go", "goes", "walk", "run", "visit", "head", "travel", "return", "come", "move"],
    "take": ["take", "pick", "grab", "get", "collect", "gather", "fetch", "find"],
    "drop": ["drop", "put", "leave"],
    "give": ["give", "hand", "offer", "share", "bring"],
    "talk": ["talk", "speak", "chat", "greet", "say", "tell", "visit"],
    "ask": ["ask", "question", "wonder"],
    "read": ["read"],
    "learn": ["learn", "study", "practise", "practice", "school"],
    "play": ["play", "kick", "throw", "bounce", "dance", "swing"],
    "pet": ["pet", "stroke", "hug", "cuddle", "feed"],
    "smell": ["smell", "sniff"],
    "plant": ["plant", "sow"],
    "water": ["water"],
    "fill": ["fill"],
    "harvest": ["harvest", "reap"],
    "chop": ["chop", "cut"],
    "make": ["make", "craft", "create"],
    "build": ["build", "construct"],
    "sculpt": ["sculpt", "carve", "sculpture"],
    "compose": ["compose", "record", "sing", "song", "melody"],
    "write": ["write", "poem", "story"],
    "listen": ["listen", "hear"],
    "admire": ["admire", "enjoy", "appreciate"],
    "light": ["light", "kindle", "start"],
    "cook": ["cook", "roast", "grill", "fry"],
    "bake": ["bake"],
    "buy": ["buy", "purchase"],
    "sell": ["sell", "trade"],
    "look": ["look", "watch", "gaze", "observe", "see"],
    "sleep": ["sleep", "nap"],
    "warm": ["warm"],
    "explore": ["explore", "wander", "roam", "discover", "climb"],
    "wait": ["wait", "rest", "sit", "stay", "relax"],
    "fish": ["fish", "fishing", "catch"],
    "mine": ["mine", "dig", "mining"],
    "milk": ["milk"],
    "paint": ["paint", "painting", "draw"],
    "swim": ["swim", "swimming", "bathe"],
    "fly": ["fly", "flying"],
}
_VERB_OF = {}
for _v, _ws in VERBS.items():
    for _w in _ws:
        _VERB_OF.setdefault(_w, _v)
_OBJECTS = sorted(list(KINDS) + ["water", "fire", "stars", "sky", "oracle", "friend", "you", "tree"],
                  key=len, reverse=True)
_PEOPLE = {n.lower(): n for n in NPCS}
SELLERS = {k: n for n, p in NPCS.items() for k in p["sells"]}


@dataclass
class Goal:
    verb: str
    obj: str = ""
    extra: str = ""          # e.g. the question for the Oracle, who receives a gift
    text: str = ""           # the intention as a sentence
    reason: str = ""         # why (for choices its needs made)
    source: str = "self"     # self: its own words | needs | you


@dataclass
class Plan:
    goal: Goal
    target: tuple | None = None    # ("entity", id) | ("tile", (x, y), adjacent) | ("being", name) | None
    route: list = field(default_factory=list)
    ticks: int = 0
    perception: str = ""
    wellbeing_before: float = 0.0


# ====================================================================== words -> goals
def _find_obj(rest: str) -> str:
    for name, real in _PEOPLE.items():
        if re.search(rf"\b{name}\b", rest):
            return real
    for o in _OBJECTS:
        if re.search(rf"\b{re.escape(o)}(?:s|es)?\b", rest):
            return o
    for p in sorted(PLACES, key=len, reverse=True):
        if re.search(rf"\b{p}\b", rest):
            return p
    return ""


def parse(text: str) -> Goal | None:
    """Understand an intention, if it can be understood."""
    t = text.lower().strip()
    t = re.sub(r"[^a-z' ]+", " ", t)
    words = t.split()
    if not words:
        return None
    verbs = [(i, _VERB_OF[w]) for i, w in enumerate(words) if w in _VERB_OF]
    if not verbs:
        return None
    i, verb = verbs[0]
    # "go and eat the apple" / "go fishing": the second verb is the real one
    if verb in ("go", "talk") and len(verbs) > 1 and verbs[1][1] not in ("go",):
        i, verb = verbs[1]
    rest = " ".join(words[i + 1:])
    # "water" is both a verb and a thing: "water the sprout" vs "drink water"
    if verb == "water" and i > 0 and words[i - 1] not in ("i", "will", "to", "and", "then", "now"):
        verb = "drink"
    if verb == "fish" and words[i] == "fish" and i > 0 and words[i - 1] in ("the", "a", "my", "some"):
        verb = "take"                                   # "eat the fish" is handled by eat; "get the fish"
    obj = _find_obj(rest)
    if obj == "you":
        obj = "friend"
    if verb == "give":   # "give the apple to Mira": the thing, then who receives it
        item = next((o for o in _OBJECTS if o in KINDS and re.search(rf"\b{re.escape(o)}s?\b", rest)), "")
        who = next((real for name, real in _PEOPLE.items() if re.search(rf"\b{name}\b", rest)), "")
        who = who or ("friend" if re.search(r"\b(friend|you)\b", rest) else "")
        return Goal("give", item, who, text.strip())
    extra = ""
    if verb == "ask":
        m = re.search(r"\b(?:oracle|her|him|them|it)\b\s*(.*)", rest)
        extra = (m.group(1) if m else rest).strip()
        obj = obj if obj in _PEOPLE.values() else "oracle"
    if verb == "look" and obj in ("stars", "sky", ""):
        obj = "telescope" if obj else ""
    if verb == "play" and words[i] == "swing":
        obj = "swing"
    if verb == "make" and obj == "" and "snow" in rest:
        obj = "snowman"
    if verb == "fly" and not obj:
        obj = "kite"
    return Goal(verb, obj, extra, text.strip())


def say(goal: Goal) -> str:
    """The canonical sentence for a goal: what the synth learns to say before it does it."""
    v, o = goal.verb, goal.obj
    the = _the(o)
    return {
        "eat": f"I eat {the}.", "drink": "I drink water." if o in ("", "water", "well") else f"I drink {the}.",
        "go": f"I go to {o if o in NPCS else ('my friend' if o == 'friend' else 'the ' + o)}.",
        "take": f"I pick up {the}.", "drop": f"I put down {the}.",
        "give": f"I give {the} to {'my friend' if goal.extra in ('', 'friend', 'my friend') else goal.extra}.",
        "talk": f"I talk to {'my friend' if o == 'friend' else o}.",
        "ask": (f"I ask the Oracle: {goal.extra[:1].lower() + goal.extra[1:]}" if goal.extra else "I ask the Oracle a question")
               + ("" if goal.extra.endswith("?") else "?"),
        "read": f"I read {the}.", "learn": "I go to school and learn new words.",
        "play": {"music box": "I play the music box.", "piano": "I play the piano.",
                 "swing": "I play on the swing."}.get(o, f"I play with {the}."),
        "pet": f"I pet {the}.", "smell": f"I smell {the}.",
        "plant": f"I plant {_a(o) if o in KINDS else 'a seed'} in the field.",
        "water": "I water the sprout.", "fill": "I fill the bucket with water.", "harvest": f"I harvest {the if o else 'the crops'}.",
        "chop": "I chop wood from a tree.", "make": f"I make {_a(o)}.", "light": "I light the fire.",
        "cook": f"I cook {the}.", "bake": f"I bake {the if o else 'bread'} in the oven.",
        "buy": f"I buy {_a(o)}.", "sell": f"I sell {the} at the market.",
        "look": "I look at the stars through the telescope." if o == "telescope" else "I look around.",
        "sleep": "I go to bed and sleep.", "warm": "I warm myself by the fire.",
        "explore": f"I explore the {o}." if o else "I explore.", "wait": "I rest for a while.",
        "fish": "I go fishing at the dock.", "mine": f"I mine {'crystals' if o == 'crystal' else 'ore'} in the mine.",
        "milk": "I milk the cow.", "paint": "I paint a picture at the easel.", "swim": "I swim in the lake.",
        "fly": "I fly my kite in the meadow.",
        "build": f"I build {_a(o) if o else 'something'} with my hammer.",
        "sculpt": f"I carve a sculpture out of {o or 'stone'}.", "compose": "I play the piano and record a song.",
        "write": "I write a poem.", "listen": "I listen to a recording.", "admire": f"I admire {the if o else 'the art'}.",
    }.get(v, f"I {v} {the}.")


def _the(o: str) -> str:
    if not o:
        return "it"
    if o in NPCS or o == "friend":
        return o if o in NPCS else "my friend"
    n = KINDS.get(o, {}).get("noun", "a " + o)
    for art in ("an ", "a ", "some "):
        if n.startswith(art):
            return "the " + n[len(art):]
    return n


def _a(o: str) -> str:
    return KINDS.get(o, {}).get("noun", ("an " if o[:1] in "aeiou" else "a ") + o)


def _recipe(product: str):
    return next(((p, ing, st) for p, ing, st in RECIPES if p == product), None)


def _has(carrying: list[str], needed: list[str]) -> bool:
    left = list(carrying)
    for k in needed:
        if k not in left:
            return False
        left.remove(k)
    return True


# ====================================================================== needs -> goals
QUESTIONS = ["What is the sun?", "Why is the sky blue?", "What are stars?", "Why does it rain?",
             "How do plants grow?", "What is a word?", "Where does bread come from?", "What is the moon?",
             "Why do birds fly?", "What is fire?", "How do fish breathe?", "What is snow?",
             "Why do we sleep?", "What is a friend?", "What is music?", "How does a book hold ideas?",
             "Where does the river go?", "Why are mountains cold on top?", "How do bees make honey?",
             "What are crystals made of?", "Why do leaves change colour in autumn?", "What is a rainbow?"]
FOODS = ["pumpkin pie", "bread", "grilled fish", "cooked mushroom", "fried egg", "roasted carrot", "honey",
         "apple", "carrot", "berry"]


def drives(w: World, rng: random.Random, asked_recently: bool, unread: bool, me=None) -> Goal:
    """A sensible thing to do now, chosen from a mind's needs and purposes, with a reason.

    The same for the synth and for every villager; villagers also have their work."""
    a = me or w.ada
    n = a.needs
    synth = a is w.ada
    carrying = [e["kind"] for e in a.carrying]
    food = [k for k in FOODS if k in carrying]
    lit = w.nearest(COOKING_STATIONS, (a.x, a.y), where=lambda e: e.get("lit") or e["kind"] == "stove")
    opts: list[tuple[float, Goal]] = []

    def add(score, verb, obj="", reason="", extra=""):
        g = Goal(verb, obj, extra, reason=reason, source="needs")
        g.text = say(g)
        opts.append((score, g))

    hunger = 100 - n["energy"]
    if n["energy"] < 60:
        if food:
            add(hunger * 1.4, "eat", food[0], "I am hungry.")
        else:
            e = w.nearest(FOODS, (a.x, a.y))
            if e and abs(e["x"] - a.x) + abs(e["y"] - a.y) < 40:
                add(hunger * 1.2, "eat", e["kind"], "I am hungry.")
        if a.coins >= KINDS["bread"]["price"]:
            add(hunger, "buy", "bread", "I am hungry and I have coins.")
        raw = next((k for k in carrying if KINDS[k].get("cooked")), None)
        if raw:
            add(hunger * 1.1, "cook", raw, f"I am hungry. {_cap(_the(raw))} tastes better cooked.")
    if n["water"] < 60:
        drink = next((k for k in ("water bucket", "milk") if k in carrying), "water")
        add((100 - n["water"]) * 1.3, "drink", drink, "I am thirsty.")
    if n["rest"] < 30:
        add((100 - n["rest"]) * 1.2, "sleep", "bed", "I am tired.")
    if n["warmth"] < 50:
        if lit:
            add((100 - n["warmth"]) * 1.2, "warm", "fire pit", "I am cold.")
        elif "wood" in carrying:
            add((100 - n["warmth"]) * 1.1, "light", "fire pit", "I am cold. Fire is warm.")
        else:
            add((100 - n["warmth"]), "go", "home", "I am cold. My home is warm.")
    if n["company"] < 60:
        if w.visitor:
            add((100 - n["company"]) * 1.3, "talk", "friend", "I feel lonely. My friend is here.")
        others = [b for b in [w.ada] + list(w.people.values()) if b is not a and not b.sleeping and b.engaged is None]
        if others:
            b = min(others, key=lambda b: abs(b.x - a.x) + abs(b.y - a.y) - b.friends.get(a.name, 0) / 10)
            add((100 - n["company"]), "talk", b.name, f"I want to talk to {b.name}.")
        add((100 - n["company"]) * 0.5, "pet", rng.choice(["cat", "dog", "chicken", "sheep"]), "I want an animal friend.")
    if n["fun"] < 60:
        boredom = 100 - n["fun"]
        add(boredom * 0.7, "play", rng.choice(["ball", "music box", "piano", "swing"]), "I am bored.")
        add(boredom * 0.5, "smell", "flower", "I want something nice.")
        add(boredom * 0.6, "paint", "easel", "I want to make something beautiful.")
        if "fishing rod" in carrying:
            add(boredom * 0.9, "fish", "", "Fishing is fun and calm.")
        if "kite" in carrying and w.weather in ("windy", "clear"):
            add(boredom * 1.0, "fly", "kite", "It is a good day for my kite.")
        if w.season == "summer" and w.weather == "clear":
            add(boredom * 0.6, "swim", "", "It is hot. The lake is cool.")
        if w.season == "winter" and w.weather in ("snow", "clear"):
            add(boredom * 0.8, "make", "snowman", "There is snow! I can build a snowman.")
        creative_options(w, a, add, carrying, boredom, rng)
    if not synth:
        return _villager_drives(w, rng, a, opts, add)
    # ---- quests: the villagers need things
    for q in w.quests:
        need = q["count"] - q["got"]
        have = carrying.count(q["want"])
        if have >= 1:
            add(55, "give", q["want"], f"{q['giver']} needs {_a(q['want'])}. I have one.", q["giver"])
        else:
            sub = _how_to_get(w, q["want"], carrying)
            if sub:
                add(30 + 4 * need, *sub, reason=f"{q['text']} I want to help.")
    # ---- money
    valuables = [k for k in carrying if KINDS[k].get("value", 0) >= 3 and k not in ("fishing rod", "pickaxe", "axe", "bucket")
                 and not any(q["want"] == k for q in w.quests)]
    if a.coins < 3 and valuables:
        add(26, "sell", valuables[0], "My purse is nearly empty. Juniper buys things.")
    # ---- curiosity and purpose
    unseen = [p for p in w.anchors if p not in w.visited and p not in ("barn", "boathouse")]
    if unseen:
        add(32, "go", rng.choice(unseen), "I wonder what is there.")
    if unread:
        add(22, "read", "book", "I want to learn something.")
    add(18, "learn", "blackboard", "I want to learn new words at school.")
    if not asked_recently:
        add(22, "ask", "oracle", "I have a question.", rng.choice(QUESTIONS))
    if w.time_of_day(600) in ("evening",) or w.phase == "night":
        add(25, "look", "telescope", "The stars will come out soon.")
    loner = min(NPCS, key=lambda p: w.friends.get(p, 0))
    if not w.people[loner].sleeping:
        add(14, "talk", loner, f"I want to be friends with {loner}.")
    # ---- the farm
    seeds = [k for k in carrying if KINDS[k].get("grows")]
    if seeds:
        add(30, "plant", seeds[0], "Seeds grow into food.")
    elif not w.nearest("sprout", (a.x, a.y)) and w.nearest("seed", (a.x, a.y)):
        add(14, "take", "seed", "I can plant a seed.")
    sprout = w.nearest("sprout", (a.x, a.y), where=lambda e: not e.get("watered"))
    if sprout:
        add(28 if "water bucket" in carrying else 16, "water", "sprout", "The sprout needs water.")
    ripe = w.nearest(("wheat", "carrot", "pumpkin"), (a.x, a.y), where=lambda e: w.terrain[e["y"]][e["x"]] == SOIL)
    if ripe:
        add(30, "harvest", ripe["kind"], f"The {ripe['kind']} is ready.")
    for raw in ("wheat", "pumpkin"):
        if raw in carrying:
            add(28, "bake", raw, f"{_cap(_the(raw))} can be baked.")
    if "bucket" in carrying and not any(k in carrying for k in ("milk",)):
        add(12, "milk", "cow", "The cow gives milk.")
    # ---- making things
    for product, ingredients, _st in RECIPES:
        if product not in carrying and _has(carrying, ingredients):
            add(24, "make", product, f"I have {' and '.join(_a(k) for k in sorted(set(ingredients)))}.")
    if "pickaxe" in carrying:
        add(16, "mine", rng.choice(["ore", "crystal"]), "The mine has ore and crystals.")
    if "fishing rod" not in carrying and n["fun"] < 70:
        add(8, "take", "fishing rod", "I want to go fishing.")
    add(10, "explore", rng.choice(list(w.anchors)), "I want to explore.")
    add(5, "wait", "", "I want to rest a little.")
    weights = [max(0.1, s) ** 2 for s, _ in opts]
    return rng.choices([g for _, g in opts], weights)[0]


WORK = {   # what each villager's work is, in their own words
    "baker": ("I bake bread for the village.", "Mira's oven needs tending."),
    "librarian": ("I sort the books in the library.", "The books need care."),
    "toolmaker and smith": ("I make tools at my forge.", "People need good tools."),
    "merchant": ("I look after my market stall.", "Customers will come."),
    "fisher": ("I go fishing at the dock.", "The fish are biting."),
    "teacher": ("I prepare a lesson at the school.", "Tomorrow's lesson must be good."),
    "child who loves to play": ("I play in the park.", "Playing is the best!"),
}


# What each villager loves to make in their free time.
CRAFTS = {"baker": "paint", "librarian": "write", "toolmaker and smith": "build", "merchant": "compose",
          "fisher": "compose", "teacher": "write", "child who loves to play": "sculpt"}


def creative_options(w: World, a, add, carrying: list[str], boredom: float, rng: random.Random, favourite: str = ""):
    """Making things: painting, music, sculpture, building, writing; and enjoying what others made."""
    bonus = lambda verb: 1.8 if verb == favourite else 1.0  # noqa: E731
    add(boredom * 0.55 * bonus("paint"), "paint", "easel", "I want to paint what I see.")
    add(boredom * 0.5 * bonus("compose"), "compose", "piano", "A melody is singing in my head.")
    mat = next((k for k in SCULPT_MATERIALS if k in carrying), "")
    if "chisel" in carrying and mat:
        add(boredom * 0.7 * bonus("sculpt"), "sculpt", mat, f"I can carve this {mat} into something beautiful.")
    if "hammer" in carrying:
        what = next((b for b, ing in BUILDS.items() if _has(carrying, ing)), "")
        if what:
            add(boredom * 0.7 * bonus("build"), "build", what, f"I have what I need to build {_a(what)}.")
    if "paper" in carrying:
        add(boredom * 0.6 * bonus("write"), "write", "poem", "I have words to write down.")
    if "recording" in carrying:
        add(boredom * 0.3, "listen", "recording", "I want to hear my song again.")
    if any(e["kind"] in ("sculpture", "painting", "fountain", "flower bed") and e.get("work") for e in w.entities.values()):
        add(boredom * 0.3, "admire", "", "I want to see what my neighbours made.")


def _villager_drives(w: World, rng: random.Random, a, opts, add) -> Goal:
    """A villager's purposes beyond its needs: its work by day, making things, a walk, a chat, home at night."""
    tod = w.time_of_day(600)
    working = tod in ("morning", "noon", "afternoon")
    add(60 if working else 20, "work", "", WORK.get(a.role, ("I do my work.", ""))[1])
    creative_options(w, a, add, [e["kind"] for e in a.carrying], max(30.0, 100 - a.needs["fun"]), rng,
                     CRAFTS.get(a.role, ""))
    add(16, "go", rng.choice(["village", "park", "market", "meadow", "lake"]), "I want a little walk.")
    if a.carrying:
        add(18, "drop", a.carrying[0]["kind"], "I put this away.")
    if tod == "evening":
        add(40, "work", "", "The day is ending. I go back to my place.")
    weights = [max(0.1, s) ** 2 for s, _ in opts]
    return rng.choices([g for _, g in opts], weights)[0]


def _how_to_get(w: World, kind: str, carrying: list[str]):
    """(verb, obj) that would get this kind of thing, if there is a simple way."""
    if w.nearest(kind, (w.ada.x, w.ada.y)) and KINDS[kind].get("portable"):
        return ("take", kind)
    if kind == "raw fish":
        return ("fish", "") if "fishing rod" in carrying else ("take", "fishing rod")
    if kind in ("ore", "crystal"):
        return ("mine", kind) if "pickaxe" in carrying else ("take", "pickaxe")
    if kind == "milk":
        return ("milk", "cow") if "bucket" in carrying else ("take", "bucket")
    if kind in ("bread", "pumpkin pie") and kind.split()[0] in carrying:
        return ("bake", "wheat" if kind == "bread" else "pumpkin")
    r = _recipe(kind)
    if r and _has(carrying, r[1]):
        return ("make", kind)
    if kind in SELLERS and w.ada.coins >= KINDS[kind].get("price", 99):
        return ("buy", kind)
    return None


# ====================================================================== goals -> plans
def plan(w: World, g: Goal, me=None) -> tuple[Plan | None, str]:
    """Where to go for a goal. Returns (plan, '') or (None, why it can't be done)."""
    a = me or w.ada
    here = (a.x, a.y)
    carrying = [e["kind"] for e in a.carrying]
    p = Plan(g)
    v, o = g.verb, g.obj

    def ent(kind, where=None):
        e = w.nearest(kind, here, where=where)
        return ("entity", e["id"]) if e else None

    def person(name):
        if name == "friend":
            return ("being", "friend") if w.visitor else None
        if name in (w.ada.name, "synth"):
            return ("being", "synth") if a is not w.ada else None
        return ("being", name) if name in w.people and w.people[name] is not a else None

    def sub(verb, obj, text, reason):
        return plan(w, Goal(verb, obj, text=text, source=g.source, reason=reason), me)

    if v == "work":
        post = w.posts.get(a.name)
        if not post:
            return None, "I have no work to go to."
        p.target = ("tile", post, False)
    elif v == "go":
        if o in w.anchors:
            p.target = ("tile", w.anchors[o], False)
        elif o in NPCS or o in ("friend", w.ada.name):
            p.target = person(o)
        elif o in KINDS:
            p.target = ent(o)
        if not p.target:
            return None, f"I don't know where {o or 'that'} is."
    elif v in ("eat", "drop") and o in carrying:
        p.target = ("tile", here, False)
    elif v in ("eat", "take", "read", "play", "smell", "pet"):
        kind = o or {"read": "book", "play": "ball", "smell": "flower", "pet": "cat"}.get(v, "")
        if kind not in KINDS:
            return None, f"I don't know what {o or 'that'} is."
        if v == "eat" and not KINDS[kind].get("food"):
            return None, f"I can't eat {_the(kind)}."
        if v == "pet" and not KINDS[kind].get("creature"):
            return None, f"I can't pet {_the(kind)}."
        p.target = (ent(kind, lambda e: e["id"] not in w.read_books) if v == "read" else None) or ent(kind)
        if not p.target:
            return None, f"I can't find {_a(kind)}."
    elif v == "drink":
        if o in ("milk", "water bucket") and o in carrying or "water bucket" in carrying and o in ("", "water"):
            p.target = ("tile", here, False)
        else:
            well = w.nearest("well", here)
            water = w.nearest_tile(WATER, here)
            if well and (not water or abs(well["x"] - a.x) + abs(well["y"] - a.y) <= abs(water[0] - a.x) + abs(water[1] - a.y)):
                p.target = ("entity", well["id"])
            elif water:
                p.target = ("tile", water, True)
            else:
                return None, "I can't find any water."
    elif v == "fill":
        if "bucket" not in carrying:
            return None, "I need a bucket first."
        well = w.nearest("well", here)
        p.target = ("entity", well["id"]) if well else ("tile", w.nearest_tile(WATER, here), True)
    elif v in ("talk", "give"):
        names = set(NPCS) | {w.ada.name}
        who = o if o in names or o == "friend" else (g.extra if g.extra in names else "friend")
        if v == "give":
            item = o if o in carrying else (carrying[0] if carrying else "")
            if not item:
                return None, "I have nothing to give."
            if g.extra in names:
                who = g.extra
            g.obj, g.extra = item, (who if who != "friend" else "my friend")
        p.target = person(who)
        if not p.target:
            return None, "My friend is not here." if who == "friend" else f"I don't know {who}."
    elif v == "ask":
        p.target = ent("shrine")
        g.extra = g.extra or random.choice(QUESTIONS)
    elif v == "learn":
        p.target = ent("blackboard")
    elif v == "plant":
        seed = o if o in carrying and KINDS.get(o, {}).get("grows") else next((k for k in carrying if KINDS[k].get("grows")), "")
        if not seed:
            return None, "I need a seed to plant."
        g.obj = seed
        spots = [(x, y) for (x, y) in w.cells.get("farm", []) if w.terrain[y][x] == SOIL and not w.at(x, y)]
        if not spots:
            return None, "The fields are full."
        p.target = ("tile", min(spots, key=lambda s: abs(s[0] - a.x) + abs(s[1] - a.y)), False)
    elif v == "water":
        if "water bucket" not in carrying:
            if "bucket" in carrying:
                return sub("fill", "bucket", "I fill the bucket with water.", "The sprout needs water. I need water in my bucket.")
            return sub("take", "bucket", "I pick up the bucket.", "I need a bucket to carry water.")
        p.target = ent("sprout", lambda e: not e.get("watered")) or ent("sprout")
        if not p.target:
            return None, "There is no sprout to water."
    elif v == "harvest":
        crops = (o,) if o in ("wheat", "carrot", "pumpkin") else ("wheat", "carrot", "pumpkin")
        p.target = ent(crops, lambda e: w.terrain[e["y"]][e["x"]] == SOIL) or ent(crops)
        if not p.target:
            return None, "There is nothing ripe to harvest yet."
    elif v == "chop":
        if "axe" not in carrying:
            return sub("take", "axe", "I pick up the axe.", "I need an axe to chop wood.")
        tree = w.nearest_tile((3, 18), here)
        p.target = ("tile", tree, True)
    elif v == "make":
        if o == "snowman":
            if w.season != "winter":
                return None, "I can only build a snowman when there is snow."
            p.target = ("tile", w.anchors["meadow"] if w.region[a.y][a.x] == "village" else here, False)
        else:
            r = _recipe(o) or next(((pr, ing, st) for pr, ing, st in RECIPES if _has(carrying, ing)), None)
            if not r:
                return None, f"I don't know how to make {_a(o) if o else 'that'}."
            product, ingredients, station = r
            if not _has(carrying, ingredients):
                return None, f"To make {_a(product)} I need {' and '.join(_a(k) for k in ingredients)}."
            g.obj = product
            p.target = ent(station) if station else ("tile", here, False)
    elif v == "light":
        if "wood" not in carrying:
            return None, "I need wood to light a fire."
        p.target = ent("fire pit")
    elif v == "warm":
        p.target = ent("fire pit", lambda e: e.get("lit")) or ent("stove") or ("tile", w.anchors["home"], False)
    elif v == "cook":
        raw = o if o in carrying and KINDS[o].get("cooked") else next((k for k in carrying if KINDS[k].get("cooked")), "")
        if not raw:
            return None, "I have nothing to cook."
        g.obj = raw
        p.target = ent(COOKING_STATIONS, lambda e: e["kind"] == "stove" or e.get("lit"))
        if not p.target:
            return None, "There is no fire to cook on. I need to light the fire pit."
    elif v == "bake":
        raw = o if o in carrying and KINDS[o].get("baked") else next((k for k in carrying if KINDS[k].get("baked")), "")
        if not raw:
            return None, "I need wheat or a pumpkin to bake."
        g.obj = raw
        p.target = ent(BAKING_STATIONS)
    elif v == "buy":
        item = o if o in SELLERS else "bread"
        price = KINDS[item].get("price", 5)
        if a.coins < price:
            return None, f"{_cap(_a(item))} costs {price} coins. I have {a.coins}."
        g.obj, g.extra = item, SELLERS[item]
        p.target = person(SELLERS[item])
    elif v == "sell":
        item = o if o in carrying else next((k for k in carrying if KINDS[k].get("value", 0) >= 1), "")
        if not item:
            return None, "I have nothing to sell."
        g.obj = item
        p.target = person("Juniper")
    elif v == "fish":
        if "fishing rod" not in carrying:
            return sub("take", "fishing rod", "I pick up the fishing rod.", "I need a fishing rod to fish.")
        spot = w.nearest_tile(DOCK, here, need_neighbour_walkable=False)
        p.target = ("tile", spot, False) if spot else ("tile", w.nearest_tile(WATER, here), True)
    elif v == "mine":
        if "pickaxe" not in carrying:
            return sub("take", "pickaxe", "I pick up the pickaxe.", "I need a pickaxe to mine.")
        kind = "crystal cluster" if o == "crystal" else "ore vein"
        p.target = ent(kind, lambda e: e.get("left", 0) > 0) or ent(("ore vein", "crystal cluster"), lambda e: e.get("left", 0) > 0)
        if not p.target:
            return None, "The mine is empty for now. The rock will grow back."
    elif v == "milk":
        if "bucket" not in carrying:
            return sub("take", "bucket", "I pick up the bucket.", "I need a bucket to milk the cow.")
        p.target = ent("cow")
        if not p.target:
            return None, "There is no cow."
    elif v == "paint":
        p.target = ent("easel")
    elif v == "swim":
        water = w.nearest_tile(WATER, w.anchors["lake"])
        p.target = ("tile", water, True)
    elif v == "fly":
        if "kite" not in carrying:
            return None, "I need a kite. I can make one from wood and paper, or buy one from Juniper."
        p.target = ("tile", w.anchors["meadow"], False)
    elif v == "compose":
        p.target = ent("piano")
    elif v == "write":
        if "paper" not in carrying:
            if a.coins >= KINDS["paper"]["price"]:
                return sub("buy", "paper", "I buy a sheet of paper.", "I need paper to write on.")
            return None, "I need paper to write on."
        p.target = ent("book", lambda e: True) and ("tile", here, False)
    elif v == "sculpt":
        mat = o if o in SCULPT_MATERIALS and o in carrying else next((k for k in SCULPT_MATERIALS if k in carrying), "")
        if "chisel" not in carrying:
            return sub("take", "chisel", "I pick up a chisel.", "I need a chisel to sculpt.") if w.nearest("chisel", here) \
                else (None, "I need a chisel. I can make one from wood and ore at the forge.")
        if not mat:
            return None, "I need stone, wood or clay to sculpt."
        g.obj = mat
        p.target = ("tile", here, False)
    elif v == "build":
        if "hammer" not in carrying:
            return sub("take", "hammer", "I pick up a hammer.", "I need a hammer to build.") if w.nearest("hammer", here) \
                else (None, "I need a hammer. I can make one from wood and stone at the forge.")
        what = o if o in BUILDS else next((b for b, ing in BUILDS.items() if _has(carrying, ing)), "")
        if not what:
            return None, "I don't have the materials to build anything. Wood and stone are good to start."
        if not _has(carrying, BUILDS[what]):
            return None, f"To build {_a(what)} I need {' and '.join(_a(k) for k in BUILDS[what])}."
        g.obj = what
        p.target = ("tile", here, False)
    elif v == "listen":
        p.target = ("tile", here, False) if "recording" in carrying else ent("recording") or ent("piano")
    elif v == "admire":
        kinds = (o,) if o in ("painting", "sculpture", "fountain", "flower bed") else ("sculpture", "painting", "fountain", "flower bed")
        p.target = ent(kinds)
        if not p.target:
            return None, "There is no art here to admire yet."
    elif v == "look":
        p.target = ent("telescope") if o == "telescope" else ("tile", here, False)
    elif v == "sleep":
        p.target = ent("bed") if a is w.ada else ("tile", w.posts.get(a.name, here), False)
    elif v == "explore":
        p.target = ("tile", w.anchors.get(o) or w.anchors[random.choice(list(w.anchors))], False)
    elif v == "wait":
        p.target = ent("bench") if o == "bench" else ("tile", here, False)
    else:
        return None, f"I don't know how to {v}."
    if p.target is None:
        return None, f"I can't find a way to {v}."
    return p, ""


def target_pos(w: World, p: Plan):
    """(x, y, adjacent?) for the plan's target right now, or None if it vanished."""
    t = p.target
    if t is None:
        return None
    if t[0] == "tile":
        return (*t[1], t[2]) if t[1] else None
    if t[0] == "entity":
        e = w.entities.get(t[1])
        if not e:
            return None
        stand_on = KINDS[e["kind"]].get("portable") and w.walkable(e["x"], e["y"])
        return e["x"], e["y"], not stand_on
    if t[0] == "being":
        b = w.visitor if t[1] == "friend" else w.ada if t[1] == "synth" else w.people.get(t[1])
        return (b.x, b.y, True) if b else None
    return None


# ====================================================================== doing it
def act(w: World, p: Plan, me=None) -> tuple[bool, str, dict]:
    """The synth has arrived: do the thing. Returns (succeeded, narration, info for the World process)."""
    a, g = (me or w.ada), p.goal
    v, o = g.verb, g.obj
    info: dict = {}
    carrying = a.carrying
    n = a.needs
    synth = a is w.ada

    def holding(kind):
        return next((e for e in carrying if e["kind"] == kind), None)

    def new_item(kind) -> dict:
        e = {"id": w.next_id, "kind": kind, "x": a.x, "y": a.y}
        w.next_id += 1
        return e

    def pick(e) -> bool:
        if len(carrying) >= 6:
            return False
        w.remove(e)
        carrying.append(e)
        return True

    def gain(need, amount):
        n[need] = max(0.0, min(100.0, n[need] + amount))

    t = p.target
    e = w.entities.get(t[1]) if t and t[0] == "entity" else None
    if v == "work":
        return _work(w, a, info)
    if v in ("go", "explore"):
        place = w.place_of(a.x, a.y)
        if synth:
            w.visited.add(place)
        return True, f"I am {where(place)}. It is {PLACES.get(place, 'a nice place')}.", info
    if v == "eat":
        item = holding(o) or e
        if not item:
            return False, f"The {o} is gone.", info
        if item is e and not pick(e):
            return False, "My hands are full.", info
        carrying.remove(item)
        food = KINDS[item["kind"]].get("food", 0)
        if food < 0:
            gain("energy", food)
            return True, f"I eat {_the(item['kind'])} raw. It tastes bad and my tummy hurts. I should cook it first.", info
        gain("energy", food)
        return True, f"I eat {_the(item['kind'])}. It is {', '.join(KINDS[item['kind']].get('props', ['good'])[:2])}. I feel full.", info
    if v == "drink":
        jug = holding("milk") if o == "milk" else None
        bucket = None if jug else holding("water bucket")
        if jug:
            carrying.remove(jug)
            gain("water", 35)
            gain("energy", 10)
            return True, "I drink the cold, creamy milk. Yum!", info
        if bucket:
            bucket["kind"] = "bucket"
        gain("water", 45)
        src = "from my bucket" if bucket else ("from the well" if e and e["kind"] == "well" else "from the water")
        return True, f"I drink cool water {src}. I am not thirsty now.", info
    if v == "fill":
        b = holding("bucket")
        if not b:
            return False, "I have no bucket.", info
        b["kind"] = "water bucket"
        return True, "I fill my bucket with water. It is heavy now.", info
    if v == "take":
        if not e:
            return False, f"The {o} is gone.", info
        if not KINDS[e["kind"]].get("portable"):
            return False, f"{_cap(_the(e['kind']))} is too big to carry.", info
        if e["kind"] == "coin":
            w.remove(e)
            a.coins += 1
            return True, f"I find a shiny coin! Now I have {a.coins} coins.", info
        if not pick(e):
            return False, "My hands are full. I can carry six things.", info
        return True, f"I pick up {_the(e['kind'])}. It is {KINDS[e['kind']]['color']}.", info
    if v == "drop":
        item = holding(o)
        if not item:
            return False, f"I am not carrying {_a(o)}.", info
        carrying.remove(item)
        item["x"], item["y"] = a.x, a.y
        w.entities[item["id"]] = item
        w.touch(item)
        return True, f"I put down {_the(o)}.", info
    if v == "give":
        item = holding(o)
        if not item:
            return False, f"I am not carrying {_a(o)}.", info
        receiver = g.extra
        carrying.remove(item)
        info["gave"] = (o, receiver)
        gain("company", 20)
        if receiver == "my friend":
            if w.visitor:
                w.visitor.carrying.append(item)
            return True, f"I give {_the(o)} to my friend. Sharing feels good.", info
        other = w.being(receiver)
        if other is not None and len(other.carrying) < 6:
            other.carrying.append(item)
        liked = o in NPCS.get(receiver, {}).get("likes", [])
        w.befriend(receiver, 12 if liked else 6, me=a)
        info["talk"] = receiver
        q = next((q for q in w.quests if q["giver"] == receiver and q["want"] == o), None) if synth else None
        if q:
            q["got"] += 1
            if q["got"] >= q["count"]:
                w.quests.remove(q)
                a.coins += q["reward"]
                w.done_quests += 1
                w.befriend(receiver, 15, me=a)
                if other is not None and item in other.carrying:
                    other.carrying.remove(item)
                info["quest_done"] = q
                return True, (f"I give {_the(o)} to {receiver}. {receiver} is so happy! "
                              f"Quest done: {receiver} gives me {q['reward']} coins."), info
            return True, f"I give {_the(o)} to {receiver}. {receiver} needs {q['count'] - q['got']} more.", info
        return True, f"I give {_the(o)} to {receiver}. {'They love it!' if liked else 'They say thank you.'}", info
    if v == "talk":
        who = o if o in NPCS or o == w.ada.name else "friend"
        info["talk"] = who
        gain("company", 10)
        if who != "friend":
            w.befriend(who, 3, me=a)
            return True, f"I go to talk with {who}. {who} is {w.friendship_word(who, a)}.", info
        return True, "I talk with my friend.", info
    if v == "ask":
        info["ask"] = g.extra
        gain("fun", 10)
        return True, f'At the shrine I ask the Oracle: "{g.extra}"', info
    if v == "learn":
        info["learn"] = True
        gain("fun", 15)
        w.befriend("Sage", 4, me=a)
        return True, "I sit in the school. Sage writes words on the blackboard and I learn them.", info
    if v == "read":
        if not e:
            return False, "The book is gone.", info
        info["read"] = e
        gain("fun", 15)
        return True, f"I open {_the(e['kind'])} and read.", info
    if v == "play":
        if not e:
            return False, "I can't find it.", info
        gain("fun", 30)
        k = e["kind"]
        if k == "ball":
            dx, dy = {"north": (0, -1), "south": (0, 1), "west": (-1, 0), "east": (1, 0)}[a.facing]
            for _ in range(3):
                if w.walkable(e["x"] + dx, e["y"] + dy):
                    e["x"] += dx
                    e["y"] += dy
            w.touch(e)
            return True, "I kick the ball and it bounces far away. That is fun!", info
        if k in ("music box", "piano"):
            info["music"] = True
            return True, ("I wind the music box. A little song plays: do re mi fa sol." if k == "music box"
                          else "I press the piano keys. Low notes are deep, high notes are bright. I make a song!"), info
        if k == "swing":
            return True, "I swing high and low. The wind is in my face. Whee!", info
        return True, f"I play with {_the(k)}.", info
    if v == "pet":
        if not e:
            return False, "It ran away.", info
        gain("company", 15)
        gain("fun", 10)
        k = e["kind"]
        return True, f"I pet {_the(k)}. It is {KINDS[k]['props'][0]}. It says {KINDS[k].get('sound', 'nothing')}.", info
    if v == "smell":
        if not e:
            return False, "The flower is gone.", info
        gain("fun", 12)
        return True, f"I smell {_the(e['kind'])}. It smells nice and it is {KINDS[e['kind']]['color']}.", info
    if v == "plant":
        seed = holding(o)
        if not seed or w.terrain[a.y][a.x] != SOIL:
            return False, "I can only plant seeds in the soil of the fields.", info
        carrying.remove(seed)
        crop = KINDS[o]["grows"]
        w.add("sprout", a.x, a.y, growth=0, crop=crop)
        return True, f"I plant {_the(o)} in the soil. It will grow into {_a(crop)}. It needs water.", info
    if v == "water":
        b = holding("water bucket")
        if not (b and e):
            return False, "I need a bucket of water and a sprout.", info
        b["kind"] = "bucket"
        e["watered"] = True
        w.touch(e)
        return True, "I water the sprout. It drinks the water and will grow faster.", info
    if v == "harvest":
        if not e or e["kind"] not in ("wheat", "carrot", "pumpkin"):
            return False, "It is not ready.", info
        k = e["kind"]
        if not pick(e):
            return False, "My hands are full.", info
        return True, f"I harvest {_the(k)}. {'Wheat makes bread.' if k == 'wheat' else 'It looks delicious.'}", info
    if v == "chop":
        if not holding("axe"):
            return False, "I need an axe.", info
        if len(carrying) >= 6:
            return False, "My hands are full.", info
        carrying.append(new_item("wood"))
        return True, "I chop the tree with my axe. Now I have wood.", info
    if v == "make":
        if o == "snowman":
            w.add("snowman", a.x, a.y)
            gain("fun", 35)
            return True, "I roll three big snowballs and stack them. I made a snowman! He has a carrot nose.", info
        r = _recipe(o)
        if not r or not _has([x["kind"] for x in carrying], r[1]):
            return False, f"I don't have what I need to make {_a(o)}.", info
        for k in r[1]:
            carrying.remove(holding(k))
        carrying.append(new_item(o))
        gain("fun", 15)
        where_ = f"At the {r[2]} " if r[2] else ""
        return True, f"{where_}I put {' and '.join(_a(k) for k in r[1])} together. I made {_a(o)}!", info
    if v == "light":
        wood = holding("wood")
        if not (wood and e):
            return False, "I need wood and the fire pit.", info
        carrying.remove(wood)
        e["lit"] = 240
        w.touch(e)
        return True, "I put the wood in the fire pit and light it. The fire is hot and bright.", info
    if v == "warm":
        gain("warmth", 25)
        return True, "I sit close to the warm fire. I am not cold now.", info
    if v == "cook":
        raw = holding(o)
        if not (raw and e and (e["kind"] == "stove" or e.get("lit"))):
            return False, "I need something to cook and a fire.", info
        cooked = KINDS[o]["cooked"]
        raw["kind"] = cooked
        return True, f"I cook {_the(o)} on the {e['kind']}. Now I have {_a(cooked)}. It smells so good.", info
    if v == "bake":
        raw = holding(o)
        if not (raw and e):
            return False, "I need something to bake and the oven.", info
        baked = KINDS[o]["baked"]
        raw["kind"] = baked
        return True, f"I put {_the(o)} in the hot oven. Soon I have {_a(baked)}!", info
    if v == "buy":
        price = KINDS[o].get("price", 5)
        if a.coins < price:
            return False, f"I don't have enough coins. {_cap(_a(o))} costs {price}.", info
        if len(carrying) >= 6:
            return False, "My hands are full.", info
        a.coins -= price
        seller = w.being(g.extra)
        if seller is not None:
            seller.coins += price                           # money goes round the valley
        carrying.append(new_item(o))
        info["talk"] = g.extra
        w.befriend(g.extra, 2, me=a)
        return True, f"I give {g.extra} {price} coins and get {_a(o)}. I have {a.coins} coins left.", info
    if v == "sell":
        item = holding(o)
        if not item:
            return False, f"I don't have {_a(o)}.", info
        value = max(1, KINDS[o].get("value", 1))
        juniper = w.people.get("Juniper")
        if juniper is not None and juniper is not a:
            if juniper.coins < value:
                return False, "Juniper has no coins left to buy things today.", info
            juniper.coins -= value
            if len(juniper.carrying) < 6:
                juniper.carrying.append(item)
        carrying.remove(item)
        a.coins += value
        info["talk"] = "Juniper"
        w.befriend("Juniper", 2, me=a)
        return True, f"Juniper buys {_the(o)} for {value} coin{'s' if value != 1 else ''}. Now I have {a.coins} coins.", info
    if v == "fish":
        if not holding("fishing rod"):
            return False, "I need a fishing rod.", info
        gain("fun", 20)
        if len(carrying) >= 6:
            return False, "My hands are full, so I just watch the water.", info
        if w.rng.random() < (0.65 if w.time_of_day(600) in ("dawn", "morning", "evening") else 0.45):
            carrying.append(new_item("raw fish"))
            return True, "I cast my line and wait quietly... A tug! I caught a fish!", info
        return True, "I cast my line and wait. The fish don't bite this time, but the lake is calm and pretty.", info
    if v == "mine":
        if not holding("pickaxe"):
            return False, "I need a pickaxe.", info
        if not e or e.get("left", 0) <= 0:
            return False, "There is nothing left to dig here.", info
        if len(carrying) >= 6:
            return False, "My hands are full.", info
        e["left"] -= 1
        w.touch(e)
        got = "crystal" if e["kind"] == "crystal cluster" else "ore"
        carrying.append(new_item(got))
        return True, f"Clang! I swing my pickaxe at the rock and get {_a(got)}.", info
    if v == "milk":
        b = holding("bucket")
        if not (b and e):
            return False, "I need a bucket and a cow.", info
        b["kind"] = "milk"
        gain("company", 5)
        return True, "I milk the gentle cow. Moo! Now I have a jug of fresh milk.", info
    if v == "paint":
        if not e:
            return False, "There is no easel here.", info
        gain("fun", 30)
        data = art.painting(w.rng, w.place_of(a.x, a.y), w.season, w.time_of_day(600), w.weather,
                            " ".join(w.feelings(a)) or "fine")
        item = new_item("painting")
        c = w.create("painting", a.name, data, art.default_title("painting", data, w.rng), item)
        if len(carrying) < 6:
            carrying.append(item)
        else:
            spot = w.free_spot(a.x, a.y)
            if spot:
                item["x"], item["y"] = spot
                w.entities[item["id"]] = item
        info["created"] = c
        return True, f"At the easel I paint {data['subject']}. It is {data['style']} and colourful. I am proud of it.", info
    if v == "compose":
        if not e:
            return False, "There is no piano here.", info
        gain("fun", 30)
        data = art.melody(w.rng, " ".join(w.feelings(a)) or "fine", w.season)
        item = new_item("recording")
        c = w.create("music", a.name, data, art.default_title("music", data, w.rng), item)
        if len(carrying) < 6:
            carrying.append(item)
        info["created"] = c
        info["music"] = True
        return True, f"I play a {data['scale']} melody on the piano, {len(data['notes'])} notes long, and record it.", info
    if v == "sculpt":
        mat = holding(o)
        if not (mat and holding("chisel")):
            return False, "I need a chisel and something to carve.", info
        spot = w.free_spot(a.x, a.y)
        if not spot:
            return False, "There is no room here for a sculpture.", info
        carrying.remove(mat)
        data = art.sculpture(w.rng, o)
        statue = w.add("sculpture", *spot)
        c = w.create("sculpture", a.name, data, art.default_title("sculpture", data, w.rng), statue)
        gain("fun", 35)
        info["created"] = c
        return True, f"Tap, tap, tap. I carve the {o} into a sculpture. It will stand here for everyone to see.", info
    if v == "build":
        need = BUILDS.get(o)
        if not (need and holding("hammer") and _has([x["kind"] for x in carrying], need)):
            return False, "I don't have what I need to build that.", info
        spot = w.free_spot(a.x, a.y)
        if not spot:
            return False, "There is no room to build here.", info
        for k in need:
            carrying.remove(holding(k))
        thing = w.add(o, *spot, built_by=a.name, lit=60 if o == "lamp post" else None)
        c = w.create("building", a.name, {"what": o, "x": spot[0], "y": spot[1], "place": w.place_of(*spot)},
                     f"{a.name}'s {o}", thing)
        gain("fun", 30)
        info["created"] = c
        return True, f"Bang, bang! I build {_a(o)} {where(w.place_of(*spot))}. It will last a long time.", info
    if v == "write":
        paper = holding("paper")
        if not paper:
            return False, "I need paper.", info
        paper["kind"] = "poem"
        c = w.create("writing", a.name, {"place": w.place_of(a.x, a.y), "season": w.season}, "A poem", paper)
        gain("fun", 25)
        info["created"] = c
        info["write"] = c
        return True, "I sit down and write a poem on my paper.", info
    if v == "listen":
        rec = holding("recording") or (e if e and e["kind"] == "recording" else None)
        gain("fun", 20)
        if rec and rec.get("work"):
            c = next((c for c in w.creations if c["id"] == rec["work"]), None)
            info["listened"] = rec["work"]
            return True, f"I listen to \"{c['title'] if c else 'a song'}\" by {c['author'] if c else 'someone'}. It is lovely.", info
        return True, "I listen to the sounds around me.", info
    if v == "admire":
        if not e:
            return False, "It isn't here any more.", info
        gain("fun", 15)
        c = next((c for c in w.creations if c["id"] == e.get("work")), None)
        if c and c["author"] != a.name:
            w.befriend(c["author"], 2, me=a)
        who = f" by {c['author']}" if c else ""
        return True, f"I admire {_the(e['kind'])}{who}. {'It is beautiful.' if c else 'It is pretty.'}", info
    if v == "swim":
        if w.season == "winter" or w.temperature() < 8:
            gain("warmth", -20)
            return True, "I dip my toes in the lake. Brrr! The water is far too cold to swim.", info
        gain("fun", 35)
        gain("warmth", -5)
        return True, "I swim in the cool lake. Splash! The fish swim around me.", info
    if v == "fly":
        if not holding("kite"):
            return False, "I need a kite.", info
        windy = w.weather in ("windy", "clear")
        gain("fun", 40 if windy else 10)
        return True, ("I run and my kite climbs high into the wind. It dances in the sky!" if windy
                      else "I run with my kite, but there is no wind. It falls down."), info
    if v == "look":
        if o == "telescope":
            info["stars"] = True
            dark = w.phase == "night" or w.time_of_day(600) == "evening"
            return True, ("I look through the telescope. I see many stars and the bright moon." if dark
                          else "I look through the telescope, but the sky is too bright to see stars."), info
        return True, "I look around. " + w.perceive(600), info
    if v == "sleep":
        a.sleeping = True
        return True, "I lie down in my soft bed and close my eyes.", info
    if v == "learn" and not synth:
        return True, "I listen to Sage's lesson.", info
    if v == "wait":
        gain("rest", 5)
        return True, "I sit and rest for a moment." if e else "I rest for a moment.", info
    return False, f"I don't know how to {v}.", info


def _work(w: World, a, info: dict) -> tuple[bool, str, dict]:
    """A villager's work: it makes something, and it feels good to do it."""
    r = w.rng
    a.needs["fun"] = min(100.0, a.needs["fun"] + 8)
    a.coins += 1                                            # a day's work earns a little
    role = a.role
    post = w.posts.get(a.name, (a.x, a.y))

    def gift(kind, chance):
        if r.random() < chance and len(a.carrying) < 6:
            a.carrying.append({"id": w.next_id, "kind": kind, "x": a.x, "y": a.y})
            w.next_id += 1

    craft = {"toolmaker and smith": ["wood", "stone", "ore"], "librarian": ["paper"], "teacher": ["paper"],
             "child who loves to play": ["clay"]}.get(role, [])
    for k in craft:
        if sum(1 for e in a.carrying if e["kind"] == k) < 2:
            gift(k, 0.25)
    if role == "toolmaker and smith" and not any(e["kind"] == "hammer" for e in a.carrying):
        gift("hammer", 1.0)
    if role.startswith("child") and not any(e["kind"] == "chisel" for e in a.carrying):
        gift("chisel", 1.0)

    def lay(kind, cap=4):
        here = [e for e in w.entities.values() if e["kind"] == kind and abs(e["x"] - post[0]) + abs(e["y"] - post[1]) <= 4]
        if len(here) < cap:
            w.spawn_near(kind, w.place_of(*post), near=post)

    if role == "baker":
        lay("bread")
        return True, r.choice(["I knead the dough and bake fresh bread.", "The oven is hot. The loaves are golden."]), info
    if role == "toolmaker and smith":
        if r.random() < 0.3:
            lay(r.choice(["axe", "bucket", "fishing rod", "pickaxe"]), 3)
        return True, r.choice(["Clang, clang! I shape hot metal at the forge.", "I sharpen tools on my workbench."]), info
    if role == "fisher":
        a.needs["fun"] = min(100.0, a.needs["fun"] + 6)
        return True, r.choice(["I cast my line. A fish! I put it back for another day.", "The lake is calm. I wait for a bite."]), info
    if role == "merchant":
        return True, r.choice(["I polish my coins and tidy the stall.", "I count my goods: seeds, kites and buckets."]), info
    if role == "librarian":
        if r.random() < 0.15:
            lay("book", 8)
        return True, r.choice(["I sort the books by colour and size.", "I read a chapter about the stars."]), info
    if role == "teacher":
        return True, r.choice(["I write new words on the blackboard.", "I plan a lesson about the seasons."]), info
    if role.startswith("child"):
        a.needs["fun"] = min(100.0, a.needs["fun"] + 20)
        return True, r.choice(["I run around the pond as fast as I can!", "I swing as high as the clouds!"]), info
    return True, "I do my work.", info


def face(w: World, x: int, y: int, me=None):
    a = me or w.ada
    if (x, y) != (a.x, a.y):
        a.facing = _facing(a.x, a.y, x, y)


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]
