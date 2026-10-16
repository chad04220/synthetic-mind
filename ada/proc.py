"""Plumbing shared by the Academy and World processes.

They talk to the Hub through two multiprocessing queues (commands in, messages out) and to each
other only through files in the mind's folder:

    brain/latest.pt      the Academy publishes a brain; the World loads it
    journal.jsonl        the World writes what Ada lived through; the Academy studies it
    curriculum.jsonl     the Hub writes the Oracle's lessons; the Academy studies them
    concepts.json        facts added by the Oracle; both read them
"""
from __future__ import annotations

import json
import math
import multiprocessing as mp
import os
import queue
import time
from pathlib import Path

STAGES = [  # (name, bits per byte above which the brain is still in this stage, what it means)
    ("Static", 99.0, "Random weights: its output is noise."),
    ("Babbling", 2.4, "It knows which letters and fragments are common."),
    ("First words", 1.9, "Real words appear, mostly short and frequent ones."),
    ("Phrases", 1.5, "Words start to fit together in short runs."),
    ("Sentences", 1.25, "Grammatical sentences, loosely on topic."),
    ("Conversational", 1.05, "Coherent text that follows a thread."),
    ("Articulate", 0.0, "Fluent language with real content."),
]


def stage_of(loss: float | None, bpb: float | None, n_vocab: int) -> int:
    if loss is None or bpb is None or loss > 0.85 * math.log(n_vocab):
        return 0
    for i, (_, thr, _) in enumerate(STAGES[1:], start=1):
        if bpb > thr:
            return i
    return len(STAGES) - 1


class Link:
    """A worker's connection to the Hub, its log file and its performance timers."""

    def __init__(self, src: str, inbox: mp.Queue, outbox: mp.Queue, folder: Path):
        from .diag import Perf, setup_logging

        self.src, self.inbox, self.outbox = src, inbox, outbox
        self.logger = setup_logging(src, folder)
        self.perf = Perf()
        self._printed: dict[str, float] = {}
        self._perf_sent = time.time()

    def send(self, type_: str, **data):
        try:
            self.outbox.put_nowait({"src": self.src, "type": type_, "t": time.time(), **data})
        except queue.Full:
            pass  # the Hub is behind; status messages are replaced by the next one anyway

    def reply(self, rid, result=None, error: str | None = None):
        if rid is not None:
            self.send("reply", rid=rid, result=result, error=error)

    def commands(self):
        while True:
            try:
                yield self.inbox.get_nowait()
            except queue.Empty:
                return

    def hub_alive(self) -> bool:
        p = mp.parent_process()
        return p is None or p.is_alive()

    def log(self, msg: str, every: float = 0.0, error: bool = False):
        """Write to logs/<process>.log, and tell the Hub (at most once per `every` seconds)."""
        (self.logger.error if error else self.logger.info)(msg)
        key = msg[:40]
        if time.time() - self._printed.get(key, 0) >= every:
            self._printed[key] = time.time()
            self.send("log", text=msg[-600:], error=error)

    def warn(self, msg: str, every: float = 60.0):
        self.logger.warning(msg)
        key = "w" + msg[:40]
        if time.time() - self._printed.get(key, 0) >= every:
            self._printed[key] = time.time()
            self.send("log", text=msg[-600:], error=False)

    def crash(self, e: BaseException):
        self.logger.critical("crashed", exc_info=e)
        self.send("error", text=f"{type(e).__name__}: {e}"[:500])

    def maybe_send_perf(self, every: float = 5.0):
        if time.time() - self._perf_sent >= every:
            self._perf_sent = time.time()
            self.send("perf", perf=self.perf.take())


class FileTail:
    """Follows a JSON-lines file another process appends to."""

    def __init__(self, path: Path, start_bytes: int = 16 << 20):
        self.path = path
        self.pos = 0
        if path.exists() and path.stat().st_size > start_bytes:
            self.pos = path.stat().st_size - start_bytes   # on start, read only the recent past

    def read(self) -> list[dict]:
        if not self.path.exists():
            return []
        size = self.path.stat().st_size
        if size < self.pos:
            self.pos = 0
        if size == self.pos:
            return []
        out = []
        with open(self.path, "rb") as f:
            f.seek(self.pos)
            data = f.read()
        end = data.rfind(b"\n")
        if end < 0:
            return []
        self.pos += end + 1
        for line in data[:end].split(b"\n"):
            try:
                out.append(json.loads(line))
            except ValueError:
                continue   # a partial first line after seeking, or a torn write
        return out


def append_jsonl(path: Path, obj: dict):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def write_json(path: Path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def pick_device(pref: str = "auto"):
    import torch

    if pref == "cpu":
        return torch.device("cpu")
    if torch.cuda.is_available() and pref in ("auto", "cuda"):
        return torch.device("cuda")
    if pref == "auto" and getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")
