"""Optimizers: Muon (orthogonalised momentum) for the transformer's matrices, which learns markedly
faster per token than AdamW, and AdamW for embeddings and gains."""
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
    return X.mT if tall else X


class Muon(torch.optim.Optimizer):
    def __init__(self, params, lr=0.02, momentum=0.95):
        super().__init__(params, dict(lr=lr, momentum=momentum))

    @torch.no_grad()
    def step(self):
        for group in self.param_groups:
            lr, mom = group["lr"], group["momentum"]
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
                p.add_(u, alpha=-lr * max(1.0, p.size(-2) / p.size(-1)) ** 0.5)


def build_optimizers(model, acfg, device_type: str) -> list[torch.optim.Optimizer]:
    """Each param group carries its own 'base_lr' and 'kind' so the schedule and live settings can
    rescale learning rates without rebuilding the optimizers."""
    matrices, embed, other = [], [], []
    for name, p in model.named_parameters():
        if name.startswith("embed"):
            embed.append(p)
        elif p.ndim == 2 and name.startswith("blocks"):
            matrices.append(p)
        else:
            other.append(p)
    muon = Muon([dict(params=matrices, base_lr=acfg.muon_lr, kind="muon")], lr=acfg.muon_lr)
    adam = torch.optim.AdamW(
        [dict(params=embed, base_lr=acfg.embed_lr, kind="embed"),
         dict(params=other, base_lr=acfg.adam_lr, kind="adam")],
        lr=acfg.adam_lr, betas=(0.9, 0.95), eps=1e-10, weight_decay=0.0, fused=device_type == "cuda")
    return [muon, adam]


def set_lrs(opts, acfg, factor: float) -> None:
    for o in opts:
        for g in o.param_groups:
            base = {"muon": acfg.muon_lr, "adam": acfg.adam_lr}.get(g["kind"], g["base_lr"])
            g["lr"] = base * factor
