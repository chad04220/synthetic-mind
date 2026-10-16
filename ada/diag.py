"""Diagnostics: an error/warning log for every process, and timings that show where time goes.

Every process (Hub, Academy, World) writes its errors, warnings and uncaught exceptions to
minds/<name>/logs/<process>.log (rotated, UTF-8). Each process also times its own work with
`Perf` and sends a summary to the Hub every few seconds; the Hub adds GPU readings and the
browser's own frame timings, flags likely bottlenecks, and can write everything into one
report file to share.
"""
from __future__ import annotations

import logging
import logging.handlers
import platform
import sys
import threading
import time
import warnings
from contextlib import contextmanager
from pathlib import Path

_FMT = "%(asctime)s %(levelname)-7s %(processName)s/%(threadName)s %(name)s: %(message)s"


def setup_logging(process: str, folder: Path) -> logging.Logger:
    """Log warnings, errors and uncaught exceptions of this process to logs/<process>.log."""
    logs = folder / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    for h in list(root.handlers):
        if getattr(h, "_ada", False):
            root.removeHandler(h)
            h.close()
    h = logging.handlers.RotatingFileHandler(logs / f"{process}.log", maxBytes=2 << 20, backupCount=3, encoding="utf-8")
    h._ada = True
    h.setFormatter(logging.Formatter(_FMT))
    h.setLevel(logging.INFO)
    root.addHandler(h)
    root.setLevel(logging.WARNING)                 # libraries: warnings and errors only
    logging.getLogger("ada").setLevel(logging.INFO)  # Ada's own processes: also what they're doing
    # Python warnings (including PyTorch's, which arrive as warnings) go to the log, each once.
    logging.captureWarnings(True)
    warnings.simplefilter("default")

    log = logging.getLogger(f"ada.{process}")

    def excepthook(t, v, tb):
        log.critical("uncaught exception", exc_info=(t, v, tb))
        sys.__excepthook__(t, v, tb)

    def thread_excepthook(args):
        log.critical(f"uncaught exception in thread {args.thread.name if args.thread else '?'}",
                     exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = excepthook
    threading.excepthook = thread_excepthook
    log.info(f"{process} started: Python {platform.python_version()} on {platform.platform()}")
    return log


class Perf:
    """Accumulates how long named activities take; `take()` returns a summary and starts over."""

    def __init__(self):
        self.lock = threading.Lock()
        self.stats: dict[str, list] = {}       # name -> [count, total seconds, max seconds]
        self.values: dict[str, float] = {}     # gauges: latest value of something
        self.t0 = time.perf_counter()
        self.cpu0 = time.process_time()

    @contextmanager
    def time(self, name: str):
        t = time.perf_counter()
        try:
            yield
        finally:
            self.add(name, time.perf_counter() - t)

    def add(self, name: str, seconds: float):
        with self.lock:
            s = self.stats.setdefault(name, [0, 0.0, 0.0])
            s[0] += 1
            s[1] += seconds
            s[2] = max(s[2], seconds)

    def gauge(self, name: str, value: float):
        self.values[name] = value

    def take(self) -> dict:
        with self.lock:
            now, cpu = time.perf_counter(), time.process_time()
            wall = max(now - self.t0, 1e-6)
            out = {
                "window_s": round(wall, 1),
                "cpu_percent": round(100 * (cpu - self.cpu0) / wall, 1),   # of one core
                "timings": {k: {"per_s": round(c / wall, 2), "avg_ms": round(1000 * t / max(c, 1), 2),
                                "max_ms": round(1000 * m, 1), "share": round(t / wall, 3)}
                            for k, (c, t, m) in self.stats.items()},
                "gauges": dict(self.values),
            }
            rss = memory_mb()
            if rss:
                out["gauges"]["memory_mb"] = rss
            self.stats, self.t0, self.cpu0 = {}, now, cpu
            return out


def memory_mb() -> float | None:
    try:
        import psutil

        return round(psutil.Process().memory_info().rss / 2**20, 1)
    except Exception:
        try:
            import resource

            return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
        except Exception:
            return None


def gpu_readings() -> list[dict]:
    """Utilisation, memory, temperature and power of each NVIDIA GPU (empty without nvidia-smi)."""
    import shutil
    import subprocess

    if not shutil.which("nvidia-smi"):
        return []
    q = "name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,clocks.sm,driver_version"
    try:
        out = subprocess.run(["nvidia-smi", f"--query-gpu={q}", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    gpus = []
    for line in out.strip().splitlines():
        p = [x.strip() for x in line.split(",")]
        if len(p) < 8:
            continue

        def num(x):
            try:
                return float(x)
            except ValueError:
                return None

        gpus.append({"name": p[0], "util_percent": num(p[1]), "mem_used_mb": num(p[2]), "mem_total_mb": num(p[3]),
                     "temp_c": num(p[4]), "power_w": num(p[5]), "sm_clock_mhz": num(p[6]), "driver": p[7]})
    return gpus


def findings(perf: dict, gpu: list, client: dict | None, restarts: dict) -> list[dict]:
    """Plain-language guesses at bottlenecks from the latest measurements."""
    out = []

    def add(level, where, text):
        out.append({"level": level, "where": where, "text": text})

    ac, wo, hub = perf.get("academy") or {}, perf.get("world") or {}, perf.get("hub") or {}
    at, wt, ht = ac.get("timings", {}), wo.get("timings", {}), hub.get("timings", {})
    ag, wg, hg = ac.get("gauges", {}), wo.get("gauges", {}), hub.get("gauges", {})
    studying = ag.get("studying")
    if studying and at.get("wait for data", {}).get("share", 0) > 0.15:
        add("warn", "academy", "The Academy spends {:.0%} of its time waiting for training data. FineWeb may be downloading "
            "slowly; lessons and drills keep it going.".format(at["wait for data"]["share"]))
    if studying and gpu and gpu[0].get("util_percent") is not None and gpu[0]["util_percent"] < 50 and ag.get("device") == "cuda":
        add("info", "academy", f"The GPU is only {gpu[0]['util_percent']:.0f}% busy while studying: the CPU side (data, Python) "
            "is the limit. A bigger batch or brain would use the GPU better.")
    test, used = ag.get("gpu_test_tflops"), ag.get("training_tflops")
    if studying and test and used is not None and used < 0.08 * test:
        why = ("GPU memory is nearly full, so Windows is probably spilling it into ordinary RAM, which is very slow"
               if ag.get("gpu_free_mb") is not None and ag["gpu_free_mb"] < 600 else
               "see the step profile below: forward, loss over the vocabulary, backward")
        add("warn", "academy", f"Training uses about {used:.1f} of the {test:.0f} TFLOPS this GPU reached in a quick test "
            f"({used / test:.0%}). Something is holding it back: {why}.")
    if test is not None and test < 4 and ag.get("device") == "cuda":
        add("warn", "gpu", f"The GPU managed only {test:.1f} TFLOPS in the start-up test. It may be in a power-saving state, "
            "throttling, or short of memory.")
    if studying and hg.get("ollama_gpu_mb", 0) > 500:
        add("warn", "gpu", f"Ollama is holding {hg['ollama_gpu_mb']:.0f} MB of GPU memory while the Academy studies. "
            "Settings → Ollama runs on: 'CPU' frees it.")
    if gpu and gpu[0].get("mem_total_mb") and gpu[0]["mem_used_mb"] / gpu[0]["mem_total_mb"] > 0.92:
        add("warn", "gpu", "GPU memory is over 92% full; Windows may start swapping it, which is very slow. Use a smaller "
            "batch or brain, or close other GPU programs (Ollama models also live in GPU memory).")
    if gpu and (gpu[0].get("temp_c") or 0) >= 85:
        add("warn", "gpu", f"The GPU is at {gpu[0]['temp_c']:.0f}°C and is probably slowing itself down to cool "
            f"(clock now {gpu[0].get('sm_clock_mhz') or '?'} MHz). That is safe, but training gets slower. On a laptop: "
            "plug it in, raise the back for airflow or use a cooling pad, and pick the high-performance power mode; "
            "or set GPU intensity to Balanced, which lets the GPU cool between steps.")
    if gpu and studying and (gpu[0].get("util_percent") or 0) > 95 and client and client.get("fps", 60) < 20:
        add("warn", "browser", "The GPU is fully busy training and the page is drawing slowly: the browser shares that GPU. "
            "Set GPU intensity to Balanced or Gentle, or watch while Ada is awake.")
    late = wt.get("tick", {})
    if late and late.get("avg_ms", 0) > 250:
        add("warn", "world", f"World steps take {late['avg_ms']:.0f} ms on average (they should be under 250 ms); the World "
            "is running behind. Ada's brain may be on a busy device.")
    slow = {k: v for k, v in wt.items() if k.startswith("brain: ") and k != "brain: waiting in line"
            and k != "brain: load" and v.get("avg_ms", 0) > 1000}
    if slow:
        k, v = max(slow.items(), key=lambda kv: kv[1]["avg_ms"])
        tip = (" The GPU may be busy training; Settings → World device = cpu keeps her daily life off it."
               if wg.get("device") == "cuda" else "")
        add("info", "world", f"Her brain takes {v['avg_ms'] / 1000:.1f} s for '{k[7:]}' on {wg.get('device', '?')}. "
            f"The world no longer waits for it, but her replies arrive that much later.{tip}")
    lag = ht.get("event loop lag", {})
    if lag and lag.get("max_ms", 0) > 250:
        add("warn", "hub", f"The Hub's web server stalled for up to {lag['max_ms']:.0f} ms; something is starving it of CPU.")
    if hg.get("outbox_backlog", 0) > 500:
        add("warn", "hub", f"{hg['outbox_backlog']:.0f} messages are waiting for the Hub; it can't keep up.")
    if client:
        if client.get("fps") is not None and client["fps"] < 15 and client.get("visible"):
            add("warn", "browser", f"The page drew only {client['fps']:.0f} frames per second.")
        if client.get("longtask_ms", 0) > 1500:
            add("warn", "browser", f"The browser was frozen for {client['longtask_ms'] / 1000:.1f} s in total over the last "
                f"{client.get('window_s', 0):.0f} s (longest {client.get('longtask_max_ms', 0):.0f} ms). "
                "Check that hardware acceleration is on in the browser.")
        if client.get("draw_avg_ms", 0) > 12:
            add("info", "browser", f"Drawing the map takes {client['draw_avg_ms']:.0f} ms; 'The whole hollow' view or a smaller "
                "window is cheaper.")
    for proc, n in restarts.items():
        if n:
            add("error", proc, f"The {proc} process has crashed and restarted {n} time(s). The error is in logs/{proc}.log.")
    return out


def system_info() -> dict:
    info = {"python": sys.version.split()[0], "platform": platform.platform(), "processor": platform.processor(),
            "machine": platform.machine()}
    try:
        import os

        info["cpus"] = os.cpu_count()
        import psutil

        vm = psutil.virtual_memory()
        info["ram_gb"] = round(vm.total / 2**30, 1)
        info["ram_used_percent"] = vm.percent
    except Exception:
        pass
    return info
