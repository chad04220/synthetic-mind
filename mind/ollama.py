"""Minimal client for a local Ollama server (stdlib only)."""
from __future__ import annotations

import json
import urllib.error
import urllib.request


class Ollama:
    def __init__(self, url: str = "http://localhost:11434"):
        self.url = url.rstrip("/")

    def _req(self, path: str, body: dict | None = None, timeout: float = 120.0) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data,
                                     headers={"Content-Type": "application/json"},
                                     method="POST" if body is not None else "GET")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())

    def models(self) -> list[dict]:
        """Installed models, smallest first: [{name, size, family, parameter_size}]"""
        out = []
        for m in self._req("/api/tags", timeout=5).get("models", []):
            det = m.get("details") or {}
            out.append({
                "name": m.get("name") or m.get("model"),
                "size": m.get("size", 0),
                "family": det.get("family", ""),
                "parameter_size": det.get("parameter_size", ""),
            })
        # Embedding-only models cannot write lessons.
        out = [m for m in out if "embed" not in m["name"].lower() and "bert" not in m["family"].lower()]
        return sorted(out, key=lambda m: m["size"])

    def available(self) -> bool:
        try:
            self._req("/api/version", timeout=3)
            return True
        except (urllib.error.URLError, OSError, ValueError):
            return False

    def chat(self, model: str, messages: list[dict], temperature: float = 0.8,
             max_tokens: int = 400, json_mode: bool = False) -> str:
        body = {"model": model, "messages": messages, "stream": False,
                "options": {"temperature": temperature, "num_predict": max_tokens}}
        if json_mode:
            body["format"] = "json"
        r = self._req("/api/chat", body, timeout=300)
        return (r.get("message") or {}).get("content", "").strip()
