"""The synth's journey: the milestones on its way from knowing nothing to speaking.

The Hub watches what happens (thoughts, replies, deeds, conversations, works, quests, the Academy's
stages and tests) and records each first time, once, with the day and what was said. They are
kept in minds/<name>/journey.json and shown as a timeline.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

# A small core of very common English words: hearing one of these on its own is a "first word".
COMMON = set("""a about after again all also am an and any apple are as ask at away back be bed because been big bird
book bread but by can cat come could day did do dog down eat every fire fish for friend from fun get give go good great
had happy has have he hello help her here him his home house how i if in is it its just know like little look love make
man many me more morning mother my name new night no not now of oh on one or our out over people play please put rain
read red run said say see she sleep so some sun take tell thank thanks that the their them then there they thing think
this time to today too tree two up us very want was water way we well went were what when where which who why will
with word work world yes you your zen sky blue green warm cold tree star moon bake fish paint song village""".split())
_WORD = re.compile(r"[a-z]+(?:'[a-z]+)?")

STAGES = ["Static", "Babbling", "First words", "Phrases", "Sentences", "Conversational", "Articulate"]


class Journey:
    def __init__(self, folder: Path, name: str):
        self.path = folder / "journey.json"
        self.name = name
        self.items: list[dict] = []
        self.done: set[str] = set()
        try:
            self.items = json.loads(self.path.read_text(encoding="utf-8"))
            self.done = {m["key"] for m in self.items}
        except (OSError, ValueError):
            pass

    def _mark(self, key: str, title: str, detail: str = "", day: int | None = None) -> dict | None:
        if key in self.done:
            return None
        self.done.add(key)
        m = {"key": key, "title": title, "detail": detail[:240], "t": time.time(), "day": day}
        self.items.append(m)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.items, indent=1), encoding="utf-8")
        tmp.replace(self.path)
        return m

    def observe(self, ev: dict, day: int | None = None) -> list[dict]:
        """Look at one event; return any milestones it reached."""
        kind, out = ev.get("kind"), []

        def mark(*a):
            m = self._mark(*a, day=day)
            if m:
                out.append(m)

        n = self.name
        if kind == "talk" and ev.get("name") == n:
            kind = "ada_says"                         # its own line in a conversation
        if kind in ("thought", "chat", "ada_says"):
            text = ev.get("text", "") or ""
            words = [w for w in _WORD.findall(text.lower()) if w in COMMON and len(w) > 1]
            where = {"thought": "in its thoughts", "chat": "to you", "ada_says": "out loud"}[kind]
            if words:
                mark("first_word", f"{n}'s first real word", f"“{words[0]}” {where}: {text[:120]}")
            if len(set(words)) >= 3:
                mark("first_phrase", f"{n}'s first phrase", f"{where}: {text[:160]}")
            if re.search(r"\b(i|you|it|we)\s+(am|is|are|want|like|see|go|have|eat|feel)\b", text.lower()):
                mark("first_sentence", f"{n}'s first sentence", f"{where}: {text[:160]}")
            if kind == "chat" and len(set(words)) >= 2:
                mark("first_reply", f"{n} answered you in words", text[:160])
        elif kind == "intent" and ev.get("source") == "self":
            mark("first_own_action", f"{n} did something it chose in its own words", ev.get("text", ""))
        if ev.get("kind") == "talk" and n in ev.get("members", []):
            mark("first_conversation", f"{n}'s first conversation", f"with {[m for m in ev['members'] if m != n][0]} about {ev.get('topic', '')}")
        elif kind == "created" and (ev.get("creation") or {}).get("author") == n:
            c = ev["creation"]
            mark(f"first_{c['kind']}", f"{n}'s first {c['kind'] if c['kind'] != 'music' else 'song'}", c.get("title", ""))
        elif kind == "quest":
            mark("first_quest", f"{n} completed its first quest", ev.get("text", ""))
        elif kind == "brain":
            stage = (ev.get("meta") or {}).get("stage_name", "")
            if stage and stage != "Static":
                mark(f"stage_{stage}", f"{n} reached the stage: {stage}", f"brain v{ev['meta'].get('version')}")
        elif kind == "concepts":
            acc = (ev.get("summary") or {}).get("accuracy")
            for th in (0.4, 0.6, 0.8):
                if acc is not None and acc >= th:
                    mark(f"concepts_{int(th * 100)}", f"{n} knows {int(th * 100)}% of its concepts", f"{acc:.0%} on the held-out test")
        return out
