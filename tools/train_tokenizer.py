"""Build the "fineweb32k" tokenizer that new minds use (ada/data/fineweb32k.tiktoken).

A byte-level BPE with 32,760 learned tokens (plus the 8 role tokens = 32,768), trained on a random
sample of FineWeb, the same web text the Academy studies. Byte-level means any text can be
written with it, so nothing is ever out of vocabulary; a vocabulary this size suits brains of
tens to hundreds of millions of parameters better than GPT-2's 50,257: half of a small brain is no
longer a lookup table, and the loss over the vocabulary costs a third less.

The result is stored in tiktoken's format, so the program itself only needs tiktoken.

    pip install tokenizers huggingface_hub pyarrow
    python tools/train_tokenizer.py --megabytes 300
"""
from __future__ import annotations

import argparse
import base64
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ada.tokenizer import FW32_PATTERN, FW32_VOCAB, SPECIALS  # noqa: E402


def sample_fineweb(megabytes: float, seed: int) -> list[str]:
    """Random 1000-document row groups from random FineWeb files across Common Crawl dumps."""
    import pyarrow.parquet as pq
    from huggingface_hub import HfApi, HfFileSystem

    api, fs, rng = HfApi(), HfFileSystem(), random.Random(seed)
    dumps = [e.path for e in api.list_repo_tree("HuggingFaceFW/fineweb", path_in_repo="data", repo_type="dataset")]
    texts, size, t0 = [], 0, time.time()
    while size < megabytes * 1e6:
        dump = rng.choice(dumps)
        files = [e.path for e in api.list_repo_tree("HuggingFaceFW/fineweb", path_in_repo=dump, repo_type="dataset")
                 if e.path.endswith(".parquet")]
        path = "datasets/HuggingFaceFW/fineweb/" + rng.choice(files)
        with fs.open(path, "rb", block_size=1 << 20) as f:
            pf = pq.ParquetFile(f)
            g = rng.randrange(pf.num_row_groups)
            col = pf.read_row_group(g, columns=["text"]).column("text").to_pylist()
        texts.extend(col)
        size += sum(len(t.encode("utf-8")) for t in col)
        print(f"  {size / 1e6:6.1f} MB from {dump} ({time.time() - t0:.0f}s)", flush=True)
    return texts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--megabytes", type=float, default=300)
    ap.add_argument("--seed", type=int, default=20261016)
    ap.add_argument("--out", default=str(ROOT / "ada" / "data" / "fineweb32k.tiktoken"))
    args = ap.parse_args()

    from tokenizers import Regex, Tokenizer, decoders, models, pre_tokenizers, trainers

    print("Sampling FineWeb…")
    texts = sample_fineweb(args.megabytes, args.seed)
    tok = Tokenizer(models.BPE())
    tok.pre_tokenizer = pre_tokenizers.Sequence([
        pre_tokenizers.Split(Regex(FW32_PATTERN), behavior="isolated"),
        pre_tokenizers.ByteLevel(add_prefix_space=False, use_regex=False),
    ])
    tok.decoder = decoders.ByteLevel()
    trainer = trainers.BpeTrainer(vocab_size=FW32_VOCAB, show_progress=True, min_frequency=2,
                                  initial_alphabet=pre_tokenizers.ByteLevel.alphabet())
    print(f"Training a {FW32_VOCAB}-token BPE on {len(texts)} documents…")
    tok.train_from_iterator(texts, trainer=trainer, length=len(texts))

    # Byte-level BPE writes bytes as printable characters; map them back to raw bytes.
    bs = list(range(ord("!"), ord("~") + 1)) + list(range(ord("¡"), ord("¬") + 1)) + list(range(ord("®"), ord("ÿ") + 1))
    cs = bs[:]
    n = 0
    for b in range(256):
        if b not in bs:
            bs.append(b)
            cs.append(256 + n)
            n += 1
    unbyte = {chr(c): b for b, c in zip(bs, cs)}
    vocab = json.loads(tok.to_str())["model"]["vocab"]
    ranks = sorted(vocab.items(), key=lambda kv: kv[1])
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="ascii") as f:
        for token, rank in ranks:
            f.write(f"{base64.b64encode(bytes(unbyte[c] for c in token)).decode()} {rank}\n")
    print(f"Wrote {len(ranks)} tokens (+{len(SPECIALS)} role tokens) to {out}")


if __name__ == "__main__":
    main()
