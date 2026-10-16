"""The World process: where the synth lives.

It runs the simulation, keeps the synth's brain (the latest one the Academy published), and lets
that brain decide what it does, think out loud and talk. Everything it lives through is written
to its journal for the Academy to study. Nothing here trains; when night falls it goes to bed, its
brain rests, and the Academy gets the GPU to itself.
"""
from __future__ import annotations

import itertools
import json
import queue
import random
import threading
import time
from collections import deque
from pathlib import Path

from .community import Community
from .config import AdaConfig, cpu_threads
from .ontology import KINDS, NPCS
from .proc import Link, append_jsonl, pick_device, write_json
from .world import agent as ag
from .world.sim import World, where as where_words

ROLE_TOKENS = ["<|endoftext|>", "<|thought|>", "<|user|>", "<|mind|>", "<|oracle|>", "<|world|>", "<|intent|>", "<|npc|>"]


def run(name: str, root: str, inbox, outbox):
    folder = Path(root) / name
    link = Link("world", inbox, outbox, folder)
    life = None
    try:
        life = Life(folder, link)
        life.loop()
    except Exception as e:  # pragma: no cover
        link.crash(e)
        raise
    finally:
        if life is not None:
            life.speaker.stop()


class Speaker:
    """Runs Ada's brain on its own thread, so the world never waits for her words.

    Requests (load a new brain, a reply to you, something to say, an intention, a thought) are
    queued by urgency and answered one at a time; the World collects the answers each loop. With
    threaded=False (tests) a request is answered on the spot."""

    PRIORITY = {"load": 0, "chat": 1, "speech": 2, "intent": 3, "thought": 4}

    def __init__(self, life: "Life", threaded: bool = True):
        self.life, self.threaded = life, threaded
        self.jobs: queue.PriorityQueue = queue.PriorityQueue()
        self.done: queue.Queue = queue.Queue()
        self.busy: dict[str, int] = {}
        self.seq = itertools.count()
        self.thread = None
        if threaded:
            self.thread = threading.Thread(target=self._run, name="ada-brain", daemon=True)
            self.thread.start()

    def stop(self, timeout: float = 30.0):
        """Let the current job finish and end the thread. Python must not exit while the brain
        thread is inside PyTorch: that aborts the whole process."""
        if self.thread is not None and self.thread.is_alive():
            self.jobs.put((-1, -1, None, None, None, 0.0))
            self.thread.join(timeout)

    def pending(self, kind: str) -> bool:
        return self.busy.get(kind, 0) > 0

    def ask(self, kind: str, work, callback):
        """Run work() (which uses the brain) and later call callback(result) on the World's thread."""
        self.busy[kind] = self.busy.get(kind, 0) + 1
        if not self.threaded:
            self.busy[kind] -= 1
            callback(work())
            return
        self.jobs.put((self.PRIORITY.get(kind, 5), next(self.seq), kind, work, callback, time.perf_counter()))

    def _run(self):
        perf = self.life.link.perf
        while True:
            _, _, kind, work, callback, queued = self.jobs.get()
            if kind is None:
                return
            perf.add("brain: waiting in line", time.perf_counter() - queued)
            t = time.perf_counter()
            try:
                result = work()
            except Exception as e:   # a failed thought must not take the World down
                self.life.link.warn(f"{self.life.cfg.name}'s brain failed while working on '{kind}': {type(e).__name__}: {e}")
                result = None
            perf.add(f"brain: {kind}", time.perf_counter() - t)
            self.done.put((kind, callback, result))

    def deliver(self):
        while True:
            try:
                kind, callback, result = self.done.get_nowait()
            except queue.Empty:
                return
            self.busy[kind] -= 1
            if result is not None:
                callback(result)


class Life(Community):
    def __init__(self, folder: Path, link: Link, with_brain: bool = True, threaded: bool = True):
        from .tokenizer import make_tokenizer

        self.folder, self.link = folder, link
        self.cfg = AdaConfig.load(folder / "config.json")
        self.tok = make_tokenizer(self.cfg.tokenizer)
        self.stop_ids = {self.tok[r] for r in ROLE_TOKENS}
        self.with_brain = with_brain
        self.device = pick_device(self.cfg.world.device) if with_brain else None
        self.use_cpu_threads()
        self.brain = None
        self.brain_version = 0
        self.brain_meta: dict = {}
        self.rng = random.Random()
        self.world = World(name=self.cfg.name)
        self.greeted: dict[str, float] = {}           # villager -> when they last greeted the synth
        self.last_greet = 0.0
        self.speech_queue: list[tuple[float, str, str]] = []   # (when, villager, line): banter, said in turn
        self.plan: ag.Plan | None = None
        self.decisions: deque = deque(maxlen=60)      # "self" | "needs" | "you"
        self.memory: list[int] = []
        self.thoughts: deque = deque(maxlen=120)
        self.chat_log: list[dict] = []
        self.next_thought = time.time() + 3
        self.asked_at = 0.0
        self.pending: dict[str, dict] = {}            # oracle requests in flight
        self.last_intent: dict = {}
        self.bedtime = False
        self.intent_wait: tuple | None = None          # (request number, since, perception) while she finds words
        self.intent_seq = itertools.count()
        self.speaker = Speaker(self, threaded and with_brain)
        self.init_community()
        self.load()

    # ------------------------------------------------------------------ brain
    @property
    def day_seconds(self) -> float:
        return self.cfg.world.day_minutes * 60

    @property
    def night_seconds(self) -> float:
        return self.cfg.world.night_minutes * 60

    def maybe_load_brain(self):
        meta_path = self.folder / "brain" / "latest.json"
        if not self.with_brain or not meta_path.exists():
            return
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return
        if meta.get("version", 0) <= self.brain_version or self.speaker.pending("load"):
            return
        self.speaker.ask("load", lambda: self._load_brain(meta), self._use_brain)

    def use_cpu_threads(self):
        """On the CPU her brain uses its share of the physical cores (see config.cpu_threads)."""
        if self.device is None or self.device.type != "cpu":
            return
        import torch

        n = cpu_threads(self.cfg)["world"]
        if torch.get_num_threads() != n:
            torch.set_num_threads(n)
            self.link.log(f"{self.cfg.name}'s brain thinks on the CPU with {n} threads")

    def _load_brain(self, meta: dict):
        """On the brain thread: read and prepare the published weights."""
        import torch

        from .config import BrainConfig
        from .model import Brain

        blob = torch.load(self.folder / "brain" / "latest.pt", map_location="cpu", weights_only=False)
        bc = BrainConfig(**blob["brain"])
        brain = Brain(bc)
        dtype = torch.bfloat16 if self.device.type == "cuda" else torch.float32
        brain.load_state_dict({k: v.float() for k, v in blob["weights"].items()})
        return brain.to(self.device, dtype).eval(), meta

    def _use_brain(self, loaded):
        brain, meta = loaded
        self.brain = brain
        self.brain_version, self.brain_meta = meta["version"], meta
        self.link.send("event", kind="brain", meta=meta)
        self.link.log(f"living with brain v{meta['version']} (step {meta['step']}, {meta.get('stage_name', '')})")

    def say_async(self, kind: str, parts, callback, prefix: str = "", max_new: int = 24, temperature: float = 0.8,
                  stop_text=None, ids: list[int] | None = None):
        """Ask her brain for words after a prompt; callback(text, tokens, raw) runs later on this thread."""
        from .tokenizer import encode_parts

        prompt = ids if ids is not None else encode_parts(self.tok, parts) + self.tok.encode(prefix)

        def work():
            brain = self.brain
            if brain is None:
                return []
            return brain.generate(prompt, max_new, temperature, 0.95, stop=self.stop_ids, n_real=self.tok.n_real,
                                  stop_text=stop_text)

        def done(out):
            toks = [t for t, _, _ in out]
            callback(prefix + self.tok.decode(toks), [[self.tok.token_str(t), round(p, 3)] for t, p, _ in out], out)

        self.speaker.ask(kind, work, done)

    # ------------------------------------------------------------------ journal
    def journal(self, kind: str, parts, weight: float = 1.0):
        parts = [[r, t] for r, t in parts if t]
        if parts:
            append_jsonl(self.folder / "journal.jsonl", {"t": time.time(), "kind": kind, "parts": parts,
                                                         "weight": round(weight, 3)})

    def oracle(self, purpose: str, **payload) -> str:
        """Ask the Hub's Oracle something; the answer arrives later as an 'oracle_reply' command."""
        rid = f"w{time.time_ns()}"
        self.pending[rid] = {"purpose": purpose, "rid": rid, **payload}
        self.link.send("oracle", rid=rid, purpose=purpose, payload=payload,
                       stage=self.brain_meta.get("stage_name", "Static"))
        return rid

    # ------------------------------------------------------------------ time of day
    def clock(self, dt: float):
        w = self.world
        if w.phase == "day" and w.phase_t >= self.day_seconds and not self.bedtime:
            self.bedtime = True
            w.note("The sun is setting. It is time to go to bed.")
            self.set_plan(ag.Goal("sleep", "bed", text="I go to bed and sleep.", reason="It is getting dark. I am sleepy.",
                                  source="needs"))
        if self.bedtime and (w.ada.sleeping or w.phase_t >= self.day_seconds + 90):
            self.nightfall()
        if w.phase == "night" and w.phase_t >= self.night_seconds:
            self.dawn()

    def nightfall(self):
        w, a = self.world, self.world.ada
        bed = w.nearest("bed", (a.x, a.y))
        if bed and abs(bed["x"] - a.x) + abs(bed["y"] - a.y) > 1:
            a.x, a.y = bed["x"] + 1, bed["y"]            # too far from bed: she's carried home asleep
        a.sleeping, self.plan, self.bedtime = True, None, False
        w.phase, w.phase_t = "night", 0.0
        w.note(f"Night falls. {self.cfg.name} sleeps, and while it sleeps it studies.")
        self.link.send("phase", phase="night", day=w.day)
        self.save()

    def dawn(self):
        w = self.world
        w.day += 1
        w.phase, w.phase_t = "day", 0.0
        w.ada.sleeping = False
        w.needs["rest"] = 100.0
        w.note(f"Good morning! Day {w.day} begins.")
        self.link.send("phase", phase="day", day=w.day)
        self.maybe_load_brain()

    # ------------------------------------------------------------------ deciding and doing
    def set_plan(self, goal: ag.Goal) -> bool:
        p, why = ag.plan(self.world, goal)
        if not p:
            self.world.note(why)
            return False
        p.perception = self.world.perceive(self.day_seconds)
        p.wellbeing_before = self.world.wellbeing()
        self.plan = p
        self.last_intent = {"text": p.goal.text or ag.say(p.goal), "source": p.goal.source,
                            "reason": p.goal.reason, "t": time.time()}
        self.link.send("event", kind="intent", **self.last_intent)
        return True

    def decide(self):
        """Ask her brain what she wants to do. While it finds words she waits; after 3 s her needs decide."""
        w = self.world
        if self.intent_wait:
            if time.time() - self.intent_wait[1] > 3.0:
                perception = self.intent_wait[2]
                self.intent_wait = None
                self.choose(perception, "", [])
            return
        perception = w.perceive(self.day_seconds)
        req = next(self.intent_seq)
        self.intent_wait = (req, time.time(), perception)
        self.say_async("intent", [("<|world|>", perception), ("<|intent|>", "")],
                       lambda text, toks, _: self.on_intent(req, perception, text, toks), prefix="I", max_new=16,
                       temperature=self.cfg.world.intent_temperature,
                       stop_text=lambda ids: "." in self.tok.decode(ids[-2:]))

    def on_intent(self, req: int, perception: str, own: str, toks):
        if not self.intent_wait or self.intent_wait[0] != req or self.plan or self.world.ada.sleeping:
            return                     # too late: her needs already chose, or she fell asleep
        self.intent_wait = None
        self.choose(perception, own, toks)

    def choose(self, perception: str, own: str, toks):
        w = self.world
        own = own.strip() if self.brain is not None else ""
        goal = ag.parse(own) if own else None
        if goal and goal.verb != "wait":
            goal.source, goal.text = "self", own.split(".")[0] + "."
            if self.set_plan(goal):
                self.decisions.append("self")
                return
        g = ag.drives(w, self.rng, time.time() - self.asked_at < 300,
                      any(e["kind"] == "book" and e["id"] not in w.read_books for e in w.entities.values()))
        if own:
            self.link.send("event", kind="tried", text=own, tokens=toks)
        if self.set_plan(g):
            self.decisions.append("needs")
        else:
            self.set_plan(ag.Goal("wait", text="I rest for a while.", source="needs"))

    def walk(self):
        """Follow the synth's plan one step, or act when there."""
        result = self.advance(self.world.ada, self.plan)
        if result is not None:
            self.finish(*result)

    def advance(self, a, p):
        """One step of any mind's plan. Returns (ok, narration, info) when it is done, else None."""
        w = self.world
        p.ticks += 1
        tp = ag.target_pos(w, p)
        if tp is None or p.ticks > 400:
            return False, "I could not get there.", {}
        tx, ty, adjacent = tp
        arrived = (abs(tx - a.x) + abs(ty - a.y) == 1) if adjacent else ((a.x, a.y) == (tx, ty))
        if adjacent and (a.x, a.y) == (tx, ty):
            arrived = True
        if arrived:
            ag.face(w, tx, ty, a)
            return ag.act(w, p, a)
        if not p.route or p.ticks % 12 == 0:
            p.route = (w.path((a.x, a.y), (tx, ty), me=a, adjacent=adjacent)
                       or w.path((a.x, a.y), (tx, ty), me=a, adjacent=adjacent, avoid=False) or [])
            if not p.route:
                return (False, "Something is in the way.", {}) if p.ticks > 8 else None
        nx, ny = p.route[0]
        blocker = next((b for b in w.beings() if b is not a and (b.x, b.y) == (nx, ny)), None)
        if blocker is not None:
            if blocker is w.visitor or blocker.engaged is not None or blocker is w.ada:
                if p.ticks % 6 == 0:
                    p.route = []                     # find a way around
                return None
            blocker.x, blocker.y = a.x, a.y          # a villager steps aside
        p.route.pop(0)
        ag.face(w, nx, ny, a)
        a.x, a.y = nx, ny
        if a is w.ada:
            place = w.place_of(nx, ny)
            if place not in w.visited:
                w.visited.add(place)
                w.note(f"I arrive in the {place} for the first time.")
        return None

    def finish(self, ok: bool, narration: str, info: dict):
        w, p = self.world, self.plan
        self.plan = None
        g = p.goal
        key = f"{g.verb}:{g.obj}"
        novelty = 0.0
        if ok and key not in w.firsts:
            w.firsts.add(key)
            novelty = 1.0
        reward = (w.wellbeing() - p.wellbeing_before) * 10 + novelty + (0.2 if ok else -0.3)
        w.note(narration)
        self.link.send("event", kind="did", text=narration, ok=ok, source=g.source, reward=round(reward, 2))
        weight = (2.0 if g.source in ("self", "you") else 1.0) + max(0.0, reward)
        if not ok:
            weight = 0.3 if g.source == "self" else 0.0
        if weight > 0:
            self.journal("deed", [("<|world|>", p.perception), ("<|thought|>", g.reason),
                                  ("<|intent|>", g.text or ag.say(g)), ("<|thought|>", narration)], weight)
        self.consequences(info, p.perception)

    def npc_context(self, who: str) -> dict:
        w = self.world
        p = w.people.get(who)
        q = next((q for q in w.quests if q["giver"] == who), None)
        return {"time": w.time_of_day(self.day_seconds), "season": w.season, "weather": w.weather,
                "where": where_words(w.place_of(p.x, p.y)) if p else "in the village",
                "friendship": round(w.friends.get(who, 0)),
                "quest": (KINDS[q["want"]]["noun"] if q["count"] == 1 else f"{q['count']} of {q['want']}") if q else ""}

    def villager_reacts(self, who: str, kind: str, said: str = "", **ctx):
        """A villager has something to say to the synth: it starts a conversation (or, if one of them is
        busy, just says it)."""
        topic = {"gift": f"thanking {self.cfg.name} for {ctx.get('gift', 'a present')}",
                 "quest": f"thanking {self.cfg.name} for doing what they asked; they gave it {ctx.get('reward', 'some')} coins",
                 "greet": "saying hello and asking how it is"}.get(kind, "")
        if topic and self.start_talk(who, self.cfg.name, topic, turns=random.choice([2, 3])):
            return
        self.oracle("npc", npc=who, said=said, kind=kind, ctx=self.npc_context(who) | ctx)

    def consequences(self, info: dict, perception: str):
        """Things that need words from the brain, a villager or the Oracle."""
        w = self.world
        if "quest_done" in info:
            q = info["quest_done"]
            self.link.send("event", kind="quest", text=f"Quest done for {q['giver']}: +{q['reward']} coins", quest=q)
            self.villager_reacts(q["giver"], "quest", reward=q["reward"])
        elif "gave" in info and info["gave"][1] in NPCS:
            self.villager_reacts(info["gave"][1], "gift", gift=KINDS[info["gave"][0]]["noun"])
        elif "talk" in info and info["talk"] in NPCS and self.start_talk(self.cfg.name, info["talk"]):
            pass                                         # a conversation, turn by turn
        elif "talk" in info:
            who = info["talk"]

            def spoken(line, toks, _):
                line = line.strip()
                if line:
                    w.ada.say(line)
                if who == "friend":
                    self.link.send("event", kind="ada_says", text=line, to="friend")
                else:
                    self.villager_reacts(who, "talk", said=line)

            self.say_async("speech", [("<|world|>", perception), ("<|mind|>", "")], spoken, max_new=20,
                           temperature=self.cfg.world.reply_temperature)
        if "created" in info:
            self.link.send("event", kind="created", creation=info["created"])
            self.synth_creates(info["created"])
        if "ask" in info:
            self.asked_at = time.time()
            self.oracle("answer", question=info["ask"])
        if "learn" in info:
            from .oracle import TOPICS

            self.oracle("lesson", topic=self.rng.choice(TOPICS), ctx=self.npc_context("Sage"))
        if "read" in info:
            book = info["read"]
            w.read_books.add(book["id"])
            if book.get("text"):
                self.read_text(book)
            else:
                self.oracle("book", entity=book["id"], kind=book["kind"])
        if "stars" in info:
            self.oracle("fact", topic="the stars, the moon and the planets")

    def neighbours(self):
        """Villagers who pass the synth like to stop and say hello."""
        w, a, now = self.world, self.world.ada, time.time()
        if a.sleeping or a.engaged is not None or now - self.last_greet < 30:
            return
        for name, p in w.people.items():
            if p.sleeping or p.engaged is not None or abs(p.x - a.x) + abs(p.y - a.y) > 3 \
                    or now - self.greeted.get(name, 0) < 300:
                continue
            self.greeted[name] = self.last_greet = now
            self.villager_reacts(name, "greet")
            break

    def banter(self):
        """Two villagers near each other start a conversation."""
        w = self.world
        free = [(n, p) for n, p in w.people.items() if not p.sleeping and p.engaged is None]
        pairs = [(a, b) for i, (a, pa) in enumerate(free) for b, pb in free[i + 1:]
                 if abs(pa.x - pb.x) + abs(pa.y - pb.y) <= 6]
        if not pairs:
            return False
        a, b = self.rng.choice(pairs)
        return self.start_talk(a, b)

    def read_text(self, book: dict):
        text = book["text"]
        self.world.note("The book says: " + text[:140] + ("…" if len(text) > 140 else ""))
        self.link.send("event", kind="read", text=text[:1500])
        self.journal("reading", [("<|thought|>", "I read a book. It says:"), ("<|oracle|>", text)], 1.5)

    # ------------------------------------------------------------------ thoughts and talk
    def think(self):
        cfg = self.cfg.world
        parts = []
        if cfg.thoughts_grounded:
            parts.append(("<|world|>", self.world.perceive(self.day_seconds)))
        from .tokenizer import encode_parts

        if self.speaker.pending("thought"):
            return
        ids = self.memory[-192:] + encode_parts(self.tok, parts) + [self.tok["<|thought|>"]]

        def thought(text, toks, out):
            gen = [t for t, _, _ in out]
            self.memory = (self.memory + [self.tok["<|thought|>"]] + gen)[-800:]
            th = {"text": text, "tokens": toks, "brain": self.brain_version, "t": time.time()}
            self.thoughts.append(th)
            self.link.send("event", kind="thought", **th)

        self.say_async("thought", None, thought, max_new=cfg.thought_tokens, temperature=cfg.thought_temperature, ids=ids)

    def chat(self, text: str, rid=None):
        """Ada answers you. Returns the reply when it's ready at once; otherwise replies to `rid` later."""
        w = self.world
        if w.ada.sleeping:
            return {"asleep": True, "text": ""}
        w.hear("my friend", text)
        if w.visitor:
            w.visitor.say(text)
        hist = []
        for m in self.chat_log[-6:]:
            hist.append(("<|user|>" if m["role"] == "user" else "<|mind|>", m["text"]))
        answer: dict = {}

        def replied(reply, toks, _):
            reply = reply.strip()
            w.ada.say(reply or "…")
            self.chat_log += [{"role": "user", "text": text, "t": time.time()},
                              {"role": "mind", "text": reply, "tokens": toks, "t": time.time(), "brain": self.brain_version}]
            self.chat_log = self.chat_log[-200:]
            self.journal("heard", [("<|user|>", text)], 1.5)
            w.needs["company"] = min(100, w.needs["company"] + 8)
            if self.cfg.oracle.tutor_replies:
                self.oracle("tutor", history=[[m["role"], m["text"]] for m in self.chat_log[-8:-2]], user=text, mind=reply)
            answer.update(text=reply, tokens=toks, brain=self.brain_version)
            if rid is not None:
                self.link.reply(rid, dict(answer))

        self.say_async("chat", [("<|world|>", w.perceive(self.day_seconds))] + hist + [("<|user|>", text), ("<|mind|>", "")],
                       replied, max_new=self.cfg.world.reply_tokens, temperature=self.cfg.world.reply_temperature)
        return dict(answer) if answer else None

    def oracle_reply(self, rid: str, text: str, extra: dict | None = None):
        req = self.pending.pop(rid, None)
        if req is None:
            return
        if req["purpose"] in ("turn", "intent", "thought", "create"):
            self.community_reply(req["purpose"], req, text, extra or {})
            return
        if not text:
            return
        w, purpose = self.world, req["purpose"]
        a = w.ada
        if purpose in ("npc", "visitor_npc", "lesson"):
            name = req.get("npc", "Sage")
            p = w.people.get(name)
            if p:
                p.say(text, 9)
            near = p is not None and abs(p.x - a.x) + abs(p.y - a.y) <= 8
            if near or purpose != "visitor_npc":
                w.hear(name, text)
            to = "you" if purpose == "visitor_npc" else self.cfg.name
            self.link.send("event", kind="npc", name=name, text=text, said=req.get("said", ""), to=to,
                           why=req.get("kind", purpose))
            if purpose == "lesson":
                self.journal("lesson", [("<|thought|>", "I am at school. Sage teaches me."), ("<|npc|>", f"Sage: {text}")], 2.5)
            elif purpose == "visitor_npc":
                if near:
                    self.journal("overheard", [("<|user|>", req["said"]), ("<|npc|>", f"{name}: {text}")], 1.2)
            else:
                self.journal("conversation", [("<|mind|>", req.get("said", "")), ("<|npc|>", f"{name}: {text}")], 1.5)
        elif purpose == "banter":
            lines = [tuple(x) for x in (extra or {}).get("lines", []) if len(x) == 2]
            now = time.time()
            for i, (who, line) in enumerate(lines):
                self.speech_queue.append((now + i * 4.5, who, line))
                self.link.send("event", kind="npc", name=who, text=line, to=(lines[1 - i % 2][0] if len(lines) > 1 else ""),
                               why="banter")
            if lines and any(abs(w.people[x].x - a.x) + abs(w.people[x].y - a.y) <= 10 for x, _ in lines if x in w.people):
                self.journal("overheard", [("<|npc|>", f"{who}: {line}") for who, line in lines], 1.3)
        elif purpose == "answer":
            w.hear("the Oracle", text)
            w.note(f'The Oracle answers: "{text[:160]}"')
            self.link.send("event", kind="oracle", question=req["question"], text=text, by=self.cfg.name)
            self.journal("oracle", [("<|mind|>", req["question"]), ("<|oracle|>", text)], 3.0)
        elif purpose == "tutor":
            self.link.send("event", kind="tutor", user=req["user"], mind=req["mind"], text=text)
            parts = [("<|user|>" if r == "user" else "<|mind|>", t) for r, t in req.get("history", [])]
            self.journal("tutored", parts + [("<|user|>", req["user"]), ("<|mind|>", text)], 3.0)
        elif purpose == "book":
            e = w.entities.get(req["entity"]) or next((x for x in w.ada.carrying if x["id"] == req["entity"]), None)
            if e is not None:
                e["text"] = text
                w.touch(e)
                self.read_text(e)
        elif purpose == "fact":
            w.note(text[:200])
            self.link.send("event", kind="fact", text=text)
            self.journal("observation", [("<|thought|>", "I look at the night sky."), ("<|oracle|>", text)], 2.0)

    # ------------------------------------------------------------------ you
    def visitor(self, action: str, kind: str = "", text: str = "", msg: dict | None = None):
        """You, in the world: walk, carry, give, hug, talk to the synth and to the villagers."""
        w, msg = self.world, msg or {}
        name = self.cfg.name
        if action == "join":
            w.join()
            return f"You are in the valley. Walk with WASD and the mouse; {name} can see you."
        if action == "leave":
            w.leave()
            return "You left the valley."
        v = w.visitor
        if not v:
            return "Join the world first."
        a = w.ada
        near = abs(v.x - a.x) + abs(v.y - a.y) <= 2
        if action == "pos":
            w.move_visitor(float(msg.get("fx", v.x)), float(msg.get("fy", v.y)), msg.get("facing"))
            return ""
        if action in ("north", "south", "east", "west"):
            from .world.sim import DIRS

            dx, dy = DIRS[action]
            v.facing = action
            if w.walkable(v.x + dx, v.y + dy) and not w.occupied(v.x + dx, v.y + dy, v):
                w.move_visitor(v.x + dx, v.y + dy, action)
            return ""
        if action == "hold":
            if kind not in KINDS or not KINDS[kind].get("portable"):
                return f"You can only hold small things (not {kind})."
            if len(v.carrying) >= 6:
                return "Your hands are full."
            e = {"id": w.next_id, "kind": kind, "x": v.x, "y": v.y}
            w.next_id += 1
            if kind == "book" and text:
                e["text"] = text
                self.journal("written", [("<|oracle|>", text)], 2.0)
            v.carrying.append(e)
            return f"You are holding {KINDS[kind]['noun']}."
        if action == "interact":
            target = msg.get("target") or {}
            if target.get("kind") == "entity":
                e = w.entities.get(int(target.get("id", -1)))
                if not e:
                    return "It's gone."
                if e.get("text") and e["kind"] in ("sign", "book"):
                    return f"{KINDS[e['kind']]['noun'].capitalize()} says: {e['text']}"
                if KINDS[e["kind"]].get("portable"):
                    if e["kind"] == "coin":
                        w.remove(e)
                        w.coins += 1
                        return f"You drop the coin in {name}'s purse ({w.coins} coins)."
                    if len(v.carrying) >= 6:
                        return "Your hands are full."
                    w.remove(e)
                    v.carrying.append(e)
                    return f"You pick up {KINDS[e['kind']]['noun']}."
                if KINDS[e["kind"]].get("creature"):
                    return f"You pet {KINDS[e['kind']]['noun']}. It says {KINDS[e['kind']].get('sound', 'nothing')}."
                return f"{KINDS[e['kind']]['noun'].capitalize()}: {KINDS[e['kind']]['used_for']}."
            if target.get("kind") == "person":
                return {"talk_to": target.get("name")}
            if target.get("kind") == "synth":
                return {"talk_to": name}
            return ""
        if action == "say":                      # you talk to a villager
            who = msg.get("to") or ""
            p = w.people.get(who)
            if not p:
                return "Nobody by that name is here."
            if abs(p.x - v.x) + abs(p.y - v.y) > 4:
                return f"Walk up to {who} first."
            v.say(text)
            if p.engaged is None:
                p.say("…", 60)
            if abs(p.x - a.x) + abs(p.y - a.y) <= 8:
                w.hear("my friend", text)
            self.oracle("visitor_npc", npc=who, said=text, ctx=self.npc_context(who))
            return f"{who} is listening…"
        if action == "take":
            for e in w.at(v.x, v.y) + [x for d in ((0, 1), (1, 0), (0, -1), (-1, 0)) for x in w.at(v.x + d[0], v.y + d[1])]:
                if KINDS[e["kind"]].get("portable") and len(v.carrying) < 6:
                    w.remove(e)
                    v.carrying.append(e)
                    return f"You pick up {KINDS[e['kind']]['noun']}."
            return "Nothing to pick up here."
        if action == "drop":
            if not v.carrying:
                return "Your hands are empty."
            e = v.carrying.pop()
            e["x"], e["y"] = v.x, v.y
            w.entities[e["id"]] = e
            w.touch(e)
            return f"You put down {KINDS[e['kind']]['noun']}."
        if action == "give":
            if not v.carrying:
                return "You aren't holding anything to give."
            if not near:
                return f"Walk right up to {name} to give it something."
            e = v.carrying.pop()
            what = KINDS[e["kind"]]["noun"]
            if e["kind"] == "coin":
                w.coins += 1
            elif len(a.carrying) < 6:
                a.carrying.append(e)
            else:
                e["x"], e["y"] = a.x, a.y
                w.entities[e["id"]] = e
                w.touch(e)
            w.needs["company"] = min(100, w.needs["company"] + 20)
            w.note(f"My friend gives me {what}!")
            self.journal("gift", [("<|world|>", w.perceive(self.day_seconds)), ("<|thought|>", f"My friend gives me {what}. Thank you, friend!")], 2.0)
            return f"You give {name} {what}."
        if action == "hug":
            if not near:
                return f"Walk right up to {name} first."
            w.needs["company"] = min(100, w.needs["company"] + 25)
            w.needs["fun"] = min(100, w.needs["fun"] + 10)
            w.note("My friend hugs me. I feel happy.")
            self.journal("hug", [("<|thought|>", "My friend hugs me. I feel warm and happy.")], 1.5)
            return f"You hug {name}."
        return f"Unknown action {action}."

    def place(self, kind: str, x: int, y: int, text: str = "") -> str:
        w = self.world
        if kind == "erase":
            for e in w.at(x, y):
                w.remove(e)
            return "Erased."
        if kind not in KINDS:
            return f"Unknown thing: {kind}."
        if not w.walkable(x, y):
            return "That spot is blocked. Choose open ground."
        extra = {"text": text} if text and kind in ("book", "sign") else {}
        w.add(kind, x, y, **extra)
        if text:
            self.journal("written", [("<|oracle|>", text)], 2.0)
        return f"Placed {KINDS[kind]['noun']}."

    def suggest(self, text: str) -> str:
        """You tell Ada what to do. If she understands, she does it (and learns from it)."""
        g = ag.parse(text if text.lower().startswith("i ") else "I " + text)
        if not g:
            return f"{self.cfg.name} doesn't understand that yet. Try something like 'go fishing' or 'eat an apple'."
        g.source, g.text, g.reason = "you", ag.say(g), "My friend suggested it."
        if self.world.ada.sleeping:
            return f"{self.cfg.name} is asleep."
        if not self.set_plan(g):
            return f"{self.cfg.name} can't do that right now: " + (self.world.log[-1] if self.world.log else "")
        self.decisions.append("you")
        return f"{self.cfg.name} will: {self.plan.goal.text}"

    # ------------------------------------------------------------------ hub messages
    def handle(self, msg: dict):
        cmd, rid = msg.get("cmd"), msg.get("rid")
        try:
            if cmd == "chat":
                result = self.chat(msg["text"], rid)
                if result is None:
                    return              # the reply follows when her brain has found the words
            elif cmd == "oracle_reply":
                self.oracle_reply(msg["req"], msg.get("text", ""), {"lines": msg.get("lines", []), "work": msg.get("work")})
                result = True
            elif cmd == "visitor":
                result = self.visitor(msg["action"], msg.get("kind") or "", msg.get("text") or "", msg)
            elif cmd == "banter":
                result = self.banter()
            elif cmd == "place":
                result = self.place(msg["kind"], int(msg["x"]), int(msg["y"]), msg.get("text") or "")
            elif cmd == "suggest":
                result = self.suggest(msg["text"])
            elif cmd == "sleep_now":
                if self.world.phase == "day":
                    self.world.phase_t = max(self.world.phase_t, self.day_seconds)
                result = True
            elif cmd == "wake_now":
                if self.world.phase == "night":
                    self.world.phase_t = self.night_seconds
                result = True
            elif cmd == "think":
                self.next_thought = 0
                result = True
            elif cmd == "config":
                old = self.cfg.world.device
                self.cfg = AdaConfig.from_dict(msg["config"])
                if self.cfg.world.device != old and self.with_brain:
                    self.device = pick_device(self.cfg.world.device)   # move her brain: reload it there
                    self.brain_version = 0
                    self.maybe_load_brain()
                self.use_cpu_threads()
                result = True
            elif cmd == "full":
                self.broadcast(full=True)
                result = True
            elif cmd == "stop":
                raise SystemExit
            else:
                raise ValueError(f"unknown command {cmd}")
            self.link.reply(rid, result)
        except SystemExit:
            raise
        except Exception as e:
            self.link.reply(rid, error=f"{type(e).__name__}: {e}")

    def broadcast(self, full: bool = False):
        w = self.world
        snap = w.snapshot(full=full, day_seconds=self.day_seconds, night_seconds=self.night_seconds)
        recent = list(self.decisions)
        snap["mind"] = {
            "awake": not w.ada.sleeping, "brain": self.brain_version, "brain_meta": self.brain_meta,
            "intent": self.last_intent, "plan": self.plan.goal.text if self.plan else "",
            "self_rate": round(recent.count("self") / len(recent), 3) if recent else 0.0,
            "decisions": len(recent),
            "phase_left": max(0.0, (self.day_seconds if w.phase == "day" else self.night_seconds) - w.phase_t),
        }
        if full or time.time() - self.minds_cast >= 1.0:
            self.minds_cast = time.time()
            snap["minds"] = self.minds_view()
        self.link.send("world", snap=snap)

    # ------------------------------------------------------------------ persistence
    def save(self):
        write_json(self.folder / "world.json", {"world": self.world.state(), "memory": self.memory[-400:],
                                                "thoughts": list(self.thoughts)[-60:],
                                                "chat": self.chat_log[-100:], "community": self.community_state()})

    def load(self):
        path = self.folder / "world.json"
        if not path.exists():
            return
        try:
            s = json.loads(path.read_text(encoding="utf-8"))
            self.world.load_state(s["world"])
            self.memory = s.get("memory", [])
            self.thoughts.extend(s.get("thoughts", []))
            self.chat_log = s.get("chat", [])
            self.load_community(s.get("community", {}))
        except (ValueError, KeyError, TypeError) as e:
            self.link.warn(f"could not restore the world ({e}); starting a fresh one")

    # ------------------------------------------------------------------ main loop
    def step(self):
        cfg, w = self.cfg, self.world
        if cfg.schedule.mode == "academy":
            return                                  # the world holds its breath while she only studies
        dt = cfg.world.tick
        w.advance(dt)
        self.clock(dt)
        w.update_needs(dt)
        with self.link.perf.time("the villagers"):
            self.community_step()
        self.neighbours()
        if w.ada.engaged is not None:
            return                                  # the synth is in a conversation: it waits its turn
        if w.ada.sleeping:
            if w.phase == "day" and not self.bedtime and w.needs["rest"] > 90:
                w.ada.sleeping = False             # a daytime nap ends when she's rested
            return
        perf = self.link.perf
        if self.plan:
            with perf.time("walking and doing"):
                self.walk()
        elif self.brain is not None or not self.with_brain:
            with perf.time("deciding"):
                self.decide()
        if self.brain is not None and time.time() >= self.next_thought:
            self.next_thought = time.time() + cfg.world.thought_seconds
            with perf.time("thinking"):
                self.think()

    def loop(self):
        self.maybe_load_brain()
        while self.brain is None and self.speaker.pending("load"):   # her first brain, before she wakes
            time.sleep(0.05)
            self.speaker.deliver()
        self.broadcast(full=True)
        self.link.send("history", thoughts=list(self.thoughts), chat=self.chat_log)
        next_tick = next_cast = next_save = next_brain = time.time()
        perf = self.link.perf
        while True:
            if not self.link.hub_alive():
                self.save()
                return
            for msg in self.link.commands():
                with perf.time(f"request: {msg.get('cmd')}"):
                    self.handle(msg)
            with perf.time("taking her brain's answers"):
                self.speaker.deliver()
            now = time.time()
            if now >= next_tick:
                late = now - next_tick
                if late > 1.0:
                    self.link.warn(f"the world fell {late:.1f}s behind schedule", every=120)
                perf.add("lateness", max(0.0, late))
                next_tick = now + self.cfg.world.tick
                with perf.time("tick"):
                    self.step()
            if now >= next_cast:
                next_cast = now + 0.2
                with perf.time("sending the world to the Hub"):
                    self.broadcast()
            if now >= next_brain:
                next_brain = now + 5
                if self.world.phase == "day" or self.brain is None:
                    with perf.time("loading a new brain"):
                        self.maybe_load_brain()
                perf.gauge("device", str(self.device.type) if self.device is not None else "none")
                perf.gauge("brain_version", self.brain_version)
                perf.gauge("awake", 0 if self.world.ada.sleeping else 1)
                perf.gauge("journal_mb", round((self.folder / "journal.jsonl").stat().st_size / 2**20, 2)
                           if (self.folder / "journal.jsonl").exists() else 0)
                self.link.maybe_send_perf()
            if now >= next_save:
                next_save = now + 60
                with perf.time("saving"):
                    self.save()
            time.sleep(0.01)
