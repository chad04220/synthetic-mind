"""Zen's mind in v4: every action and every mark chosen by its own brain, learnt from what follows."""
import json
import multiprocessing as mp
import random
import struct
import sys
from pathlib import Path

import pytest
import torch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ada.config import AdaConfig, BrainConfig  # noqa: E402
from ada.model import Brain  # noqa: E402
from ada.motor import MOTOR, Experience, MotorMind, motor_ids  # noqa: E402
from ada.proc import Link, append_jsonl  # noqa: E402
from ada.tokenizer import make_tokenizer  # noqa: E402
from ada.world import render, studio  # noqa: E402


@pytest.fixture
def mind(tmp_path):
    folder = tmp_path / "Z"
    folder.mkdir()
    cfg = AdaConfig(name="Z", tokenizer="bytes")
    cfg.apply_preset("tiny")
    cfg.brain.d_model, cfg.brain.n_layers, cfg.brain.n_heads, cfg.brain.seq_len = 64, 2, 2, 96
    cfg.academy.batch_size, cfg.academy.fineweb = 4, False
    cfg.save(folder / "config.json")
    return folder


def tiny_brain(seed=0):
    torch.manual_seed(seed)
    b = Brain(BrainConfig(vocab_size=320, d_model=64, n_layers=2, n_heads=2, seq_len=96)).eval()
    for blk in b.blocks:                         # untrained blocks are zero: give them something to do
        torch.nn.init.normal_(blk.attn.proj.weight, std=0.05)
        torch.nn.init.normal_(blk.mlp.down.weight, std=0.05)
    return b


def test_appending_several_tokens_to_a_cache_matches_one_full_pass():
    b = tiny_brain()
    ids = torch.randint(0, 320, (1, 50))
    with torch.no_grad():
        full = b.hidden(ids)
        caches = [{} for _ in b.blocks]
        parts = [b.hidden(ids[:, :20], caches), b.hidden(ids[:, 20:23], caches), b.hidden(ids[:, 23:], caches)]
    assert torch.allclose(torch.cat(parts, 1), full, atol=1e-5)


def test_the_brain_chooses_every_action_from_its_own_logits():
    tok = make_tokenizer("bytes")
    motor = motor_ids(tok)
    assert len(motor) == len(MOTOR) == len(set(motor))
    assert motor_ids(make_tokenizer("fineweb32k")) == [make_tokenizer("fineweb32k").encode(" " + w)[0] for w in MOTOR]
    b = tiny_brain()
    m = MotorMind(96)
    rng = random.Random(1)
    seen = set()
    for step in range(60):                       # far past the window: the cache is rebuilt as it goes
        m.push([tok["<|world|>"]] + tok.encode(f"I see a tree {step}."))
        c = m.choose(b, motor, tok["<|act|>"], 1.0, rng)
        assert 0 <= c["index"] < len(MOTOR) and abs(sum(c["probs"]) - 1) < 1e-3 and c["entropy"] > 0
        seen.add(c["word"])
        assert m.cached <= 96
    assert len(seen) > 3                         # an untrained brain explores
    # what it chose is exactly what its brain makes most likely when it is sure
    with torch.no_grad():
        b.embed.weight[motor[7]] *= 0
        b.embed.weight[motor[7]] += 5 * b.embed.weight[tok["<|act|>"]]
    m.reset()
    picks = [m.choose(b, motor, tok["<|act|>"], 0.05, rng)["word"] for _ in range(5)]
    assert len(set(picks)) == 1


def test_experience_scores_each_action_by_what_followed():
    e = Experience(window=60, lookahead=6)
    out = []
    for step in range(80):
        e.tokens([1, 2, 3])
        e.tokens([9, 10])
        e.act(step % 3, vocab=0)
        e.reward(1.0 if step % 3 == 0 else -0.5)
        out += e.ready()
    assert out and all(len(w["ids"]) == 60 for w in out)
    acts = [a for w in out for a in w["acts"]]
    assert all(1 <= a[0] < 60 and len(a) == 4 for a in acts)
    good = [a[2] for a in acts if a[1] == 0]
    bad = [a[2] for a in acts if a[1] != 0]
    assert sum(good) / len(good) > sum(bad) / len(bad)      # rewarded actions get the higher advantage
    for w in out:                                          # each action sits right after an <|act|>-like token
        for pos, idx, adv, voc in w["acts"]:
            assert w["ids"][pos] == 10


def test_the_academy_learns_to_do_what_turned_out_well(mind):
    from ada.academy import Academy

    tok = make_tokenizer("bytes")
    motor = motor_ids(tok)
    act = tok["<|act|>"]
    ctx = [tok["<|world|>"]] + tok.encode("I am thirsty. Ahead: a stream.")
    for _ in range(40):                          # drinking at the stream helped; walking away did not
        for good in (True, False):
            ids = ctx + [act, motor[MOTOR.index("drink" if good else "back")]]
            append_jsonl(mind / "experience.jsonl", {"ids": ids, "acts": [[len(ids) - 1,
                         MOTOR.index("drink" if good else "back"), 1.5 if good else -1.5, 0]], "ret": 0.0})
    q = mp.Queue()
    a = Academy(mind, Link("academy", q, q, mind))
    a.ingest()
    assert len(a.experience) == 80

    def p_drink():
        with torch.no_grad():
            h = a.brain.hidden(torch.tensor([ctx + [act]], device=a.device))
            z = a.brain.motor_logits(h[0, -1], torch.tensor(motor, device=a.device)).float()
            return float(torch.softmax(z, -1)[MOTOR.index("drink")])

    before = p_drink()
    a.handle({"cmd": "resume"})
    for _ in range(30):
        assert a.train_step()
    assert p_drink() > 1.5 * before and a.pg_loss is not None and a.motor_entropy is not None
    assert a.status()["motor"]["windows"] == 80


def test_the_studio_only_does_what_it_is_told():
    c = studio.Canvas()
    assert c.pixels() == "." * (64 * 48)
    for w in ["red", "press", "right", "right", "lift", "right", "big", "dot", "blue", "jump"]:
        c.apply(w)
    px = c.pixels()
    red = studio.CODES[studio.COLOR_NAMES.index("red")]
    assert px[24 * 64 + 32: 24 * 64 + 35] == red * 3 and px[24 * 64 + 35] != "."
    assert px.count(".") == 64 * 48 - 11         # three red cells, a 3×3 dab over one of them; the jump was pen-up
    assert "".join(c.ops) == "".join(studio.PAINT_CODES[w] for w in ["red", "press", "right", "right", "lift", "right", "big", "dot", "blue", "jump"])
    p = studio.Piano()
    for w in ["C", "E", "high", "C", "long", "rest", "short", "G", "fast", "done"]:
        p.apply(w)
    assert p.notes == [[60, 1.0], [64, 1.0], [72, 1.0], [-1, 2.0], [79, 0.5]] and p.done and p.tempo == 112
    k = studio.Clay()
    for w in ["add", "up", "add", "right", "add", "cut", "smooth"]:
        k.apply(w)
    assert k.voxels().count("1") >= 2 and k.data()["n"] == 12
    for kind, ins in (("paint", studio.Canvas()), ("compose", studio.Piano()), ("sculpt", studio.Clay())):
        r = random.Random(0)
        for _ in range(200):
            ins.apply(r.choice(studio.VOCABS[kind][:-1]))
        sc = ins.score([])
        assert 0 <= sc["total"] <= 1 and ins.describe()
    assert studio.vocab_ids(make_tokenizer("fineweb32k"), "paint")[studio.PAINT.index("red")] == \
        make_tokenizer("fineweb32k").encode(" red")[0]


def test_the_sprite_is_shown_real_pictures_and_sounds():
    c = studio.Canvas()
    for w in ["green", "big", "press", "right", "down"]:
        c.apply(w)
    p = render.painting_png(c.data())
    assert p[:8] == b"\x89PNG\r\n\x1a\n" and struct.unpack(">II", p[16:24]) == (64 * 7, 48 * 7)
    k = studio.Clay()
    k.apply("add")
    assert render.sculpture_png(k.data())[:4] == b"\x89PNG"
    m = studio.Piano()
    for w in "C D E".split():
        m.apply(w)
    wav = render.music_wav(m.data())
    assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE" and len(wav) > 16000


def test_the_sprite_judges_what_it_sees():
    from ada.sprite import SpriteVoice

    class Eyes:
        senses = True

        def __init__(self):
            self.seen = []

        def look_listen(self, system, prompt, images=(), audio=()):
            self.seen.append((len(images), len(audio), prompt))
            return 'Sure! {"score": 6.5, "see": "A green square on white paper.", "say": "Nice square, Zen. Try a second colour."}'

        def chat(self, *a, **k):
            return '{"score": 3, "see": "Three words.", "say": "Keep writing."}'

    eyes = Eyes()
    v = SpriteVoice(eyes)
    out = v.critique("painting", image=b"png", marks=40)
    assert out == {"score": 6.5, "see": "A green square on white paper.", "say": "Nice square, Zen. Try a second colour."}
    assert eyes.seen[-1][:2] == (1, 0) and "40 marks" in eyes.seen[-1][2]
    v.critique("music", audio=b"wav")
    assert eyes.seen[-1][:2] == (0, 1)
    assert v.critique("poem", text="sun sun tree")["score"] == 3
    eyes.senses = False
    assert v.critique("painting", image=b"png") == {}   # a model that can't see doesn't pretend to


def test_its_own_actions_are_not_imitated_only_reinforced(mind):
    """The language-model loss skips its action words: copying its past choices would turn chance into habit."""
    from ada.academy import Academy

    tok = make_tokenizer("bytes")
    motor = motor_ids(tok)
    act = tok["<|act|>"]
    ctx = [tok["<|world|>"]] + tok.encode("A wall is in the way.")
    for _ in range(60):                          # it did 'back' again and again, and it never helped (advantage 0)
        ids = ctx + [act, motor[MOTOR.index("back")]]
        append_jsonl(mind / "experience.jsonl", {"ids": ids, "acts": [[len(ids) - 1, MOTOR.index("back"), 0.0, 0]], "ret": 0.0})
    q = mp.Queue()
    a = Academy(mind, Link("academy", q, q, mind))
    a.ingest()

    def p_back():
        with torch.no_grad():
            h = a.brain.hidden(torch.tensor([ctx + [act]], device=a.device))
            z = a.brain.motor_logits(h[0, -1], torch.tensor(motor, device=a.device)).float()
            return float(torch.softmax(z, -1)[MOTOR.index("back")])

    before = p_back()
    a.handle({"cmd": "resume"})
    for _ in range(30):
        a.train_step()
    assert p_back() < before + 0.05              # no habit from mere repetition
