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
from .config import AdaConfig, cpu_threads, get_live, set_live
from .diag import Perf, findings, gpu_readings, setup_logging, system_info
from .localllm import LocalLLM
from .ontology import NPCS
from .oracle import TOPICS, Oracle
from .proc import append_jsonl
from .villagers import Villagers
from .journey import Journey

CHILDREN = {"academy": academy.run, "world": life.run}


class Hub:
    def __init__(self, cfg: AdaConfig, root: Path):
        self.cfg = cfg
        self.root = root
        self.folder = root / cfg.name
        self.folder.mkdir(parents=True, exist_ok=True)
        cfg.save(self.folder / "config.json")
        self.log = setup_logging("hub", self.folder)
        self.perf = Perf()
        self.perf_latest: dict[str, dict] = {}          # process -> latest timings
        self.perf_history: deque = deque(maxlen=720)    # (t, process, timings)
        self.gpu: list[dict] = []
        self.client_perf: dict = {}
        self.findings: list[dict] = []
        self._finding_seen: dict[str, float] = {}
        self.started = time.time()
        self.ws_bytes = 0
        self.ollama_loaded: list[dict] = []
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
                      (("thought", 80), ("chat", 200), ("oracle", 60), ("lesson", 60), ("npc", 120), ("deed", 80),
                       ("talk", 60), ("vthought", 120), ("vdid", 160), ("ada_says", 60))}
        self.gallery: dict[int, dict] = {}            # every work made in the valley, by id
        self.journey = Journey(self.folder, cfg.name)
        self.concept_report: dict = {}
        self._load_history()

        # the Oracle and the villagers' voices: one llama.cpp server each
        voices = Path(__file__).resolve().parent.parent / "oracle"
        self.fleet: dict[str, LocalLLM] = {"oracle": LocalLLM(voices, self._local_log, "oracle")}
        for n in NPCS:
            self.fleet[n] = LocalLLM(voices, self._local_log, n)
        self.local = self.fleet["oracle"]
        self.villagers = Villagers(self, self.folder)
        self.last_banter = time.time()
        self.oracle = Oracle(cfg.oracle.url, cfg.oracle.model, self.local)
        self.oracle.backend = cfg.oracle.backend
        self.oracle.name = cfg.name
        self.oracle.cpu_threads = cpu_threads(cfg)["oracle"]
        self.pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="oracle")
        self.voice_pool = ThreadPoolExecutor(max_workers=16, thread_name_prefix="voice")   # the gate limits the work
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
        self.voice_pool.shutdown(wait=False, cancel_futures=True)
        closers = [threading.Thread(target=server.close, daemon=True) for server in self.fleet.values()]
        for t in closers:
            t.start()
        for t in closers:
            t.join(20)
        try:
            self.villagers.save()
        except OSError:
            pass

    def _supervise(self):
        while not self.stopping:
            time.sleep(1.0)
            for n, p in list(self.procs.items()):
                if not p.is_alive() and not self.stopping:
                    self.restarts[n] += 1
                    wait = min(60, 3 * self.restarts[n])
                    self.event("error", text=f"The {n} process stopped (exit code {p.exitcode}); restarting in {wait}s. "
                                             f"Details are in minds/{self.cfg.name}/logs/{n}.log")
                    time.sleep(wait)
                    if not self.stopping:
                        self.spawn(n)
            self.apply_schedule()
            self._local_tick()
            self._diagnose_tick()
            if (self.cfg.oracle.enabled and self.cfg.oracle.backend == "ollama" and not self.oracle.models
                    and time.time() - self.last_refresh > 30):
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
        if kind == "error" and data.get("src") is None:
            self.log.error(data.get("text", ""))
        with self.lock:
            self.event_id += 1
            ev = {"id": self.event_id, "kind": kind, "t": time.time(), **data}
            self.events.append(ev)
            if kind in self.feeds:
                self.feeds[kind].append(ev)
        if kind != "milestone":
            for m in self.journey.observe(ev, self.world_state.get("day")):
                self.event("milestone", **m)

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
            villagers = m["purpose"] in ("npc", "visitor_npc", "banter", "lesson", "intent", "thought", "turn", "create")
            (self.voice_pool if villagers else self.pool).submit(self._world_oracle, m)
        elif t == "perf":
            self.perf_latest[m["src"]] = m["perf"]
            self.perf_history.append((m["t"], m["src"], m["perf"]))

    def _merge_world(self, snap: dict):
        works = snap.pop("creations", None)
        with self.lock:
            for c in works or []:
                self.gallery[c["id"]] = c
            if works and not snap.get("full"):
                snap["creations"] = works
            if snap.get("full"):
                self.world_ents = {e["id"]: e for e in snap["ents"]}
                self.world_state = {k: v for k, v in snap.items() if k not in ("ents", "removed", "creations")}
            else:
                for e in snap["ents"]:
                    self.world_ents[e["id"]] = e
                for i in snap["removed"]:
                    self.world_ents.pop(i, None)
                for k, v in snap.items():
                    if k not in ("ents", "removed", "creations"):
                        self.world_state[k] = v
            self.world_seq += 1
            self.world_msgs.append((self.world_seq, snap))

    def world_full(self) -> dict:
        with self.lock:
            return dict(self.world_state, ents=list(self.world_ents.values()), removed=[], full=True,
                        creations=list(self.gallery.values()))

    def world_delta(self, since: int) -> tuple[int, dict | None]:
        """Everything that changed in the world since `since`, merged into one message."""
        with self.lock:
            if not self.world_msgs or since >= self.world_seq:
                return self.world_seq, None
            if since < self.world_msgs[0][0] - 1 or any(m.get("full") for s, m in self.world_msgs if s > since):
                return self.world_seq, self.world_full()
            ents, removed, out, works = {}, set(), {}, {}
            for s, m in self.world_msgs:
                if s <= since:
                    continue
                for c in m.get("creations", []):
                    works[c["id"]] = c
                for e in m["ents"]:
                    ents[e["id"]] = e
                    removed.discard(e["id"])
                for i in m["removed"]:
                    removed.add(i)
                    ents.pop(i, None)
                out.update({k: v for k, v in m.items() if k not in ("ents", "removed", "creations")})
            out["ents"], out["removed"] = list(ents.values()), list(removed)
            if works:
                out["creations"] = list(works.values())
            return self.world_seq, out

    # ------------------------------------------------------------------ schedule
    def apply_schedule(self):
        s = self.cfg.schedule
        if s.mode == "day_night":
            want = ("resume", "full") if self.phase == "night" else \
                (("resume", "gentle") if s.day_training == "gentle" else ("pause", "Ada is awake"))
        elif s.mode == "together":
            # With her brain on the CPU, living doesn't touch the GPU: training can have all of it.
            want = ("resume", "full" if self.cfg.world.device == "cpu" else "balanced")
        elif s.mode == "academy":
            want = ("resume", "full")
        else:
            want = ("pause", "live-only mode")
        studying = want[0] == "resume"
        place = self.cfg.oracle.placement
        use_gpu = place == "gpu" or (place == "auto" and not studying)
        if use_gpu != self.oracle.use_gpu or want != self.academy_wanted and not use_gpu:
            self.oracle.use_gpu = use_gpu
            if not use_gpu:
                self.pool.submit(self._free_oracle_gpu)
        if want != self.academy_wanted:
            self.academy_wanted = want
            if want[0] == "resume":
                self.send("academy", "resume", intensity=want[1] if want[1] != "full" else None)
            else:
                self.send("academy", "pause", why=want[1])

    # ------------------------------------------------------------------ diagnostics
    def _diagnose_tick(self):
        now = time.time()
        if now - getattr(self, "_last_diag", 0) < 10:
            return
        self._last_diag = now
        self._last_diag_prev = getattr(self, "_last_diag_prev", self.started)
        self.gpu = gpu_readings()
        if self.oracle.models:
            self.ollama_loaded = self.oracle.loaded()
            self.perf.gauge("ollama_gpu_mb", sum(m["vram_mb"] for m in self.ollama_loaded))
            self.perf.gauge("oracle_on_gpu", 1 if self.oracle.use_gpu else 0)
        self.perf.gauge("kb_sent_to_browsers_per_s", round(self.ws_bytes / 1024 / max(1.0, now - self._last_diag_prev), 1))
        self.ws_bytes, self._last_diag_prev = 0, now
        try:
            self.perf.gauge("outbox_backlog", self.outbox.qsize())
        except (NotImplementedError, OSError):
            pass
        hub_perf = self.perf.take()
        self.perf_latest["hub"] = hub_perf
        self.perf_history.append((now, "hub", hub_perf))
        if self.gpu:
            self.perf_history.append((now, "gpu", {"gpu": self.gpu}))
        client = self.client_perf if now - self.client_perf.get("t", 0) < 60 else None
        self.findings = findings(self.perf_latest, self.gpu, client, self.restarts)
        for f in self.findings:
            key = f["where"] + f["text"][:50]
            if now - self._finding_seen.get(key, 0) > 600:   # log each finding at most every 10 minutes
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
                if line[:4].isdigit() and line[4:5] == "-":       # a new entry (tracebacks continue it)
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

        out = [f"Ada diagnostics report · version {__version__} · {time.strftime('%Y-%m-%d %H:%M:%S %z')} · "
               f"mind '{self.cfg.name}' · Hub up {round((time.time() - self.started) / 60)} min\n"]
        out.append(block("Likely bottlenecks and problems", "\n".join(f"[{f['level']}] {f['where']}: {f['text']}"
                                                                    for f in self.findings) or "none detected"))
        out.append(block("System", system_info()))
        out.append(block("GPU (nvidia-smi)", self.gpu or "no NVIDIA GPU readings"))
        out.append(block("Processes", self.health()["processes"]))
        out.append(block("Latest timings per process (avg/max ms, calls per second, share of wall time)", self.perf_latest))
        out.append(block("Browser", self.client_perf or "the page hasn't reported yet (keep it open for 15 s)"))
        a = self.academy_status
        out.append(block("Academy", {k: a.get(k) for k in ("paused", "pause_reason", "line", "intensity", "step", "tokens",
                                                            "tps", "loss", "val", "bpb", "stage_name", "params", "layers",
                                                            "device", "precision", "tokenizer", "version", "mix", "pools",
                                                            "fineweb", "skipped")}))
        w = self.world_state
        out.append(block("World", {"day": w.get("day"), "phase": w.get("phase"), "mind": w.get("mind"),
                                   "ada": {k: (w.get("ada") or {}).get(k) for k in ("place", "needs", "sleeping")}}))
        out.append(block("Oracle", {k: v for k, v in self.oracle_info().items() if k != "models"} |
                         {"models": [m["name"] for m in self.oracle.models], "runs_on_gpu": self.oracle.use_gpu,
                          "loaded_in_ollama": self.ollama_loaded}))
        out.append(block("Settings", self.cfg.to_dict()))
        def line(t, src, p):
            stamp = time.strftime("%H:%M:%S", time.localtime(t))
            if src == "gpu":
                g = p["gpu"][0]
                return f"{stamp} gpu      {g.get('util_percent')}% busy, {g.get('mem_used_mb')} MB, {g.get('temp_c')}°C, {g.get('power_w')} W"
            if src == "browser":
                return (f"{stamp} browser  {p.get('fps')} fps, worst gap {p.get('worst_frame_gap_ms')} ms, frozen "
                        f"{p.get('longtask_ms')} ms, draw {p.get('draw_avg_ms')} ms, view {p.get('view')}")
            top = sorted((p.get("timings") or {}).items(), key=lambda kv: -kv[1]["share"])[:4]
            return (f"{stamp} {src:<8} cpu {p.get('cpu_percent')}% | " +
                    "; ".join(f"{k} {v['avg_ms']}ms×{v['per_s']}/s ({v['share']:.0%}, max {v['max_ms']})" for k, v in top))

        recent = [line(t, s, p) for t, s, p in self.perf_history if time.time() - t < 1800]
        out.append(block("Timing history (last 30 minutes, top activities)", "\n".join(recent) or "none yet"))
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
        self.oracle.cpu_threads = cpu_threads(self.cfg)["oracle"]
        if key.startswith("oracle."):
            self.oracle.url, self.oracle.model = self.cfg.oracle.url.rstrip("/"), self.cfg.oracle.model
            self.oracle.backend = self.cfg.oracle.backend
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

    def _local_tick(self):
        """Keep the llama.cpp servers that are wanted running (one starting at a time), stop the rest."""
        o = self.cfg.oracle
        want: dict[str, tuple] = {}
        if o.enabled and o.backend == "builtin":
            want["oracle"] = (o.builtin_model, cpu_threads(self.cfg)["oracle"], 6144, 2)
            if not getattr(self, "_ollama_released", False):
                self._ollama_released = True
                self.pool.submit(self._release_ollama)
        else:
            self._ollama_released = False
        oracle_settled = "oracle" not in want or self.local.ready or self.local.status == "error"
        if o.enabled and o.villager_voices and oracle_settled:
            for n in NPCS:
                want[n] = (o.village_model, max(1, o.villager_threads), 2048, 1)
        starting = any(s.busy for s in self.fleet.values())
        for role, (model, threads, ctx, slots) in want.items():
            server = self.fleet[role]
            if not starting and server.wants(model, threads):
                threading.Thread(target=server.ensure, args=(model, threads, ctx, slots),
                                 name=f"voice-setup-{role}", daemon=True).start()
                starting = True
        for role, server in self.fleet.items():
            if role not in want and server.proc is not None and not server.busy:
                server.stop()
                self._local_log(f"stopped {server.who} (not in use)")
        if (o.enabled and o.banter and time.time() - self.last_banter > o.banter_seconds
                and self.world_state.get("phase") == "day"):
            self.last_banter = time.time()
            self.send("world", "banter")

    def _release_ollama(self):
        """With the built-in Oracle in use, free the memory an Ollama model we used still holds."""
        for m in self.oracle.loaded():
            if m["name"] == self.cfg.oracle.model and self.oracle.unload(m["name"]):
                self._local_log(f"asked Ollama to unload {m['name']} ({m['size_mb']} MB): the built-in Oracle is in use")

    def _local_log(self, text: str, level: str = "info"):
        if level == "warning":
            self.log.warning(text)
            self.event("error", text=f"Built-in Oracle: {text}", src="hub")
        else:
            self.log.info(text)
            self.event("log", text=text, src="hub")

    def _free_oracle_gpu(self):
        freed = self.oracle.unload_from_gpu()
        if freed:
            self.log.info(f"asked Ollama to free GPU memory for the Academy: {', '.join(freed)}")

    def _refresh_oracle(self):
        before = self.oracle.model
        self.oracle.refresh()
        if self.oracle.model and self.oracle.model != self.cfg.oracle.model:
            self.set("oracle.model", self.oracle.model)
        if self.oracle.models and not before:
            self.event("log", text=f"The Oracle is here: {self.oracle.model}", src="hub")

    def oracle_ready(self) -> bool:
        return self.cfg.oracle.enabled and self.oracle.ready

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
        """The World needs words from the Oracle or a villager: answer when they arrive (or a fallback)."""
        purpose, p, st = m["purpose"], m["payload"], self.stage
        text, extra = "", {}
        ctx = dict(p.get("ctx") or {}, stage=st)
        community = purpose in ("intent", "thought", "turn", "create")
        try:
            if community and not self.cfg.oracle.enabled:
                pass
            elif purpose == "intent":
                text = self.villagers.intent(p["npc"], p["perception"], ctx)
            elif purpose == "thought":
                text = self.villagers.thought(p["npc"], p["perception"], ctx)
            elif purpose == "turn":
                text = self.villagers.turn(p["speaker"], p["listener"], p["history"], p.get("topic", ""),
                                           p.get("opening", False), p.get("closing", False), ctx)
            elif purpose == "create":
                extra["work"] = self.villagers.create(p["npc"], p["creation"], ctx)
                text = extra["work"].get("title", "")
            elif purpose == "npc":
                if self.cfg.oracle.enabled and self.cfg.oracle.npc_voices:
                    text = self.villagers.to_synth(p["npc"], p.get("said", ""), ctx, p.get("kind", "talk"))
                else:
                    text = random.choice(NPCS[p["npc"]]["lines"])
            elif purpose == "visitor_npc":
                text = self.villagers.to_visitor(p["npc"], p["said"], ctx) if self.cfg.oracle.enabled else \
                    random.choice(NPCS[p["npc"]]["lines"])
            elif purpose == "lesson":
                topic = p.get("topic") or random.choice(TOPICS)
                ctx["topic"] = topic
                text = self.villagers.to_synth("Sage", "", ctx, "lesson") if self.cfg.oracle.enabled else ""
                if text:
                    self._curriculum("lesson", [("<|npc|>", f"Sage: {text}")], 2.0, True, topic)
                    self.event("lesson", topic=f"Sage's lesson: {topic}", text=text, qa=[], facts=[], new_facts=0,
                               priority=True)
                if self.oracle_ready() and len(self.topics) < 3:
                    self.topics.append(topic)          # and the Oracle writes a full lesson for the Academy
            elif purpose == "banter":
                if self.cfg.oracle.enabled:
                    extra["lines"] = self.villagers.banter(p["a"], p["b"], ctx)
                    text = " ".join(t for _, t in extra["lines"])
            elif self.oracle_ready():
                if purpose == "answer":
                    text = self.oracle.answer(p["question"], st, asker=self.cfg.name)
                elif purpose == "tutor" and self.cfg.oracle.tutor_replies:
                    text = self.oracle.tutor(p["history"], p["user"], p["mind"], st, self.cfg.name)
                elif purpose == "book":
                    text = self.oracle.book(st)
                elif purpose == "fact":
                    text = self.oracle.fact(p["topic"], st, self.cfg.name)
        except Exception as e:
            self.event("error", text=f"{'A villager' if purpose in ('npc', 'visitor_npc', 'banter') else 'The Oracle'} "
                                     f"({purpose}): {type(e).__name__}: {e}")
        if not text and purpose in ("npc", "visitor_npc"):
            text = random.choice(NPCS[p["npc"]]["lines"])
        if not text and purpose == "book":
            facts = self.graph.drill(random.Random())
            text = " ".join(t for _, t in facts)
        if text or community:
            self.send("world", "oracle_reply", req=m["rid"], text=text, **extra)
        if purpose in ("npc", "visitor_npc", "banter", "turn") and random.random() < 0.2:
            self.voice_pool.submit(self.villagers.save)

    def ask(self, question: str) -> str:
        """You ask the Oracle something."""
        answer = self.oracle.answer(question, 6, asker="you", name=self.cfg.name)
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
            for line in path.read_text(encoding="utf-8").splitlines()[-20000:]:
                try:
                    self.metrics.append(json.loads(line))
                except ValueError:
                    pass
        path = self.folder / "assessments.jsonl"
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines()[-500:]:
                try:
                    self.assessments.append(json.loads(line))
                except ValueError:
                    pass
        path = self.folder / "concept_report.json"
        if path.exists():
            try:
                self.concept_report = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                pass

    def init_payload(self) -> dict:
        with self.lock:
            return {
                "type": "init", "name": self.cfg.name, "settings": self.settings(),
                "academy": self.academy_status, "world": self.world_full(), "world_seq": self.world_seq,
                "metrics": list(self.metrics)[-4000:], "assessments": list(self.assessments),
                "feeds": {k: list(v) for k, v in self.feeds.items()}, "journey": self.journey.items,
                "concepts": self.concept_report, "event_id": self.event_id,
                "oracle": self.oracle_info(), "events": [e for e in self.events if e["kind"] in ("error", "log")][-20:],
            }

    def oracle_info(self) -> dict:
        builtin = self.cfg.oracle.backend == "builtin"
        return {"backend": self.cfg.oracle.backend, "active": self.oracle.active if self.oracle.ready else "",
                "builtin": self.local.info() | {"catalog": self.local.catalog(), "choice": self.cfg.oracle.builtin_model},
                "models": self.oracle.models, "model": self.oracle.model,
                "error": (self.local.error if builtin else self.oracle.error),
                "teaching": self.teaching, "lessons": self.lessons_written, "queued": list(self.topics),
                "enabled": self.cfg.oracle.enabled, "villagers": self.villagers.status()}
