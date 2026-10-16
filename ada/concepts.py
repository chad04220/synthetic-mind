"""The concept graph: facts as (subject, relation, object) triples.

Facts come from the world's ontology, from a list of general truths and from the Oracle (lesson
packs, and topics you ask it to teach). The graph does two jobs:

* drills: varied sentences and question/answer pairs stating the facts, mixed into training;
* probes: multiple-choice tests worded differently from every drill ("To find a mushroom, go to
  the ___": forest / library / lake / bakery). Ada answers by which option her brain finds most
  likely. Because probe wording never appears in training, the score measures whether she has
  learned the concept rather than memorised a sentence.
"""
from __future__ import annotations

import hashlib
import json
import random
import threading
from pathlib import Path

from .ontology import KINDS, triples as world_triples

RELATIONS = ("is a", "color", "is", "made of", "used for", "found in", "can")


def _a(word: str) -> str:
    return ("an " if word[:1].lower() in "aeiou" else "a ") + word


def noun(s: str) -> str:
    """'apple' -> 'an apple'; names and known phrases are used as they are."""
    if s in KINDS:
        return KINDS[s]["noun"]
    if s[:1].isupper():
        return s
    return _a(s)


def the(s: str) -> str:
    if s[:1].isupper():
        return s
    n = noun(s)
    for art in ("an ", "a ", "some ", "the "):
        if n.startswith(art):
            return "the " + n[len(art):]
    return "the " + n


def cap(s: str) -> str:
    return s[:1].upper() + s[1:]


# Training wording. Each is (plain sentence) or ("Q", question, answer).
DRILLS = {
    "is a": ["{S} is a kind of {o}.", "{S} is {ao}.", ("Q", "What is {the}?", "{The} is {ao}.")],
    "color": ["{The} is {o}.", "The color of {the} is {o}.", ("Q", "What color is {the}?", "It is {o}.")],
    "is": ["{The} is {o}.", "I know that {the} is {o}.", ("Q", "What is {the} like?", "It is {o}.")],
    "made of": ["{The} is made of {o}.", ("Q", "What is {the} made of?", "It is made of {o}.")],
    "used for": ["{S} is used for {o}.", "You use {the} for {o}.",
                 ("Q", "What is {the} for?", "It is used for {o}.")],
    "found in": ["You can find {s} in the {o}.", "{S} is in the {o}.",
                 ("Q", "Where can I find {s}?", "In the {o}.")],
    "can": ["{S} can {o}.", ("Q", "What can {the} do?", "It can {o}.")],
}

# Test wording: never used in training.
PROBES = {
    "is a": "{The} is one type of {o}.",
    "color": "If you look at {the}, you can see that it is {o}.",
    "is": "Everyone agrees that {the} is {o}.",
    "made of": "{The} was put together from {o}.",
    "used for": "People keep {the} around for {o}.",
    "found in": "To look for {s}, go to the {o}.",
    "can": "It is true that {the} can {o}.",
}


def fill(template: str, s: str, o: str) -> str:
    return template.format(S=cap(noun(s)), s=noun(s), the=the(s), The=cap(the(s)), o=o, ao=_a(o))


class ConceptGraph:
    def __init__(self, path: Path | None = None):
        self.path = path
        self.lock = threading.Lock()
        self.facts: dict[tuple[str, str, str], str] = {}   # triple -> source
        for t in world_triples():
            self.facts[t] = "built-in"
        self.mtime = 0.0
        if path and path.exists():
            self.reload()

    def reload(self) -> bool:
        """Pick up facts another process added. Returns True if anything changed."""
        if not self.path or not self.path.exists():
            return False
        m = self.path.stat().st_mtime
        if m == self.mtime:
            return False
        self.mtime = m
        try:
            data = json.loads(self.path.read_text())
        except (ValueError, OSError):
            return False
        with self.lock:
            for f in data.get("facts", []):
                t = (f["s"], f["r"], f["o"])
                self.facts.setdefault(t, f.get("src", "oracle"))
        return True

    def add(self, facts: list[dict], src: str) -> int:
        """Add facts like {"s": "moon", "r": "is", "o": "round"}; returns how many were new."""
        new = 0
        with self.lock:
            for f in facts:
                s, r, o = str(f.get("s", "")).strip().lower(), str(f.get("r", "")).strip().lower(), \
                    str(f.get("o", "")).strip().lower()
                if not s or not o or r not in RELATIONS or len(s) > 40 or len(o) > 40:
                    continue
                if (s, r, o) not in self.facts:
                    self.facts[(s, r, o)] = src
                    new += 1
        if new:
            self.save()
        return new

    def save(self):
        if not self.path:
            return
        with self.lock:
            data = {"facts": [{"s": s, "r": r, "o": o, "src": src} for (s, r, o), src in self.facts.items()
                              if src != "built-in"]}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1))
        tmp.replace(self.path)
        self.mtime = self.path.stat().st_mtime

    def all(self) -> list[tuple[tuple[str, str, str], str]]:
        with self.lock:
            return list(self.facts.items())

    # -- training text ---------------------------------------------------------------
    def drill(self, rng: random.Random, n: int = 6) -> list[tuple[str, str]]:
        """A short run of facts about one subject, as (role, text) parts."""
        facts = self.all()
        (s, _, _), _ = rng.choice(facts)
        about = [t for t, _ in facts if t[0] == s]
        rng.shuffle(about)
        parts = []
        for (s, r, o) in about[:n]:
            t = rng.choice(DRILLS[r])
            if isinstance(t, tuple):
                parts += [("<|user|>", fill(t[1], s, o)), ("<|mind|>", fill(t[2], s, o))]
            else:
                parts.append(("<|oracle|>", fill(t, s, o)))
        return parts

    # -- tests -----------------------------------------------------------------------
    def probes(self, limit: int = 240) -> list[dict]:
        """Multiple-choice items: the true object plus three objects that are false for the subject."""
        facts = [t for t, _ in self.all()]
        by_rel: dict[str, set[str]] = {}
        true_for: dict[tuple[str, str], set[str]] = {}
        for s, r, o in facts:
            by_rel.setdefault(r, set()).add(o)
            true_for.setdefault((s, r), set()).add(o)
        # stable order so scores are comparable over time; built-in facts first
        src = dict(self.all())
        facts.sort(key=lambda t: (src[t] != "built-in", hashlib.md5("|".join(t).encode()).hexdigest()))
        items = []
        for s, r, o in facts:
            wrong = sorted(by_rel[r] - true_for[(s, r)])
            if len(wrong) < 3:
                continue
            rng = random.Random("|".join((s, r, o)))
            options = [o] + rng.sample(wrong, 3)
            rng.shuffle(options)
            items.append({"s": s, "r": r, "o": o, "options": options,
                          "sentences": [fill(PROBES[r], s, x) for x in options]})
            if len(items) >= limit:
                break
        return items
