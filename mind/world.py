"""A small garden world the mind lives in through a body.

The body senses its surroundings as first-person text ("I see an apple 2 steps north"),
the same network that learns language picks an action, and what happens is narrated
back in words. Hunger, boredom and novelty give the body intrinsic rewards, so it
learns to look after itself and explore while its language is grounded in experience.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

W, H = 28, 18
DAY = 720  # ticks per day

ACTIONS = ["rest", "north", "south", "west", "east", "use", "take", "drop", "look", "speak", "sleep", "approach"]
DIRS = {"north": (0, -1), "south": (0, 1), "west": (-1, 0), "east": (1, 0)}

# terrain codes
GRASS, WATER, SAND, TREE, ROCK, FLOWERS, BUSH, PATH = range(8)
TERRAIN_NAMES = ["grass", "water", "sand", "a tree", "a rock", "flowers", "a bush", "a path"]
BLOCKING = {WATER, TREE, ROCK, BUSH}

KINDS = {
    # kind: (portable, description)
    "apple": (True, "a red apple"),
    "berry": (True, "a handful of berries"),
    "ball": (True, "a bouncy ball"),
    "book": (True, "a book"),
    "block": (True, "a wooden block"),
    "seed": (True, "a seed"),
    "lamp": (False, "a lamp"),
    "musicbox": (False, "a music box"),
    "mirror": (False, "a mirror"),
    "sign": (False, "a sign"),
    "bed": (False, "a soft bed"),
    "cat": (False, "a cat"),
    "flower": (False, "a flower"),
}
FOOD = {"apple": 35.0, "berry": 15.0}
NOTES = ["do", "re", "mi", "fa", "sol", "la", "ti"]


@dataclass
class Body:
    x: int = 3
    y: int = 3
    facing: str = "south"
    energy: float = 80.0
    fun: float = 60.0
    holding: dict | None = None
    sleeping: bool = False
    said: str = ""
    said_ttl: int = 0
    steps: int = 0
    visits: dict = field(default_factory=dict)
    uses: dict = field(default_factory=dict)
    faints: int = 0
    total_reward: float = 0.0


class World:
    def __init__(self, seed: int | None = None):
        self.rng = random.Random(seed)
        self.tick_n = 0
        self.next_id = 1
        self.entities: dict[int, dict] = {}
        self.terrain = [[GRASS] * W for _ in range(H)]
        self.body = Body()
        self.log: list[str] = []
        self.book_texts: list[str] = []
        self._generate()

    # -- generation -----------------------------------------------------------
    def _generate(self):
        r = self.rng
        # a pond with a sandy shore
        cx, cy = r.randint(16, 22), r.randint(5, 12)
        for y in range(H):
            for x in range(W):
                d = math.hypot((x - cx) / 1.4, y - cy)
                if d < 2.6:
                    self.terrain[y][x] = WATER
                elif d < 3.6:
                    self.terrain[y][x] = SAND
        for _ in range(26):
            self._scatter(TREE)
        for _ in range(10):
            self._scatter(ROCK)
        for _ in range(8):
            self._scatter(BUSH)
        for _ in range(22):
            self._scatter(FLOWERS)
        # a path from the home corner
        x, y = 2, 2
        while x < W - 3:
            self.terrain[y][x] = PATH
            x += 1
            if r.random() < 0.3:
                y = max(1, min(H - 2, y + r.choice((-1, 1))))
                self.terrain[y][x] = PATH
        for y in range(1, 6):
            for x in range(1, 6):
                if self.terrain[y][x] in BLOCKING:
                    self.terrain[y][x] = GRASS
        self.add("bed", 2, 2)
        self.add("lamp", 4, 2)
        self.add("mirror", 1, 4)
        self.add("sign", 5, 4, text="Welcome home. Explore, play and learn!")
        for k, n in (("apple", 4), ("berry", 3), ("ball", 2), ("book", 4), ("block", 4), ("seed", 2)):
            for _ in range(n):
                self.add_random(k)
        self.add_random("musicbox")
        self.add_random("cat")
        self.body.x, self.body.y = 3, 3

    def _scatter(self, t):
        for _ in range(50):
            x, y = self.rng.randrange(W), self.rng.randrange(H)
            if self.terrain[y][x] == GRASS and not (x < 7 and y < 6):
                self.terrain[y][x] = t
                return

    def walkable(self, x, y) -> bool:
        return 0 <= x < W and 0 <= y < H and self.terrain[y][x] not in BLOCKING

    def add(self, kind: str, x: int, y: int, **state) -> dict | None:
        if kind not in KINDS or not (0 <= x < W and 0 <= y < H):
            return None
        e = {"id": self.next_id, "kind": kind, "x": x, "y": y, **state}
        if kind == "book" and "text" not in e:
            e["text"] = ""
        self.entities[self.next_id] = e
        self.next_id += 1
        return e

    def add_random(self, kind: str):
        for _ in range(100):
            x, y = self.rng.randrange(W), self.rng.randrange(H)
            if self.walkable(x, y) and not self.at(x, y) and (x, y) != (self.body.x, self.body.y):
                return self.add(kind, x, y)
        return None

    def at(self, x, y) -> list[dict]:
        return [e for e in self.entities.values() if e["x"] == x and e["y"] == y]

    def remove_at(self, x, y):
        for e in self.at(x, y):
            del self.entities[e["id"]]

    # -- senses ---------------------------------------------------------------
    @property
    def time_of_day(self) -> str:
        p = (self.tick_n % DAY) / DAY
        return ("morning" if p < 0.25 else "afternoon" if p < 0.5 else "evening" if p < 0.7 else "night")

    @property
    def light(self) -> float:
        p = (self.tick_n % DAY) / DAY
        return max(0.25, min(1.0, 1.25 - 1.4 * abs(p - 0.35) * 1.6)) if p < 0.85 else 0.25

    def feelings(self) -> list[str]:
        b = self.body
        f = []
        if b.energy < 25:
            f.append("very hungry and tired")
        elif b.energy < 50:
            f.append("hungry")
        if b.fun < 30:
            f.append("bored")
        elif b.fun > 80:
            f.append("happy")
        return f

    def _rel(self, dx, dy) -> str:
        parts = []
        if dy:
            parts.append(f"{abs(dy)} {'north' if dy < 0 else 'south'}")
        if dx:
            parts.append(f"{abs(dx)} {'west' if dx < 0 else 'east'}")
        return " and ".join(parts)

    def visible(self, radius: int = 6) -> list[tuple[int, dict]]:
        b = self.body
        r = radius if self.light > 0.4 or self._lamp_near() else 3
        out = []
        for e in self.entities.values():
            d = abs(e["x"] - b.x) + abs(e["y"] - b.y)
            if d <= r:
                out.append((d, e))
        out.sort(key=lambda t: t[0])
        return out

    def _lamp_near(self) -> bool:
        b = self.body
        return any(e["kind"] == "lamp" and e.get("on") and abs(e["x"] - b.x) + abs(e["y"] - b.y) < 6
                   for e in self.entities.values())

    def observe(self) -> str:
        b = self.body
        s = [f"It is {self.time_of_day}."]
        f = self.feelings()
        s.append(f"I feel {' and '.join(f)}." if f else "I feel fine.")
        if b.sleeping:
            s.append("I am asleep.")
        s.append(f"I hold {KINDS[b.holding['kind']][1]}." if b.holding else "My hands are empty.")
        around = []
        for d, (dx, dy) in DIRS.items():
            x, y = b.x + dx, b.y + dy
            if not (0 <= x < W and 0 <= y < H):
                around.append(f"{d} is the edge")
                continue
            ents = self.at(x, y)
            what = KINDS[ents[0]["kind"]][1] if ents else TERRAIN_NAMES[self.terrain[y][x]]
            around.append(f"{d} is {what}")
        s.append("Around me: " + ", ".join(around) + ".")
        here = [e for e in self.at(b.x, b.y)]
        if here:
            s.append("Here is " + KINDS[here[0]["kind"]][1] + ".")
        seen = [f"{KINDS[e['kind']][1]} {self._rel(e['x'] - b.x, e['y'] - b.y)}"
                for d, e in self.visible() if d > 1][:3]
        if seen:
            s.append("I see " + "; ".join(seen) + ".")
        return " ".join(s)

    def describe_self(self) -> str:
        b = self.body
        f = self.feelings()
        return (f"In the mirror I see myself: a small round body. I have taken {b.steps} steps "
                f"and visited {len(b.visits)} places. I feel {' and '.join(f) if f else 'fine'}.")

    # -- acting -----------------------------------------------------------------
    def step(self, action: str) -> tuple[float, str, dict]:
        """Apply one action. Returns (reward, narration, info)."""
        b = self.body
        self.tick_n += 1
        b.steps += 1
        reward = 0.0
        info: dict = {}
        narr = ""
        if b.said_ttl > 0:
            b.said_ttl -= 1

        if b.sleeping and action not in ("sleep", "rest"):
            b.sleeping = False
            narr = "I wake up. "
        if action in DIRS:
            r2, n2 = self._move(action)
            reward += r2
            narr += n2
        elif action == "approach":
            target = next((e for d, e in self.visible() if d > 0 and self._interesting(e)), None)
            if target:
                dx, dy = target["x"] - b.x, target["y"] - b.y
                opts = []
                if dx:
                    opts.append("east" if dx > 0 else "west")
                if dy:
                    opts.append("south" if dy > 0 else "north")
                moved = False
                for d in sorted(opts, key=lambda _: self.rng.random()):
                    ddx, ddy = DIRS[d]
                    if self.walkable(b.x + ddx, b.y + ddy):
                        r2, n2 = self._move(d)
                        reward += r2
                        narr += f"I go toward {KINDS[target['kind']][1]}. " + n2
                        moved = True
                        break
                if not moved:
                    narr += f"I want to reach {KINDS[target['kind']][1]} but something is in the way."
            else:
                narr += "I look for something interesting, but I see nothing new."
        elif action == "use":
            reward, narr2, info = self._use()
            narr += narr2
        elif action == "take":
            e = self._target(portable=True)
            if b.holding:
                narr += f"My hands are full; I already hold {KINDS[b.holding['kind']][1]}."
            elif e:
                del self.entities[e["id"]]
                b.holding = e
                narr += f"I pick up {KINDS[e['kind']][1]}."
                reward += self._novel("take:" + e["kind"], 0.2)
            else:
                narr += "There is nothing here to pick up."
                reward -= 0.02
        elif action == "drop":
            if b.holding:
                e = b.holding
                b.holding = None
                if e["kind"] == "seed" and self.terrain[b.y][b.x] in (GRASS, FLOWERS):
                    e["kind"] = "flower"
                    e["grow"] = self.tick_n
                    narr += "I plant the seed in the ground. Something may grow."
                    reward += self._novel("plant", 0.6)
                else:
                    narr += f"I put down {KINDS[e['kind']][1]}."
                e["x"], e["y"] = b.x, b.y
                self.entities[e["id"]] = e
            else:
                narr += "I have nothing to put down."
                reward -= 0.02
        elif action == "look":
            narr += "I look around. " + self.observe()
            reward += self._novel(f"look:{b.x // 4},{b.y // 4}", 0.1)
        elif action == "speak":
            info["speak"] = True
            reward += self._novel("speak", 0.1) if b.said_ttl == 0 else -0.02
            narr += "I speak."
        elif action == "sleep":
            if not b.sleeping:
                narr += "I lie down and close my eyes."
            b.sleeping = True
            on_bed = any(e["kind"] == "bed" for e in self.at(b.x, b.y))
            b.energy = min(100.0, b.energy + (1.6 if on_bed else 0.6))
            if b.energy < 60:
                reward += 0.03
        else:  # rest
            narr += "I rest for a moment."

        # needs
        b.energy = max(0.0, b.energy - (0.08 if b.sleeping else 0.22))
        b.fun = max(0.0, b.fun - 0.15)
        reward -= 0.004 * (100 - b.fun) / 100
        if b.energy <= 0:
            reward -= 2.0
            b.faints += 1
            bed = next((e for e in self.entities.values() if e["kind"] == "bed"), None)
            b.x, b.y = (bed["x"], bed["y"]) if bed else (3, 3)
            b.energy, b.sleeping = 40.0, True
            narr += " I am too weak and I faint. I wake up in my bed."
        self._world_tick()
        b.total_reward += reward
        self.log.append(narr)
        self.log = self.log[-60:]
        return reward, narr.strip(), info

    def _move(self, action: str) -> tuple[float, str]:
        b = self.body
        dx, dy = DIRS[action]
        b.facing = action
        nx, ny = b.x + dx, b.y + dy
        if not self.walkable(nx, ny):
            what = TERRAIN_NAMES[self.terrain[ny][nx]] if 0 <= nx < W and 0 <= ny < H else "the edge"
            return -0.05, f"I cannot go {action}, there is {what}."
        b.x, b.y = nx, ny
        key = f"{nx},{ny}"
        c = b.visits.get(key, 0)
        b.visits[key] = c + 1
        narr = f"I walk {action}."
        here = self.at(nx, ny)
        if here:
            narr += f" I find {KINDS[here[0]['kind']][1]}."
        return 0.25 / math.sqrt(1 + c), narr

    def _interesting(self, e) -> bool:
        b = self.body
        if e["kind"] in FOOD:
            return b.energy < 70
        return b.uses.get("use:" + e["kind"], 0) < 4 or e["kind"] in ("cat", "book", "ball")

    def _novel(self, key: str, base: float) -> float:
        c = self.body.uses.get(key, 0)
        self.body.uses[key] = c + 1
        return base / math.sqrt(1 + c)

    def _target(self, portable: bool | None = None) -> dict | None:
        b = self.body
        dx, dy = DIRS[b.facing]
        for x, y in ((b.x, b.y), (b.x + dx, b.y + dy)):
            for e in self.at(x, y):
                if portable is None or KINDS[e["kind"]][0] == portable:
                    return e
        if portable is None:
            for d, e in self.visible(1):
                return e
        return None

    def _use(self) -> tuple[float, str, dict]:
        b = self.body
        info: dict = {}
        h = b.holding
        if h and h["kind"] in FOOD:
            gain = FOOD[h["kind"]]
            hunger = (100 - b.energy) / 100
            b.energy = min(100.0, b.energy + gain)
            b.holding = None
            return 0.1 + 1.5 * hunger, f"I eat {KINDS[h['kind']][1]}. It tastes sweet.", info
        e = self._target() or (h if h else None)
        if not e:
            return -0.02, "I reach out but touch nothing.", info
        k = e["kind"]
        fun_gain, base, text = 0.0, 0.3, ""
        if k in FOOD:
            del self.entities[e["id"]]
            hunger = (100 - b.energy) / 100
            b.energy = min(100.0, b.energy + FOOD[k])
            return 0.1 + 1.5 * hunger, f"I eat {KINDS[k][1]}. It tastes sweet.", info
        if k == "ball":
            dx, dy = DIRS[b.facing]
            x, y = e["x"], e["y"]
            if e is h:
                b.holding = None
                x, y = b.x, b.y
                self.entities[e["id"]] = e
            for _ in range(3):
                if self.walkable(x + dx, y + dy):
                    x, y = x + dx, y + dy
            e["x"], e["y"] = x, y
            fun_gain, text = 15, "I kick the ball and it bounces away. That is fun!"
        elif k == "book":
            info["read"] = e
            fun_gain, base, text = 6, 0.35, "I open the book and read."
        elif k == "lamp":
            e["on"] = not e.get("on")
            fun_gain, text = 3, f"I turn the lamp {'on. Light fills the room' if e['on'] else 'off'}."
        elif k == "musicbox":
            tune = " ".join(self.rng.choice(NOTES) for _ in range(5))
            fun_gain, text = 12, f"I play the music box: {tune}. It sounds lovely."
            info["music"] = tune
        elif k == "mirror":
            fun_gain, text = 5, self.describe_self()
        elif k == "sign":
            fun_gain, text = 3, f"The sign says: {e.get('text', '')}"
            info["learn"] = e.get("text", "")
        elif k == "cat":
            fun_gain, base, text = 14, 0.4, "I pet the cat. It purrs softly. I like the cat."
        elif k == "bed":
            text = "The bed is soft. I could sleep here."
        elif k == "flower":
            fun_gain, text = 4, "I smell the flower. It smells nice."
        elif k == "block":
            fun_gain, text = 4, "I stack the wooden block. It is heavy and square."
        elif k == "seed":
            text = "A seed. If I put it on the grass it might grow."
        b.fun = min(100.0, b.fun + fun_gain)
        return self._novel("use:" + k, base) + fun_gain / 100, text, info

    def _world_tick(self):
        r = self.rng
        for e in list(self.entities.values()):
            if e["kind"] == "cat" and r.random() < 0.25:
                dx, dy = r.choice(list(DIRS.values()))
                if self.walkable(e["x"] + dx, e["y"] + dy) and (e["x"] + dx, e["y"] + dy) != (self.body.x, self.body.y):
                    e["x"] += dx
                    e["y"] += dy
            if e["kind"] == "flower" and "grow" in e and self.tick_n - e["grow"] > 400:
                e.pop("grow")
                self.terrain[e["y"]][e["x"]] = FLOWERS
        counts = {}
        for e in self.entities.values():
            counts[e["kind"]] = counts.get(e["kind"], 0) + 1
        if counts.get("apple", 0) < 5 and r.random() < 0.01:
            trees = [(x, y) for y in range(H) for x in range(W) if self.terrain[y][x] == TREE]
            if trees:
                tx, ty = r.choice(trees)
                for dx, dy in DIRS.values():
                    if self.walkable(tx + dx, ty + dy) and not self.at(tx + dx, ty + dy):
                        self.add("apple", tx + dx, ty + dy)
                        self.log.append("An apple falls from a tree.")
                        break
        if counts.get("berry", 0) < 3 and r.random() < 0.006:
            self.add_random("berry")
        if counts.get("ball", 0) < 1:
            self.add_random("ball")

    def say(self, text: str):
        self.body.said = text
        self.body.said_ttl = 14

    # -- serialisation ------------------------------------------------------------
    def to_dict(self, full: bool = True) -> dict:
        b = self.body
        d = {
            "w": W, "h": H, "tick": self.tick_n, "time": self.time_of_day, "light": self.light,
            "entities": [{k: v for k, v in e.items() if k != "text"} | ({"title": e["text"][:40]} if e.get("text") else {})
                         for e in self.entities.values()],
            "body": {"x": b.x, "y": b.y, "facing": b.facing, "energy": round(b.energy, 1),
                     "fun": round(b.fun, 1), "holding": b.holding["kind"] if b.holding else None,
                     "sleeping": b.sleeping, "said": b.said if b.said_ttl else "", "steps": b.steps,
                     "visited": len(b.visits), "faints": b.faints, "reward": round(b.total_reward, 2)},
            "log": self.log[-12:],
        }
        if full:
            d["terrain"] = self.terrain
        return d

    def state(self) -> dict:
        b = self.body
        return {"tick": self.tick_n, "next_id": self.next_id, "terrain": self.terrain,
                "entities": list(self.entities.values()),
                "body": {k: getattr(b, k) for k in Body.__dataclass_fields__}}

    def load_state(self, s: dict):
        self.tick_n, self.next_id, self.terrain = s["tick"], s["next_id"], s["terrain"]
        self.entities = {e["id"]: e for e in s["entities"]}
        for k, v in s["body"].items():
            setattr(self.body, k, v)
