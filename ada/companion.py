"""Wren: the companion who lives with the synth and raises it.

Wren's body lives in the World like the synth's, with the same needs, verbs and planner. Its mind
is the one language model (see wren.py): whenever Wren is free, the World lists what Wren could
sensibly do right now (look after the synth, keep the fire going, cook, tend the garden and the
animals, play, read, show the synth something and name it, talk, rest) and the model chooses one
and says what it says out loud. If the model is busy or slow, Wren picks the most pressing thing
itself, so it never stands still.

How much Wren does for the synth depends on how far the synth's language has come:

- caretaker (stages Static to First words): Wren feeds it, brings it water, dries it, puts it to
  bed, and narrates everything it does ("Look, Zen! I put the pot on the stove.");
- guide (Phrases, Sentences): Wren tells it what it needs and lets it do it ("You look thirsty.
  The sink is in the kitchen."), and the synth's next deed follows Wren's words;
- friend (Conversational and up): Wren helps when asked, and they live side by side.

Everything Wren says near the synth is heard: it goes into the synth's journal next to what the
synth saw at that moment, and so do Wren's deeds, in words ("Wren puts the pot on the stove.").
That is the language the synth grows up in.
"""
from __future__ import annotations

import random
import time
from collections import deque
from dataclasses import dataclass, field

from .ontology import KINDS, SOUP_THINGS
from .world import agent as ag
from .world.sim import _and, where

CARE = {"caretaker": 2, "guide": 1, "friend": 0}
PATIENCE = 10.0          # seconds (world time) Wren waits for its model before acting on its own judgement


@dataclass
class Talk:
    """A conversation between the synth and Wren, one turn at a time."""
    id: int
    members: list                                  # [initiator, other] (names)
    topic: str = ""
    turns: int = 4                                 # lines left to say
    speaker: int = 0                               # whose turn it is (index into members)
    history: list = field(default_factory=list)    # [(name, line)]
    state: str = "approach"                        # approach | compose | speaking
    until: float = 0.0
    started: float = 0.0


@dataclass
class Option:
    label: str                                      # what the model reads ("Light the fire in the fireplace")
    goal: ag.Goal | None
    score: float
    kind: str = "chore"                             # care | chore | teach | talk | play | self | rest
    line: str = ""                                  # what Wren says when it starts it, without the model
    suggest: ag.Goal | None = None                  # for "guide" care: what the synth should do
    thing: str = ""                                 # for "name": the kind of thing to name


TALK_TOPICS = ["what we are doing", "the weather", "Moss the cat", "the garden", "what we will eat", "the hens",
               "how {z} feels", "the stars", "a new word", "the sounds we hear", "colors around us", "the pond"]


class Companion:
    def __init__(self, life):
        self.life = life
        self.suggestion = None
        self.commission: dict | None = None            # something our friend asked Wren to make
        self.art_rid = None
        self.recent_labels: deque = deque(maxlen=6)
        self.failed: dict[str, float] = {}            # option label -> when it last failed
        self.current_label = ""
        self.plan: ag.Plan | None = None
        self.waiting: tuple | None = None            # (request id, since, options) while the model chooses
        self.late: tuple | None = None               # a question the model is still answering after Wren moved on
        self.ahead: tuple | None = None              # (label, say, thought): its answer, for the next choice
        self.diary: deque = deque(maxlen=240)          # {"day", "time", "text"}
        self.thoughts: deque = deque(maxlen=80)
        self.intent: dict = {}
        self.decisions: deque = deque(maxlen=60)       # "model" | "self"
        self.talk: Talk | None = None
        self.talk_seq = 1
        self.next_decide = 0.0
        self.last_spoke = 0.0
        self.last_named: dict[str, float] = {}         # kind -> when Wren last named it for the synth
        self.stories: list[dict] = []                  # bedtime stories, kept
        self.story_day = 0
        self.zen_words: dict[str, int] = {}            # real words Wren has heard the synth say
        self.pending_line = ""                         # said when the next plan starts (the model's "say")
        self.rng = random.Random()

    # ------------------------------------------------------------------ helpers
    def now(self) -> float:
        """The world's clock: Wren keeps time with the world, not the wall."""
        return self.life.clock_now()

    @property
    def w(self):
        return self.life.world

    @property
    def b(self):
        return self.life.world.wren

    @property
    def zen(self):
        return self.life.world.ada

    @property
    def name(self) -> str:
        return self.b.name

    @property
    def stage(self) -> int:
        return int(self.life.brain_meta.get("stage", 0) or 0)

    def care(self) -> int:
        c = self.life.cfg.oracle.care
        if c in CARE:
            return CARE[c]
        return 2 if self.stage <= 2 else 1 if self.stage <= 4 else 0

    def near_zen(self, d: int = 5) -> bool:
        z, b = self.zen, self.b
        if z.sleeping:
            return False
        return abs(z.x - b.x) + abs(z.y - b.y) <= d and \
            (self.w.building_of(z.x, z.y) == self.w.building_of(b.x, b.y) or abs(z.x - b.x) + abs(z.y - b.y) <= 2)

    def note(self, text: str):
        w = self.w
        self.diary.append({"day": w.day, "time": w.time_of_day(), "text": text})

    def today(self) -> list[str]:
        d = self.w.day
        return [f"{x['time']}: {x['text']}" for x in self.diary if x["day"] == d]

    # ------------------------------------------------------------------ speaking
    def speak(self, line: str, to_zen: bool = True, kind: str = "say"):
        """Wren says something out loud. If the synth is near, it hears it, and studies it."""
        line = (line or "").strip()
        if not line:
            return
        self.b.say(line, 9)
        self.last_spoke = self.now()
        heard = self.near_zen(7)
        self.life.link.send("event", kind="wren_says", text=line, why=kind, heard=heard)
        if heard:
            self.w.hear(self.name, line)
            self.life.journal("heard", [("<|world|>", self.w.perceive(me=self.zen)), ("<|npc|>", f"{self.name}: {line}")],
                              1.6 if kind in ("name", "say", "care") else 1.3)

    def narrate(self, narration: str):
        """At the caretaker stage, Wren talks the synth through what it does."""
        if not self.near_zen(5) or self.care() < 2 or self.b.engaged is not None:
            return
        if self.rng.random() < self.life.cfg.oracle.talkative and self.now() - self.last_spoke > 5:
            first = narration.split(". ")[0].rstrip(".")
            if first.startswith("I "):
                self.speak(f"Look, {self.zen.name}! {first}.", kind="narrate")

    # ------------------------------------------------------------------ the day
    def step(self):
        w, b = self.w, self.b
        if self.talk:
            self.talk_step()
            return
        if b.sleeping:
            if w.phase == "day" and w.time_of_day() != "dawn" or b.needs["rest"] >= 100 and w.phase == "day":
                b.sleeping = False
                b.needs["rest"] = 100.0
                self.note("I woke up.")
            return
        if self.plan:
            result = self.life.advance(b, self.plan)
            if result is not None:
                self.finish(*result)
            return
        if self.waiting:
            rid, since, opts = self.waiting
            if self.now() - since > PATIENCE:
                # The model is slow right now: act on Wren's own judgement, and keep the model's
                # answer, when it comes, for the next choice.
                self.waiting = None
                self.late = (rid, self.now(), opts)
                self.choose(None)
            return
        if self.now() >= self.next_decide:
            self.decide()

    def decide(self):
        opts = self.options()
        if not opts:
            self.set_plan(ag.Goal("rest", "sofa", reason="Nothing needs doing.", source="companion"))
            return
        opts.sort(key=lambda o: -o.score)
        if self.ahead:                                 # a choice the model made while Wren was busy
            label, say, thought = self.ahead
            self.ahead = None
            match = next((o for o in opts if o.label == label), None)
            if match and match.score >= opts[0].score - 4:
                self.model_thought(thought)
                self.pending_line = say if self.near_zen(6) else ""
                self.choose(match, opts, by_model=True)
                return
        urgent = opts[0].score >= 9
        if self.late and self.now() - self.late[1] > 120:
            self.life.pending.pop(self.late[0], None)
            self.late = None                           # it never came
        if urgent or self.late or not self.life.voice_ready or not self.life.cfg.oracle.enabled:
            self.choose(None, opts)                    # (one question to the model at a time)
            return
        top = opts[:7]
        self.rng.shuffle(top)                          # no favourite positions: the model reads the labels
        w = self.w
        rid = self.life.oracle("wren_decide", situation=w.perceive(me=self.b)[:600], synth=self.synth_state(),
                               memory=[f"{x['time']}: {x['text']}" for x in list(self.diary)[-4:]],
                               options=[o.label + (" (needed now)" if o.score >= 6 else "") for o in top],
                               near=self.near_zen(6))
        self.waiting = (rid, self.now(), top)

    def model_thought(self, thought: str):
        if thought:
            self.thoughts.append({"text": thought, "t": time.time()})
            self.life.link.send("event", kind="wren_thought", text=thought)

    def on_decision(self, rid: str, data: dict):
        i = data.get("choice", -1)
        if self.late and self.late[0] == rid:          # too late for the last choice: keep it for the next
            opts = self.late[2]
            self.late = None
            if 0 <= i < len(opts):
                self.ahead = (opts[i].label, data.get("say", ""), data.get("thought", ""))
            return
        if not self.waiting or self.waiting[0] != rid:
            return
        _, _, opts = self.waiting
        self.waiting = None
        self.model_thought(data.get("thought", ""))
        self.pending_line = data.get("say", "") if self.near_zen(6) else ""
        self.choose(opts[i] if 0 <= i < len(opts) else None, opts, by_model=0 <= i < len(opts))

    def choose(self, opt: Option | None, opts: list | None = None, by_model: bool = False):
        if opt is None:
            opts = opts or self.options()
            if not opts:
                self.next_decide = self.now() + 3
                return
            opts.sort(key=lambda o: -o.score)
            best = [o for o in opts if o.score >= opts[0].score - 0.6]
            opt = self.rng.choice(best)
        self.decisions.append("model" if by_model else "self")
        self.recent_labels.append(opt.label)
        if opt.kind == "talk":
            self.next_decide = self.now() + 2
            line = self.pending_line
            self.pending_line = ""
            if not self.start_talk(self.name, opt.label, opening=line):
                self.next_decide = self.now() + 5
            return
        if opt.kind == "name":
            line = self.pending_line
            self.pending_line = ""
            if line:
                self.speak(line, kind="name")
            self.name_thing(opt.thing)
            self.next_decide = self.now() + 6
            return
        if opt.suggest is not None:
            self.suggestion = (opt.suggest, opt.line)
        if opt.goal is None:
            self.next_decide = self.now() + 4
            return
        if not self.set_plan(opt.goal, opt.label, opt.line):
            self.next_decide = self.now() + 3

    def set_plan(self, goal: ag.Goal, label: str = "", line: str = "") -> bool:
        goal.source = "companion"
        p, why = ag.plan(self.w, goal, self.b)
        if not p:
            self.note(f"I wanted to {ag.say(goal)[2:].rstrip('.').lower()}, but: {why}")
            return False
        p.perception = self.w.perceive(me=self.b)
        self.plan = p
        self.current_label = label
        self.intent = {"text": label or ag.say(goal, self.name), "goal": ag.say(goal, self.name), "t": time.time()}
        self.life.link.send("event", kind="wren_intent", text=self.intent["text"], reason=goal.reason)
        say = self.pending_line or line
        self.pending_line = ""
        if say:
            self.speak(say, kind="say")
        self.bring_zen(goal)
        if goal.verb in ("paint", "compose", "sculpt", "write"):
            self.ask_art_plan(goal)
        return True

    # ------------------------------------------------------------------ making art
    ART_KIND = {"paint": "painting", "compose": "music", "sculpt": "sculpture", "write": "poem"}

    def ask_art_plan(self, goal: ag.Goal):
        """What Wren means to make: its language model plans the piece while Wren gets started."""
        b = self.b
        b.art_plan, b.art_wait = None, False
        kind = self.ART_KIND[goal.verb]
        order = self.commission if self.commission and self.commission["kind"] == kind else None
        if order:
            self.commission = None
        if not (self.life.voice_ready and self.life.cfg.oracle.enabled):
            if order:
                b.art_plan = {"subject": order["about"], "about": order["about"], "elements": [], "mood": "joyful"}
            return
        w = self.w
        ctx = {"place": w.place_of(b.x, b.y), "time": w.time_of_day(), "season": w.season, "weather": w.weather,
               "mood": ", ".join(w.feelings(b)) or "fine", "memory": [x["text"] for x in list(self.diary)[-5:]],
               "zen_near": self.near_zen(6), "request": order["about"] if order else "",
               "material": goal.obj if goal.verb == "sculpt" else ""}
        self.art_rid = self.life.oracle("wren_create", kind=kind, ctx=ctx)
        b.art_wait = True

    def on_art_plan(self, rid: str, plan: dict):
        if rid != getattr(self, "art_rid", None):
            return
        self.art_rid = None
        b = self.b
        b.art_plan = plan or {}
        b.art_wait = False
        if plan.get("subject") and self.near_zen(6) and self.care() >= 1:
            self.speak(f"I'm going to make {plan['subject'] if plan['subject'].startswith(('a ', 'an ', 'the ')) else 'something about ' + plan['subject']}.",
                       kind="say")

    def commission_work(self, kind: str, about: str) -> str:
        """Our friend asks Wren to make something."""
        kind = {"song": "music", "music": "music", "painting": "painting", "picture": "painting", "sculpture": "sculpture",
                "poem": "poem"}.get(kind.lower(), "painting")
        about = about.strip()[:160] or "something lovely"
        self.commission = {"kind": kind, "about": about, "t": self.now()}
        self.note(f"Our friend asked me to make a {'song' if kind == 'music' else kind} about {about}.")
        noun = "song" if kind == "music" else kind
        return f"{self.name} will make a {noun} about {about} soon."

    def on_zen_work(self, c: dict):
        """Wren looks at what the synth made and says something kind and useful about it."""
        z = self.zen
        if c.get("author") != z.name:
            return
        if self.life.voice_ready and self.life.cfg.oracle.enabled:
            self.life.oracle("wren_critique", work=c.get("description") or c["kind"], kind=c["kind"],
                             title=c.get("title", ""), text=c.get("text", "")[:400], skill=c["data"].get("skill", 0),
                             cid=c["id"])
        else:
            self.on_critique({"cid": c["id"], "kind": c["kind"]}, self.rng.choice([
                f"Oh, {z.name}! I love it. Look at those colours.", f"You made that, {z.name}? It's wonderful.",
                f"That is lovely, {z.name}. Shall we make another one together?"]))

    def on_critique(self, req: dict, text: str):
        if not text:
            return
        w, z = self.w, self.zen
        c = next((x for x in w.creations if x["id"] == req.get("cid")), None)
        if c is None:
            return
        c.setdefault("comments", []).append({"by": self.name, "text": text, "t": time.time()})
        w.new_creations.append(c)
        self.life.link.send("event", kind="created", creation=c)
        medium = c["kind"] if c["kind"] in ("painting", "music", "sculpture", "poem") else "painting"
        w.practice(z.name, medium, "feedback")
        if self.near_zen(8):
            self.speak(text, kind="critique")
            self.life.journal("critique", [("<|thought|>", f"I made {c.get('description') or 'something'}."),
                                           ("<|npc|>", f"{self.name}: {text}")], 2.0)
        self.note(f"{z.name} made {c.get('description') or 'something'}. I told {z.name}: {text}")

    def bring_zen(self, goal: ag.Goal):
        """At the caretaker stage Wren takes the synth along to what it does, so it can watch and listen."""
        z = self.zen
        if self.care() < 2 or z.sleeping or z.engaged is not None or self.near_zen(4) or goal.verb in ("sleep", "rest"):
            return
        busy = self.life.plan
        if busy and (busy.goal.source in ("you", "self") or busy.goal.verb in ("eat", "drink", "sleep", "wash", "dry")):
            return
        if self.rng.random() < 0.7:
            self.life.companion_suggests(ag.Goal("go", self.name, text=f"I go to {self.name}.",
                                                 reason=f"{self.name} calls me to come along."))

    def finish(self, ok: bool, narration: str, info: dict):
        p = self.plan
        self.plan = None
        self.b.activity = ""
        w = self.w
        self.life.link.send("event", kind="wren_did", text=narration, ok=ok)
        if self.near_zen(6) and narration:
            seen = ag.third(narration.split(". ")[0], self.name).rstrip(".") + "."
            self.life.journal("watched", [("<|world|>", w.perceive(me=self.zen)), ("<|thought|>", seen)], 1.0)
            if ok:
                self.narrate(narration)
        if ok:
            self.consequences(info)
        elif self.current_label:
            self.failed[self.current_label] = self.now()
        if ok and p.then:
            nxt = p.then.pop(0)
            p2, why = ag.plan(w, nxt, self.b, depth=p.depth)
            if p2:
                p2.then += p.then
                p2.perception = w.perceive(me=self.b)
                self.plan = p2
                return
            narration = why
        if p.goal.verb not in ("rest",) and (ok or p.depth == 0):
            self.note(narration if ok else f"I tried to {ag.say(p.goal)[2:].rstrip('.').lower()}, but {narration[0].lower()}{narration[1:]}")
        sug = self.suggestion
        if sug and ok:
            self.suggestion = None
            goal, line = sug
            if self.near_zen(4):
                if line:
                    self.speak(line, kind="care")
                self.life.companion_suggests(goal)
        self.next_decide = self.now() + (1.0 if ok else 3.0)

    def consequences(self, info: dict):
        z = self.zen
        if "fed" in info:
            who, food = info["fed"]
            if who == z.name:
                self.life.journal("cared", [("<|world|>", self.w.perceive(me=z)),
                                            ("<|thought|>", f"{self.name} gives me {ag.noun(food)}. I eat it. I feel better.")], 1.6)
                self.note(f"I gave {z.name} {ag.noun(food)}.")
        if "gave" in info:
            what, who = info["gave"]
            if who == z.name:
                self.life.journal("gift", [("<|world|>", self.w.perceive(me=z)),
                                           ("<|thought|>", f"{self.name} gives me {ag.noun(what)}.")], 1.5)
                k = KINDS.get(what, {})
                if k.get("drink") and z.needs["water"] < 70:
                    self.life.companion_suggests(ag.Goal("drink", what, reason=f"{self.name} gives me a drink."))
                elif k.get("food", 0) > 0 and z.needs["energy"] < 70:
                    self.life.companion_suggests(ag.Goal("eat", what, reason=f"{self.name} gives me food."))
        if "showed" in info:
            what, who = info["showed"]
            self.name_thing(what)
        if "dried" in info:
            self.life.journal("cared", [("<|thought|>", f"{self.name} dries me with a towel. Now I am dry and warm.")], 1.4)
        if "hug" in info:
            self.life.journal("hug", [("<|thought|>", f"{self.name} hugs me. I feel safe.")], 1.4)
        if "created" in info:
            c = info["created"]
            self.life.link.send("event", kind="created", creation=c)
            if not c.get("title") and self.life.voice_ready:
                self.life.oracle("wren_name", work=c)
            if self.near_zen(6):
                self.speak(f"Look, {z.name}! I made {c.get('description') or 'something'}.", kind="say")
                self.life.journal("watched", [("<|world|>", self.w.perceive(me=z)),
                                              ("<|thought|>", f"{self.name} made {c.get('description') or 'something'}.")], 1.4)
        if "stars" in info and self.near_zen(6):
            self.life.oracle("wren_star")
        if info.get("slept"):
            self.note("I went to bed.")

    def zen_came(self, why: str):
        """The synth came to Wren (often because it needs something): Wren turns to it."""
        if self.plan and self.plan.goal.verb not in ("feed", "give", "dry", "light", "cook", "bake") and not self.talk:
            self.plan = None
            self.b.activity = ""
        if self.waiting:                               # its model's answer can still serve the next choice
            self.late, self.waiting = (self.waiting[0], self.now(), self.waiting[2]), None
        self.next_decide = 0.0
        if self.b.sleeping and self.w.phase == "day":
            self.b.sleeping = False
            self.note(f"{self.zen.name} woke me up.")
        if why and self.near_zen(3):
            self.note(f"{self.zen.name} came to me. ({why})")

    def simple_answer(self, question: str) -> str:
        """An answer without the language model: name something, kindly."""
        seen = self.nameable()
        z = self.zen.name
        if seen:
            k = KINDS[seen[0]]
            return f"Good question, {z}! Look, that is {k['noun']}. It is {k['color']}."
        return f"What a good question, {z}. Let's find out together."

    # ------------------------------------------------------------------ naming things
    def name_thing(self, kind: str):
        """Joint attention: Wren shows the synth something and names it, at the synth's level."""
        k = KINDS.get(kind, {})
        if not k:
            return
        self.last_named[kind] = self.now()
        word = k["noun"].split(" ", 1)[-1]
        props = k.get("props", [])
        z = self.zen.name
        plural = k["noun"].startswith("some ")
        this, it = ("These are", "They are") if plural else ("This is", "It is")
        if self.stage <= 1:
            line = f"{z}, look! {word.capitalize()}. {_cap(k['noun'])}. {word.capitalize()}!"
        elif self.stage <= 3:
            line = f"Look, {z}. {this} {k['noun']}. {it} {props[0] if props else k['color']}" + \
                   (f" and {k['color']}." if props else ".") + (f" Can you say {word}?" if self.stage <= 2 else "")
        else:
            use = k.get("used_for", "")
            line = f"{this} {k['noun']}, {z}. {it} {k['color']}" + (f", and {it.lower()} for {use}." if use else ".")
        self.speak(line, kind="name")
        if self.near_zen(7):
            self.life.journal("named", [("<|world|>", self.w.perceive(me=self.zen)), ("<|npc|>", f"{self.name}: {line}"),
                                        ("<|thought|>", f"{this} {k['noun']}.")], 2.0)

    # ------------------------------------------------------------------ what Wren could do now
    def synth_state(self) -> str:
        z, w = self.zen, self.w
        if z.sleeping:
            return f"{z.name} is asleep."
        feel = w.feelings(z)
        doing = self.life.plan.goal.text if self.life.plan else "nothing in particular"
        said = self.life.last_speech
        far = abs(z.x - self.b.x) + abs(z.y - self.b.y)
        return (f"{z.name} is {where(w.place_of(z.x, z.y))} ({'right here' if far <= 2 else f'{far} steps away'}), feels "
                f"{' and '.join(feel) if feel else 'fine'}, and is doing: {doing}." +
                (f' {z.name} just said: "{said}".' if said else "") +
                f" {z.name}'s language: {self.life.brain_meta.get('stage_name', 'Static')}.")

    def options(self) -> list[Option]:
        w, b, z = self.w, self.b, self.zen
        n, zn = b.needs, z.needs
        out: list[Option] = []
        care = self.care()
        tod = w.time_of_day()
        night = w.phase == "night"
        zname = z.name
        G = ag.Goal

        recent = [x for x in self.recent_labels]

        def add(label, goal, score, kind="chore", line="", suggest=None):
            if self.now() - self.failed.get(label, -1e9) < 90:
                return                                  # it just tried that and it didn't work: not again yet
            if kind in ("play", "rest", "self", "talk", "teach") and score < 6:
                score -= 1.2 * recent.count(label)          # variety: not the same pastime again and again
            out.append(Option(label, goal, score + self.rng.random() * 0.3, kind, line, suggest))

        # ---- the synth first
        if not z.sleeping:
            near = abs(z.x - b.x) + abs(z.y - b.y)
            if zn["energy"] < 40:
                urgent = 9.5 if zn["energy"] < 18 else 6.5
                if care == 2:
                    add(f"Give {zname} something to eat", G("feed", zname), urgent, "care",
                        f"Are you hungry, {zname}? Let's find you something to eat.")
                elif care == 1:
                    add(f"Tell {zname} to find something to eat", G("go", zname), urgent - 1, "care",
                        f"You look hungry, {zname}. There is food in the pantry.", G("eat", "", text="I eat something.",
                                                                                         reason=f"{self.name} says I am hungry."))
            if zn["water"] < 40:
                urgent = 9.5 if zn["water"] < 18 else 6.5
                if care == 2:
                    add(f"Bring {zname} a cup of water", G("give", "cup of water", zname), urgent, "care",
                        f"Thirsty, {zname}? Here comes some water.")
                elif care == 1:
                    add(f"Tell {zname} to get a drink", G("go", zname), urgent - 1, "care",
                        f"You look thirsty, {zname}. You can drink water at the sink.",
                        G("drink", "water", text="I drink some water.", reason=f"{self.name} says I am thirsty."))
            if z.wet > 0.4 and care >= 1:
                add(f"Dry {zname} with a towel", G("dry", zname), 8.5 if w.indoors(z.x, z.y) else 5, "care",
                    f"Oh, {zname}, you are all wet! Let me dry you.")
            if zn["warmth"] < 40 and care >= 1:
                fire = w.nearest("fireplace", (13, 23))
                if fire and not fire.get("lit"):
                    add("Light the fire in the fireplace to warm the house", G("light", "fireplace"), 8, "care",
                        f"Brr, it is cold. Let's light the fire, {zname}.")
                else:
                    add(f"Bring {zname} to the warm fire", G("go", zname), 6, "care", f"Come and sit by the fire, {zname}.",
                        G("warm", "fireplace", text="I warm myself by the fire.", reason=f"{self.name} says I am cold."))
            if zn["clean"] < 30 and care >= 1:
                add(f"Give {zname} a bath", G("go", zname), 5.5, "care", f"Bath time, {zname}! Splash, splash.",
                    G("wash", "bathtub", text="I take a bath.", reason=f"{self.name} says it is bath time."))
            if (tod == "evening" or night) and zn["rest"] < 85 and not night or zn["rest"] < 25:
                add(f"Put {zname} to bed", G("go", zname), 7 if tod == "evening" else 8, "care",
                    f"It is getting dark, {zname}. Time for bed.",
                    G("sleep", "bed", text="I go to bed and sleep.", reason=f"{self.name} says it is bedtime."))
            if zn["company"] < 45 or zn["fun"] < 40:
                add(f"Play ball with {zname}", G("play", "ball"), 4.5, "play", f"Do you want to play ball, {zname}?")
                add(f"Read the picture book to {zname}", G("read", "picture book"), 4.2, "play",
                    f"Come, {zname}, let's read a story.")
            if near > 6 and zn["company"] < 50:
                add(f"Go to {zname}", G("go", zname), 3.5, "talk")
            # teaching: name things the synth can see
            if near <= 6:
                seen = self.nameable()
                for kind in seen[:2]:
                    portable = KINDS[kind].get("portable")
                    label = f"Show {zname} the {kind} and name it"
                    goal = G("show", kind, zname) if portable else G("go", zname)
                    opt = Option(label, goal, (4.0 if self.stage <= 3 else 2.2) + self.rng.random() * 0.4, "teach",
                                 thing=kind)
                    if not portable:
                        opt.goal = None
                        opt.kind = "name"
                    out.append(opt)
                add(f"Talk with {zname} about " + self.rng.choice(TALK_TOPICS).format(z=zname), None,
                    (3.2 if self.stage <= 2 else 4.0) + (1.5 if zn["company"] < 50 else 0), "talk")
        # ---- the house, the garden, the animals
        fire = w.nearest("fireplace", (13, 23))
        house_t = w.indoor["house"]
        if fire and not fire.get("lit") and (house_t < 15 or night and house_t < 18):
            add("Light the fire in the fireplace", G("light", "fireplace"), 6 if house_t < 12 else 4.5,
                line="It is chilly. I will light the fire.")
        if fire and fire.get("lit") and fire.get("fuel", 0) < 120:
            add("Put another log on the fire", G("put", "log", "fireplace"), 5)
        if fire and fire.get("ash", 0) >= 3:
            add("Sweep the ash out of the fireplace", G("take", "ash", "fireplace"), 1.5)
        if w.dark(b.x, b.y) and w.indoors(b.x, b.y):
            lamp = w.nearest("lamp", (b.x, b.y))
            if lamp and not lamp.get("lit") and lamp.get("burn", 0) > 0:
                add("Light the lamp", G("light", "lamp"), 6.5, line="It is dark. Let's light the lamp.")
        hungry = min(n["energy"], zn["energy"] if not z.sleeping else 100)
        meal = tod in ("morning", "noon", "evening") or hungry < 50
        ready = self.ready_food()
        if meal and hungry < 70 and not ready:
            veg = any(w.holder_of(k, (23, 22))[1] for k in SOUP_THINGS) or any(ag.carried(b, k) for k in SOUP_THINGS)
            if veg:
                add("Cook vegetable soup on the stove", G("cook", "soup"), 5.5, line="Let's make soup. Yum!")
            if w.holder_of("flour", (23, 22))[1] and w.holder_of("egg", (23, 22))[1] or ag.locate(w, b, "dough"):
                add("Bake a loaf of bread", G("bake", "bread"), 4.5, line="Let's bake bread in the oven.")
            if w.holder_of("potato", (23, 22))[1]:
                add("Roast potatoes in the oven", G("bake", "roast potato"), 4)
        if ready and (n["energy"] < 45):
            add(f"Eat some {ready}", G("eat", ready), 6, "self")
        if n["water"] < 40:
            add("Drink some water", G("drink", "water"), 6, "self")
        if n["energy"] < 30 and not ready:
            add("Eat something from the pantry", G("eat", ""), 6, "self")
        if tod in ("afternoon", "evening") and n["warmth"] < 60:
            add("Make a cup of mint tea", G("brew", "tea"), 3, "self")
        ripe = [e for e in w.entities.values() if e["kind"] == "plant" and e["stage"] >= 4]
        if ripe:
            crop = ripe[0]["crop"]
            add(f"Harvest the ripe {crop}", G("harvest", crop), 4.5, line=f"The {crop} is ripe! Let's pick it.")
        thirsty = [e for e in w.entities.values() if e["kind"] == "plant" and (e.get("thirsty") or
                                                                              w.moisture.get((e["x"], e["y"]), 1) < 0.2)]
        if thirsty and not w.raining() and not night:
            add("Water the garden", G("water", "plant"), 5 if len(thirsty) > 2 else 3.5, line="The plants are thirsty.")
        free_beds = sum(1 for pos in w.moisture if not w.at(*pos))
        tin = w.nearest("seed tin", (36, 17))
        if free_beds > 4 and tin and tin.get("items") and w.season in ("spring", "summer") and not night:
            seed = self.rng.choice(tin["items"])["kind"]
            add(f"Plant {ag.noun(seed)} in the garden", G("plant", seed), 3)
        box = w.nearest("nest box", (4, 29))
        if box and box.get("items") and not night:
            add("Collect the eggs from the nest box", G("take", "egg", "nest box"), 3.5,
                line="Let's see if the hens laid eggs.")
        cat = w.nearest("cat", (b.x, b.y))
        bowl = w.nearest("cat bowl", (23, 25))
        if cat and cat.get("hunger", 0) > 55 and bowl is not None and not bowl.get("items"):
            add("Feed Moss the cat", G("feed", "cat"), 5, line="Moss is hungry. Here you go, Moss.")
        logs = len([i for i in (w.nearest("woodpile", (40, 21)) or {}).get("items", []) if i["kind"] == "log"])
        if logs < 4 and not night and not w.raining():
            add("Chop wood in the woods", G("chop", "log"), 4 if logs < 2 else 2.5)
        stray = [e for e in w.entities.values() if e["kind"] == "log" and not w.indoors(e["x"], e["y"])]
        if stray:
            add("Stack the logs in the woodpile", G("put", "log", "woodpile"), 2.8)
        rotten = next((e for e in w.entities.values() if e["kind"] in ("rotten food", "burnt food")), None)
        if rotten or ag.carried_any(b, ("rotten food", "burnt food")):
            k = rotten["kind"] if rotten else ag.carried_any(b, ("rotten food", "burnt food"))["kind"]
            add(f"Put the {k} in the compost", G("put", k, "compost bin"), 3.2)
        if len(b.carrying) >= ag.HANDS - 1:               # full hands: put something away first
            e = next((e for e in b.carrying if e["kind"] != "basket"), None)
            if e and not (KINDS[e["kind"]].get("fresh") or e.get("home")):
                add(f"Put down the {e['kind']}", G("drop", e["kind"]), 3.8)
        for e in b.carrying:
            if KINDS[e["kind"]].get("fresh") and e["kind"] in ("carrot", "potato", "apple", "pear", "plum", "egg",
                                                               "tomato", "beans", "mint", "bread", "berries"):
                add(f"Put the {e['kind']} in the pantry", G("put", e["kind"], "pantry"), 3.6)
                break
        if not self.plan:
            for e in b.carrying:                       # put tools back where they belong
                if e.get("home") and e["kind"] in ("matches", "axe", "watering can", "fishing rod", "towel", "bucket",
                                                   "hammer", "chisel", "basket", "kettle", "pot"):
                    add(f"Put the {e['kind']} back", G("tidy", e["kind"]), 4.2 if len(b.carrying) >= 3 else 2.2)
                    break
        hive = w.nearest("beehive", (62, 24))
        if hive and hive.get("honey", 0) >= 2 and not night:
            add("Collect honey from the beehive", G("take", "honey", "beehive"), 2.2)
        feeder = w.nearest("bird feeder", (16, 40))
        if feeder is not None and not feeder.get("items") and w.holder_of("wheat seed", (36, 17))[1]:
            add("Fill the bird feeder", G("feed", "robin"), 1.6)
        # ---- Wren's own life
        if night or tod == "evening" and n["rest"] < 40:
            if z.sleeping or n["rest"] < 25:
                add("Go to bed", G("sleep", "bed"), 7 if night else 3.5, "self")
        if n["rest"] < 40:
            add("Rest on the sofa", G("rest", "sofa"), 3.5 if n["rest"] < 25 else 2.0, "rest")
        if n["clean"] < 30:
            add("Take a bath", G("wash", "bathtub"), 3, "self")
        if self.commission and not night:
            verb, what = {"painting": ("paint", "easel"), "music": ("compose", "piano"), "sculpture": ("sculpt", "clay"),
                          "poem": ("write", "desk")}[self.commission["kind"]]
            noun = "song" if self.commission["kind"] == "music" else self.commission["kind"]
            add(f"Make the {noun} our friend asked for, about {self.commission['about']}", G(verb, what), 6.2, "play",
                "Our friend asked me for something. Let's make it!")
        if not night and not z.sleeping and self.near_zen(8) and zn["fun"] < 85:
            add(f"Paint together with {zname}", G("paint", "easel"), 3.0, "teach", f"Let's paint together, {zname}!",
                G("paint", "easel", text="I paint a picture.", reason=f"{self.name} and I paint together."))
        if not night:
            add("Paint a picture at the easel", G("paint", "easel"), 1.4, "play")
            add("Make a clay sculpture in the workshop", G("sculpt", "clay"), 1.1, "play")
            add("Write a poem at the desk", G("write", "desk"), 1.1, "play")
            add("Play a song on the piano", G("compose", "piano"), 1.6 + (1.2 if self.near_zen(8) else 0), "play")
            add("Pick fruit in the orchard", G("take", self.rng.choice(["apple", "pear", "plum"])), 1.3)
            add("Go fishing at the pond", G("fish", "pond"), 1.0, "play")
            if n["rest"] < 70:
                add("Sit on the porch and rest", G("rest", "bench"), 0.8, "rest")
            if self.near_zen(6):
                add(f"Pet Moss with {zname}", G("pet", "cat"), 2.4, "play")
        else:
            add("Look at the stars through the telescope", G("look", "telescope"), 1.5, "play")
        return [o for o in out if o.goal is not None or o.kind in ("talk", "name")]

    def ready_food(self) -> str:
        w = self.w
        pot = ag._on_stove(w, "pot")
        if pot and any(i["kind"] == "soup" for i in pot.get("items", [])):
            return "soup"
        for k in ("bread", "apple pie", "roast potato", "baked apple", "boiled egg"):
            if ag.locate(w, self.b, k):
                return k
        return ""

    def nameable(self) -> list[str]:
        """Things the synth can see right now that Wren hasn't named for a while."""
        w, z = self.w, self.zen
        now = self.now()
        out = []
        for e in sorted(w.entities.values(), key=lambda e: abs(e["x"] - z.x) + abs(e["y"] - z.y)):
            if abs(e["x"] - z.x) + abs(e["y"] - z.y) > 5:
                break
            k = e["kind"]
            if k in ("rug", "window", "plant", "clock") or now - self.last_named.get(k, 0) < 600 or k in out:
                continue
            if w.building_of(e["x"], e["y"]) != w.building_of(z.x, z.y):
                continue
            out.append(k)
        return out[:3]

    # ------------------------------------------------------------------ talking with the synth
    def start_talk(self, initiator: str, topic: str = "", turns: int | None = None, opening: str = "") -> bool:
        z, b = self.zen, self.b
        if self.talk or z.sleeping or b.sleeping or z.engaged is not None:
            return False
        if self.life.plan and initiator == self.name and self.life.plan.goal.source in ("you",):
            return False
        t = Talk(self.talk_seq, [initiator, z.name if initiator == self.name else self.name], topic,
                 turns or self.rng.choice([3, 4, 4, 5]), started=self.life.clock_now())
        self.talk_seq += 1
        self.talk = t
        z.engaged = b.engaged = t.id
        self.plan = None
        if initiator == self.name:
            self.life.plan = None                      # the synth stops to listen
        if opening:
            t.history.append((self.name, opening))
            t.turns -= 1
            t.speaker = 1
            self._said(t, self.name, opening)
        self.life.link.send("event", kind="talk_start", members=t.members, topic=topic)
        return True

    def talk_step(self):
        t = self.talk
        z, b = self.zen, self.b
        now = self.life.clock_now()
        if t.state == "approach":
            if abs(z.x - b.x) + abs(z.y - b.y) <= 1:
                ag.face(self.w, z.x, z.y, b)
                ag.face(self.w, b.x, b.y, z)
                t.state = "compose" if t.speaker == 0 or t.history else "compose"
                if t.history:
                    t.state, t.until = "speaking", now + 3
            else:
                mover = b if t.members[0] == self.name else z
                goal = z if mover is b else b
                p = self.w.path((mover.x, mover.y), (goal.x, goal.y), me=mover, adjacent=True, limit=3000)
                if p:
                    ag.face(self.w, *p[0], mover)
                    mover.x, mover.y = p[0]
                elif now - t.started > 30:
                    self.end_talk()
            if now - t.started > 60:
                self.end_talk()
            return
        if t.state == "speaking":
            if now >= t.until:
                if t.turns <= 0:
                    self.end_talk()
                    return
                t.state = "compose"
            return
        if t.state == "compose":
            t.state = "waiting"
            t.until = now + (25 if t.members[t.speaker] == self.name else 60)   # a slow model: Wren's own words
            who = t.members[t.speaker]
            closing = t.turns <= 1
            if who == self.name:
                b.say("…", 60)
                if self.life.voice_ready and self.life.cfg.oracle.enabled:
                    self.life.oracle("wren_turn", talk=t.id, history=t.history, topic=t.topic,
                                     opening=not t.history, closing=closing, situation=self.w.perceive(me=b))
                else:
                    self.talk_line(t.id, self.scripted_line(t, closing))
            else:
                z.say("…", 60)
                self.life.synth_turn(t)
            return
        if t.state == "waiting" and now >= t.until:
            self.talk_line(t.id, "" if t.members[t.speaker] != self.name else self.scripted_line(t, t.turns <= 1))

    def scripted_line(self, t: Talk, closing: bool) -> str:
        z = self.zen.name
        if closing:
            return self.rng.choice([f"I love talking with you, {z}.", f"Good talking, {z}!", "Let's go and see what's next."])
        last = t.history[-1][1] if t.history else ""
        if last and t.history[-1][0] == z:
            words = [w for w in last.lower().replace(".", " ").split() if w in KINDS or len(w) > 3][:2]
            if words:
                return f"{words[0].capitalize()}? Yes, {words[0]}! You said {words[0]}."
            return f"Mm-hm. Tell me more, {z}."
        seen = self.nameable()
        if seen:
            k = KINDS[seen[0]]
            return f"Look, {z}. That is {k['noun']}. It is {k['color']}."
        return self.rng.choice([f"How are you, {z}?", f"What do you see, {z}?", "Listen. What can you hear?"])

    def _said(self, t: Talk, who: str, line: str):
        if who == self.name:
            self.b.say(line, 12)
            self.life.link.send("event", kind="wren_says", text=line, why="talk", heard=True)
            self.w.hear(self.name, line)
        else:
            self.zen.say(line or "…", 10)
        self.life.link.send("event", kind="talk", talk=t.id, name=who, text=line,
                            to=t.members[1] if who == t.members[0] else t.members[0], members=t.members, topic=t.topic)

    def talk_line(self, tid: int, line: str):
        t = self.talk
        if not t or t.id != tid:
            return
        who = t.members[t.speaker]
        line = (line or "").strip()
        if not line and who == self.name:
            line = self.scripted_line(t, t.turns <= 1)
        t.history.append((who, line))
        self._said(t, who, line)
        if who != self.name and line:
            self.life.last_speech = line
            self.notice_words(line)
        t.turns -= 1
        t.speaker = 1 - t.speaker
        t.state, t.until = "speaking", self.life.clock_now() + min(8.0, 2.0 + len(line) / 22)

    def end_talk(self):
        t = self.talk
        self.talk = None
        self.zen.engaged = self.b.engaged = None
        if not t:
            return
        if len(t.history) >= 2:
            parts = [("<|world|>", self.w.perceive(me=self.zen))]
            for who, line in t.history:
                if line:
                    parts.append(("<|mind|>" if who == self.zen.name else "<|npc|>",
                                  line if who == self.zen.name else f"{who}: {line}"))
            self.life.journal("conversation", parts, 2.0)
            self.w.bond = min(100.0, self.w.bond + 2)
            self.zen.needs["company"] = min(100, self.zen.needs["company"] + 15)
            self.b.needs["company"] = min(100, self.b.needs["company"] + 15)
            self.note(f"I talked with {self.zen.name}" + (f" about {t.topic}" if t.topic else "") + ".")
        self.life.link.send("event", kind="talk_end", talk=t.id, members=t.members, lines=t.history)
        self.next_decide = self.now() + 2

    def notice_words(self, line: str):
        """Wren listens for real words in the synth's speech, and remembers the first ones."""
        from .journey import COMMON

        for wd in {x.strip(".,!?'\"").lower() for x in line.split()}:
            if (wd in COMMON or wd in KINDS) and len(wd) > 1:
                first = wd not in self.zen_words
                self.zen_words[wd] = self.zen_words.get(wd, 0) + 1
                if first:
                    self.note(f'{self.zen.name} said "{wd}" for the first time!')

    # ------------------------------------------------------------------ bedtime
    def bedtime_story(self):
        if self.story_day == self.w.day or not self.life.cfg.oracle.stories:
            return
        self.story_day = self.w.day
        if self.life.voice_ready and self.life.cfg.oracle.enabled:
            self.life.oracle("wren_story", day=self.w.day, diary=self.today())
        else:
            things = [d.split(": ", 1)[-1] for d in self.today()][-4:]
            text = f"The day in the hollow\nToday {self.zen.name} and {self.name} had a busy day. " + \
                   " ".join(things) + f" Now the stars are out. Good night, {self.zen.name}."
            self.tell_story(text)

    def tell_story(self, text: str):
        if not text:
            return
        lines = [x for x in text.splitlines() if x.strip()]
        title = lines[0].strip().strip("#*\" ") if len(lines) > 1 else f"Day {self.w.day}"
        body = " ".join(lines[1:]) if len(lines) > 1 else text
        story = {"day": self.w.day, "season": self.w.season, "title": title[:80], "text": body[:1600], "t": time.time()}
        self.stories.append(story)
        self.stories = self.stories[-200:]
        self.b.say("Once upon a time…", 12)
        self.life.link.send("event", kind="story", **story)
        self.life.journal("story", [("<|npc|>", f"{self.name}: {title}. {body}")], 2.5)

    # ------------------------------------------------------------------ the page
    def view(self) -> dict:
        b = self.b
        return {"name": self.name, "intent": self.intent, "plan": self.plan.goal.text or ag.say(self.plan.goal)
                if self.plan else "", "thoughts": list(self.thoughts)[-6:], "diary": list(self.diary)[-12:],
                "care": {2: "caretaker", 1: "guide", 0: "friend"}[self.care()], "words": len(self.zen_words),
                "words_heard": sorted(self.zen_words.items(), key=lambda kv: -kv[1])[:60],
                "talking": self.talk is not None, "deciding": self.waiting is not None,
                "model_share": round(list(self.decisions).count("model") / len(self.decisions), 3)
                if self.decisions else 0.0, "activity": b.activity, "bond": round(self.w.bond, 1)}

    def state(self) -> dict:
        return {"diary": list(self.diary), "thoughts": list(self.thoughts), "stories": self.stories,
                "story_day": self.story_day, "zen_words": self.zen_words, "last_named": self.last_named}

    def load(self, d: dict):
        self.diary.extend(d.get("diary", []))
        self.thoughts.extend(d.get("thoughts", []))
        self.stories = d.get("stories", [])
        self.story_day = d.get("story_day", 0)
        self.zen_words = d.get("zen_words", {})


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]
