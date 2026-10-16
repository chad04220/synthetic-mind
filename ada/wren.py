"""Wren's voice: everything the one language model writes, as Wren.

Wren is the companion who lives with the synth at the homestead and raises it: a pretrained
language model (llama.cpp on the CPU, or Ollama) that already knows language and the world. The
World runs Wren's body and gives it a short list of things it could do; the model chooses one and
says what it says out loud. It also talks with the synth turn by turn, answers its questions,
tells it a bedtime story about the day, reads it picture books, suggests the reply the synth
should have given you, and writes the Academy's lessons from the days they spent together.

Wren never touches the synth's weights. Everything it says near the synth is something the synth
hears, and the synth studies what it hears next to what it saw and did.
"""
from __future__ import annotations

import json
import random
import re

from .oracle import Oracle, clean

# How Wren talks to the synth at each of its stages (Academy stage numbers).
LEVEL = {
    0: "baby talk: two to five very common words per sentence, naming what is right here",
    1: "baby talk: two to five very common words per sentence, naming what is right here",
    2: "toddler talk: short sentences of three to seven common words about what is here and now",
    3: "simple sentences a small child understands, one idea each",
    4: "plain English for a curious six-year-old",
    5: "plain English for a curious ten-year-old",
    6: "clear, warm English",
}
TOPICS = ["the garden and how plants grow", "cooking soup", "baking bread", "the hens and their eggs", "the bees and honey",
          "Moss the cat", "the pond, the ducks and the frogs", "rain and clouds", "fire and keeping warm", "the seasons",
          "day and night", "the stars and the moon", "colors", "counting", "feelings", "words and names", "the woods",
          "trees and fruit", "water", "music", "being kind", "the body", "sleep and dreams", "asking questions",
          "hot and cold", "big and small", "the kitchen", "tools and making things", "wind and weather", "snow"]
RELATIONS = "is a, color, is, made of, used for, found in, can"


class WrenVoice:
    def __init__(self, oracle: Oracle, name: str = "Wren", synth: str = "Zen"):
        self.o = oracle
        self.name, self.synth = name, synth

    @property
    def system(self) -> str:
        n, z = self.name, self.synth
        return (f"You are {n}. You live with {z} in a small house in a quiet hollow: a kitchen with a stove, a living "
                f"room with a fireplace, a garden, hens, a cat called Moss, a pond and the woods. {z} is a young synth, "
                f"an artificial mind that started knowing nothing and is learning to speak and to live, and you are "
                f"raising {z}. You are warm, patient, playful and practical. You love the garden, cooking and the stars. "
                f"When you speak to {z} you use short, simple, concrete sentences about what is here and now, you name "
                f"things and say what you are both doing, and you answer {z}'s attempts at words as if they meant "
                f"something. Call {z} by name (or \"you\" when talking to {z}); never \"he\" or \"she\". "
                f"Write plain text: no markdown, lists, emojis, stage directions or asterisks.")

    def _level(self, stage: int, up: int = 0) -> str:
        return LEVEL[max(0, min(6, stage + up))]

    def _json(self, prompt: str, **kw) -> dict:
        try:
            text = self.o.chat(self.system, prompt, as_json=True, **kw)
            m = re.search(r"\{.*\}", text, re.S)
            return json.loads(m.group(0) if m else text)
        except (ValueError, TypeError):
            return {}

    # ------------------------------------------------------------------ living
    def decide(self, situation: str, synth_state: str, memory: list[str], options: list[str], stage: int,
               synth_near: bool) -> dict:
        """Choose one of the options. Returns {"choice": index, "say": str, "thought": str}."""
        menu = "\n".join(f"{i + 1}. {o}" for i, o in enumerate(options))     # options say "(needed now)" when urgent
        mem = "\n".join(f"- {m}" for m in memory[-6:]) or "- (nothing yet today)"
        say = (f'"say": what you say out loud to {self.synth} as you start (one or two sentences in {self._level(stage)}; '
               f'name what you are doing or what {self.synth} sees; may be empty)') if synth_near else \
            f'"say": "" ({self.synth} is not nearby)'
        d = self._json(f"Where you are: {situation}\n{self.synth}: {synth_state}\nEarlier:\n{mem}\n\n"
                       f"What you could do next:\n{menu}\n\nChoose what to do now, as {self.name}. Things marked (needed now) "
                       f"come first. Otherwise keep the house, the garden and the animals going, and play and talk with "
                       f"{self.synth} often: that is how {self.synth} learns. Don't do the same thing again and again. "
                       f"Reply with JSON: "
                       f'{{"choice": the number, {say}, "thought": "one short private thought"}}',
                       temperature=0.75, max_tokens=160)
        try:
            choice = int(d.get("choice", 0)) - 1
        except (TypeError, ValueError):
            choice = -1
        return {"choice": choice if 0 <= choice < len(options) else -1,
                "say": _line(d.get("say", "")) if synth_near else "", "thought": _line(d.get("thought", ""))}

    def turn(self, history: list, topic: str, stage: int, opening: bool, closing: bool, situation: str) -> str:
        """One turn in a conversation with the synth."""
        z = self.synth
        convo = "\n".join(f"{who}: {line}" for who, line in history[-8:]) or "(you start the conversation)"
        how = ("Start the conversation" + (f" about {topic}" if topic else "")) if opening else \
            ("Say a warm goodbye in one sentence" if closing else
             f"Reply to {z}. If {z}'s words are babble or broken, guess kindly what {z} means and say it back properly "
             f"(for example {z}: \"apple eat\" -> \"Yes! You want to eat the apple.\"), then add one small new thing")
        text = self.o.chat(self.system, f"Where you are: {situation}\nThe conversation so far:\n{convo}\n\n{how}. "
                                        f"Use {self._level(stage)}. At most two short sentences. Reply only with your words.",
                           temperature=0.8, max_tokens=90)
        return _line(text)

    def answer(self, question: str, stage: int, situation: str = "") -> str:
        z = self.synth
        if not re.search(r"[a-z]{3}", question.lower()):
            return _line(self.o.chat(self.system, f"{z} tries to ask you something, but the words are still sounds. "
                                                  f"Answer warmly in one or two sentences using {self._level(stage)}, "
                                                  f"and name something you can both see. {situation}", max_tokens=80))
        return _line(self.o.chat(self.system, f"{situation}\n{z} asks you: \"{question}\"\nAnswer in two or three "
                                              f"sentences using {self._level(stage)}.", max_tokens=160), 400)

    def story(self, day: int, diary: list[str], stage: int) -> str:
        today = "\n".join(f"- {d}" for d in diary[-14:]) or "- a quiet day at home"
        text = self.o.chat(self.system, f"It is the end of day {day}. {self.synth} is tucked into bed. Today:\n{today}\n\n"
                                        f"Tell {self.synth} a short bedtime story (6 to 9 sentences) about today, gentle "
                                        f"and a little magical, using {self._level(stage, 1)}. Start with a title on its "
                                        f"own line.", temperature=0.9, max_tokens=420)
        return clean(text)[:1600]

    def book(self, stage: int, topic: str | None = None) -> str:
        topic = topic or random.choice(TOPICS)
        return clean(self.o.chat(self.system, f"Write one page (5 to 7 sentences) of a picture book for {self.synth} "
                                              f"about {topic}, using {self._level(stage, 1)}. Start with a title line.",
                                 temperature=0.9, max_tokens=320))[:1400]

    def name_work(self, work: dict, maker: str) -> str:
        what = {"painting": f"a painting of {work.get('data', {}).get('subject', 'the hollow')}",
                "music": "a little song played on the piano", "sculpture":
                f"a sculpture in {work.get('data', {}).get('material', 'clay')}", "poem": "a poem",
                "building": f"a {work.get('data', {}).get('what', 'birdhouse')}"}.get(work.get("kind", ""), "something")
        by = "you made" if maker == self.name else f"{self.synth} made"
        return _line(self.o.chat(self.system, f"Give a short, lovely title (two to five words) to {what} that {by}. "
                                              "Reply with the title only.", temperature=0.9, max_tokens=20), 60).strip('"')

    def poem(self, stage: int, about: str) -> str:
        return clean(self.o.chat(self.system, f"Write a tiny poem (4 lines) about {about}, using {self._level(stage, 1)}.",
                                 temperature=0.95, max_tokens=120))[:500]

    def star_fact(self, stage: int) -> str:
        return _line(self.o.chat(self.system, f"You and {self.synth} look at the night sky through the telescope. Tell "
                                              f"{self.synth} one true, wonderful thing about the stars, the moon or the "
                                              f"planets in two sentences, using {self._level(stage)}.", max_tokens=100), 300)

    # ------------------------------------------------------------------ you
    def to_visitor(self, said: str, situation: str, about_synth: str) -> str:
        return _line(self.o.chat(self.system, f"{situation}\nYou are talking with {self.synth}'s friend, a person who "
                                              f"visits the hollow (they started {self.synth}'s life). About {self.synth}: "
                                              f"{about_synth}\nThey say: \"{said}\"\nReply warmly in one to three sentences, "
                                              "in clear normal English.", max_tokens=150), 500)

    def tutor(self, history: list, user: str, mind: str, stage: int) -> str:
        z = self.synth
        convo = "\n".join(f"{'Friend' if r == 'user' else z}: {t}" for r, t in history[-6:])
        return _line(self.o.chat(self.system,
                                 f"{z} is talking with its friend.\n{convo}\nFriend: {user}\n{z} tried to say: \"{mind}\"\n\n"
                                 f"Write the reply {z} should learn to give: first person, as {z}, honest about being a "
                                 f"young mind who is still learning, warm, at most two sentences, using "
                                 f"{self._level(stage, 1)}. Reply only with {z}'s words.", max_tokens=110), 400)

    # ------------------------------------------------------------------ the Academy's lessons
    def lesson_pack(self, topic: str, stage: int, focus: list[str] | None = None, memories: list[str] | None = None) -> dict:
        """A lesson in Wren's words, about a topic and the days they shared; questions; facts."""
        hint = f" Make sure to cover: {'; '.join(focus)}." if focus else ""
        mem = (" Use things you and " + self.synth + " did together as examples: " + "; ".join(memories[-5:]) + ".") \
            if memories else ""
        d = self._json(f"Teach {self.synth} about {topic}.{hint}{mem} Use {self._level(stage, 1)}. Return JSON with keys: "
                       '"lesson": a short paragraph of 4 to 8 sentences in your own voice; '
                       f'"qa": 3 objects with "q" (a question {self.synth} might ask) and "a" (a short answer); '
                       f'"facts": up to 8 objects with "s", "r", "o" where "r" is one of: {RELATIONS}, and "s" and '
                       '"o" are one or two lowercase words (example: {"s": "egg", "r": "found in", "o": "nest box"}).',
                       temperature=0.8, max_tokens=700)
        lesson = clean(str(d.get("lesson", "")))
        qa = [(clean(str(x.get("q", ""))), clean(str(x.get("a", "")))) for x in d.get("qa", []) if isinstance(x, dict)]
        facts = [x for x in d.get("facts", []) if isinstance(x, dict)]
        return {"topic": topic, "lesson": lesson, "qa": [q for q in qa if q[0] and q[1]], "facts": facts}

    def assess(self, thoughts: list[str], self_rate: float) -> dict:
        sample = "\n".join(f"- {t}" for t in thoughts[-8:])
        d = self._json(f"These are recent inner thoughts of {self.synth}, learning language from scratch:\n{sample}\n\n"
                       "Rate them 0 to 10 for spelling (real words), grammar, coherence and meaning, and say in one short "
                       'sentence what it is learning now. Return JSON: {"spelling": n, "grammar": n, "coherence": n, '
                       '"meaning": n, "note": "..."}', temperature=0.2, max_tokens=200)
        try:
            return {k: float(d.get(k, 0)) for k in ("spelling", "grammar", "coherence", "meaning")} | \
                {"note": str(d.get("note", ""))[:300]}
        except (TypeError, ValueError):
            return {}


def _line(text, limit: int = 260) -> str:
    """One clean spoken line: no quotes, speaker labels, stage directions or emojis."""
    t = clean(str(text or ""))
    t = re.sub(r"^\s*(?:Wren|Me|I)\s*:\s*", "", t)
    t = re.sub(r"\([^)]*\)|\[[^\]]*\]", "", t)
    t = re.sub(r"[\U0001F000-\U0001FAFF☀-➿]", "", t)
    t = " ".join(t.split()).strip().strip('"').strip()
    return t[:limit]
