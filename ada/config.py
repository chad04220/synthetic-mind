"""Settings for the synth, the Academy, the World, the Sprite of All Knowing and the schedule that ties them together.

Plain dataclasses saved as minds/<name>/config.json. Only `LIVE` settings can change while
running; the rest (network shape, tokenizer) are fixed when a mind is created.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

# name -> (width, layers, heads, context)
PRESETS = {
    "tiny": (256, 4, 4, 256),
    "small": (512, 8, 8, 512),       # default on an 8 GB GPU (RTX 3070 class)
    "medium": (768, 12, 12, 1024),
    "large": (1024, 16, 16, 1024),
}


@dataclass
class BrainConfig:
    vocab_size: int = 50304
    d_model: int = 512
    n_layers: int = 8
    n_heads: int = 8
    seq_len: int = 512
    rope_base: float = 10000.0
    logit_softcap: float = 30.0

    @property
    def head_dim(self) -> int:
        return self.d_model // self.n_heads

    @property
    def mlp_hidden(self) -> int:
        return ((self.d_model * 8 // 3) + 63) // 64 * 64


@dataclass
class AcademyConfig:
    batch_size: int = 16             # the smallest batch; on a GPU it grows to fill free memory
    auto_batch: bool = True
    max_batch_size: int = 128
    grad_accum: int = 1
    muon_lr: float = 0.02
    adam_lr: float = 3e-3
    embed_lr: float = 0.006
    warmup_steps: int = 250
    grad_clip: float = 1.0
    compile: bool = False
    intensity: str = "full"          # full | balanced | gentle: how much GPU time it leaves free
    eval_every: int = 250
    publish_minutes: float = 5.0     # how often a fresh brain is handed to the World
    auto_grow: bool = True
    max_layers: int = 24
    grow_patience_evals: int = 12
    fineweb_repo: str = "HuggingFaceFW/fineweb"
    fineweb_config: str = "default"
    fineweb: bool = True
    # Share of each batch from each source (renormalised over the sources that have data).
    mix_fineweb: float = 0.60
    mix_lessons: float = 0.0         # lessons written into curriculum.jsonl (none by default in v4)
    mix_journal: float = 0.10        # what it said and was told: talks with you, the Sprite's answers, books
    mix_concepts: float = 0.05       # concept drills generated from the concept graph
    # Zen's own experience (experience.jsonl): every training step also learns from some of it, with
    # the language-model loss (what follows what it does) and the policy-gradient loss on its actions.
    mix_experience: float = 0.25
    pg_coef: float = 1.0             # weight of the policy-gradient loss
    entropy_coef: float = 0.01       # keeps it curious: a bonus for not being too sure of one action


@dataclass
class WorldConfig:
    # Where Ada's brain runs while she lives: cpu | cuda | auto. The CPU by default, so the GPU is
    # kept entirely for the Academy's training.
    device: str = "cpu"
    cpu_threads: int = 0             # threads for her brain on the CPU; 0 = half the physical cores
    tick: float = 0.25               # seconds per world step
    day_minutes: float = 10.0        # real minutes of daylight: Ada is awake
    night_minutes: float = 20.0      # real minutes of night: Ada sleeps and the Academy studies
    thought_seconds: float = 6.0
    thought_tokens: int = 40
    thought_temperature: float = 0.9
    thoughts_grounded: bool = True   # (v4: thoughts always follow its lived stream)
    intent_temperature: float = 0.8  # (unused since v4)
    motor_seconds: float = 0.5       # one motor action every this many seconds while awake
    motor_temperature: float = 1.0   # how adventurous its choice of action is (its brain's own odds at 1.0)
    seed: int = 0                    # the world's seed (0: chosen when the mind is created)
    reply_tokens: int = 60
    reply_temperature: float = 0.8


@dataclass
class OracleConfig:
    """The Sprite of All Knowing: the one language model, which answers when Zen asks (the section
    keeps its old name, 'oracle')."""
    # "builtin": a small model the program downloads and runs itself with llama.cpp, on the CPU.
    # "ollama": any model in your local Ollama (url, model and placement below).
    backend: str = "builtin"
    builtin_model: str = "qwen2.5-omni-3b"  # see localllm.CATALOG (this one sees and hears: it judges Zen's art)
    url: str = "http://localhost:11434"
    model: str = ""
    enabled: bool = True
    # Where Ollama runs the model. "cpu" (default): always on the CPU, so the GPU is kept for
    # training. "auto": on the CPU while the Academy studies and on the GPU otherwise. "gpu": always.
    placement: str = "cpu"
    cpu_threads: int = 0             # the Sprite's threads on the CPU; 0 = the physical cores Zen's brain leaves free


CONFIG_VERSION = 4   # 2: the brain and the Oracle default to the CPU, the schedule to "together". 3: the companion.
#                      4: Zen alone, in an endless world, every deed its own; the Sprite answers its questions


@dataclass
class ScheduleConfig:
    # day_night: Ada lives by day and studies while she sleeps at night (never both at once).
    # together:  both always run (default). With her brain on the CPU the Academy keeps the whole
    #            GPU; with her brain on the GPU it trains gently so the World stays smooth.
    # academy:   study only, the World is paused.   world: live only, no training.
    mode: str = "together"
    day_training: str = "pause"        # with day_night: pause | gentle training while she's awake


# The padded vocabulary of each tokenizer (ada/tokenizer.py), known here without loading it.
TOKENIZER_VOCAB = {"fineweb32k": 32768, "gpt2": 50304, "bytes": 320}


@dataclass
class AdaConfig:
    version: int = CONFIG_VERSION
    name: str = "Zen"
    companion: str = "the Sprite"     # who answers Zen's questions
    tokenizer: str = "fineweb32k"
    preset: str = "small"
    brain: BrainConfig = field(default_factory=BrainConfig)
    academy: AcademyConfig = field(default_factory=AcademyConfig)
    world: WorldConfig = field(default_factory=WorldConfig)
    oracle: OracleConfig = field(default_factory=OracleConfig)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)

    def apply_preset(self, preset: str) -> None:
        d, n, h, t = PRESETS[preset]
        self.preset = preset
        b = self.brain
        b.d_model, b.n_layers, b.n_heads, b.seq_len = d, n, h, t
        if preset in ("medium", "large"):
            self.academy.batch_size, self.academy.grad_accum = 8, 2

    def to_dict(self) -> dict:
        d = asdict(self)
        # The embedding table is sized by the tokenizer (the Academy sets it when it builds the
        # brain); show that size rather than the default, which only fits "gpt2".
        d["brain"]["vocab_size"] = TOKENIZER_VOCAB.get(self.tokenizer, d["brain"]["vocab_size"])
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "AdaConfig":
        cfg = cls()
        _fill(cfg, d)
        return cfg

    def save(self, path: Path) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> "AdaConfig":
        d = json.loads(path.read_text(encoding="utf-8"))
        if d.get("version", 1) < 2:
            # Minds saved before version 2 kept the old defaults ("auto"); move them to the new
            # ones (the CPU), leaving any setting that was changed by hand alone.
            for section, key, was, now in (("world", "device", "auto", "cpu"), ("oracle", "placement", "auto", "cpu"),
                                           ("schedule", "mode", "day_night", "together")):
                if d.get(section, {}).get(key) == was:
                    d[section][key] = now
        if d.get("version", 1) < 3 and d.get("oracle", {}).get("lesson_seconds") == 30.0:
            d["oracle"]["lesson_seconds"] = 120.0     # one model now lives Wren's life too
        if d.get("version", 1) < 4:
            d["companion"] = "the Sprite"
            ac = d.setdefault("academy", {})
            ac["mix_lessons"] = 0.0               # no one writes lessons any more
            if d.get("oracle", {}).get("builtin_model", "gemma-2-2b") == "gemma-2-2b":
                d.setdefault("oracle", {})["builtin_model"] = "qwen2.5-omni-3b"   # the Sprite sees and hears
            if ac.get("mix_fineweb") == 0.70:
                ac["mix_fineweb"] = 0.60
        d["version"] = CONFIG_VERSION
        return cls.from_dict(d)


def _fill(obj, d: dict) -> None:
    for f in fields(obj):
        if f.name in d:
            cur = getattr(obj, f.name)
            if hasattr(cur, "__dataclass_fields__") and isinstance(d[f.name], dict):
                _fill(cur, d[f.name])
            else:
                setattr(obj, f.name, d[f.name])


CHOICES = {
    "schedule.mode": ("day_night", "together", "academy", "world"),
    "schedule.day_training": ("pause", "gentle"),
    "academy.intensity": ("full", "balanced", "gentle"),
    "world.device": ("cpu", "cuda", "auto"),
    "oracle.placement": ("cpu", "auto", "gpu"),
    "oracle.backend": ("builtin", "ollama"),
    "oracle.builtin_model": ("qwen2.5-omni-3b", "gemma-2-2b", "qwen2.5-1.5b", "qwen2.5-0.5b", "llama-3.2-3b"),
}

LIVE = {
    "schedule.mode": str, "schedule.day_training": str,
    "academy.intensity": str, "academy.publish_minutes": float, "academy.fineweb": bool,
    "academy.mix_fineweb": float, "academy.mix_lessons": float, "academy.mix_journal": float,
    "academy.mix_concepts": float, "academy.mix_experience": float, "academy.entropy_coef": float,
    "academy.muon_lr": float, "academy.adam_lr": float,
    "academy.auto_grow": bool,
    "world.device": str, "world.cpu_threads": int, "oracle.cpu_threads": int, "world.day_minutes": float, "world.night_minutes": float, "world.thought_seconds": float,
    "world.thought_tokens": int, "world.thought_temperature": float, "world.thoughts_grounded": bool,
    "world.reply_tokens": int, "world.reply_temperature": float, "world.motor_seconds": float,
    "world.motor_temperature": float,
    "oracle.backend": str, "oracle.builtin_model": str, "oracle.url": str, "oracle.model": str,
    "oracle.enabled": bool, "oracle.placement": str,
}


def set_live(cfg: AdaConfig, key: str, value):
    """Validate and apply one live setting. Returns the stored value."""
    if key not in LIVE:
        raise KeyError(f"{key} can't be changed while running")
    typ = LIVE[key]
    if typ is bool and isinstance(value, str):
        value = value.lower() in ("1", "true", "yes", "on")
    value = typ(value)
    if key.endswith("cpu_threads") and not 0 <= value <= 256:
        raise ValueError(f"{key} must be between 0 (automatic) and 256")
    if key in CHOICES and value not in CHOICES[key]:
        raise ValueError(f"{key} must be one of: {', '.join(CHOICES[key])}")
    section, name = key.split(".")
    setattr(getattr(cfg, section), name, value)
    return value


def physical_cores() -> int:
    try:
        import psutil

        n = psutil.cpu_count(logical=False)
    except Exception:
        n = None
    return n or max(1, (os.cpu_count() or 2) // 2)


def cpu_threads(cfg: AdaConfig) -> dict:
    """How the CPU's physical cores are shared. Zen's brain runs all the time now (it chooses every
    action), so it gets half the cores (at most 4). The Sprite's model, used only when Zen asks, gets
    the rest. The Academy, on the GPU, needs almost no CPU."""
    cores = physical_cores()
    world = cfg.world.cpu_threads or max(1, min(4, cores // 2))
    oracle = cfg.oracle.cpu_threads or max(1, cores - world)
    return {"cores": cores, "world": world, "oracle": oracle}


def get_live(cfg: AdaConfig) -> dict:
    return {k: getattr(getattr(cfg, k.split(".")[0]), k.split(".")[1]) for k in LIVE}
