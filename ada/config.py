"""Settings for the inhabitant, its mind (the language model and its practice) and its world.

Plain dataclasses saved as minds/<name>/config.json. `LIVE` settings can change while running.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

CONFIG_VERSION = 5   # 5: a voxel world, and a pretrained language model that lives in it and practises


@dataclass
class MindConfig:
    model: str = "qwen2.5-1.5b"      # see localllm.CATALOG
    gpu: bool = True                 # run the model on the GPU when there is one
    cpu_threads: int = 0             # for the model on the CPU; 0 = the physical cores
    context: int = 8192
    temperature: float = 0.7
    idle_seconds: float = 20.0       # it thinks at least this often, even when nothing happens
    radio: bool = True               # it hears the chat box from anywhere (else only within hear_radius)
    hear_radius: float = 24.0
    # Practice: its model learns from its own judged decisions (ada/agent/practice.py)
    practice_min: int = 40           # new decisions needed before it can practise again
    practice_auto: bool = False      # practise whenever it goes to sleep in a bed with enough new experience
    practice_steps: int = 300        # at most this many training steps per round
    practice_lr: float = 1e-4
    practice_rank: int = 16
    adapter: str = ""                # the practice adapter in use ("" = the base model)


@dataclass
class WorldConfig:
    seed: int = 0                    # chosen when the world is created
    day_minutes: float = 20.0        # real minutes in a whole day and night
    peaceful: bool = False           # no hostile creatures
    view_chunks: int = 6             # simulated around the inhabitant and you


@dataclass
class AdaConfig:
    version: int = CONFIG_VERSION
    name: str = "Zen"
    mind: MindConfig = field(default_factory=MindConfig)
    world: WorldConfig = field(default_factory=WorldConfig)

    def to_dict(self) -> dict:
        return asdict(self)

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
        if d.get("version", 1) < 5:
            # An earlier edition's mind (a trained brain in a tile world): v5 keeps only its name and
            # starts it in a new voxel world with a pretrained model; the old files stay where they are.
            d = {"name": d.get("name", "Zen")}
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


def _models() -> tuple:
    from .localllm import CATALOG

    return tuple(CATALOG)


LIVE = {
    "mind.model": str, "mind.gpu": bool, "mind.cpu_threads": int, "mind.temperature": float,
    "mind.idle_seconds": float, "mind.radio": bool, "mind.hear_radius": float,
    "mind.practice_min": int, "mind.practice_auto": bool, "mind.practice_steps": int, "mind.practice_lr": float,
    "mind.practice_rank": int,
    "world.day_minutes": float, "world.peaceful": bool, "world.view_chunks": int,
}
RANGES = {"mind.temperature": (0.0, 2.0), "mind.idle_seconds": (2.0, 600.0), "mind.hear_radius": (4.0, 128.0),
          "mind.practice_min": (8, 100000), "mind.practice_steps": (10, 5000), "mind.practice_lr": (1e-6, 1e-2),
          "mind.practice_rank": (4, 64), "mind.cpu_threads": (0, 256), "world.day_minutes": (1.0, 240.0),
          "world.view_chunks": (2, 12)}


def set_live(cfg: AdaConfig, key: str, value):
    """Validate and apply one live setting. Returns the stored value."""
    if key not in LIVE:
        raise KeyError(f"{key} can't be changed while running")
    typ = LIVE[key]
    if typ is bool and isinstance(value, str):
        value = value.lower() in ("1", "true", "yes", "on")
    value = typ(value)
    if key in RANGES and not RANGES[key][0] <= value <= RANGES[key][1]:
        raise ValueError(f"{key} must be between {RANGES[key][0]} and {RANGES[key][1]}")
    if key == "mind.model" and value not in _models():
        raise ValueError(f"mind.model must be one of: {', '.join(_models())}")
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


def model_threads(cfg: AdaConfig) -> int:
    """CPU threads for the model server: the physical cores less one for the world."""
    return cfg.mind.cpu_threads or max(1, physical_cores() - 1)


def get_live(cfg: AdaConfig) -> dict:
    return {k: getattr(getattr(cfg, k.split(".")[0]), k.split(".")[1]) for k in LIVE}
