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
NAMES = {"wren": "Wren", "zen": "Zen"}


@pytest.mark.parametrize("text,verb,obj,extra", [
    ("I eat the apple.", "eat", "apple", ""), ("I go and bake bread", "bake", "bread", ""),
    ("I water the plants", "water", "plant", ""), ("I drink water", "drink", "water", ""),
    ("I talk to wren", "talk", "Wren", ""), ("I look at the stars", "look", "telescope", ""),
    ("I go to the kitchen.", "go", "kitchen", ""), ("I give the apple to my friend", "give", "apple", "friend"),
    ("I put the log in the fireplace.", "put", "log", "fireplace"), ("I take an egg from the nest box", "take", "egg", "nest box"),
    ("I feed the cat.", "feed", "cat", ""), ("I make a cup of tea", "brew", "tea", ""), ("I cook soup", "cook", "soup", ""),
])
def _live(w, me, goal, ticks=3000):
    """Carry out one goal and everything it needs first, the way the World does. Returns the steps."""
    p, why = ag.plan(w, goal, me)
    assert p, why
    steps = []
    for _ in range(ticks):
        w.advance(0.25)
        w.update_needs(0.25)
        p.ticks += 1
        tp = ag.target_pos(w, p)
        if p.target is not None and tp is None:
            steps.append((False, "gone"))
            return steps
        if tp is not None:
            tx, ty, adj = tp
            there = (abs(tx - me.x) + abs(ty - me.y) == 1) if adj else (me.x, me.y) == (tx, ty)
            if not (there or adj and (me.x, me.y) == (tx, ty)):
                if not p.route:
                    p.route = w.path((me.x, me.y), (tx, ty), me=me, adjacent=adj) or \
                        w.path((me.x, me.y), (tx, ty), me=me, adjacent=adj, avoid=False) or []
                    if not p.route:
                        steps.append((False, "no way"))
                        return steps
                me.x, me.y = p.route.pop(0)
                continue
        r = ag.act(w, p, me)
        if r is None:
            continue
        ok, narration, _ = r
        steps.append((ok, narration))
        if not ok or not p.then:
            return steps
        nxt, rest = p.then[0], p.then[1:]
        p, why = ag.plan(w, nxt, me)
        assert p, why
        p.then += rest
    return steps


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
    full = w.snapshot(full=True)
    hub.on_message({"type": "world", "snap": full})
    seq0 = hub.world_seq
    apple = {"id": 999001, "kind": "apple", "x": 3, "y": 2}
    hub.on_message({"type": "world", "snap": {"ents": [apple], "removed": [], "day": 1}})
    hub.on_message({"type": "world", "snap": {"ents": [{"id": 999002, "kind": "ball", "x": 4, "y": 2}],
                                              "removed": [999001], "day": 2}})
    _, d = hub.world_delta(seq0)
    assert [x["kind"] for x in d["ents"]] == ["ball"] and 999001 in d["removed"] and d["day"] == 2
    assert hub.world_full()["full"] and len(hub.world_full()["ents"]) == len(full["ents"]) + 1


def test_world_happenings_reach_the_page(tmp_path):
    from ada.hub import Hub

    cfg = AdaConfig(name="H2", tokenizer="bytes")
    cfg.oracle.enabled = False
    hub = Hub(cfg, tmp_path)
    w = World(seed=1)
    snap = w.snapshot(full=True)
    snap["happenings"] = [{"kind": "fire_out", "text": "The fire burns out.", "what": "stove", "t": 1.0}]
    hub.on_message({"type": "world", "snap": snap})          # a key named like ours must not break the merge
    ev = hub.feeds["happening"][-1]
    assert ev["what"] == "fire_out" and ev["text"] == "The fire burns out." and hub.world_state


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
    assert cfg.version == 4 and cfg.world.device == "cpu" and cfg.oracle.placement == "gpu"
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
        from ada.sprite import SpriteVoice

        answer = SpriteVoice(o).answer("Why do owls hoot at night?", "A wood at night. An owl sits on a branch.", 2)
        assert "Owls hunt at night." in answer
        path, body = seen[-1]
        assert path == "/v1/chat/completions" and "response_format" not in body
        assert [m["role"] for m in body["messages"]] == ["user"]          # no system role for Gemma
        content = body["messages"][0]["content"]
        assert content.startswith("You are the Sprite of All Knowing") and "An owl sits on a branch." in content
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


# ------------------------------------------------------------------ Wren and Zen
def _wren_life(mind, steps=0, voice=False):
    life = Life(mind, FakeLink(), with_brain=False, threaded=False)
    life.voice_ready = voice
    for _ in range(steps):
        life.step()
    return life


def test_fineweb32k_tokenizer_round_trips():
    from ada.tokenizer import make_tokenizer

    tok = make_tokenizer("fineweb32k")
    assert tok.vocab_size == 32768 and tok.n_real == 32768
    s = "Zen floats to the bakery. \"Hello, Mira!\" 1234 café 😀\n"
    assert tok.decode(tok.encode(s)) == s
    assert tok.token_str(tok["<|act|>"]) == "<|act|>" and tok["<|npc|>"] == tok["<|act|>"]   # v3's name still works
    assert len(tok.encode("The villagers in the valley are learning together.")) <= 10


def test_journey_records_each_first_once(tmp_path):
    from ada.journey import Journey

    j = Journey(tmp_path, "Zen")
    assert j.observe({"kind": "thought", "text": "blorp xq zzt"}) == []
    got = j.observe({"kind": "thought", "text": "the sun warm"})
    assert [m["key"] for m in got] == ["first_word", "first_phrase"]
    assert j.observe({"kind": "chat", "text": "I want bread"})[0]["key"] == "first_sentence"
    assert j.observe({"kind": "thought", "text": "the sun"}) == []                 # only the first time
    assert j.observe({"kind": "did", "action": "eat", "ok": True, "text": "I eat the berries."})[0]["key"] == "first_eat"
    assert j.observe({"kind": "did", "action": "drink", "ok": False, "text": "There is no water."}) == []
    assert Journey(tmp_path, "Zen").done == j.done                                # kept on disk


def test_settings_show_the_tokenizers_vocabulary():
    from ada.config import TOKENIZER_VOCAB, AdaConfig
    from ada.tokenizer import make_tokenizer
    for name, size in TOKENIZER_VOCAB.items():
        assert make_tokenizer(name).vocab_size == size
        assert AdaConfig(tokenizer=name).to_dict()["brain"]["vocab_size"] == size


# ---------------------------------------------------------------------------------------------- art v2
def test_composers_grow_with_skill():
    from ada.world import art

    rng = random.Random(3)
    plan = art.words_to_plan("I paint the moon over the pond.", "garden", "noon", "summer", "clear", "calm")
    assert "moon" in plan["elements"] and plan["place"] == "pond" and plan["time"] == "night"
    assert plan["subject"] == "the moon over the pond"
    rough, fine = art.compose_painting(rng, plan, 0.1), art.compose_painting(rng, plan, 0.95)
    assert rough["style"] == "naive" and rough["layers"] and fine["objects"]
    assert any(o["type"] == "moon" for o in fine["objects"])
    hum, song = art.compose_music(rng, {"mood": "calm"}, 0.1), art.compose_music(rng, {"mood": "calm"}, 0.9)
    assert hum["form"] == ["A"] and len(song["form"]) >= 3
    assert all(-2 <= d <= 9 for sec in song["sections"].values() for d, _ in sec["melody"])
    lump, owl = art.compose_sculpture(rng, {"subject": "owl"}, 0.1), art.compose_sculpture(rng, {"subject": "owl"}, 0.9)
    assert lump["finish"] == "rough" and owl["finish"] == "polished" and len(owl["parts"]) >= len(lump["parts"])
    for kind, d in (("painting", fine), ("music", song), ("sculpture", owl)):
        json.dumps(d)
        assert art.describe(kind, d)
    assert art.effective_skill(0.0, "synth", 0) < art.effective_skill(0.5, "synth", 0) < art.effective_skill(0.5, "synth", 6)
    assert art.effective_skill(0.0, "companion") >= 0.6 and art.grow(0.5, "work") > art.grow(0.5, "admire") > 0.5

