"""FineWeb, streamed: random 1000-document parquet row groups fetched by HTTP range requests from
random Common Crawl dumps, tokenized on a background thread into a ready buffer. Memory stays flat
(a whole FineWeb file is about 2 GB) and the stream is well shuffled across all of the crawl."""
from __future__ import annotations

import random
import re
import threading
import time
from collections import Counter, deque

from .tokenizer import Tokenizer

_WORD = re.compile(r"[a-z]+(?:'[a-z]+)?")


class FineWebStream:
    def __init__(self, tok: Tokenizer, repo: str, config: str, buffer_docs: int, seed: int | None = None):
        self.tok = tok
        self.repo, self.config = repo, config
        self.docs: deque[list[int]] = deque(maxlen=buffer_docs)
        self.raw_texts: deque[str] = deque(maxlen=64)   # for books in the world
        self.lock = threading.Lock()
        self.words: Counter[str] = Counter()
        self.docs_seen = 0
        self.bytes_seen = 0
        self.tokens_seen = 0
        self.status = "idle"
        self.error = ""
        self.source = ""
        self.enabled = True
        self.seed = seed if seed is not None else random.randrange(1 << 30)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="fineweb", daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    @property
    def bytes_per_token(self) -> float:
        return self.bytes_seen / self.tokens_seen if self.tokens_seen else 1.0

    def ready(self) -> bool:
        return len(self.docs) > 8

    def _base_path(self) -> str:
        c = self.config
        if c in ("", "default"):
            return "data"                       # every Common Crawl dump
        if c.startswith("sample-"):
            return "sample/" + c[len("sample-"):]  # e.g. sample-10BT -> sample/10BT
        return "data/" + c                      # a single dump, e.g. CC-MAIN-2024-10

    def _files(self, api, rng: random.Random) -> list[str]:
        """Parquet files of one randomly chosen dump (or of the whole config if it is flat)."""
        base = self._base_path()
        if base not in self._tree:
            self._tree[base] = list(api.list_repo_tree(self.repo, path_in_repo=base, repo_type="dataset"))
        entries = self._tree[base]
        files = [e.path for e in entries if e.path.endswith(".parquet")]
        if files:
            return files
        sub = rng.choice([e.path for e in entries])
        if sub not in self._tree:
            self._tree[sub] = list(api.list_repo_tree(self.repo, path_in_repo=sub, repo_type="dataset"))
        return [e.path for e in self._tree[sub] if e.path.endswith(".parquet")]

    def _run(self):
        """Stream random row groups (1000 documents each) from random FineWeb parquet files.

        Reading row groups over HTTP range requests keeps memory flat (a whole FineWeb file is
        about 2 GB) and gives a well-shuffled stream across all of Common Crawl's dumps."""
        backoff = 2.0
        rng = random.Random(self.seed)
        self._tree: dict[str, list] = {}
        while not self._stop.is_set():
            if not self.enabled:
                self.status = "paused"
                time.sleep(0.5)
                continue
            try:
                import pyarrow.parquet as pq
                from huggingface_hub import HfApi, HfFileSystem

                api, fs = HfApi(), HfFileSystem()
                if not self.docs:
                    self.status = "connecting"            # (with documents buffered, it stays "streaming")
                path = rng.choice(self._files(api, rng))
                with fs.open(f"datasets/{self.repo}/{path}", block_size=4 << 20) as f:
                    pf = pq.ParquetFile(f)
                    groups = rng.sample(range(pf.metadata.num_row_groups), min(3, pf.metadata.num_row_groups))
                    for g in groups:
                        texts = pf.read_row_group(g, columns=["text"]).column(0).to_pylist()
                        rng.shuffle(texts)
                        self.status = "streaming"
                        self.source = path
                        self.error = ""
                        backoff = 2.0
                        for text in texts:
                            if self._stop.is_set():
                                return
                            while (len(self.docs) >= self.docs.maxlen - 1 or not self.enabled) \
                                    and not self._stop.is_set():
                                time.sleep(0.05)
                            self._add(text)
            except Exception as e:  # network drop, missing package, rate limit...
                self.status = "retrying"
                self.error = f"{type(e).__name__}: {e}"[:300]
                print(f"[fineweb] {self.error}; retrying in {backoff:.0f}s")
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 120)

    def _add(self, text: str):
        if not text or len(text) < 64:
            return
        ids = self.tok.encode(text)
        ids.append(self.tok.eot)
        with self.lock:
            self.docs.append(ids)
            self.raw_texts.append(text)
            self.docs_seen += 1
            self.bytes_seen += len(text.encode("utf-8"))
            self.tokens_seen += len(ids)
            if self.docs_seen % 4 == 0:
                self.words.update(_WORD.findall(text.lower()))
                if len(self.words) > 400_000:   # prune rarely: it holds Python's lock for a moment
                    self.words = Counter(dict(self.words.most_common(200_000)))

    def take(self, n: int) -> list[int] | None:
        """Pack whole documents (and the start of the next one) into n tokens."""
        out: list[int] = []
        with self.lock:
            if not self.docs:
                return None
            while len(out) < n and self.docs:
                d = self.docs.popleft()
                need = n - len(out)
                out.extend(d[:need])
                if len(d) > need + 32:
                    self.docs.appendleft(d[need:])  # keep the rest for the next row
        return out if len(out) == n else None

    def random_text(self) -> str | None:
        with self.lock:
            return random.choice(self.raw_texts) if self.raw_texts else None

    def known_word(self, w: str) -> bool:
        return self.words.get(w, 0) >= 8

    def learn_words(self, text: str, weight: int = 3):
        with self.lock:
            for w in _WORD.findall(text.lower()):
                self.words[w] += weight
