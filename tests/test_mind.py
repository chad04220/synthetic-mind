"""v5: the mind decides through a (fake) llama-server, judges itself, and learns from what it judged."""
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ada.agent import practice  # noqa: E402
from ada.agent.mind import Mind, action_end, schema  # noqa: E402

SKILLS = {"go_to": {"doc": "Walk somewhere.", "args": {"x": "int", "y": "int", "z": "int"}, "example": {"x": 1, "y": 64, "z": 2}},
          "mine_nearest": {"doc": "Mine the nearest blocks of a kind.", "args": {"block": "block name", "count": "int"},
                           "example": {"block": "oak_log", "count": 3}}}


class FakeLlama:
    """A stand-in for llama-server: streams the replies it is given, and remembers the requests."""

    def __init__(self):
        self.replies, self.requests = [], []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append(body)
                text = outer.replies.pop(0) if outer.replies else "{}"
                if body.get("stream"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    for i in range(0, len(text), 7):
                        piece = {"choices": [{"delta": {"content": text[i:i + 7]}}]}
                        self.wfile.write(f"data: {json.dumps(piece)}\n\n".encode())
                        self.wfile.flush()
                        time.sleep(0.002)
                    last = {"choices": [{"delta": {}}], "timings": {"prompt_ms": 12.0, "predicted_ms": 80.0, "cache_n": 900,
                                                                     "predicted_n": 40}}
                    self.wfile.write(f"data: {json.dumps(last)}\n\ndata: [DONE]\n\n".encode())
                else:
                    out = json.dumps({"choices": [{"message": {"content": text}}], "timings": {}}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(out)))
                    self.end_headers()
                    self.wfile.write(out)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


@pytest.fixture
def llama():
    f = FakeLlama()
    yield f
    f.server.shutdown()


def reply(skill="mine_nearest", args=None, thought="Logs nearby.", say=None, note=None, goal=None):
    return json.dumps({"thought": thought, "action": {"skill": skill, "args": args or {"block": "oak_log", "count": 3}},
                       "say": say, "note": note, "goal": goal})


def decide(mind, llama, text, perceived="Day 1, 08:00. Oak logs ×6 at 4 east."):
    llama.replies.append(text)
    got = []
    rec = mind.think(perceived, mind.due(time.time() + 100, False) or "test", lambda r, a: got.append(a))
    kind, rec2, res = mind.inbox.get(timeout=10)
    assert kind == "decided" and rec2 is rec
    return mind.finish(rec, res), got


def test_the_action_is_known_before_the_reply_is_finished():
    text = '{"thought": "a {brace} \\" in a string", "action": {"skill": "go_to", "args": {"x": 1, "y": {"a": 2}}}, "say": null'
    end = action_end(text)
    assert text[:end].endswith('{"a": 2}}}') and action_end('{"thought": "x", "action": {"skill": "go') is None
    s = schema(["go_to", "reflect"])
    assert s["properties"]["action"]["properties"]["skill"]["enum"] == ["go_to", "reflect"]
    assert s["required"][:2] == ["thought", "action"]


def test_it_decides_through_its_model_and_remembers(tmp_path, llama):
    m = Mind(tmp_path, "Zen", SKILLS)
    m.url = llama.url
    m.hear("Chad", "Hello Zen! Can you get some wood?")
    assert m.due(time.time(), True) == "someone spoke to you"
    rec, got = decide(m, llama, reply(say="Hello! On my way.", note="Chad likes wood.", goal="Gather wood"))
    assert got == [{"skill": "mine_nearest", "args": {"block": "oak_log", "count": 3}}]     # streamed early
    assert rec["say"] == "Hello! On my way." and m.goal == "Gather wood" and m.notes == ["Chad likes wood."]
    req = llama.requests[-1]
    assert req["messages"][0]["content"] == m.system and "json_schema" in req["response_format"]["type"]
    assert "Chad: Hello Zen!" in req["messages"][1]["content"] and "Why you are thinking now: someone spoke" in req["messages"][1]["content"]
    assert rec["ms"]["action_ms"] is not None and rec["ms"]["cached"] == 900
    m.outcome(rec, True, "I mined 3 oak logs.")
    row = json.loads((tmp_path / "decisions.jsonl").read_text().splitlines()[-1])
    assert row["outcome"]["ok"] and row["obs"] == req["messages"][1]["content"] and row["reply"]
    assert (tmp_path / "prompts" / f"{row['sys']}.txt").read_text() == m.system
    # memory survives a restart
    m.save()
    again = Mind(tmp_path, "Zen", SKILLS)
    assert again.goal == "Gather wood" and again.notes == ["Chad likes wood."] and list(again.convo)[-1] == ("you", "Hello! On my way.")


def test_it_knows_it_can_learn_and_judges_itself(tmp_path, llama):
    m = Mind(tmp_path, "Zen", SKILLS)
    m.url = llama.url
    assert "reflect" in m.skills and "practice" in m.skills and "train your model" in m.system
    recs = []
    for i in range(6):
        rec, _ = decide(m, llama, reply(skill="go_to", args={"x": i, "y": 64, "z": 0}))
        m.outcome(rec, i % 2 == 0, "arrived" if i % 2 == 0 else "I can't reach that.")
        recs.append(rec)
    m.judge(recs[1]["id"], "visitor", value=-1, correction="mine the logs first")
    assert "practised 0 times" in m.memory_text() and "I haven't enough new experience" in m.practice_need()
    llama.replies.append(json.dumps({"judgements": [
        {"n": 2, "verdict": "bad", "better": {"skill": "mine_nearest", "args": {"block": "oak_log", "count": 3}}, "why": "Wood first."},
        {"n": 1, "verdict": "good", "better": None, "why": "It worked."}], "lessons": ["Gather wood before wandering."]}))
    done = threading.Event()
    assert m.reflect(done.set) is None and m.busy_with == "reflecting"
    kind, todo, text = m.inbox.get(timeout=10)
    req = llama.requests[-1]["messages"][1]["content"]
    assert kind == "reflected" and "Your visitor said about it: mine the logs first" in req
    said = m.reflected(todo, text)
    assert "1 good, 1 bad, 1 with a better choice" in said and m.lessons[-1]["text"] == "Gather wood before wandering."
    assert recs[1]["self"]["better"]["skill"] == "mine_nearest" and m.learning["good"] == 1 and m.learning["bad"] == 2
    js = [json.loads(x) for x in (tmp_path / "judgements.jsonl").read_text().splitlines()]
    assert {j["by"] for j in js} == {"visitor", "self"}


def test_practice_learns_from_the_good_and_the_corrected(tmp_path, llama):
    m = Mind(tmp_path, "Zen", SKILLS)
    m.url = llama.url
    ids = []
    for i in range(12):
        rec, _ = decide(m, llama, reply(skill="go_to" if i % 3 else "mine_nearest", args={"x": i, "y": 1, "z": 1}))
        m.outcome(rec, i % 4 != 1, "ok" if i % 4 != 1 else "I can't reach that.")
        ids.append(rec["id"])
    m.judge(ids[1], "self", value=-1, better={"skill": "mine_nearest", "args": {"block": "stone", "count": 1}}, why="Closer.")
    m.judge(ids[2], "visitor", value=1)
    m.judge(ids[3], "visitor", value=-1)          # worked, but you didn't like it, and there's no better action: out
    exs, counts = practice.examples(tmp_path, seed=1)
    by = {e["id"]: e for e in exs}
    assert ids[3] not in by and ids[5] not in by          # judged bad / failed without a correction
    assert json.loads(by[ids[1]]["reply"])["action"] == {"skill": "mine_nearest", "args": {"block": "stone", "count": 1}}
    assert by[ids[2]]["weight"] == 2.0 and counts["corrected"] == 1 and counts["liked"] == 1
    assert all(e["system"] == m.system and e["prompt"].startswith("Your learning") for e in exs)
    assert max(sum(e["skill"] == s for e in exs) for s in ("go_to", "mine_nearest")) <= max(8, len(exs) // 3 + 1)


def test_an_adapter_is_written_for_llama_cpp(tmp_path):
    torch = pytest.importorskip("torch")
    gguf = pytest.importorskip("gguf")
    w = {}
    for layer in range(2):
        for proj, (o, i) in {"q_proj": (8, 8), "k_proj": (4, 8), "down_proj": (8, 16)}.items():
            n = f"model.layers.{layer}.{'mlp' if proj == 'down_proj' else 'self_attn'}.{proj}"
            w[n + ".A"], w[n + ".B"] = torch.randn(2, i), torch.randn(o, 2)
    torch.save(w, tmp_path / "p1.pt")
    out = practice.export_gguf(tmp_path / "p1.pt", tmp_path / "p1.gguf", "llama", 4.0, n_head=2, n_kv=1)
    r = gguf.GGUFReader(str(out))
    names = {t.name: t for t in r.tensors}
    assert "blk.1.attn_k.weight.lora_b" in names and "blk.0.ffn_down.weight.lora_a" in names
    assert list(names["blk.0.ffn_down.weight.lora_a"].shape) == [16, 2]          # ggml order: (in, r)
    assert list(names["blk.0.attn_q.weight.lora_b"].shape) == [2, 8]             # (r, out)
    kv = {f.name: f for f in r.fields.values()}
    assert "adapter.lora.alpha" in kv and bytes(kv["general.type"].parts[-1]).decode() == "adapter"
    # Llama's q/k rows are reordered the way llama.cpp's converter does it; the other projections are not
    b = w["model.layers.0.self_attn.q_proj.B"].numpy()
    assert (practice.permute(b, 2)[[0, 2, 1, 3, 4, 6, 5, 7]] == b).all()


def test_a_practice_round_that_made_it_worse_is_undone(tmp_path):
    m = Mind(tmp_path, "Zen", SKILLS)
    for i in range(60):
        rec = {"id": f"x{i}", "t": i, "adapter": None, "action": {"skill": "go_to"}, "obs": ""}
        m.recent.append(rec)
        rec["outcome"] = {"ok": i % 4 != 0, "text": ""}                     # 75% worked before
    say = m.practised("p1", {"examples": 50, "loss": 0.4})
    assert "p1" in say and m.learning["adapter"] == "p1" and m.learning["practices"] == 1
    for i in range(30):
        m.recent.append({"id": f"y{i}", "t": 100 + i, "adapter": "p1", "action": {"skill": "go_to"}, "obs": "",
                         "outcome": {"ok": i % 2 == 0, "text": ""}})         # 50% after
    back = m.check_practice()
    assert back and back["rollback_to"] is None and m.learning["adapter"] is None and "made me worse" in back["text"]
    assert m.check_practice() is None                                          # judged once


def test_a_decision_whose_action_ends_before_its_reply_is_still_logged_whole(tmp_path, llama):
    m = Mind(tmp_path, "Zen", SKILLS)
    m.url = llama.url
    llama.replies.append(reply(skill="go_to", args={"x": 1, "y": 2, "z": 3}))
    got = []
    rec = m.think("Here.", "test", lambda r, a: got.append(r))
    kind, _, res = m.inbox.get(timeout=10)
    assert got and got[0] is rec
    m.outcome(rec, True, "Arrived at once.")           # the body was quicker than the rest of the reply
    assert not (tmp_path / "decisions.jsonl").exists()
    m.finish(rec, res)
    row = json.loads((tmp_path / "decisions.jsonl").read_text().splitlines()[-1])
    assert row["reply"] and row["outcome"]["text"] == "Arrived at once." and row["thought"] == "Logs nearby."
    assert len(practice.examples(tmp_path)[0]) == 1
