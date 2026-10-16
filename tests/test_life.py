"""v5 World process: the real voxel world, the real skills, a (fake) model deciding."""
import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ada.config import AdaConfig  # noqa: E402
from ada.life import World  # noqa: E402
from test_mind import FakeLlama, reply  # noqa: E402


class FakeLink:
    def __init__(self):
        from ada.diag import Perf

        self.sent, self.perf = [], Perf()

    def send(self, t, **d):
        self.sent.append((t, d))

    def log(self, *a, **k):
        pass

    def commands(self):
        return []

    def maybe_send_perf(self, *a):
        pass

    def hub_alive(self):
        return True

    def reply(self, rid, result=None, error=None):
        self.sent.append(("reply", {"rid": rid, "result": result, "error": error}))

    def events(self, kind):
        return [d for t, d in self.sent if t == "event" and d.get("kind") == kind]


@pytest.fixture
def world(tmp_path):
    folder = tmp_path / "Zen"
    folder.mkdir()
    cfg = AdaConfig(name="Zen")
    cfg.world.seed = 1234
    cfg.world.view_chunks = 3
    cfg.save(folder / "config.json")
    llama = FakeLlama()
    w = World(folder, FakeLink(), threaded=False)
    w.mind.url = llama.url
    yield w, llama
    llama.server.shutdown()


def live(w, until, seconds=30.0):
    t0 = time.time()
    while time.time() - t0 < seconds:
        w.w.tick()
        w.step()
        if until():
            return True
        time.sleep(0.002)
    return False


def test_it_decides_acts_and_learns_what_came_of_it(world):
    w, llama = world
    llama.replies.append(reply(skill="mine_nearest", args={"block": "oak_log", "count": 1}, say="Wood first!"))
    w.handle({"cmd": "chat", "text": "Hello Zen, could you get some wood?", "who": "Chad"})
    assert live(w, lambda: w.link.events("outcome"), 60)
    out = w.link.events("outcome")[-1]
    assert out["ok"], out
    assert w.w.agent.count("oak_log") >= 1
    d = w.link.events("decision")[-1]["decision"]
    assert d["say"] == "Wood first!" and w.link.events("said")[-1]["text"] == "Wood first!"
    obs = llama.requests[0]["messages"][1]["content"]
    assert "Chad: Hello Zen" in obs and "What you perceive now:" in obs and "inventory" in obs
    row = json.loads((w.folder / "decisions.jsonl").read_text().splitlines()[-1])
    assert row["outcome"]["ok"] and row["reply"]
    # the next thought sees what happened
    llama.replies.append(reply(skill="wait", args={"seconds": 1}))
    assert live(w, lambda: len(llama.requests) >= 2, 20)
    assert "mine_nearest" in llama.requests[1]["messages"][1]["content"] and "worked" in llama.requests[1]["messages"][1]["content"]


def test_a_failed_action_is_its_own_decisions_outcome(world):
    w, llama = world
    llama.replies.append(reply(skill="craft", args={"item": "diamond_pickaxe"}))
    w.mind.wake("test")
    assert live(w, lambda: w.link.events("outcome"), 20)
    o = w.link.events("outcome")[-1]
    assert not o["ok"] and o["id"] == "d1"


def test_deciding_the_same_thing_again_does_not_restart_it(world):
    w, llama = world
    llama.replies.append(reply(skill="wait", args={"seconds": 60}))
    w.mind.wake("test")
    rec = None
    assert live(w, lambda: w.running is not None and w.w.skills.busy, 20)
    rec = w.running
    llama.replies.append(reply(skill="wait", args={"seconds": 60}))
    w.mind.wake("again")
    assert live(w, lambda: w.running is not rec and w.running is not None, 20)
    assert w.w.skills.busy and rec["outcome"]["ok"], rec.get("outcome")
    assert "keep at it" in rec["outcome"]["text"]


def test_it_names_places_and_hears_about_its_practice(world):
    w, llama = world
    llama.replies.append(reply(skill="name_place", args={"name": "home"}))
    w.mind.wake("test")
    assert live(w, lambda: w.link.events("outcome"), 20)
    assert "home" in w.mind.places and w.w.places["home"] == w.mind.places["home"]
    # practice it asked for: refused (too little experience), then a round you started
    llama.replies.append(reply(skill="practice", args={}))
    w.mind.wake("test")
    assert live(w, lambda: len(w.link.events("outcome")) >= 2, 20)
    assert "enough new experience" in w.link.events("outcome")[-1]["text"]
    w.handle({"cmd": "practice", "event": "started", "by": "visitor", "name": "p1"})
    assert w.mind.busy_with == "practising" and w.w.agent.sleeping
    assert w.mind.due(time.time() + 999, False) is None              # no thinking while it practises
    w.handle({"cmd": "practice", "event": "done", "name": "p1", "info": {"examples": 12, "loss": 0.3}})
    assert w.mind.learning["adapter"] == "p1" and w.mind.learning["practices"] == 1 and not w.w.agent.sleeping
    assert "woke up as p1" in w.link.events("reflection")[-1]["text"]


def test_you_are_heard_and_your_judgements_are_kept(world):
    w, llama = world
    llama.replies.append(reply(skill="wait", args={"seconds": 1}))
    w.mind.wake("test")
    assert live(w, lambda: w.link.events("outcome"), 20)
    w.handle({"cmd": "agent", "action": "rate", "id": "d1", "value": -1})
    w.handle({"cmd": "agent", "action": "correct", "id": "d1", "text": "Don't just stand there: get wood."})
    js = [json.loads(x) for x in (w.folder / "judgements.jsonl").read_text().splitlines()]
    assert [j.get("value") for j in js if j["by"] == "visitor"][0] == -1
    assert w.mind.lessons[-1]["by"] == "visitor" and "get wood" in w.mind.events[-1]
    w.cfg.mind.radio = False
    assert w.handle({"cmd": "chat", "text": "can you hear me?", "rid": None}) is None
    assert w._handle("chat", {"text": "far away"}) == {"heard": False}
    w.save()
    again = World(w.folder, FakeLink(), threaded=False)
    assert again.mind.lessons == w.mind.lessons and again.w.agent.x == pytest.approx(w.w.agent.x)
