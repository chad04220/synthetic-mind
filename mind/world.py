"""A small garden world the mind lives in through a body.

The body senses its surroundings as first-person text ("I see an apple 2 steps north"),
the same network that learns language picks an action, and what happens is narrated
back in words. Hunger, boredom and novelty give the body intrinsic rewards, so it
learns to look after itself and explore while its language is grounded in experience.
"""
from __future__ import annotations

import math
import random
import time
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
        self.terrain_v = random.randrange(1 << 30)   # changes whenever the terrain does
        self.body = Body()
        self.visitor: dict | None = None   # you, when you join the world ("my friend" to the mind)
        self.heard = ""                    # what you last said near the mind
        self.heard_ttl = 0
        self.bonus = 0.0                   # social reward waiting for the mind's next step
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

    def free_for_body(self, x, y) -> bool:
        v = self.visitor
        return self.walkable(x, y) and not (v and (v["x"], v["y"]) == (x, y))

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
        v = self.visitor
        if v:
            d = abs(v["x"] - b.x) + abs(v["y"] - b.y)
            where = "right next to me" if d == 1 else self._rel(v["x"] - b.x, v["y"] - b.y)
            s.append(f"My friend is {where}" + (f" and holds {KINDS[v['holding']['kind']][1]}." if v["holding"] else "."))
        if self.heard_ttl > 0:
            s.append(f'My friend says: "{self.heard}"')
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
            v = self.visitor
            if v and abs(v["x"] - b.x) + abs(v["y"] - b.y) > 1 and (target is None or self.rng.random() < 0.5):
                target = {"kind": "friend", "x": v["x"], "y": v["y"]}
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
                    if self.free_for_body(b.x + ddx, b.y + ddy):
                        r2, n2 = self._move(d)
                        reward += r2
                        narr += f"I go toward {self._name(target)}. " + n2
                        moved = True
                        break
                if not moved:
                    narr += f"I want to reach {self._name(target)} but something is in the way."
            else:
                narr += "I look for something interesting, but I see nothing new."
        elif action == "use":
            reward, narr2, info = self._use()
            narr += narr2
        elif action == "take":
            e = self._target(portable=True)
            v = self.visitor
            if not b.holding and v and v["holding"] and self._facing_friend():
                b.holding, v["holding"] = v["holding"], None
                narr += f"I take {KINDS[b.holding['kind']][1]} from my friend. Thank you!"
                reward += self._novel("take:gift", 0.5)
            elif b.holding:
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

        # company
        v = self.visitor
        if v and abs(v["x"] - b.x) + abs(v["y"] - b.y) <= 2:
            reward += 0.015
        reward += self.bonus
        self.bonus = 0.0
        if self.heard_ttl > 0:
            self.heard_ttl -= 1

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
        if self.visitor and (self.visitor["x"], self.visitor["y"]) == (nx, ny):
            return 0.0, f"My friend is {action} of me."
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
        if self._facing_friend() and not self.at(*self._front()):
            b.fun = min(100.0, b.fun + 12)
            return self._novel("use:friend", 0.45) + 0.12, "I hug my friend. I feel happy.", info
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

    def _front(self) -> tuple[int, int]:
        dx, dy = DIRS[self.body.facing]
        return self.body.x + dx, self.body.y + dy

    def _facing_friend(self) -> bool:
        v = self.visitor
        if not v:
            return False
        if (v["x"], v["y"]) == self._front():
            return True
        # Adjacent but not faced: turn toward the friend.
        b = self.body
        for d, (dx, dy) in DIRS.items():
            if (b.x + dx, b.y + dy) == (v["x"], v["y"]):
                b.facing = d
                return True
        return False

    @staticmethod
    def _name(target: dict) -> str:
        return "my friend" if target["kind"] == "friend" else KINDS[target["kind"]][1]

    # -- you, the visitor ---------------------------------------------------------
    def join(self) -> dict:
        """Put your avatar in the world on a free tile near the mind."""
        if self.visitor:
            return self.visitor
        b = self.body
        best = None
        for r in range(1, max(W, H)):
            for y in range(b.y - r, b.y + r + 1):
                for x in range(b.x - r, b.x + r + 1):
                    if abs(x - b.x) + abs(y - b.y) == r and self.walkable(x, y) and (x, y) != (b.x, b.y):
                        best = (x, y)
                        break
                if best:
                    break
            if best:
                break
        x, y = best or (b.x, b.y)
        self.visitor = {"x": x, "y": y, "facing": "south", "holding": None, "said": "", "said_until": 0.0}
        self.log.append("My friend arrives!")
        self.bonus += self._novel("friend:arrive", 0.5)
        return self.visitor

    def leave(self):
        v = self.visitor
        if v and v["holding"]:
            e = v["holding"]
            e["x"], e["y"] = v["x"], v["y"]
            self.entities[e["id"]] = e
        if v:
            self.log.append("My friend waves goodbye and leaves.")
        self.visitor = None
        self.heard_ttl = 0

    def visitor_say(self, text: str):
        if self.visitor:
            self.visitor["said"] = text
            self.visitor["said_until"] = time.time() + 7
            b, v = self.body, self.visitor
            if abs(v["x"] - b.x) + abs(v["y"] - b.y) <= 6:
                self.heard, self.heard_ttl = text[:160], 20

    def visitor_act(self, action: str, kind: str | None = None, text: str = "") -> str:
        """Move or act as your avatar. Returns a short description of what happened."""
        v = self.visitor
        if not v:
            return "Join the world first."
        b = self.body
        if action in DIRS:
            dx, dy = DIRS[action]
            v["facing"] = action
            nx, ny = v["x"] + dx, v["y"] + dy
            if self.walkable(nx, ny) and (nx, ny) != (b.x, b.y):
                v["x"], v["y"] = nx, ny
            return ""
        if action == "hold":
            if kind not in KINDS or not KINDS[kind][0]:
                return f"You can only hold small things (not a {kind})."
            if v["holding"]:
                self.visitor_act("drop")
            v["holding"] = {"id": self.next_id, "kind": kind, "x": v["x"], "y": v["y"]}
            if kind == "book":
                v["holding"]["text"] = text or ""
            self.next_id += 1
            return f"You are holding {KINDS[kind][1]}."
        if action == "take":
            if v["holding"]:
                return self.visitor_act("drop")
            dx, dy = DIRS[v["facing"]]
            for x, y in ((v["x"], v["y"]), (v["x"] + dx, v["y"] + dy)):
                for e in self.at(x, y):
                    if KINDS[e["kind"]][0]:
                        del self.entities[e["id"]]
                        v["holding"] = e
                        return f"You pick up {KINDS[e['kind']][1]}."
            return "Nothing to pick up here."
        if action == "drop":
            if not v["holding"]:
                return "Your hands are empty."
            e, v["holding"] = v["holding"], None
            e["x"], e["y"] = v["x"], v["y"]
            self.entities[e["id"]] = e
            return f"You put down {KINDS[e['kind']][1]}."
        if action == "give":
            if not v["holding"]:
                return "Pick something up (or choose an item and press Hold) first."
            if abs(v["x"] - b.x) + abs(v["y"] - b.y) > 1:
                return "Walk right next to the mind to give it something."
            e, v["holding"] = v["holding"], None
            what = KINDS[e["kind"]][1]
            if b.holding:
                e["x"], e["y"] = b.x, b.y
                self.entities[e["id"]] = e
                self.log.append(f"My friend puts {what} down beside me.")
            else:
                b.holding = e
                self.log.append(f"My friend gives me {what}!")
            b.sleeping = False
            self.bonus += self._novel("gift:" + e["kind"], 0.6)
            return f"You give it {what}."
        if action == "pet":
            if abs(v["x"] - b.x) + abs(v["y"] - b.y) > 1:
                return "Walk right next to the mind first."
            b.fun = min(100.0, b.fun + 10)
            self.log.append("My friend gives me a hug. I feel happy.")
            self.bonus += self._novel("hugged", 0.4)
            return "You hug the mind."
        return f"Unknown action {action}."

    def _world_tick(self):
        r = self.rng
        for e in list(self.entities.values()):
            if e["kind"] == "cat" and r.random() < 0.25:
                dx, dy = r.choice(list(DIRS.values()))
                if self.free_for_body(e["x"] + dx, e["y"] + dy) and (e["x"] + dx, e["y"] + dy) != (self.body.x, self.body.y):
                    e["x"] += dx
                    e["y"] += dy
            if e["kind"] == "flower" and "grow" in e and self.tick_n - e["grow"] > 400:
                e.pop("grow")
                self.terrain[e["y"]][e["x"]] = FLOWERS
                self.terrain_v += 1
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
            "visitor": None if not self.visitor else {
                "x": self.visitor["x"], "y": self.visitor["y"], "facing": self.visitor["facing"],
                "holding": self.visitor["holding"]["kind"] if self.visitor["holding"] else None,
                "said": self.visitor["said"] if time.time() < self.visitor["said_until"] else ""},
        }
        d["terrain_v"] = self.terrain_v
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
        self.terrain_v += 1
        self.entities = {e["id"]: e for e in s["entities"]}
        for k, v in s["body"].items():
            setattr(self.body, k, v)
