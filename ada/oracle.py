"""The language model behind Wren: how to reach it, whichever backend runs it.

Two backends: "builtin" (a llama.cpp server the Hub runs on the CPU, see localllm.py) and
"ollama" (any model in a local Ollama). What the model is asked, and in whose voice, is in
wren.py. It never touches the synth's weights.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request


def clean(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    text = re.sub(r"[*#`_]+", "", text)
    return text.strip().strip('"').strip()


class Oracle:
    """Two backends: "builtin" (a llama.cpp server the Hub runs on the CPU, see localllm.py) and
    "ollama" (any model in a local Ollama). `url`, `model` and `models` are Ollama's."""

    def __init__(self, url: str, model: str, local=None):
        self.url, self.model = url.rstrip("/"), model
        self.models: list[dict] = []
        self.error = ""
        self.backend = "ollama"
        self.local = local           # LocalLLM, for the built-in backend
        self.use_gpu = True          # False: ask Ollama to run the model on the CPU
        self.cpu_threads = 0         # Ollama's threads when on the CPU (0: Ollama decides)

    # -- Ollama -------------------------------------------------------------------
    def _req(self, path: str, body: dict | None = None, timeout: float = 180.0) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, headers={"Content-Type": "application/json"},
                                     method="POST" if body is not None else "GET")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())

    @property
    def builtin(self) -> bool:
        return self.backend == "builtin" and self.local is not None

    @property
    def ready(self) -> bool:
        return self.local.ready if self.builtin else bool(self.model)

    @property
    def active(self) -> str:
        """The model answering right now, as shown to the user."""
        return f"{self.local.label()} (built-in)" if self.builtin else self.model

    def refresh(self) -> list[dict]:
        """Ask Ollama which models are installed; pick a sensible one if none is chosen."""
        try:
            ms = []
            for m in self._req("/api/tags", timeout=5).get("models", []):
                det = m.get("details") or {}
                name = m.get("name") or m.get("model")
                if "embed" in name.lower() or "bert" in (det.get("family") or "").lower():
                    continue
                ms.append({"name": name, "size": m.get("size", 0), "parameter_size": det.get("parameter_size", "")})
            self.models = sorted(ms, key=lambda m: m["size"])
            names = [m["name"] for m in self.models]
            if names and self.model not in names:
                self.model = next((n for p in ("llama3", "qwen", "gemma", "mistral", "phi") for n in names
                                   if p in n.lower()), names[len(names) // 2])
            self.error = "" if names else "Ollama is running but has no chat models (try: ollama pull llama3.2)"
        except (urllib.error.URLError, OSError, ValueError) as e:
            self.models = []
            self.error = f"Ollama isn't reachable at {self.url} ({type(e).__name__}). Is it running?"
        return self.models

    def chat(self, system: str, prompt: str, temperature: float = 0.7, max_tokens: int = 400,
             as_json: bool = False) -> str:
        if self.builtin:
            return clean(self.local.chat(system, prompt, temperature, max_tokens, as_json))
        if not self.model:
            raise RuntimeError(self.error or "no Oracle model chosen")
        body = {"model": self.model, "stream": False,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                # The Oracle's prompts are short: a small context keeps Ollama's memory small (its
                # default can be 65,536 tokens, which costs gigabytes).
                "options": {"temperature": temperature, "num_predict": max_tokens, "num_ctx": 4096}}
        if not self.use_gpu:
            body["options"]["num_gpu"] = 0       # keep the Oracle out of GPU memory
            if self.cpu_threads:
                body["options"]["num_thread"] = self.cpu_threads
        if as_json:
            body["format"] = "json"
        r = self._req("/api/chat", body)
        return clean((r.get("message") or {}).get("content", ""))

    def loaded(self) -> list[dict]:
        """Models Ollama has in memory right now, and how much of each sits in GPU memory."""
        try:
            return [{"name": m.get("name"), "vram_mb": round((m.get("size_vram") or 0) / 2**20),
                     "size_mb": round((m.get("size") or 0) / 2**20)}
                    for m in self._req("/api/ps", timeout=3).get("models", [])]
        except (urllib.error.URLError, OSError, ValueError):
            return []

    def unload(self, name: str) -> bool:
        """Ask Ollama to let go of a model entirely (it reloads on the next request)."""
        try:
            self._req("/api/generate", {"model": name, "keep_alive": 0}, timeout=30)
            return True
        except (urllib.error.URLError, OSError, ValueError):
            return False

    def unload_from_gpu(self) -> list[str]:
        """Ask Ollama to free the GPU memory its models hold (they reload on the next request)."""
        freed = []
        for m in self.loaded():
            if m["vram_mb"] > 0:
                try:
                    self._req("/api/generate", {"model": m["name"], "keep_alive": 0}, timeout=30)
                    freed.append(f"{m['name']} ({m['vram_mb']} MB)")
                except (urllib.error.URLError, OSError, ValueError):
                    pass
        return freed

    def _json(self, system: str, prompt: str, **kw) -> dict:
        try:
            return json.loads(self.chat(system, prompt, as_json=True, **kw))
        except ValueError:
            return {}
