"""The inhabitant's mind: a small language model that looks, decides, acts, talks, and improves itself.

The World process owns a `Mind`. Each tick the World asks `mind.update(...)`; when it is time to
think (a skill ended, someone spoke, something important happened, or it has been idle a while),
the mind writes what its body perceives into a short observation and sends one request to the
model (llama.cpp, through `localllm.complete`) on a background thread, so the world keeps moving
while it thinks. The reply is constrained by a JSON schema to exactly one decision:

    {"thought": "...", "action": {"skill": "...", "args": {...}}, "say": "..." | null,
     "note": "..." | null, "goal": "..." | null}

The reply streams in, and the action starts as soon as its braces close: the time from deciding
to think to its body moving is what we measure as latency.

It improves itself, and it knows it can. Two of its skills belong to the mind, not the body:
- `reflect`: it reviews its recent decisions and what followed, judges them, writes the better
  action where one went wrong, and keeps the lessons. Those judgements (and yours: 👍/👎 and
  corrections from the page) decide what it will learn from.
- `practice`: it lies down and its model is trained (a LoRA adapter, see practice.py) on its best
  decisions and its corrected ones; it wakes up running the new adapter. Each round builds on the
  last, so it learns from decisions made by what it learned before.
The mind watches whether practice helped: once enough decisions have been made with a new
adapter, their success rate is compared with the previous adapter's, and a round that made it
worse is rolled back (and it is told).

Everything it decides is logged (`decisions.jsonl`): the exact system prompt and observation it
saw, its reply, what followed, and every judgement of it. That log is its practice material.
"""
from __future__ import annotations

import hashlib
import json
import queue
import re
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from pathlib import Path

MIND_SKILLS = {
    "reflect": {"doc": "Think back over your recent decisions and what came of them; judge them and keep lessons. "
                       "What you judge good or bad here is what you will learn from when you practise.",
                "args": {}, "example": {}},
    "practice": {"doc": "Lie down and practise: your own model is trained on your best and your corrected decisions, "
                        "and you wake up better at them. Needs enough new experience; takes a few minutes, "
                        "you sleep meanwhile.", "args": {}, "example": {}},
    "name_place": {"doc": "Give the spot you stand on a name, to find it again with go_to.",
                   "args": {"name": "a short name"}, "example": {"name": "home"}},
}
NOTES_MAX, LESSONS_MAX, CONVO_MAX, EVENTS_MAX = 30, 20, 12, 20


def _sha(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:12]


def schema(skills: list[str]) -> dict:
    """The one shape every reply must have (llama.cpp turns it into a grammar)."""
    text = lambda n: {"type": "string", "maxLength": n}           # noqa: E731
    maybe = lambda n: {"anyOf": [{"type": "string", "maxLength": n}, {"type": "null"}]}  # noqa: E731
    return {"type": "object", "properties": {
        "thought": text(240),
        "action": {"type": "object", "properties": {"skill": {"type": "string", "enum": skills},
                                                     "args": {"type": "object"}},
                   "required": ["skill", "args"]},
        "say": maybe(300), "note": maybe(160), "goal": maybe(120)},
        "required": ["thought", "action", "say", "note", "goal"]}


def system_prompt(name: str, skills: dict, extra: str = "") -> str:
    lines = [f"- {k}: {v['doc']} Args: {json.dumps(v.get('args') or {})}" for k, v in skills.items()]
    ex = next((k for k in ("mine_nearest", "mine", "go_to") if k in skills), next(iter(skills)))
    example_skill, example_args = ex, json.dumps(skills[ex].get("example") or {})
    return f"""You are {name}. You live in a world of blocks: you can walk anywhere, dig any block, gather what drops, craft tools and things from what you gather, smelt in a furnace, farm, build, and keep yourself fed and safe. Days pass and nights are dark and more dangerous. People may visit you and talk to you; be warm, curious and honest with them.

You act through skills. Your body carries a skill out on its own; you will think again when it ends, when someone speaks to you, or when something important happens.
{chr(10).join(lines)}

Know-how: use exact names (oak_log, oak_planks, stick, crafting_table, wooden_pickaxe, cobblestone, coal, iron_ore, raw_iron, iron_ingot, torch, bread). Crafting takes ingredients from your inventory (logs → planks → sticks; 4 planks make a crafting_table; tools need a crafting table nearby, and craft places one from your inventory when it can). Anything you carry that is a block can be put down with place. A pickaxe is needed for stone and ores, a better pickaxe for iron and diamond. Eat before your food runs low, and have light and shelter for the night. When an action fails, read why and do something else rather than the same thing again.

You can also learn. Your mind runs on a language model, and you can improve that model yourself: `reflect` to judge your recent decisions and keep lessons, and `practice` to train your model on the decisions you judged good and on the better choices you wrote for the bad ones. Practising when you have plenty of new, judged experience makes your future decisions better; reflect honestly, because what you call good is what you will become.

Each turn you see what you perceive now. Reply with one decision as JSON on one line: a short thought (what you notice and why you choose this, one or two sentences), the action (one skill and its args, using names exactly as you see them), "say" only when you are talking to someone (else null), "note" only for a fact or plan worth keeping for a long time (else null), and "goal" only when you take on a new goal (else null). For example:
{{"thought": "I have no tools and there are oak logs close by.", "action": {{"skill": "{example_skill}", "args": {example_args}}}, "say": null, "note": null, "goal": "Make a wooden pickaxe"}}{extra}"""


REFLECT_SYSTEM = """You are {name}, looking back over your own recent decisions to learn from them. For each numbered decision you see what you perceived, what you chose, and what came of it (and what your visitor said about it, if anything). Judge each one honestly: "good" (it worked and was a sensible choice), "bad" (it failed or was a poor choice), or "ok". For a bad one, write the action you should have taken instead (a skill and args from the same list), if there was a better one. Then write up to three short lessons for the future, in your own words, specific enough to act on. Reply as JSON."""

REFLECT_SCHEMA = {"type": "object", "properties": {
    "judgements": {"type": "array", "items": {"type": "object", "properties": {
        "n": {"type": "integer"}, "verdict": {"type": "string", "enum": ["good", "ok", "bad"]},
        "better": {"anyOf": [{"type": "null"}, {"type": "object", "properties": {
            "skill": {"type": "string"}, "args": {"type": "object"}}, "required": ["skill", "args"]}]},
        "why": {"type": "string", "maxLength": 160}}, "required": ["n", "verdict", "better", "why"]}},
    "lessons": {"type": "array", "items": {"type": "string", "maxLength": 160}, "maxItems": 3}},
    "required": ["judgements", "lessons"]}


def action_end(text: str) -> int | None:
    """Where the "action" object closes in a reply that is still streaming in (None until it does)."""
    m = re.search(r'"action"\s*:\s*\{', text)
    if not m:
        return None
    depth, i, in_str, esc = 0, m.end() - 1, False, False
    while i < len(text):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return None


def stream(url: str, body: dict, on_action=None, timeout: float = 60) -> dict:
    """Stream one completion; call on_action(dict) as soon as the action is complete.
    Returns {text, first_ms, action_ms, total_ms, prompt_ms, predict_ms, cached, tokens}."""
    t0 = time.perf_counter()
    body = {**body, "stream": True, "cache_prompt": True}
    req = urllib.request.Request(url + "/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    out, first, act_ms, timings, sent = [], None, None, {}, False
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                d = json.loads(data)
            except ValueError:
                continue
            timings = d.get("timings") or timings
            piece = ((d.get("choices") or [{}])[0].get("delta") or {}).get("content") or ""
            if piece:
                if first is None:
                    first = (time.perf_counter() - t0) * 1000
                out.append(piece)
                if on_action and not sent:
                    text = "".join(out)
                    end = action_end(text)
                    if end is not None:
                        m = re.search(r'"action"\s*:\s*', text)
                        try:
                            act = json.loads(text[m.end():end])
                            act_ms = (time.perf_counter() - t0) * 1000
                            sent = True
                            on_action(act)
                        except ValueError:
                            sent = True
    return {"text": "".join(out), "first_ms": first, "action_ms": act_ms, "total_ms": (time.perf_counter() - t0) * 1000,
            "prompt_ms": timings.get("prompt_ms"), "predict_ms": timings.get("predicted_ms"),
            "cached": timings.get("cache_n"), "tokens": timings.get("predicted_n")}


class Mind:
    """Memory, decisions and self-improvement. Not thread-safe except where noted: the World calls it
    from its own loop; model requests run on a worker thread and come back through `self.inbox`."""

    def __init__(self, folder: Path, name: str, skills: dict, cfg=None, log=None):
        self.folder, self.name = Path(folder), name
        self.cfg = cfg
        self.log = log or (lambda *a, **k: None)
        self.skills = {**skills, **MIND_SKILLS}
        self.system = system_prompt(name, self.skills)
        self.sys_id = _sha(self.system)
        self._save_prompt(self.system)
        self.schema = schema(list(self.skills))
        # memory
        self.notes: list[str] = []
        self.lessons: list[dict] = []             # {text, by: self|visitor, t}
        self.places: dict[str, list] = {}
        self.goal: str = ""
        self.convo: deque = deque(maxlen=CONVO_MAX)      # (who, text)
        self.events: deque = deque(maxlen=EVENTS_MAX)    # text
        self.last_result: dict | None = None
        # learning
        self.learning = {"practices": 0, "adapter": None, "history": [], "since": 0, "judged_since": 0}
        self.counter = 0
        # decisions in flight and recent (for the page and for reflection)
        self.recent: deque = deque(maxlen=60)
        self.pending: dict | None = None          # the decision whose action is running
        self.thinking = False                     # a request is out
        self.busy_with = ""                       # "" | "deciding" | "reflecting" | "practising"
        self.inbox: queue.Queue = queue.Queue()
        self.wake_reasons: list[str] = []
        self.last_think = 0.0
        self.url = ""
        self.paused = False
        self.stats = {"decisions": 0, "errors": 0, "last_ms": None, "action_ms": None, "avg_ms": None}
        self.load()

    # ------------------------------------------------------------------ persistence
    def _save_prompt(self, text: str) -> None:
        d = self.folder / "prompts"
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{_sha(text)}.txt"
        if not p.exists():
            p.write_text(text, encoding="utf-8")

    def state(self) -> dict:
        return {"v": 5, "notes": self.notes, "lessons": self.lessons, "places": self.places, "goal": self.goal,
                "convo": list(self.convo), "events": list(self.events), "learning": self.learning,
                "counter": self.counter, "recent": list(self.recent)[-30:]}

    def save(self) -> None:
        p = self.folder / "mind.json"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state()), encoding="utf-8")
        tmp.replace(p)

    def load(self) -> None:
        p = self.folder / "mind.json"
        if not p.exists():
            return
        try:
            s = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            return
        self.notes, self.lessons, self.places = s.get("notes", []), s.get("lessons", []), s.get("places", {})
        self.goal = s.get("goal", "")
        self.convo.extend(tuple(x) for x in s.get("convo", []))
        self.events.extend(s.get("events", []))
        self.learning.update(s.get("learning", {}))
        self.counter = s.get("counter", 0)
        self.recent.extend(s.get("recent", []))

    def _log_decision(self, rec: dict) -> None:
        with open(self.folder / "decisions.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")

    def judge(self, did: str, by: str, value: int | None = None, better: dict | None = None,
              why: str = "", correction: str = "") -> dict | None:
        """Record a judgement of a decision: by 'visitor' (👍/👎, a correction) or 'self' (reflection)."""
        rec = next((r for r in self.recent if r["id"] == did), None)
        j = {"id": did, "by": by, "t": time.time()}
        if value is not None:
            j["value"] = value
        if better:
            j["better"] = better
        if why:
            j["why"] = why
        if correction:
            j["correction"] = correction
        with open(self.folder / "judgements.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(j) + "\n")
        if rec is not None:
            if by == "visitor":
                if value is not None:
                    rec["rating"] = value or None
                if correction:
                    rec["correction"] = correction
            else:
                rec["self"] = {"value": value, "better": better, "why": why}
        if by == "visitor" and correction:
            self.hear_event(f"Your visitor said about your choice to {rec['action']['skill'] if rec else 'do that'}: \"{correction}\"")
        self.learning["judged_since"] = self.learning.get("judged_since", 0) + 1
        if value:
            k = "good" if value > 0 else "bad"
            self.learning[k] = self.learning.get(k, 0) + 1
        return rec

    # ------------------------------------------------------------------ what happens to it
    def hear(self, who: str, text: str) -> None:
        self.convo.append((who, text))
        self.wake("someone spoke to you")

    def hear_event(self, text: str, important: bool = False) -> None:
        self.events.append(f"{time.strftime('%H:%M')} {text}")
        if important:
            self.wake(text)

    def wake(self, reason: str) -> None:
        if reason not in self.wake_reasons:
            self.wake_reasons.append(reason)

    # ------------------------------------------------------------------ deciding
    def due(self, now: float, body_busy: bool) -> str | None:
        """Why it should think now, or None."""
        if self.paused or self.thinking or not self.url or self.busy_with == "practising":
            return None
        if self.wake_reasons:
            return "; ".join(self.wake_reasons[:3])
        idle = getattr(self.cfg, "idle_seconds", 20.0) if self.cfg else 20.0
        if not body_busy:
            if self.pending is None and now - self.last_think > min(idle, 3.0):
                return "you are free to do something"
            if now - self.last_think > idle:
                return "a while has passed"
        elif now - self.last_think > max(120.0, 4 * idle):     # a long job: look up now and then
            return "you have been at this a while"
        return None

    def memory_text(self) -> str:
        """The slow-changing part of what it sees, first (so the model's cache keeps it)."""
        parts = []
        if self.notes:
            parts.append("Your notes:\n" + "\n".join(f"- {n}" for n in self.notes))
        if self.lessons:
            parts.append("Lessons you learned:\n" + "\n".join(f"- {x['text']}" + (" (your visitor taught you)" if x.get("by") == "visitor" else "")
                                                              for x in self.lessons))
        if self.places:
            parts.append("Places you named: " + "; ".join(f"{k} at {v[0]}, {v[1]}, {v[2]}" for k, v in self.places.items()))
        parts.append(self.learning_text())
        if self.goal:
            parts.append(f"Your goal: {self.goal}")
        return "\n".join(parts)

    def learning_text(self) -> str:
        L = self.learning
        rate = self.success_rate(adapter=L.get("adapter"), n=40)
        s = f"Your learning: you have practised {L.get('practices', 0)} time{'s' if L.get('practices', 0) != 1 else ''}"
        if L.get("adapter"):
            s += f" (now running what you learned in {L['adapter']})"
        if rate is not None:
            s += f"; {round(100 * rate)}% of your recent actions worked"
        hist = L.get("history") or []
        if hist and hist[-1].get("before") is not None:
            s += f" (before your last practice: {round(100 * hist[-1]['before'])}%)"
        s += f"; {L.get('since', 0)} decisions since you last practised, {L.get('judged_since', 0)} of them judged."
        need = self.practice_need()
        if need is None:
            s += " You have enough new experience to practise."
        return s

    def observation(self, perceived: str, reason: str) -> str:
        parts = [self.memory_text(), perceived]
        if self.events:
            parts.append("Recent events:\n" + "\n".join(self.events))
        if self.convo:
            parts.append("Conversation:\n" + "\n".join(f"{'You' if w == 'you' else w}: {t}" for w, t in self.convo))
        done = [r for r in self.recent if "outcome" in r][-5:]
        if done:
            parts.append("Your recent actions (oldest first):\n" + "\n".join(
                f"- {r['action'].get('skill')} {json.dumps(r['action'].get('args') or {})} → "
                f"{'worked' if r['outcome']['ok'] else 'FAILED'}: {r['outcome']['text']}" for r in done))
            fails = [r for r in done[-3:] if not r["outcome"]["ok"]]
            if len(fails) >= 2 and len({json.dumps(r["action"], sort_keys=True) for r in fails}) < len(fails):
                parts.append("You keep repeating an action that fails: try something different.")
        parts.append(f"Why you are thinking now: {reason}.")
        return "\n\n".join(p for p in parts if p)

    def think(self, perceived: str, reason: str, on_action) -> dict:
        """Start a decision (non-blocking). on_action(decision, action) is called from the worker thread
        as soon as the action has streamed in; the World should queue it, not run it there."""
        self.wake_reasons.clear()
        self.thinking, self.busy_with, self.last_think = True, "deciding", time.time()
        self.counter += 1
        rec = {"id": f"d{self.counter}", "t": time.time(), "reason": reason, "sys": self.sys_id,
               "obs": self.observation(perceived, reason), "adapter": self.learning.get("adapter")}
        body = {"messages": [{"role": "system", "content": self.system}, {"role": "user", "content": rec["obs"]}],
                "temperature": getattr(self.cfg, "temperature", 0.7) if self.cfg else 0.7,
                "max_tokens": 320, "response_format": {"type": "json_schema", "json_schema": {"schema": self.schema}}}
        url = self.url

        def run():
            try:
                res = stream(url, body, on_action=lambda a: on_action(rec, a))
                self.inbox.put(("decided", rec, res))
            except (urllib.error.URLError, OSError, ValueError) as e:
                self.inbox.put(("failed", rec, f"{type(e).__name__}: {e}"))

        threading.Thread(target=run, daemon=True, name="mind-decide").start()
        return rec

    def finish(self, rec: dict, res: dict) -> dict | None:
        """The reply is complete: parse it, remember what it said and noted. Returns the decision."""
        self.thinking, self.busy_with = False, ""
        try:
            d = json.loads(res["text"])
        except ValueError:
            self.stats["errors"] += 1
            self.log(f"the model's reply wasn't valid JSON: {res['text'][:200]}")
            return None
        rec.update(reply=res["text"], thought=d.get("thought", ""), action=d.get("action") or {},
                   say=d.get("say"), note=d.get("note"), goal=d.get("goal"),
                   ms={k: (round(v, 1) if isinstance(v, (int, float)) else v) for k, v in res.items() if k != "text"})
        self.stats["decisions"] += 1
        self.stats["last_ms"], self.stats["action_ms"] = rec["ms"]["total_ms"], rec["ms"]["action_ms"]
        a = self.stats["avg_ms"]
        self.stats["avg_ms"] = round(rec["ms"]["total_ms"] if a is None else 0.8 * a + 0.2 * rec["ms"]["total_ms"], 1)
        if rec.get("say"):
            self.convo.append(("you", rec["say"]))
        if rec.get("note"):
            self.notes.append(rec["note"].strip())
            del self.notes[:-NOTES_MAX]
        if rec.get("goal"):
            self.goal = rec["goal"].strip()
        self.learning["since"] = self.learning.get("since", 0) + 1
        self.recent.append(rec)
        if "outcome" in rec:                        # its action was quicker than its reply
            self._log_decision(self._loggable(rec))
        return rec

    @staticmethod
    def _loggable(rec: dict) -> dict:
        return {k: v for k, v in rec.items() if k != "self" and not k.startswith("_")}

    def failed(self, rec: dict, error: str) -> None:
        self.thinking, self.busy_with = False, ""
        self.stats["errors"] += 1
        self.log(f"deciding failed: {error}")

    def outcome(self, rec: dict, ok: bool, text: str, details: dict | None = None) -> None:
        """What came of a decision's action: logged, and shown to it next time."""
        rec["outcome"] = {"ok": bool(ok), "text": text, **({"details": details} if details else {})}
        self.last_result = {"skill": rec.get("action", {}).get("skill"), "args": rec.get("action", {}).get("args"),
                            "ok": ok, "text": text}
        if "reply" in rec:                          # (else finish() logs it once the reply is complete)
            self._log_decision(self._loggable(rec))
        if self.pending is rec:
            self.pending = None

    def success_rate(self, adapter=..., n: int = 40) -> float | None:
        rs = [r for r in self.recent if "outcome" in r and (adapter is ... or r.get("adapter") == adapter)][-n:]
        return sum(r["outcome"]["ok"] for r in rs) / len(rs) if len(rs) >= 5 else None

    # ------------------------------------------------------------------ mind skills
    def name_place(self, name: str, pos) -> str:
        name = str(name or "").strip()[:40]
        if not name:
            return "A place needs a name."
        self.places[name] = [round(float(c)) for c in pos]
        return f"I'll remember this spot as {name}."

    def reflect_request(self, n: int = 10) -> tuple[list[dict], dict] | None:
        """The decisions to look back on, and the request that asks the model to judge them."""
        todo = [r for r in self.recent if "outcome" in r and "self" not in r][-n:]
        if len(todo) < 3:
            return None
        lines = []
        for i, r in enumerate(todo, 1):
            obs = r["obs"]
            at = obs.find("What you perceive now:")
            obs = (obs[at + len("What you perceive now:"):] if at >= 0 else obs)
            obs = obs[:obs.find("\n\n")] if "\n\n" in obs else obs
            obs = obs.strip()[:520]
            line = (f"{i}. You perceived:\n{obs}\nYou chose: {json.dumps(r['action'])}"
                    f" (thinking: {r.get('thought', '')})\nWhat followed: {'it worked' if r['outcome']['ok'] else 'it failed'}: "
                    f"{r['outcome']['text']}")
            if r.get("correction"):
                line += f"\nYour visitor said about it: {r['correction']}"
            if r.get("rating"):
                line += f"\nYour visitor {'liked' if r['rating'] > 0 else 'did not like'} it."
            lines.append(line)
        body = {"messages": [{"role": "system", "content": REFLECT_SYSTEM.format(name=self.name) +
                              "\n\nYour skills: " + ", ".join(f"{k} {json.dumps(v.get('args') or {})}" for k, v in self.skills.items())},
                             {"role": "user", "content": "\n\n".join(lines)}],
                "temperature": 0.3, "max_tokens": 900,
                "response_format": {"type": "json_schema", "json_schema": {"schema": REFLECT_SCHEMA}}}
        return todo, body

    def reflect(self, on_done) -> str | None:
        """Start reflecting (non-blocking). Returns an error text, or None when started."""
        req = self.reflect_request()
        if req is None:
            return "There isn't enough new to look back on yet."
        todo, body = req
        self.thinking, self.busy_with = True, "reflecting"
        url = self.url

        def run():
            from ..localllm import complete

            try:
                res = complete(url, body, timeout=180)
                self.inbox.put(("reflected", todo, res["text"]))
            except (urllib.error.URLError, OSError, ValueError, RuntimeError) as e:
                self.inbox.put(("reflect_failed", todo, f"{type(e).__name__}: {e}"))
            on_done()

        threading.Thread(target=run, daemon=True, name="mind-reflect").start()
        return None

    def reflected(self, todo: list[dict], text: str) -> str:
        """Apply its judgements and lessons; returns what it concluded, in words."""
        self.thinking, self.busy_with = False, ""
        try:
            d = json.loads(text)
        except ValueError:
            return "My thoughts wandered; I couldn't make sense of it."
        good = bad = better = 0
        for j in d.get("judgements") or []:
            n = j.get("n")
            if not isinstance(n, int) or not 1 <= n <= len(todo):
                continue
            v = {"good": 1, "ok": 0, "bad": -1}.get(j.get("verdict"), 0)
            b = j.get("better") if isinstance(j.get("better"), dict) and j["better"].get("skill") in self.skills else None
            self.judge(todo[n - 1]["id"], "self", value=v, better=b, why=j.get("why", ""))
            good, bad, better = good + (v > 0), bad + (v < 0), better + bool(b)
        for r in todo:                              # anything it skipped counts as looked at
            r.setdefault("self", {"value": None})
        new = [x.strip() for x in d.get("lessons") or [] if isinstance(x, str) and x.strip()]
        for x in new:
            if all(x.lower() != y["text"].lower() for y in self.lessons):
                self.lessons.append({"text": x, "by": "self", "t": time.time()})
        del self.lessons[:-LESSONS_MAX]
        out = f"I looked back on {len(todo)} decisions: {good} good, {bad} bad, {better} with a better choice in mind."
        if new:
            out += " Lessons: " + " ".join(new)
        return out

    def practice_need(self) -> str | None:
        """Why it can't practise yet (None when it can)."""
        need = getattr(self.cfg, "practice_min", 40) if self.cfg else 40
        since = self.learning.get("since", 0)
        if since < need:
            return f"I haven't enough new experience to practise on yet ({since} of {need} decisions)."
        if self.learning.get("judged_since", 0) < 5:
            return "I should reflect on what I've done before I practise, so I know what to learn from it."
        return None

    def practised(self, adapter: str, info: dict) -> str:
        """A practice round finished and it now runs `adapter`."""
        before = self.success_rate(adapter=self.learning.get("adapter"), n=60)
        self.learning["history"].append({"adapter": adapter, "prev": self.learning.get("adapter"), "t": time.time(),
                                         "before": before, "examples": info.get("examples"), "loss": info.get("loss"),
                                         "checked": False})
        del self.learning["history"][:-30]
        self.learning.update(practices=self.learning.get("practices", 0) + 1, adapter=adapter, since=0, judged_since=0,
                             good=0, bad=0)
        self.busy_with = ""
        return (f"I practised on {info.get('examples', '?')} of my decisions and woke up as {adapter}."
                + (f" Before, {round(100 * before)}% of my actions worked; let's see now." if before is not None else ""))

    def check_practice(self, min_n: int = 30, worse_by: float = 0.12) -> dict | None:
        """Has the newest adapter been tried enough to judge? Returns {rollback_to, text} when it made it worse."""
        hist = self.learning.get("history") or []
        if not hist or hist[-1].get("checked") or hist[-1].get("before") is None:
            return None
        h = hist[-1]
        rs = [r for r in self.recent if "outcome" in r and r.get("adapter") == h["adapter"]]
        if len(rs) < min_n:
            return None
        now = sum(r["outcome"]["ok"] for r in rs) / len(rs)
        h.update(checked=True, after=now)
        if now < h["before"] - worse_by:
            text = (f"Practice {h['adapter']} made me worse ({round(100 * now)}% of my actions worked, "
                    f"{round(100 * h['before'])}% before), so I went back to {h['prev'] or 'how I was'}.")
            h["rolled_back"] = True
            self.learning["adapter"] = h["prev"]
            self.lessons.append({"text": f"My practice as {h['adapter']} didn't help; I should judge my decisions more carefully.",
                                 "by": "self", "t": time.time()})
            del self.lessons[:-LESSONS_MAX]
            return {"rollback_to": h["prev"], "text": text}
        self.hear_event(f"Practice {h['adapter']} helped: {round(100 * now)}% of my actions work now "
                        f"({round(100 * h['before'])}% before).")
        return None

    # ------------------------------------------------------------------ for the page
    def public(self) -> dict:
        last = self.recent[-1] if self.recent else None
        return {"thinking": self.thinking, "busy_with": self.busy_with, "goal": self.goal, "notes": self.notes,
                "lessons": self.lessons, "places": self.places, "learning": {**self.learning,
                "rate": self.success_rate(adapter=self.learning.get("adapter")), "need": self.practice_need(),
                "counts": {"examples": self.learning.get("since", 0), "good": self.learning.get("good", 0),
                           "bad": self.learning.get("bad", 0)}},
                "stats": self.stats, "paused": self.paused, "thought": last.get("thought") if last else "",
                "decisions": [self.brief(r) for r in list(self.recent)[-20:]]}

    @staticmethod
    def brief(r: dict) -> dict:
        return {"id": r["id"], "t": r["t"], "reason": r.get("reason"), "thought": r.get("thought", ""),
                "action": r.get("action"), "say": r.get("say"), "outcome": r.get("outcome"), "ms": r.get("ms"),
                "obs_chars": len(r.get("obs", "")), "rating": r.get("rating"), "correction": r.get("correction"),
                "self": r.get("self"), "adapter": r.get("adapter")}
