"""Offline tests: no network, no Ollama, CPU only.  Run with:  python -m pytest tests"""
import sys
import time
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mind.brain import Mind  # noqa: E402
from mind.config import MindConfig  # noqa: E402
from mind.model import MindNet  # noqa: E402
from mind.tokenizer import ByteTokenizer  # noqa: E402
from mind.world import ACTIONS, World  # noqa: E402


def tiny_cfg(name="T") -> MindConfig:
    cfg = MindConfig(name=name, tokenizer="bytes")
    cfg.apply_preset("tiny")
    cfg.model.d_model, cfg.model.n_layers, cfg.model.n_heads, cfg.model.seq_len = 64, 2, 2, 64
    cfg.train.batch_size = 4
    cfg.data.fineweb_enabled = False
    cfg.teacher_enabled = False
    cfg.autosave_minutes = 0
    return cfg


def test_growth_preserves_function():
    cfg = tiny_cfg().model
    cfg.vocab_size = 320
    net = MindNet(cfg)
    for p in net.parameters():  # make the existing blocks non-trivial
        p.data.add_(torch.randn_like(p) * 0.02)
    x = torch.randint(0, 256, (2, 16))
    before = net(x)
    net.grow()
    assert len(net.blocks) == 3
    assert torch.allclose(before, net(x), atol=1e-5)


def test_chunked_loss_matches_full():
    cfg = tiny_cfg().model
    cfg.vocab_size = 320
    net = MindNet(cfg)
    x, y = torch.randint(0, 256, (3, 40)), torch.randint(0, 256, (3, 40))
    _, loss = net(x, y)
    full = torch.nn.functional.cross_entropy(net(x).reshape(-1, 320), y.reshape(-1))
    assert torch.allclose(loss, full, atol=1e-5)
    loss.backward()


def test_world_runs_every_action():
    w = World(seed=1)
    for i in range(400):
        r, narr, info = w.step(ACTIONS[i % len(ACTIONS)])
        assert isinstance(r, float) and narr
    assert "I " in w.observe()
    s = w.state()
    w2 = World(seed=2)
    w2.load_state(s)
    assert w2.observe() == w.observe()


def test_mind_learns_and_resumes(tmp_path):
    cfg = tiny_cfg()
    m = Mind(cfg, tmp_path, torch.device("cpu"))
    for _ in range(50):
        m.experience_pool.add("the cat sat on the mat. " * 4)
    first = None
    for _ in range(60):
        assert m.train_step()
        first = first or m.loss_ema
    assert m.loss_ema < first, "loss should fall on a repeated sentence"
    m.think()
    m.body_step()
    reply = m.chat("hello")
    assert "text" in reply and m.chat_log[-1]["role"] == "mind"
    assert m.probe("the cat")["next"]
    m.grow()
    m.save()
    m2 = Mind(MindConfig.load(m.dir / "config.json"), tmp_path, torch.device("cpu"))
    assert m2.step == m.step and m2.cfg.model.n_layers == 3
    assert len(m2.thoughts) == 1 and len(m2.experience_pool) == len(m.experience_pool)


def test_engine_thread_answers_commands(tmp_path):
    cfg = tiny_cfg("E")
    m = Mind(cfg, tmp_path, torch.device("cpu"))
    m.experience_pool.add("hello world " * 20)
    m.start()
    try:
        assert m.call("chat", "hi").result(timeout=60)["role"] == "mind"
        m.call("set", "thought_interval", 0.5).result(timeout=30)
        m.call("act", "east").result(timeout=30)
        m.call("place", "sign", 6, 6, "be kind").result(timeout=30)
        time.sleep(3)
        assert m.snapshot["step"] > 0 and m.thoughts
    finally:
        m.stop()


def test_byte_tokenizer_roundtrip():
    t = ByteTokenizer()
    s = "Hello, wörld! 🌷"
    assert t.decode(t.encode(s)) == s


def test_unstable_step_is_skipped_and_broken_weights_recover(tmp_path):
    cfg = tiny_cfg("N")
    m = Mind(cfg, tmp_path, torch.device("cpu"))
    m.experience_pool.add("a stable sentence to learn. " * 4)
    for _ in range(5):
        m.train_step()
    m.save()
    good = {k: v.clone() for k, v in m.model.state_dict().items()}

    # A step whose loss is NaN must not reach the weights.
    real = m.model.chunked_loss
    m.model.chunked_loss = lambda h, t: real(h, t) * float("nan")
    step = m.step
    assert m.train_step()
    assert m.step == step and m.skipped_steps == 1 and m._weights_finite()
    m.model.chunked_loss = real

    # Weights that went bad anyway are rolled back instead of saved, and resuming ignores them.
    with torch.no_grad():
        m.model.embed.weight[0, 0] = float("nan")
    assert m.save() == ""
    assert m._weights_finite()
    assert all(torch.equal(v, good[k]) for k, v in m.model.state_dict().items())


def test_broken_checkpoint_is_not_resumed(tmp_path):
    cfg = tiny_cfg("C")
    m = Mind(cfg, tmp_path, torch.device("cpu"))
    m.experience_pool.add("hello there. " * 10)
    m.train_step()
    m.save()
    m.train_step()
    m.save()  # state.prev.pt now holds the first good save
    s = torch.load(m.dir / "state.pt", weights_only=False)
    s["model"]["embed.weight"][:] = float("nan")
    torch.save(s, m.dir / "state.pt")
    m2 = Mind(MindConfig.load(m.dir / "config.json"), tmp_path, torch.device("cpu"))
    assert m2._weights_finite()


def test_server_never_sends_nan():
    from mind.server import clean
    out = clean({"a": float("nan"), "b": [1.0, float("inf")], "c": {"d": 2}})
    assert out == {"a": None, "b": [1.0, None], "c": {"d": 2}}
