"""The Coach, in the Hub: runs the inhabitant's practice rounds and keeps its adapters.

A round (asked for by the inhabitant itself with its `practice` skill, by you on the page, or
automatically when it sleeps): the model server is stopped (the GPU is needed for training; the
inhabitant sleeps meanwhile), `python -m ada.agent.practice` runs as its own process and reports
progress line by line, and when it finishes the server starts again with the new adapter. The
inhabitant is told how it went.

Adapters live in minds/<name>/adapters/ as p1, p2, … (.gguf for llama.cpp, .pt to continue from,
.json with what the round learned from). Any of them, or none (the base model), can be used.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

from .agent.practice import missing_tools

ROOT = Path(__file__).resolve().parent.parent


class Coach:
    def __init__(self, folder: Path, oracle: Path, cfg, log, on_change):
        self.folder, self.oracle, self.cfg = folder, oracle, cfg
        self.dir = folder / "adapters"
        self.log = log                     # log(text, level)
        self.on_change = on_change         # on_change(event: str, data: dict): tell the Hub
        self.proc: subprocess.Popen | None = None
        self.state, self.detail, self.progress = "ready", "", 0.0
        self.step = self.steps = 0
        self.loss = None
        self.eta = None
        self.by = ""
        self.started = 0.0
        self.missing: list[str] = []
        self.stopped = False
        self.check_tools()

    # ------------------------------------------------------------------ status
    def check_tools(self) -> None:
        self.missing = missing_tools()
        if self.missing and self.state in ("ready", "needs_tools"):
            self.state = "needs_tools"
            self.detail = "Practice needs " + ", ".join(self.missing) + " (Install training tools)"
        elif not self.missing and self.state == "needs_tools":
            self.state, self.detail = "ready", ""

    @property
    def running(self) -> bool:
        return self.state in ("preparing", "training", "exporting", "installing")

    def adapters(self) -> list[dict]:
        out = []
        for j in sorted(self.dir.glob("p*.json"), key=lambda p: int(p.stem[1:]) if p.stem[1:].isdigit() else 0):
            try:
                info = json.loads(j.read_text(encoding="utf-8"))
            except ValueError:
                continue
            if (self.dir / f"{j.stem}.gguf").exists():
                out.append({"name": j.stem, "created": info.get("created"), "examples": info.get("examples"),
                            "loss": info.get("loss"), "model": info.get("model"), "active": j.stem == self.cfg.mind.adapter,
                            "corrected": info.get("corrected"), "liked": info.get("liked")})
        return out

    def adapter_path(self) -> Path | None:
        """The active adapter's GGUF, if it fits the model in use."""
        name = self.cfg.mind.adapter
        if not name:
            return None
        p = self.dir / f"{name}.gguf"
        try:
            info = json.loads((self.dir / f"{name}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return p if p.exists() and info.get("model") == self.cfg.mind.model else None

    def info(self, counts: dict | None = None) -> dict:
        return {"state": self.state, "detail": self.detail, "progress": round(self.progress, 3), "step": self.step,
                "steps": self.steps, "loss": self.loss, "eta": self.eta, "by": self.by,
                "adapters": self.adapters(), "active": self.cfg.mind.adapter or None,
                "auto": self.cfg.mind.practice_auto, **(counts or {})}

    # ------------------------------------------------------------------ a round
    def next_name(self) -> str:
        n = [int(p.stem[1:]) for p in self.dir.glob("p*.json") if p.stem[1:].isdigit()]
        return f"p{max(n, default=0) + 1}"

    def start(self, by: str, stop_model, since: float = 0.0) -> str | None:
        """Begin a round. Returns why it can't, or None. stop_model() frees the GPU first."""
        self.check_tools()
        if self.running:
            return "Already practising."
        if self.missing:
            return "Practice needs its tools first (Settings → Practice → Install training tools)."
        name = self.next_name()
        prev = self.cfg.mind.adapter
        resume = prev if prev and (self.dir / f"{prev}.pt").exists() and self._fits(prev) else ""
        self.dir.mkdir(parents=True, exist_ok=True)
        args = [sys.executable, "-m", "ada.agent.practice", "--mind", str(self.folder), "--model", self.cfg.mind.model,
                "--oracle", str(self.oracle), "--name", name, "--since", str(since),
                "--max-steps", str(self.cfg.mind.practice_steps), "--lr", str(self.cfg.mind.practice_lr),
                "--rank", str(self.cfg.mind.practice_rank)]
        if resume:
            args += ["--resume", resume]
        self.state, self.detail, self.progress, self.step, self.steps, self.loss, self.eta = \
            "preparing", "Getting ready to practise", 0.0, 0, 0, None, None
        self.by, self.started, self.stopped = by, time.time(), False
        threading.Thread(target=self._run, args=(args, name, stop_model), name="practice", daemon=True).start()
        return None

    def _fits(self, name: str) -> bool:
        try:
            return json.loads((self.dir / f"{name}.json").read_text(encoding="utf-8")).get("model") == self.cfg.mind.model
        except (OSError, ValueError):
            return False

    def _run(self, args: list[str], name: str, stop_model) -> None:
        self.on_change("practice_started", {"by": self.by, "name": name})
        stop_model()
        info, error = None, ""
        logp = self.folder / "logs" / "practice.log"
        logp.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(logp, "a", encoding="utf-8") as logf:
                logf.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} {' '.join(args)}\n")
                self.proc = subprocess.Popen(args, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=logf, text=True,
                                             encoding="utf-8", errors="replace",
                                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                for line in self.proc.stdout:
                    logf.write(line)
                    try:
                        d = json.loads(line)
                    except ValueError:
                        continue
                    self.detail = d.get("detail", self.detail)
                    self.progress = d.get("progress", self.progress)
                    for k in ("step", "steps", "loss", "eta"):
                        if k in d:
                            setattr(self, k, d[k])
                    if d.get("state") in ("preparing", "training", "exporting"):
                        self.state = d["state"]
                    elif d.get("state") == "done":
                        info = d.get("info")
                    elif d.get("state") == "error":
                        error = d.get("detail", "practice failed")
                self.proc.wait()
            if self.stopped:
                info, error = None, "stopped"
            elif info is None and not error:
                error = f"practice stopped (exit code {self.proc.returncode}); see {logp}"
        except OSError as e:
            error = f"{type(e).__name__}: {e}"
        finally:
            self.proc = None
        if info:
            self.cfg.mind.adapter = name
            self.state, self.detail, self.progress = "ready", f"{name}: practised on {info.get('examples')} examples", 1.0
            self.log(f"practice {name} finished: {info.get('examples')} examples, {info.get('steps')} steps, "
                     f"loss {info.get('first_loss')} → {info.get('loss')}")
            self.on_change("practice_done", {"name": name, "info": info})
        else:
            self.state, self.detail = ("ready", "Practice stopped.") if error == "stopped" else ("error", error)
            self.log(f"practice failed: {error}", "warning")
            self.on_change("practice_failed", {"error": error})

    def stop(self) -> None:
        p = self.proc
        if p and p.poll() is None:
            self.stopped = True
            p.terminate()

    def use(self, name: str | None) -> str | None:
        """Switch to an adapter (or None: the base model). Returns an error, or None."""
        if self.running:
            return "Wait until practice is over."
        if name and not (self.dir / f"{name}.gguf").exists():
            return f"There is no adapter called {name}."
        if name and not self._fits(name):
            return f"{name} was practised with a different model."
        self.cfg.mind.adapter = name or ""
        return None

    # ------------------------------------------------------------------ the tools
    def install(self) -> str | None:
        if self.running:
            return "Busy."
        self.check_tools()
        if not self.missing:
            return "The training tools are already installed."
        self.state, self.detail, self.progress = "installing", "Installing " + ", ".join(self.missing), 0.0
        threading.Thread(target=self._install, name="practice-install", daemon=True).start()
        return None

    def _install(self) -> None:
        from .localllm import nvidia_gpu_cached

        cmds = []
        rest = [m for m in self.missing if m != "torch"]
        if "torch" in self.missing:
            cuda = nvidia_gpu_cached() is not None
            cmds.append([sys.executable, "-m", "pip", "install", "torch"] +
                        (["--index-url", "https://download.pytorch.org/whl/cu126"] if cuda else []))
        if rest:
            cmds.append([sys.executable, "-m", "pip", "install", "transformers>=4.45", "safetensors", "gguf",
                         "huggingface_hub"])
        logp = self.folder / "logs" / "practice.log"
        err = ""
        for i, c in enumerate(cmds):
            self.detail = f"Installing ({i + 1} of {len(cmds)}): {' '.join(c[4:6])}…"
            with open(logp, "a", encoding="utf-8") as logf:
                r = subprocess.run(c, stdout=logf, stderr=subprocess.STDOUT,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if r.returncode:
                err = f"pip failed (exit code {r.returncode}); see {logp}"
                break
            self.progress = (i + 1) / len(cmds)
        self.state = "ready"
        self.check_tools()
        if err or self.missing:
            self.state, self.detail = "needs_tools", err or ("Still missing: " + ", ".join(self.missing) +
                                                             " (restart the program if pip just installed them)")
            self.log(self.detail, "warning")
        else:
            self.detail = "Training tools installed."
            self.log("the training tools for practice are installed")
