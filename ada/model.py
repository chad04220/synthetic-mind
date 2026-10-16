"""Ada's brain: a decoder-only transformer trained from random weights.

RMSNorm, rotary positions, QK-norm, SwiGLU, tied embeddings, tanh logit soft-capping and
zero-initialised residual outputs (so `grow()` can add depth without changing what it computes).
`generate()` uses a key/value cache, which makes the World's inference cheap enough to run on a
CPU while the Academy keeps the GPU.
"""
from __future__ import annotations

import math

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.checkpoint import checkpoint

from .config import BrainConfig


def rms_norm(x: torch.Tensor) -> torch.Tensor:
    return F.rms_norm(x, (x.size(-1),))


class Rotary(nn.Module):
    def __init__(self, head_dim: int, base: float):
        super().__init__()
        inv = 1.0 / (base ** (torch.arange(0, head_dim, 2, dtype=torch.float32) / head_dim))
        self.register_buffer("inv_freq", inv, persistent=False)
        self._cache = None

    def forward(self, x: torch.Tensor, offset: int = 0) -> torch.Tensor:  # x: B,H,T,D
        end = offset + x.size(2)
        if self._cache is None or self._cache[0] < end or self._cache[1] != x.device:
            t = torch.arange(max(end, 1024), device=x.device, dtype=torch.float32)
            f = torch.outer(t, self.inv_freq.to(x.device))
            self._cache = (f.size(0), x.device, f.cos(), f.sin())
        cos = self._cache[2][offset:end].to(x.dtype)
        sin = self._cache[3][offset:end].to(x.dtype)
        x1, x2 = x.chunk(2, dim=-1)
        return torch.cat((x1 * cos - x2 * sin, x1 * sin + x2 * cos), dim=-1)


class Attention(nn.Module):
    def __init__(self, cfg: BrainConfig, rotary: Rotary):
        super().__init__()
        self.n_heads = cfg.n_heads
        self.qkv = nn.Linear(cfg.d_model, 3 * cfg.d_model, bias=False)
        self.proj = nn.Linear(cfg.d_model, cfg.d_model, bias=False)
        nn.init.zeros_(self.proj.weight)
        self.rotary = rotary

    def forward(self, x, cache: dict | None = None, capture: dict | None = None):
        B, T, C = x.shape
        q, k, v = self.qkv(x).view(B, T, 3, self.n_heads, C // self.n_heads).permute(2, 0, 3, 1, 4)
        offset = cache["k"].size(2) if cache and "k" in cache else 0
        q, k = rms_norm(q), rms_norm(k)
        q, k = self.rotary(q, offset), self.rotary(k, offset)
        if cache is not None:
            if "k" in cache:
                k = torch.cat([cache["k"], k], dim=2)
                v = torch.cat([cache["v"], v], dim=2)
            cache["k"], cache["v"] = k, v
        if capture is not None:
            att = (q @ k.transpose(-2, -1)) / math.sqrt(q.size(-1))
            mask = torch.ones(T, k.size(2), dtype=torch.bool, device=x.device).tril(k.size(2) - T)
            att = att.masked_fill(~mask, float("-inf")).softmax(-1)
            y = att @ v
            capture.setdefault("attn", []).append(att[0].float().mean(0).cpu())
        elif offset and T == 1:
            y = F.scaled_dot_product_attention(q, k, v)            # one new token sees everything
        elif offset:
            # several new tokens after a cache: each sees all of the past and the new ones up to itself
            # (is_causal would align the mask to the top-left corner and hide the past from them)
            mask = torch.ones(T, k.size(2), dtype=torch.bool, device=x.device).tril(k.size(2) - T)
            y = F.scaled_dot_product_attention(q, k, v, attn_mask=mask)
        else:
            y = F.scaled_dot_product_attention(q, k, v, is_causal=True)
        return self.proj(y.transpose(1, 2).reshape(B, T, C))


class SwiGLU(nn.Module):
    def __init__(self, cfg: BrainConfig):
        super().__init__()
        self.gate_up = nn.Linear(cfg.d_model, 2 * cfg.mlp_hidden, bias=False)
        self.down = nn.Linear(cfg.mlp_hidden, cfg.d_model, bias=False)
        nn.init.zeros_(self.down.weight)

    def forward(self, x):
        g, u = self.gate_up(x).chunk(2, dim=-1)
        return self.down(F.silu(g) * u)


class Block(nn.Module):
    def __init__(self, cfg: BrainConfig, rotary: Rotary):
        super().__init__()
        self.attn = Attention(cfg, rotary)
        self.mlp = SwiGLU(cfg)

    def forward(self, x, cache=None, capture=None):
        x = x + self.attn(rms_norm(x), cache, capture)
        x = x + self.mlp(rms_norm(x))
        if capture is not None:
            capture.setdefault("resid_rms", []).append(float(x[0].float().pow(2).mean().sqrt()))
        return x


class FusedLMLoss(torch.autograd.Function):
    """Mean cross-entropy of softcapped tied-embedding logits, with the gradient done in the forward.

    For each chunk of tokens: logits z = h W^T (in the autocast dtype), y = c*tanh(z/c), loss from
    log-softmax(y); dL/dz = (softmax(y) - onehot) * (1 - tanh^2) is turned straight into the
    gradients for h and W, then the chunk's logits are thrown away. Compared with recomputing the
    chunk under checkpointing, this skips one vocabulary-sized matrix product and a dozen
    vocabulary-sized elementwise passes per chunk."""

    @staticmethod
    def forward(ctx, h, W, t, cap: float, chunk: int, dt, masked: bool = True):
        # Every step below reads or writes a (tokens x vocabulary) block, so their number is what
        # costs: memory traffic, not arithmetic, is the limit. Each is in place where possible.
        with torch.autocast(h.device.type, enabled=False):
            n = (t != -1).sum().clamp_min(1)
            Wd = W.detach().to(dt)
            Ws = (W.detach() / cap).to(dt)                           # folds the 1/c into the product
            gh = torch.empty_like(h)
            gW = torch.zeros(W.shape, dtype=torch.float32, device=W.device)
            total = torch.zeros((), dtype=torch.float32, device=h.device)
            for i in range(0, h.size(0), chunk):
                hc, tc = h[i:i + chunk].detach().to(dt), t[i:i + chunk]
                tg = tc.clamp_min(0).unsqueeze(1)
                th = (hc @ Ws.T).float().tanh_()                     # tanh(z / c)
                p = torch.softmax(th * cap, -1)                      # softmax of the capped logits
                pt = p.gather(1, tg).squeeze(1)
                if masked:
                    valid = (tc != -1).to(p.dtype)
                    total -= (pt.clamp_min(1e-38).log() * valid).sum()
                    p.scatter_add_(1, tg, -valid.unsqueeze(1))       # p - onehot
                    p.mul_(valid.unsqueeze(1))                       # ignored targets: no gradient
                else:
                    total -= pt.clamp_min(1e-38).log().sum()
                    p.scatter_add_(1, tg, torch.full_like(pt, -1.0).unsqueeze(1))
                p.addcmul_(p, th.square_(), value=-1)                # times dy/dz = 1 - tanh^2
                del th
                g = p.to(dt)
                del p
                gh[i:i + chunk] = (g @ Wd).to(h.dtype)
                gW += g.T @ hc
            ctx.save_for_backward(gh, gW, n)
            return total / n

    @staticmethod
    def backward(ctx, go):
        gh, gW, n = ctx.saved_tensors
        s = go / n
        return gh * s.to(gh.dtype), gW * s, None, None, None, None, None


class Brain(nn.Module):
    def __init__(self, cfg: BrainConfig):
        super().__init__()
        self.cfg = cfg
        self.embed = nn.Embedding(cfg.vocab_size, cfg.d_model)
        nn.init.normal_(self.embed.weight, std=0.02)
        self.rotary = Rotary(cfg.head_dim, cfg.rope_base)
        self.blocks = nn.ModuleList(Block(cfg, self.rotary) for _ in range(cfg.n_layers))

    def hidden(self, idx, caches=None, capture=None):
        x = rms_norm(self.embed(idx))
        for i, b in enumerate(self.blocks):
            x = b(x, caches[i] if caches is not None else None, capture)
        return rms_norm(x)

    def motor_logits(self, h, motor_ids):
        """Logits over the motor words only: Zen's policy is its own language model, restricted to
        the words that move its body."""
        W = self.embed.weight[motor_ids]
        z = F.linear(h, W).float()
        c = self.cfg.logit_softcap
        return c * torch.tanh(z / c)

    def logits(self, h):
        z = F.linear(h, self.embed.weight).float()
        c = self.cfg.logit_softcap
        return c * torch.tanh(z / c)

    def forward(self, idx, targets=None, masked: bool = True):
        """masked=False promises there are no ignored (-1) targets, which saves a pass in training."""
        h = self.hidden(idx)
        if targets is None:
            return self.logits(h)
        return self.chunked_loss(h, targets, masked=masked)

    def _ce(self, h, t):
        return F.cross_entropy(self.logits(h), t, ignore_index=-1, reduction="sum")

    def chunked_loss(self, h, targets, chunk: int = 1024, reduction: str = "mean", masked: bool = True):
        """Cross-entropy without materialising the full (tokens x vocabulary) logits.

        When training, the gradients of the vocabulary projection are worked out in the same pass
        (FusedLMLoss), so nothing vocabulary-sized is kept for, or recomputed in, the backward pass."""
        h = h.reshape(-1, h.size(-1))
        t = targets.reshape(-1)
        if torch.is_grad_enabled() and (h.requires_grad or self.embed.weight.requires_grad) and reduction == "mean":
            dt = torch.get_autocast_dtype(h.device.type) if torch.is_autocast_enabled(h.device.type) else h.dtype
            return FusedLMLoss.apply(h, self.embed.weight, t, self.cfg.logit_softcap, chunk, dt, masked)
        total = h.new_zeros((), dtype=torch.float32)
        for i in range(0, h.size(0), chunk):
            if torch.is_grad_enabled():
                total = total + checkpoint(self._ce, h[i:i + chunk], t[i:i + chunk], use_reentrant=False)
            else:
                total = total + self._ce(h[i:i + chunk], t[i:i + chunk])
        return total / (t != -1).sum().clamp_min(1) if reduction == "mean" else total

    # -- inference ------------------------------------------------------------------
    @torch.no_grad()
    def generate(self, prompt: list[int], max_new: int, temperature: float = 0.8, top_p: float = 0.95,
                 stop: set[int] | None = None, n_real: int | None = None, stop_text=None):
        """Sample up to max_new tokens after prompt. Returns [(id, prob, entropy)].

        Ends before any id in `stop`, or once `stop_text(ids)` is true. On a GPU the tokens stay on
        the device and are only checked every few steps: waiting for the GPU after every token
        costs far more than the occasional extra token (especially on Windows)."""
        T = self.cfg.seq_len
        prompt = prompt[-(T - max_new):] or [0]
        dev = self.embed.weight.device
        on_gpu = dev.type != "cpu"
        caches = [{} for _ in self.blocks]
        h = self.hidden(torch.tensor([prompt], device=dev), caches)
        stop_t = torch.tensor(sorted(stop), device=dev) if stop else None
        toks, probs, ents = [], [], []
        temp = max(temperature, 1e-3)
        for i in range(max_new):
            logits = self.logits(h[0, -1])
            if n_real is not None:
                logits[n_real:] = float("-inf")
            full = F.softmax(logits, -1)
            ents.append(-(full * full.clamp_min(1e-12).log()).sum())
            top_v, top_i = F.softmax(logits / temp, -1).topk(min(64, logits.numel()))
            top_v = top_v * ((top_v.cumsum(0) - top_v) < top_p)
            nxt = top_i[torch.multinomial(top_v / top_v.sum(), 1)]
            toks.append(nxt)
            probs.append(full[nxt])
            # Look at what was generated only now and then (every token on a CPU, where it's free).
            if (not on_gpu or i % 8 == 7 or i == max_new - 1) and self._should_stop(toks, stop_t, stop_text):
                break
            h = self.hidden(nxt.view(1, 1), caches)
        ids = torch.cat(toks).tolist()
        ps = torch.cat(probs).float().tolist()
        es = torch.stack(ents).float().tolist()
        out = []
        for t, p, e in zip(ids, ps, es):
            if stop and t in stop:
                break
            out.append((t, p, e))
            if stop_text and stop_text([x for x, _, _ in out]):
                break
        return out

    @staticmethod
    def _should_stop(toks, stop_t, stop_text) -> bool:
        ids = torch.cat(toks)
        if stop_t is not None and bool(torch.isin(ids, stop_t).any()):
            return True
        return bool(stop_text and stop_text(ids.tolist()))

    @torch.no_grad()
    def capture(self, ids: list[int]) -> dict:
        cap: dict = {}
        self.hidden(torch.tensor([ids], device=self.embed.weight.device), capture=cap)
        return cap

    # -- growth -----------------------------------------------------------------------
    @torch.no_grad()
    def grow(self) -> int:
        blk = Block(self.cfg, self.rotary).to(self.embed.weight.device, self.embed.weight.dtype)
        blocks = list(self.blocks)
        blocks.insert((2 * len(blocks)) // 3, blk)
        self.blocks = nn.ModuleList(blocks)
        self.cfg.n_layers = len(self.blocks)
        return self.cfg.n_layers

    def n_params(self, trunk_only: bool = False) -> int:
        n = sum(p.numel() for p in self.parameters())
        return n - self.embed.weight.numel() if trunk_only else n
