"""Zen's body, driven by its own mind.

Zen lives one continuous stream of experience: what it perceives (<|world|>), what it thinks
(<|thought|>), what it says (<|mind|>), what it is told (<|oracle|>, <|user|>) and what it does
(<|act|> followed by one motor word). Each motor action is sampled from Zen's brain (the language
model the Academy trains) with its logits restricted to the motor words. Nothing else moves Zen.

The World answers every action with a consequence and a reward. `Experience` turns the stream
into training windows for the Academy: the tokens (so Zen learns to predict what follows what it
does) and, at each action, the advantage of that action (so Zen learns to do what turned out well).
"""
from __future__ import annotations

import math
import threading

MOTOR = ["forward", "back", "left", "right", "wait", "take", "drop", "eat", "drink", "use", "sleep", "look",
         "speak", "ask"]
GAMMA = 0.95


def motor_ids(tok) -> list[int]:
    """The token of each motor word: one token each, with its leading space (fineweb32k, gpt2).
    A byte-level tokenizer has no whole words, so there each action is one capital letter."""
    words = [tok.encode(" " + w) for w in MOTOR]
    if all(len(x) == 1 for x in words) and len({x[0] for x in words}) == len(MOTOR):
        return [x[0] for x in words]
    return [tok.encode(chr(65 + i))[0] for i in range(len(MOTOR))]


class MotorMind:
    """Zen's stream as its brain sees it, with the attention cache kept between actions.

    The World's thread appends tokens (`push`); the brain's thread folds them into the cache and
    chooses actions (`choose`). When the stream outgrows the brain's window, the cache is rebuilt
    from the most recent half."""

    def __init__(self, seq_len: int):
        self.T = seq_len
        self.lock = threading.Lock()
        self.ids: list[int] = []          # the whole recent stream (bounded)
        self.pending: list[int] = []      # appended but not yet seen by the brain
        self.caches = None
        self.cached = 0                   # tokens in the cache
        self.brain = None
        self.h = None                     # the brain's last hidden state

    def push(self, ids: list[int]):
        with self.lock:
            self.pending.extend(ids)

    def tail(self, n: int) -> list[int]:
        with self.lock:
            return (self.ids + self.pending)[-n:]

    def _sync(self, brain):
        import torch

        with self.lock:
            new, self.pending = self.pending, []
        self.ids.extend(new)
        if len(self.ids) > 4 * self.T:
            self.ids = self.ids[-2 * self.T:]
        dev = brain.embed.weight.device
        if brain is not self.brain or self.caches is None or self.cached + len(new) > self.T - 8:
            keep = self.ids[-(self.T // 2):] or [0]
            self.caches = [{} for _ in brain.blocks]
            self.h = brain.hidden(torch.tensor([keep], device=dev), self.caches)
            self.cached, self.brain = len(keep), brain
        elif new:
            self.h = brain.hidden(torch.tensor([new], device=dev), self.caches)
            self.cached += len(new)

    def choose(self, brain, motor: list[int], act_token: int, temperature: float, rng, words: list[str] = MOTOR) -> dict:
        """On the brain's thread: read the stream so far, then pick the next word from `motor` (the token
        ids of `words`: its body's motor words, or a brush's, a piano's or the clay's)."""
        import torch

        self.push([act_token])
        with torch.no_grad():
            self._sync(brain)
            z = brain.motor_logits(self.h[0, -1], motor).float()
            p_full = torch.softmax(z, -1)
            p = torch.softmax(z / max(1e-3, temperature), -1)
            i = int(torch.multinomial(p, 1, generator=None)) if rng is None else _sample(p.tolist(), rng)
            ent = float(-(p_full * p_full.clamp_min(1e-12).log()).sum())
        self.push([motor[i]])
        return {"index": i, "word": words[i], "probs": [round(x, 4) for x in p_full.tolist()], "entropy": ent}

    def reset(self):
        with self.lock:
            self.caches, self.cached, self.brain, self.h = None, 0, None, None


def _sample(p: list[float], rng) -> int:
    r, acc = rng.random() * sum(p), 0.0
    for i, x in enumerate(p):
        acc += x
        if r <= acc:
            return i
    return len(p) - 1


class Experience:
    """Records Zen's stream with the action positions and rewards, and cuts it into training
    windows once enough of the future is known to score each action (discounted return)."""

    def __init__(self, window: int, lookahead: int = 30):
        self.window = window
        self.lookahead = lookahead
        self.ids: list[int] = []
        self.acts: list[list] = []        # [position in ids, motor index, reward]
        self.baseline = 0.0
        self.var = 1.0
        self.n = 0

    def tokens(self, ids: list[int]):
        self.ids.extend(ids)

    def act(self, index: int, vocab: int = 0, position_offset: int = -1):
        """The action token was just appended to `ids` (its position is the last one). `vocab`: which
        set of words it was chosen from (0 motor, 1 paint, 2 music, 3 sculpt)."""
        self.acts.append([len(self.ids) + position_offset, index, 0.0, vocab])

    def reward(self, r: float):
        if self.acts:
            self.acts[-1][2] += r

    def ready(self) -> list[dict]:
        """Windows whose actions all have `lookahead` later actions to score them."""
        out = []
        while len(self.ids) > self.window:
            cut = self.window
            later = [a for a in self.acts if a[0] >= cut]
            if len(later) < self.lookahead and len(self.ids) < 3 * self.window:
                break                                  # wait until the future of these actions is known
            rets = self._returns(self.acts)
            acts, rs = [], []
            for (pos, idx, r, voc), g in zip(self.acts, rets):
                if 1 <= pos < cut:
                    acts.append([pos, idx, round(self._advantage(g), 4), voc])
                    rs.append(r)
            if acts:
                out.append({"ids": self.ids[:cut], "acts": acts, "ret": round(sum(rs) / len(rs), 4),
                            "steps": len(acts)})
            self.ids = self.ids[cut:]
            self.acts = [[p - cut, i, r, v] for p, i, r, v in later]
        return out

    def _returns(self, acts) -> list[float]:
        g, out = 0.0, []
        for _, _, r, _ in reversed(acts):
            g = r + GAMMA * g
            out.append(g)
        return out[::-1]

    def _advantage(self, g: float) -> float:
        self.n += 1
        a = 0.01 if self.n > 50 else 1.0 / self.n
        d = g - self.baseline
        self.baseline += a * d
        self.var = (1 - a) * self.var + a * d * d
        return max(-3.0, min(3.0, d / math.sqrt(self.var + 1e-6)))

    def state(self) -> dict:
        return {"baseline": self.baseline, "var": self.var, "n": self.n}

    def load(self, s: dict):
        self.baseline, self.var, self.n = s.get("baseline", 0.0), s.get("var", 1.0), s.get("n", 0)
