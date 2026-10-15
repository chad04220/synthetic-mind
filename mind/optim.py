"""Optimizers. Muon (orthogonalised momentum) trains transformer matrices markedly faster per
token than AdamW; embeddings, gains and the body heads stay on AdamW."""
from __future__ import annotations

import torch


def _newton_schulz(G: torch.Tensor, steps: int = 5) -> torch.Tensor:
    a, b, c = 3.4445, -4.7750, 2.0315
    X = G.bfloat16() if G.is_cuda else G.float()
    tall = X.size(-2) > X.size(-1)
    if tall:
        X = X.mT
    X = X / (X.norm(dim=(-2, -1), keepdim=True) + 1e-7)
    for _ in range(steps):
        A = X @ X.mT
        B = b * A + c * (A @ A)
        X = a * X + B @ X
    if tall:
        X = X.mT
    return X


class Muon(torch.optim.Optimizer):
    def __init__(self, params, lr=0.02, momentum=0.95, weight_decay=0.0):
        super().__init__(params, dict(lr=lr, momentum=momentum, weight_decay=weight_decay))

    @torch.no_grad()
    def step(self):
        for group in self.param_groups:
            lr, mom, wd = group["lr"], group["momentum"], group["weight_decay"]
            for p in group["params"]:
                if p.grad is None:
                    continue
                st = self.state[p]
                if "buf" not in st:
                    st["buf"] = torch.zeros_like(p.grad)
                buf = st["buf"]
                buf.lerp_(p.grad, 1 - mom)
                g = p.grad.lerp(buf, mom)  # Nesterov
                u = _newton_schulz(g).to(p.dtype)
                scale = max(1.0, p.size(-2) / p.size(-1)) ** 0.5
                if wd:
                    p.mul_(1 - lr * wd)
                p.add_(u, alpha=-lr * scale)


def build_optimizers(model, tcfg, device_type: str):
    """Return a list of (optimizer, base_lr_key) pairs; base lrs are kept in each group's 'base_lr'."""
    matrices, embed, other = [], [], []
    for name, p in model.named_parameters():
        if name.startswith("embed"):
            embed.append(p)
        elif p.ndim == 2 and name.startswith("blocks"):
            matrices.append(p)
        else:
            other.append(p)
    fused = device_type == "cuda"
    opts = []
    if tcfg.optimizer == "muon":
        opts.append(Muon([dict(params=matrices, base_lr=tcfg.muon_lr, kind="muon")],
                         lr=tcfg.muon_lr, weight_decay=tcfg.weight_decay))
        adam_groups = [
            dict(params=embed, base_lr=tcfg.embed_lr, kind="embed"),
            dict(params=other, base_lr=tcfg.adam_lr, kind="adam"),
        ]
    else:
        adam_groups = [
            dict(params=embed, base_lr=tcfg.embed_lr, kind="embed"),
            dict(params=matrices + other, base_lr=tcfg.adam_lr / 3, kind="adam"),
        ]
    opts.append(torch.optim.AdamW(adam_groups, lr=tcfg.adam_lr, betas=(0.9, 0.95), eps=1e-10,
                                  weight_decay=0.0, fused=fused))
    return opts


def refresh_base_lrs(opts, tcfg) -> None:
    """Pick up learning-rate changes made from the UI."""
    for o in opts:
        for g in o.param_groups:
            if g.get("kind") == "muon":
                g["base_lr"] = tcfg.muon_lr
            elif g.get("kind") == "adam":
                g["base_lr"] = tcfg.adam_lr if tcfg.optimizer == "muon" else tcfg.adam_lr / 3
