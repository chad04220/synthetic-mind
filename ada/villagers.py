"""The villagers' voices.

Each villager is played by its own small language model (its own llama.cpp server, see
localllm.py) with a persona: who they are, what they do, how they talk, how well they know the
synth, what they asked of it, and what was said lately. They talk with the synth (pitched at its
level of language), with you when you visit, and with each other; when the synth is in earshot,
their conversations become natural dialogue for it to study.

When a villager's own server isn't running, the Oracle speaks for them (in their persona), and
failing that they say one of their scripted lines.
"""
from __future__ import annotations

import json
import random
import re
import threading
import time
from collections import deque
from pathlib import Path

from .ontology import NPCS, PLACES
from .oracle import LEVEL, clean


def _line(text: str, name: str, others=()) -> str:
    """Tidy a model's reply into one spoken line by this villager."""
    text = clean(text)
    text = re.sub(rf"^\s*{re.escape(name)}\s*:\s*", "", text)
    for o in others:                                    # stop where the model starts writing someone else
        text = re.split(rf"\n\s*{re.escape(o)}\s*:", text)[0]
    text = re.sub(r"\([^)]*\)|\*[^*]*\*", "", text)     # stage directions
    text = " ".join(text.split())
    return text[:300].strip()


class PriorityGate:
    """At most `slots` villagers generate at once; the rest wait their turn by priority (lower first).

    Seven language models on a laptop CPU get more done taking turns than all running at once."""

    def __init__(self, slots: int):
        self.slots = max(1, slots)
        self.busy = 0
        self.cv = threading.Condition()
        self.waiting: list[tuple[int, int]] = []
        self.seq = 0

    def __enter__(self):
        return self

    def acquire(self, priority: int):
        with self.cv:
            self.seq += 1
            me = (priority, self.seq)
            self.waiting.append(me)
            while self.busy >= self.slots or min(self.waiting) != me:
                self.cv.wait(0.5)
            self.waiting.remove(me)
            self.busy += 1

    def release(self):
        with self.cv:
            self.busy -= 1
            self.cv.notify_all()


PRIORITY = {"turn": 0, "visitor": 0, "talk": 1, "intent": 2, "create": 3, "thought": 4}


class Villagers:
    def __init__(self, hub, folder: Path):
        self.hub = hub
        from .config import physical_cores

        self.gate = PriorityGate(max(2, physical_cores() // 2))
        self.path = folder / "villagers.json"
        self.memory: dict[str, deque] = {n: deque(maxlen=12) for n in NPCS}
        self.lock = threading.Lock()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for n, items in data.get("memory", {}).items():
                if n in self.memory:
                    self.memory[n].extend(items[-12:])
        except (OSError, ValueError):
            pass

    def save(self):
        with self.lock:
            data = {"memory": {n: list(m) for n, m in self.memory.items()}}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(self.path)

    def remember(self, name: str, who: str, text: str):
        if name in self.memory and text:
            with self.lock:
                self.memory[name].append([who, text[:240]])

    # ------------------------------------------------------------------ prompts
    def persona(self, name: str, ctx: dict, listener: str) -> str:
        p, synth = NPCS[name], self.hub.cfg.name
        stage = int(ctx.get("stage", 0))
        friend = ctx.get("friendship", 10)
        bond = ("you have only just met" if friend < 25 else "you are friends" if friend < 55 else
                "you are good friends" if friend < 80 else "you are best friends")
        level = LEVEL[min(stage + 1, 6)]
        lines = [
            f"You are {name}, the {p['role']} in a small, cosy valley village. You are {p['personality']}.",
            f"You spend your days at {PLACES.get(p['home'], 'the village')}." if p['home'] in PLACES else "",
            f"{synth} is a young synth: an artificial mind who began knowing no words at all and is learning "
            f"language by living in the valley. {synth} glows softly, like a little floating orb. With {synth}, {bond}.",
        ]
        if listener == "synth":
            lines.append(f"Speak to {synth} using {level}, so it can learn from your words. Be warm and encouraging.")
        else:
            lines.append(f"Right now you are talking with {synth}'s human friend, a visitor to the valley. "
                         f"Speak naturally and kindly.")
        lines.append("Answer with one to three short sentences of spoken words only: no emojis, no stage directions, "
                     "no quotation marks, no name in front.")
        return " ".join(x for x in lines if x)

    def situation(self, name: str, ctx: dict) -> str:
        bits = [f"It is {ctx.get('time', 'day')} in {ctx.get('season', 'spring')}; the weather is "
                f"{ctx.get('weather', 'clear')}; you are {ctx.get('where', 'in the village')}."]
        q = ctx.get("quest")
        if q:
            bits.append(f"You asked {self.hub.cfg.name} for {q}.")
        mem = list(self.memory.get(name, []))[-6:]
        if mem:
            bits.append("Recently: " + " / ".join(f"{w}: {t}" for w, t in mem))
        return " ".join(bits)

    # ------------------------------------------------------------------ talking
    def _chat(self, name: str, system: str, prompt: str, max_tokens: int = 90, temperature: float = 0.85,
              kind: str = "talk") -> str:
        """Use the villager's own server, else the Oracle, else nothing. Waits its turn at the gate."""
        server = self.hub.fleet.get(name)
        own = server is not None and server.ready
        if not own and not self.hub.oracle_ready():
            return ""
        self.gate.acquire(PRIORITY.get(kind, 2))
        t = time.time()
        try:
            if own:
                return server.chat(system, prompt, temperature, max_tokens, False)
            return self.hub.oracle.chat(system, prompt, temperature=temperature, max_tokens=max_tokens)
        finally:
            self.gate.release()
            self.hub.perf.add(f"villager voice: {kind}", time.time() - t)

    def to_synth(self, name: str, said: str, ctx: dict, kind: str = "talk") -> str:
        """A villager answers the synth (or greets it, thanks it for a gift, gives a lesson...)."""
        synth = self.hub.cfg.name
        heard = (f'{synth} says to you: "{said}"' if re.search(r"[a-z]{3}\s+[a-z]{2,}", said.lower())
                 else f"{synth} comes to you and makes some sounds; it is still learning to talk." if said else "")
        prompt = {
            "talk": f"{heard} Reply to {synth}.",
            "greet": f"{synth} floats past you. Greet it in a friendly way and mention something about your day.",
            "gift": f"{synth} just gave you {ctx.get('gift', 'a present')}. Thank it.",
            "quest": f"{synth} just brought you everything you asked for! Thank it warmly; you gave it "
                     f"{ctx.get('reward', 'some')} coins.",
            "trade": f"{synth} just {ctx.get('trade', 'traded with you')}. Say something friendly about it.",
            "lesson": f"{synth} came to your school for a lesson. Teach it a few simple words about "
                      f"{ctx.get('topic', 'everyday things')} in three or four very short sentences, and praise it.",
        }.get(kind, heard)
        text = self._chat(name, self.persona(name, ctx, "synth"), f"{self.situation(name, ctx)}\n\n{prompt}",
                          max_tokens=140 if kind == "lesson" else 80)
        text = _line(text, name, [synth])
        if not text:
            text = random.choice(NPCS[name]["lines"])
        if said:
            self.remember(name, synth, said)
        self.remember(name, name, text)
        return text

    def to_visitor(self, name: str, said: str, ctx: dict) -> str:
        prompt = f'The visitor says to you: "{said}"\nReply to the visitor.'
        text = _line(self._chat(name, self.persona(name, ctx, "visitor"), f"{self.situation(name, ctx)}\n\n{prompt}",
                                max_tokens=110, kind="visitor"), name, ["Visitor", "You"])
        if not text:
            text = random.choice(NPCS[name]["lines"])
        self.remember(name, "visitor", said)
        self.remember(name, name, text)
        return text

    def banter(self, a: str, b: str, ctx: dict) -> list[tuple[str, str]]:
        """A short conversation between two villagers, each speaking with their own voice."""
        synth = self.hub.cfg.name
        topic = random.choice(["the weather", "their work today", f"how {synth} is learning to talk",
                               "something funny that happened", "the season", "food", "the lake and the river",
                               "a book", "the festival they are planning", "the animals in the valley"])
        out: list[tuple[str, str]] = []
        speakers = [a, b, a, b][:random.choice([2, 3, 4])]
        for i, who in enumerate(speakers):
            other = b if who == a else a
            convo = "\n".join(f"{n}: {t}" for n, t in out)
            if i == 0:
                prompt = f"You meet {other} the {NPCS[other]['role']} in the village. Start a short chat about {topic}."
            else:
                prompt = f"You are chatting with {other}.\n{convo}\nReply to {other}."
            ctx2 = dict(ctx, friendship=60)
            system = self.persona(who, ctx2, "visitor").replace(
                f"Right now you are talking with {synth}'s human friend, a visitor to the valley. Speak naturally and kindly.",
                f"Right now you are talking with your neighbour {other}. Use simple, clear everyday English.")
            text = _line(self._chat(who, system, prompt, max_tokens=70, temperature=0.95), who, [other])
            if not text:
                break
            out.append((who, text))
        for who, text in out:
            self.remember(who, who, text)
        return out

    # ------------------------------------------------------------------ a villager's own mind
    def intent(self, name: str, perception: str, ctx: dict) -> str:
        """What the villager decides to do next, as one sentence in its own words."""
        from .world.agent import CRAFTS, WORK

        p = NPCS[name]
        work, craft = WORK.get(p["role"], ("I do my work.", ""))[0], CRAFTS.get(p["role"], "")
        system = (f"You are {name}, the {p['role']} in a small valley village. You are {p['personality']}. "
                  "You decide what to do next, like a person living their day.")
        prompt = (f"What you notice right now: {perception}\n\n"
                  f"Your work: {work} In your free time you love to {craft or 'make things'}. You can also eat, drink "
                  "water at the well, rest, walk to a place, talk to someone nearby, give someone a present, paint at "
                  "an easel, play and record music at the piano, carve a sculpture, build something, write a poem, "
                  "read a book, or admire what your neighbours made.\n"
                  "Write ONE short sentence starting with \"I\" saying what you do next and where, for example: "
                  "\"I go to the bakery and bake bread.\" or \"I talk to Theo.\" Then stop.")
        text = self._chat(name, system, prompt, max_tokens=30, temperature=0.8, kind="intent")
        text = _line(text, name).split("\n")[0]
        return text if text.lower().startswith("i ") else ""

    def thought(self, name: str, perception: str, ctx: dict) -> str:
        """One sentence of the villager's inner monologue."""
        p = NPCS[name]
        system = (f"You are {name}, the {p['role']} in a small valley village. You are {p['personality']}. "
                  "Write one private thought you have right now: one or two short sentences in the first person, "
                  "honest and specific, no quotation marks.")
        diary = "; ".join(ctx.get("diary", [])[-4:])
        prompt = f"Right now: {perception}\nLately: {diary or 'an ordinary day'}\nYour thought:"
        return _line(self._chat(name, system, prompt, max_tokens=50, temperature=0.95, kind="thought"), name)

    def turn(self, speaker: str, listener: str, history: list, topic: str, opening: bool, closing: bool,
             ctx: dict) -> str:
        """The speaker's next line in a conversation (the listener waits for it)."""
        synth = self.hub.cfg.name
        to_synth = listener == synth
        if to_synth:
            system = self.persona(speaker, ctx, "synth")
        else:
            role = NPCS.get(listener, {}).get("role", "neighbour")
            system = self.persona(speaker, ctx, "visitor").replace(
                f"Right now you are talking with {synth}'s human friend, a visitor to the valley. Speak naturally and kindly.",
                f"Right now you are talking with your neighbour {listener} the {role}. Use simple, clear everyday English.")
        convo = "\n".join(f"{n}: {t}" for n, t in history[-8:])
        if opening:
            prompt = f"You walk up to {listener} because you want to talk about {topic}. Say the first thing you say."
        else:
            prompt = f"You are talking with {listener} about {topic}.\n{convo}\nReply to {listener}."
        if closing:
            prompt += " This is your last line: finish the conversation kindly and say goodbye."
        text = _line(self._chat(speaker, system, f"{self.situation(speaker, ctx)}\n\n{prompt}", max_tokens=70,
                                temperature=0.9, kind="turn"), speaker, [listener])
        if text:
            self.remember(speaker, speaker, text)
        return text

    def create(self, name: str, creation: dict, ctx: dict) -> dict:
        """A title (and, for writing, the text) for something the villager made."""
        p = NPCS[name]
        system = (f"You are {name}, the {p['role']} in a small valley village. You are {p['personality']}. "
                  "You just finished making something and you name it. Plain text only.")
        if creation["kind"] == "writing":
            prompt = (f"You wrote a short poem ({ctx.get('season', 'spring')}, {ctx.get('where', 'in the village')}). "
                      "Write the poem: four to six short lines. Then on the last line write: Title: <a title>.")
            raw = clean(self._chat(name, system, prompt, max_tokens=140, temperature=1.0, kind="create"))
            title = ""
            lines = []
            for ln in raw.splitlines():
                if ln.lower().startswith("title:"):
                    title = ln.split(":", 1)[1].strip().strip('"')
                elif ln.strip():
                    lines.append(ln.strip())
            return {"title": title or (lines[0][:40] if lines else ""), "text": "\n".join(lines[:8])}
        prompt = f"You just made {creation.get('about', 'something')}. Give it a short, lovely title (two to five words). Only the title."
        title = _line(self._chat(name, system, prompt, max_tokens=16, temperature=0.9, kind="create"), name).strip('"').split("\n")[0]
        return {"title": title[:60]}

    def status(self) -> list[dict]:
        out = []
        for n in NPCS:
            s = self.hub.fleet.get(n)
            out.append({"name": n, "role": NPCS[n]["role"], "voice": s.info() if s else {"status": "off"},
                        "color": NPCS[n]["color"]})
        return out


def now() -> float:
    return time.time()
