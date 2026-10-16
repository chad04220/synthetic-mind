"""The studio: instruments on which Zen makes art from scratch, one mark at a time.

Zen's brain chooses every mark, one word at a time, from a small vocabulary per medium (the same
constrained decoding that moves its body). These classes are the instruments only: a canvas that
paints a cell where the brush is, a piano that plays the note it is told, a lump of clay that grows
where clay is added. Nothing here composes, suggests or corrects.

The rules are mirrored exactly in web/art.js, which replays any piece from its `ops` string.

Each finished piece is scored with intrinsic measures only (how varied, balanced, structured and new
it is, never what it "should" show). The score is the reward for the session (relative to Zen's
own running average per medium), so Zen's taste can grow from its own work, and from yours: a piece
you love sends an extra reward back to every mark that made it.
"""
from __future__ import annotations

import math
from collections import Counter

CODES = "0123456789abcdefghijklmnopqrstuvwxyz"

PAINT = ["up", "down", "left", "right", "jump", "press", "lift", "dot", "big", "small",
         "black", "white", "red", "orange", "yellow", "green", "blue", "purple", "pink", "brown", "grey", "gold",
         "done"]
MUSIC = ["C", "D", "E", "F", "G", "A", "B", "high", "low", "long", "short", "rest", "fast", "slow", "done"]
SCULPT = ["up", "down", "left", "right", "in", "out", "add", "cut", "smooth", "done"]
VOCABS = {"paint": PAINT, "compose": MUSIC, "sculpt": SCULPT}
PAINT_CODES = {w: CODES[i] for i, w in enumerate(PAINT)}
MUSIC_CODES = {w: CODES[i] for i, w in enumerate(MUSIC)}
SCULPT_CODES = {w: CODES[i] for i, w in enumerate(SCULPT)}
LIMITS = {"paint": 900, "compose": 200, "sculpt": 600}
MEDIUM = {"paint": "painting", "compose": "music", "sculpt": "sculpture", "write": "poem"}

PALETTE = ["#1d1d1f", "#f7f4ec", "#d64545", "#ef8a3a", "#f2c94c", "#4f9a4f", "#3f6fb5", "#8e5bb5", "#ee8fb2",
           "#8a5a2b", "#8d8d8d", "#d9a93b"]
COLOR_NAMES = PAINT[10:22]
W, H = 64, 48
NOTES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
DIRS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
N3 = 12


def vocab_ids(tok, medium: str) -> list[int]:
    """Token of each word of a medium's vocabulary (a capital letter each on a byte tokenizer)."""
    words = VOCABS[medium]
    ids = [tok.encode(" " + w) for w in words]
    if all(len(x) == 1 for x in ids) and len({x[0] for x in ids}) == len(words):
        return [x[0] for x in ids]
    return [tok.encode(chr(65 + i))[0] for i in range(len(words))]


# ====================================================================== painting
class Canvas:
    medium = "paint"

    def __init__(self):
        self.px = [-1] * (W * H)
        self.x, self.y = W // 2, H // 2
        self.pen = False
        self.color = 0
        self.size = 1
        self.last = "right"
        self.ops: list[str] = []
        self.done = False

    def _paint(self):
        r = 1 if self.size == 3 else 0
        for yy in range(self.y - r, self.y + r + 1):
            for xx in range(self.x - r, self.x + r + 1):
                if 0 <= xx < W and 0 <= yy < H:
                    self.px[yy * W + xx] = self.color

    def _move(self, d: str, n: int):
        dx, dy = DIRS[d]
        for _ in range(n):
            nx, ny = min(W - 1, max(0, self.x + dx)), min(H - 1, max(0, self.y + dy))
            if (nx, ny) == (self.x, self.y):
                break
            self.x, self.y = nx, ny
            if self.pen:
                self._paint()

    def apply(self, word: str):
        self.ops.append(PAINT_CODES[word])
        if word in DIRS:
            self.last = word
            self._move(word, 1)
        elif word == "jump":
            self._move(self.last, 6)
        elif word == "press":
            self.pen = True
            self._paint()
        elif word == "lift":
            self.pen = False
        elif word == "dot":
            self._paint()
        elif word == "big":
            self.size = 3
        elif word == "small":
            self.size = 1
        elif word in COLOR_NAMES:
            self.color = COLOR_NAMES.index(word)
        elif word == "done":
            self.done = True

    def pixels(self) -> str:
        return "".join("." if c < 0 else CODES[c] for c in self.px)

    def describe(self) -> str:
        """What Zen sees on its paper, in words."""
        used = Counter(c for c in self.px if c >= 0)
        n = sum(used.values())
        if not n:
            return "The paper is still blank."
        cover = n / len(self.px)
        cols = [COLOR_NAMES[c] for c, _ in used.most_common(3)]
        xs = [i % W for i, c in enumerate(self.px) if c >= 0]
        ys = [i // W for i, c in enumerate(self.px) if c >= 0]
        cx, cy = sum(xs) / n, sum(ys) / n
        where = ("at the top" if cy < H * .35 else "at the bottom" if cy > H * .65 else "in the middle") + \
                (" on the left" if cx < W * .35 else " on the right" if cx > W * .65 else "")
        amount = "a little" if cover < .05 else "some" if cover < .2 else "a lot of" if cover < .6 else "paint all over"
        cs = cols[0] if len(cols) == 1 else ", ".join(cols[:-1]) + " and " + cols[-1]
        pen = "The brush is on the paper" if self.pen else "The brush is up"
        return (f"There is {amount} {cs} {where}." if amount != "paint all over" else f"There is {cs} paint all over.") + \
            f" {pen}, {COLOR_NAMES[self.color]}."

    def view(self, full: bool) -> dict:
        d = {"medium": "painting", "w": W, "h": H, "cursor": [self.x, self.y], "color": self.color,
             "size": self.size, "pen": self.pen, "steps": len(self.ops)}
        if full:
            d["pixels"], d["palette"] = self.pixels(), PALETTE
        return d

    def data(self) -> dict:
        return {"v": 3, "w": W, "h": H, "palette": PALETTE, "pixels": self.pixels(), "ops": "".join(self.ops)}

    def score(self, earlier: list[str] | None = None) -> dict:
        return score_painting(self.px, earlier or [])


def score_painting(px: list[int], earlier: list[str]) -> dict:
    n = sum(1 for c in px if c >= 0)
    cover = n / len(px)
    s_cover = math.exp(-((cover - 0.35) / 0.25) ** 2) if n else 0.0
    used = Counter(c for c in px if c >= 0)
    k = len(used)
    s_colors = {0: 0.0, 1: 0.35, 2: 0.75, 3: 1.0, 4: 1.0, 5: 0.85, 6: 0.65}.get(k, 0.45)   # a chosen palette
    # contrast: brightness spread of the used colours (and against paper)
    lum = [_lum(PALETTE[c]) for c in used] + ([_lum("#f7f4ec")] if cover < 0.98 else [])
    s_contrast = min(1.0, (max(lum) - min(lum)) / 0.6) if len(lum) > 1 else 0.0
    # structure: edges between different neighbours, neither noise nor nothing
    edges = sum(1 for y in range(H) for x in range(W - 1) if px[y * W + x] != px[y * W + x + 1]) + \
        sum(1 for y in range(H - 1) for x in range(W) if px[y * W + x] != px[(y + 1) * W + x])
    e = edges / (2 * W * H)
    s_structure = math.exp(-((e - 0.08) / 0.07) ** 2) if n else 0.0
    # balance: the painted mass not crammed in one corner, and some symmetry
    if n:
        cx = sum(i % W for i, c in enumerate(px) if c >= 0) / n / W
        cy = sum(i // W for i, c in enumerate(px) if c >= 0) / n / H
        s_balance = 1 - min(1.0, 2.2 * math.hypot(cx - 0.5, cy - 0.5))
        # painted cells echoed in the same colour across the middle (left-right or top-bottom)
        lr = sum(1 for i, c in enumerate(px) if c >= 0 and px[(i // W) * W + W - 1 - i % W] == c) / n
        tb = sum(1 for i, c in enumerate(px) if c >= 0 and px[(H - 1 - i // W) * W + i % W] == c) / n
        s_symmetry = max(lr, tb)
    else:
        s_balance = s_symmetry = 0.0
    # novelty: unlike its earlier paintings
    me = "".join("." if c < 0 else CODES[c] for c in px)
    if earlier and n:
        sims = [sum(a == b for a, b in zip(me, o)) / len(me) for o in earlier[-12:] if len(o) == len(me)]
        s_new = 1 - max(sims) if sims else 1.0
        s_new = min(1.0, s_new / 0.5)
    else:
        s_new = 1.0 if n else 0.0
    # solidity: shapes and thick strokes rather than thin noise (painted cells among their own colour)
    same = 0
    for i, c in enumerate(px):
        if c >= 0:
            x, y = i % W, i // W
            same += sum(1 for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                        if 0 <= x + dx < W and 0 <= y + dy < H and px[(y + dy) * W + x + dx] == c) >= 3
    s_solid = min(1.0, (same / n) / 0.6) if n else 0.0
    # colour places: each colour kept together rather than sprinkled everywhere
    if n:
        spread = []
        for c, cnt in used.items():
            if cnt < 4:
                continue
            xs = [i % W for i, v in enumerate(px) if v == c]
            ys = [i // W for i, v in enumerate(px) if v == c]
            mx, my = sum(xs) / cnt, sum(ys) / cnt
            sd = math.sqrt(sum((x - mx) ** 2 + (y - my) ** 2 for x, y in zip(xs, ys)) / cnt)
            spread.append(sd / math.hypot(W, H) * (cnt / n))
        s_places = max(0.0, 1 - 3.2 * sum(spread)) if spread else 0.5
    else:
        s_places = 0.0
    parts = {"coverage": s_cover, "colour": s_colors, "contrast": s_contrast, "structure": s_structure,
             "solidity": s_solid, "places": s_places, "balance": s_balance, "symmetry": s_symmetry, "new": s_new}
    w = {"coverage": 1.0, "colour": 0.8, "contrast": 0.6, "structure": 0.8, "solidity": 1.4, "places": 1.2,
         "balance": 0.8, "symmetry": 0.5, "new": 0.8}
    total = sum(parts[k] * w[k] for k in parts) / sum(w.values())
    return {k: round(v, 3) for k, v in parts.items()} | {"total": round(total, 3)}


def _lum(hexc: str) -> float:
    r, g, b = (int(hexc[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


# ====================================================================== music
class Piano:
    medium = "compose"

    def __init__(self):
        self.octave = 4
        self.length = 1.0
        self.tempo = 100
        self.notes: list[list] = []
        self.tempos: list[list] = []
        self.ops: list[str] = []
        self.done = False

    def apply(self, word: str):
        self.ops.append(MUSIC_CODES[word])
        if word in NOTES:
            self.notes.append([12 * (self.octave + 1) + NOTES[word], self.length])
        elif word == "high":
            self.octave = min(6, self.octave + 1)
        elif word == "low":
            self.octave = max(3, self.octave - 1)
        elif word == "long":
            self.length = 2.0
        elif word == "short":
            self.length = 0.5
        elif word == "rest":
            self.notes.append([-1, self.length])
        elif word in ("fast", "slow"):
            self.tempo = max(60, min(180, self.tempo + (12 if word == "fast" else -12)))
            self.tempos.append([len(self.notes), self.tempo])
        elif word == "done":
            self.done = True

    def last(self) -> int | None:
        return self.notes[-1][0] if self.notes else None

    def describe(self) -> str:
        played = [n for n, _ in self.notes if n >= 0]
        if not played:
            return "I have not played a note yet."
        names = ["C", "C sharp", "D", "D sharp", "E", "F", "F sharp", "G", "G sharp", "A", "A sharp", "B"]
        last = played[-4:]
        tail = ", ".join(names[n % 12] for n in last)
        rise = "going up" if len(last) > 1 and last[-1] > last[0] else "going down" if len(last) > 1 and last[-1] < last[0] else "staying"
        return f"I have played {len(played)} notes. The last ones were {tail}, {rise}."

    def view(self, full: bool) -> dict:
        d = {"medium": "music", "steps": len(self.ops), "octave": self.octave, "length": self.length, "tempo": self.tempo}
        if full:
            d["notes"] = self.notes[-200:]
        return d

    def data(self) -> dict:
        return {"v": 3, "tempo": 100, "notes": self.notes, "tempo_changes": self.tempos, "ops": "".join(self.ops)}

    def score(self, earlier=None) -> dict:
        return score_music(self.notes)


def score_music(notes: list[list]) -> dict:
    pitches = [n for n, _ in notes if n >= 0]
    if len(pitches) < 2:
        return {"length": 0.0, "steps": 0.0, "motifs": 0.0, "home": 0.0, "range": 0.0, "rhythm": 0.0, "total": 0.0}
    s_len = min(1.0, len(pitches) / 24) * (1.0 if len(pitches) < 160 else 0.8)
    iv = [abs(b - a) for a, b in zip(pitches, pitches[1:])]
    small = sum(1 for d in iv if 0 < d <= 4) / len(iv)
    leaps = sum(1 for d in iv if 5 <= d <= 12) / len(iv)
    same = sum(1 for d in iv if d == 0) / len(iv)
    s_steps = max(0.0, min(1.0, small * 1.2 + min(leaps, 0.25) - max(0.0, same - 0.3)))
    # motifs: three-interval patterns that come back
    signed = [b - a for a, b in zip(pitches, pitches[1:])]
    grams = Counter(tuple(signed[i:i + 3]) for i in range(len(signed) - 2))
    rep = sum(c for c in grams.values() if c > 1) / max(1, sum(grams.values()))
    s_motifs = math.exp(-((rep - 0.35) / 0.25) ** 2)
    # a home note: the first and last notes agree, and one pitch class leads
    pcs = Counter(p % 12 for p in pitches)
    s_home = 0.5 * (pitches[0] % 12 == pitches[-1] % 12) + 0.5 * min(1.0, pcs.most_common(1)[0][1] / len(pitches) * 4)
    rng = max(pitches) - min(pitches)
    s_range = math.exp(-((rng - 12) / 9) ** 2)
    lens = Counter(l for _, l in notes)
    s_rhythm = min(1.0, (len(lens) - 1) / 2) if len(lens) > 1 else 0.2
    parts = {"length": s_len, "steps": s_steps, "motifs": s_motifs, "home": s_home, "range": s_range, "rhythm": s_rhythm}
    w = {"length": 0.8, "steps": 1.4, "motifs": 1.2, "home": 0.6, "range": 0.8, "rhythm": 0.6}
    total = sum(parts[k] * w[k] for k in parts) / sum(w.values())
    return {k: round(v, 3) for k, v in parts.items()} | {"total": round(total, 3)}


# ====================================================================== sculpture
class Clay:
    medium = "sculpt"

    def __init__(self, material: str = "clay"):
        self.v = bytearray(N3 * N3 * N3)
        self.x, self.y, self.z = N3 // 2, 0, N3 // 2
        self.material = material
        self.ops: list[str] = []
        self.done = False

    @staticmethod
    def idx(x, y, z) -> int:
        return x + N3 * (z + N3 * y)

    def apply(self, word: str):
        self.ops.append(SCULPT_CODES[word])
        mv = {"up": (0, 1, 0), "down": (0, -1, 0), "left": (-1, 0, 0), "right": (1, 0, 0), "in": (0, 0, -1), "out": (0, 0, 1)}
        if word in mv:
            dx, dy, dz = mv[word]
            self.x = min(N3 - 1, max(0, self.x + dx))
            self.y = min(N3 - 1, max(0, self.y + dy))
            self.z = min(N3 - 1, max(0, self.z + dz))
        elif word == "add":
            self.v[self.idx(self.x, self.y, self.z)] = 1
        elif word == "cut":
            self.v[self.idx(self.x, self.y, self.z)] = 0
        elif word == "smooth":
            fill = []
            for y in range(self.y - 1, self.y + 2):
                for z in range(self.z - 1, self.z + 2):
                    for x in range(self.x - 1, self.x + 2):
                        if 0 <= x < N3 and 0 <= y < N3 and 0 <= z < N3 and not self.v[self.idx(x, y, z)]:
                            nb = sum(1 for dx, dy, dz in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))
                                     if 0 <= x + dx < N3 and 0 <= y + dy < N3 and 0 <= z + dz < N3
                                     and self.v[self.idx(x + dx, y + dy, z + dz)])
                            if nb >= 4:
                                fill.append(self.idx(x, y, z))
            for i in fill:
                self.v[i] = 1
        elif word == "done":
            self.done = True

    def voxels(self) -> str:
        return "".join("1" if b else "0" for b in self.v)

    def describe(self) -> str:
        n = sum(self.v)
        if not n:
            return f"The {self.material} is still a lump in my hands. Nothing is built yet."
        top = max(y for y in range(N3) for z in range(N3) for x in range(N3) if self.v[self.idx(x, y, z)])
        size = "small" if n < 20 else "middle-sized" if n < 120 else "big"
        return f"The {self.material} shape is {size} and {top + 1} high. My hands are at height {self.y + 1}."

    def view(self, full: bool) -> dict:
        d = {"medium": "sculpture", "n": N3, "cursor": [self.x, self.y, self.z], "steps": len(self.ops),
             "material": self.material}
        if full:
            d["voxels"] = self.voxels()
        return d

    def data(self) -> dict:
        return {"v": 3, "n": N3, "voxels": self.voxels(), "material": self.material, "ops": "".join(self.ops)}

    def score(self, earlier=None) -> dict:
        return score_sculpture(self.v)


def score_sculpture(v) -> dict:
    cells = [(x, y, z) for y in range(N3) for z in range(N3) for x in range(N3) if v[x + N3 * (z + N3 * y)]]
    n = len(cells)
    if not n:
        return {"mass": 0.0, "connected": 0.0, "standing": 0.0, "shape": 0.0, "symmetry": 0.0, "total": 0.0}
    s_mass = math.exp(-((math.log(n) - math.log(90)) / 1.1) ** 2)
    # the biggest connected piece
    left, best = set(cells), 0
    while left:
        stack, comp = [left.pop()], 1
        while stack:
            x, y, z = stack.pop()
            for d in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)):
                q = (x + d[0], y + d[1], z + d[2])
                if q in left:
                    left.remove(q)
                    stack.append(q)
                    comp += 1
        best = max(best, comp)
    s_conn = best / n
    s_stand = 1.0 if any(y == 0 for _, y, _ in cells) else 0.0
    xs, ys, zs = [c[0] for c in cells], [c[1] for c in cells], [c[2] for c in cells]
    dims = sorted([max(xs) - min(xs) + 1, max(ys) - min(ys) + 1, max(zs) - min(zs) + 1])
    layers = Counter(ys)
    s_shape = min(1.0, (dims[2] / max(1, dims[0])) / 3) * 0.5 + min(1.0, len(set(layers.values())) / 4) * 0.5
    sset = set(cells)
    mx = min(xs) + max(xs)
    s_sym = sum(1 for (x, y, z) in cells if (mx - x, y, z) in sset) / n
    parts = {"mass": s_mass, "connected": s_conn, "standing": s_stand, "shape": s_shape, "symmetry": s_sym}
    w = {"mass": 1.0, "connected": 1.2, "standing": 0.6, "shape": 1.0, "symmetry": 0.8}
    total = sum(parts[k] * w[k] for k in parts) / sum(w.values())
    return {k: round(v, 3) for k, v in parts.items()} | {"total": round(total, 3)}


def instrument(kind: str, material: str = "clay"):
    return {"paint": Canvas, "compose": Piano}[kind]() if kind != "sculpt" else Clay(material)
