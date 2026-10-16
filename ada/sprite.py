"""The Sprite of All Knowing: a small glowing being that floats beside Zen and answers whatever
Zen asks. It is the one language model in the program (llama.cpp on the CPU, or Ollama), and it is
used only when it is asked: by Zen (its own brain writes the question), or by you from its tab.

It never acts in the world and never decides anything for Zen. Its answers are plain, true and
short, in simple words, so they are good material for a mind learning language from scratch.
"""
from __future__ import annotations

import json
import re

from .oracle import Oracle, clean

CRITIC = ("You are also a fair and honest judge of art. {z} is a young synth learning to make art from nothing, one mark "
          "or one note at a time, with no lessons and no examples. Judge only what is really there. Do not be generous "
          "to random scribbles or noise; reward real shapes, deliberate lines, colour chosen with care, balance, "
          "rhythm, melody and structure. A score of 0-2 is noise, 3-4 has a little intent, 5-6 is a clear idea, "
          "7-8 is good, 9-10 is beautiful.")
WHAT = {"painting": "a painting (it painted every cell of it with a brush on paper)",
        "music": "a short piece it played on the piano, note by note",
        "sculpture": "a clay sculpture it built bit by bit (shown from one side, slightly above)",
        "poem": "something it wrote"}


class SpriteVoice:
    def __init__(self, oracle: Oracle, synth: str = "Zen"):
        self.o = oracle
        self.synth = synth

    @property
    def system(self) -> str:
        z = self.synth
        return (f"You are the Sprite of All Knowing, a small glowing sprite that floats beside {z}. {z} is a young "
                f"synth: an artificial mind that started knowing nothing, living alone in a wide wild world (forests, "
                f"rivers, mountains, deserts, ruins) and learning to speak, to understand and to use its body. You know "
                f"everything and you answer whatever {z} asks, truthfully, kindly and simply. You never tell {z} what "
                f"to do and you never decide for it; you only answer. Use short, clear sentences and common words. "
                f"Write plain text: no markdown, lists, emojis or stage directions.")

    def answer(self, question: str, situation: str = "", stage: int = 0) -> str:
        """Answer Zen's question. Early on its questions are babble: answer what it most likely means,
        given where it is, or say plainly what it might be asking about and answer that."""
        q = (question or "").strip()[:400]
        level = ("very short sentences of a few words each" if stage <= 1 else
                 "short, simple sentences" if stage <= 3 else "clear, natural sentences")
        hint = ("" if _wordy(q) else
                f" {self.synth}'s words may not make sense yet: it is still learning to speak. Guess kindly what it most "
                f"likely wants to know about what is around it, say that question in proper words first ('You may be "
                f"asking: ...'), then answer it.")
        prompt = (f"Where {self.synth} is now: {situation[:500]}\n{self.synth} asks you: \"{q}\"\n"
                  f"Answer in two to four {level}.{hint}")
        return _line(self.o.chat(self.system, prompt, temperature=0.5, max_tokens=140), 600)

    def critique(self, kind: str, image: bytes | None = None, audio: bytes | None = None, text: str = "",
                 marks: int = 0, stage: int = 0) -> dict:
        """Look at (or listen to) a finished piece. Returns {"score": 0..10, "see": str, "say": str} or {}."""
        z = self.synth
        sysmsg = self.system + " " + CRITIC.format(z=z)
        prompt = (f"{z} just made {WHAT.get(kind, 'something')}" + (f" in {marks} marks" if marks else "") + "."
                  + (f' It says:\n"{text[:800]}"' if text else "")
                  + ' Reply only with JSON: {"score": a number from 0 to 10, "see": "one plain sentence: exactly what '
                    'is in it", "say": "one or two short, kind, honest sentences to ' + z + ' about it, with one thing '
                    'to try next time"}')
        try:
            if (image or audio) and getattr(self.o, "senses", False):
                raw = self.o.look_listen(sysmsg, prompt, images=[image] if image else [], audio=[audio] if audio else [])
            elif text:
                raw = self.o.chat(sysmsg, prompt, temperature=0.4, max_tokens=200, as_json=True)
            else:
                return {}
            m = re.search(r"\{.*\}", raw, re.S)
            d = json.loads(m.group(0) if m else raw)
            score = float(d.get("score", 0))
        except (ValueError, TypeError, AttributeError, RuntimeError, OSError):
            return {}
        return {"score": max(0.0, min(10.0, score)), "see": _line(str(d.get("see", "")), 300),
                "say": _line(str(d.get("say", "")), 400)}

    def to_visitor(self, said: str, about_synth: str) -> str:
        """You ask the Sprite something (on its tab)."""
        return _line(self.o.chat(self.system, f"Someone who cares about {self.synth} asks you: \"{said[:600]}\"\n"
                                              f"What you know about {self.synth} right now: {about_synth[:600]}\n"
                                              f"Answer in a few clear sentences.", temperature=0.6, max_tokens=220), 1200)


def _wordy(q: str) -> bool:
    """Does this look like a real question in words (rather than babble)?"""
    words = re.findall(r"[a-zA-Z']+", q.lower())
    if len(words) < 2:
        return False
    common = {"what", "why", "where", "who", "how", "is", "the", "a", "do", "does", "can", "i", "you", "it", "this",
              "that", "are", "of", "to", "in", "when", "which"}
    return sum(w in common for w in words) >= 2 and len(set(words)) >= max(2, len(words) // 2)


def _line(text, limit: int = 600) -> str:
    t = clean(text or "").replace("\n", " ")
    t = re.sub(r'["“”]\s*["“”]', " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:limit]
