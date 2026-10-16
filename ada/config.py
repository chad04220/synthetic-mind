"""Settings for Ada, the Academy, the World, the Oracle and the schedule that ties them together.

Plain dataclasses saved as minds/<name>/config.json. Only `LIVE` settings can change while
running; the rest (network shape, tokenizer) are fixed when a mind is created.
"""
from __future__ import annotations

import json
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
    batch_size: int = 16
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
    device: str = "auto"             # where Ada's brain runs while she lives: auto | cuda | cpu
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
    url: str = "http://localhost:11434"
    model: str = ""
    enabled: bool = True
    background_teaching: bool = True   # keep the lesson queue topped up while the Academy studies
    lesson_seconds: float = 30.0       # pause between background lessons (Ollama shares the GPU)
    npc_voices: bool = True            # villagers speak with the Oracle's words
    tutor_replies: bool = True         # suggest the reply Ada should have given you
    assess_minutes: float = 10.0


@dataclass
class ScheduleConfig:
    # day_night: Ada lives by day and studies while she sleeps at night (never both at once).
    # together:  both always run; the Academy trains gently so the World stays smooth.
    # academy:   study only, the World is paused.   world: live only, no training.
    mode: str = "day_night"
    day_training: str = "pause"        # with day_night: pause | gentle training while she's awake


@dataclass
class AdaConfig:
    name: str = "Ada"
    tokenizer: str = "gpt2"
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
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "AdaConfig":
        cfg = cls()
        _fill(cfg, d)
        return cfg

    def save(self, path: Path) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2))
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> "AdaConfig":
        return cls.from_dict(json.loads(path.read_text()))


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
}

LIVE = {
    "schedule.mode": str, "schedule.day_training": str,
    "academy.intensity": str, "academy.publish_minutes": float, "academy.fineweb": bool,
    "academy.mix_fineweb": float, "academy.mix_lessons": float, "academy.mix_journal": float,
    "academy.mix_concepts": float, "academy.muon_lr": float, "academy.adam_lr": float,
    "academy.auto_grow": bool,
    "world.day_minutes": float, "world.night_minutes": float, "world.thought_seconds": float,
    "world.thought_tokens": int, "world.thought_temperature": float, "world.thoughts_grounded": bool,
    "world.intent_temperature": float, "world.reply_tokens": int, "world.reply_temperature": float,
    "oracle.url": str, "oracle.model": str, "oracle.enabled": bool, "oracle.background_teaching": bool,
    "oracle.npc_voices": bool, "oracle.tutor_replies": bool, "oracle.lesson_seconds": float,
}


def set_live(cfg: AdaConfig, key: str, value):
    """Validate and apply one live setting. Returns the stored value."""
    if key not in LIVE:
        raise KeyError(f"{key} can't be changed while running")
    typ = LIVE[key]
    if typ is bool and isinstance(value, str):
        value = value.lower() in ("1", "true", "yes", "on")
    value = typ(value)
    if key in CHOICES and value not in CHOICES[key]:
        raise ValueError(f"{key} must be one of: {', '.join(CHOICES[key])}")
    section, name = key.split(".")
    setattr(getattr(cfg, section), name, value)
    return value


def get_live(cfg: AdaConfig) -> dict:
    return {k: getattr(getattr(cfg, k.split(".")[0]), k.split(".")[1]) for k in LIVE}
