"""The inhabitant's model: a llama.cpp server with a small instruct model, on the GPU when there is one.

Nothing to install by hand. On first use the Hub downloads llama.cpp's prebuilt server for this
computer (from llama.cpp's GitHub releases) and the chosen model (a GGUF file from Hugging Face)
into the `oracle/` folder next to run.py, starts `llama-server` on a free local port and keeps it
running. Which build:

- Windows with an NVIDIA card: the CUDA build (and its CUDA runtime files), every layer on the GPU;
- other Windows and Linux: the Vulkan build (NVIDIA, AMD and Intel GPUs), every layer on the GPU;
- macOS on Apple silicon: the regular build, which uses Metal;
- and when a GPU build is missing or fails to start, the CPU build.

Every decision is one request with a JSON schema, so the reply is always a valid action. The long
fixed instructions come first in every request and stay in the server's prompt cache: only the
observation is new, which keeps a decision at a fraction of a second.

Practice (see ada/agent/practice.py) produces LoRA adapters (GGUF); the server loads the active one
with `--lora`, and switching adapters restarts it (a few seconds).
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import socket
import subprocess
import tarfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

# key: label, GGUF repo and file and its size, the original weights (for Practice), and the
# family (how practice names its layers in the adapter). All ungated: no Hugging Face login.
CATALOG = {
    "qwen2.5-1.5b": dict(label="Qwen 2.5 1.5B Instruct (fast, recommended)", repo="Qwen/Qwen2.5-1.5B-Instruct-GGUF",
                         file="qwen2.5-1.5b-instruct-q4_k_m.gguf", size=1117320736, hf="Qwen/Qwen2.5-1.5B-Instruct",
                         family="qwen2"),
    "qwen2.5-3b": dict(label="Qwen 2.5 3B Instruct (smarter)", repo="Qwen/Qwen2.5-3B-Instruct-GGUF",
                       file="qwen2.5-3b-instruct-q4_k_m.gguf", size=2104932768, hf="Qwen/Qwen2.5-3B-Instruct",
                       family="qwen2"),
    "llama-3.2-3b": dict(label="Llama 3.2 3B Instruct", repo="bartowski/Llama-3.2-3B-Instruct-GGUF",
                         file="Llama-3.2-3B-Instruct-Q4_K_M.gguf", size=2019377696, hf="unsloth/Llama-3.2-3B-Instruct",
                         family="llama"),
    "llama-3.2-1b": dict(label="Llama 3.2 1B Instruct (fastest)", repo="bartowski/Llama-3.2-1B-Instruct-GGUF",
                         file="Llama-3.2-1B-Instruct-Q4_K_M.gguf", size=807694464, hf="unsloth/Llama-3.2-1B-Instruct",
                         family="llama"),
    "gemma-3-1b": dict(label="Gemma 3 1B Instruct", repo="ggml-org/gemma-3-1b-it-GGUF",
                       file="gemma-3-1b-it-Q4_K_M.gguf", size=806058240, hf="unsloth/gemma-3-1b-it", family="gemma3"),
    "qwen2.5-0.5b": dict(label="Qwen 2.5 0.5B Instruct (tiny, for weak computers)", repo="Qwen/Qwen2.5-0.5B-Instruct-GGUF",
                         file="qwen2.5-0.5b-instruct-q4_k_m.gguf", size=491400032, hf="Qwen/Qwen2.5-0.5B-Instruct",
                         family="qwen2"),
    "qwen2.5-7b": dict(label="Qwen 2.5 7B Instruct (needs 8 GB of GPU memory)", repo="bartowski/Qwen2.5-7B-Instruct-GGUF",
                       file="Qwen2.5-7B-Instruct-Q4_K_M.gguf", size=4683074240, hf="Qwen/Qwen2.5-7B-Instruct",
                       family="qwen2"),
}
DEFAULT_MODEL = "qwen2.5-1.5b"

# llama.cpp publishes a release many times a day, and each one appears before its files have
# finished uploading: look through the recent ones for the newest that has the file we need.
RELEASES = "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=20"
LATEST_PAGE = "https://github.com/ggml-org/llama.cpp/releases/latest"


def nvidia_gpu() -> dict | None:
    """The NVIDIA card, if there is one: {name, memory (MB)}."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip().splitlines()
        name, mem = out[0].rsplit(",", 1)
        return {"name": name.strip(), "memory": int(float(mem))}
    except Exception:  # noqa: BLE001 - no usable card
        return None


def builds(gpu: bool = True) -> list[dict]:
    """The llama.cpp builds to try on this computer, best first: {device, patterns (regexes for the
    release files: the program first, then any runtime it needs)}."""
    system, machine = platform.system(), platform.machine().lower()
    arm = machine in ("arm64", "aarch64")
    out = []
    if system == "Windows":
        if gpu and not arm and nvidia_gpu():
            out.append({"device": "cuda", "patterns": [r"^llama-.*-bin-win-cuda-(12\.\d+)-x64\.zip$",
                                                       r"^cudart-llama-bin-win-cuda-{v}-x64\.zip$"]})
        if gpu and not arm:
            out.append({"device": "vulkan", "patterns": [r"^llama-.*-bin-win-vulkan-x64\.zip$"]})
        out.append({"device": "cpu", "patterns": [rf"^llama-.*-bin-win-cpu-{'arm64' if arm else 'x64'}\.zip$"]})
    elif system == "Linux":
        if gpu and not arm:
            out.append({"device": "vulkan", "patterns": [r"^llama-.*-bin-ubuntu-vulkan-x64\.(tar\.gz|zip)$"]})
        out.append({"device": "cpu", "patterns": [rf"^llama-.*-bin-ubuntu-{'arm64' if arm else 'x64'}\.(tar\.gz|zip)$"]})
    elif system == "Darwin":
        out.append({"device": "metal" if arm and gpu else "cpu",
                    "patterns": [rf"^llama-.*-bin-macos-{'arm64' if arm else 'x64'}\.(tar\.gz|zip)$"]})
    return out


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LocalLLM:
    """One llama-server running the inhabitant's model."""

    _install = threading.Lock()      # one download at a time

    def __init__(self, folder: Path, log=None, role: str = "mind"):
        self.folder = folder
        self.role = role
        self.log = log or (lambda text, level="info": None)
        self.lock = threading.Lock()
        self.proc: subprocess.Popen | None = None
        self.url = ""
        self.model_key = ""
        self.threads = 0
        self.device = ""             # cuda | vulkan | metal | cpu, once running
        self.adapter: Path | None = None
        self.status = "off"          # off | waiting | downloading | starting | ready | error
        self.detail = ""
        self.progress = 0.0
        self.error = ""
        self.failed_at = 0.0
        self.busy = False
        self.ctx, self.slots = 8192, 2
        self.use_gpu = True
        self.bad_builds: set[str] = set()     # GPU builds that wouldn't start here
        self.closed = False
        self.name = ""

    # ------------------------------------------------------------------ state
    @property
    def ready(self) -> bool:
        return self.status == "ready" and self.proc is not None and self.proc.poll() is None

    @property
    def who(self) -> str:
        return self.name or "the inhabitant's model"

    def label(self, key: str | None = None) -> str:
        return CATALOG.get(key or self.model_key, {}).get("label", key or self.model_key)

    def catalog(self) -> list[dict]:
        return [{"name": k, "label": e["label"], "size": e["size"], "family": e["family"],
                 "downloaded": (self.folder / "models" / e["file"]).exists()} for k, e in CATALOG.items()]

    def info(self) -> dict:
        return {"role": self.role, "status": self.status, "detail": self.detail, "progress": round(self.progress, 3),
                "error": self.error, "model": self.model_key, "label": self.label() if self.model_key else "",
                "device": self.device, "threads": self.threads, "gpu": nvidia_gpu_cached(),
                "adapter": self.adapter.stem if self.adapter else None}

    def wants(self, key: str, threads: int, adapter: Path | None = None, gpu: bool = True) -> bool:
        """True when the server should be (re)started for this model, thread count and adapter."""
        if self.busy:
            return False
        same = (key, threads, adapter, gpu) == (self.model_key, self.threads, self.adapter, self.use_gpu)
        if self.ready and same:
            return False
        if self.status == "error" and same:
            return time.time() - self.failed_at > 300          # retry a failure every 5 minutes
        return True

    # ------------------------------------------------------------------ setup
    def ensure(self, key: str, threads: int, ctx: int = 8192, slots: int = 2, adapter: Path | None = None,
               gpu: bool = True) -> None:
        """Download what is missing and (re)start the server. Runs on a background thread."""
        with self.lock:
            if self.busy or self.closed:
                return
            self.busy = True
        try:
            key = key if key in CATALOG else DEFAULT_MODEL
            self.stop()
            self.model_key, self.threads, self.error, self.ctx, self.slots = key, threads, "", ctx, slots
            self.adapter = adapter if adapter and Path(adapter).exists() else None
            self.use_gpu = gpu
            self.status, self.detail = "waiting", "Waiting for downloads to finish"
            with LocalLLM._install:
                model = self._model(key)
            for build in builds(gpu):
                if build["device"] in self.bad_builds:
                    continue
                with LocalLLM._install:
                    exe = self._server(build)
                if exe is None:
                    continue
                try:
                    self._start(exe, model, threads, build["device"])
                    return
                except RuntimeError as e:
                    if build["device"] == "cpu" or self.closed:
                        raise
                    self.bad_builds.add(build["device"])
                    self.log(f"the {build['device']} build of llama.cpp didn't start here ({e}); trying the next", "warning")
            raise RuntimeError("no llama.cpp build for this computer would start; see the logs folder")
        except Exception as e:  # noqa: BLE001 - shown to the user, retried later
            self.status, self.error, self.failed_at = "error", f"{type(e).__name__}: {e}", time.time()
            self.detail = ""
            self.log(f"{self.who} failed: {self.error}", "warning")
        finally:
            self.busy = False

    def _find_exe(self, device: str) -> Path | None:
        name = "llama-server.exe" if os.name == "nt" else "llama-server"
        root = self.folder / f"llama.cpp-{device}"
        if not root.exists():
            return None
        found = sorted(root.rglob(name))
        return found[0] if found else None

    def _server(self, build: dict) -> Path | None:
        """The llama-server program of this build, downloaded if needed (None if it isn't published)."""
        device = build["device"]
        exe = self._find_exe(device)
        if exe:
            return exe
        try:
            tag, files = self._find_release(build["patterns"])
        except RuntimeError as e:
            if device == "cpu":
                raise
            self.log(f"no {device} build of llama.cpp to download ({e})", "warning")
            return None
        dest = self.folder / f"llama.cpp-{device}"
        tmp = self.folder / f"llama.cpp-{device}.tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        for url in files:
            archive = self.folder / "downloads" / url.rsplit("/", 1)[1]
            self._download(url, archive, f"llama.cpp {tag} for the {device.upper() if device != 'cpu' else 'CPU'}")
            if archive.name.endswith(".zip"):
                with zipfile.ZipFile(archive) as z:
                    z.extractall(tmp)
            else:
                with tarfile.open(archive) as t:
                    try:
                        t.extractall(tmp, filter="data")
                    except TypeError:                         # Python without extraction filters
                        t.extractall(tmp)
            archive.unlink(missing_ok=True)
        # a runtime archive (CUDA) belongs next to the program
        progs = sorted(tmp.rglob("llama-server.exe" if os.name == "nt" else "llama-server"))
        if not progs:
            raise RuntimeError(f"llama-server wasn't in the {device} build")
        for f in tmp.iterdir():
            if f.is_file() and f.parent != progs[0].parent:
                shutil.move(str(f), progs[0].parent / f.name)
        shutil.rmtree(dest, ignore_errors=True)
        tmp.replace(dest)
        exe = self._find_exe(device)
        if os.name != "nt":
            for f in exe.parent.iterdir():
                if f.is_file():
                    f.chmod(f.stat().st_mode | 0o111)
        self.log(f"installed llama.cpp {tag} ({device}) in {dest}")
        return exe

    def _find_release(self, patterns: list[str]) -> tuple[str, list[str]]:
        """The newest llama.cpp release that has every file this build needs: (tag, urls).
        A later pattern may use {v}: the first group the first pattern matched (the CUDA version)."""
        seen = []
        try:
            with self._get(RELEASES, timeout=20, headers={"Accept": "application/vnd.github+json"}) as r:
                releases = json.loads(r.read().decode())
            for rel in releases:
                if rel.get("draft"):
                    continue
                seen.append(rel.get("tag_name", "?"))
                assets = {a.get("name", ""): a.get("browser_download_url") for a in rel.get("assets", [])}
                urls, v = [], ""
                for p in patterns:
                    rx = re.compile(p.replace("{v}", re.escape(v)))
                    hits = sorted((n for n in assets if rx.match(n)), reverse=True)    # the newest CUDA first
                    if not hits:
                        break
                    if not v:
                        m = rx.match(hits[0])
                        v = m.group(1) if m and m.groups() else ""
                    urls.append(assets[hits[0]])
                if len(urls) == len(patterns):
                    return rel["tag_name"], urls
        except (urllib.error.URLError, OSError, ValueError) as e:
            self.log(f"couldn't list llama.cpp's releases on GitHub ({type(e).__name__}: {e})")
        if len(patterns) == 1:
            # Without the API (it allows 60 requests an hour), guess the file name from the latest tag.
            try:
                with self._get(LATEST_PAGE, timeout=20) as r:
                    tag = r.geturl().rstrip("/").rsplit("/", 1)[-1]
                name = patterns[0].strip("^$").replace(r"\.", ".").replace(".*", tag.join(["", ""]))
                name = re.sub(r"\((tar\.gz)\|zip\)", r"\1", name)
                if tag.startswith("b") and re.fullmatch(r"[\w.\-]+", name):
                    return tag, [f"https://github.com/ggml-org/llama.cpp/releases/download/{tag}/{name}"]
            except (urllib.error.URLError, OSError) as e:
                seen.append(f"latest page: {type(e).__name__}")
        raise RuntimeError(f"no llama.cpp release with {patterns[0]} found (looked at: {', '.join(seen[:8]) or 'nothing'})")

    def _model(self, key: str) -> Path:
        e = CATALOG[key]
        path = self.folder / "models" / e["file"]
        if not path.exists():
            self._download(f"https://huggingface.co/{e['repo']}/resolve/main/{e['file']}", path, e["label"])
        return path

    @staticmethod
    def _get(url: str, timeout: float = 30, headers: dict | None = None):
        req = urllib.request.Request(url, headers={"User-Agent": "ada-synthetic-mind", **(headers or {})})
        return urllib.request.urlopen(req, timeout=timeout)

    def _download(self, url: str, path: Path, what: str) -> None:
        """Download with progress, resuming a partial download if there is one."""
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_name(path.name + ".part")
        have = part.stat().st_size if part.exists() else 0
        self.status, self.detail, self.progress = "downloading", f"Downloading {what}", 0.0
        self.log(f"downloading {what} from {url}")
        try:
            r = self._get(url, timeout=60, headers={"Range": f"bytes={have}-"} if have else None)
        except urllib.error.HTTPError as e:
            e.close()
            raise RuntimeError(f"downloading {what} failed: HTTP {e.code} {e.reason} ({url})") from None
        with r:
            if have and r.status != 206:
                have = 0                                      # the server ignored the resume
            total = have + int(r.headers.get("Content-Length") or 0)
            with open(part, "ab" if have else "wb") as f:
                done = have
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if total:
                        self.progress = done / total
                        self.detail = f"Downloading {what}: {done / 2**20:.0f} of {total / 2**20:.0f} MB"
        part.replace(path)

    # ------------------------------------------------------------------ the server
    def _start(self, exe: Path, model: Path, threads: int, device: str) -> None:
        self.status, self.detail, self.progress = "starting", f"Starting {self.label()} ({device.upper()})", 0.0
        if self.closed:
            raise RuntimeError("shutting down")
        port = free_port()
        args = [str(exe), "-m", str(model), "--host", "127.0.0.1", "--port", str(port), "-t", str(threads),
                "-c", str(self.ctx), "-np", str(self.slots), "-ngl", "0" if device == "cpu" else "99", "--no-webui"]
        if device != "cpu":
            args += ["-fa", "on"] if not getattr(self, "_old_fa", False) else ["-fa"]
        if self.adapter:
            args += ["--lora", str(self.adapter)]
        (self.folder / "logs").mkdir(parents=True, exist_ok=True)
        logpath = self.folder / "logs" / f"llama-server-{self.role}.log"
        logf = open(logpath, "a", encoding="utf-8", errors="replace")
        logf.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} {' '.join(args)}\n")
        logf.flush()
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.proc = subprocess.Popen(args, stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                     cwd=str(exe.parent), creationflags=flags)
        logf.close()
        self._pid_file().write_text(str(self.proc.pid), encoding="utf-8")
        self.url = f"http://127.0.0.1:{port}"
        deadline = time.time() + 180
        while time.time() < deadline:
            if self.proc.poll() is not None:
                tail = logpath.read_text(encoding="utf-8", errors="replace")[-3000:]
                if "-fa" in args and not getattr(self, "_old_fa", False) and "flash" in tail.lower():
                    self._old_fa = True                       # an older llama.cpp: -fa takes no value
                    return self._start(exe, model, threads, device)
                raise RuntimeError(f"llama-server stopped (exit code {self.proc.returncode}); see {logpath}")
            try:
                with self._get(self.url + "/health", timeout=2) as r:
                    if r.status == 200:
                        self.status, self.detail, self.progress, self.device = "ready", "", 1.0, device
                        where = "on the CPU" if device == "cpu" else f"on the GPU ({device.upper()})"
                        extra = f" with practice adapter {self.adapter.stem}" if self.adapter else ""
                        self.log(f"{self.who} is ready: {self.label()} {where}{extra}")
                        return
            except (urllib.error.URLError, OSError) as e:
                if isinstance(e, urllib.error.HTTPError):
                    e.close()                                 # still loading the model (503)
            time.sleep(0.3)
        raise RuntimeError("llama-server didn't become ready within 3 minutes")

    def close(self) -> None:
        """Stop for good (the program is exiting), including a server that is still starting."""
        self.closed = True
        self.stop()
        deadline = time.time() + 15
        while self.busy and time.time() < deadline:
            time.sleep(0.1)
        self.stop()

    def stop(self) -> None:
        p, self.proc = self.proc, None
        if self.status == "ready":
            self.status, self.detail = "off", ""
        if p is not None and p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
        self.stop_leftover()

    def _pid_file(self) -> Path:
        return self.folder / f"llama-server-{self.role}.pid"

    def stop_leftover(self) -> None:
        """Stop a server left running by an earlier run that didn't shut down cleanly."""
        pid_file = self._pid_file()
        if not pid_file.exists():
            return
        try:
            import psutil

            p = psutil.Process(int(pid_file.read_text(encoding="utf-8").strip()))
            if "llama-server" in p.name().lower():
                p.terminate()
                p.wait(timeout=10)
        except Exception:  # noqa: BLE001 - already gone, or not ours
            pass
        pid_file.unlink(missing_ok=True)

    # ------------------------------------------------------------------ talking to it
    def chat(self, system: str, prompt: str, temperature: float = 0.7, max_tokens: int = 300,
             as_json: bool = False) -> str:
        body = {"messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                "temperature": temperature, "max_tokens": max_tokens}
        if as_json:
            body["response_format"] = {"type": "json_object"}
        return complete(self.url, body)["text"]


_gpu_cache: list = []


def nvidia_gpu_cached() -> dict | None:
    if not _gpu_cache:
        _gpu_cache.append(nvidia_gpu())
    return _gpu_cache[0]


def complete(url: str, body: dict, timeout: float = 120) -> dict:
    """One chat completion from a llama-server: {text, prompt_ms, predict_ms, cached, prompt_tokens,
    tokens}. Used by the Hub and directly by the World's mind (no queue between the mind and its model)."""
    if not url:
        raise RuntimeError("the model isn't running yet")
    body = {"stream": False, "cache_prompt": True, **body}
    req = urllib.request.Request(url + "/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read().decode())
    t = d.get("timings") or {}
    u = d.get("usage") or {}
    return {"text": ((d.get("choices") or [{}])[0].get("message") or {}).get("content", "") or "",
            "prompt_ms": t.get("prompt_ms"), "predict_ms": t.get("predicted_ms"),
            "cached": t.get("cache_n"), "prompt_tokens": u.get("prompt_tokens"), "tokens": u.get("completion_tokens")}
