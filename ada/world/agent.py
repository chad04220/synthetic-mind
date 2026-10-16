"""How Ada acts: words become deeds.

Each time she is free to choose, her brain writes an intention ("I eat the apple.", "I ask the
Oracle why the sky is blue."). `parse()` turns it into a Goal (a verb and its object); if the
world can make sense of it, she carries it out, and her own words have moved her body.

While her words can't yet do that, her needs decide (`drives()`): hunger, thirst, tiredness,
cold, loneliness, boredom and curiosity each propose something sensible, with a reason
("I am hungry."). Those choices are written into her journal next to what she sensed and how it
turned out, so the Academy teaches her brain to make them herself. The share of her actions
that come from her own words is the clearest sign that her language is grounded.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

from ..ontology import KINDS, NPCS, PLACES
from .sim import SOIL, WATER, World, _facing, where

VERBS = {
    "eat": ["eat", "eats", "ate", "eating", "taste", "munch"],
    "drink": ["drink", "drinks", "sip", "drinking"],
    "go": ["go", "goes", "walk", "run", "visit", "head", "travel", "return", "come", "move"],
    "take": ["take", "pick", "grab", "get", "collect", "gather", "fetch", "find"],
    "drop": ["drop", "put", "leave"],
    "give": ["give", "hand", "offer", "share"],
    "talk": ["talk", "speak", "chat", "greet", "say", "tell"],
    "ask": ["ask", "question"],
    "read": ["read", "study"],
    "play": ["play", "kick", "throw", "bounce", "dance"],
    "pet": ["pet", "stroke", "hug", "cuddle"],
    "smell": ["smell", "sniff"],
    "plant": ["plant", "sow"],
    "water": ["water"],
    "fill": ["fill"],
    "harvest": ["harvest", "reap"],
    "chop": ["chop", "cut"],
    "make": ["make", "craft", "build"],
    "light": ["light", "kindle", "start"],
    "cook": ["cook", "roast", "grill"],
    "bake": ["bake"],
    "buy": ["buy", "trade", "purchase"],
    "look": ["look", "watch", "gaze", "observe", "see"],
    "sleep": ["sleep", "nap"],
    "warm": ["warm"],
    "explore": ["explore", "wander", "roam", "discover"],
    "wait": ["wait", "rest", "sit", "stay", "relax"],
}
_VERB_OF = {w: v for v, ws in VERBS.items() for w in ws}
_OBJECTS = sorted(list(KINDS) + ["water", "fire", "stars", "sky", "oracle", "friend", "you", "bread", "tree"],
                  key=len, reverse=True)
_PEOPLE = {n.lower(): n for n in NPCS}


@dataclass
class Goal:
    verb: str
    obj: str = ""
    extra: str = ""          # e.g. the question for the Oracle
    text: str = ""           # the intention as a sentence
    reason: str = ""         # why (for choices her needs made)
    source: str = "self"     # self: her own words | needs | you


@dataclass
class Plan:
    goal: Goal
    target: tuple | None = None    # ("entity", id) | ("tile", (x, y), adjacent) | ("being", name) | None
    route: list = field(default_factory=list)
    ticks: int = 0
    perception: str = ""
    wellbeing_before: float = 0.0


# ====================================================================== words -> goals
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
    # "go and eat the apple" / "go to bake bread": the second verb is the real one
    if verb == "go" and len(verbs) > 1 and verbs[1][1] not in ("go",):
        i, verb = verbs[1]
    rest = " ".join(words[i + 1:])
    # "water" is both a verb and a thing: "water the sprout" vs "drink water"
    if verb == "water" and i > 0 and words[i - 1] not in ("i", "will", "to", "and", "then", "now"):
        verb = "drink"
    obj = ""
    for name, real in _PEOPLE.items():
        if re.search(rf"\b{name}\b", rest):
            obj = real
            break
    if not obj:
        for o in _OBJECTS:
            if re.search(rf"\b{re.escape(o)}s?\b", rest):
                obj = o
                break
    if not obj:
        for p in sorted(PLACES, key=len, reverse=True):
            if re.search(rf"\b{p}\b", rest):
                obj = p
                break
    if obj == "you":
        obj = "friend"
    extra = ""
    if verb == "give":   # "give the apple to my friend": the thing, then who receives it
        item = next((o for o in _OBJECTS if o in KINDS and re.search(rf"\b{re.escape(o)}s?\b", rest)), "")
        who = next((real for name, real in _PEOPLE.items() if re.search(rf"\b{name}\b", rest)), "")
        who = who or ("friend" if re.search(r"\b(friend|you)\b", rest) else "")
        return Goal("give", item, who, text.strip())
    if verb == "ask":
        m = re.search(r"\b(?:oracle|her|him|them)\b\s*(.*)", rest)
        extra = (m.group(1) if m else rest).strip()
        obj = obj if obj in _PEOPLE.values() else "oracle"
    if verb == "look" and obj in ("stars", "sky", ""):
        obj = "telescope" if obj else ""
    return Goal(verb, obj, extra, text.strip())


def say(goal: Goal) -> str:
    """The canonical sentence for a goal: what Ada learns to say before she does it."""
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
        "read": f"I read {the}.", "play": f"I play with {the}." if o != "music box" else "I play the music box.",
        "pet": f"I pet {the}.", "smell": f"I smell {the}.", "plant": "I plant a seed in the garden.",
        "water": "I water the sprout.", "fill": "I fill the bucket with water.", "harvest": "I harvest the wheat.",
        "chop": "I chop wood from a tree.", "make": f"I make {_a(o)}.", "light": "I light the fire.",
        "cook": f"I cook {the}.", "bake": "I bake bread in the oven.", "buy": "I buy bread from Mira.",
        "look": "I look at the stars through the telescope." if o == "telescope" else "I look around.",
        "sleep": "I go to bed and sleep.", "warm": "I warm myself by the fire.",
        "explore": f"I explore the {o}." if o else "I explore.", "wait": "I rest for a while.",
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


# ====================================================================== needs -> goals
QUESTIONS = ["What is the sun?", "Why is the sky blue?", "What are stars?", "Why does it rain?",
             "How do plants grow?", "What is a word?", "Where does bread come from?", "What is the moon?",
             "Why do birds fly?", "What is fire?", "How do fish breathe?", "What is snow?",
             "Why do we sleep?", "What is a friend?", "What is music?", "How does a book hold ideas?"]


def drives(w: World, rng: random.Random, asked_recently: bool, unread: bool) -> Goal:
    """A sensible thing to do now, chosen from her needs, with a reason."""
    n, a = w.needs, w.ada
    carrying = [e["kind"] for e in a.carrying]
    food = [k for k in ("bread", "cooked mushroom", "apple", "berry") if k in carrying]
    lit = w.nearest("fire pit", (a.x, a.y), where=lambda e: e.get("lit"))
    opts: list[tuple[float, Goal]] = []

    def add(score, verb, obj="", reason="", extra=""):
        g = Goal(verb, obj, extra, reason=reason, source="needs")
        g.text = say(g)
        opts.append((score, g))

    hunger = 100 - n["energy"]
    if n["energy"] < 60:
        if food:
            add(hunger * 1.4, "eat", food[0], "I am hungry.")
        elif w.nearest(["bread", "apple", "berry", "cooked mushroom"], (a.x, a.y)):
            e = w.nearest(["bread", "apple", "berry", "cooked mushroom"], (a.x, a.y))
            add(hunger * 1.2, "eat", e["kind"], "I am hungry.")
        if "coin" in carrying:
            add(hunger, "buy", "bread", "I am hungry and I have a coin.")
        if "mushroom" in carrying and lit:
            add(hunger * 1.1, "cook", "mushroom", "I am hungry. Mushrooms must be cooked.")
    if n["water"] < 60:
        add((100 - n["water"]) * 1.3, "drink", "water bucket" if "water bucket" in carrying else "water", "I am thirsty.")
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
        name = min(w.people, key=lambda p: abs(w.people[p].x - a.x) + abs(w.people[p].y - a.y))
        if not w.people[name].sleeping:
            add((100 - n["company"]), "talk", name, f"I want to talk to {name}.")
        add((100 - n["company"]) * 0.6, "pet", rng.choice(["cat", "dog"]), "I want a friend to play with.")
    if n["fun"] < 60:
        add((100 - n["fun"]) * 0.9, "play", rng.choice(["ball", "music box"]), "I am bored.")
        add((100 - n["fun"]) * 0.6, "smell", "flower", "I want something nice.")
    # curiosity and purpose
    unseen = [p for p in w.anchors if p not in w.visited]
    if unseen:
        add(35, "go", rng.choice(unseen), "I wonder what is there.")
    if unread:
        add(25, "read", "book", "I want to learn something.")
    if not asked_recently:
        add(22, "ask", "oracle", "I have a question.", rng.choice(QUESTIONS))
    if w.time_of_day(600) == "evening":
        add(25, "look", "telescope", "The stars will come out soon.")
    if "seed" in carrying:
        add(30, "plant", "seed", "Seeds grow into wheat.")
    elif w.nearest("seed", (a.x, a.y)) and not w.nearest("sprout", (a.x, a.y)):
        add(15, "take", "seed", "I can plant a seed.")
    sprout = w.nearest("sprout", (a.x, a.y), where=lambda e: not e.get("watered"))
    if sprout:
        add(28 if "water bucket" in carrying else 18, "water", "sprout", "The sprout needs water.")
    if w.nearest("wheat", (a.x, a.y), where=lambda e: w.terrain[e["y"]][e["x"]] == SOIL):
        add(30, "harvest", "wheat", "The wheat is ready.")
    if "wheat" in carrying:
        add(32, "bake", "bread", "Wheat makes bread.")
    if "wood" in carrying and "stone" in carrying and "axe" not in carrying:
        add(26, "make", "axe", "I have wood and a stone.")
    add(12, "explore", rng.choice(list(w.anchors)), "I want to explore.")
    add(5, "wait", "", "I want to rest a little.")
    weights = [max(0.1, s) ** 2 for s, _ in opts]
    return rng.choices([g for _, g in opts], weights)[0]


# ====================================================================== goals -> plans
def plan(w: World, g: Goal) -> tuple[Plan | None, str]:
    """Where to go for a goal. Returns (plan, '') or (None, why it can't be done)."""
    a = w.ada
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
        return ("being", name) if name in w.people else None

    if v == "go":
        if o in w.anchors:
            p.target = ("tile", w.anchors[o], False)
        elif o in NPCS or o == "friend":
            p.target = person(o)
        elif o in KINDS:
            p.target = ent(o)
        if not p.target:
            return None, f"I don't know where {o or 'that'} is."
    elif v in ("eat", "cook", "drop") and o in carrying:
        p.target = ("tile", here, False) if v != "cook" else ent("fire pit", lambda e: e.get("lit"))
        if v == "cook" and not p.target:
            return None, "There is no fire to cook on. I need to light the fire pit."
    elif v in ("eat", "take", "read", "play", "smell", "pet"):
        kind = o or {"read": "book", "play": "ball", "smell": "flower", "pet": "cat"}.get(v, "")
        if kind not in KINDS:
            return None, f"I don't know what {o or 'that'} is."
        if v == "eat" and not KINDS[kind].get("food"):
            return None, f"I can't eat {_the(kind)}."
        p.target = (ent(kind, lambda e: e["id"] not in w.read_books) if v == "read" else None) or ent(kind)
        if not p.target:
            return None, f"I can't find {_a(kind)}."
    elif v == "drink":
        if "water bucket" in carrying:
            p.target = ("tile", here, False)
        else:
            well = w.nearest("well", here)
            lake = w.nearest_tile(WATER, here)
            if well and (not lake or abs(well["x"] - a.x) + abs(well["y"] - a.y) <= abs(lake[0] - a.x) + abs(lake[1] - a.y)):
                p.target = ("entity", well["id"])
            else:
                p.target = ("tile", lake, True)
    elif v == "fill":
        if "bucket" not in carrying:
            return None, "I need a bucket first."
        well = w.nearest("well", here)
        p.target = ("entity", well["id"]) if well else ("tile", w.nearest_tile(WATER, here), True)
    elif v in ("talk", "give"):
        who = o if o in NPCS or o == "friend" else (g.extra if g.extra in NPCS else "friend")
        if v == "give":
            item = o if o in carrying else (carrying[0] if carrying else "")
            if not item:
                return None, "I have nothing to give."
            g.obj, g.extra = item, (who if who != "friend" else "my friend")
        p.target = person(who)
        if not p.target:
            return None, "My friend is not here." if who == "friend" else f"I don't know {who}."
    elif v == "ask":
        p.target = ("entity", w.nearest("shrine", here)["id"])
        g.extra = g.extra or random.choice(QUESTIONS)
    elif v == "plant":
        if "seed" not in carrying:
            return None, "I need a seed to plant."
        spots = [(x, y) for y in range(len(w.terrain)) for x in range(len(w.terrain[0]))
                 if w.terrain[y][x] == SOIL and not w.at(x, y)]
        if not spots:
            return None, "The garden is full."
        p.target = ("tile", min(spots, key=lambda s: abs(s[0] - a.x) + abs(s[1] - a.y)), False)
    elif v == "water":
        if "water bucket" not in carrying:
            if "bucket" in carrying:
                return plan(w, Goal("fill", "bucket", text="I fill the bucket with water.", source=g.source,
                                    reason="The sprout needs water. I need water in my bucket."))
            return plan(w, Goal("take", "bucket", text="I pick up the bucket.", source=g.source,
                                reason="I need a bucket to carry water."))
        p.target = ent("sprout", lambda e: not e.get("watered")) or ent("sprout")
        if not p.target:
            return None, "There is no sprout to water."
    elif v == "harvest":
        p.target = ent("wheat", lambda e: w.terrain[e["y"]][e["x"]] == SOIL) or ent("wheat")
        if not p.target:
            return None, "There is no wheat to harvest yet."
    elif v == "chop":
        if "axe" not in carrying:
            return None, "I need an axe to chop wood."
        tree = w.nearest_tile(3, here)
        p.target = ("tile", tree, True)
    elif v == "make":
        if not ("wood" in carrying and "stone" in carrying):
            return None, "To make an axe I need wood and a stone."
        p.target = ent("workbench")
    elif v == "light":
        if "wood" not in carrying:
            return None, "I need wood to light a fire."
        p.target = ent("fire pit")
    elif v == "warm":
        p.target = ent("fire pit", lambda e: e.get("lit")) or ("tile", w.anchors["home"], False)
    elif v == "bake":
        if "wheat" not in carrying:
            return None, "I need wheat to bake bread."
        p.target = ent("oven")
    elif v == "buy":
        if "coin" not in carrying:
            return None, "I need a coin to buy bread."
        p.target = person("Mira")
    elif v == "look":
        p.target = ent("telescope") if o == "telescope" else ("tile", here, False)
    elif v == "sleep":
        p.target = ent("bed")
    elif v == "explore":
        p.target = ("tile", w.anchors.get(o) or w.anchors[random.choice(list(w.anchors))], False)
    elif v == "wait":
        p.target = ("tile", here, False)
    else:
        return None, f"I don't know how to {v}."
    return p, ""


def target_pos(w: World, p: Plan):
    """(x, y, adjacent?) for the plan's target right now, or None if it vanished."""
    t = p.target
    if t is None:
        return None
    if t[0] == "tile":
        return (*t[1], t[2])
    if t[0] == "entity":
        e = w.entities.get(t[1])
        if not e:
            return None
        stand_on = KINDS[e["kind"]].get("portable") and w.walkable(e["x"], e["y"])
        return e["x"], e["y"], not stand_on
    if t[0] == "being":
        b = w.visitor if t[1] == "friend" else w.people.get(t[1])
        return (b.x, b.y, True) if b else None
    return None


# ====================================================================== doing it
def act(w: World, p: Plan) -> tuple[bool, str, dict]:
    """Ada has arrived: do the thing. Returns (succeeded, narration, info for the World process)."""
    a, g = w.ada, p.goal
    v, o = g.verb, g.obj
    info: dict = {}
    carrying = a.carrying

    def holding(kind):
        return next((e for e in carrying if e["kind"] == kind), None)

    def pick(e) -> bool:
        if len(carrying) >= 4:
            return False
        w.remove(e)
        carrying.append(e)
        return True

    def target_entity():
        t = p.target
        return w.entities.get(t[1]) if t and t[0] == "entity" else None

    e = target_entity()
    if v == "go" or v == "explore":
        place = w.place_of(a.x, a.y)
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
            w.needs["energy"] = max(0, w.needs["energy"] + food)
            return True, f"I eat {_the(item['kind'])} raw. It tastes bad and my tummy hurts. I should cook it first.", info
        w.needs["energy"] = min(100, w.needs["energy"] + food)
        return True, f"I eat {_the(item['kind'])}. It is {', '.join(KINDS[item['kind']].get('props', ['good'])[:2])}. I feel full.", info
    if v == "drink":
        bucket = holding("water bucket")
        if bucket:
            bucket["kind"] = "bucket"
        w.needs["water"] = min(100, w.needs["water"] + 45)
        src = "from my bucket" if bucket else ("from the well" if e and e["kind"] == "well" else "from the lake")
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
            return False, f"{_the(e['kind']).capitalize()} is too big to carry.", info
        if not pick(e):
            return False, "My hands are full. I can carry four things.", info
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
        carrying.remove(item)
        receiver = g.extra
        if receiver == "my friend" and w.visitor:
            w.visitor.carrying.append(item)
        info["gave"] = (o, receiver)
        w.needs["company"] = min(100, w.needs["company"] + 20)
        return True, f"I give {_the(o)} to {receiver}. Sharing feels good.", info
    if v == "talk":
        who = o if o in NPCS else "friend"
        info["talk"] = who
        w.needs["company"] = min(100, w.needs["company"] + 30)
        return True, f"I talk with {'my friend' if who == 'friend' else who}.", info
    if v == "ask":
        info["ask"] = g.extra
        w.needs["fun"] = min(100, w.needs["fun"] + 10)
        return True, f'At the shrine I ask the Oracle: "{g.extra}"', info
    if v == "read":
        if not e:
            return False, "The book is gone.", info
        info["read"] = e
        w.needs["fun"] = min(100, w.needs["fun"] + 15)
        return True, f"I open {_the(e['kind'])} and read.", info
    if v == "play":
        if not e:
            return False, "I can't find it.", info
        w.needs["fun"] = min(100, w.needs["fun"] + 30)
        if e["kind"] == "ball":
            dx, dy = {"north": (0, -1), "south": (0, 1), "west": (-1, 0), "east": (1, 0)}[a.facing]
            for _ in range(3):
                if w.walkable(e["x"] + dx, e["y"] + dy):
                    e["x"] += dx
                    e["y"] += dy
            w.touch(e)
            return True, "I kick the ball and it bounces far away. That is fun!", info
        if e["kind"] == "music box":
            info["music"] = True
            return True, "I wind the music box. A little song plays: do re mi fa sol.", info
        return True, f"I play with {_the(e['kind'])}.", info
    if v == "pet":
        if not e:
            return False, "It ran away.", info
        w.needs["company"] = min(100, w.needs["company"] + 15)
        w.needs["fun"] = min(100, w.needs["fun"] + 10)
        k = e["kind"]
        return True, f"I pet {_the(k)}. It is {KINDS[k]['props'][0]}. It says {KINDS[k].get('sound', 'nothing')}.", info
    if v == "smell":
        if not e:
            return False, "The flower is gone.", info
        w.needs["fun"] = min(100, w.needs["fun"] + 12)
        return True, f"I smell {_the(e['kind'])}. It smells nice and it is {KINDS[e['kind']]['color']}.", info
    if v == "plant":
        seed = holding("seed")
        if not seed or w.terrain[a.y][a.x] != SOIL:
            return False, "I can only plant a seed in the soil of the garden.", info
        carrying.remove(seed)
        w.add("sprout", a.x, a.y, growth=0)
        return True, "I plant the seed in the soil. A little sprout will grow. It needs water.", info
    if v == "water":
        b = holding("water bucket")
        if not (b and e):
            return False, "I need a bucket of water and a sprout.", info
        b["kind"] = "bucket"
        e["watered"] = True
        w.touch(e)
        return True, "I water the sprout. It drinks the water and will grow faster.", info
    if v == "harvest":
        if not e or e["kind"] != "wheat":
            return False, "The wheat is not ready.", info
        if not pick(e):
            return False, "My hands are full.", info
        return True, "I harvest the yellow wheat. Wheat makes bread.", info
    if v == "chop":
        if not holding("axe"):
            return False, "I need an axe.", info
        if len(carrying) >= 4:
            return False, "My hands are full.", info
        carrying.append({"id": w.next_id, "kind": "wood", "x": a.x, "y": a.y})
        w.next_id += 1
        return True, "I chop the tree with my axe. Now I have wood.", info
    if v == "make":
        wood, stone = holding("wood"), holding("stone")
        if not (wood and stone):
            return False, "I need wood and a stone.", info
        carrying.remove(wood)
        carrying.remove(stone)
        carrying.append({"id": w.next_id, "kind": "axe", "x": a.x, "y": a.y})
        w.next_id += 1
        return True, "At the workbench I tie the stone to the wood. I made an axe!", info
    if v == "light":
        wood = holding("wood")
        if not (wood and e):
            return False, "I need wood and the fire pit.", info
        carrying.remove(wood)
        e["lit"] = 240
        w.touch(e)
        return True, "I put the wood in the fire pit and light it. The fire is hot and bright.", info
    if v == "warm":
        w.needs["warmth"] = min(100, w.needs["warmth"] + 25)
        return True, "I sit close to the warm fire. I am not cold now.", info
    if v == "cook":
        m = holding("mushroom")
        if not (m and e and e.get("lit")):
            return False, "I need a mushroom and a burning fire.", info
        m["kind"] = "cooked mushroom"
        return True, "I cook the mushroom over the fire. Now it is safe and tasty.", info
    if v == "bake":
        wheat = holding("wheat")
        if not (wheat and e):
            return False, "I need wheat and the oven.", info
        wheat["kind"] = "bread"
        return True, "I put the wheat in the hot oven. Soon I have a warm loaf of bread!", info
    if v == "buy":
        coin = holding("coin")
        if not coin:
            return False, "I have no coin.", info
        carrying.remove(coin)
        carrying.append({"id": w.next_id, "kind": "bread", "x": a.x, "y": a.y})
        w.next_id += 1
        info["talk"] = "Mira"
        return True, "I give Mira a coin and she gives me a loaf of bread.", info
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
    if v == "wait":
        w.needs["rest"] = min(100, w.needs["rest"] + 5)
        return True, "I rest for a moment.", info
    return False, f"I don't know how to {v}.", info


def face(w: World, x: int, y: int):
    a = w.ada
    if (x, y) != (a.x, a.y):
        a.facing = _facing(a.x, a.y, x, y)
