"""The built-in Oracle: a llama.cpp server with a small model, running on the CPU.

Nothing to install by hand. On first use the Hub downloads llama.cpp's prebuilt server for this
computer (from llama.cpp's GitHub releases) and the chosen model (a GGUF file from Hugging Face)
into the `oracle/` folder next to run.py, starts `llama-server` on a free local port with the
Oracle's share of the CPU threads, and keeps it running. The GPU is never touched: the CPU build
of llama.cpp is used, so the GPU stays entirely with the Academy.

Ollama remains available as the other Oracle backend (Settings).
"""
from __future__ import annotations

import json
import os
import platform
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

# key: (label, Hugging Face repo, file, size in bytes). All ungated, so no Hugging Face login.
CATALOG = {
    "gemma-2-2b": ("Gemma 2 2B Instruct", "bartowski/gemma-2-2b-it-GGUF", "gemma-2-2b-it-Q4_K_M.gguf", 1708582752),
    "qwen2.5-1.5b": ("Qwen 2.5 1.5B Instruct (lightest)", "Qwen/Qwen2.5-1.5B-Instruct-GGUF",
                     "qwen2.5-1.5b-instruct-q4_k_m.gguf", 1117320736),
    "llama-3.2-3b": ("Llama 3.2 3B Instruct (strongest, slowest)", "bartowski/Llama-3.2-3B-Instruct-GGUF",
                     "Llama-3.2-3B-Instruct-Q4_K_M.gguf", 2019377696),
}
DEFAULT_MODEL = "gemma-2-2b"
# llama.cpp publishes a release many times a day, and each one appears before its files have
# finished uploading: look through the recent ones for the newest that has the file we need.
RELEASES = "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=20"
LATEST_PAGE = "https://github.com/ggml-org/llama.cpp/releases/latest"


def platform_asset() -> str | None:
    """The suffix of the llama.cpp release file with the CPU build for this computer."""
    system, machine = platform.system(), platform.machine().lower()
    arm = machine in ("arm64", "aarch64")
    if system == "Windows":
        return f"bin-win-cpu-{'arm64' if arm else 'x64'}.zip"
    if system == "Linux":
        return f"bin-ubuntu-{'arm64' if arm else 'x64'}.tar.gz"
    if system == "Darwin":
        return f"bin-macos-{'arm64' if arm else 'x64'}.tar.gz"
    return None


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LocalLLM:
    def __init__(self, folder: Path, log=None):
        self.folder = folder
        self.log = log or (lambda text, level="info": None)
        self.lock = threading.Lock()
        self.proc: subprocess.Popen | None = None
        self.url = ""
        self.model_key = ""
        self.threads = 0
        self.status = "off"          # off | downloading | starting | ready | error
        self.detail = ""
        self.progress = 0.0
        self.error = ""
        self.failed_at = 0.0
        self.busy = False

    # ------------------------------------------------------------------ state
    @property
    def ready(self) -> bool:
        return self.status == "ready" and self.proc is not None and self.proc.poll() is None

    def label(self, key: str | None = None) -> str:
        return CATALOG.get(key or self.model_key, (key or self.model_key,))[0]

    def catalog(self) -> list[dict]:
        out = []
        for key, (label, _repo, file, size) in CATALOG.items():
            out.append({"name": key, "label": label, "size": size,
                        "downloaded": (self.folder / "models" / file).exists()})
        return out

    def info(self) -> dict:
        return {"status": self.status, "detail": self.detail, "progress": round(self.progress, 3),
                "error": self.error, "model": self.model_key, "threads": self.threads}

    def wants(self, key: str, threads: int) -> bool:
        """True when the server should be (re)started for this model and thread count."""
        if self.busy:
            return False
        if self.ready and (key, threads) == (self.model_key, self.threads):
            return False
        if self.status == "error" and (key, threads) == (self.model_key, self.threads):
            return time.time() - self.failed_at > 300          # retry a failure every 5 minutes
        return True

    # ------------------------------------------------------------------ setup
    def ensure(self, key: str, threads: int) -> None:
        """Download what is missing and (re)start the server. Runs on a background thread."""
        with self.lock:
            if self.busy:
                return
            self.busy = True
        try:
            key = key if key in CATALOG else DEFAULT_MODEL
            self.stop()
            self.model_key, self.threads, self.error = key, threads, ""
            exe = self._server()
            model = self._model(key)
            self._start(exe, model, threads)
        except Exception as e:  # noqa: BLE001 - shown to the user, retried later
            self.status, self.error, self.failed_at = "error", f"{type(e).__name__}: {e}", time.time()
            self.detail = ""
            self.log(f"built-in Oracle failed: {self.error}", "warning")
        finally:
            self.busy = False

    def _find_exe(self) -> Path | None:
        name = "llama-server.exe" if os.name == "nt" else "llama-server"
        root = self.folder / "llama.cpp"
        if not root.exists():
            return None
        found = sorted(root.rglob(name))
        return found[0] if found else None

    def _server(self) -> Path:
        exe = self._find_exe()
        if exe:
            return exe
        suffix = platform_asset()
        if not suffix:
            raise RuntimeError(f"no prebuilt llama.cpp for {platform.system()} {platform.machine()}; use Ollama")
        tag, url = self._find_release(suffix)
        archive = self.folder / "downloads" / url.rsplit("/", 1)[1]
        self._download(url, archive, f"llama.cpp {tag} (the Oracle's engine)")
        dest = self.folder / "llama.cpp"
        tmp = self.folder / "llama.cpp.tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        if archive.name.endswith(".zip"):
            with zipfile.ZipFile(archive) as z:
                z.extractall(tmp)
        else:
            with tarfile.open(archive) as t:
                try:
                    t.extractall(tmp, filter="data")
                except TypeError:                             # Python without extraction filters
                    t.extractall(tmp)
        shutil.rmtree(dest, ignore_errors=True)
        tmp.replace(dest)
        archive.unlink(missing_ok=True)
        exe = self._find_exe()
        if not exe:
            raise RuntimeError(f"llama-server wasn't in {archive.name}")
        if os.name != "nt":
            for f in exe.parent.iterdir():
                if f.is_file():
                    f.chmod(f.stat().st_mode | 0o111)
        self.log(f"installed llama.cpp {tag} in {dest}")
        return exe

    def _find_release(self, suffix: str) -> tuple[str, str]:
        """The newest llama.cpp release that has the CPU build for this computer: (tag, url)."""
        seen = []
        try:
            with self._get(RELEASES, timeout=20, headers={"Accept": "application/vnd.github+json"}) as r:
                releases = json.loads(r.read().decode())
            for rel in releases:
                if rel.get("draft"):
                    continue
                seen.append(rel.get("tag_name", "?"))
                for a in rel.get("assets", []):
                    if a.get("name", "").endswith(suffix):
                        return rel["tag_name"], a["browser_download_url"]
        except (urllib.error.URLError, OSError, ValueError) as e:
            self.log(f"couldn't list llama.cpp's releases on GitHub ({type(e).__name__}: {e}); trying its latest release page")
        # Without the API (it allows 60 requests an hour), follow the "latest release" page to its tag.
        try:
            with self._get(LATEST_PAGE, timeout=20) as r:
                tag = r.geturl().rstrip("/").rsplit("/", 1)[-1]
            if tag.startswith("b"):
                return tag, f"https://github.com/ggml-org/llama.cpp/releases/download/{tag}/llama-{tag}-{suffix}"
        except (urllib.error.URLError, OSError) as e:
            seen.append(f"latest page: {type(e).__name__}")
        raise RuntimeError(f"no llama.cpp release with '{suffix}' found (looked at: {', '.join(seen[:8]) or 'nothing'}). "
                           f"You can put llama-server and its files in {self.folder / 'llama.cpp'} yourself, or use Ollama")

    def _model(self, key: str) -> Path:
        label, repo, file, _size = CATALOG[key]
        path = self.folder / "models" / file
        if not path.exists():
            self._download(f"https://huggingface.co/{repo}/resolve/main/{file}", path, label)
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
    def _start(self, exe: Path, model: Path, threads: int) -> None:
        self.status, self.detail, self.progress = "starting", f"Starting the Oracle ({self.label()})", 0.0
        port = free_port()
        args = [str(exe), "-m", str(model), "--host", "127.0.0.1", "--port", str(port),
                "-t", str(threads), "-c", "8192", "-np", "2", "-ngl", "0", "--no-webui"]
        logf = open(self.folder / "llama-server.log", "a", encoding="utf-8", errors="replace")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
        self.proc = subprocess.Popen(args, stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                     cwd=str(exe.parent), creationflags=flags)
        logf.close()
        (self.folder / "llama-server.pid").write_text(str(self.proc.pid), encoding="utf-8")
        self.url = f"http://127.0.0.1:{port}"
        deadline = time.time() + 180
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"llama-server stopped (exit code {self.proc.returncode}); "
                                   f"see {self.folder / 'llama-server.log'}")
            try:
                with self._get(self.url + "/health", timeout=2) as r:
                    if r.status == 200:
                        self.status, self.detail, self.progress = "ready", "", 1.0
                        self.log(f"the built-in Oracle is ready: {self.label()} on the CPU with {threads} threads")
                        return
            except (urllib.error.URLError, OSError):
                pass                                          # still loading the model (503) or starting
            time.sleep(0.5)
        raise RuntimeError("llama-server didn't become ready within 3 minutes")

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

    def stop_leftover(self) -> None:
        """Stop a server left running by an earlier run that didn't shut down cleanly."""
        pid_file = self.folder / "llama-server.pid"
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
    def chat(self, system: str, prompt: str, temperature: float, max_tokens: int, as_json: bool) -> str:
        if not self.ready:
            raise RuntimeError(self.detail or self.error or "the built-in Oracle isn't running yet")
        # Some small models' chat templates (Gemma's) have no system role: put it in the message.
        body = {"messages": [{"role": "user", "content": f"{system}\n\n{prompt}"}],
                "temperature": temperature, "max_tokens": max_tokens, "stream": False}
        if as_json:
            body["response_format"] = {"type": "json_object"}
        req = urllib.request.Request(self.url + "/v1/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=300) as r:
            d = json.loads(r.read().decode())
        return ((d.get("choices") or [{}])[0].get("message") or {}).get("content", "")
