"""Tokenizers. The network is trained from scratch; only the text<->id mapping is borrowed.

"fineweb32k" (new minds) is a 32,768-token byte-level BPE trained on FineWeb itself
(tools/train_tokenizer.py, shipped as ada/data/fineweb32k.tiktoken). It writes any text, its
pieces fit the web text the Academy studies, and at this size half of a small brain is no
longer a lookup table of rare word pieces. "gpt2" uses tiktoken's GPT-2 BPE (50,257 tokens; the
minds made before it keep it). "bytes" needs no download and lets you watch the mind learn to
spell from raw characters.
"""
from __future__ import annotations

import base64
from pathlib import Path

# Role tokens mark who is speaking or what kind of text follows: <|world|> what the synth perceives
# and what happens, <|thought|> its inner voice, <|mind|> what it says, <|user|> you, <|oracle|> the
# Sprite of All Knowing, and <|act|> the motor word its brain chooses (see motor.py). <|intent|> is
# no longer used. <|act|> took the place (and the id) of v3's <|npc|>, which still names it.
SPECIALS = ["<|endoftext|>", "<|thought|>", "<|user|>", "<|mind|>", "<|oracle|>", "<|world|>",
            "<|intent|>", "<|act|>"]


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
        self.special["<|npc|>"] = self.special["<|act|>"]   # v3 journals
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
        self.special["<|npc|>"] = self.special["<|act|>"]   # v3 journals
        self.vocab_size = _pad64(self.n_real)

    def encode(self, text: str) -> list[int]:
        return self._enc.encode_ordinary(text)

    def token_bytes(self, tid: int) -> bytes:
        if tid in self._special_ids or tid >= self._enc.n_vocab:
            return b""
        return self._enc.decode_single_token_bytes(tid)


FW32_FILE = Path(__file__).resolve().parent / "data" / "fineweb32k.tiktoken"
FW32_VOCAB = 32760          # learned tokens; with the 8 role tokens: 32,768
# GPT-4's pre-tokenisation (contractions, words, numbers of up to 3 digits, punctuation, spaces).
FW32_PATTERN = (r"""(?i:'s|'t|'re|'ve|'m|'ll|'d)|[^\r\n\p{L}\p{N}]?\p{L}+|\p{N}{1,3}| ?[^\s\p{L}\p{N}]+[\r\n]*"""
                r"""|\s*[\r\n]+|\s+(?!\S)|\s+""")


class FineWeb32kTokenizer(Tokenizer):
    kind = "fineweb32k"

    def __init__(self):
        import tiktoken

        ranks = {}
        for line in FW32_FILE.read_text(encoding="ascii").splitlines():
            if line:
                tok, rank = line.split()
                ranks[base64.b64decode(tok)] = int(rank)
        n = len(ranks)
        self.special = {s: n + i for i, s in enumerate(SPECIALS)}
        self._special_ids = set(self.special.values())
        self._enc = tiktoken.Encoding(name="fineweb32k", pat_str=FW32_PATTERN, mergeable_ranks=ranks,
                                      special_tokens=self.special)
        self.n_real = n + len(SPECIALS)
        self.special["<|npc|>"] = self.special["<|act|>"]   # v3 journals
        self.vocab_size = _pad64(self.n_real)

    def encode(self, text: str) -> list[int]:
        return self._enc.encode_ordinary(text)

    def token_bytes(self, tid: int) -> bytes:
        if tid in self._special_ids or tid >= self.n_real:
            return b""
        return self._enc.decode_single_token_bytes(tid)


def make_tokenizer(kind: str) -> Tokenizer:
    if kind == "fineweb32k":
        return FineWeb32kTokenizer()
    if kind == "gpt2":
        try:
            return GPT2Tokenizer()
        except Exception as e:  # tiktoken missing or no network for its first download
            print(f"[tokenizer] GPT-2 BPE unavailable ({e}); falling back to bytes")
            return ByteTokenizer()
    return ByteTokenizer()


def encode_parts(tok: Tokenizer, parts) -> list[int]:
    """[(role, text), ...] -> ids, each text preceded by its role token."""
    ids: list[int] = []
    for role, text in parts:
        ids.append(tok[role])
        ids.extend(tok.encode(text))
    return ids
