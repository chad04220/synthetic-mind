"""v4 end to end: a real (tiny) brain living in the real world, every deed its own."""
import json
import multiprocessing as mp
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ada.academy import Academy  # noqa: E402
from ada.config import AdaConfig  # noqa: E402
from ada.life import Life  # noqa: E402
from ada.motor import MOTOR  # noqa: E402
from ada.proc import Link  # noqa: E402
from ada.world.sim import DIRS  # noqa: E402


class FakeLink:
    def __init__(self):
        from ada.diag import Perf

        self.sent, self.perf = [], Perf()

    def warn(self, *a, **k):
        pass

    def log(self, *a, **k):
        pass

    def maybe_send_perf(self, *a, **k):
        pass

    def send(self, type_, **d):
        self.sent.append((type_, d))

    def reply(self, rid, result=None, error=None):
        self.sent.append(("reply", {"rid": rid, "result": result, "error": error}))

    def events(self, kind):
        return [d for t, d in self.sent if t == "event" and d.get("kind") == kind]


@pytest.fixture
def zen(tmp_path):
    folder = tmp_path / "Zen"
    folder.mkdir()
    cfg = AdaConfig(name="Zen", tokenizer="bytes")
    cfg.apply_preset("tiny")
    cfg.brain.d_model, cfg.brain.n_layers, cfg.brain.n_heads, cfg.brain.seq_len = 64, 2, 2, 128
    cfg.academy.batch_size, cfg.academy.fineweb = 4, False
    cfg.world.seed = 11
    cfg.world.thought_tokens = 8
    cfg.save(folder / "config.json")
    q = mp.Queue()
    a = Academy(folder, Link("academy", q, q, folder))
    a.publish("first")
    life = Life(folder, FakeLink(), with_brain=True, threaded=False)
    life.maybe_load_brain()
    assert life.brain is not None
    return life


def live(life, beats):
    for _ in range(beats):
        life.next_motor = 0
        life.step()


def test_every_deed_is_chosen_by_its_own_brain(zen):
    live(zen, 300)
    did = zen.link.events("did")
    assert len(did) >= 250
    assert {d["action"] for d in did} <= set(MOTOR) and len({d["action"] for d in did}) >= 8
    assert all(len(d["probs"]) == len(MOTOR) for d in did)          # its brain's own odds came with every deed
    assert zen.motor_stats["steps"] == len(did)
    # the stream it lives is the stream it learns from: windows of experience with each action scored
    rows = [json.loads(x) for x in (zen.folder / "experience.jsonl").read_text().splitlines()]
    assert rows and all(len(r["ids"]) == zen.cfg.brain.seq_len + 1 for r in rows)
    acts = [a for r in rows for a in r["acts"]]
    vocab = [zen.vocab[k] for k in ("motor", "paint", "compose", "sculpt")]      # body, brush, piano, clay
    assert all(r["ids"][a[0]] == vocab[a[3]][a[1]] and r["ids"][a[0] - 1] == zen.act_tok for r in rows for a in r["acts"])
    assert any(a[2] > 0 for a in acts) and any(a[2] < 0 for a in acts)
    snap = [d for t, d in zen.link.sent if t == "world"]
    zen.broadcast()
    snap = [d for t, d in zen.link.sent if t == "world"][-1]["snap"]
    assert snap["mind"]["motor"]["steps"] == len(did) and "zen" in snap and "sprite" in snap


def test_it_paints_mark_by_mark_and_the_sprite_judges_it(zen):
    w = zen.world
    easel = next(e for e in w.ents.values() if e["kind"] == "easel")
    for f, (dx, dy) in enumerate(DIRS):                 # stand in front of the easel, facing it
        if w.walkable(easel["x"] - dx, easel["y"] - dy):
            w.zen.x, w.zen.y, w.zen.facing = easel["x"] - dx, easel["y"] - dy, f
            break
    zen.voice_ready = True
    zen.on_motor({"index": MOTOR.index("use"), "word": "use", "probs": [1 / 14] * 14, "entropy": 2.6})
    assert zen.session is not None and zen.session["kind"] == "paint"
    for _ in range(2000):
        if zen.session is None:
            break
        zen.step()
    made = [d["creation"] for d in zen.link.events("created")]
    assert made and made[-1]["kind"] == "painting" and made[-1]["data"]["v"] == 3
    piece = made[-1]
    assert len(piece["data"]["ops"]) == piece["data"]["marks"] and len(piece["data"]["pixels"]) == 64 * 48
    # the Sprite is shown the painting itself and its verdict becomes the reward for the marks
    ask = [d for t, d in zen.link.sent if t == "oracle" and d["purpose"] == "sprite_critique"]
    assert ask and ask[-1]["payload"]["image"][:4] == b"\x89PNG"
    zen.handle({"cmd": "oracle_reply", "req": ask[-1]["rid"], "text": "",
                "critique": {"score": 7.0, "see": "A red line across white paper.", "say": "A brave line, Zen."}})
    assert piece["critique"]["score"] == 7.0 and w.sprite.said == "A brave line, Zen."
    assert zen.judging is None
    # you can love it: every mark counts for more
    assert "marks" in zen.love(piece["id"])
    rows = [json.loads(x) for x in (zen.folder / "experience.jsonl").read_text().splitlines()]
    loved = [r for r in rows if r.get("loved") == piece["id"]]
    assert loved and all(a[2] > 0 and a[3] == 1 for r in loved for a in r["acts"])


def test_it_asks_the_sprite_and_waits_for_the_answer(zen):
    zen.voice_ready = True
    zen.on_motor({"index": MOTOR.index("ask"), "word": "ask", "probs": [1 / 14] * 14, "entropy": 2.6})
    ask = [d for t, d in zen.link.sent if t == "oracle" and d["purpose"] == "sprite_answer"]
    if not ask:                                     # its brain wrote nothing yet: nothing to ask
        assert zen.waiting is None
        return
    assert zen.waiting is not None and not zen.can_act()          # its body waits; thoughts go on
    before = zen.motor_stats["steps"]
    live(zen, 20)
    assert zen.motor_stats["steps"] == before
    zen.handle({"cmd": "oracle_reply", "req": ask[-1]["rid"], "text": "That is a tree. Trees grow from seeds."})
    assert zen.waiting is None and zen.can_act()
    assert zen.link.events("answer")[-1]["text"].startswith("That is a tree")


def test_its_life_survives_a_restart(zen):
    live(zen, 60)
    w = zen.world
    pos, steps = (w.zen.x, w.zen.y), zen.motor_stats["steps"]
    zen.save()
    again = Life(zen.folder, FakeLink(), with_brain=False, threaded=False)
    assert (again.world.zen.x, again.world.zen.y) == pos and again.motor_stats["steps"] == steps
    assert again.mind.tail(50) == zen.mind.tail(50)
