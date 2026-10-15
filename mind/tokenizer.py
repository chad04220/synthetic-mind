"""Tokenizers. The network itself is trained from scratch; only the text<->id mapping is borrowed.

"gpt2" uses tiktoken's GPT-2 BPE (about 3.5x fewer tokens per text than bytes, so far
more language per training step). "bytes" needs no download and lets you watch the
mind learn to spell from raw characters.
"""
from __future__ import annotations

SPECIALS = ["<|endoftext|>", "<|thought|>", "<|user|>", "<|mind|>", "<|teacher|>", "<|world|>"]


def _pad64(n: int) -> int:
    return (n + 63) // 64 * 64


class Tokenizer:
    kind: str
    vocab_size: int          # padded size used by the embedding table
    n_real: int              # ids at or above this are padding and never sampled
    special: dict[str, int]

    def encode(self, text: str) -> list[int]:
        raise NotImplementedError

    def token_bytes(self, tid: int) -> bytes:
        raise NotImplementedError

    def decode(self, ids: list[int]) -> str:
        out = bytearray()
        for t in ids:
            if t in self._special_ids:
                continue
            out += self.token_bytes(t)
        return out.decode("utf-8", errors="replace")

    def token_str(self, tid: int) -> str:
        for name, sid in self.special.items():
            if sid == tid:
                return name
        return self.token_bytes(tid).decode("utf-8", errors="replace")

    @property
    def eot(self) -> int:
        return self.special["<|endoftext|>"]

    def __getitem__(self, name: str) -> int:
        return self.special[name]


class ByteTokenizer(Tokenizer):
    kind = "bytes"

    def __init__(self):
        self.special = {s: 256 + i for i, s in enumerate(SPECIALS)}
        self._special_ids = set(self.special.values())
        self.n_real = 256 + len(SPECIALS)
        self.vocab_size = _pad64(self.n_real)

    def encode(self, text: str) -> list[int]:
        return list(text.encode("utf-8"))

    def token_bytes(self, tid: int) -> bytes:
        return bytes([tid]) if tid < 256 else b""


class GPT2Tokenizer(Tokenizer):
    kind = "gpt2"

    def __init__(self):
        import tiktoken

        base = tiktoken.get_encoding("gpt2")
        n = base.n_vocab  # 50257, last id is <|endoftext|>
        self.special = {"<|endoftext|>": base.eot_token}
        for i, s in enumerate(SPECIALS[1:]):
            self.special[s] = n + i
        self._special_ids = set(self.special.values())
        self._enc = tiktoken.Encoding(
            name="gpt2_mind",
            pat_str=base._pat_str,
            mergeable_ranks=base._mergeable_ranks,
            special_tokens=self.special,
        )
        self.n_real = n + len(SPECIALS) - 1
        self.vocab_size = _pad64(self.n_real)

    def encode(self, text: str) -> list[int]:
        return self._enc.encode_ordinary(text)

    def token_bytes(self, tid: int) -> bytes:
        if tid in self._special_ids or tid >= self._enc.n_vocab:
            return b""
        return self._enc.decode_single_token_bytes(tid)


def make_tokenizer(kind: str) -> Tokenizer:
    if kind == "gpt2":
        try:
            return GPT2Tokenizer()
        except Exception as e:  # tiktoken missing or no network for its first download
            print(f"[tokenizer] GPT-2 BPE unavailable ({e}); falling back to bytes")
            return ByteTokenizer()
    return ByteTokenizer()
