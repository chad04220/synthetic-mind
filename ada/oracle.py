"""The Oracle: a local Ollama model that knows far more than Ada and helps her learn.

It never touches her weights. It writes: lessons pitched at her stage (aimed first at the
concepts her tests show she gets wrong, and at topics you ask for), answers to questions (hers,
asked at the shrine, and yours), the villagers' words, the books in the library, the reply she
should have given you, and periodic assessments of how she uses language. Lessons and answers go
into the curriculum the Academy studies; new facts go into the concept graph.
"""
from __future__ import annotations

import json
import random
import re
import urllib.error
import urllib.request

LEVEL = {
    0: "a toddler's words: very short sentences of three to six common words",
    1: "a toddler's words: very short sentences of three to six common words",
    2: "a picture book: short, simple sentences with everyday words",
    3: "an early reader: simple sentences, one idea each",
    4: "plain English for a curious eight-year-old",
    5: "clear English for a bright twelve-year-old",
    6: "clear, thoughtful English for an adult",
}
TOPICS = ["the sun and the moon", "colors", "animals", "food", "water", "trees", "weather", "seasons",
          "feelings", "friends", "numbers", "shapes", "day and night", "music", "books and words",
          "the body", "families", "kindness", "how plants grow", "fire", "the sea", "stars", "time",
          "machines", "maps", "questions", "memory", "learning", "light and shadow", "gravity",
          "electricity", "cities", "history", "mathematics", "language", "thinking", "art", "honesty"]
RELATIONS = "is a, color, is, made of, used for, found in, can"


def clean(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    text = re.sub(r"[*#`_]+", "", text)
    return text.strip().strip('"').strip()


class Oracle:
    def __init__(self, url: str, model: str):
        self.url, self.model = url.rstrip("/"), model
        self.models: list[dict] = []
        self.error = ""

    # -- Ollama -------------------------------------------------------------------
    def _req(self, path: str, body: dict | None = None, timeout: float = 180.0) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, headers={"Content-Type": "application/json"},
                                     method="POST" if body is not None else "GET")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())

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
        if not self.model:
            raise RuntimeError(self.error or "no Oracle model chosen")
        body = {"model": self.model, "stream": False,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                "options": {"temperature": temperature, "num_predict": max_tokens}}
        if as_json:
            body["format"] = "json"
        r = self._req("/api/chat", body)
        return clean((r.get("message") or {}).get("content", ""))

    def _json(self, system: str, prompt: str, **kw) -> dict:
        try:
            return json.loads(self.chat(system, prompt, as_json=True, **kw))
        except ValueError:
            return {}

    # -- what the Oracle writes ---------------------------------------------------------
    SYSTEM = ("You are the Oracle, a wise and gentle teacher of Ada, a young artificial mind who is learning "
              "language and the world from nothing. Write plain text only: no markdown, lists, emojis or preamble.")

    def lesson_pack(self, topic: str, stage: int, focus: list[str] | None = None) -> dict:
        """A lesson, questions with answers, and facts for the concept graph."""
        hint = f" Make sure to cover: {'; '.join(focus)}." if focus else ""
        d = self._json(self.SYSTEM,
                       f"Teach Ada about {topic}.{hint} Use {LEVEL[min(stage, 6)]}. Return JSON with keys: "
                       '"lesson": a short paragraph of 4 to 8 sentences; '
                       '"qa": 3 objects with "q" (a question Ada might ask) and "a" (a short answer); '
                       f'"facts": up to 8 objects with "s", "r", "o" where "r" is one of: {RELATIONS}, and "s" and '
                       '"o" are one or two lowercase words (example: {"s": "moon", "r": "is", "o": "round"}).',
                       temperature=0.8, max_tokens=700)
        lesson = clean(str(d.get("lesson", "")))
        qa = [(clean(str(x.get("q", ""))), clean(str(x.get("a", "")))) for x in d.get("qa", []) if isinstance(x, dict)]
        facts = [x for x in d.get("facts", []) if isinstance(x, dict)]
        return {"topic": topic, "lesson": lesson, "qa": [q for q in qa if q[0] and q[1]], "facts": facts}

    def answer(self, question: str, stage: int, asker: str = "Ada") -> str:
        who = "Ada asks you" if asker == "Ada" else "Ada's friend asks you"
        if asker == "Ada" and not re.search(r"[a-z]{3}", question.lower()):
            return self.chat(self.SYSTEM, "Ada tries to ask a question but her words are still sounds. "
                                          f"Say something kind and simple about asking questions, using {LEVEL[min(stage, 6)]}. "
                                          "Two sentences.", max_tokens=120)
        level = LEVEL[min(stage, 6)] if asker == "Ada" else "clear, friendly English"
        return self.chat(self.SYSTEM, f'{who}: "{question}"\nAnswer in two to four sentences using {level}.',
                         max_tokens=260)

    def npc(self, name: str, role: str, ada_said: str, stage: int, season: str, weather: str, place: str) -> str:
        heard = (f'Ada says to you: "{ada_said}"' if re.search(r"[a-z]{3}\s+[a-z]{2,}", ada_said.lower())
                 else "Ada comes to you and makes some sounds; she is still learning to talk.")
        return self.chat(
            f"You are {name}, the {role} in a small village. You talk with Ada, a young artificial mind who is "
            "learning words. Speak warmly in one or two short sentences, in character. Mention your work or the "
            "world around you. Plain text only.",
            f"{heard} It is {season}, the weather is {weather}, you are in the {place}. Use {LEVEL[min(stage, 6)]}.",
            temperature=0.9, max_tokens=90)

    def tutor(self, history: list, user: str, mind: str, stage: int) -> str:
        convo = "\n".join(f"{'Friend' if r == 'user' else 'Ada'}: {t}" for r, t in history[-6:])
        return self.chat(self.SYSTEM,
                         f"Ada is talking with her friend.\n{convo}\nFriend: {user}\nAda tried to say: \"{mind}\"\n\n"
                         "Write the reply Ada should learn to give: first person, honest about being a young mind who "
                         f"is still learning, warm, at most three sentences, using {LEVEL[min(stage + 1, 6)]}. "
                         "Reply only with Ada's words.", max_tokens=150)

    def book(self, stage: int, topic: str | None = None) -> str:
        topic = topic or random.choice(TOPICS)
        return self.chat(self.SYSTEM, f"Write one page (5 to 8 sentences) of a book in the village library about "
                                      f"{topic}, using {LEVEL[min(stage + 1, 6)]}. Start with a title line.",
                         temperature=0.9, max_tokens=400)

    def fact(self, topic: str, stage: int) -> str:
        return self.chat(self.SYSTEM, f"Ada looks through a telescope. Tell her one wonderful true fact about "
                                      f"{topic} in two sentences, using {LEVEL[min(stage, 6)]}.", max_tokens=120)

    def assess(self, thoughts: list[str], self_rate: float) -> dict:
        sample = "\n".join(f"- {t}" for t in thoughts[-8:])
        d = self._json(self.SYSTEM,
                       f"These are recent inner thoughts of Ada, an artificial mind learning language from scratch:\n"
                       f"{sample}\n\nRate them 0 to 10 for spelling (real words), grammar, coherence and meaning, "
                       'and say in one short sentence what she is learning now. Return JSON: {"spelling": n, '
                       '"grammar": n, "coherence": n, "meaning": n, "note": "..."}', temperature=0.2, max_tokens=200)
        try:
            return {k: float(d.get(k, 0)) for k in ("spelling", "grammar", "coherence", "meaning")} | \
                {"note": str(d.get("note", ""))[:300]}
        except (TypeError, ValueError):
            return {}
