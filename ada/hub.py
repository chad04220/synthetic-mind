"""The Hub: the parent process. It never imports PyTorch and never does heavy work, so the web page
it serves stays responsive whatever the Academy and the World are doing.

It starts both worker processes (and restarts either if it crashes), carries messages between
them and the browser, runs the schedule (by default the Academy studies while Ada sleeps and
rests while she is awake), and runs the Oracle: background lessons aimed at what Ada gets wrong,
topics you ask it to teach, answers to questions, villagers' words and assessments.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import queue
import random
import threading
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from . import academy, life
from .concepts import ConceptGraph
from .config import AdaConfig, get_live, set_live
from .oracle import TOPICS, Oracle
from .proc import append_jsonl

CHILDREN = {"academy": academy.run, "world": life.run}


class Hub:
    def __init__(self, cfg: AdaConfig, root: Path):
        self.cfg = cfg
        self.root = root
        self.folder = root / cfg.name
        self.folder.mkdir(parents=True, exist_ok=True)
        cfg.save(self.folder / "config.json")
        self.ctx = mp.get_context("spawn")
        self.outbox = self.ctx.Queue(maxsize=5000)
        self.inboxes = {n: self.ctx.Queue() for n in CHILDREN}
        self.procs: dict[str, mp.Process] = {}
        self.restarts = {n: 0 for n in CHILDREN}
        self.stopping = False
        self.lock = threading.RLock()

        # what the browser sees
        self.academy_status: dict = {}
        self.academy_seq = 0
        self.world_state: dict = {}
        self.world_ents: dict[int, dict] = {}
        self.world_msgs: deque = deque(maxlen=80)    # (seq, delta)
        self.world_seq = 0
        self.events: deque = deque(maxlen=800)
        self.event_id = 0
        self.metrics: deque = deque(maxlen=20000)
        self.assessments: deque = deque(maxlen=500)
        self.feeds = {k: deque(maxlen=n) for k, n in
                      (("thought", 80), ("chat", 200), ("oracle", 60), ("lesson", 60), ("npc", 40), ("deed", 80))}
        self.concept_report: dict = {}
        self._load_history()

        # the Oracle
        self.oracle = Oracle(cfg.oracle.url, cfg.oracle.model)
        self.pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="oracle")
        self.teaching = False
        self.last_teach = 0.0
        self.last_assess = time.time()
        self.last_refresh = time.time()
        self.topics: deque = deque()               # topics you asked the Oracle to teach
        self.lessons_written = 0
        self.graph = ConceptGraph(self.folder / "concepts.json")

        self.waiters: dict[str, Future] = {}
        self.phase = "day"
        self.academy_wanted: tuple | None = None

    # ------------------------------------------------------------------ lifecycle
    def start(self):
        self.oracle.refresh()
        if self.oracle.model != self.cfg.oracle.model:
            self.cfg.oracle.model = self.oracle.model
            self.cfg.save(self.folder / "config.json")
        for n in CHILDREN:
            self.spawn(n)
        threading.Thread(target=self._reader, name="hub-reader", daemon=True).start()
        threading.Thread(target=self._supervise, name="hub-supervisor", daemon=True).start()

    def spawn(self, name: str):
        p = self.ctx.Process(target=CHILDREN[name], args=(self.cfg.name, str(self.root), self.inboxes[name], self.outbox),
                             name=f"ada-{name}", daemon=True)
        p.start()
        self.procs[name] = p
        self.event("system", text=f"The {'Academy' if name == 'academy' else 'World'} is starting.")
        if name == "academy":
            self.academy_wanted = None      # re-send the schedule to the new process
        else:
            self.send("world", "full")

    def stop(self):
        self.stopping = True
        for n in self.procs:
            self.send(n, "stop")
        deadline = time.time() + 25
        for p in self.procs.values():
            p.join(timeout=max(0.1, deadline - time.time()))
            if p.is_alive():
                p.terminate()
        self.pool.shutdown(wait=False, cancel_futures=True)

    def _supervise(self):
        while not self.stopping:
            time.sleep(1.0)
            for n, p in list(self.procs.items()):
                if not p.is_alive() and not self.stopping:
                    self.restarts[n] += 1
                    wait = min(60, 3 * self.restarts[n])
                    self.event("error", text=f"The {n} process stopped (exit code {p.exitcode}); restarting in {wait}s. "
                                             f"Details are in minds/{self.cfg.name}/{n}.log")
                    time.sleep(wait)
                    if not self.stopping:
                        self.spawn(n)
            self.apply_schedule()
            if self.cfg.oracle.enabled and not self.oracle.models and time.time() - self.last_refresh > 30:
                self.last_refresh = time.time()      # Ollama may have been started after us
                self.pool.submit(self._refresh_oracle)
            try:
                self._teach_tick()
                self._assess_tick()
            except Exception as e:  # never let the Oracle take the Hub down
                self.event("error", text=f"Oracle: {type(e).__name__}: {e}")

    # ------------------------------------------------------------------ messaging
    def send(self, child: str, cmd: str, rid: str | None = None, **args):
        try:
            self.inboxes[child].put_nowait({"cmd": cmd, "rid": rid, **args})
        except queue.Full:
            pass

    def request(self, child: str, cmd: str, **args) -> Future:
        rid = f"h{time.time_ns()}{random.randrange(1000)}"
        f: Future = Future()
        self.waiters[rid] = f
        if child not in self.procs or not self.procs[child].is_alive():
            f.set_exception(RuntimeError(f"the {child} isn't running right now"))
            self.waiters.pop(rid, None)
            return f
        self.send(child, cmd, rid=rid, **args)
        return f

    def event(self, kind: str, **data):
        with self.lock:
            self.event_id += 1
            ev = {"id": self.event_id, "kind": kind, "t": time.time(), **data}
            self.events.append(ev)
            if kind in self.feeds:
                self.feeds[kind].append(ev)

    def events_since(self, eid: int) -> list[dict]:
        with self.lock:
            if not self.events or self.events[-1]["id"] <= eid:
                return []
            return [e for e in self.events if e["id"] > eid]

    def _reader(self):
        while not self.stopping:
            try:
                msg = self.outbox.get(timeout=0.5)
            except queue.Empty:
                continue
            except (EOFError, OSError):
                return
            try:
                self.on_message(msg)
            except Exception as e:
                self.event("error", text=f"Hub: {type(e).__name__}: {e}")

    def on_message(self, m: dict):
        t = m["type"]
        if t == "reply":
            f = self.waiters.pop(m["rid"], None)
            if f and not f.done():
                f.set_exception(RuntimeError(m["error"])) if m.get("error") else f.set_result(m.get("result"))
        elif t == "status":
            with self.lock:
                self.academy_status = m["status"]
                self.academy_seq += 1
        elif t == "metric":
            p = m["point"]
            self.metrics.append(p)
            append_jsonl(self.folder / "metrics.jsonl", p)
            self.event("metric", point=p)
        elif t == "concepts":
            self.concept_report = m["report"]
            self.event("concepts", summary={k: v for k, v in m["report"].items() if k != "results"})
        elif t == "published":
            self.event("published", meta=m["meta"])
        elif t == "grew":
            self.event("grew", layers=m["layers"], params=m["params"], why=m["why"])
        elif t in ("log", "error"):
            self.event("error" if t == "error" or m.get("error") else "log", text=m["text"], src=m["src"])
        elif t == "world":
            self._merge_world(m["snap"])
        elif t == "phase":
            self.phase = m["phase"]
            self.event("phase", phase=m["phase"], day=m["day"])
            self.academy_wanted = None
            self.apply_schedule()
        elif t == "event":
            kind = m["kind"]
            self.event(kind, **{k: v for k, v in m.items() if k not in ("src", "type", "t", "kind")})
            also = {"did": "deed", "intent": "deed", "tutor": "chat"}.get(kind)   # feeds shown on load
            if also:
                with self.lock:
                    self.feeds[also].append(self.events[-1])
        elif t == "history":
            for th in m.get("thoughts", []):
                self.feeds["thought"].append({"id": 0, "kind": "thought", **th})
            for c in m.get("chat", []):
                self.feeds["chat"].append({"id": 0, "kind": "chatline", **c})
        elif t == "oracle":
            self.pool.submit(self._world_oracle, m)

    def _merge_world(self, snap: dict):
        with self.lock:
            if snap.get("full"):
                self.world_ents = {e["id"]: e for e in snap["ents"]}
                self.world_state = {k: v for k, v in snap.items() if k not in ("ents", "removed")}
            else:
                for e in snap["ents"]:
                    self.world_ents[e["id"]] = e
                for i in snap["removed"]:
                    self.world_ents.pop(i, None)
                for k, v in snap.items():
                    if k not in ("ents", "removed"):
                        self.world_state[k] = v
            self.world_seq += 1
            self.world_msgs.append((self.world_seq, snap))

    def world_full(self) -> dict:
        with self.lock:
            return dict(self.world_state, ents=list(self.world_ents.values()), removed=[], full=True)

    def world_delta(self, since: int) -> tuple[int, dict | None]:
        """Everything that changed in the world since `since`, merged into one message."""
        with self.lock:
            if not self.world_msgs or since >= self.world_seq:
                return self.world_seq, None
            if since < self.world_msgs[0][0] - 1 or any(m.get("full") for s, m in self.world_msgs if s > since):
                return self.world_seq, self.world_full()
            ents, removed, out = {}, set(), {}
            for s, m in self.world_msgs:
                if s <= since:
                    continue
                for e in m["ents"]:
                    ents[e["id"]] = e
                    removed.discard(e["id"])
                for i in m["removed"]:
                    removed.add(i)
                    ents.pop(i, None)
                out.update({k: v for k, v in m.items() if k not in ("ents", "removed")})
            out["ents"], out["removed"] = list(ents.values()), list(removed)
            return self.world_seq, out

    # ------------------------------------------------------------------ schedule
    def apply_schedule(self):
        s = self.cfg.schedule
        if s.mode == "day_night":
            want = ("resume", "full") if self.phase == "night" else \
                (("resume", "gentle") if s.day_training == "gentle" else ("pause", "Ada is awake"))
        elif s.mode == "together":
            want = ("resume", "balanced")
        elif s.mode == "academy":
            want = ("resume", "full")
        else:
            want = ("pause", "live-only mode")
        if want != self.academy_wanted:
            self.academy_wanted = want
            if want[0] == "resume":
                self.send("academy", "resume", intensity=want[1] if want[1] != "full" else None)
            else:
                self.send("academy", "pause", why=want[1])

    # ------------------------------------------------------------------ settings
    def set(self, key: str, value):
        v = set_live(self.cfg, key, value)
        self.cfg.save(self.folder / "config.json")
        for n in CHILDREN:
            self.send(n, "config", config=self.cfg.to_dict())
        if key.startswith("oracle."):
            self.oracle.url, self.oracle.model = self.cfg.oracle.url.rstrip("/"), self.cfg.oracle.model
            if key == "oracle.url":
                self.oracle.refresh()
        if key.startswith("schedule."):
            self.academy_wanted = None
            self.apply_schedule()
        return v

    def settings(self) -> dict:
        return get_live(self.cfg)

    # ------------------------------------------------------------------ the Oracle
    @property
    def stage(self) -> int:
        return int(self.academy_status.get("stage", 0) or 0)

    def _refresh_oracle(self):
        before = self.oracle.model
        self.oracle.refresh()
        if self.oracle.model and self.oracle.model != self.cfg.oracle.model:
            self.set("oracle.model", self.oracle.model)
        if self.oracle.models and not before:
            self.event("log", text=f"The Oracle is here: {self.oracle.model}", src="hub")

    def oracle_ready(self) -> bool:
        return self.cfg.oracle.enabled and bool(self.oracle.model)

    def _curriculum(self, kind: str, parts, weight: float = 1.0, priority: bool = False, topic: str = ""):
        append_jsonl(self.folder / "curriculum.jsonl", {"t": time.time(), "kind": kind, "topic": topic,
                                                        "parts": [[r, t] for r, t in parts if t],
                                                        "weight": weight, "priority": priority})

    def teach(self, topic: str, priority: bool = False, focus: list[str] | None = None) -> dict:
        """Ask the Oracle for a lesson pack and hand it to the Academy. Returns the pack."""
        pack = self.oracle.lesson_pack(topic, self.stage, focus)
        if pack["lesson"]:
            self._curriculum("lesson", [("<|oracle|>", pack["lesson"])], 1.0, priority, topic)
        for q, a in pack["qa"]:
            self._curriculum("qa", [("<|user|>", q), ("<|oracle|>", a)], 1.5, priority, topic)
            self._curriculum("qa", [("<|user|>", q), ("<|mind|>", a)], 1.0, priority, topic)
        pack["new_facts"] = self.graph.add(pack["facts"], "oracle")
        self.lessons_written += 1
        self.event("lesson", topic=topic, text=pack["lesson"], qa=pack["qa"], facts=pack["facts"],
                   new_facts=pack["new_facts"], priority=priority)
        return pack

    def _teach_tick(self):
        """Keep lessons flowing while the Academy studies: your topics first, then what Ada gets wrong."""
        o = self.cfg.oracle
        studying = self.academy_wanted is not None and self.academy_wanted[0] == "resume"
        if self.teaching or not self.oracle_ready():
            return
        if not self.topics and not (o.background_teaching and studying and time.time() - self.last_teach >= o.lesson_seconds):
            return
        if self.topics:
            topic, priority, focus = self.topics.popleft(), True, None
        else:
            wrong = [r for r in self.concept_report.get("results", []) if not r["ok"]]
            if wrong and random.random() < 0.6:
                pick = random.choice(wrong)
                topic = pick["s"]
                focus = [f"{x['s']} {x['r']} {x['o']}" for x in wrong if x["s"] == topic][:4]
            else:
                topic, focus = random.choice(TOPICS), None
            priority = False
        self.teaching = True
        self.last_teach = time.time()

        def job():
            try:
                self.teach(topic, priority, focus)
            except Exception as e:
                self.event("error", text=f"Oracle lesson on {topic}: {type(e).__name__}: {e}")
            finally:
                self.teaching = False

        self.pool.submit(job)

    def _assess_tick(self):
        if not self.oracle_ready() or time.time() - self.last_assess < self.cfg.oracle.assess_minutes * 60:
            return
        thoughts = [e["text"] for e in self.feeds["thought"] if e.get("text", "").strip()]
        if len(thoughts) < 5:
            return
        self.last_assess = time.time()
        rate = (self.world_state.get("mind") or {}).get("self_rate", 0)

        def job():
            a = self.oracle.assess(thoughts, rate)
            if a:
                a.update(step=self.academy_status.get("step", 0), t=time.time(), self_rate=rate)
                self.assessments.append(a)
                append_jsonl(self.folder / "assessments.jsonl", a)
                self.event("assessment", **a)

        self.pool.submit(job)

    def _world_oracle(self, m: dict):
        """The World needs words from the Oracle: answer when they arrive (or a fallback)."""
        from .ontology import NPCS

        purpose, p, st = m["purpose"], m["payload"], self.stage
        text = ""
        try:
            if self.oracle_ready():
                if purpose == "npc" and self.cfg.oracle.npc_voices:
                    text = self.oracle.npc(p["npc"], p["role"], p.get("ada_said", ""), st, p["season"], p["weather"], p["place"])
                elif purpose == "answer":
                    text = self.oracle.answer(p["question"], st)
                elif purpose == "tutor" and self.cfg.oracle.tutor_replies:
                    text = self.oracle.tutor(p["history"], p["user"], p["mind"], st)
                elif purpose == "book":
                    text = self.oracle.book(st)
                elif purpose == "fact":
                    text = self.oracle.fact(p["topic"], st)
        except Exception as e:
            self.event("error", text=f"Oracle ({purpose}): {type(e).__name__}: {e}")
        if not text and purpose == "npc":
            text = random.choice(NPCS[p["npc"]]["lines"])
        if not text and purpose == "book":
            facts = self.graph.drill(random.Random())
            text = " ".join(t for _, t in facts)
        if text:
            self.send("world", "oracle_reply", req=m["rid"], text=text)

    def ask(self, question: str) -> str:
        """You ask the Oracle something."""
        answer = self.oracle.answer(question, 6, asker="you")
        self.event("oracle", question=question, text=answer, by="you")
        return answer

    def learn_answer(self, question: str, answer: str):
        """Give an Oracle answer to Ada to study."""
        self._curriculum("qa", [("<|user|>", question), ("<|oracle|>", answer)], 2.0, True, question[:60])
        self._curriculum("qa", [("<|user|>", question), ("<|mind|>", answer)], 1.5, True, question[:60])
        self.event("lesson", topic=question[:80], text=answer, qa=[], facts=[], new_facts=0, priority=True)

    # ------------------------------------------------------------------ history across restarts
    def _load_history(self):
        path = self.folder / "metrics.jsonl"
        if path.exists():
            for line in path.read_text().splitlines()[-20000:]:
                try:
                    self.metrics.append(json.loads(line))
                except ValueError:
                    pass
        path = self.folder / "assessments.jsonl"
        if path.exists():
            for line in path.read_text().splitlines()[-500:]:
                try:
                    self.assessments.append(json.loads(line))
                except ValueError:
                    pass
        path = self.folder / "concept_report.json"
        if path.exists():
            try:
                self.concept_report = json.loads(path.read_text())
            except ValueError:
                pass

    def init_payload(self) -> dict:
        with self.lock:
            return {
                "type": "init", "name": self.cfg.name, "settings": self.settings(),
                "academy": self.academy_status, "world": self.world_full(), "world_seq": self.world_seq,
                "metrics": list(self.metrics)[-4000:], "assessments": list(self.assessments),
                "feeds": {k: list(v) for k, v in self.feeds.items()},
                "concepts": self.concept_report, "event_id": self.event_id,
                "oracle": self.oracle_info(), "events": [e for e in self.events if e["kind"] in ("error", "log")][-20:],
            }

    def oracle_info(self) -> dict:
        return {"models": self.oracle.models, "model": self.oracle.model, "error": self.oracle.error,
                "teaching": self.teaching, "lessons": self.lessons_written, "queued": list(self.topics),
                "enabled": self.cfg.oracle.enabled}
