"""Configuration for a synthetic mind: network shape, training, data mix, body and services.

Everything is a plain dataclass so a mind's config round-trips through JSON and is
saved next to its checkpoint.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

# name -> (d_model, n_layers, n_heads, seq_len)
MODEL_PRESETS = {
    "tiny": (256, 4, 4, 256),      # CPU friendly; learns spelling within minutes
    "small": (512, 8, 8, 512),     # good default for an 8 GB GPU (e.g. RTX 3070)
    "medium": (768, 12, 12, 1024),  # GPT-2 small sized trunk, wants 12 GB+
    "large": (1024, 16, 16, 1024),  # 24 GB class GPUs
}


@dataclass
class ModelConfig:
    vocab_size: int = 50304
    d_model: int = 512
    n_layers: int = 8
    n_heads: int = 8
    seq_len: int = 512
    rope_base: float = 10000.0
    logit_softcap: float = 30.0
    n_actions: int = 12

    @property
    def head_dim(self) -> int:
        return self.d_model // self.n_heads

    @property
    def mlp_hidden(self) -> int:
        # SwiGLU keeps parameter count of a 4x MLP with 8/3 x width, rounded for tensor cores.
        return ((self.d_model * 8 // 3) + 63) // 64 * 64


@dataclass
class TrainConfig:
    batch_size: int = 16          # sequences per micro-batch
    grad_accum: int = 1
    optimizer: str = "muon"       # "muon" (Muon for matrices + AdamW elsewhere) or "adamw"
    muon_lr: float = 0.02
    adam_lr: float = 3e-3
    embed_lr: float = 0.05 / 8    # embeddings learn fast with AdamW at a modest rate
    weight_decay: float = 0.0
    warmup_steps: int = 250
    grad_clip: float = 1.0
    compile: bool = False         # torch.compile; needs Triton (Linux / WSL)
    eval_every: int = 250
    rl_every: int = 24            # environment steps per policy update
    rl_coef: float = 0.5
    auto_grow: bool = True        # add a layer when validation loss plateaus
    max_layers: int = 24
    grow_patience_evals: int = 12


@dataclass
class DataConfig:
    fineweb_repo: str = "HuggingFaceFW/fineweb"
    fineweb_config: str = "default"
    fineweb_enabled: bool = True
    # Probability that a training sequence comes from each source.
    mix_fineweb: float = 0.80
    mix_teacher: float = 0.12
    mix_experience: float = 0.08
    pool_size: int = 4000         # texts kept per replay pool
    buffer_docs: int = 2048       # tokenized FineWeb documents kept ready


@dataclass
class MindConfig:
    name: str = "Ada"
    tokenizer: str = "gpt2"       # "gpt2" (tiktoken BPE) or "bytes"
    preset: str = "small"
    model: ModelConfig = field(default_factory=ModelConfig)
    train: TrainConfig = field(default_factory=TrainConfig)
    data: DataConfig = field(default_factory=DataConfig)

    # Inner monologue
    thought_interval: float = 3.0   # seconds between thoughts
    thought_tokens: int = 40
    thought_temperature: float = 0.9
    thought_top_p: float = 0.95
    thoughts_grounded: bool = False  # prefix thoughts with what the body senses
    memory_tokens: int = 192        # how much of its past monologue a thought sees

    # Chat
    reply_tokens: int = 64
    reply_temperature: float = 0.8

    # World / body
    world_enabled: bool = True
    world_tick: float = 0.35

    # Ollama teacher
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = ""
    teacher_enabled: bool = True
    teacher_interval: float = 2.0   # seconds of rest between teacher requests
    teacher_reviews_thoughts: bool = True
    teacher_assesses: bool = True

    autosave_minutes: float = 10.0
    training: bool = True

    def apply_preset(self, preset: str) -> None:
        d, n, h, t = MODEL_PRESETS[preset]
        self.preset = preset
        self.model.d_model, self.model.n_layers, self.model.n_heads, self.model.seq_len = d, n, h, t
        if preset == "tiny":
            self.train.batch_size = 16
        elif preset == "small":
            self.train.batch_size = 16
        else:
            self.train.batch_size = 8
            self.train.grad_accum = 2

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "MindConfig":
        cfg = cls()
        _fill(cfg, d)
        return cfg

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load(cls, path: Path) -> "MindConfig":
        return cls.from_dict(json.loads(path.read_text()))


def _fill(obj, d: dict) -> None:
    """Copy known keys from d onto a dataclass, recursing into nested dataclasses."""
    for f in fields(obj):
        if f.name not in d:
            continue
        cur = getattr(obj, f.name)
        if hasattr(cur, "__dataclass_fields__") and isinstance(d[f.name], dict):
            _fill(cur, d[f.name])
        else:
            setattr(obj, f.name, d[f.name])


# Settings the UI may change on a live mind (dotted paths into MindConfig).
LIVE_SETTINGS = {
    "training": bool,
    "thought_interval": float,
    "thought_tokens": int,
    "thought_temperature": float,
    "thought_top_p": float,
    "thoughts_grounded": bool,
    "memory_tokens": int,
    "reply_tokens": int,
    "reply_temperature": float,
    "world_enabled": bool,
    "world_tick": float,
    "ollama_url": str,
    "ollama_model": str,
    "teacher_enabled": bool,
    "teacher_interval": float,
    "teacher_reviews_thoughts": bool,
    "teacher_assesses": bool,
    "autosave_minutes": float,
    "data.fineweb_enabled": bool,
    "data.mix_fineweb": float,
    "data.mix_teacher": float,
    "data.mix_experience": float,
    "train.muon_lr": float,
    "train.adam_lr": float,
    "train.rl_coef": float,
    "train.auto_grow": bool,
}


def set_live(cfg: MindConfig, key: str, value) -> None:
    if key not in LIVE_SETTINGS:
        raise KeyError(f"{key} cannot be changed while running")
    typ = LIVE_SETTINGS[key]
    if typ is bool and isinstance(value, str):
        value = value.lower() in ("1", "true", "yes", "on")
    value = typ(value)
    target = cfg
    parts = key.split(".")
    for p in parts[:-1]:
        target = getattr(target, p)
    setattr(target, parts[-1], value)
