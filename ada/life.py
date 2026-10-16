"""The World process: Zen, alone in an endless world, doing only what its own mind chooses.

Zen's brain (the latest one the Academy published) runs here on its own thread. It lives one
continuous stream: what Zen perceives, thinks, says, is told, and does. Every motor action is a word
its brain chooses (motor.py); so is every mark of a painting, every note and every bit of clay
(world/studio.py), and every word it says, writes or asks. Nothing else decides for Zen. The World
(world/sim.py) answers with consequences and rewards, which become Zen's experience
(experience.jsonl) for the Academy to learn from.

The Sprite of All Knowing floats beside Zen and answers when Zen asks (its words come from the
Hub's language model). Zen waits for the answer; its thoughts go on meanwhile.
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
from .motor import MOTOR, Experience, MotorMind, motor_ids
from .proc import Link, append_jsonl, pick_device, write_json
from .world import studio
from .world.sim import World

ROLE_TOKENS = ["<|endoftext|>", "<|thought|>", "<|user|>", "<|mind|>", "<|oracle|>", "<|world|>", "<|intent|>", "<|act|>"]
VOCAB_INDEX = {"motor": 0, "paint": 1, "compose": 2, "sculpt": 3}
ASK_PATIENCE = 180.0          # seconds Zen waits for the Sprite before it gives up


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
    """Runs the synth's brain on its own thread, so the world never waits for it.

    Jobs (load a new brain, a reply to you, an action, a mark, a thought) are queued by urgency and
    done one at a time; the World collects the results each loop. With threaded=False (tests) a job
    is done on the spot."""

    PRIORITY = {"load": 0, "chat": 1, "motor": 2, "studio": 2, "speech": 3, "create": 4, "thought": 5}

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
        self.busy[kind] = self.busy.get(kind, 0) + 1
        if not self.threaded:
            self.busy[kind] -= 1
            callback(work())
            return
        self.jobs.put((self.PRIORITY.get(kind, 6), next(self.seq), kind, work, callback, time.perf_counter()))

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


class Life:
    def __init__(self, folder: Path, link: Link, with_brain: bool = True, threaded: bool = True):
        from .tokenizer import make_tokenizer

        self.folder, self.link = folder, link
        self.cfg = AdaConfig.load(folder / "config.json")
        if not self.cfg.world.seed:
            self.cfg.world.seed = random.randrange(1, 2 ** 31)
            self.cfg.save(folder / "config.json")
        self.tok = make_tokenizer(self.cfg.tokenizer)
        self.stop_ids = {self.tok[r] for r in ROLE_TOKENS}
        self.with_brain = with_brain
        self.device = pick_device(self.cfg.world.device) if with_brain else None
        self.use_cpu_threads()
        self.brain = None
        self.brain_version = 0
        self.brain_meta: dict = {}
        self.rng = random.Random()
        self.world = World(self.cfg.world.seed)
        T = self.cfg.brain.seq_len
        self.mind = MotorMind(T)
        self.exp = Experience(T + 1)
        self.vocab = {"motor": motor_ids(self.tok)} | {m: studio.vocab_ids(self.tok, m) for m in studio.VOCABS}
        self.act_tok = self.tok["<|act|>"]
        self.last_percept = ""
        self.last_fail = ("", "", 0)                  # (word, consequence, how many times in a row)
        self.next_motor = 0.0
        self.waiting: dict | None = None              # a question to the Sprite, in flight
        self.session = None                           # a piece of art in the making
        self.session_start = 0                        # where the session's marks begin in the experience
        self.judging: dict | None = None              # a finished piece the Sprite is looking at
        self.thoughts: deque = deque(maxlen=120)
        self.last_thought = ""
        self.chat_log: list[dict] = []
        self.next_thought = time.time() + 3
        self.pending: dict[str, dict] = {}            # language-model requests in flight
        self.last_speech = ""
        self.voice_ready = False                      # the Hub says the Sprite's model is up
        self.motor_stats = {"steps": 0, "last": "", "entropy": None, "reward_rate": 0.0, "counts": [0] * len(MOTOR)}
        self.art_scores: dict[str, float] = {}        # running average score per medium
        self.earlier_paintings: deque = deque(maxlen=12)
        self.speaker = Speaker(self, threaded and with_brain)
        self.phase_seen = self.world.phase
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
        if self.device is None or self.device.type != "cpu":
            return
        import torch

        n = cpu_threads(self.cfg)["world"]
        if torch.get_num_threads() != n:
            torch.set_num_threads(n)
            self.link.log(f"{self.cfg.name}'s brain thinks on the CPU with {n} threads")

    def _load_brain(self, meta: dict):
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
        self.mind.reset()
        self.link.send("event", kind="brain", meta=meta)
        self.link.log(f"living with brain v{meta['version']} (step {meta['step']}, {meta.get('stage_name', '')})")

    def say_async(self, kind: str, prompt: list[int], callback, max_new: int = 24, temperature: float = 0.8,
                  stop_text=None):
        """Ask the brain for words after a prompt; callback(text, tokens, ids) runs later on this thread."""
        def work():
            brain = self.brain
            if brain is None:
                return []
            return brain.generate(prompt, max_new, temperature, 0.95, stop=self.stop_ids, n_real=self.tok.n_real,
                                  stop_text=stop_text)

        def done(out):
            toks = [t for t, _, _ in out]
            callback(self.tok.decode(toks), [[self.tok.token_str(t), round(p, 3)] for t, p, _ in out], toks)

        self.speaker.ask(kind, work, done)

    # ------------------------------------------------------------------ the stream
    def stream(self, role: str, text: str = "", ids: list[int] | None = None):
        """Add to Zen's lived stream (what its brain sees next, and what the Academy will study)."""
        ids = [self.tok[role]] + (ids if ids is not None else self.tok.encode(text))
        self.mind.push(ids)
        self.exp.tokens(ids)

    def context(self, room: int) -> list[int]:
        return self.mind.tail(self.cfg.brain.seq_len - room)

    def flush_experience(self):
        if self.session is not None or self.judging is not None:
            return                       # a piece's marks wait for its verdict before they are learnt from
        for win in self.exp.ready():
            append_jsonl(self.folder / "experience.jsonl", {"t": time.time(), **win})

    def journal(self, kind: str, parts, weight: float = 1.0):
        parts = [[r, t] for r, t in parts if t]
        if parts:
            append_jsonl(self.folder / "journal.jsonl", {"t": time.time(), "kind": kind, "parts": parts,
                                                         "weight": round(weight, 3)})

    def oracle(self, purpose: str, **payload) -> str:
        """Ask the Hub's language model (the Sprite) for something; the answer arrives as 'oracle_reply'."""
        rid = f"w{time.time_ns()}"
        self.pending[rid] = {"purpose": purpose, "rid": rid, **payload}
        self.link.send("oracle", rid=rid, purpose=purpose, payload=payload,
                       stage=int(self.brain_meta.get("stage", 0) or 0))
        return rid

    # ------------------------------------------------------------------ acting
    def can_act(self) -> bool:
        z = self.world.zen
        return (self.brain is not None and not z.sleeping and self.waiting is None
                and not self.speaker.pending("motor") and not self.speaker.pending("studio")
                and not self.speaker.pending("speech"))

    def motor_beat(self):
        """Zen's brain chooses its next action, from everything it has lived so far."""
        w = self.world
        percept = w.perceive()
        if percept != self.last_percept:
            self.stream("<|world|>", percept)
            self.last_percept = percept
        brain, temp = self.brain, self.cfg.world.motor_temperature
        motor = self.vocab["motor"]
        self.speaker.ask("motor", lambda: self.mind.choose(brain, motor, self.act_tok, temp, self.rng), self.on_motor)

    def on_motor(self, choice: dict):
        w = self.world
        i, word = choice["index"], choice["word"]
        self.exp.tokens([self.act_tok, self.vocab["motor"][i]])
        self.exp.act(i, VOCAB_INDEX["motor"])
        r = w.act(word, context_text=self.last_thought) or {}
        reward = float(r.get("reward", 0.0)) + float(w.reward_since_last())
        # the same failure again and again hurts more each time (a bruise, not a rule)
        same = not r.get("ok", True) and (word, r.get("text")) == self.last_fail[:2]
        self.last_fail = (word, r.get("text"), self.last_fail[2] + 1 if same else 0) if not r.get("ok", True) else ("", "", 0)
        if same:
            n = self.last_fail[2]
            reward -= min(0.4, 0.03 * n)
            if n in (2, 5, 10, 20):
                r["text"] = (r.get("text") or "") + " Ouch, again. It hurts."
        self.exp.reward(reward)
        st = self.motor_stats
        st["steps"] += 1
        st["last"] = word
        st["counts"][i] += 1
        st["entropy"] = choice["entropy"] if st["entropy"] is None else 0.95 * st["entropy"] + 0.05 * choice["entropy"]
        st["reward_rate"] = 0.97 * st["reward_rate"] + 0.03 * reward
        text = r.get("text", "")
        if text:
            self.stream("<|world|>", text)
        self.link.send("event", kind="did", action=word, text=text, ok=bool(r.get("ok", True)), reward=round(reward, 3),
                       probs=choice["probs"])
        need = r.get("needs_words")
        if need == "ask":
            self.ask_sprite()
        elif need == "speak":
            self.speak()
        elif need in ("paint", "compose", "sculpt"):
            self.begin_session(need, r.get("material", "clay"))
        elif need == "write":
            self.write()
        self.flush_experience()

    # ------------------------------------------------------------------ words
    def speak(self):
        """Zen says something aloud: its own brain finds every word."""
        def spoken(text, toks, ids):
            text = text.strip()
            if ids:
                self.stream("<|mind|>", ids=ids)
            self.last_speech = text
            self.world.heard(text or "…")
            self.link.send("event", kind="ada_says", text=text, tokens=toks)

        self.say_async("speech", self.context(40) + [self.tok["<|mind|>"]], spoken, max_new=24,
                       temperature=self.cfg.world.reply_temperature)

    def ask_sprite(self):
        """Zen asks the Sprite: its brain writes the question, then its body waits for the answer."""
        w = self.world

        def asked(text, toks, ids):
            q = text.strip()
            if ids:
                self.stream("<|mind|>", ids=ids)
            self.last_speech = q
            w.heard(q or "…")
            self.link.send("event", kind="ada_says", text=q, tokens=toks, to="sprite")
            if not q:
                w.sprite_say("…?")
                return
            if not (self.voice_ready and self.cfg.oracle.enabled):
                w.sprite_say("(The Sprite is resting.)")
                return
            w.sprite_state("listening")
            rid = self.oracle("sprite_answer", question=q, situation=w.look())
            self.waiting = {"rid": rid, "question": q, "since": time.time(), "percept": w.perceive()}

        self.say_async("speech", self.context(48) + [self.tok["<|mind|>"]], asked, max_new=32,
                       temperature=self.cfg.world.reply_temperature,
                       stop_text=lambda ids: "?" in self.tok.decode(ids[-2:]))

    def sprite_answered(self, req: dict, text: str):
        w = self.world
        q = req.get("question", "")
        self.waiting = None
        if not text:
            w.sprite_state("idle")
            return
        w.sprite_say(text)
        w.answer_arrived()
        self.stream("<|oracle|>", text)
        self.link.send("event", kind="answer", question=q, text=text, by=self.cfg.name)
        self.journal("answer", [("<|world|>", req.get("situation", "")[:600]), ("<|mind|>", q), ("<|oracle|>", text)], 3.0)

    def write(self):
        """At the desk: Zen's brain writes whatever it writes."""
        w = self.world
        w.zen.activity = "writing"

        def wrote(text, toks, ids):
            from .world.art import poem_spec

            w.zen.activity = ""
            text = text.strip()
            if ids:
                self.stream("<|mind|>", ids=ids)
            if not text:
                return
            c = w.create("poem", self.cfg.name, poem_spec(text, "", "") | {"v": 3}, "")
            c["text"] = text
            self.journal("writing", [("<|mind|>", text)], 1.5)
            self.name_work(c)
            if self.judging is None and self.voice_ready and self.cfg.oracle.enabled:
                self.judging = {"cid": c["id"], "medium": "poem", "marks": [], "intrinsic": 0.0, "since": time.time(),
                                "rid": self.oracle("sprite_critique", kind="poem", text=text)}

        self.say_async("create", self.context(130) + [self.tok["<|mind|>"]], wrote, max_new=120, temperature=0.95)

    def name_work(self, c: dict):
        """Zen names what it made, in its own words."""
        def named(text, toks, ids):
            title = text.strip().split(".")[0][:48]
            c["title"] = title or c.get("title") or ""
            self.link.send("event", kind="created", creation=c)

        self.say_async("create", self.context(24) + [self.tok["<|thought|>"]] + self.tok.encode("I call it")
                       + [self.tok["<|mind|>"]], named, max_new=8, temperature=0.9)

    # ------------------------------------------------------------------ the studio
    def begin_session(self, kind: str, material: str = "clay"):
        w = self.world
        self.session = {"kind": kind, "ins": studio.instrument(kind, material), "start": time.time(),
                        "marks": 0, "cast": 0.0}
        self.session_start = len(self.exp.acts)
        w.zen.activity = {"paint": "painting", "compose": "playing the piano", "sculpt": "sculpting"}[kind]
        self.stream("<|world|>", self.session["ins"].describe())
        self.cast_studio(full=True)

    def studio_beat(self):
        s = self.session
        brain, temp = self.brain, self.cfg.world.motor_temperature
        vocab = self.vocab[s["kind"]]
        words = studio.VOCABS[s["kind"]]
        self.speaker.ask("studio", lambda: self.mind.choose(brain, vocab, self.act_tok, temp, self.rng, words),
                         self.on_mark)

    def on_mark(self, choice: dict):
        s = self.session
        if s is None:
            return
        kind = s["kind"]
        words = studio.VOCABS[kind]
        i = choice["index"]
        word = words[i]
        self.exp.tokens([self.act_tok, self.vocab[kind][i]])
        self.exp.act(i, VOCAB_INDEX[kind])
        s["ins"].apply(word)
        s["marks"] += 1
        # now and then Zen looks at its work: what it sees goes into its stream
        if s["marks"] % 24 == 0:
            self.stream("<|world|>", s["ins"].describe())
        if s["ins"].done or s["marks"] >= studio.LIMITS[kind]:
            self.end_session()
        else:
            self.cast_studio()

    def cast_studio(self, full: bool = False):
        s = self.session
        if s is None:
            self.world.set_studio(None)
            return
        now = time.time()
        full = full or now - s["cast"] >= 1.0
        if full:
            s["cast"] = now
        self.world.set_studio(s["ins"].view(full))

    def end_session(self, interrupted: bool = False):
        s, w = self.session, self.world
        self.session = None
        w.zen.activity = ""
        w.set_studio(None)
        if s is None:
            return
        ins, kind = s["ins"], s["kind"]
        medium = studio.MEDIUM[kind]
        earlier = list(self.earlier_paintings) if kind == "paint" else None
        sc = ins.score(earlier)
        marks = self.exp.acts[self.session_start:]
        if s["marks"] == 0:
            return
        data = ins.data() | {"score": sc, "marks": s["marks"], "seconds": round(time.time() - s["start"], 1)}
        if kind == "paint":
            self.earlier_paintings.append(data["pixels"])
        c = w.create(medium, self.cfg.name, data, "")
        self.stream("<|world|>", f"I finished. {ins.describe()}")
        self.link.send("event", kind="created", creation=c)
        self.journal("made", [("<|thought|>", f"I made {_a(medium)}. {ins.describe()}")], 1.2)
        self.name_work(c)
        self.judge(c, medium, marks, sc["total"])

    # ------------------------------------------------------------------ the Sprite looks at the work
    def judge(self, c: dict, medium: str, marks: list, intrinsic: float, text: str = ""):
        """Show the finished piece to the Sprite, which sees (or hears) it and scores it. That verdict is
        the reward for every mark that made it. Without the Sprite, the studio's own measures stand in."""
        from .world import render

        payload = {"kind": medium, "marks": len(marks), "text": text}
        try:
            if medium == "painting":
                payload["image"] = render.painting_png(c["data"])
            elif medium == "sculpture":
                payload["image"] = render.sculpture_png(c["data"])
            elif medium == "music":
                payload["audio"] = render.music_wav(c["data"])
        except Exception as e:  # a piece that can't be shown is judged by its own measures
            self.link.warn(f"could not show the Sprite {_a(medium)}: {type(e).__name__}: {e}")
            payload = {}
        self.judging = {"cid": c["id"], "medium": medium, "marks": marks, "intrinsic": intrinsic, "since": time.time(),
                        "rid": None}
        if payload and self.voice_ready and self.cfg.oracle.enabled:
            self.world.sprite_state("listening" if medium == "music" else "answering")
            self.judging["rid"] = self.oracle("sprite_critique", **payload)
        else:
            self.verdict({})

    def verdict(self, crit: dict):
        """The Sprite's verdict (or none): reward the marks, tell Zen what the Sprite saw."""
        j, w = self.judging, self.world
        self.judging = None
        if j is None:
            return
        medium, marks = j["medium"], j["marks"]
        c = next((x for x in w.creations if x.get("id") == j["cid"]), None)
        if crit and "score" in crit:
            quality = 0.75 * crit["score"] / 10 + 0.25 * j["intrinsic"]
        else:
            quality = j["intrinsic"]
        avg = self.art_scores.get(medium, quality)
        self.art_scores[medium] = 0.9 * avg + 0.1 * quality
        reward = 2.0 * (quality - avg) + (0.3 if len(marks) >= 12 else -0.2)
        for a in marks:                              # every mark shares in how the piece turned out
            a[2] += reward / max(1, len(marks))
        if crit and c is not None:
            c["critique"] = crit
            words = " ".join(x for x in (crit.get("see", ""), crit.get("say", "")) if x)
            if words:
                w.sprite_say(crit.get("say") or crit.get("see"))
                self.stream("<|oracle|>", words)
                self.journal("critique", [("<|world|>", f"I made {_a(medium)}."), ("<|oracle|>", words)], 2.0)
            self.link.send("event", kind="created", creation=c)
            self.link.send("event", kind="answer", question=f"(looks at {_a(medium)})", text=words, by="critique")
        w.sprite_state("idle")
        self.flush_experience()

    def exp_position(self, act) -> int:
        return int(act[0])

    def love(self, cid: int) -> str:
        """You love a piece: every mark that made it gets a strong extra reward (if it is still recent
        enough to be in Zen's experience, else as a thought for its journal)."""
        w = self.world
        c = next((x for x in w.creations if x.get("id") == cid), None)
        if c is None:
            return "That piece is gone."
        w.love(cid)
        c["loves"] = c.get("loves", 0) + 1
        self.journal("loved", [("<|user|>", f"I love your {c['kind'] if c['kind'] != 'music' else 'song'}"
                                              f"{(' ' + repr(c['title'])) if c.get('title') else ''}!")], 2.0)
        self.stream("<|user|>", "I love what you made!")
        ops = (c.get("data") or {}).get("ops")
        kind = {"painting": "paint", "music": "compose", "sculpture": "sculpt"}.get(c["kind"])
        if ops and kind:
            # replay the piece as experience with a strong positive advantage on every mark
            words = studio.VOCABS[kind]
            ids, acts = [self.tok["<|world|>"]] + self.tok.encode(studio.instrument(kind).describe()), []
            for ch in ops:
                i = studio.CODES.index(ch)
                ids += [self.act_tok, self.vocab[kind][i]]
                acts.append([len(ids) - 1, i, 1.5, VOCAB_INDEX[kind]])
            T = self.cfg.brain.seq_len + 1
            for k in range(0, len(ids), T):
                part = [[p - k, i, a, v] for p, i, a, v in acts if k + 1 <= p < k + T]
                if part:
                    append_jsonl(self.folder / "experience.jsonl",
                                 {"t": time.time(), "ids": ids[k:k + T], "acts": part, "ret": 1.0, "steps": len(part),
                                  "loved": cid})
            words = len(ops)
            return f"{self.cfg.name} feels your love for it: all {words} marks of it count for more now."
        self.link.send("event", kind="created", creation=c)
        return f"{self.cfg.name} hears that you love it."

    # ------------------------------------------------------------------ thoughts and talk
    def think(self):
        if self.speaker.pending("thought"):
            return

        def thought(text, toks, ids):
            if ids:
                self.stream("<|thought|>", ids=ids)
            th = {"text": text, "tokens": toks, "brain": self.brain_version, "t": time.time()}
            if text.strip():
                self.last_thought = text.strip()
            self.thoughts.append(th)
            self.link.send("event", kind="thought", **th)

        cfg = self.cfg.world
        self.say_async("thought", self.context(cfg.thought_tokens + 8) + [self.tok["<|thought|>"]], thought,
                       max_new=cfg.thought_tokens, temperature=cfg.thought_temperature)

    def chat(self, text: str, rid=None):
        """You talk to Zen; it answers with its own brain."""
        w = self.world
        if w.zen.sleeping:
            return {"asleep": True, "text": ""}
        w.visitor_say(text) if w.visitor else None
        self.stream("<|user|>", text)
        answer: dict = {}

        def replied(reply, toks, ids):
            reply = reply.strip()
            if ids:
                self.stream("<|mind|>", ids=ids)
            w.heard(reply or "…")
            self.last_speech = reply
            self.chat_log += [{"role": "user", "text": text, "t": time.time()},
                              {"role": "mind", "text": reply, "tokens": toks, "t": time.time(), "brain": self.brain_version}]
            self.chat_log = self.chat_log[-200:]
            self.journal("heard", [("<|user|>", text), ("<|mind|>", reply)], 1.5)
            answer.update(text=reply, tokens=toks, brain=self.brain_version)
            if rid is not None:
                self.link.reply(rid, dict(answer))

        self.say_async("chat", self.context(self.cfg.world.reply_tokens + 4) + [self.tok["<|mind|>"]], replied,
                       max_new=self.cfg.world.reply_tokens, temperature=self.cfg.world.reply_temperature)
        return dict(answer) if answer else None

    def oracle_reply(self, rid: str, text: str, extra: dict | None = None):
        req = self.pending.pop(rid, None)
        if req is None:
            return
        if req["purpose"] == "sprite_critique":
            if self.judging and self.judging.get("rid") == rid:
                self.verdict((extra or {}).get("critique") or {})
            return
        if req["purpose"] == "sprite_answer":
            if self.waiting and self.waiting.get("rid") == rid:
                self.sprite_answered(req | {"question": self.waiting["question"]}, text)
            elif text:
                self.world.sprite_say(text)      # it came after Zen gave up waiting: still said

    # ------------------------------------------------------------------ you
    def visitor(self, action: str, msg: dict) -> str:
        w = self.world
        name = self.cfg.name
        if action == "join":
            w.visitor_join()
            return f"You are in {name}'s world. Walk with WASD and the mouse; {name} can see and hear you."
        if action == "leave":
            w.visitor_leave()
            return "You left."
        if not w.visitor:
            return "Join the world first."
        if action in ("move", "pos"):
            w.visitor_move(float(msg.get("fx", msg.get("x", 0))), float(msg.get("fy", msg.get("y", 0))), msg.get("facing"))
            return ""
        if action == "say":
            text = str(msg.get("text") or "")
            w.visitor_say(text)
            if text:
                self.stream("<|user|>", text)
                self.journal("heard", [("<|user|>", text)], 1.2)
            return ""
        if action == "give":
            return w.visitor_give() or ""
        if action == "take":
            return w.visitor_take(int(msg.get("id", -1))) or ""
        if action == "place":
            return w.visitor_place(str(msg.get("kind") or ""), int(msg.get("x", 0)), int(msg.get("y", 0))) or ""
        return f"Unknown action {action}."

    # ------------------------------------------------------------------ hub messages
    def handle(self, msg: dict):
        cmd, rid = msg.get("cmd"), msg.get("rid")
        try:
            if cmd == "chat":
                result = self.chat(msg["text"], rid)
                if result is None:
                    return              # the reply follows when its brain has found the words
            elif cmd == "oracle_reply":
                self.oracle_reply(msg["req"], msg.get("text", ""), {"critique": msg.get("critique")})
                result = True
            elif cmd == "voice":
                self.voice_ready = bool(msg.get("ready"))
                result = True
            elif cmd == "visitor":
                result = self.visitor(msg.get("action", ""), msg)
            elif cmd == "place":
                result = self.world.visitor_place(str(msg.get("kind")), int(msg["x"]), int(msg["y"])) or ""
            elif cmd == "love":
                result = self.love(int(msg.get("id", -1)))
            elif cmd == "chunk":
                result = self.world.chunk_payload(int(msg["cx"]), int(msg["cy"]))
            elif cmd == "atlas":
                result = self.world.atlas()
            elif cmd == "world_meta":
                result = self.world.world_meta()
            elif cmd == "sleep_now":                 # you make the night come now (Zen sleeps only if it is tired)
                if self.world.phase == "day":
                    self.world.phase_t = self.day_seconds
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
                    self.device = pick_device(self.cfg.world.device)
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
        snap = w.snapshot(full=full)
        st = self.motor_stats
        total = sum(st["counts"]) or 1
        snap["mind"] = {
            "awake": not w.zen.sleeping, "brain": self.brain_version, "brain_meta": self.brain_meta,
            "said": self.last_speech, "waiting": bool(self.waiting), "creating": self.session["kind"] if self.session else "",
            "phase_left": max(0.0, (self.day_seconds if w.phase == "day" else self.night_seconds) - w.phase_t),
            "motor": {"steps": st["steps"], "last": st["last"], "entropy": None if st["entropy"] is None else round(st["entropy"], 3),
                      "reward_rate": round(st["reward_rate"], 4),
                      "share": {MOTOR[i]: round(c / total, 3) for i, c in enumerate(st["counts"]) if c}},
            "art": {k: round(v, 3) for k, v in self.art_scores.items()},
        }
        self.link.send("world", snap=snap)

    # ------------------------------------------------------------------ persistence
    def save(self):
        write_json(self.folder / "world.json", {"v": 4, "world": self.world.state(), "stream": self.mind.tail(1024),
                                                "thoughts": list(self.thoughts)[-60:], "chat": self.chat_log[-100:],
                                                "experience": self.exp.state(), "motor": self.motor_stats,
                                                "art_scores": self.art_scores, "earlier": list(self.earlier_paintings)})

    def load(self):
        path = self.folder / "world.json"
        if not path.exists():
            return
        try:
            s = json.loads(path.read_text(encoding="utf-8"))
            if s.get("v") != 4:
                self.link.log("an earlier version's homestead was found: Zen starts afresh in the endless world "
                              "(its brain, journey and keepsakes are kept)")
                self._adopt_v3(s)
                return
            self.world = World.from_state(s["world"])
            self.mind.push(s.get("stream", []))
            self.thoughts.extend(s.get("thoughts", []))
            self.chat_log = s.get("chat", [])
            self.exp.load(s.get("experience", {}))
            self.motor_stats.update(s.get("motor", {}))
            self.art_scores = s.get("art_scores", {})
            self.earlier_paintings.extend(s.get("earlier", []))
        except (ValueError, KeyError, TypeError) as e:
            self.link.warn(f"could not restore the world ({e}); starting a fresh one")

    def _adopt_v3(self, s: dict):
        """Bring v3's keepsakes into the new world (as old works; the homestead itself is gone)."""
        self.thoughts.extend(s.get("thoughts", []))
        self.chat_log = s.get("chat", [])
        for c in (s.get("world") or {}).get("creations", []):
            if c.get("author") == self.cfg.name:
                try:
                    self.world.create(c["kind"], c["author"], c.get("data") or {}, c.get("title", ""))
                except Exception:
                    pass

    # ------------------------------------------------------------------ main loop
    def step(self):
        cfg, w = self.cfg, self.world
        if cfg.schedule.mode == "academy":
            return                                  # the world holds its breath while it only studies
        w.zen_stage = int(self.brain_meta.get("stage", 0) or 0)
        w.advance(cfg.world.tick, day_seconds=self.day_seconds, night_seconds=self.night_seconds)
        for ev in w.take_events():                  # what happened to Zen by itself (sleep, weather, places found)
            if ev.get("text"):
                self.stream("<|world|>", ev["text"])
                self.link.send("event", kind="happening", what=ev.get("kind", ""), text=ev["text"],
                               **{k: v for k, v in ev.items() if k not in ("kind", "text", "t")})
        if w.phase != self.phase_seen:
            self.phase_seen = w.phase
            self.link.send("phase", phase=w.phase, day=w.day)
            if w.phase == "night":
                self.save()
            else:
                self.maybe_load_brain()
        now = time.time()
        if self.judging and now - self.judging["since"] > 600:
            self.verdict({})                         # the Sprite took too long: the studio's own measures
        if self.waiting and now - self.waiting["since"] > ASK_PATIENCE:
            self.waiting = None                     # the Sprite is too slow: Zen moves on
            w.sprite_state("idle")
            self.stream("<|world|>", "The Sprite does not answer.")
        if w.zen.sleeping:
            if self.session:
                self.end_session(interrupted=True)
            return
        if self.brain is None:
            return
        perf = self.link.perf
        if self.session is not None:
            if not self.speaker.pending("studio"):
                with perf.time("creating"):
                    self.studio_beat()
        elif self.can_act() and now >= self.next_motor:
            self.next_motor = now + cfg.world.motor_seconds
            with perf.time("acting"):
                self.motor_beat()
        if now >= self.next_thought:
            self.next_thought = now + cfg.world.thought_seconds
            with perf.time("thinking"):
                self.think()

    def loop(self):
        self.maybe_load_brain()
        while self.brain is None and self.speaker.pending("load"):   # its first brain, before it wakes
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
            with perf.time("taking its brain's answers"):
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
                if self.session:
                    self.cast_studio()
                with perf.time("sending the world to the Hub"):
                    self.broadcast()
            if now >= next_brain:
                next_brain = now + 5
                if self.world.zen.sleeping or self.brain is None:
                    with perf.time("loading a new brain"):
                        self.maybe_load_brain()
                perf.gauge("device", str(self.device.type) if self.device is not None else "none")
                perf.gauge("brain_version", self.brain_version)
                perf.gauge("awake", 0 if self.world.zen.sleeping else 1)
                perf.gauge("motor_steps", self.motor_stats["steps"])
                perf.gauge("experience_mb", round((self.folder / "experience.jsonl").stat().st_size / 2**20, 2)
                           if (self.folder / "experience.jsonl").exists() else 0)
                self.link.maybe_send_perf()
            if now >= next_save:
                next_save = now + 60
                with perf.time("saving"):
                    self.save()
            time.sleep(0.005)


def _a(medium: str) -> str:
    return {"painting": "a painting", "music": "a song", "sculpture": "a sculpture", "poem": "a poem"}.get(medium, medium)
