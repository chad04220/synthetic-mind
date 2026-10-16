"""The World process: where Ada lives.

It runs the simulation, keeps Ada's brain (the latest one the Academy published), and lets that
brain decide what she does, think out loud and talk. Everything she lives through is written to
her journal for the Academy to study. Nothing here trains; when night falls she goes to bed, her
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

from .config import AdaConfig, cpu_threads
from .ontology import KINDS, NPCS
from .proc import Link, append_jsonl, pick_device, write_json
from .world import agent as ag
from .world.sim import World

ROLE_TOKENS = ["<|endoftext|>", "<|thought|>", "<|user|>", "<|mind|>", "<|oracle|>", "<|world|>", "<|intent|>", "<|npc|>"]


def run(name: str, root: str, inbox, outbox):
    folder = Path(root) / name
    link = Link("world", inbox, outbox, folder)
    try:
        Life(folder, link).loop()
    except Exception as e:  # pragma: no cover
        link.crash(e)
        raise


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
        if threaded:
            threading.Thread(target=self._run, name="ada-brain", daemon=True).start()

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
            perf.add("brain: waiting in line", time.perf_counter() - queued)
            t = time.perf_counter()
            try:
                result = work()
            except Exception as e:   # a failed thought must not take the World down
                self.life.link.warn(f"Ada's brain failed while working on '{kind}': {type(e).__name__}: {e}")
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


class Life:
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
        self.world = World()
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
            self.link.log(f"her brain thinks on the CPU with {n} threads")

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
        self.pending[rid] = {"purpose": purpose, **payload}
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
        w.note("Night falls. Ada sleeps, and while she sleeps she studies.")
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
        """Follow the plan one step, or act when there."""
        w, p, a = self.world, self.plan, self.world.ada
        p.ticks += 1
        tp = ag.target_pos(w, p)
        if tp is None or p.ticks > 400:
            w.note("I could not get there.")
            self.finish(False, "I could not get there.", {})
            return
        tx, ty, adjacent = tp
        arrived = (abs(tx - a.x) + abs(ty - a.y) == 1) if adjacent else ((a.x, a.y) == (tx, ty))
        if adjacent and (a.x, a.y) == (tx, ty):
            arrived = True
        if arrived:
            ag.face(w, tx, ty)
            ok, narration, info = ag.act(w, p)
            self.finish(ok, narration, info)
            return
        if not p.route or p.ticks % 12 == 0:
            p.route = (w.path((a.x, a.y), (tx, ty), me=a, adjacent=adjacent)
                       or w.path((a.x, a.y), (tx, ty), me=a, adjacent=adjacent, avoid=False) or [])
            if not p.route:
                if p.ticks > 8:
                    self.finish(False, "Something is in the way.", {})
                return
        nx, ny = p.route[0]
        blocker = next((b for b in w.beings() if b is not a and (b.x, b.y) == (nx, ny)), None)
        if blocker is not None:
            if blocker is w.visitor:
                return                       # wait for you to move
            blocker.x, blocker.y = a.x, a.y  # a villager steps aside
        p.route.pop(0)
        ag.face(w, nx, ny)
        a.x, a.y = nx, ny
        place = w.place_of(nx, ny)
        if place not in w.visited:
            w.visited.add(place)
            w.note(f"I arrive in the {place} for the first time.")

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

    def consequences(self, info: dict, perception: str):
        """Things that need words from the brain or the Oracle."""
        w = self.world
        if "talk" in info:
            who = info["talk"]

            def spoken(line, toks, _):
                line = line.strip()
                if line:
                    w.ada.say(line)
                if who == "friend":
                    self.link.send("event", kind="ada_says", text=line, to="friend")
                else:
                    self.oracle("npc", npc=who, role=NPCS[who]["role"], ada_said=line,
                                season=w.season, weather=w.weather, place=w.place_of(w.ada.x, w.ada.y))

            self.say_async("speech", [("<|world|>", perception), ("<|mind|>", "")], spoken, max_new=20,
                           temperature=self.cfg.world.reply_temperature)
        if "ask" in info:
            self.asked_at = time.time()
            self.oracle("answer", question=info["ask"])
        if "read" in info:
            book = info["read"]
            w.read_books.add(book["id"])
            if book.get("text"):
                self.read_text(book)
            else:
                self.oracle("book", entity=book["id"], kind=book["kind"])
        if "stars" in info:
            self.oracle("fact", topic="the stars, the moon and the planets")

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
        if req is None or not text:
            return
        w, purpose = self.world, req["purpose"]
        if purpose == "npc":
            name = req["npc"]
            p = w.people.get(name)
            if p:
                p.say(text)
            w.hear(name, text)
            self.link.send("event", kind="npc", name=name, text=text, ada=req.get("ada_said", ""))
            self.journal("conversation", [("<|mind|>", req.get("ada_said", "")), ("<|npc|>", f"{name}: {text}")], 1.5)
        elif purpose == "answer":
            w.hear("the Oracle", text)
            w.note(f'The Oracle answers: "{text[:160]}"')
            self.link.send("event", kind="oracle", question=req["question"], text=text, by="Ada")
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
    def visitor(self, action: str, kind: str = "", text: str = "") -> str:
        w = self.world
        if action == "join":
            w.join()
            return "You are in the world. Walk with WASD or the arrows; Ada can see you."
        if action == "leave":
            w.leave()
            return "You left the world."
        v = w.visitor
        if not v:
            return "Join the world first."
        a = w.ada
        near = abs(v.x - a.x) + abs(v.y - a.y) <= 1
        if action in ("north", "south", "east", "west"):
            from .world.sim import DIRS

            dx, dy = DIRS[action]
            v.facing = action
            if w.walkable(v.x + dx, v.y + dy) and not w.occupied(v.x + dx, v.y + dy, v):
                v.x, v.y = v.x + dx, v.y + dy
            return ""
        if action == "hold":
            if kind not in KINDS or not KINDS[kind].get("portable"):
                return f"You can only hold small things (not {kind})."
            if len(v.carrying) >= 4:
                return "Your hands are full."
            e = {"id": w.next_id, "kind": kind, "x": v.x, "y": v.y}
            w.next_id += 1
            if kind == "book" and text:
                e["text"] = text
                self.journal("written", [("<|oracle|>", text)], 2.0)
            v.carrying.append(e)
            return f"You are holding {KINDS[kind]['noun']}."
        if action == "take":
            for e in w.at(v.x, v.y) + [x for d in ((0, 1), (1, 0), (0, -1), (-1, 0)) for x in w.at(v.x + d[0], v.y + d[1])]:
                if KINDS[e["kind"]].get("portable") and len(v.carrying) < 4:
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
                return "Walk right next to Ada to give her something."
            e = v.carrying.pop()
            what = KINDS[e["kind"]]["noun"]
            if len(a.carrying) < 4:
                a.carrying.append(e)
            else:
                e["x"], e["y"] = a.x, a.y
                w.entities[e["id"]] = e
                w.touch(e)
            w.needs["company"] = min(100, w.needs["company"] + 20)
            w.note(f"My friend gives me {what}!")
            self.journal("gift", [("<|world|>", w.perceive(self.day_seconds)), ("<|thought|>", f"My friend gives me {what}. Thank you, friend!")], 2.0)
            return f"You give Ada {what}."
        if action == "hug":
            if not near:
                return "Walk right next to Ada first."
            w.needs["company"] = min(100, w.needs["company"] + 25)
            w.needs["fun"] = min(100, w.needs["fun"] + 10)
            w.note("My friend hugs me. I feel happy.")
            self.journal("hug", [("<|thought|>", "My friend hugs me. I feel warm and happy.")], 1.5)
            return "You hug Ada."
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
            return "Ada doesn't understand that yet. Try something like 'go to the library' or 'eat an apple'."
        g.source, g.text, g.reason = "you", ag.say(g), "My friend suggested it."
        if self.world.ada.sleeping:
            return "Ada is asleep."
        if not self.set_plan(g):
            return "Ada can't do that right now: " + (self.world.log[-1] if self.world.log else "")
        self.decisions.append("you")
        return f"Ada will: {self.plan.goal.text}"

    # ------------------------------------------------------------------ hub messages
    def handle(self, msg: dict):
        cmd, rid = msg.get("cmd"), msg.get("rid")
        try:
            if cmd == "chat":
                result = self.chat(msg["text"], rid)
                if result is None:
                    return              # the reply follows when her brain has found the words
            elif cmd == "oracle_reply":
                self.oracle_reply(msg["req"], msg.get("text", ""))
                result = True
            elif cmd == "visitor":
                result = self.visitor(msg["action"], msg.get("kind") or "", msg.get("text") or "")
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
        snap = w.snapshot(full=full, day_seconds=self.day_seconds)
        recent = list(self.decisions)
        snap["mind"] = {
            "awake": not w.ada.sleeping, "brain": self.brain_version, "brain_meta": self.brain_meta,
            "intent": self.last_intent, "plan": self.plan.goal.text if self.plan else "",
            "self_rate": round(recent.count("self") / len(recent), 3) if recent else 0.0,
            "decisions": len(recent),
            "phase_left": max(0.0, (self.day_seconds if w.phase == "day" else self.night_seconds) - w.phase_t),
        }
        self.link.send("world", snap=snap)

    # ------------------------------------------------------------------ persistence
    def save(self):
        write_json(self.folder / "world.json", {"world": self.world.state(), "memory": self.memory[-400:],
                                                "thoughts": list(self.thoughts)[-60:],
                                                "chat": self.chat_log[-100:]})

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
