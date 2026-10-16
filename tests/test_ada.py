"""Offline tests: CPU only, no FineWeb, no Ollama (a tiny fake one where needed).

    python -m pytest tests
"""
import json
import time
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
    life.cfg.oracle.enabled = False             # no language models here: the villagers use their scripted lines
    life.maybe_load_brain()
    assert life.brain_version == 1
    for _ in range(3000):                       # the valley is big: walk until the first deed is done
        life.step()
        if "did" in life.link.kinds():
            break
    kinds = life.link.kinds()
    assert "intent" in kinds and "did" in kinds
    r = life.chat("Hello Ada")
    assert "text" in r and life.chat_log[-1]["role"] == "mind"
    assert "T will" in life.suggest("go to the library")
    assert "Placed" in life.place("apple", 100, 46)
    assert "blocked" in life.place("apple", 100, 80)           # the lake
    assert "in the valley" in life.visitor("join")
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
    life.place("ball", 100, 46)
    life.save()
    again = Life(mind, FakeLink(), with_brain=False)
    assert (again.world.ada.x, again.world.ada.y) == (life.world.ada.x, life.world.ada.y)
    assert any(e["kind"] == "ball" and (e["x"], e["y"]) == (100, 46) for e in again.world.entities.values())


# ------------------------------------------------------------------ the Hub
def test_hub_never_imports_torch():
    code = "import sys; sys.path.insert(0, %r); import ada.hub, ada.web; print('torch' in sys.modules)" % str(ROOT)
    assert subprocess.run([sys.executable, "-c", code], capture_output=True, text=True).stdout.strip() == "False"


def test_hub_schedule_and_world_deltas(tmp_path):
    from ada.hub import Hub

    cfg = AdaConfig(name="H", tokenizer="bytes")
    cfg.oracle.enabled = False
    cfg.schedule.mode = "day_night"
    hub = Hub(cfg, tmp_path)
    sent = []
    hub.send = lambda child, cmd, rid=None, **a: sent.append((child, cmd, a))
    hub.phase = "day"
    hub.apply_schedule()
    assert sent[-1][:2] == ("academy", "pause")
    hub.on_message({"type": "phase", "phase": "night", "day": 1})
    assert sent[-1][:2] == ("academy", "resume")
    hub.set("schedule.mode", "together")                  # her brain is on the CPU: the GPU is all training's
    assert sent[-1][1] == "resume" and sent[-1][2]["intensity"] is None
    hub.set("world.device", "cuda")
    hub.set("schedule.mode", "day_night")
    hub.set("schedule.mode", "together")                  # sharing the GPU: train gently
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
    cfg.oracle.backend = "ollama"
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
    life.speaker.stop()


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
    cfg.oracle.backend = "ollama"
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
    assert seen[-1][1]["options"]["num_thread"] >= 1          # its share of the CPU's cores
    srv.shutdown()


def test_slow_training_on_a_fast_gpu_is_flagged():
    from ada.diag import findings

    academy_perf = {"timings": {}, "gauges": {"studying": 1, "device": "cuda", "gpu_test_tflops": 40.0,
                                              "training_tflops": 1.2, "gpu_free_mb": 300}}
    text = " ".join(f["text"] for f in findings({"academy": academy_perf}, [], None, {}))
    assert "1.2 of the 40 TFLOPS" in text and "spilling" in text


def test_fused_loss_matches_plain_cross_entropy():
    """The fused loss (gradients worked out in the forward pass) must give the same loss and
    gradients as ordinary cross-entropy over the full logits, ignored targets included."""
    import torch
    from ada.config import BrainConfig
    from ada.model import Brain
    torch.manual_seed(0)
    b = Brain(BrainConfig(vocab_size=300, d_model=32, n_layers=2, n_heads=4, seq_len=32))
    with torch.no_grad():
        for p in b.parameters():
            p.add_(torch.randn_like(p) * 0.05)
    x, y = torch.randint(0, 300, (3, 32)), torch.randint(0, 300, (3, 32))
    y[0, :7] = -1

    def run(fused):
        b.zero_grad()
        h = b.hidden(x)
        loss = (b.chunked_loss(h, y, chunk=40) if fused else
                torch.nn.functional.cross_entropy(b.logits(h.reshape(-1, 32)), y.reshape(-1), ignore_index=-1))
        (2 * loss).backward()
        return loss.item(), {n: p.grad.clone() for n, p in b.named_parameters()}

    (l1, g1), (l2, g2) = run(True), run(False)
    assert abs(l1 - l2) < 1e-5
    for n in g1:
        assert (g1[n] - g2[n]).norm() <= 1e-5 * (g2[n].norm() + 1e-8), n
    # Training's packed batches have no ignored targets and skip the masking pass: same result.
    y[0, :7] = 5
    b.zero_grad()
    b(x, y, masked=False).backward()
    g3 = {n: p.grad.clone() for n, p in b.named_parameters()}
    b.zero_grad()
    b(x, y).backward()
    for n, p in b.named_parameters():
        assert (g3[n] - p.grad).norm() <= 1e-6 * (p.grad.norm() + 1e-8), n


def test_muon_batched_step_matches_one_matrix_at_a_time():
    from ada.optim import Muon, _newton_schulz
    torch.manual_seed(0)
    ps = [torch.nn.Parameter(torch.randn(*s)) for s in [(24, 8), (24, 8), (8, 8), (8, 20)]]
    ref, bufs = [p.detach().clone() for p in ps], [torch.zeros_like(p) for p in ps]
    opt = Muon(ps, lr=0.02)
    for _ in range(2):
        gs = [torch.randn_like(p) for p in ps]
        for p, g in zip(ps, gs):
            p.grad = g.clone()
        opt.step()
        for r, g, buf in zip(ref, gs, bufs):
            buf.lerp_(g, 0.05)
            r.add_(_newton_schulz(g.lerp(buf, 0.95)), alpha=-0.02 * max(1, r.size(-2) / r.size(-1)) ** 0.5)
    assert max((p.detach() - r).abs().max().item() for p, r in zip(ps, ref)) < 1e-6


def test_old_minds_move_to_the_cpu_defaults(tmp_path):
    """Minds saved before config version 2 had 'auto' for her brain and the Oracle: they now run on
    the CPU, keeping the GPU for training. Settings changed by hand are left alone."""
    from ada.config import cpu_threads

    p = tmp_path / "config.json"
    old = AdaConfig().to_dict()
    old.pop("version")
    old["world"]["device"], old["oracle"]["placement"], old["schedule"]["mode"] = "auto", "gpu", "day_night"
    p.write_text(json.dumps(old), encoding="utf-8")
    cfg = AdaConfig.load(p)
    assert cfg.version == 2 and cfg.world.device == "cpu" and cfg.oracle.placement == "gpu"
    assert cfg.oracle.backend == "builtin" and cfg.schedule.mode == "together"
    t = cpu_threads(cfg)
    assert t["world"] >= 1 and t["oracle"] >= 1 and t["world"] + t["oracle"] <= max(2, t["cores"])
    cfg.world.cpu_threads, cfg.oracle.cpu_threads = 3, 5
    assert (cpu_threads(cfg)["world"], cpu_threads(cfg)["oracle"]) == (3, 5)


def test_builtin_oracle_talks_to_a_llama_server(tmp_path):
    from ada.localllm import LocalLLM, platform_asset
    from ada.oracle import Oracle

    seen = []

    class Fake(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            seen.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            b = json.dumps({"choices": [{"message": {"content": '{"lesson": "Owls hunt at night.", "qa": [], "facts": []}'}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    local = LocalLLM(tmp_path)
    o = Oracle("http://localhost:1", "", local)
    o.backend = "builtin"
    assert not o.ready
    with pytest.raises(RuntimeError):
        o.chat("system", "hi")
    local.status, local.url, local.model_key = "ready", f"http://127.0.0.1:{srv.server_port}", "gemma-2-2b"
    local.proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert o.ready and o.active == "Gemma 2 2B Instruct (built-in)"
        pack = o.lesson_pack("owls", 2)
        assert pack["lesson"] == "Owls hunt at night."
        path, body = seen[-1]
        assert path == "/v1/chat/completions" and body["response_format"] == {"type": "json_object"}
        assert [m["role"] for m in body["messages"]] == ["user"]          # no system role for Gemma
        assert body["messages"][0]["content"].startswith("You are the Oracle")
    finally:
        local.proc.kill()
        srv.shutdown()
    assert platform_asset() is not None


def test_builtin_oracle_skips_releases_still_uploading(tmp_path, monkeypatch):
    """llama.cpp's newest release often has no files yet: use the newest one that has ours."""
    import ada.localllm as ll

    class Fake(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            suffix = ll.platform_asset()
            rels = [{"tag_name": "b3", "assets": []},
                    {"tag_name": "b2", "assets": [{"name": f"llama-b2-{suffix}", "browser_download_url": "http://x/b2"}]},
                    {"tag_name": "b1", "assets": [{"name": f"llama-b1-{suffix}", "browser_download_url": "http://x/b1"}]}]
            b = json.dumps(rels).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(ll, "RELEASES", f"http://127.0.0.1:{srv.server_port}/releases")
    try:
        assert ll.LocalLLM(tmp_path)._find_release(ll.platform_asset()) == ("b2", "http://x/b2")
    finally:
        srv.shutdown()


# ------------------------------------------------------------------ the bigger valley
def _do(life, verb, obj="", extra="", ticks=3000):
    """Have the synth carry out one goal (walking there) and return what happened."""
    goal = ag.Goal(verb, obj, extra, text=ag.say(ag.Goal(verb, obj, extra)), source="you")
    assert life.set_plan(goal), (verb, obj, life.world.log[-1:])
    for _ in range(ticks):
        if not life.plan:
            break
        life.walk()
    did = [d for t, d in life.link.sent if d.get("kind") == "did"]
    return did[-1] if did else {}


def _hold(w, *kinds):
    for k in kinds:
        w.ada.carrying.append({"id": w.next_id, "kind": k, "x": 0, "y": 0})
        w.next_id += 1


def test_valley_activities_fish_mine_craft_trade_cook(mind):
    life = Life(mind, FakeLink(), with_brain=False)
    w = life.world
    w.rng.seed(1)
    assert w.anchors["mine"] and w.anchors["dock"] and w.anchors["market"]
    _hold(w, "wood", "wood")
    assert "fishing rod" in _do(life, "make", "fishing rod")["text"]
    assert any(e["kind"] == "fishing rod" for e in w.ada.carrying)
    for _ in range(6):                                            # fish until something bites
        _do(life, "fish")
        if any(e["kind"] == "raw fish" for e in w.ada.carrying):
            break
    assert any(e["kind"] == "raw fish" for e in w.ada.carrying)
    assert "grilled fish" in _do(life, "cook", "raw fish")["text"]
    coins = w.coins
    assert "Juniper buys" in _do(life, "sell", "grilled fish")["text"] and w.coins > coins
    _do(life, "take", "pickaxe")
    assert "Clang" in _do(life, "mine", "ore")["text"]
    assert any(e["kind"] == "ore" for e in w.ada.carrying)
    w.coins = 20
    assert "kite" in _do(life, "buy", "kite")["text"] and w.coins == 12


def _run_talks(life, replies, steps=80):
    """Drive conversations: answer each 'turn' request in order, skipping the waits."""
    answered, said = set(), []
    for _ in range(steps):
        life.talk_step()
        for t, d in list(life.link.sent):
            if t == "oracle" and d["purpose"] == "turn" and d["rid"] not in answered:
                answered.add(d["rid"])
                line = replies.pop(0) if replies else "Goodbye!"
                said.append((d["payload"]["speaker"], line))
                life.oracle_reply(d["rid"], line)
        for talk in life.talks.values():
            if talk.state == "speaking":
                talk.until = 0
        if not life.talks:
            break
    return said


def test_quests_friendship_and_a_conversation(mind):
    life = Life(mind, FakeLink(), with_brain=False)
    w = life.world
    w.quests.append({"id": 99, "giver": "Mira", "want": "wheat", "count": 1, "got": 0, "reward": 5,
                     "text": "Mira needs some wheat.", "day": 1})
    before, coins = w.friends["Mira"], w.coins
    _hold(w, "wheat")
    assert "Quest done" in _do(life, "give", "wheat", "Mira")["text"]
    assert w.coins == coins + 5 and w.friends["Mira"] > before and not w.quests
    assert w.people["Mira"].friends["T"] > 10                    # friendship grows both ways
    # Mira has something to say: she starts a conversation, and the synth waits for her line
    talk = next(iter(life.talks.values()))
    assert talk.members == ["Mira", "T"] and w.ada.engaged == talk.id and w.people["Mira"].engaged == talk.id
    said = _run_talks(life, ["Thank you, little one! Here are your coins."])
    assert said[0] == ("Mira", "Thank you, little one! Here are your coins.")
    assert w.ada.engaged is None and w.people["Mira"].engaged is None
    lines = [json.loads(x) for x in (mind / "journal.jsonl").read_text().splitlines()]
    assert any(any(r == "<|npc|>" and t.startswith("Mira: Thank you") for r, t in x["parts"]) for x in lines)


def test_villagers_talk_in_turns_and_you_can_walk_freely(mind):
    life = Life(mind, FakeLink(), with_brain=False)
    w = life.world
    m, th = w.people["Mira"], w.people["Theo"]
    th.x, th.y = m.x + 3, m.y
    w.ada.x, w.ada.y = m.x, m.y + 2
    assert life.start_talk("Mira", "Theo", "the weather", turns=2)
    talk = next(iter(life.talks.values()))
    for _ in range(10):                                         # Mira walks up to Theo first
        life.talk_step()
        if talk.state == "waiting":
            break
    assert abs(m.x - th.x) + abs(m.y - th.y) <= 1
    assert m.said == "…"                                        # composing: Theo waits
    turns = [d for t, d in life.link.sent if t == "oracle" and d["purpose"] == "turn"]
    assert len(turns) == 1 and turns[0]["payload"]["speaker"] == "Mira" and turns[0]["payload"]["opening"]
    said = _run_talks(life, ["Lovely day, Theo!", "Perfect for reading. Goodbye!"])
    assert said == [("Mira", "Lovely day, Theo!"), ("Theo", "Perfect for reading. Goodbye!")]
    second = [d for t, d in life.link.sent if t == "oracle" and d["purpose"] == "turn"][1]["payload"]
    assert second["history"] == [["Mira", "Lovely day, Theo!"]] or second["history"] == [("Mira", "Lovely day, Theo!")]
    lines = [json.loads(x) for x in (mind / "journal.jsonl").read_text().splitlines()]
    assert any(x["kind"] == "overheard" for x in lines)          # the synth was close enough to hear
    # villagers are minds too: they decide, act and keep a diary
    for _ in range(200):
        life.community_step()
    assert any(st.diary for st in life.vminds.values())
    view = {m["name"]: m for m in life.minds_view()}
    assert set(view) == {"T", *w.people} and "needs" in view["Mira"] and "doing" in view["Mira"]
    life.visitor("join")
    v = w.visitor
    life.visitor("pos", msg={"fx": v.x + 0.6, "fy": v.y, "facing": "east"})
    assert v.facing == "east"
    x0 = v.x
    life.visitor("pos", msg={"fx": 100, "fy": 80})                   # the middle of the lake: you can't walk on water
    assert v.x == x0
    assert life.visitor("interact", msg={"target": {"kind": "person", "name": "Mira"}}) == {"talk_to": "Mira"}


def test_minds_make_lasting_art(mind):
    life = Life(mind, FakeLink(), with_brain=False)
    w = life.world
    assert "paint" in _do(life, "paint", "easel")["text"]
    _hold(w, "chisel", "stone")
    assert "sculpture" in _do(life, "sculpt", "stone")["text"]
    _hold(w, "hammer", "wood", "wood")
    assert "bench" in _do(life, "build", "bench")["text"]
    assert "melody" in _do(life, "compose", "piano")["text"]
    kinds = [c["kind"] for c in w.creations]
    assert kinds == ["painting", "sculpture", "building", "music"]
    music = w.creations[-1]["data"]
    assert music["notes"] and all(len(n) == 2 for n in music["notes"])
    statue = next(e for e in w.entities.values() if e["kind"] == "sculpture")
    assert statue["work"] == w.creations[1]["id"]
    life.save()
    again = Life(mind, FakeLink(), with_brain=False)               # the gallery lasts
    assert [c["kind"] for c in again.world.creations] == kinds
    assert any(e["kind"] == "bench" and e.get("built_by") == "T" for e in again.world.entities.values())


def test_fineweb32k_tokenizer_round_trips():
    from ada.tokenizer import make_tokenizer

    tok = make_tokenizer("fineweb32k")
    assert tok.vocab_size == 32768 and tok.n_real == 32768
    s = "Zen floats to the bakery. \"Hello, Mira!\" 1234 café 😀\n"
    assert tok.decode(tok.encode(s)) == s
    assert tok.token_str(tok["<|npc|>"]) == "<|npc|>"
    assert len(tok.encode("The villagers in the valley are learning together.")) <= 10


def test_journey_records_each_first_once(tmp_path):
    from ada.journey import Journey

    j = Journey(tmp_path, "Zen")
    assert j.observe({"kind": "thought", "text": "blorp xq zzt"}) == []
    got = j.observe({"kind": "thought", "text": "the sun warm"})
    assert [m["key"] for m in got] == ["first_word", "first_phrase"]
    assert j.observe({"kind": "chat", "text": "I want bread"})[0]["key"] == "first_sentence"
    assert j.observe({"kind": "thought", "text": "the sun"}) == []                 # only the first time
    assert j.observe({"kind": "talk", "members": ["Mira", "Zen"], "topic": "bread"})[0]["key"] == "first_conversation"
    assert Journey(tmp_path, "Zen").done == j.done                                # kept on disk
