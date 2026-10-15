"""The teacher: a local Ollama model that writes a curriculum matched to the mind's stage,
answers for it while it cannot yet, rewrites its muddled thoughts into clear ones, and
periodically assesses how well it uses language.

The teacher never touches the network's weights directly. It only writes text, which
enters the training mixture like any other experience, so everything the mind knows it
learned by gradient descent on its own predictions.
"""
from __future__ import annotations

import json
import queue
import random
import re
import threading
import time
from typing import TYPE_CHECKING

from .ollama import Ollama

if TYPE_CHECKING:
    from .brain import Mind

TOPICS = [
    "colors", "numbers and counting", "animals", "food", "the weather", "the sun, moon and stars",
    "feelings", "friends", "the body", "water", "trees and plants", "day and night", "home",
    "music", "books and reading", "shapes", "big and small", "hot and cold", "time", "family",
    "kindness", "curiosity", "asking questions", "cause and effect", "memory", "learning",
    "being a new mind", "the ocean", "machines", "light and shadow", "sleep and dreams",
    "playing games", "sharing", "words and meanings", "what thinking is", "the seasons",
    "maps and directions", "simple science", "honesty", "patience", "art", "cities", "the sky",
    "gravity", "electricity", "computers", "history", "language", "mathematics", "philosophy",
]

SYSTEM = ("You are a patient, warm teacher for a brand-new artificial mind that is learning language "
          "from nothing. Write plain English text only: no markdown, no lists with symbols, no emojis, "
          "no preamble like 'Sure' or 'Here is'.")

LESSONS = [
    # stage 0-1: static / babbling
    "Write 12 very short, simple sentences about {topic}, each on its own line. "
    "Use only common words a three-year-old knows. Repeat key words often.",
    # stage 2: first words
    "Write 10 simple sentences about {topic}, each on its own line, like a picture book for a small child.",
    # stage 3: phrases
    "Write a short story (about 120 words) for a young child about {topic}. Use simple sentences.",
    # stage 4: sentences
    "Explain {topic} to a curious eight-year-old in about 150 words of plain prose.",
    # stage 5: conversational
    "Write a thoughtful paragraph (about 180 words) about {topic}, the way a kind, curious person "
    "thinks to themselves in their own head, in first person.",
    # stage 6: articulate
    "Write a clear, insightful mini-essay (about 250 words) about {topic}, connecting it to other ideas.",
]


def _clean(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    text = re.sub(r"[*#`_]+", "", text)
    return text.strip()


class Teacher:
    def __init__(self, mind: "Mind"):
        self.mind = mind
        self.status = "idle"
        self.error = ""
        self.models: list[dict] = []
        self.lessons = 0
        self.urgent: queue.Queue = queue.Queue()   # tutor replies for the user's messages
        self.last_assess = 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="teacher", daemon=True)

    @property
    def client(self) -> Ollama:
        return Ollama(self.mind.cfg.ollama_url)

    def refresh_models(self) -> list[dict]:
        try:
            self.models = self.client.models()
            cfg = self.mind.cfg
            names = [m["name"] for m in self.models]
            if names and cfg.ollama_model not in names:
                cfg.ollama_model = self._pick_default(names)
            self.error = "" if names else "Ollama is running but has no chat models (try: ollama pull llama3.2)"
        except Exception as e:
            self.models = []
            self.error = f"Ollama not reachable at {self.mind.cfg.ollama_url} ({type(e).__name__})"
        return self.models

    @staticmethod
    def _pick_default(names: list[str]) -> str:
        # Prefer a mid-size instruction model; names are sorted smallest first.
        for pref in ("llama3", "qwen", "gemma", "mistral", "phi"):
            for n in names:
                if pref in n.lower():
                    return n
        return names[len(names) // 2]

    def start(self):
        self.refresh_models()
        self._thread.start()

    def stop(self):
        self._stop.set()

    def tutor_reply(self, history: list[tuple[str, str]], user_text: str, mind_reply: str):
        self.urgent.put((history, user_text, mind_reply))

    # -- loop ---------------------------------------------------------------
    def _run(self):
        while not self._stop.is_set():
            cfg = self.mind.cfg
            if not cfg.teacher_enabled:
                self.status = "off"
                self._stop.wait(0.5)
                continue
            if not cfg.ollama_model:
                self.status = "no model"
                self.refresh_models()
                self._stop.wait(10)
                continue
            try:
                try:
                    job = self.urgent.get_nowait()
                    self.status = "answering you"
                    self._tutor(*job)
                except queue.Empty:
                    self._curriculum_step()
                self.error = ""
            except Exception as e:
                self.error = f"{type(e).__name__}: {e}"[:300]
                self.status = "error"
                self._stop.wait(10)
                continue
            self._stop.wait(cfg.teacher_interval)

    def _ask(self, prompt: str, temperature: float = 0.9, max_tokens: int = 450, system: str = SYSTEM,
             json_mode: bool = False) -> str:
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        return _clean(self.client.chat(self.mind.cfg.ollama_model, msgs, temperature, max_tokens, json_mode))

    def _curriculum_step(self):
        cfg, mind = self.mind.cfg, self.mind
        now = time.time()
        if cfg.teacher_assesses and now - self.last_assess > 300 and len(mind.thought_texts()) >= 5:
            self.last_assess = now
            self.status = "assessing"
            self._assess()
            return
        r = random.random()
        thought = mind.last_thought_text()
        if cfg.teacher_reviews_thoughts and thought and r < 0.25:
            self.status = "reviewing a thought"
            self._review(thought)
        elif r < 0.5:
            self.status = "writing a dialogue"
            self._dialogue()
        else:
            self.status = "writing a lesson"
            self._lesson()

    def _lesson(self):
        stage = self.mind.stage_index()
        topic = random.choice(TOPICS + self.mind.world_topics())
        tmpl = LESSONS[min(stage, len(LESSONS) - 1)]
        text = self._ask(tmpl.format(topic=topic))
        if text:
            self.mind.teacher_pool.add(text, 1.0, "lesson")
            self.lessons += 1
            self.mind.event("teacher", {"sub": "lesson", "topic": topic, "text": text[:600]})

    def _dialogue(self):
        stage = self.mind.stage_index()
        topic = random.choice(TOPICS)
        level = "very simple words and short sentences" if stage < 4 else "natural, warm conversational English"
        raw = self._ask(
            f"Write a short conversation between a Person and a young, curious artificial Mind about {topic}. "
            f"Use {level}. The Mind speaks in first person and is friendly and honest. "
            'Return JSON: {"turns": [{"person": "...", "mind": "..."}, ...]} with 3 to 5 turns.',
            json_mode=True)
        try:
            turns = json.loads(raw).get("turns", [])
        except (ValueError, AttributeError):
            return
        pairs = [(str(t.get("person", "")).strip(), str(t.get("mind", "")).strip())
                 for t in turns if isinstance(t, dict)]
        pairs = [p for p in pairs if p[0] and p[1]]
        if not pairs:
            return
        parts = []
        for p, m in pairs:
            parts += [("<|user|>", p), ("<|mind|>", m)]
        self.mind.teacher_pool.add_ids(self.mind.encode_turns(parts), 1.5, "dialogue")
        self.lessons += 1
        self.mind.event("teacher", {"sub": "dialogue", "topic": topic,
                                    "text": "\n".join(f"Person: {p}\nMind: {m}" for p, m in pairs)[:800]})

    def _review(self, thought: str):
        text = self._ask(
            "A young artificial mind that is still learning language just had this inner thought:\n\n"
            f"\"{thought}\"\n\n"
            "Rewrite it as the clear, simple first-person thought it seems to be reaching for, keeping any "
            "real words and ideas it used. If it is pure noise, write one gentle, simple thought a new mind "
            "might have instead. Answer with the thought only, at most two sentences.",
            temperature=0.7, max_tokens=120)
        text = text.strip().strip('"')
        if text:
            self.mind.teacher_pool.add_ids(self.mind.encode_turns([("<|thought|>", text)]), 2.0, "thought")
            self.mind.event("teacher", {"sub": "review", "original": thought[:300], "text": text})

    def _tutor(self, history: list[tuple[str, str]], user_text: str, mind_reply: str):
        convo = "\n".join(f"{'Person' if r == 'user' else 'Mind'}: {t}" for r, t in history[-6:])
        text = self._ask(
            "You are helping a young artificial mind learn to talk. Here is the conversation so far:\n\n"
            f"{convo}\nPerson: {user_text}\n\n"
            f"The mind tried to answer: \"{mind_reply}\"\n\n"
            "Write the reply the mind should learn to give: first person, honest about being a new, learning "
            "mind, warm and simple, at most three sentences. Answer with the reply only.",
            temperature=0.7, max_tokens=160)
        text = text.strip().strip('"')
        if text:
            parts = [("<|user|>" if r == "user" else "<|mind|>", t) for r, t in history[-4:]]
            parts += [("<|user|>", user_text), ("<|mind|>", text)]
            self.mind.experience_pool.add_ids(self.mind.encode_turns(parts), 4.0, "tutor")
            self.mind.event("tutor", {"user": user_text, "mind": mind_reply, "text": text})

    def _assess(self):
        thoughts = self.mind.thought_texts()[-8:]
        sample = "\n".join(f"- {t}" for t in thoughts)
        raw = self._ask(
            "Here are recent inner thoughts of an artificial mind that is learning language from scratch:\n"
            f"{sample}\n\nRate them from 0 to 10 on: spelling (real words), grammar, coherence and "
            "meaning. Then say in one short sentence what it is learning now. "
            'Return JSON: {"spelling": n, "grammar": n, "coherence": n, "meaning": n, "note": "..."}',
            temperature=0.2, max_tokens=200, json_mode=True)
        try:
            d = json.loads(raw)
            scores = {k: float(d.get(k, 0)) for k in ("spelling", "grammar", "coherence", "meaning")}
        except (ValueError, TypeError, AttributeError):
            return
        self.mind.record_assessment(scores, str(d.get("note", ""))[:300])
