"""The Mind: one network, one engine thread, many activities.

A single thread owns the network and interleaves everything it does, so the GPU is
never contended and training never stops for long:

    commands from you (chat, probes, world edits)  ->  answered first
    a body step every world tick                  ->  policy head picks an action
    a thought every few seconds                   ->  free-running inner monologue
    otherwise                                     ->  a training step on the data mix

The web server only reads snapshots and the event stream and posts commands.
"""
from __future__ import annotations

import contextlib
import math
import queue
import random
import re
import threading
import time
from collections import deque
from concurrent.futures import Future
from pathlib import Path

import torch
import torch.nn.functional as F

from .config import MindConfig, set_live
from .data import FineWebStream, Mixer, TextPool
from .model import MindNet
from .optim import build_optimizers, refresh_base_lrs
from .teacher import Teacher
from .tokenizer import make_tokenizer
from .world import ACTIONS, KINDS, World

STAGES = [  # (name, bits per byte above which the mind is still in this stage, blurb)
    ("Static", 99.0, "Random weights: every token is about equally likely, so its output is noise."),
    ("Babbling", 2.4, "It has learned which characters and fragments are common."),
    ("First words", 1.9, "Real words appear, mostly short and frequent ones."),
    ("Phrases", 1.5, "Words start to fit together in short runs."),
    ("Sentences", 1.25, "Grammatical sentences, loosely on topic."),
    ("Conversational", 1.05, "Coherent text that follows a thread (GPT-2 small sits about here)."),
    ("Articulate", 0.0, "Fluent language with real content."),
]
_WORD = re.compile(r"[a-z]+(?:'[a-z]+)?")
_STOP = {"the", "a", "an", "and", "of", "to", "in", "is", "it", "i"}


def pick_device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda")
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


class Mind:
    def __init__(self, cfg: MindConfig, root: Path, device: torch.device | None = None):
        self.cfg = cfg
        self.dir = root / cfg.name
        self.dir.mkdir(parents=True, exist_ok=True)
        self.device = device or pick_device()
        if self.device.type == "cuda":
            torch.backends.cuda.matmul.allow_tf32 = True
            torch.backends.cudnn.allow_tf32 = True
        self.amp_dtype = (torch.bfloat16 if self.device.type == "cuda" and torch.cuda.is_bf16_supported()
                          else None)

        self.tok = make_tokenizer(cfg.tokenizer)
        cfg.tokenizer = self.tok.kind
        cfg.model.vocab_size = self.tok.vocab_size
        self.model = MindNet(cfg.model).to(self.device)
        self._build_optim()

        self.fineweb = FineWebStream(self.tok, cfg.data.fineweb_repo, cfg.data.fineweb_config, cfg.data.buffer_docs)
        self.teacher_pool = TextPool(self.tok, cfg.data.pool_size, on_text=self.fineweb.learn_words)
        self.experience_pool = TextPool(self.tok, cfg.data.pool_size)
        self.mixer = Mixer(cfg, self.fineweb, self.teacher_pool, self.experience_pool)
        self.world = World()
        self.teacher = Teacher(self)

        # progress
        self.step = 0
        self.tokens_trained = 0
        self.age_seconds = 0.0
        self.loss_ema: float | None = None
        self.val_loss: float | None = None
        self.best_val = float("inf")
        self.evals_since_best = 0
        self.val_batches: list[tuple[torch.Tensor, torch.Tensor]] = []
        self.growths = 0
        self.last_gnorm = 0.0
        self.tok_per_sec = 0.0
        self.last_lr = 0.0

        # mind state
        self.memory: list[int] = []                      # running monologue, token ids
        self.thoughts: deque[dict] = deque(maxlen=400)
        self.chat_log: list[dict] = []
        self.vocab_used: set[str] = set()
        self.internals: dict = {}
        self.assessments: list[dict] = []
        self.history: deque[dict] = deque(maxlen=6000)  # metric points for charts

        # body
        self.rl_buf: list[tuple[list[int], int, float, bool]] = []
        self.demo_actions: deque[str] = deque()
        self.narration: list[str] = []
        self.reward_ema = 0.0
        self.action_counts = [0] * len(ACTIONS)
        self.last_policy: list[float] = [1 / len(ACTIONS)] * len(ACTIONS)

        # plumbing
        self.events: deque[dict] = deque(maxlen=3000)
        self.event_id = 0
        self.ev_lock = threading.Lock()
        self.commands: queue.Queue = queue.Queue()
        self.snapshot: dict = {}
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._engine, name="engine", daemon=True)
        self.started_at = time.time()
        self.load()

    # ------------------------------------------------------------------ setup
    def _build_optim(self):
        self.opts = build_optimizers(self.model, self.cfg.train, self.device.type)
        self.train_model = self.model
        if self.cfg.train.compile:
            try:
                self.train_model = torch.compile(self.model)
            except Exception as e:
                print(f"[mind] torch.compile unavailable: {e}")

    def autocast(self):
        if self.amp_dtype is None:
            return contextlib.nullcontext()
        return torch.autocast(self.device.type, dtype=self.amp_dtype)

    def start(self):
        self.fineweb.enabled = self.cfg.data.fineweb_enabled
        self.fineweb.start()
        self.teacher.start()
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=30)
        self.fineweb.stop()
        self.teacher.stop()

    # ------------------------------------------------------------------ events
    def event(self, kind: str, data: dict):
        with self.ev_lock:
            self.event_id += 1
            self.events.append({"id": self.event_id, "kind": kind, "t": time.time(), **data})

    def events_since(self, eid: int) -> list[dict]:
        with self.ev_lock:
            if not self.events or self.events[-1]["id"] <= eid:
                return []
            return [e for e in self.events if e["id"] > eid]

    def call(self, name: str, *args) -> Future:
        f: Future = Future()
        self.commands.put((name, args, f))
        return f

    # ------------------------------------------------------------------ text helpers
    def encode_turns(self, parts: list[tuple[str, str]]) -> list[int]:
        ids: list[int] = []
        for role, text in parts:
            ids.append(self.tok[role])
            ids.extend(self.tok.encode(text))
        return ids

    def thought_texts(self) -> list[str]:
        return [t["text"] for t in self.thoughts if t["text"].strip()]

    def last_thought_text(self) -> str:
        t = self.thought_texts()
        return t[-1] if t else ""

    def world_topics(self) -> list[str]:
        return ["apples and eating", "a friendly cat", "playing with a ball", "reading a book",
                "a lamp in the dark", "a music box", "looking in a mirror", "planting a seed",
                "a garden with a pond", "sleeping in a bed"]

    def stage_index(self) -> int:
        bpb = self.bpb()
        loss = self.val_loss if self.val_loss is not None else self.loss_ema
        if bpb is None or loss > 0.85 * math.log(self.tok.n_real):
            return 0
        for i, (_, thr, _) in enumerate(STAGES[1:], start=1):
            if bpb > thr:
                return i
        return len(STAGES) - 1

    def bpb(self) -> float | None:
        loss = self.val_loss if self.val_loss is not None else self.loss_ema
        if loss is None:
            return None
        return loss / math.log(2) / max(self.fineweb.bytes_per_token, 1e-6)

    def record_assessment(self, scores: dict, note: str):
        a = {"step": self.step, "t": time.time(), **scores, "note": note}
        self.assessments.append(a)
        self.event("assessment", a)

    # ------------------------------------------------------------------ generation
    @torch.no_grad()
    def generate(self, prompt: list[int], max_new: int, temperature: float, top_p: float,
                 stop_on_newline: bool = False) -> list[tuple[int, float, float]]:
        """Sample tokens. Returns [(id, prob, entropy)] and stops at any role token."""
        T = self.cfg.model.seq_len
        ids = list(prompt)
        out = []
        specials = set(self.tok.special.values())
        for _ in range(max_new):
            x = torch.tensor([ids[-T:]], device=self.device)
            with self.autocast():
                logits = self.model(x)[0, -1].float()
            logits[self.tok.n_real:] = float("-inf")
            probs_full = F.softmax(logits, -1)
            ent = float(-(probs_full * probs_full.clamp_min(1e-12).log()).sum())
            p = F.softmax(logits / max(temperature, 1e-3), -1)
            if top_p < 1.0:
                sp, si = p.sort(descending=True)
                keep = sp.cumsum(-1) - sp < top_p
                sp = sp * keep
                nxt = int(si[torch.multinomial(sp / sp.sum(), 1)])
            else:
                nxt = int(torch.multinomial(p, 1))
            if nxt in specials:
                break
            out.append((nxt, float(probs_full[nxt]), ent))
            ids.append(nxt)
            if stop_on_newline and "\n" in self.tok.token_str(nxt) and len(out) > 3:
                break
        return out

    def _render(self, gen: list[tuple[int, float, float]]) -> list[list]:
        return [[self.tok.token_str(t), round(p, 4), round(e, 3)] for t, p, e in gen]

    def _real_word_ratio(self, text: str) -> tuple[float, list[str]]:
        words = [w for w in _WORD.findall(text.lower()) if len(w) > 1 or w in ("a", "i")]
        if not words:
            return 0.0, []
        known = [w for w in words if self.fineweb.known_word(w)]
        return len(known) / len(words), known

    # ------------------------------------------------------------------ activities
    def think(self):
        cfg = self.cfg
        prompt = self.memory[-cfg.memory_tokens:]
        if cfg.thoughts_grounded and cfg.world_enabled:
            prompt = prompt + self.encode_turns([("<|world|>", self.world.observe())])
        prompt = prompt + [self.tok["<|thought|>"]]
        gen = self.generate(prompt, cfg.thought_tokens, cfg.thought_temperature, cfg.thought_top_p)
        ids = [t for t, _, _ in gen]
        text = self.tok.decode(ids)
        self.memory += [self.tok["<|thought|>"]] + ids
        self.memory = self.memory[-4 * cfg.memory_tokens:]
        ratio, known = self._real_word_ratio(text)
        self.vocab_used.update(w for w in known if w not in _STOP)
        self._capture(prompt[-96:] + ids)
        avg_p = sum(p for _, p, _ in gen) / len(gen) if gen else 0.0
        avg_e = sum(e for _, _, e in gen) / len(gen) if gen else 0.0
        th = {"step": self.step, "text": text, "tokens": self._render(gen), "real": round(ratio, 3),
              "confidence": round(avg_p, 4), "entropy": round(avg_e, 3), "grounded": cfg.thoughts_grounded,
              "known": sorted(set(known))[:80]}
        self.thoughts.append(th)
        self.event("thought", th)

    @torch.no_grad()
    def _capture(self, ids: list[int]):
        if not ids:
            return
        ids = ids[-96:]
        cap: dict = {}
        x = torch.tensor([ids], device=self.device)
        with self.autocast():
            self.model.hidden(x, cap)
        last = cap["attn"][-1]
        n = min(48, last.size(0))
        self.internals = {
            "tokens": [self.tok.token_str(t) for t in ids[-n:]],
            "attn": [[round(float(v), 3) for v in row[-n:]] for row in last[-n:]],
            "resid_rms": [round(v, 3) for v in cap["resid_rms"]],
            "attn_entropy": [round(v, 3) for v in cap["attn_entropy"]],
        }

    def chat(self, text: str) -> dict:
        cfg = self.cfg
        parts = [("<|user|>" if m["role"] == "user" else "<|mind|>", m["text"]) for m in self.chat_log[-8:]]
        prompt = self.encode_turns(parts + [("<|user|>", text)]) + [self.tok["<|mind|>"]]
        gen = self.generate(prompt[-(cfg.model.seq_len - cfg.reply_tokens):], cfg.reply_tokens,
                            cfg.reply_temperature, 0.95)
        reply = self.tok.decode([t for t, _, _ in gen]).strip()
        history = [(m["role"], m["text"]) for m in self.chat_log[-8:]]
        self.chat_log.append({"role": "user", "text": text, "t": time.time()})
        msg = {"role": "mind", "text": reply, "t": time.time(), "tokens": self._render(gen), "step": self.step}
        self.chat_log.append(msg)
        self.chat_log = self.chat_log[-400:]
        index = len(self.chat_log) - 1
        if cfg.world_enabled:
            self.world.say(reply or "...")
        # Hearing you is experience in itself; the teacher adds what it should have said.
        self.experience_pool.add_ids(self.encode_turns([("<|user|>", text)]), 2.0, "heard")
        if cfg.teacher_enabled and cfg.ollama_model:
            self.teacher.tutor_reply(history, text, reply)
        self.event("chat", {"user": text, "mind": reply, "tokens": msg["tokens"], "index": index})
        return msg

    def feedback(self, index: int, good: bool):
        """You liked (or disliked) one of its replies. Liked replies become training examples."""
        if not (0 <= index < len(self.chat_log)) or self.chat_log[index]["role"] != "mind":
            return
        self.chat_log[index]["rating"] = 1 if good else -1
        if good and index > 0:
            u, m = self.chat_log[index - 1], self.chat_log[index]
            self.experience_pool.add_ids(self.encode_turns([("<|user|>", u["text"]), ("<|mind|>", m["text"])]),
                                         3.0, "liked")

    def teach(self, text: str):
        self.experience_pool.add(text, 3.0, "taught")
        self.fineweb.learn_words(text)
        self.event("taught", {"text": text[:500]})

    @torch.no_grad()
    def probe(self, text: str) -> dict:
        ids = self.tok.encode(text)[-(self.cfg.model.seq_len - 1):] or [self.tok.eot]
        x = torch.tensor([ids], device=self.device)
        with self.autocast():
            logits = self.model(x)[0].float()
        logits[:, self.tok.n_real:] = float("-inf")
        logp = F.log_softmax(logits, -1)
        surprise = [0.0] + [float(-logp[i, ids[i + 1]]) for i in range(len(ids) - 1)]
        top = logp[-1].exp().topk(12)
        return {
            "tokens": [[self.tok.token_str(t), round(s / math.log(2), 2)] for t, s in zip(ids, surprise)],
            "next": [[self.tok.token_str(int(i)), round(float(p), 4)] for p, i in zip(top.values, top.indices)],
        }

    # ------------------------------------------------------------------ body
    def _obs_ids(self, obs: str) -> list[int]:
        return self.encode_turns([("<|world|>", obs)])[-160:]

    def body_step(self):
        w = self.world
        obs = w.observe()
        ids = self._obs_ids(obs)
        demo = bool(self.demo_actions)
        if demo:
            a = ACTIONS.index(self.demo_actions.popleft())
        else:
            with torch.no_grad(), self.autocast():
                logits, _ = self.model.act(torch.tensor([ids], device=self.device),
                                           torch.tensor([len(ids)], device=self.device))
            p = F.softmax(logits[0].float(), -1)
            self.last_policy = [round(float(v), 4) for v in p]
            a = int(torch.multinomial(p, 1)) if random.random() > 0.05 else random.randrange(len(ACTIONS))
        reward, narr, info = w.step(ACTIONS[a])
        self.action_counts[a] += 1
        self.reward_ema = 0.98 * self.reward_ema + 0.02 * reward

        if info.get("speak"):
            prompt = ids + [self.tok["<|mind|>"]]
            gen = self.generate(prompt, 20, 0.8, 0.95, stop_on_newline=True)
            said = self.tok.decode([t for t, _, _ in gen]).strip()
            w.say(said or "...")
            narr += f' I say: "{said}"'
            self.event("speak", {"text": said})
        if "read" in info:
            book = info["read"]
            if not book.get("text"):
                book["text"] = (self.fineweb.random_text() or random.choice(
                    [t for t, _, _ in self.teacher_pool.texts(200)] or ["The pages are blank."]))[:2000]
            self.experience_pool.add(book["text"], 1.5, "book")
            narr += " It says: " + book["text"][:160].replace("\n", " ") + "..."
            self.event("read", {"text": book["text"][:1200]})
        if info.get("learn"):
            self.experience_pool.add(info["learn"], 2.0, "sign")

        self.rl_buf.append((ids, a, reward, demo))
        self.narration.append(narr)
        if len(self.narration) >= 6:
            self.experience_pool.add_ids(self.encode_turns([("<|world|>", obs),
                                                            ("<|thought|>", " ".join(self.narration))]),
                                         1.0, "lived")
            self.narration = []

    def _rl_loss(self) -> torch.Tensor | None:
        k = self.cfg.train.rl_every
        if len(self.rl_buf) < k + 1:
            return None
        seg, self.rl_buf = self.rl_buf[:k + 1], self.rl_buf[k:]
        L = max(len(s[0]) for s in seg)
        x = torch.full((len(seg), L), self.tok.eot, dtype=torch.long)
        for i, s in enumerate(seg):
            x[i, :len(s[0])] = torch.tensor(s[0])
        lengths = torch.tensor([len(s[0]) for s in seg])
        x, lengths = x.to(self.device), lengths.to(self.device)
        with self.autocast():
            logits, values = self.model.act(x, lengths)
        logits = logits[:-1]
        acts = torch.tensor([s[1] for s in seg[:-1]], device=self.device)
        rews = [s[2] for s in seg[:-1]]
        demo = torch.tensor([s[3] for s in seg[:-1]], device=self.device)
        gamma = 0.95
        with torch.no_grad():
            R = float(values[-1])
            rets = []
            for r in reversed(rews):
                R = r + gamma * R
                rets.append(R)
            rets = torch.tensor(rets[::-1], device=self.device)
            adv = rets - values[:-1].detach()
            adv = (adv - adv.mean()) / (adv.std() + 1e-6)
        logp = F.log_softmax(logits, -1)
        chosen = logp.gather(1, acts[:, None]).squeeze(1)
        own = ~demo
        pg = -(chosen * adv)[own].mean() if own.any() else logits.sum() * 0
        bc = -chosen[demo].mean() if demo.any() else logits.sum() * 0
        v_loss = F.mse_loss(values[:-1], rets)
        ent = -(logp.exp() * logp).sum(-1).mean()
        return pg + 2.0 * bc + 0.5 * v_loss - 0.01 * ent

    # ------------------------------------------------------------------ training
    def _lr_factor(self) -> float:
        return min(1.0, (self.step + 1) / max(1, self.cfg.train.warmup_steps))

    def train_step(self) -> bool:
        cfg, tc = self.cfg, self.cfg.train
        B, T = tc.batch_size, cfg.model.seq_len
        if not self.val_batches and self.fineweb.ready() and cfg.data.fineweb_enabled:
            for _ in range(2):
                rows = [self.fineweb.take(T + 1) for _ in range(B)]
                rows = [r for r in rows if r]
                if rows:
                    t = torch.tensor(rows, device=self.device)
                    self.val_batches.append((t[:, :-1], t[:, 1:]))
        t0 = time.time()
        total = 0.0
        ntok = 0
        for _ in range(tc.grad_accum):
            batch = self.mixer.batch(B, T, self.device)
            if batch is None:
                return False
            x, y = batch
            with self.autocast():
                _, loss = self.train_model(x, y)
            (loss / tc.grad_accum).backward()
            total += float(loss.detach()) / tc.grad_accum
            ntok += x.numel()
        rl = self._rl_loss()
        if rl is not None and tc.rl_coef > 0:
            (tc.rl_coef * rl).backward()
        refresh_base_lrs(self.opts, tc)
        f = self._lr_factor()
        for o in self.opts:
            for g in o.param_groups:
                g["lr"] = g["base_lr"] * f
        self.last_lr = tc.muon_lr * f if tc.optimizer == "muon" else tc.adam_lr * f
        self.last_gnorm = float(torch.nn.utils.clip_grad_norm_(self.model.parameters(), tc.grad_clip))
        for o in self.opts:
            o.step()
            o.zero_grad(set_to_none=True)
        if self.device.type == "cuda":
            torch.cuda.synchronize()
        dt = time.time() - t0
        self.step += 1
        self.tokens_trained += ntok
        self.tok_per_sec = 0.9 * self.tok_per_sec + 0.1 * ntok / max(dt, 1e-6) if self.step > 1 else ntok / dt
        if not math.isfinite(total):
            print("[mind] non-finite loss; skipping")
            return True
        self.loss_ema = total if self.loss_ema is None else 0.98 * self.loss_ema + 0.02 * total
        if self.step % 10 == 0:
            self._metric(total, rl)
        if self.step % tc.eval_every == 0:
            self.evaluate()
        return True

    def _metric(self, loss: float, rl):
        point = {"step": self.step, "tokens": self.tokens_trained, "loss": round(loss, 4),
                 "loss_ema": round(self.loss_ema, 4), "lr": self.last_lr, "gnorm": round(self.last_gnorm, 3),
                 "tps": round(self.tok_per_sec), "reward": round(self.reward_ema, 4),
                 "bpb": round(self.bpb() or 0, 4), "layers": self.cfg.model.n_layers,
                 "real": round(sum(t["real"] for t in list(self.thoughts)[-10:]) / max(1, min(10, len(self.thoughts))), 3),
                 "vocab": len(self.vocab_used)}
        if self.val_loss is not None:
            point["val"] = round(self.val_loss, 4)
        self.history.append(point)
        self.event("metric", point)

    @torch.no_grad()
    def evaluate(self):
        if not self.val_batches:
            return
        losses = []
        for x, y in self.val_batches:
            with self.autocast():
                _, l = self.model(x, y)
            losses.append(float(l))
        self.val_loss = sum(losses) / len(losses)
        if self.val_loss < self.best_val * 0.99:
            self.best_val = self.val_loss
            self.evals_since_best = 0
        else:
            self.evals_since_best += 1
        tc = self.cfg.train
        if (tc.auto_grow and self.evals_since_best >= tc.grow_patience_evals
                and self.cfg.model.n_layers < tc.max_layers):
            self.grow("plateau")

    def grow(self, why: str = "manual"):
        n = self.model.grow()
        self._build_optim()
        self.growths += 1
        self.evals_since_best = 0
        self.best_val = float("inf")
        self.event("growth", {"layers": n, "params": self.model.n_params(), "why": why})
        print(f"[mind] grew to {n} layers ({why})")

    # ------------------------------------------------------------------ engine
    def _engine(self):
        self._next = {"thought": time.time() + 1.0, "body": time.time(), "snap": 0.0,
                      "save": time.time(), "last": time.time()}
        while not self._stop.is_set():
            try:
                if not self._tick():
                    time.sleep(0.02)
            except Exception as e:  # keep the mind alive; show what went wrong
                import traceback
                traceback.print_exc()
                self.event("error", {"text": f"{type(e).__name__}: {e}"[:400]})
                self._snap()
                time.sleep(1.0)
        self.save()

    def _tick(self) -> bool:
        cfg, nx = self.cfg, self._next
        now = time.time()
        self.age_seconds += now - nx["last"]
        nx["last"] = now
        self._drain_commands()
        did = False
        if cfg.world_enabled and now >= nx["body"]:
            nx["body"] = now + cfg.world_tick
            self.body_step()
            did = True
        if now >= nx["thought"]:
            nx["thought"] = time.time() + cfg.thought_interval
            self.think()
            did = True
        if cfg.training and self.train_step():
            did = True
        if now >= nx["snap"]:
            nx["snap"] = now + 0.25
            self._snap()
        if cfg.autosave_minutes > 0 and now - nx["save"] > cfg.autosave_minutes * 60:
            nx["save"] = now
            self.save()
        return did

    def _drain_commands(self):
        while True:
            try:
                name, args, fut = self.commands.get_nowait()
            except queue.Empty:
                return
            try:
                fut.set_result(self._command(name, *args))
            except Exception as e:
                fut.set_exception(e)

    def _command(self, name: str, *args):
        w = self.world
        if name == "chat":
            return self.chat(args[0])
        if name == "probe":
            return self.probe(args[0])
        if name == "teach":
            return self.teach(args[0])
        if name == "feedback":
            return self.feedback(*args)
        if name == "set":
            set_live(self.cfg, args[0], args[1])
            if args[0] == "data.fineweb_enabled":
                self.fineweb.enabled = self.cfg.data.fineweb_enabled
            if args[0] == "ollama_url":
                self.teacher.refresh_models()
            return True
        if name == "grow":
            return self.grow("manual")
        if name == "save":
            return self.save()
        if name == "think":
            return self.think()
        if name == "act":
            if args[0] in ACTIONS:
                self.demo_actions.append(args[0])
            return True
        if name == "place":
            kind, x, y, text = args
            if kind == "erase":
                w.remove_at(x, y)
            elif kind in KINDS:
                extra = {"text": text} if text and kind in ("sign", "book") else {}
                w.add(kind, x, y, **extra)
                if text:
                    self.experience_pool.add(text, 2.0, kind)
            return True
        if name == "refresh_models":
            return self.teacher.refresh_models()
        if name == "reset_world":
            self.world = World()
            return True
        raise ValueError(f"unknown command {name}")

    def _snap(self):
        stage = self.stage_index()
        self.snapshot = {
            "name": self.cfg.name,
            "device": str(self.device) + (f" ({torch.cuda.get_device_name()})" if self.device.type == "cuda" else ""),
            "precision": str(self.amp_dtype).replace("torch.", "") if self.amp_dtype else "float32",
            "step": self.step, "tokens": self.tokens_trained, "age": round(self.age_seconds),
            "params": self.model.n_params(), "trunk_params": self.model.n_params(True),
            "layers": self.cfg.model.n_layers, "d_model": self.cfg.model.d_model,
            "seq_len": self.cfg.model.seq_len, "tokenizer": self.tok.kind, "growths": self.growths,
            "loss": self.loss_ema, "val": self.val_loss, "bpb": self.bpb(), "tps": self.tok_per_sec,
            "lr": self.last_lr, "gnorm": self.last_gnorm,
            "stage": stage, "stage_name": STAGES[stage][0], "stage_blurb": STAGES[stage][2],
            "stages": [s[0] for s in STAGES],
            "vocab": len(self.vocab_used), "vocab_sample": sorted(self.vocab_used)[-60:],
            "fineweb": {"status": self.fineweb.status, "error": self.fineweb.error, "docs": self.fineweb.docs_seen,
                        "buffer": len(self.fineweb.docs), "source": self.fineweb.source, "bytes_per_token": round(self.fineweb.bytes_per_token, 3)},
            "teacher": {"status": self.teacher.status, "error": self.teacher.error, "lessons": self.teacher.lessons,
                        "models": self.teacher.models},
            "pools": {"teacher": len(self.teacher_pool), "experience": len(self.experience_pool)},
            "rows_from": dict(self.mixer.rows_from), "mix_active": self.mixer.weights(),
            "settings": self._settings(),
            "world": self.world.to_dict(),
            "policy": self.last_policy, "actions": ACTIONS, "action_counts": self.action_counts,
            "reward_ema": self.reward_ema, "internals": self.internals,
            "event_id": self.event_id,
        }

    def _settings(self) -> dict:
        from .config import LIVE_SETTINGS
        out = {}
        for k in LIVE_SETTINGS:
            v = self.cfg
            for p in k.split("."):
                v = getattr(v, p)
            out[k] = v
        return out

    # ------------------------------------------------------------------ persistence
    def save(self) -> str:
        path = self.dir / "state.pt"
        tmp = path.with_suffix(".tmp")
        state = {
            "model": self.model.state_dict(),
            "opts": [o.state_dict() for o in self.opts],
            "counters": {"step": self.step, "tokens": self.tokens_trained, "age": self.age_seconds,
                         "loss_ema": self.loss_ema, "val": self.val_loss, "growths": self.growths,
                         "best_val": self.best_val},
            "memory": self.memory,
            "thoughts": list(self.thoughts),
            "chat": self.chat_log,
            "vocab": sorted(self.vocab_used),
            "assessments": self.assessments,
            "history": list(self.history),
            "teacher_pool": list(self.teacher_pool.items),
            "experience_pool": list(self.experience_pool.items),
            "world": self.world.state(),
            "action_counts": self.action_counts,
        }
        torch.save(state, tmp)
        tmp.replace(path)
        self.cfg.save(self.dir / "config.json")
        self.event("saved", {"path": str(path)})
        return str(path)

    def load(self):
        path = self.dir / "state.pt"
        if not path.exists():
            return
        s = torch.load(path, map_location=self.device, weights_only=False)
        self.model.load_state_dict(s["model"])
        try:
            for o, st in zip(self.opts, s["opts"]):
                o.load_state_dict(st)
        except (ValueError, KeyError, RuntimeError) as e:
            print(f"[mind] optimizer state not restored ({e}); continuing with fresh moments")
        c = s["counters"]
        self.step, self.tokens_trained, self.age_seconds = c["step"], c["tokens"], c["age"]
        self.loss_ema, self.val_loss, self.growths = c["loss_ema"], c["val"], c["growths"]
        self.best_val = c.get("best_val", float("inf"))
        self.memory = s["memory"]
        self.thoughts.extend(s["thoughts"])
        self.chat_log = s["chat"]
        self.vocab_used = set(s["vocab"])
        self.assessments = s["assessments"]
        self.history.extend(s["history"])
        self.teacher_pool.items.extend(s["teacher_pool"])
        self.experience_pool.items.extend(s["experience_pool"])
        try:
            self.world.load_state(s["world"])
        except (KeyError, TypeError):
            pass
        self.action_counts = s.get("action_counts", self.action_counts)
        print(f"[mind] resumed {self.cfg.name} at step {self.step} ({self.tokens_trained:,} tokens)")
