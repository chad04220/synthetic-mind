"""The built-in voices: llama.cpp servers with small models, running on the CPU.

One server runs the Sprite of All Knowing's mind (see sprite.py). The default model also sees and
hears (images and audio, through its multimodal projector), so the Sprite can look at Zen's paintings
and sculptures and listen to its songs. The class can run several servers (one per role).

Nothing to install by hand. On first use the Hub downloads llama.cpp's prebuilt server for this
computer (from llama.cpp's GitHub releases) and the chosen model (a GGUF file from Hugging Face)
into the `oracle/` folder next to run.py, starts each `llama-server` on a free local port with its
share of the CPU threads, and keeps them running. The GPU is never touched: the CPU build
of llama.cpp is used, so the GPU stays entirely with the Academy.

Ollama remains available as the other backend (Settings).
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
# key: (label, Hugging Face repo, model file, size, optional (projector file, size) for seeing and hearing)
CATALOG = {
    "qwen2.5-omni-3b": ("Qwen 2.5 Omni 3B (sees and hears)", "ggml-org/Qwen2.5-Omni-3B-GGUF",
                        "Qwen2.5-Omni-3B-Q4_K_M.gguf", 2104931648, ("mmproj-Qwen2.5-Omni-3B-Q8_0.gguf", 1538031328)),
    "gemma-2-2b": ("Gemma 2 2B Instruct", "bartowski/gemma-2-2b-it-GGUF", "gemma-2-2b-it-Q4_K_M.gguf", 1708582752),
    "qwen2.5-1.5b": ("Qwen 2.5 1.5B Instruct (light)", "Qwen/Qwen2.5-1.5B-Instruct-GGUF",
                     "qwen2.5-1.5b-instruct-q4_k_m.gguf", 1117320736),
    "qwen2.5-0.5b": ("Qwen 2.5 0.5B Instruct (tiny, fastest)", "Qwen/Qwen2.5-0.5B-Instruct-GGUF",
                     "qwen2.5-0.5b-instruct-q4_k_m.gguf", 491400032),
    "llama-3.2-3b": ("Llama 3.2 3B Instruct (strongest, slowest)", "bartowski/Llama-3.2-3B-Instruct-GGUF",
                     "Llama-3.2-3B-Instruct-Q4_K_M.gguf", 2019377696),
}
DEFAULT_MODEL = "qwen2.5-omni-3b"


def senses(key: str) -> bool:
    """Can this model see images and hear audio?"""
    return len(CATALOG.get(key, ())) > 4
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
    """One llama-server (the Sprite's mind). Each runs as its own process on its
    own port; the program and the model files are shared (downloaded once), and several servers
    loading the same model file share its memory, because llama.cpp maps it rather than copying it."""

    _install = threading.Lock()      # one download at a time, shared by every server

    def __init__(self, folder: Path, log=None, role: str = "oracle"):
        self.folder = folder
        self.role = role
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
        self.ctx, self.slots = 8192, 2
        self.closed = False          # the program is shutting down: never start again

    # ------------------------------------------------------------------ state
    @property
    def ready(self) -> bool:
        return self.status == "ready" and self.proc is not None and self.proc.poll() is None

    def label(self, key: str | None = None) -> str:
        return CATALOG.get(key or self.model_key, (key or self.model_key,))[0]

    def catalog(self) -> list[dict]:
        out = []
        for key, entry in CATALOG.items():
            label, _repo, file, size = entry[:4]
            extra = entry[4] if len(entry) > 4 else None
            have = (self.folder / "models" / file).exists() and (extra is None or (self.folder / "models" / extra[0]).exists())
            out.append({"name": key, "label": label, "size": size + (extra[1] if extra else 0), "downloaded": have,
                        "senses": extra is not None})
        return out

    def info(self) -> dict:
        return {"role": self.role, "status": self.status, "detail": self.detail, "progress": round(self.progress, 3),
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
    name = ""                        # who this model speaks for ("the Sprite's mind"); the Hub sets it

    @property
    def who(self) -> str:
        return self.name or ("the built-in Oracle" if self.role == "oracle" else f"{self.role}'s voice")

    def ensure(self, key: str, threads: int, ctx: int = 8192, slots: int = 2) -> None:
        """Download what is missing and (re)start the server. Runs on a background thread."""
        with self.lock:
            if self.busy or self.closed:
                return
            self.busy = True
        try:
            key = key if key in CATALOG else DEFAULT_MODEL
            self.stop()
            self.model_key, self.threads, self.error, self.ctx, self.slots = key, threads, "", ctx, slots
            self.status, self.detail = "waiting", "Waiting for downloads to finish"
            with LocalLLM._install:
                exe = self._server()
                model = self._model(key)
            self._start(exe, model, threads)
        except Exception as e:  # noqa: BLE001 - shown to the user, retried later
            self.status, self.error, self.failed_at = "error", f"{type(e).__name__}: {e}", time.time()
            self.detail = ""
            self.log(f"{self.who} failed: {self.error}", "warning")
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
        self._download(url, archive, f"llama.cpp {tag} (the engine for the Sprite's mind)")
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
        label, repo, file, _size = CATALOG[key][:4]
        path = self.folder / "models" / file
        if not path.exists():
            self._download(f"https://huggingface.co/{repo}/resolve/main/{file}", path, label)
        self.mmproj = None
        if len(CATALOG[key]) > 4:
            proj = self.folder / "models" / CATALOG[key][4][0]
            if not proj.exists():
                self._download(f"https://huggingface.co/{repo}/resolve/main/{proj.name}", proj,
                               f"{label}: its eyes and ears")
            self.mmproj = proj
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
        self.status, self.detail, self.progress = "starting", f"Starting {self.who} ({self.label()})", 0.0
        if self.closed:
            raise RuntimeError("shutting down")
        port = free_port()
        args = [str(exe), "-m", str(model), "--host", "127.0.0.1", "--port", str(port),
                "-t", str(threads), "-c", str(self.ctx), "-np", str(self.slots), "-ngl", "0", "--no-webui"]
        if getattr(self, "mmproj", None):
            args += ["--mmproj", str(self.mmproj), "--no-mmproj-offload"]   # its eyes and ears, on the CPU too
        if self.role != "oracle" and not getattr(self, "_no_extras", False):
            # Villagers share one copy of the model: without repacking, every server maps the same
            # file instead of keeping its own rearranged copy of the weights (about 1 GB each).
            args.append("--no-repack")
        (self.folder / "logs").mkdir(parents=True, exist_ok=True)
        logf = open(self.folder / "logs" / f"llama-server-{self.role}.log", "a", encoding="utf-8", errors="replace")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
        self.proc = subprocess.Popen(args, stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                     cwd=str(exe.parent), creationflags=flags)
        logf.close()
        self._pid_file().write_text(str(self.proc.pid), encoding="utf-8")
        self.url = f"http://127.0.0.1:{port}"
        deadline = time.time() + 180
        while time.time() < deadline:
            if self.proc.poll() is not None:
                if "--no-repack" in args and not getattr(self, "_no_extras", False):
                    self._no_extras = True              # an older llama.cpp without that option
                    return self._start(exe, model, threads)
                raise RuntimeError(f"llama-server stopped (exit code {self.proc.returncode}); "
                                   f"see {self.folder / 'logs' / f'llama-server-{self.role}.log'}")
            try:
                with self._get(self.url + "/health", timeout=2) as r:
                    if r.status == 200:
                        self.status, self.detail, self.progress = "ready", "", 1.0
                        self.log(f"{self.who} is ready: {self.label()} on the CPU with {threads} threads")
                        return
            except (urllib.error.URLError, OSError) as e:
                if isinstance(e, urllib.error.HTTPError):
                    e.close()                                 # still loading the model (503)
                # or still starting
            time.sleep(0.5)
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
    @property
    def senses(self) -> bool:
        return bool(getattr(self, "mmproj", None)) and self.ready

    def look_listen(self, system: str, prompt: str, images: list[bytes] = (), audio: list[bytes] = (),
                    temperature: float = 0.4, max_tokens: int = 200) -> str:
        """Show the model pictures (PNG) and let it hear sounds (WAV), then ask about them."""
        import base64

        if not self.senses:
            raise RuntimeError("this model can't see or hear")
        content = [{"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(b).decode()}}
                   for b in images]
        content += [{"type": "input_audio", "input_audio": {"data": base64.b64encode(b).decode(), "format": "wav"}}
                    for b in audio]
        content.append({"type": "text", "text": f"{system}\n\n{prompt}"})
        body = {"messages": [{"role": "user", "content": content}], "temperature": temperature,
                "max_tokens": max_tokens, "stream": False}
        req = urllib.request.Request(self.url + "/v1/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=600) as r:
            d = json.loads(r.read().decode())
        return ((d.get("choices") or [{}])[0].get("message") or {}).get("content", "")

    def chat(self, system: str, prompt: str, temperature: float, max_tokens: int, as_json: bool) -> str:
        if not self.ready:
            raise RuntimeError(self.detail or self.error or f"{self.who} isn't running yet")
        # Some small models' chat templates (Gemma's) have no system role: put it in the message.
        body = {"messages": [{"role": "user", "content": f"{system}\n\n{prompt}"}],
                "temperature": temperature, "max_tokens": max_tokens, "stream": False,
                "cache_prompt": True}       # the long fixed instructions come first: reuse them between requests
        if as_json:
            body["response_format"] = {"type": "json_object"}
        req = urllib.request.Request(self.url + "/v1/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=300) as r:
            d = json.loads(r.read().decode())
        return ((d.get("choices") or [{}])[0].get("message") or {}).get("content", "")
