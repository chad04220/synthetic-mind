"""Everything Zen thinks and says, kept whole: one line per thought or conversation, in two files
under the mind's folder, read back a page at a time (newest first) for the Thoughts and
Conversations tabs."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

FILES = {"thoughts": "thoughts.jsonl", "conversations": "conversations.jsonl"}


class Archive:
    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self.lock = threading.Lock()

    def path(self, kind: str) -> Path:
        return self.folder / FILES[kind]

    def add(self, kind: str, entry: dict):
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        with self.lock, open(self.path(kind), "a", encoding="utf-8") as f:
            f.write(line)

    def _lines_backwards(self, kind: str, chunk: int = 1 << 16):
        """The file's lines, last first, without reading the whole file."""
        p = self.path(kind)
        if not p.exists():
            return
        with open(p, "rb") as f:
            f.seek(0, os.SEEK_END)
            pos, rest = f.tell(), b""
            while pos > 0:
                step = min(chunk, pos)
                pos -= step
                f.seek(pos)
                buf = f.read(step) + rest
                lines = buf.split(b"\n")
                rest = lines.pop(0)
                for ln in reversed(lines):
                    if ln.strip():
                        yield ln
            if rest.strip():
                yield rest

    def page(self, kind: str, before: float | None = None, limit: int = 60, q: str = "", who: str = "") -> dict:
        """Entries older than `before` (a time), newest first, optionally only those mentioning `q`, and
        only those with `who` (conversations) or of kind `who` (thoughts: "thought" or "intent")."""
        limit = max(1, min(500, int(limit or 60)))
        q = (q or "").strip().lower()
        out, more = [], False
        for raw in self._lines_backwards(kind):
            try:
                e = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                continue
            if before is not None and e.get("t", 0) >= before:
                continue
            if who and (e.get("kind", "thought") if kind == "thoughts" else e.get("with")) != who:
                continue
            if q:
                text = (e.get("text", "") + " " + (e.get("reason") or "")) if kind == "thoughts" else \
                    " ".join(l[1] or "" for l in e.get("lines", []))
                if q not in text.lower():
                    continue
            if len(out) == limit:
                more = True
                break
            out.append(e)
        return {"items": out, "more": more}

    def count(self, kind: str) -> int:
        p = self.path(kind)
        if not p.exists():
            return 0
        with open(p, "rb") as f:
            return sum(1 for ln in f if ln.strip())
