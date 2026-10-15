"""The synthetic mind's network: a decoder-only transformer trained from random weights.

Modern, sample-efficient choices: RMSNorm, rotary positions, QK-norm, SwiGLU, tied
embeddings, tanh logit soft-capping and zero-initialised residual outputs. The same
trunk also drives the body: a policy head and a value head read the hidden state at
the end of a textual description of what the body senses.

Zero-initialised residual outputs make every block start as the identity, which is
what lets ``grow()`` add depth to a trained mind without disturbing what it knows.
"""
from __future__ import annotations

import math

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.checkpoint import checkpoint

from .config import ModelConfig


def rms_norm(x: torch.Tensor) -> torch.Tensor:
    return F.rms_norm(x, (x.size(-1),))


class Rotary(nn.Module):
    def __init__(self, head_dim: int, base: float):
        super().__init__()
        inv = 1.0 / (base ** (torch.arange(0, head_dim, 2, dtype=torch.float32) / head_dim))
        self.register_buffer("inv_freq", inv, persistent=False)
        self._cache: tuple[int, torch.device, torch.Tensor, torch.Tensor] | None = None

    def forward(self, x: torch.Tensor) -> torch.Tensor:  # x: B,H,T,D
        T = x.size(2)
        if self._cache is None or self._cache[0] < T or self._cache[1] != x.device:
            t = torch.arange(max(T, 64), device=x.device, dtype=torch.float32)
            f = torch.outer(t, self.inv_freq.to(x.device))
            self._cache = (f.size(0), x.device, f.cos(), f.sin())
        cos = self._cache[2][:T].to(x.dtype)
        sin = self._cache[3][:T].to(x.dtype)
        x1, x2 = x.chunk(2, dim=-1)
        return torch.cat((x1 * cos - x2 * sin, x1 * sin + x2 * cos), dim=-1)


class Attention(nn.Module):
    def __init__(self, cfg: ModelConfig, rotary: Rotary):
        super().__init__()
        self.n_heads = cfg.n_heads
        self.qkv = nn.Linear(cfg.d_model, 3 * cfg.d_model, bias=False)
        self.proj = nn.Linear(cfg.d_model, cfg.d_model, bias=False)
        nn.init.zeros_(self.proj.weight)
        self.rotary = rotary

    def forward(self, x: torch.Tensor, capture: dict | None = None) -> torch.Tensor:
        B, T, C = x.shape
        q, k, v = self.qkv(x).view(B, T, 3, self.n_heads, C // self.n_heads).permute(2, 0, 3, 1, 4)
        q, k = rms_norm(q), rms_norm(k)
        q, k = self.rotary(q), self.rotary(k)
        if capture is not None:
            # Explicit attention so the UI can show where the mind is "looking".
            att = (q @ k.transpose(-2, -1)) / math.sqrt(q.size(-1))
            mask = torch.ones(T, T, dtype=torch.bool, device=x.device).tril()
            att = att.masked_fill(~mask, float("-inf")).softmax(-1)
            y = att @ v
            capture.setdefault("attn", []).append(att[0].float().mean(0).cpu())
            ent = -(att[0].float().clamp_min(1e-9).log() * att[0].float()).sum(-1).mean()
            capture.setdefault("attn_entropy", []).append(float(ent))
        else:
            y = F.scaled_dot_product_attention(q, k, v, is_causal=True)
        return self.proj(y.transpose(1, 2).reshape(B, T, C))


class SwiGLU(nn.Module):
    def __init__(self, cfg: ModelConfig):
        super().__init__()
        self.gate_up = nn.Linear(cfg.d_model, 2 * cfg.mlp_hidden, bias=False)
        self.down = nn.Linear(cfg.mlp_hidden, cfg.d_model, bias=False)
        nn.init.zeros_(self.down.weight)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        g, u = self.gate_up(x).chunk(2, dim=-1)
        return self.down(F.silu(g) * u)


class Block(nn.Module):
    def __init__(self, cfg: ModelConfig, rotary: Rotary):
        super().__init__()
        self.attn = Attention(cfg, rotary)
        self.mlp = SwiGLU(cfg)

    def forward(self, x: torch.Tensor, capture: dict | None = None) -> torch.Tensor:
        x = x + self.attn(rms_norm(x), capture)
        x = x + self.mlp(rms_norm(x))
        if capture is not None:
            capture.setdefault("resid_rms", []).append(float(x[0].float().pow(2).mean().sqrt()))
        return x


class MindNet(nn.Module):
    def __init__(self, cfg: ModelConfig):
        super().__init__()
        self.cfg = cfg
        self.embed = nn.Embedding(cfg.vocab_size, cfg.d_model)
        nn.init.normal_(self.embed.weight, std=0.02)
        self.rotary = Rotary(cfg.head_dim, cfg.rope_base)
        self.blocks = nn.ModuleList(Block(cfg, self.rotary) for _ in range(cfg.n_layers))
        # Body: what to do next, and how good the current situation is.
        self.policy = nn.Linear(cfg.d_model, cfg.n_actions)
        self.value = nn.Linear(cfg.d_model, 1)
        nn.init.zeros_(self.policy.weight)
        nn.init.zeros_(self.policy.bias)
        nn.init.zeros_(self.value.weight)
        nn.init.zeros_(self.value.bias)

    # -- core ---------------------------------------------------------------
    def hidden(self, idx: torch.Tensor, capture: dict | None = None) -> torch.Tensor:
        x = rms_norm(self.embed(idx))
        for b in self.blocks:
            x = b(x, capture)
        return rms_norm(x)

    def logits(self, h: torch.Tensor) -> torch.Tensor:
        z = F.linear(h, self.embed.weight).float()
        c = self.cfg.logit_softcap
        return c * torch.tanh(z / c)

    def forward(self, idx: torch.Tensor, targets: torch.Tensor | None = None):
        h = self.hidden(idx)
        if targets is None:
            return self.logits(h)
        return None, self.chunked_loss(h, targets)

    def _ce_chunk(self, h: torch.Tensor, t: torch.Tensor) -> torch.Tensor:
        return F.cross_entropy(self.logits(h), t, ignore_index=-1, reduction="sum")

    def chunked_loss(self, h: torch.Tensor, targets: torch.Tensor, chunk: int = 2048) -> torch.Tensor:
        """Cross-entropy without ever holding the full (tokens x vocab) logits: with a 50k
        vocabulary those would be the largest tensor in training by far."""
        h = h.reshape(-1, h.size(-1))
        t = targets.reshape(-1)
        total = h.new_zeros((), dtype=torch.float32)
        for i in range(0, h.size(0), chunk):
            if torch.is_grad_enabled():
                total = total + checkpoint(self._ce_chunk, h[i:i + chunk], t[i:i + chunk], use_reentrant=False)
            else:
                total = total + self._ce_chunk(h[i:i + chunk], t[i:i + chunk])
        return total / (t != -1).sum().clamp_min(1)

    def act(self, idx: torch.Tensor, lengths: torch.Tensor):
        """Policy logits and value from the hidden state at each sequence's last real token."""
        h = self.hidden(idx)
        last = h[torch.arange(idx.size(0), device=idx.device), lengths - 1].float()
        return F.linear(last, self.policy.weight.float(), self.policy.bias.float()), \
            F.linear(last, self.value.weight.float(), self.value.bias.float()).squeeze(-1)

    # -- growth --------------------------------------------------------------
    @torch.no_grad()
    def grow(self) -> int:
        """Insert a fresh identity block in the upper middle of the stack. Returns new depth."""
        blk = Block(self.cfg, self.rotary).to(self.embed.weight.device, self.embed.weight.dtype)
        at = (2 * len(self.blocks)) // 3
        blocks = list(self.blocks)
        blocks.insert(at, blk)
        self.blocks = nn.ModuleList(blocks)
        self.cfg.n_layers = len(self.blocks)
        return self.cfg.n_layers

    def n_params(self, trunk_only: bool = False) -> int:
        n = sum(p.numel() for p in self.parameters())
        if trunk_only:
            n -= self.embed.weight.numel()
        return n
