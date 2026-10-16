"""Plumbing for the World process: it talks to the Hub through two multiprocessing queues
(commands in, messages out)."""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import queue
import time
from pathlib import Path

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


def append_jsonl(path: Path, obj: dict):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def write_json(path: Path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
