"""The Academy: the process where Zen learns. It does nothing else.

It trains Zen's brain on a mixture of:

    FineWeb       the open web, streamed: the language of the world beyond Zen's
    experience    Zen's own life, as it lived it: what it perceived, thought, did and made, and how
                  each deed and each mark turned out. Learnt two ways: predicting what follows
                  what it does (its understanding of the world), and a policy gradient on its
                  own choices (doing more of what turned out well)
    journal       what was said to and by Zen: talks with you, the Sprite's answers and critiques, books
    concepts      drills stating the facts in the concept graph
    lessons       anything written into curriculum.jsonl (nothing by default)

It measures Zen with held-out FineWeb (bits per byte) and with concept tests worded unlike any
drill, publishes a fresh brain to the World every few minutes (and whenever it is told to stop
for the day), and saves its full training state so it can resume exactly where it left off.
"""
from __future__ import annotations

import math
import random
import time
from array import array
from collections import Counter, deque
from pathlib import Path

from .config import AdaConfig
from .proc import STAGES, FileTail, Link, pick_device, stage_of, write_json


def _r(v, n: int = 4):
    return None if v is None else round(float(v), n)


class Pool:
    """Bounded replay pool of token sequences; recent and heavy items are drawn more often."""

    def __init__(self, maxlen: int):
        self.items: deque[tuple[list[int], float, str]] = deque(maxlen=maxlen)
        self.added = 0

    def add(self, ids: list[int], weight: float, tag: str):
        if ids:
            self.items.append((ids, max(0.05, float(weight)), tag))
            self.added += 1

    def __len__(self):
        return len(self.items)

    def take(self, n: int, rng: random.Random, eot: int) -> list[int] | None:
        if not self.items:
            return None
        out: list[int] = []
        while len(out) < n:
            k = len(self.items)
            cands = [k - 1 - rng.randrange(max(1, k // 4)) if rng.random() < 0.5 else rng.randrange(k)
                     for _ in range(4)]
            ids = self.items[rng.choices(cands, [self.items[c][1] for c in cands])[0]][0]
            if len(ids) > n and rng.random() < 0.5:
                ids = ids[rng.randrange(len(ids) - n):]
            out.extend(ids)
            out.append(eot)
        return out[:n]


def run(name: str, root: str, inbox, outbox):
    """Process entry point (spawned by the Hub)."""
    folder = Path(root) / name
    link = Link("academy", inbox, outbox, folder)
    try:
        Academy(folder, link).loop()
    except Exception as e:  # pragma: no cover - reported to the Hub, which restarts us
        link.crash(e)
        raise


class Academy:
    def __init__(self, folder: Path, link: Link):
        import torch

        from .concepts import ConceptGraph
        from .fineweb import FineWebStream
        from .model import Brain
        from .optim import build_optimizers
        from .tokenizer import make_tokenizer

        self.torch = torch
        self.folder, self.link = folder, link
        self.cfg = AdaConfig.load(folder / "config.json")
        self.tok = make_tokenizer(self.cfg.tokenizer)
        self.cfg.brain.vocab_size = self.tok.vocab_size
        self.device = pick_device("auto")
        if self.device.type == "cpu":
            import os

            torch.set_num_threads(max(1, (os.cpu_count() or 4) - 2))   # two cores stay with the World and the Hub
        else:
            torch.set_num_threads(2)   # on the GPU it needs little CPU; the cores stay with Zen's brain and the Sprite
        if self.device.type == "cuda":
            torch.backends.cuda.matmul.allow_tf32 = True
            torch.backends.cudnn.allow_tf32 = True
        self.amp = torch.bfloat16 if self.device.type == "cuda" and torch.cuda.is_bf16_supported() else None
        self.brain = Brain(self.cfg.brain).to(self.device)
        self._Brain, self._build_optimizers = Brain, build_optimizers
        self.opts = build_optimizers(self.brain, self.cfg.academy, self.device.type)
        self.rng = random.Random()
        self.batch_size = self.cfg.academy.batch_size   # may grow to fill the GPU (fit_batch)

        self.fineweb = FineWebStream(self.tok, self.cfg.academy.fineweb_repo, self.cfg.academy.fineweb_config, 2048)
        self.lessons = Pool(6000)
        self.journal = Pool(6000)
        # Zen's lived experience: windows of its stream with its actions and how they turned out
        from .motor import motor_ids
        from .world.studio import vocab_ids

        self.experience: deque = deque(maxlen=6000)    # (ids, acts [[pos, index, advantage, vocab]], ret)
        self.motor = motor_ids(self.tok)
        # the word sets Zen chooses from: its body, the brush, the piano, the clay
        self.vocabs = [self.motor, vocab_ids(self.tok, "paint"), vocab_ids(self.tok, "compose"),
                       vocab_ids(self.tok, "sculpt")]
        self.pg_loss = self.motor_entropy = self.exp_ret = None
        self.concepts = ConceptGraph(folder / "concepts.json")
        self.tails = {"lessons": FileTail(folder / "curriculum.jsonl"), "journal": FileTail(folder / "journal.jsonl"),
                      "experience": FileTail(folder / "experience.jsonl")}
        self.rows_from: Counter = Counter()

        self.step = 0
        self.tokens = 0
        self.loss_ema: float | None = None
        self.val_loss: float | None = None
        self.best_val = float("inf")
        self.evals_since_best = 0
        self.growths = 0
        self.tps = 0.0
        self.gnorm = 0.0
        self.lr = 0.0
        self.skipped = 0
        self.version = 0
        self.last_publish = 0.0
        self.steps_at_publish = -1
        self.concept_score: dict = {}
        self.val_batches: list = []
        self.paused = True
        self.pause_reason = "starting"
        self.intensity_override: str | None = None
        self.status_line = "starting"
        self.load()

    # -------------------------------------------------------------- data
    def ingest(self):
        """Pick up new lessons and journal entries written by the other processes."""
        from .tokenizer import encode_parts

        for rec in self.tails["experience"].read():
            ids, acts = rec.get("ids") or [], rec.get("acts") or []
            if len(ids) > 8 and acts:
                self.experience.append((ids, acts, float(rec.get("ret", 0.0))))
        for name, tail in self.tails.items():
            if name == "experience":
                continue
            pool = self.lessons if name == "lessons" else self.journal
            for rec in tail.read():
                parts = [(r, t) for r, t in rec.get("parts", []) if r in self.tok.special and t]
                ids = encode_parts(self.tok, parts)
                w = float(rec.get("weight", 1.0)) * (3.0 if rec.get("priority") else 1.0)
                pool.add(ids[: self.cfg.brain.seq_len * 4], w, rec.get("kind", name))
                if name == "lessons":
                    self.fineweb.learn_words(" ".join(t for _, t in parts))
        self.concepts.reload()

    def _concept_row(self, n: int) -> list[int]:
        from .tokenizer import encode_parts

        out: list[int] = []
        while len(out) < n:
            out += encode_parts(self.tok, self.concepts.drill(self.rng)) + [self.tok.eot]
        return out[:n]

    def weights(self) -> dict[str, float]:
        a = self.cfg.academy
        return {
            "fineweb": a.mix_fineweb if a.fineweb and self.fineweb.ready() else 0.0,
            "lessons": a.mix_lessons if len(self.lessons) else 0.0,
            "journal": a.mix_journal if len(self.journal) else 0.0,
            "concepts": a.mix_concepts,
        }

    def batch(self, B: int, T: int):
        w = self.weights()
        names = [k for k, v in w.items() if v > 0]
        if not names:
            return None
        rows = []
        for _ in range(B):
            for _try in range(3):
                src = self.rng.choices(names, [w[k] for k in names])[0]
                if src == "fineweb":
                    r = self.fineweb.take(T + 1)
                elif src == "concepts":
                    r = self._concept_row(T + 1)
                else:
                    r = (self.lessons if src == "lessons" else self.journal).take(T + 1, self.rng, self.tok.eot)
                if r:
                    rows.append(r)
                    self.rows_from[src] += 1
                    break
        if not rows:
            return None
        t = self.torch.tensor(rows, dtype=self.torch.long)
        t = t.pin_memory().to(self.device, non_blocking=True) if self.device.type == "cuda" else t.to(self.device)
        return t[:, :-1], t[:, 1:]

    # -------------------------------------------------------------- training
    def autocast(self):
        import contextlib

        return self.torch.autocast(self.device.type, dtype=self.amp) if self.amp else contextlib.nullcontext()

    def train_step(self) -> bool:
        from .optim import set_lrs

        torch, a = self.torch, self.cfg.academy
        B, T = self.batch_size, self.cfg.brain.seq_len
        if not self.val_batches and self.fineweb.ready() and a.fineweb:
            for _ in range(2):
                rows = [r for r in (self.fineweb.take(T + 1) for _ in range(B)) if r]
                if rows:
                    t = torch.tensor(rows, device=self.device)
                    self.val_batches.append((t[:, :-1], t[:, 1:]))
        t0 = time.perf_counter()
        losses, ntok = [], 0
        perf = self.link.perf
        for _ in range(a.grad_accum):
            with perf.time("wait for data"):
                b = self.batch(B, T)
            if b is None:
                for o in self.opts:
                    o.zero_grad(set_to_none=True)
                self.status_line = "waiting for something to study (FineWeb: %s)" % self.fineweb.status
                return False
            x, y = b
            profile = self.device.type == "cuda" and self.step % 100 == 1
            with perf.time("forward + backward"):
                if profile:
                    loss = self.profiled(x, y, a.grad_accum)
                else:
                    with self.autocast():
                        loss = self.brain(x, y, masked=False)       # packed rows: no ignored targets
                    (loss / a.grad_accum).backward()
                losses.append(loss.detach())
            ntok += x.numel()
        if self.experience and a.mix_experience > 0:
            with perf.time("learning from its experience"):
                self.experience_step(max(1, B // 4), T)
        with perf.time("optimizer"):
            gnorm_t = torch.nn.utils.clip_grad_norm_(self.brain.parameters(), a.grad_clip)
        with perf.time("waiting for the GPU"):
            self.gpu_wait()
        total = sum(float(l) for l in losses) / a.grad_accum
        gnorm = float(gnorm_t)
        if not (math.isfinite(total) and math.isfinite(gnorm)):
            for o in self.opts:
                o.zero_grad(set_to_none=True)
            self.skipped += 1
            self.link.warn(f"skipped an unstable step (loss {total}, grad norm {gnorm})", every=30)
            return True
        set_lrs(self.opts, a, min(1.0, (self.step + 1) / max(1, a.warmup_steps)))
        self.lr = a.muon_lr * min(1.0, (self.step + 1) / max(1, a.warmup_steps))
        with perf.time("optimizer"):
            for o in self.opts:
                o.step()
                o.zero_grad(set_to_none=True)
        with perf.time("waiting for the GPU"):
            self.gpu_wait()
        dt = max(time.perf_counter() - t0, 1e-6)
        perf.add("training step", dt)
        self.step += 1
        self.tokens += ntok
        self.gnorm = gnorm
        self.tps = ntok / dt if self.step == 1 else 0.9 * self.tps + 0.1 * ntok / dt
        self.loss_ema = total if self.loss_ema is None else 0.98 * self.loss_ema + 0.02 * total
        self.status_line = "studying"
        if self.step % 20 == 0:
            self.link.send("metric", point=self.point(total))
        if self.step % a.eval_every == 0:
            with perf.time("evaluate"):
                self.evaluate()
        # Leave the GPU some breathing room when asked to.
        mode = self.intensity_override or a.intensity
        rest = {"full": 0.0, "balanced": 0.35, "gentle": 1.5}.get(mode, 0.0)
        if rest:
            with perf.time("resting (intensity)"):
                time.sleep(min(0.5, dt * rest))
        return True

    def experience_step(self, B: int, T: int):
        """Learn from Zen's own life: predict what follows what it did (language-model loss) and do
        more of what turned out well, less of what didn't (policy gradient on its motor words)."""
        torch, a = self.torch, self.cfg.academy
        F = torch.nn.functional
        rows, pos_b, pos_t, act, adv, voc, rets = [], [], [], [], [], [], []
        recent = len(self.experience)
        for b in range(B):
            k = recent - 1 - self.rng.randrange(max(1, recent // 3)) if self.rng.random() < 0.6 else self.rng.randrange(recent)
            ids, acts, ret = self.experience[k]
            ids = ids[: T + 1]
            ids = ids + [self.tok.eot] * (T + 1 - len(ids))
            rows.append(ids)
            rets.append(ret)
            for a_ in acts:
                p, i, ad = a_[0], a_[1], a_[2]
                v = a_[3] if len(a_) > 3 else 0
                if 1 <= p <= T and 0 <= v < len(self.vocabs) and 0 <= i < len(self.vocabs[v]):
                    pos_b.append(b)                   # the action at p is predicted from position p-1
                    pos_t.append(p - 1)
                    act.append(int(i))
                    adv.append(float(ad))
                    voc.append(int(v))
        if not act:
            return
        t = torch.tensor(rows, dtype=torch.long, device=self.device)
        x, y = t[:, :-1], t[:, 1:]
        with self.autocast():
            h = self.brain.hidden(x)
            lm = self.brain.chunked_loss(h, y, masked=False)
            hp = h[torch.tensor(pos_b, device=self.device), torch.tensor(pos_t, device=self.device)]
        chosen_all, ents, advs = [], [], []
        for v, words in enumerate(self.vocabs):
            sel = [k for k, vv in enumerate(voc) if vv == v]
            if not sel:
                continue
            sel_t = torch.tensor(sel, device=self.device)
            with self.autocast():
                z = self.brain.motor_logits(hp[sel_t], torch.tensor(words, device=self.device))
            logp = F.log_softmax(z.float(), -1)
            a_t = torch.tensor([act[k] for k in sel], device=self.device)
            chosen_all.append(logp.gather(1, a_t[:, None])[:, 0])
            ents.append(-(logp.exp() * logp).sum(-1))
            advs.append(torch.tensor([adv[k] for k in sel], device=self.device, dtype=torch.float32))
        chosen, adv_t = torch.cat(chosen_all), torch.cat(advs)
        ent = torch.cat(ents).mean()
        pg = -(adv_t * chosen).mean()
        loss = a.mix_experience * (lm + a.pg_coef * pg - a.entropy_coef * ent)
        (loss / a.grad_accum).backward()
        e = 0.95 if self.pg_loss is not None else 0.0
        self.pg_loss = e * (self.pg_loss or 0.0) + (1 - e) * float(pg.detach())
        self.motor_entropy = e * (self.motor_entropy or 0.0) + (1 - e) * float(ent.detach())
        self.exp_ret = e * (self.exp_ret or 0.0) + (1 - e) * (sum(rets) / len(rets))

    def gpu_wait(self):
        """Wait for the GPU to finish its queued work while *sleeping*. torch.cuda.synchronize() and
        reading a number off the GPU spin a CPU core at 100% the whole time the GPU works, which
        heats the CPU for nothing (laptops share one cooler between the CPU and the GPU)."""
        if self.device.type == "cuda":
            ev = self.torch.cuda.Event(blocking=True)
            ev.record()
            ev.synchronize()

    def profiled(self, x, y, accum: int):
        """One training pass timed part by part on the GPU itself (every 100 steps)."""
        torch = self.torch
        ev = [torch.cuda.Event(enable_timing=True) for _ in range(4)]
        ev[0].record()
        with self.autocast():
            h = self.brain.hidden(x)
            ev[1].record()
            loss = self.brain.chunked_loss(h, y, masked=False)
        ev[2].record()
        (loss / accum).backward()
        ev[3].record()
        self.gpu_wait()
        perf = self.link.perf
        perf.gauge("profile_forward_ms", round(ev[0].elapsed_time(ev[1]), 1))
        perf.gauge("profile_loss_ms", round(ev[1].elapsed_time(ev[2]), 1))
        perf.gauge("profile_backward_ms", round(ev[2].elapsed_time(ev[3]), 1))
        return loss

    def fit_batch(self):
        """Use the GPU's memory: pick the largest batch that fits in what is free.

        Bigger batches keep the GPU busier and spend less time in the optimizer per token. The
        memory a batch needs is measured (two trial passes) rather than found by running out:
        on Windows, running out doesn't fail, it quietly spills into ordinary RAM and crawls."""
        torch, a = self.torch, self.cfg.academy
        if self.device.type != "cuda" or not a.auto_batch:
            self.batch_size = a.batch_size
            return
        T, V = self.cfg.brain.seq_len, self.cfg.brain.vocab_size
        per = 0.0
        try:
            peaks = {}
            for b in (4, 8):
                torch.cuda.empty_cache()
                torch.cuda.reset_peak_memory_stats()
                x = torch.randint(0, V, (b, T), device=self.device)
                with self.autocast():
                    loss = self.brain(x, x)
                loss.backward()
                self.gpu_wait()
                peaks[b] = torch.cuda.max_memory_allocated()
                for p in self.brain.parameters():
                    p.grad = None
            per = max(1, (peaks[8] - peaks[4]) / 4)                       # bytes per sequence
            base = peaks[4] - 4 * per
            # The optimizers' state, if it doesn't exist yet (otherwise it's already in the peaks).
            states = 0 if any(o.state for o in self.opts) else \
                3 * sum(p.numel() * p.element_size() for p in self.brain.parameters())
            free, total = torch.cuda.mem_get_info()
            # Leave room for the desktop, the browser and the allocator's slack.
            budget = (free + torch.cuda.memory_reserved()) * 0.85 - max(600 << 20, 0.08 * total)
            fit = int((budget - base - states) // per)
            b = max(a.batch_size, min(a.max_batch_size, fit // 8 * 8))
            torch.cuda.empty_cache()
        except Exception as e:  # noqa: BLE001 - keep training with the configured batch
            self.link.warn(f"couldn't size the batch to the GPU ({type(e).__name__}: {e})")
            b = a.batch_size
        if b != self.batch_size or not getattr(self, "_fit_logged", False):
            self._fit_logged = True
            self.link.log(f"batch: {b} x {T} tokens ({b * T:,} per step) to use the GPU's free memory "
                          f"(about {per / 2**20:.0f} MB per sequence)" if b != a.batch_size else
                          f"batch: {b} x {T} tokens (no room for more)")
        self.batch_size = b

    def gpu_speed_test(self):
        """How fast this GPU multiplies matrices right now: the ceiling for training speed."""
        torch = self.torch
        if self.device.type != "cuda":
            return
        try:
            n = 4096
            dt = self.amp or torch.float16
            a = torch.randn(n, n, device=self.device, dtype=dt)
            b = torch.randn(n, n, device=self.device, dtype=dt)
            for _ in range(3):
                a @ b
            torch.cuda.synchronize()
            t = time.perf_counter()
            for _ in range(20):
                a @ b
            torch.cuda.synchronize()
            tflops = 20 * 2 * n ** 3 / (time.perf_counter() - t) / 1e12
            del a, b
            torch.cuda.empty_cache()
            self.link.perf.gauge("gpu_test_tflops", round(tflops, 1))
            free, total = torch.cuda.mem_get_info()
            self.link.log(f"GPU speed test: {tflops:.1f} TFLOPS ({torch.cuda.get_device_name()}, "
                          f"{free / 2**20:.0f} of {total / 2**20:.0f} MB free, PyTorch {torch.__version__}, "
                          f"CUDA {torch.version.cuda}, flash attention "
                          f"{'on' if torch.backends.cuda.flash_sdp_enabled() else 'off'})")
        except Exception as e:
            self.link.warn(f"GPU speed test failed: {type(e).__name__}: {e}")

    def point(self, loss: float | None = None) -> dict:
        p = {"step": self.step, "tokens": self.tokens, "loss": None if loss is None else round(loss, 4),
             "loss_ema": None if self.loss_ema is None else round(self.loss_ema, 4),
             "bpb": None if self.bpb() is None else round(self.bpb(), 4), "tps": round(self.tps),
             "layers": self.cfg.brain.n_layers, "t": time.time()}
        if self.val_loss is not None:
            p["val"] = round(self.val_loss, 4)
        if self.concept_score:
            p["concepts"] = self.concept_score.get("accuracy")
        if self.pg_loss is not None:
            p["pg"], p["ent"], p["ret"] = _r(self.pg_loss), _r(self.motor_entropy), _r(self.exp_ret)
        return p

    def bpb(self) -> float | None:
        loss = self.val_loss if self.val_loss is not None else self.loss_ema
        if loss is None:
            return None
        return loss / math.log(2) / max(self.fineweb.bytes_per_token, 1e-6)

    def stage(self) -> int:
        return stage_of(self.val_loss if self.val_loss is not None else self.loss_ema, self.bpb(), self.tok.n_real)

    # -------------------------------------------------------------- evaluation
    def evaluate(self):
        torch = self.torch
        with torch.no_grad():
            if self.val_batches:
                ls = []
                for x, y in self.val_batches:
                    with self.autocast():
                        ls.append(float(self.brain(x, y)))
                self.val_loss = sum(ls) / len(ls)
                if self.val_loss < self.best_val * 0.99:
                    self.best_val, self.evals_since_best = self.val_loss, 0
                else:
                    self.evals_since_best += 1
            self.concept_score = self.concept_test()
        self.link.send("metric", point=self.point())
        self.link.send("concepts", report=self.concept_score)
        write_json(self.folder / "concept_report.json", self.concept_score)
        a = self.cfg.academy
        if a.auto_grow and self.evals_since_best >= a.grow_patience_evals and self.cfg.brain.n_layers < a.max_layers:
            self.grow("its learning had levelled off")

    def concept_test(self) -> dict:
        """Score every concept probe: the option whose sentence the brain finds most likely wins."""
        torch, F = self.torch, self.torch.nn.functional
        probes = self.concepts.probes()
        if not probes:
            return {}
        seqs = [[self.tok.eot] + self.tok.encode(s) for p in probes for s in p["sentences"]]
        scores = []
        for i in range(0, len(seqs), 64):
            chunk = seqs[i:i + 64]
            L = max(map(len, chunk))
            x = torch.full((len(chunk), L), self.tok.eot, dtype=torch.long)
            mask = torch.zeros(len(chunk), L - 1)
            for j, s in enumerate(chunk):
                x[j, :len(s)] = torch.tensor(s)
                mask[j, :len(s) - 1] = 1
            x = x.to(self.device)
            with self.autocast():
                logits = self.brain(x[:, :-1])
            lp = F.log_softmax(logits.float(), -1).gather(-1, x[:, 1:, None]).squeeze(-1).cpu()
            scores += ((lp * mask).sum(1) / mask.sum(1)).tolist()
        results, by_rel, by_src = [], Counter(), Counter()
        tot_rel, tot_src = Counter(), Counter()
        src_of = dict(self.concepts.all())
        for k, p in enumerate(probes):
            sc = scores[4 * k:4 * k + 4]
            choice = p["options"][max(range(4), key=lambda i: sc[i])]
            ok = choice == p["o"]
            src = src_of.get((p["s"], p["r"], p["o"]), "oracle")
            results.append({"s": p["s"], "r": p["r"], "o": p["o"], "chose": choice, "ok": ok, "src": src})
            by_rel[p["r"]] += ok
            tot_rel[p["r"]] += 1
            by_src[src] += ok
            tot_src[src] += 1
        acc = sum(r["ok"] for r in results) / len(results)
        return {"accuracy": round(acc, 4), "chance": 0.25, "n": len(results), "step": self.step,
                "by_relation": {r: round(by_rel[r] / tot_rel[r], 3) for r in tot_rel},
                "by_source": {s: round(by_src[s] / tot_src[s], 3) for s in tot_src},
                "results": results}

    @staticmethod
    def _finite(sd) -> bool:
        import torch

        return all(bool(torch.isfinite(v).all()) for v in sd.values() if v.is_floating_point())

    # -------------------------------------------------------------- publishing and saving
    def publish(self, why: str = "scheduled"):
        """Hand the World a fresh brain (bf16 weights + a small description)."""
        if not self._finite(self.brain.state_dict()):
            self.link.log("not publishing: the weights are not finite; restoring the last save", error=True)
            self.load()
            return
        brain_dir = self.folder / "brain"
        brain_dir.mkdir(exist_ok=True)
        self.version += 1
        sd = {k: v.detach().to("cpu", self.torch.bfloat16) for k, v in self.brain.state_dict().items()}
        tmp = brain_dir / "latest.pt.tmp"
        self.torch.save({"weights": sd, "brain": vars(self.cfg.brain).copy(), "tokenizer": self.tok.kind}, tmp)
        tmp.replace(brain_dir / "latest.pt")
        st = self.stage()
        meta = {"version": self.version, "step": self.step, "tokens": self.tokens, "t": time.time(),
                "layers": self.cfg.brain.n_layers, "stage": st, "stage_name": STAGES[st][0], "bpb": self.bpb(),
                "concepts": self.concept_score.get("accuracy"), "why": why}
        write_json(brain_dir / "latest.json", meta)
        self.last_publish, self.steps_at_publish = time.time(), self.step
        self.link.send("published", meta=meta)

    def save(self):
        if not self._finite(self.brain.state_dict()):
            return
        state = {
            "brain": self.brain.state_dict(), "opts": [o.state_dict() for o in self.opts],
            "brain_cfg": vars(self.cfg.brain).copy(),
            "counters": dict(step=self.step, tokens=self.tokens, loss_ema=self.loss_ema, val_loss=self.val_loss,
                             best_val=self.best_val, growths=self.growths, version=self.version),
            "concept_score": self.concept_score,
            "pools": {n: [(array("i", ids).tobytes(), w, tag) for ids, w, tag in p.items]
                      for n, p in (("lessons", self.lessons), ("journal", self.journal))},
            "tails": {n: t.pos for n, t in self.tails.items()},
        }
        path = self.folder / "academy.pt"
        tmp = path.with_suffix(".tmp")
        self.torch.save(state, tmp)
        if path.exists():
            path.replace(self.folder / "academy.prev.pt")
        tmp.replace(path)

    def load(self):
        torch = self.torch
        for name in ("academy.pt", "academy.prev.pt"):
            path = self.folder / name
            if not path.exists():
                continue
            s = torch.load(path, map_location=self.device, weights_only=False)
            if not self._finite(s["brain"]):
                self.link.log(f"{name} holds broken weights; trying the previous save", error=True)
                continue
            for k, v in s["brain_cfg"].items():
                setattr(self.cfg.brain, k, v)
            self.brain = self._Brain(self.cfg.brain).to(self.device)
            self.brain.load_state_dict(s["brain"])
            self.opts = self._build_optimizers(self.brain, self.cfg.academy, self.device.type)
            try:
                for o, st in zip(self.opts, s["opts"]):
                    o.load_state_dict(st)
            except (ValueError, KeyError, RuntimeError):
                pass
            c = s["counters"]
            self.step, self.tokens, self.loss_ema = c["step"], c["tokens"], c["loss_ema"]
            self.val_loss, self.best_val, self.growths = c["val_loss"], c["best_val"], c["growths"]
            self.version = c.get("version", 0)
            self.concept_score = s.get("concept_score", {})
            if not self.lessons.items:
                for pname, pool in (("lessons", self.lessons), ("journal", self.journal)):
                    for b, w, tag in s["pools"].get(pname, []):
                        ids = array("i")
                        ids.frombytes(b)
                        pool.add(ids.tolist(), w, tag)
                for n, pos in s.get("tails", {}).items():
                    if n in self.tails:
                        self.tails[n].pos = pos
            self.link.log(f"resumed at step {self.step} ({self.tokens:,} tokens) from {name}")
            return

    def grow(self, why: str):
        n = self.brain.grow()
        self.opts = self._build_optimizers(self.brain, self.cfg.academy, self.device.type)
        self.fit_batch()
        self.growths += 1
        self.evals_since_best, self.best_val = 0, float("inf")
        self.link.send("grew", layers=n, params=self.brain.n_params(), why=why)
        self.link.log(f"grew to {n} layers ({why})")

    # -------------------------------------------------------------- control
    def handle(self, msg: dict):
        cmd, rid = msg.get("cmd"), msg.get("rid")
        try:
            if cmd == "config":
                new = AdaConfig.from_dict(msg["config"])
                new.brain = self.cfg.brain                 # the shape is ours to change, not the Hub's
                self.cfg = new
                self.fineweb.enabled = self.cfg.academy.fineweb
            elif cmd == "pause":
                was_studying = not self.paused
                self.paused, self.pause_reason = True, msg.get("why", "paused")
                if was_studying:
                    if self.step != self.steps_at_publish:
                        self.publish("end of a study session")   # she wakes up with what she learned
                    self.save()
            elif cmd == "resume":
                self.paused, self.pause_reason = False, ""
                self.intensity_override = msg.get("intensity")
            elif cmd == "publish":
                self.publish("you asked for it")
            elif cmd == "grow":
                self.grow("you asked for it")
            elif cmd == "save":
                self.save()
            elif cmd == "evaluate":
                self.evaluate()
            elif cmd == "probe":
                self.link.reply(rid, self.probe(msg["text"]))
                return
            elif cmd == "stop":
                raise SystemExit
            self.link.reply(rid, True)
        except SystemExit:
            raise
        except Exception as e:
            self.link.reply(rid, error=f"{type(e).__name__}: {e}")

    def probe(self, text: str) -> dict:
        torch, F = self.torch, self.torch.nn.functional
        ids = self.tok.encode(text)[-(self.cfg.brain.seq_len - 1):] or [self.tok.eot]
        with torch.no_grad(), self.autocast():
            logits = self.brain(torch.tensor([ids], device=self.device))[0].float()
        logits[:, self.tok.n_real:] = float("-inf")
        lp = F.log_softmax(logits, -1)
        surprise = [0.0] + [float(-lp[i, ids[i + 1]]) / math.log(2) for i in range(len(ids) - 1)]
        top = lp[-1].exp().topk(10)
        return {"tokens": [[self.tok.token_str(t), round(s, 2)] for t, s in zip(ids, surprise)],
                "next": [[self.tok.token_str(int(i)), round(float(p), 4)] for p, i in zip(top.values, top.indices)]}

    def status(self) -> dict:
        st = self.stage()
        tot = sum(self.rows_from.values()) or 1
        return {
            "paused": self.paused, "pause_reason": self.pause_reason, "line": self.status_line,
            "intensity": self.intensity_override or self.cfg.academy.intensity,
            "step": self.step, "tokens": self.tokens, "tps": self.tps, "loss": self.loss_ema, "val": self.val_loss,
            "bpb": self.bpb(), "stage": st, "stage_name": STAGES[st][0], "stage_blurb": STAGES[st][2],
            "stages": [s[0] for s in STAGES], "lr": self.lr, "gnorm": self.gnorm, "skipped": self.skipped,
            "params": self.brain.n_params(), "trunk_params": self.brain.n_params(True),
            "layers": self.cfg.brain.n_layers, "d_model": self.cfg.brain.d_model, "seq_len": self.cfg.brain.seq_len,
            "growths": self.growths, "device": str(self.device) + (
                f" ({self.torch.cuda.get_device_name()})" if self.device.type == "cuda" else ""),
            "precision": "bf16" if self.amp else "fp32", "tokenizer": self.tok.kind,
            "version": self.version, "last_publish": self.last_publish,
            "mix": {k: round(v / tot, 3) for k, v in self.rows_from.items()},
            "pools": {"lessons": len(self.lessons), "journal": len(self.journal),
                      "lessons_added": self.lessons.added, "journal_added": self.journal.added,
                      "facts": len(self.concepts.facts), "experience": len(self.experience)},
            "motor": {"pg_loss": _r(self.pg_loss), "entropy": _r(self.motor_entropy), "return": _r(self.exp_ret),
                      "windows": len(self.experience)},
            "fineweb": {"status": self.fineweb.status, "error": self.fineweb.error, "docs": self.fineweb.docs_seen,
                        "buffer": len(self.fineweb.docs), "source": self.fineweb.source,
                        "bytes_per_token": round(self.fineweb.bytes_per_token, 3)},
            "concepts": {k: v for k, v in self.concept_score.items() if k != "results"},
        }

    def loop(self):
        self.fineweb.enabled = self.cfg.academy.fineweb
        self.fineweb.start()
        self.gpu_speed_test()
        self.fit_batch()
        self.ingest()
        if not (self.folder / "brain" / "latest.pt").exists():
            self.publish("her first brain")   # the World needs something to live with, even if it's noise
        self.concept_score = self.concept_score or self.concept_test()
        self.link.send("concepts", report=self.concept_score)
        last_ingest = last_status = 0.0
        last_save = time.time()
        while True:
            if not self.link.hub_alive():
                self.save()
                return
            for msg in self.link.commands():
                self.handle(msg)
            now = time.time()
            perf = self.link.perf
            if now - last_ingest > 2.0:
                last_ingest = now
                with perf.time("reading lessons and journal"):
                    self.ingest()
            did = False
            if not self.paused:
                did = self.train_step()
                if self.cfg.academy.publish_minutes > 0 and now - self.last_publish > self.cfg.academy.publish_minutes * 60 \
                        and self.step != self.steps_at_publish:
                    with perf.time("publishing a brain"):
                        self.publish()
                if now - last_save > 600:
                    last_save = now
                    with perf.time("saving"):
                        self.save()
            else:
                self.status_line = f"resting ({self.pause_reason})"
            if now - last_status > 1.0:
                last_status = now
                self.link.send("status", status=self.status())
                perf.gauge("studying", 0 if self.paused else 1)
                perf.gauge("device", self.device.type)
                perf.gauge("tokens_per_s", round(self.tps))
                perf.gauge("fineweb_ready_docs", len(self.fineweb.docs))
                perf.gauge("batch_tokens", self.batch_size * self.cfg.brain.seq_len * self.cfg.academy.grad_accum)
                if self.device.type == "cuda":
                    cuda = self.torch.cuda
                    perf.gauge("gpu_memory_peak_mb", round(cuda.max_memory_allocated() / 2**20))
                    perf.gauge("gpu_memory_reserved_mb", round(cuda.memory_reserved() / 2**20))
                    free, total = cuda.mem_get_info()
                    perf.gauge("gpu_free_mb", round(free / 2**20))
                    perf.gauge("gpu_total_mb", round(total / 2**20))
                    cuda.reset_peak_memory_stats()
                    if not self.paused and self.tps:
                        # rough useful work done per second: 6 x parameters x tokens
                        perf.gauge("training_tflops", round(6 * self.brain.n_params() * self.tps / 1e12, 2))
                self.link.maybe_send_perf()
            if not did:
                time.sleep(0.1)
