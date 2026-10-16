"""Settings for Ada, the Academy, the World, the Oracle and the schedule that ties them together.

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
    mix_fineweb: float = 0.70
    mix_lessons: float = 0.15        # Oracle lessons and dialogues
    mix_journal: float = 0.10        # Ada's own lived experience
    mix_concepts: float = 0.05       # concept drills generated from the concept graph


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
    thoughts_grounded: bool = False  # sense the world before each thought (else: only past thoughts)
    intent_temperature: float = 0.8
    reply_tokens: int = 60
    reply_temperature: float = 0.8


@dataclass
class OracleConfig:
    # "builtin": a small model the program downloads and runs itself with llama.cpp, on the CPU.
    # "ollama": any model in your local Ollama (url, model and placement below).
    backend: str = "builtin"
    builtin_model: str = "gemma-2-2b"  # see localllm.CATALOG
    url: str = "http://localhost:11434"
    model: str = ""
    enabled: bool = True
    background_teaching: bool = True   # keep the lesson queue topped up while the Academy studies
    lesson_seconds: float = 30.0       # pause between background lessons (Ollama shares the GPU)
    npc_voices: bool = True            # villagers speak with the Oracle's words
    tutor_replies: bool = True         # suggest the reply Ada should have given you
    assess_minutes: float = 10.0
    # Where Ollama runs the Oracle. "cpu" (default): always on the CPU, so the GPU is kept for
    # training. "auto": on the CPU while the Academy studies and on the GPU otherwise. "gpu": always.
    placement: str = "cpu"
    cpu_threads: int = 0             # the Oracle's threads on the CPU; 0 = the physical cores the synth's brain leaves free
    # Every villager has its own voice: a llama.cpp server of its own, on the CPU.
    villager_voices: bool = True
    village_model: str = "qwen2.5-1.5b"
    villager_threads: int = 2
    banter: bool = True                # villagers chat with each other (the synth overhears and learns)
    banter_seconds: float = 75.0
    villager_thought_seconds: float = 60.0   # how often each villager thinks out loud


CONFIG_VERSION = 2   # 2: Ada's brain and the Oracle default to the CPU; the schedule to "together"


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
    "oracle.builtin_model": ("gemma-2-2b", "qwen2.5-1.5b", "qwen2.5-0.5b", "llama-3.2-3b"),
    "oracle.village_model": ("gemma-2-2b", "qwen2.5-1.5b", "qwen2.5-0.5b", "llama-3.2-3b"),
}

LIVE = {
    "schedule.mode": str, "schedule.day_training": str,
    "academy.intensity": str, "academy.publish_minutes": float, "academy.fineweb": bool,
    "academy.mix_fineweb": float, "academy.mix_lessons": float, "academy.mix_journal": float,
    "academy.mix_concepts": float, "academy.muon_lr": float, "academy.adam_lr": float,
    "academy.auto_grow": bool,
    "world.device": str, "world.cpu_threads": int, "oracle.cpu_threads": int, "world.day_minutes": float, "world.night_minutes": float, "world.thought_seconds": float,
    "world.thought_tokens": int, "world.thought_temperature": float, "world.thoughts_grounded": bool,
    "world.intent_temperature": float, "world.reply_tokens": int, "world.reply_temperature": float,
    "oracle.backend": str, "oracle.builtin_model": str, "oracle.villager_voices": bool, "oracle.village_model": str,
    "oracle.villager_threads": int, "oracle.banter": bool, "oracle.banter_seconds": float, "oracle.villager_thought_seconds": float, "oracle.url": str, "oracle.model": str, "oracle.enabled": bool, "oracle.background_teaching": bool,
    "oracle.npc_voices": bool, "oracle.placement": str, "oracle.tutor_replies": bool, "oracle.lesson_seconds": float,
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
    """How the CPU's physical cores are shared: Ada's brain gets half (it thinks in short bursts,
    and one-token-at-a-time generation gains little beyond that), the Oracle gets the rest, so the
    two never fight over the same cores. The Academy, on the GPU, needs almost no CPU."""
    cores = physical_cores()
    world = cfg.world.cpu_threads or max(1, cores // 2)
    oracle = cfg.oracle.cpu_threads or max(1, cores - world)
    return {"cores": cores, "world": world, "oracle": oracle}


def get_live(cfg: AdaConfig) -> dict:
    return {k: getattr(getattr(cfg, k.split(".")[0]), k.split(".")[1]) for k in LIVE}
