"""The Hub: the parent process. It never does heavy work, so the page it serves stays responsive.

It starts the World process (and restarts it if it crashes), carries messages between it and the
browser, keeps the inhabitant's model running (llama.cpp, on the GPU when there is one), runs its
practice rounds (the Coach), archives its thoughts and conversations in full, and watches health.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import queue
import random
import threading
import time
from collections import deque
from concurrent.futures import Future
from pathlib import Path

from . import life
from .archive import Archive
from .coach import Coach
from .config import AdaConfig, get_live, model_threads, set_live
from .diag import Perf, findings, gpu_readings, setup_logging, system_info
from .localllm import LocalLLM

CHILDREN = {"world": life.run}
ORACLE = Path(__file__).resolve().parent.parent / "oracle"


class Hub:
    def __init__(self, cfg: AdaConfig, root: Path):
        self.cfg = cfg
        self.root = root
        self.folder = root / cfg.name
        self.folder.mkdir(parents=True, exist_ok=True)
        cfg.save(self.folder / "config.json")
        self.log = setup_logging("hub", self.folder)
        self.perf = Perf()
        self.perf_latest: dict[str, dict] = {}
        self.perf_history: deque = deque(maxlen=720)
        self.gpu: list[dict] = []
        self.client_perf: dict = {}
        self.findings: list[dict] = []
        self._finding_seen: dict[str, float] = {}
        self.started = time.time()
        self.ws_bytes = 0
        self.ctx = mp.get_context("spawn")
        self.outbox = self.ctx.Queue(maxsize=5000)
        self.inboxes = {n: self.ctx.Queue() for n in CHILDREN}
        self.procs: dict[str, mp.Process] = {}
        self.restarts = {n: 0 for n in CHILDREN}
        self.stopping = False
        self.lock = threading.RLock()
        # what the browser sees
        self.world_state: dict = {}
        self.world_ents: dict = {}
        self.world_msgs: deque = deque(maxlen=200)       # (seq, delta)
        self.world_seq = 0
        self.mind: dict = {}
        self.events: deque = deque(maxlen=800)
        self.event_id = 0
        self.feeds = {k: deque(maxlen=n) for k, n in (("decision", 120), ("chat", 200), ("happening", 200))}
        self.archive = Archive(self.folder)
        self.waiters: dict[str, Future] = {}
        # its model, and its practice
        self.local = LocalLLM(ORACLE, self._model_log, "mind")
        self.local.name = f"{cfg.name}'s mind"
        self.model_sent: tuple | None = None
        self.coach = Coach(self.folder, ORACLE, cfg, self._model_log, self._practice_changed)
        self.last_practice_t = self._last_practice_t()

    # ------------------------------------------------------------------ lifecycle
    def start(self):
        for n in CHILDREN:
            self.spawn(n)
        threading.Thread(target=self._reader, name="hub-reader", daemon=True).start()
        threading.Thread(target=self._supervise, name="hub-supervisor", daemon=True).start()

    def spawn(self, name: str):
        p = self.ctx.Process(target=CHILDREN[name], args=(self.cfg.name, str(self.root), self.inboxes[name], self.outbox),
                             name=f"ada-{name}", daemon=True)
        p.start()
        self.procs[name] = p
        self.model_sent = None                  # tell the new process where its model is
        self.event("system", text="The world is starting.")

    def stop(self):
        self.stopping = True
        self.coach.stop()
        for n in self.procs:
            self.send(n, "stop")
        deadline = time.time() + 25
        for p in self.procs.values():
            p.join(timeout=max(0.1, deadline - time.time()))
            if p.is_alive():
                p.terminate()
        closer = threading.Thread(target=self.local.close, daemon=True)
        closer.start()
        closer.join(20)

    def _supervise(self):
        while not self.stopping:
            time.sleep(0.5)
            for n, p in list(self.procs.items()):
                if not p.is_alive() and not self.stopping:
                    self.restarts[n] += 1
                    wait = min(60, 3 * self.restarts[n])
                    self.event("error", text=f"The {n} process stopped (exit code {p.exitcode}); restarting in {wait}s. "
                                             f"Details are in minds/{self.cfg.name}/logs/{n}.log")
                    time.sleep(wait)
                    if not self.stopping:
                        self.spawn(n)
            self._model_tick()
            self._diagnose_tick()

    # ------------------------------------------------------------------ messaging
    def send(self, child: str, cmd: str, rid: str | None = None, **args):
        try:
            self.inboxes[child].put_nowait({"cmd": cmd, "rid": rid, **args})
        except queue.Full:
            pass

    def request(self, child: str, cmd: str, **args) -> Future:
        rid = f"h{time.time_ns()}{random.randrange(1000)}"
        f: Future = Future()
        if child not in self.procs or not self.procs[child].is_alive():
            f.set_exception(RuntimeError(f"the {child} isn't running right now"))
            return f
        self.waiters[rid] = f
        self.send(child, cmd, rid=rid, **args)
        return f

    def event(self, kind: str, **data):
        if kind == "error" and data.get("src") is None:
            self.log.error(data.get("text", ""))
        with self.lock:
            self.event_id += 1
            ev = {"id": self.event_id, "kind": kind, "t": time.time(), **data}
            self.events.append(ev)
            if kind in self.feeds:
                self.feeds[kind].append(ev)
        try:
            self.keep(ev)
        except OSError as e:
            self.log.warning(f"could not keep {kind} in the archive: {e}")

    def keep(self, ev: dict):
        """Its thoughts (every decision, every reflection) and conversations go to the archive in full."""
        kind, ws, z = ev["kind"], self.world_state, self.cfg.name
        if kind not in ("decision", "reflection", "chat", "said"):
            return
        t = self.archive_t = max(ev["t"], getattr(self, "archive_t", 0.0) + 1e-6)   # unique: pages never skip one
        when = {"t": round(t, 6), "day": ws.get("day"), "time": ws.get("time", "")}
        if kind == "decision":
            d = ev.get("decision") or {}
            self.archive.add("thoughts", when | {"kind": "thought", "id": d.get("id"), "text": d.get("thought", ""),
                                                 "action": d.get("action"), "reason": d.get("reason"),
                                                 "ms": (d.get("ms") or {}).get("total_ms"), "adapter": d.get("adapter")})
        elif kind == "reflection":
            self.archive.add("thoughts", when | {"kind": "reflection", "text": ev.get("text", "")})
        elif kind == "chat":
            self.archive.add("conversations", when | {"with": ev.get("who") or "you", "kind": "chat",
                                                      "members": [ev.get("who") or "you", z],
                                                      "lines": [[ev.get("who") or "you", ev.get("text", "")]]})
        elif kind == "said" and (ev.get("text") or "").strip():
            self.archive.add("conversations", when | {"with": ev.get("to") or "world", "kind": "said", "members": [z],
                                                      "lines": [[z, ev.get("text", "")]]})

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
                with self.perf.time("handling messages"):
                    self.on_message(msg)
            except Exception as e:
                self.log.exception("could not handle a message")
                self.event("error", text=f"Hub: {type(e).__name__}: {e}")

    def on_message(self, m: dict):
        t = m["type"]
        if t == "reply":
            f = self.waiters.pop(m["rid"], None)
            if f and not f.done():
                f.set_exception(RuntimeError(m["error"])) if m.get("error") else f.set_result(m.get("result"))
        elif t == "world":
            self._merge_world(m["snap"])
        elif t == "mind":
            with self.lock:
                self.mind = m["mind"]
                self.world_seq += 1
                self.world_msgs.append((self.world_seq, {"mind": self.mind}))
        elif t in ("log", "error"):
            self.event("error" if t == "error" or m.get("error") else "log", text=m["text"], src=m["src"])
        elif t == "event":
            kind = m["kind"]
            data = {k: v for k, v in m.items() if k not in ("src", "type", "t", "kind")}
            if kind == "practice_request":
                self.start_practice(data.get("by", "self"))
            elif kind == "use_adapter":
                err = self.coach.use(data.get("name"))
                if err:
                    self.event("log", text=f"couldn't switch adapters: {err}", src="hub")
                else:
                    self.cfg.save(self.folder / "config.json")
            else:
                self.event(kind, **data)
        elif t == "perf":
            self.perf_latest[m["src"]] = m["perf"]
            self.perf_history.append((m["t"], m["src"], m["perf"]))

    def _merge_world(self, snap: dict):
        for h in snap.get("events") or []:
            self.event("happening", **(h if isinstance(h, dict) else {"text": str(h)}))
        with self.lock:
            if snap.get("full"):
                self.world_ents = {e["id"]: e for e in snap.get("entities", [])}
                self.world_state = {k: v for k, v in snap.items() if k not in ("entities", "removed", "blocks", "events")}
            else:
                for e in snap.get("entities", []):
                    self.world_ents[e["id"]] = e
                for i in snap.get("removed", []):
                    self.world_ents.pop(i, None)
                for k, v in snap.items():
                    if k not in ("entities", "removed", "blocks", "events", "full"):
                        self.world_state[k] = v
            self.world_seq += 1
            self.world_msgs.append((self.world_seq, snap))

    def world_full(self) -> dict:
        with self.lock:
            return dict(self.world_state, entities=list(self.world_ents.values()), removed=[], blocks=[], events=[],
                        mind=self.mind, full=True)

    def world_delta(self, since: int) -> tuple[int, dict | None]:
        """Everything that changed in the world since `since`, merged into one message. Block changes
        are kept in order; a page that fell too far behind gets a full snapshot (and reloads its chunks)."""
        with self.lock:
            if not self.world_msgs or since >= self.world_seq:
                return self.world_seq, None
            if since < self.world_msgs[0][0] - 1 or any(m.get("full") for s, m in self.world_msgs if s > since):
                return self.world_seq, self.world_full()
            ents, removed, blocks, events, out = {}, set(), [], [], {}
            for s, m in self.world_msgs:
                if s <= since:
                    continue
                for e in m.get("entities", []):
                    ents[e["id"]] = e
                    removed.discard(e["id"])
                for i in m.get("removed", []):
                    removed.add(i)
                    ents.pop(i, None)
                blocks += m.get("blocks", [])
                events += m.get("events", [])
                out.update({k: v for k, v in m.items() if k not in ("entities", "removed", "blocks", "events")})
            out.update(entities=list(ents.values()), removed=list(removed), blocks=blocks, events=events)
            return self.world_seq, out

    # ------------------------------------------------------------------ its model
    def _model_tick(self):
        """Keep its model running with the right adapter, and tell the World where it is."""
        m = self.cfg.mind
        if not self.coach.running and not self.local.busy:
            adapter = self.coach.adapter_path()
            if self.local.wants(m.model, model_threads(self.cfg), adapter, m.gpu):
                threading.Thread(target=self.local.ensure, args=(m.model, model_threads(self.cfg), m.context, 2,
                                                                 adapter, m.gpu), name="model-setup", daemon=True).start()
        state = (self.local.ready, self.local.url, self.local.adapter.stem if self.local.adapter else None, self.local.device)
        if state != self.model_sent:
            self.model_sent = state
            self.send("world", "model", ready=state[0], url=state[1] if state[0] else "", adapter=state[2],
                      device=state[3], label=self.local.label())

    def _model_log(self, text: str, level: str = "info"):
        if level == "warning":
            self.log.warning(text)
            self.event("error", text=f"{self.cfg.name}'s mind: {text}", src="hub")
        else:
            self.log.info(text)
            self.event("log", text=text, src="hub")

    # ------------------------------------------------------------------ practice
    def _last_practice_t(self) -> float:
        ts = [a.get("created") or 0 for a in self.coach.adapters()]
        return max(ts, default=0.0)

    def start_practice(self, by: str) -> str | None:
        err = self.coach.start(by, self._free_gpu, since=self.last_practice_t)
        if err:
            self.send("world", "practice", event="refused", error=err)
            self.event("log", text=f"practice: {err}", src="hub")
        return err

    def _free_gpu(self):
        self.local.stop()
        self.model_sent = None

    def _practice_changed(self, what: str, data: dict):
        if what == "practice_done":
            self.last_practice_t = data["info"].get("created", time.time())
            self.cfg.save(self.folder / "config.json")
        self.send("world", "practice", event=what.replace("practice_", ""), **data)
        self.event(what, **data)

    def practice(self, action: str, name=None, value=None):
        if action == "start":
            err = self.start_practice("visitor")
        elif action == "stop":
            self.coach.stop()
            err = None
        elif action == "install":
            err = self.coach.install()
        elif action == "auto":
            self.set("mind.practice_auto", bool(value))
            err = None
        elif action == "use":
            err = self.coach.use(name or None)
            if not err:
                self.cfg.save(self.folder / "config.json")
                self.send("world", "practice", event="switched", name=name or None)
        else:
            err = f"unknown practice action {action}"
        if err:
            raise ValueError(err)
        return self.model_info()

    def model_info(self) -> dict:
        learning = (self.mind or {}).get("learning") or {}
        counts = learning.get("counts") or {}
        return self.local.info() | {"catalog": self.local.catalog(), "choice": self.cfg.mind.model,
                                    "practice": self.coach.info({"examples": counts.get("examples", 0),
                                                                 "good": counts.get("good", 0),
                                                                 "bad": counts.get("bad", 0),
                                                                 "since": learning.get("since", 0)})}

    # ------------------------------------------------------------------ diagnostics
    def _diagnose_tick(self):
        now = time.time()
        if now - getattr(self, "_last_diag", 0) < 10:
            return
        self._last_diag = now
        self._last_diag_prev = getattr(self, "_last_diag_prev", self.started)
        self.gpu = gpu_readings()
        self.perf.gauge("kb_sent_to_browsers_per_s", round(self.ws_bytes / 1024 / max(1.0, now - self._last_diag_prev), 1))
        self.ws_bytes, self._last_diag_prev = 0, now
        try:
            self.perf.gauge("outbox_backlog", self.outbox.qsize())
        except (NotImplementedError, OSError):
            pass
        stats = (self.mind or {}).get("stats") or {}
        if stats.get("avg_ms") is not None:
            self.perf.gauge("decision_ms", stats["avg_ms"])
        hub_perf = self.perf.take()
        self.perf_latest["hub"] = hub_perf
        self.perf_history.append((now, "hub", hub_perf))
        if self.gpu:
            self.perf_history.append((now, "gpu", {"gpu": self.gpu}))
        client = self.client_perf if now - self.client_perf.get("t", 0) < 60 else None
        self.findings = findings(self.perf_latest, self.gpu, client, self.restarts)
        for f in self.findings:
            key = f["where"] + f["text"][:50]
            if now - self._finding_seen.get(key, 0) > 600:
                self._finding_seen[key] = now
                (self.log.error if f["level"] == "error" else self.log.warning if f["level"] == "warn"
                 else self.log.info)(f"[{f['where']}] {f['text']}")

    def record_client_perf(self, p: dict):
        p["t"] = time.time()
        self.client_perf = p
        self.perf_history.append((p["t"], "browser", p))

    def health(self) -> dict:
        return {"perf": self.perf_latest, "gpu": self.gpu, "browser": self.client_perf, "findings": self.findings,
                "processes": {n: {"alive": p.is_alive(), "pid": p.pid, "restarts": self.restarts[n], "exitcode": p.exitcode}
                              for n, p in self.procs.items()},
                "model": self.local.info(), "decisions": (self.mind or {}).get("stats"),
                "log": self.log_tail(80, min_level="WARNING"), "uptime_s": round(time.time() - self.started)}

    def log_tail(self, n: int = 200, min_level: str = "") -> list[str]:
        """The most recent lines of every process's log, newest last."""
        levels = ("WARNING", "ERROR", "CRITICAL")
        lines = []
        for f in sorted((self.folder / "logs").glob("*.log")):
            try:
                text = f.read_text(encoding="utf-8", errors="replace").splitlines()[-2000:]
            except OSError:
                continue
            entry = None
            for line in text:
                if line[:4].isdigit() and line[4:5] == "-":
                    entry = [line[:23], f.stem, line]
                    lines.append(entry)
                elif entry is not None:
                    entry[2] += "\n" + line
        if min_level:
            lines = [e for e in lines if any(f" {lv} " in e[2][:40] for lv in levels)]
        lines.sort(key=lambda e: e[0])
        return [e[2] for e in lines[-n:]]

    def report(self) -> str:
        """Everything useful for diagnosing a problem, as one text file."""
        from . import __version__

        def block(title, obj):
            return f"\n===== {title} =====\n" + (obj if isinstance(obj, str) else json.dumps(obj, indent=2, default=str)) + "\n"

        out = [f"Synthetic Mind diagnostics report · version {__version__} · {time.strftime('%Y-%m-%d %H:%M:%S %z')} · "
               f"'{self.cfg.name}' · Hub up {round((time.time() - self.started) / 60)} min\n"]
        out.append(block("Likely bottlenecks and problems", "\n".join(f"[{f['level']}] {f['where']}: {f['text']}"
                                                                    for f in self.findings) or "none detected"))
        out.append(block("System", system_info()))
        out.append(block("GPU (nvidia-smi)", self.gpu or "no NVIDIA GPU readings"))
        out.append(block("Processes", self.health()["processes"]))
        out.append(block("Its model", {k: v for k, v in self.model_info().items() if k != "catalog"}))
        out.append(block("Its mind", {k: (self.mind or {}).get(k) for k in ("stats", "learning", "goal", "busy_with")}))
        out.append(block("Latest timings per process", self.perf_latest))
        out.append(block("Browser", self.client_perf or "the page hasn't reported yet (keep it open for 15 s)"))
        w = self.world_state
        out.append(block("World", {k: w.get(k) for k in ("day", "time", "weather", "agent")}))
        out.append(block("Settings", self.cfg.to_dict()))
        out.append(block("Warnings and errors (all processes, newest last)", "\n".join(self.log_tail(300, "WARNING")) or "none"))
        out.append(block("Recent log (all processes, newest last)", "\n".join(self.log_tail(150))))
        text = "".join(out)
        try:
            (self.folder / "logs" / "diagnostics-latest.txt").write_text(text, encoding="utf-8")
        except OSError:
            pass
        return text

    # ------------------------------------------------------------------ settings
    def set(self, key: str, value):
        v = set_live(self.cfg, key, value)
        self.cfg.save(self.folder / "config.json")
        for n in CHILDREN:
            self.send(n, "config", config=self.cfg.to_dict())
        return v

    def settings(self) -> dict:
        return get_live(self.cfg)

    def init_payload(self) -> dict:
        from . import __version__

        with self.lock:
            return {"type": "init", "name": self.cfg.name, "version": __version__, "settings": self.settings(),
                    "world": self.world_full(), "world_seq": self.world_seq, "model": self.model_info(),
                    "feeds": {k: list(v) for k, v in self.feeds.items()}, "event_id": self.event_id,
                    "events": [e for e in self.events if e["kind"] in ("error", "log")][-20:]}
