"""The community: every villager is a mind, as the synth is.

Each villager has what the synth has: six needs and the feelings they bring, a body that walks
the valley, intentions written in its own words (by its own language model; its needs and its
work decide when that model is busy or off), the same planner and actions as the synth, an inner
monologue, a diary, friendships with everyone, and the things it makes (paintings, music,
sculptures, buildings, writing) that stay in the valley's gallery.

Conversations follow one standard, whoever takes part (two villagers, or a villager and the
synth): the one with something to say starts it and walks up to the other; both stop and face
each other; the speaker composes its line (a "…" bubble shows it is thinking) while the other
waits; when it has spoken, the other composes its reply while the first one waits; and so on for
a few turns, until one of them says goodbye. Each line comes from that speaker's own mind: a
villager's own language model, or the synth's own brain.
"""
from __future__ import annotations

import random
import time
from collections import deque
from dataclasses import dataclass, field

from .ontology import KINDS, NPCS
from .world import agent as ag
from .world.sim import where


@dataclass
class VillagerMind:
    name: str
    plan: ag.Plan | None = None
    waiting: tuple | None = None                   # (request id, since, perception) while it decides
    next_thought: float = 0.0
    thoughts: deque = field(default_factory=lambda: deque(maxlen=40))
    diary: deque = field(default_factory=lambda: deque(maxlen=60))
    intent: dict = field(default_factory=dict)
    decisions: deque = field(default_factory=lambda: deque(maxlen=40))   # "own words" | "needs"


@dataclass
class Talk:
    id: int
    members: list                                  # two names (a villager's, or the synth's)
    topic: str = ""
    turns: int = 4                                 # lines left to say
    speaker: int = 0                               # whose turn it is (index into members)
    history: list = field(default_factory=list)    # [(name, line)]
    state: str = "approach"                        # approach | compose | waiting | speaking
    until: float = 0.0
    started: float = 0.0
    route: list = field(default_factory=list)


TOPICS = ["the weather", "their work today", "something they made", "the season", "food", "the lake and the river",
          "a book", "the festival they are planning", "the animals in the valley", "a funny thing that happened",
          "music", "the stars last night", "the market", "how the synth is learning to talk"]


class Community:
    """Mixed into the World process (Life): the villagers' minds and the conversations."""

    # ------------------------------------------------------------------ set up
    def init_community(self):
        now = time.time()
        self.vminds = {n: VillagerMind(n, next_thought=now + 15 + 9 * i) for i, n in enumerate(NPCS)}
        self.talks: dict[int, Talk] = {}
        self.talk_seq = 1
        self.last_vthought = 0.0
        self.minds_cast = 0.0

    def clock_now(self) -> float:
        """The world's own clock (seconds): conversations keep time with the world, not the wall."""
        return self.world.tick_n * self.cfg.world.tick

    @property
    def synth_name(self) -> str:
        return self.cfg.name

    def villagers_think(self) -> bool:
        return self.cfg.oracle.enabled

    # ------------------------------------------------------------------ the villagers' days
    def community_step(self):
        w = self.world
        now = time.time()
        for name, b in w.people.items():
            st = self.vminds[name]
            if b.engaged is not None:
                continue
            if w.phase == "night":
                post = w.posts[name]
                if (b.x, b.y) == post:
                    b.sleeping, st.plan = True, None
                    continue
                if not st.plan or st.plan.goal.verb != "sleep":
                    self.set_vplan(b, st, ag.Goal("sleep", "", text="I go home to sleep.", reason="It is night.",
                                                  source="needs"))
            elif b.sleeping:
                b.sleeping = False
                b.needs["rest"] = 100.0
            if st.plan:
                result = self.advance(b, st.plan)
                if result is not None:
                    self.finish_v(b, st, *result)
            elif not b.sleeping:
                self.decide_v(b, st)
        # one villager thinks out loud at a time, in turn
        if self.villagers_think() and now - self.last_vthought > 6:
            awake = [n for n, b in w.people.items() if not b.sleeping and now >= self.vminds[n].next_thought]
            if awake:
                n = min(awake, key=lambda n: self.vminds[n].next_thought)
                self.vminds[n].next_thought = now + self.cfg.oracle.villager_thought_seconds * random.uniform(0.8, 1.3)
                self.last_vthought = now
                b = w.people[n]
                self.oracle("thought", npc=n, perception=w.perceive(self.day_seconds, me=b),
                            ctx=self.npc_context(n) | {"diary": [d["text"] for d in list(self.vminds[n].diary)[-4:]]})
        self.talk_step()

    def decide_v(self, b, st: VillagerMind):
        w = self.world
        if st.waiting:
            if time.time() - st.waiting[1] > 30:
                st.waiting = None
                self.choose_v(b, st, "")
            return
        if not self.villagers_think():
            self.choose_v(b, st, "")
            return
        perception = w.perceive(self.day_seconds, me=b)
        rid = self.oracle("intent", npc=b.name, perception=perception, ctx=self.npc_context(b.name))
        st.waiting = (rid, time.time(), perception)

    def choose_v(self, b, st: VillagerMind, own: str):
        w = self.world
        goal = ag.parse(own) if own else None
        if goal and goal.verb not in ("wait",):
            goal.source, goal.text = "self", own.split(".")[0].strip() + "."
            goal.reason = goal.reason or "I decided it myself."
            if self.set_vplan(b, st, goal):
                st.decisions.append("own words")
                return
        g = ag.drives(w, self.rng, True, False, me=b)
        if self.set_vplan(b, st, g):
            st.decisions.append("needs")
        else:
            self.set_vplan(b, st, ag.Goal("wait", text="I rest for a while.", source="needs"))

    def set_vplan(self, b, st: VillagerMind, goal: ag.Goal) -> bool:
        p, why = ag.plan(self.world, goal, me=b)
        if not p:
            st.diary.append({"text": why, "ok": False, "t": time.time()})
            return False
        p.perception = ""
        p.wellbeing_before = self.world.wellbeing(b)
        st.plan = p
        st.intent = {"text": goal.text or ag.say(goal), "reason": goal.reason, "source": goal.source, "t": time.time()}
        return True

    def finish_v(self, b, st: VillagerMind, ok: bool, narration: str, info: dict):
        st.plan = None
        st.diary.append({"text": narration, "ok": ok, "t": time.time()})
        self.link.send("event", kind="vdid", name=b.name, text=narration, ok=ok, source=st.intent.get("source", ""))
        if "talk" in info and info["talk"] not in ("friend",):
            self.start_talk(b.name, info["talk"])
        if "created" in info:
            c = info["created"]
            self.oracle("create", npc=b.name, creation={k: c[k] for k in ("id", "kind", "title")} |
                        {"about": _about(c)}, ctx=self.npc_context(b.name))
            self.link.send("event", kind="created", creation=c)

    # ------------------------------------------------------------------ conversations
    def start_talk(self, a: str, b: str, topic: str = "", turns: int | None = None) -> bool:
        """`a` has something to say to `b`."""
        w = self.world
        ba, bb = w.being(a), w.being(b)
        if ba is None or bb is None or ba is bb or ba is w.visitor or bb is w.visitor:
            return False
        if ba.engaged is not None or bb.engaged is not None or ba.sleeping or bb.sleeping:
            return False
        if abs(ba.x - bb.x) + abs(ba.y - bb.y) > 12:
            return False
        t = Talk(self.talk_seq, [ba.name, bb.name], topic or random.choice(TOPICS), turns or random.choice([2, 3, 4]),
                 started=self.clock_now())
        self.talk_seq += 1
        self.talks[t.id] = t
        ba.engaged = bb.engaged = t.id
        if ba is w.ada or bb is w.ada:
            self.plan = None                                  # the synth stops to talk
        for x in (ba, bb):
            st = self.vminds.get(x.name)
            if st:
                st.plan, st.waiting = None, None
        return True

    def talk_step(self):
        w, now = self.world, self.clock_now()
        for t in list(self.talks.values()):
            speaker, listener = (w.being(n) for n in (t.members[t.speaker], t.members[1 - t.speaker]))
            if speaker is None or listener is None or w.phase == "night" and now - t.started > 5:
                self.end_talk(t)
                continue
            if t.state == "approach":
                if abs(speaker.x - listener.x) + abs(speaker.y - listener.y) <= 1:
                    t.state = "compose"
                else:
                    if not t.route:
                        t.route = w.path((speaker.x, speaker.y), (listener.x, listener.y), me=speaker,
                                         adjacent=True, limit=3000) or []
                    if not t.route or now - t.started > 40:
                        t.state = "compose"                       # close enough to call out
                    else:
                        nx, ny = t.route.pop(0)
                        ag.face(w, nx, ny, speaker)
                        speaker.x, speaker.y = nx, ny
                continue
            if t.state == "compose":
                ag.face(w, listener.x, listener.y, speaker)
                ag.face(w, speaker.x, speaker.y, listener)
                speaker.say("…", 90)
                t.state, t.until = "waiting", now + 75
                self._compose(t, speaker, listener)
            elif t.state == "waiting" and now > t.until:
                line = random.choice(NPCS[speaker.name]["lines"]) if speaker.name in NPCS else ""
                self.talk_line(t.id, line)
            elif t.state == "speaking" and now >= t.until:
                t.turns -= 1
                last = t.history[-1][1].lower() if t.history else ""
                if t.turns <= 0 or any(x in last for x in ("goodbye", "bye", "see you")):
                    self.end_talk(t)
                else:
                    t.speaker = 1 - t.speaker
                    t.state = "compose"

    def _compose(self, t: Talk, speaker, listener):
        w = self.world
        if speaker is w.ada:
            if self.brain is None:
                self.talk_line(t.id, "")
                return
            parts = [("<|world|>", w.perceive(self.day_seconds))]
            for who, line in t.history[-6:]:
                parts.append(("<|mind|>", line) if who == w.ada.name else ("<|npc|>", f"{who}: {line}"))
            parts.append(("<|mind|>", ""))
            self.say_async("speech", parts, lambda text, toks, _: self.talk_line(t.id, text.strip()), max_new=24,
                           temperature=self.cfg.world.reply_temperature)
        elif not self.villagers_think():
            self.talk_line(t.id, random.choice(NPCS[speaker.name]["lines"]))   # voices off: a scripted line
        else:
            self.oracle("turn", talk=t.id, speaker=speaker.name, listener=listener.name, history=t.history[-8:],
                        topic=t.topic, opening=not t.history, closing=t.turns <= 1,
                        ctx=self.npc_context(speaker.name) | {"friendship": round(speaker.friends.get(listener.name, 10))})

    def talk_line(self, tid: int, line: str):
        t = self.talks.get(tid)
        if not t or t.state != "waiting":
            return
        w = self.world
        name = t.members[t.speaker]
        other = t.members[1 - t.speaker]
        b = w.being(name)
        line = (line or "").strip()
        if not line:
            line = "…"
        b.say(line, 2.5 + len(line) / 14)
        t.history.append((name, line))
        t.state, t.until = "speaking", self.clock_now() + 2.5 + len(line) / 14
        a = w.ada
        if b is not a and abs(b.x - a.x) + abs(b.y - a.y) <= 10:
            w.hear(name, line)
        self.link.send("event", kind="npc" if b is not a else "ada_says", name=name, text=line, to=other, why="talk",
                       talk=tid)

    def end_talk(self, t: Talk):
        w = self.world
        self.talks.pop(t.id, None)
        names = []
        for n in t.members:
            b = w.being(n)
            if b is not None and b.engaged == t.id:
                b.engaged = None
                names.append(n)
                if b.said == "…":
                    b.said = ""
        if len(t.history) < 1:
            return
        a, synth = w.ada, w.ada.name
        w.befriend(t.members[1], 3, me=w.being(t.members[0]))
        for n in t.members:
            st = self.vminds.get(n)
            if st:
                other = t.members[1] if n == t.members[0] else t.members[0]
                st.diary.append({"text": f"I talked with {other} about {t.topic}.", "ok": True, "t": time.time()})
        lines = [("<|mind|>", line) if who == synth else ("<|npc|>", f"{who}: {line}") for who, line in t.history
                 if line != "…"]
        if synth in t.members:
            self.journal("conversation", lines, 1.8)
            a.needs["company"] = min(100.0, a.needs["company"] + 20)
        elif any(abs(w.being(n).x - a.x) + abs(w.being(n).y - a.y) <= 10 for n in t.members if w.being(n)):
            self.journal("overheard", lines, 1.3)
        self.link.send("event", kind="talk", members=t.members, topic=t.topic, lines=t.history)

    # ------------------------------------------------------------------ the villagers' minds, answered
    def community_reply(self, purpose: str, req: dict, text: str, extra: dict) -> bool:
        """Answers from the villagers' language models. Returns True if handled."""
        w = self.world
        if purpose == "turn":
            self.talk_line(req["talk"], text)
            return True
        name = req.get("npc", "")
        st = self.vminds.get(name)
        b = w.people.get(name)
        if st is None or b is None:
            return purpose in ("intent", "thought", "create")
        if purpose == "intent":
            if st.waiting and st.waiting[0] == req.get("rid") and not st.plan and b.engaged is None:
                st.waiting = None
                self.choose_v(b, st, text)
            return True
        if purpose == "thought":
            if text:
                th = {"text": text, "t": time.time()}
                st.thoughts.append(th)
                self.link.send("event", kind="vthought", name=name, text=text)
            return True
        if purpose == "create":
            cid = req["creation"]["id"]
            fields = (extra or {}).get("work") or {}
            c = w.update_creation(cid, title=fields.get("title", ""), text=fields.get("text", ""))
            if c:
                self.link.send("event", kind="created", creation=c)
            return True
        return False

    def synth_creates(self, c: dict):
        """The synth names (and for writing, writes) what it made, with its own brain."""
        w = self.world
        if self.brain is None:
            return
        if c["kind"] == "writing":
            def wrote(text, toks, _):
                text = text.strip()
                w.update_creation(c["id"], text=text, title=(text.split(".")[0][:40] or "A poem"))
                self.link.send("event", kind="created", creation=c)
                if text:
                    self.journal("wrote", [("<|thought|>", "I write a poem:"), ("<|mind|>", text)], 1.0)

            self.say_async("speech", [("<|world|>", w.perceive(self.day_seconds)), ("<|thought|>", "I write a poem:")],
                           wrote, max_new=60, temperature=0.95)
        else:
            def named(text, toks, _):
                title = text.strip().split(".")[0][:48]
                if title:
                    w.update_creation(c["id"], title=title)
                    self.link.send("event", kind="created", creation=c)

            self.say_async("speech", [("<|world|>", w.perceive(self.day_seconds)),
                                      ("<|thought|>", f"I made {KINDS.get(_item(c), {}).get('noun', 'something')}. I call it")],
                           named, max_new=10, temperature=0.9)

    # ------------------------------------------------------------------ for the page
    def minds_view(self) -> list[dict]:
        w = self.world
        a = w.ada
        talking = {n: t for t in self.talks.values() for n in t.members}

        def base(b, kind):
            t = talking.get(b.name)
            return {"name": b.name, "kind": kind, "role": b.role, "x": b.x, "y": b.y, "place": w.place_of(b.x, b.y),
                    "needs": {k: round(v) for k, v in b.needs.items()}, "feelings": w.feelings(b),
                    "wellbeing": round(w.wellbeing(b), 3), "coins": b.coins, "sleeping": b.sleeping,
                    "carrying": [e["kind"] for e in b.carrying],
                    "friends": {k: round(v) for k, v in sorted(b.friends.items(), key=lambda kv: -kv[1])},
                    "talking_with": (t.members[1] if t.members[0] == b.name else t.members[0]) if t else "",
                    "talk_topic": t.topic if t else "",
                    "made": sum(1 for c in w.creations if c["author"] == b.name)}

        out = []
        recent = list(self.decisions)
        out.append(base(a, "synth") | {
            "doing": self.plan.goal.text if self.plan else (self.last_intent.get("text", "") if not a.sleeping else ""),
            "why": self.plan.goal.reason if self.plan else "", "source": self.last_intent.get("source", ""),
            "thought": (self.thoughts[-1]["text"] if self.thoughts else ""), "brain": self.brain_version,
            "own_words": round(recent.count("self") / len(recent), 3) if recent else 0.0,
            "diary": [x for x in w.log[-6:]]})
        for n, b in w.people.items():
            st = self.vminds[n]
            dec = list(st.decisions)
            out.append(base(b, "villager") | {
                "color": NPCS[n]["color"], "glyph": NPCS[n]["glyph"],
                "doing": st.plan.goal.text if st.plan else ("Sleeping" if b.sleeping else st.intent.get("text", "")),
                "why": st.plan.goal.reason if st.plan else "", "source": st.intent.get("source", ""),
                "thought": st.thoughts[-1]["text"] if st.thoughts else "",
                "own_words": round(dec.count("own words") / len(dec), 3) if dec else 0.0,
                "diary": [d["text"] for d in list(st.diary)[-6:]]})
        return out

    def community_state(self) -> dict:
        return {n: {"thoughts": list(st.thoughts)[-20:], "diary": list(st.diary)[-40:]} for n, st in self.vminds.items()}

    def load_community(self, data: dict):
        for n, d in (data or {}).items():
            st = self.vminds.get(n)
            if st:
                st.thoughts.extend(d.get("thoughts", []))
                st.diary.extend(d.get("diary", []))


def _item(c: dict) -> str:
    return {"painting": "painting", "music": "recording", "sculpture": "sculpture", "writing": "poem"}.get(
        c["kind"], c.get("data", {}).get("what", "building"))


def _about(c: dict) -> str:
    d = c.get("data", {})
    if c["kind"] == "painting":
        return f"a {d.get('style', '')} painting of {d.get('subject', 'the valley')}"
    if c["kind"] == "music":
        return f"a {d.get('scale', '')} melody of {len(d.get('notes', []))} notes on the {d.get('instrument', 'piano')}"
    if c["kind"] == "sculpture":
        return f"a sculpture carved from {d.get('material', 'stone')}"
    if c["kind"] == "building":
        return f"a {d.get('what', 'building')} {where(d.get('place', 'village'))}"
    return "a poem"
