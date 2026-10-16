"""Practice: the inhabitant's model learns from its own judged decisions.

Run by the Hub as a separate process while the model server is stopped (the inhabitant sleeps):

    python -m ada.agent.practice --mind minds/Zen --model qwen2.5-1.5b --oracle oracle --name p3 [--resume p2]

1. **What it learns from** (`examples`): every decision it logged (the exact system prompt and
   observation it saw, and its reply), with every judgement of it (its own, from `reflect`, and
   yours, from the page). A decision becomes an example when it worked and nobody judged it bad;
   one you liked counts twice; one that went wrong becomes an example of the *better* action
   written for it in reflection (its own correction); bad ones without a better action are left
   out. No skill may fill more than a third of the examples, so it can't learn to do one thing.
2. **How** (`train`): the model's original weights (downloaded once from Hugging Face) with a LoRA
   adapter on every attention and MLP projection, trained on the reply tokens only (it learns what
   to answer, not to predict what it sees). Each round starts from the previous adapter, and
   older examples are replayed alongside the new, so it keeps what it learned.
3. **Into the server** (`export_gguf`): the adapter is written as a llama.cpp LoRA GGUF, which
   `llama-server --lora` applies to the quantised model.

Progress goes to stdout as JSON lines: {"state", "detail", "progress", "step", "steps", "loss"}.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from collections import Counter
from pathlib import Path

TARGETS = ("q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj")
GGUF_NAMES = {"q_proj": "attn_q", "k_proj": "attn_k", "v_proj": "attn_v", "o_proj": "attn_output",
              "gate_proj": "ffn_gate", "up_proj": "ffn_up", "down_proj": "ffn_down"}
FAMILY_ARCH = {"qwen2": "qwen2", "llama": "llama", "gemma3": "gemma3"}
TOOLS = ("torch", "transformers", "safetensors", "gguf", "huggingface_hub")


def say(**d) -> None:
    print(json.dumps(d), flush=True)


def missing_tools() -> list[str]:
    import importlib.util

    return [m for m in TOOLS if importlib.util.find_spec(m) is None]


# ---------------------------------------------------------------------------------------- examples
def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def examples(mind: Path, since_t: float = 0.0, max_examples: int = 800, seed: int = 0) -> tuple[list[dict], dict]:
    """The practice set: [{system, prompt, reply, weight, new, skill}], and counts for the page."""
    decisions = read_jsonl(mind / "decisions.jsonl")
    judged: dict[str, dict] = {}
    for j in read_jsonl(mind / "judgements.jsonl"):
        d = judged.setdefault(j["id"], {})
        key = "visitor" if j.get("by") == "visitor" else "self"
        d[key] = {**d.get(key, {}), **{k: v for k, v in j.items() if k in ("value", "better", "why", "correction")}}
    prompts: dict[str, str] = {}
    out, counts = [], Counter()
    seen = set()
    for r in decisions:
        if "outcome" not in r or not r.get("reply") or r["id"] in seen:
            continue
        seen.add(r["id"])
        sys_text = prompts.get(r.get("sys"))
        if sys_text is None:
            p = mind / "prompts" / f"{r.get('sys')}.txt"
            if not p.exists():
                continue
            sys_text = prompts[r["sys"]] = p.read_text(encoding="utf-8")
        j = judged.get(r["id"], {})
        you, me = j.get("visitor", {}), j.get("self", {})
        better = me.get("better")
        ok = r["outcome"].get("ok")
        if you.get("value", 0) < 0 or (me.get("value") or 0) < 0 or not ok:
            if not better:
                counts["left out"] += 1
                continue
            reply = json.dumps({"thought": (me.get("why") or "")[:240], "action": better, "say": None,
                                "note": None, "goal": None}, ensure_ascii=False)
            weight, kind, skill = 1.0, "corrected", better.get("skill")
        else:
            reply, kind, skill = r["reply"], "liked" if you.get("value", 0) > 0 else "worked", (r.get("action") or {}).get("skill")
            weight = 2.0 if kind == "liked" else 1.0
        counts[kind] += 1
        out.append({"system": sys_text, "prompt": r["obs"], "reply": reply, "weight": weight,
                    "new": r.get("t", 0) >= since_t, "skill": skill, "id": r["id"]})
    # no one skill may be more than a third of what it learns from
    rng = random.Random(seed)
    rng.shuffle(out)
    cap = max(8, len(out) // 3)
    per, kept = Counter(), []
    for e in sorted(out, key=lambda e: (not e["new"], -e["weight"])):
        if per[e["skill"]] >= cap:
            counts["capped"] += 1
            continue
        per[e["skill"]] += 1
        kept.append(e)
    new = [e for e in kept if e["new"]]
    old = [e for e in kept if not e["new"]]
    rng.shuffle(old)
    kept = (new + old[:max(0, min(len(old), max_examples - len(new), len(new)))])[:max_examples]  # replay ≤ as many old as new
    rng.shuffle(kept)
    counts.update(examples=len(kept), new=sum(e["new"] for e in kept))
    return kept, dict(counts)


# ---------------------------------------------------------------------------------------- LoRA
def lora_modules(model) -> dict:
    """{hf module name: nn.Linear} for every projection that gets an adapter."""
    import torch.nn as nn

    return {n: m for n, m in model.named_modules()
            if isinstance(m, nn.Linear) and n.rsplit(".", 1)[-1] in TARGETS and ".layers." in n}


def attach_lora(model, r: int, alpha: float, init: dict | None = None) -> dict:
    """Wrap each target projection: y = W x + (alpha / r) · B A x. Returns {name: (A, B)}."""
    import torch
    import torch.nn as nn

    params = {}
    for name, lin in lora_modules(model).items():
        A = nn.Parameter(torch.empty(r, lin.in_features, device=lin.weight.device, dtype=torch.float32))
        B = nn.Parameter(torch.zeros(lin.out_features, r, device=lin.weight.device, dtype=torch.float32))
        nn.init.kaiming_uniform_(A, a=math.sqrt(5))
        if init and name + ".A" in init and init[name + ".A"].shape == A.shape:
            A.data.copy_(init[name + ".A"])
            B.data.copy_(init[name + ".B"])
        scale = alpha / r

        def fwd(x, lin=lin, A=A, B=B, scale=scale, base=lin.forward):
            return base(x) + ((x.to(A.dtype) @ A.t()) @ B.t() * scale).to(x.dtype)

        lin.forward = fwd
        params[name] = (A, B)
    return params


def tokenize(tok, e: dict, max_len: int) -> tuple[list[int], list[int]] | None:
    msgs = [{"role": "system", "content": e["system"]}, {"role": "user", "content": e["prompt"]}]
    head = tok.apply_chat_template(msgs, add_generation_prompt=True, tokenize=True)
    full = tok.apply_chat_template(msgs + [{"role": "assistant", "content": e["reply"]}], tokenize=True)
    if hasattr(head, "input_ids"):
        head, full = head["input_ids"], full["input_ids"]
    head, full = list(head), list(full)
    if full[:len(head)] != head or len(full) <= len(head):
        return None
    if len(full) > max_len:
        return None
    return full, [-100] * len(head) + full[len(head):]


def base_weights(model_key: str, oracle: Path) -> Path:
    """The model's original weights (safetensors), downloaded once."""
    from huggingface_hub import snapshot_download

    from ..localllm import CATALOG

    repo = CATALOG[model_key]["hf"]
    dest = oracle / "base" / model_key
    if not (dest / "config.json").exists() or not list(dest.glob("*.safetensors")):
        say(state="preparing", detail=f"Downloading {repo} (the model's original weights, needed once for practice)",
            progress=0.0)
        snapshot_download(repo, local_dir=str(dest), allow_patterns=["*.json", "*.safetensors", "tokenizer*", "*.model"])
    return dest


def train(exs: list[dict], base: Path, out: Path, resume: Path | None = None, r: int = 16, alpha: float = 32,
          lr: float = 1e-4, epochs: float = 2.0, accum: int = 4, max_len: int = 3072, max_steps: int = 400,
          seed: int = 0, device: str | None = None) -> dict:
    """Train the adapter; saves out.pt (to resume from) and returns {loss, steps, examples}."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    torch.manual_seed(seed)
    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    dtype = torch.bfloat16 if device == "cuda" and torch.cuda.is_bf16_supported() else torch.float32
    say(state="preparing", detail=f"Loading the model on the {device.upper()}", progress=0.0)
    tok = AutoTokenizer.from_pretrained(str(base))
    model = AutoModelForCausalLM.from_pretrained(str(base), torch_dtype=dtype).to(device)
    model.requires_grad_(False)
    model.config.use_cache = False
    model.gradient_checkpointing_enable()
    model.enable_input_require_grads()
    decoder, head = model.get_decoder(), model.get_output_embeddings()
    cap = getattr(model.config, "final_logit_softcapping", None)
    init = torch.load(resume, map_location=device) if resume and resume.exists() else None
    params = attach_lora(model, r, alpha, init)
    pairs = [(tokenize(tok, e, max_len), e["weight"]) for e in exs]
    data = [t for t, _ in pairs if t]
    weights = [w for t, w in pairs if t]
    if not data:
        raise RuntimeError("no usable examples (too long, or the chat template didn't fit)")
    steps = max(1, min(max_steps, int(math.ceil(epochs * len(data) / accum))))
    opt = torch.optim.AdamW([p for ab in params.values() for p in ab], lr=lr, weight_decay=0.0)
    model.train()
    rng = random.Random(seed)
    order: list[int] = []
    losses: list[float] = []
    t0 = time.time()
    for step in range(steps):
        opt.zero_grad(set_to_none=True)
        total = 0.0
        for _ in range(accum):
            if not order:
                order = list(range(len(data)))
                rng.shuffle(order)
            i = order.pop()
            ids, labels = data[i]
            x = torch.tensor([ids], device=device)
            y = torch.tensor(labels[1:], device=device)
            # logits only where the reply is predicted: the whole vocabulary at every prompt position
            # would cost gigabytes (151k words × thousands of tokens) and teach nothing
            at = (y != -100).nonzero().squeeze(1)
            h = decoder(input_ids=x).last_hidden_state[0, at]
            z = head(h).float()
            if cap:
                z = torch.tanh(z / cap) * cap
            loss = torch.nn.functional.cross_entropy(z, y[at]) * weights[i] / accum
            loss.backward()
            total += loss.item()
        lr_now = lr * min(1.0, (step + 1) / 10) * (0.5 * (1 + math.cos(math.pi * step / steps)))
        for g in opt.param_groups:
            g["lr"] = lr_now
        torch.nn.utils.clip_grad_norm_([p for ab in params.values() for p in ab], 1.0)
        opt.step()
        losses.append(total)
        if step % 2 == 0 or step == steps - 1:
            el = time.time() - t0
            say(state="training", detail=f"Practising: step {step + 1} of {steps}", progress=(step + 1) / steps,
                step=step + 1, steps=steps, loss=round(sum(losses[-10:]) / len(losses[-10:]), 4),
                eta=round(el / (step + 1) * (steps - step - 1)))
    out.parent.mkdir(parents=True, exist_ok=True)
    torch.save({f"{n}.A": A.detach().cpu() for n, (A, B) in params.items()} |
               {f"{n}.B": B.detach().cpu() for n, (A, B) in params.items()}, out.with_suffix(".pt"))
    cfg = model.config
    return {"loss": round(sum(losses[-10:]) / len(losses[-10:]), 4), "first_loss": round(losses[0], 4),
            "steps": steps, "examples": len(data), "r": r, "alpha": alpha,
            "n_head": cfg.num_attention_heads, "n_kv": getattr(cfg, "num_key_value_heads", cfg.num_attention_heads)}


def permute(w, n_head: int):
    """llama.cpp's row order for Llama's q and k projections (rotary pairs interleaved)."""
    return w.reshape(n_head, 2, w.shape[0] // n_head // 2, *w.shape[1:]).swapaxes(1, 2).reshape(w.shape)


def export_gguf(pt: Path, out: Path, family: str, alpha: float, n_head: int, n_kv: int) -> Path:
    """Write the adapter as a llama.cpp LoRA GGUF."""
    import gguf
    import numpy as np
    import torch

    w = torch.load(pt, map_location="cpu")
    writer = gguf.GGUFWriter(str(out), FAMILY_ARCH[family])
    writer.add_string("general.type", "adapter")
    writer.add_string("adapter.type", "lora")
    writer.add_float32("adapter.lora.alpha", float(alpha))
    names = sorted({k[:-2] for k in w})
    for n in names:
        parts = n.split(".")
        layer = int(parts[parts.index("layers") + 1])
        proj = parts[-1]
        A = w[n + ".A"].float().numpy()                      # (r, in)
        B = w[n + ".B"].float().numpy()                      # (out, r)
        if family == "llama" and proj in ("q_proj", "k_proj"):
            B = permute(B, n_head if proj == "q_proj" else n_kv)
        base = f"blk.{layer}.{GGUF_NAMES[proj]}.weight"
        writer.add_tensor(base + ".lora_a", np.ascontiguousarray(A.astype(np.float16)))
        writer.add_tensor(base + ".lora_b", np.ascontiguousarray(B.astype(np.float16)))
    writer.write_header_to_file()
    writer.write_kv_data_to_file()
    writer.write_tensors_to_file()
    writer.close()
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--mind", required=True, type=Path)
    ap.add_argument("--model", required=True)
    ap.add_argument("--oracle", required=True, type=Path)
    ap.add_argument("--name", required=True)
    ap.add_argument("--resume", default="")
    ap.add_argument("--since", type=float, default=0.0)
    ap.add_argument("--max-examples", type=int, default=800)
    ap.add_argument("--max-steps", type=int, default=400)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--device", default=None)
    a = ap.parse_args(argv)
    try:
        from ..localllm import CATALOG

        miss = missing_tools()
        if miss:
            raise RuntimeError("missing training tools: " + ", ".join(miss))
        exs, counts = examples(a.mind, a.since, a.max_examples)
        say(state="preparing", detail=f"{counts.get('examples', 0)} examples ({counts.get('new', 0)} new)", counts=counts)
        if len(exs) < 8:
            raise RuntimeError(f"only {len(exs)} usable examples; it needs at least 8")
        base = base_weights(a.model, a.oracle)
        folder = a.mind / "adapters"
        res = train(exs, base, folder / a.name, (folder / f"{a.resume}.pt") if a.resume else None,
                    r=a.rank, alpha=2 * a.rank, lr=a.lr, max_steps=a.max_steps, device=a.device)
        say(state="exporting", detail="Writing the adapter for llama.cpp", progress=1.0)
        family = CATALOG[a.model]["family"]
        export_gguf(folder / f"{a.name}.pt", folder / f"{a.name}.gguf", family, res["alpha"], res["n_head"], res["n_kv"])
        info = {"name": a.name, "model": a.model, "created": time.time(), "resume": a.resume or None, **counts, **res}
        (folder / f"{a.name}.json").write_text(json.dumps(info), encoding="utf-8")
        say(state="done", detail=f"Practised {res['steps']} steps on {res['examples']} examples", progress=1.0, info=info)
        return 0
    except Exception as e:  # noqa: BLE001 - reported to the Hub
        say(state="error", detail=f"{type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
