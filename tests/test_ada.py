"""Offline tests: CPU only, no FineWeb, no Ollama (a tiny fake one where needed).

    python -m pytest tests
"""
import json
import multiprocessing as mp
import random
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ada.academy import Academy  # noqa: E402
from ada.concepts import ConceptGraph  # noqa: E402
from ada.config import AdaConfig, set_live  # noqa: E402
from ada.life import Life  # noqa: E402
from ada.model import Brain  # noqa: E402
from ada.proc import FileTail, Link, append_jsonl  # noqa: E402
from ada.world import agent as ag  # noqa: E402
from ada.world.sim import World  # noqa: E402


class FakeLink:
    def __init__(self):
        from ada.diag import Perf

        self.sent = []
        self.perf = Perf()

    def warn(self, *a, **k):
        pass

    def maybe_send_perf(self, *a, **k):
        pass

    def send(self, type_, **d):
        self.sent.append((type_, d))

    def log(self, *a, **k):
        pass

    def reply(self, rid, result=None, error=None):
        self.sent.append(("reply", {"rid": rid, "result": result, "error": error}))

    def kinds(self):
        return [d.get("kind", t) for t, d in self.sent]


@pytest.fixture
def mind(tmp_path):
    folder = tmp_path / "T"
    folder.mkdir()
    cfg = AdaConfig(name="T", tokenizer="bytes")
    cfg.apply_preset("tiny")
    cfg.brain.d_model, cfg.brain.n_layers, cfg.brain.n_heads, cfg.brain.seq_len = 64, 2, 2, 96
    cfg.academy.batch_size, cfg.academy.fineweb = 4, False
    cfg.world.day_minutes, cfg.world.night_minutes = 2, 1
    cfg.save(folder / "config.json")
    return folder


def academy(folder):
    q = mp.Queue()
    return Academy(folder, Link("academy", q, q, folder))


# ------------------------------------------------------------------ brain
def test_cached_generation_matches_full_forward():
    cfg = AdaConfig().brain
    cfg.vocab_size, cfg.d_model, cfg.n_layers, cfg.n_heads, cfg.seq_len = 320, 64, 2, 2, 64
    b = Brain(cfg)
    for p in b.parameters():
        p.data.add_(torch.randn_like(p) * 0.05)
    torch.manual_seed(0)
    out = b.generate([1, 2, 3], 6, temperature=1e-4)          # ~greedy, with the key/value cache
    ids = [1, 2, 3]
    for t, _, _ in out:                                         # the same choices without the cache
        assert int(b(torch.tensor([ids]))[0, -1].argmax()) == t
        ids.append(t)


def test_growth_keeps_what_it_computes():
    cfg = AdaConfig().brain
    cfg.vocab_size, cfg.d_model, cfg.n_layers, cfg.n_heads = 320, 64, 2, 2
    b = Brain(cfg)
    for p in b.parameters():
        p.data.add_(torch.randn_like(p) * 0.02)
    x = torch.randint(0, 256, (2, 12))
    before = b(x)
    b.grow()
    assert len(b.blocks) == 3 and torch.allclose(before, b(x), atol=1e-5)


# ------------------------------------------------------------------ concepts
def test_probes_are_worded_unlike_drills_and_have_one_true_answer():
    g = ConceptGraph()
    probes = g.probes()
    assert len(probes) > 150
    drills = " ".join(t for _ in range(300) for _, t in g.drill(random.Random(_)))
    for p in probes[:40]:
        assert p["o"] in p["options"] and len(set(p["options"])) == 4
        truth = p["sentences"][p["options"].index(p["o"])]
        assert truth not in drills


def test_oracle_facts_are_validated_and_shared_through_the_file(tmp_path):
    a = ConceptGraph(tmp_path / "concepts.json")
    n = a.add([{"s": "moon", "r": "is", "o": "round"}, {"s": "x", "r": "likes", "o": "y"}, {"s": "", "r": "is", "o": "z"}], "oracle")
    assert n == 1
    b = ConceptGraph(tmp_path / "concepts.json")
    assert b.all() and dict(b.all())[("moon", "is", "round")] == "oracle"


# ------------------------------------------------------------------ words -> deeds
@pytest.mark.parametrize("text,verb,obj", [
    ("I eat the apple.", "eat", "apple"), ("I go and bake bread", "bake", "bread"),
    ("I water the sprout", "water", "sprout"), ("I drink water", "drink", "water"),
    ("I talk to mira", "talk", "Mira"), ("I look at the stars", "look", "telescope"),
    ("I go to the library.", "go", "library"), ("I give the apple to my friend", "give", "apple"),
])
def test_intentions_parse(text, verb, obj):
    g = ag.parse(text)
    assert (g.verb, g.obj) == (verb, obj)
    assert ag.parse(ag.say(g)).verb == verb          # what she learns to say, she can do


def test_gibberish_is_not_an_intention():
    assert ag.parse("IIIII 0x9f zz") is None


def test_her_needs_alone_keep_her_alive_and_busy():
    w = World(seed=4)
    done, ok = [], 0
    rng = random.Random(4)
    plan = None
    for _ in range(4000):
        w.advance(0.25)
        w.update_needs(0.25)
        if plan is None:
            g = ag.drives(w, rng, False, True)
            plan, _ = ag.plan(w, g)
            continue
        tx, ty, adj = ag.target_pos(w, plan) or (w.ada.x, w.ada.y, False)
        a = w.ada
        there = (abs(tx - a.x) + abs(ty - a.y) == 1) if adj else (a.x, a.y) == (tx, ty)
        if there or (adj and (a.x, a.y) == (tx, ty)):
            success, _, _ = ag.act(w, plan)
            ok += success
            done.append(plan.goal.verb)
            plan = None
            continue
        route = w.path((a.x, a.y), (tx, ty), me=a, adjacent=adj) or w.path((a.x, a.y), (tx, ty), me=a, adjacent=adj, avoid=False)
        if not route:
            plan = None
            continue
        a.x, a.y = route[0]
    assert len(set(done)) >= 6 and ok >= 0.8 * len(done)
    assert min(w.needs["energy"], w.needs["water"]) > 10


# ------------------------------------------------------------------ the Academy
def test_academy_learns_publishes_and_resumes(mind):
    append_jsonl(mind / "curriculum.jsonl", {"kind": "lesson", "parts": [["<|oracle|>", "The sun is hot. Snow is cold."]]})
    append_jsonl(mind / "journal.jsonl", {"kind": "deed", "parts": [["<|world|>", "I am hungry."], ["<|intent|>", "I eat the apple."]]})
    a = academy(mind)
    a.ingest()
    assert len(a.lessons) == 1 and len(a.journal) == 1
    a.handle({"cmd": "resume"})
    first = None
    for _ in range(25):
        assert a.train_step()
        first = first or a.loss_ema
    assert a.loss_ema < first
    a.evaluate()
    assert 0 <= a.concept_score["accuracy"] <= 1 and a.concept_score["n"] > 150
    a.handle({"cmd": "pause", "why": "night"})                 # pausing publishes and saves
    meta = json.loads((mind / "brain" / "latest.json").read_text())
    assert meta["step"] == 25 and (mind / "academy.pt").exists()
    b = academy(mind)
    assert b.step == 25 and len(b.lessons) == 1


def test_unstable_steps_never_reach_the_weights(mind):
    a = academy(mind)
    a.handle({"cmd": "resume"})
    a.train_step()
    real = a.brain.chunked_loss
    a.brain.chunked_loss = lambda h, t, **k: real(h, t, **k) * float("nan")
    step = a.step
    assert a.train_step() and a.step == step and a.skipped == 1
    assert all(torch.isfinite(p).all() for p in a.brain.parameters())


def test_file_tail_reads_only_whole_new_lines(tmp_path):
    p = tmp_path / "j.jsonl"
    t = FileTail(p)
    append_jsonl(p, {"a": 1})
    with open(p, "a") as f:
        f.write('{"b": ')                                       # a write in progress
    assert t.read() == [{"a": 1}]
    with open(p, "a") as f:
        f.write('2}\n')
    assert t.read() == [{"b": 2}]


# ------------------------------------------------------------------ the World
def test_life_with_a_brain(mind):
    a = academy(mind)
    a.publish("test")
    life = Life(mind, FakeLink(), threaded=False)
    life.maybe_load_brain()
    assert life.brain_version == 1
    for _ in range(200):
        life.step()
    kinds = life.link.kinds()
    assert "intent" in kinds and "did" in kinds
    r = life.chat("Hello Ada")
    assert "text" in r and life.chat_log[-1]["role"] == "mind"
    assert "Ada will" in life.suggest("go to the library")
    assert "Placed" in life.place("apple", 18, 12)
    assert "blocked" in life.place("apple", 50, 30)            # the lake
    assert "in the world" in life.visitor("join")
    assert "holding" in life.visitor("hold", "apple")
    lines = (mind / "journal.jsonl").read_text().splitlines()
    assert any(json.loads(x)["kind"] == "deed" for x in lines)


def test_night_and_day(mind):
    life = Life(mind, FakeLink(), with_brain=False)
    w = life.world
    life.handle({"cmd": "sleep_now"})
    for _ in range(4000):
        life.step()
        if w.phase == "night":
            break
    assert w.phase == "night" and w.ada.sleeping
    assert ("phase", {"phase": "night", "day": 1}) in life.link.sent
    assert life.chat("are you there?") == {"asleep": True, "text": ""}
    life.handle({"cmd": "wake_now"})
    life.step()
    assert w.phase == "day" and w.day == 2 and not w.ada.sleeping
    assert "asleep" not in life.chat("good morning")


def test_world_state_survives_a_restart(mind):
    life = Life(mind, FakeLink(), with_brain=False)
    for _ in range(300):
        life.step()
    life.place("ball", 18, 12)
    life.save()
    again = Life(mind, FakeLink(), with_brain=False)
    assert (again.world.ada.x, again.world.ada.y) == (life.world.ada.x, life.world.ada.y)
    assert any(e["kind"] == "ball" and (e["x"], e["y"]) == (18, 12) for e in again.world.entities.values())


# ------------------------------------------------------------------ the Hub
def test_hub_never_imports_torch():
    code = "import sys; sys.path.insert(0, %r); import ada.hub, ada.web; print('torch' in sys.modules)" % str(ROOT)
    assert subprocess.run([sys.executable, "-c", code], capture_output=True, text=True).stdout.strip() == "False"


def test_hub_schedule_and_world_deltas(tmp_path):
    from ada.hub import Hub

    cfg = AdaConfig(name="H", tokenizer="bytes")
    cfg.oracle.enabled = False
    hub = Hub(cfg, tmp_path)
    sent = []
    hub.send = lambda child, cmd, rid=None, **a: sent.append((child, cmd, a))
    hub.phase = "day"
    hub.apply_schedule()
    assert sent[-1][:2] == ("academy", "pause")
    hub.on_message({"type": "phase", "phase": "night", "day": 1})
    assert sent[-1][:2] == ("academy", "resume")
    hub.set("schedule.mode", "together")
    assert sent[-1][1] == "resume" and sent[-1][2]["intensity"] == "balanced"
    with pytest.raises(ValueError):
        set_live(hub.cfg, "schedule.mode", "sometimes")
    # world updates merge into one delta per client
    w = World(seed=1)
    hub.on_message({"type": "world", "snap": w.snapshot(full=True)})
    seq0 = hub.world_seq
    e = w.add("apple", 18, 12)
    hub.on_message({"type": "world", "snap": w.snapshot()})
    w.remove(e)
    w.add("ball", 19, 12)
    hub.on_message({"type": "world", "snap": w.snapshot()})
    _, d = hub.world_delta(seq0)
    assert [x["kind"] for x in d["ents"]] == ["ball"] and e["id"] in d["removed"]
    assert hub.world_full()["full"] and len(hub.world_full()["ents"]) == len(w.entities)


def test_oracle_lesson_pack_against_a_fake_ollama(tmp_path):
    from ada.hub import Hub

    class Fake(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            self._send({"models": [{"name": "tiny:1b", "size": 1, "details": {}}, {"name": "nomic-embed-text", "size": 1, "details": {}}]})

        def do_POST(self):
            json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            c = json.dumps({"lesson": "Owls hunt at night.", "qa": [{"q": "Can owls see at night?", "a": "Yes."}],
                            "facts": [{"s": "owl", "r": "can", "o": "fly"}, {"s": "owl", "r": "eats", "o": "mice"}]})
            self._send({"message": {"content": c}})

        def _send(self, d):
            b = json.dumps(d).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    cfg = AdaConfig(name="O", tokenizer="bytes")
    cfg.oracle.url = f"http://127.0.0.1:{srv.server_port}"
    hub = Hub(cfg, tmp_path)
    assert [m["name"] for m in hub.oracle.refresh()] == ["tiny:1b"] and hub.oracle.model == "tiny:1b"
    pack = hub.teach("owls", priority=True)
    assert pack["new_facts"] == 1                                # the made-up relation was refused
    lines = [json.loads(x) for x in (tmp_path / "O" / "curriculum.jsonl").read_text().splitlines()]
    assert lines[0]["priority"] and lines[0]["parts"][0] == ["<|oracle|>", "Owls hunt at night."]
    srv.shutdown()


def test_saving_works_where_the_default_encoding_is_not_utf8(mind):
    """Windows writes text as cp1252 by default, which cannot hold the '�' Ada babbles early on."""
    code = f"""
import sys, locale; sys.path.insert(0, {str(ROOT)!r})
assert locale.getpreferredencoding(False).lower() not in ("utf-8", "utf8"), locale.getpreferredencoding(False)
from pathlib import Path
from ada.proc import write_json
from ada.concepts import ConceptGraph
from ada.config import AdaConfig
folder = Path({str(mind)!r})
write_json(folder / "x.json", {{"text": "babble \\ufffd \\u00e9 \\U0001F34E"}})
g = ConceptGraph(folder / "concepts.json"); g.add([{{"s": "caf\\u00e9", "r": "is", "o": "cozy"}}], "oracle")
assert ConceptGraph(folder / "concepts.json").all()
AdaConfig.load(folder / "config.json").save(folder / "config.json")
print("ok")
"""
    env = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C", "PYTHONUTF8": "0", "PYTHONCOERCECLOCALE": "0"}
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    assert r.stdout.strip() == "ok", r.stderr[-800:]


def test_warnings_and_crashes_are_logged(tmp_path):
    code = f"""
import sys, warnings, threading, time; sys.path.insert(0, {str(ROOT)!r})
from pathlib import Path
from ada.diag import setup_logging
setup_logging("probe", Path({str(tmp_path)!r}))
warnings.warn("something odd \\ufffd")
t = threading.Thread(target=lambda: 1 / 0, name="worker"); t.start(); t.join()
raise RuntimeError("the whole thing fell over")
"""
    subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    log = (tmp_path / "logs" / "probe.log").read_text(encoding="utf-8")
    assert "WARNING" in log and "something odd" in log
    assert "ZeroDivisionError" in log and "worker" in log
    assert "CRITICAL" in log and "the whole thing fell over" in log


def test_timings_and_findings():
    import time as _t

    from ada.diag import Perf, findings

    p = Perf()
    with p.time("wait for data"):
        _t.sleep(0.05)
    p.add("training step", 0.01)
    p.gauge("studying", 1)
    s = p.take()
    assert s["timings"]["wait for data"]["avg_ms"] >= 45 and s["timings"]["wait for data"]["share"] > 0.3
    f = findings({"academy": s}, [{"util_percent": 99, "mem_used_mb": 7900, "mem_total_mb": 8192, "temp_c": 70}],
                 {"fps": 9, "visible": True, "longtask_ms": 4000, "longtask_max_ms": 900, "window_s": 15}, {"world": 2})
    text = " ".join(x["text"] for x in f)
    assert "waiting for training data" in text and "memory is over 92%" in text
    assert "frames per second" in text and "frozen" in text and "restarted 2 time" in text


def test_report_has_everything(tmp_path):
    from ada.hub import Hub

    cfg = AdaConfig(name="R", tokenizer="bytes")
    cfg.oracle.enabled = False
    hub = Hub(cfg, tmp_path)
    hub.log.warning("a test warning")
    hub.on_message({"type": "perf", "src": "academy", "t": 1.0, "perf": {"timings": {}, "gauges": {}, "cpu_percent": 5}})
    hub.record_client_perf({"fps": 50, "visible": True})
    hub._diagnose_tick()
    text = hub.report()
    for section in ("Likely bottlenecks", "System", "GPU", "Latest timings", "Browser", "Academy", "Settings",
                    "Warnings and errors", "a test warning"):
        assert section in text
    assert (tmp_path / "R" / "logs" / "diagnostics-latest.txt").exists()


def test_a_slow_brain_never_stalls_the_world(mind):
    """Her brain works on its own thread: however long it takes, the world keeps its pace."""
    import time as _t

    a = academy(mind)
    a.publish("test")
    life = Life(mind, FakeLink())                 # threaded, as in the real World process
    life.maybe_load_brain()
    for _ in range(100):
        life.speaker.deliver()
        if life.brain is not None:
            break
        _t.sleep(0.05)
    assert life.brain is not None
    real = life.brain.generate

    def slow(*a, **k):
        _t.sleep(1.5)
        return real(*a, **k)

    life.brain.generate = slow
    life.next_thought = 0
    assert life.chat("Hello Ada", rid="r1") is None            # the reply comes later
    worst = 0.0
    end = _t.time() + 5
    while _t.time() < end:
        t = _t.perf_counter()
        life.step()
        life.speaker.deliver()
        worst = max(worst, _t.perf_counter() - t)
        _t.sleep(0.02)
    assert worst < 0.5, f"a world step took {worst:.2f}s"
    replies = [d for k, d in life.link.sent if k == "reply" and d["rid"] == "r1"]
    assert replies and "text" in replies[0]["result"]
    assert any(d.get("kind") == "intent" for k, d in life.link.sent)   # her needs decided while she searched for words


def test_the_oracle_leaves_gpu_memory_to_the_academy(tmp_path):
    from ada.hub import Hub

    seen = []

    class Fake(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path == "/api/ps":
                self._send({"models": [{"name": "tiny:1b", "size": 2 << 30, "size_vram": 2 << 30}]})
            else:
                self._send({"models": [{"name": "tiny:1b", "size": 1, "details": {}}]})

        def do_POST(self):
            seen.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            self._send({"message": {"content": "ok"}})

        def _send(self, d):
            b = json.dumps(d).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    cfg = AdaConfig(name="G", tokenizer="bytes")
    cfg.oracle.url = f"http://127.0.0.1:{srv.server_port}"
    hub = Hub(cfg, tmp_path)
    hub.oracle.refresh()
    hub.send = lambda *a, **k: None
    hub.phase = "night"                                   # the Academy studies
    hub.apply_schedule()
    hub.pool.shutdown(wait=True)                          # let the unload request finish
    assert hub.oracle.use_gpu is False
    assert ("/api/generate", {"model": "tiny:1b", "keep_alive": 0}) in seen
    hub.oracle.chat("system", "hello")
    assert seen[-1][1]["options"]["num_gpu"] == 0
    srv.shutdown()


def test_slow_training_on_a_fast_gpu_is_flagged():
    from ada.diag import findings

    academy_perf = {"timings": {}, "gauges": {"studying": 1, "device": "cuda", "gpu_test_tflops": 40.0,
                                              "training_tflops": 1.2, "gpu_free_mb": 300}}
    text = " ".join(f["text"] for f in findings({"academy": academy_perf}, [], None, {}))
    assert "1.2 of the 40 TFLOPS" in text and "spilling" in text
