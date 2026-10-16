"""A* over voxel positions (DESIGN-v5 §3.2 go_to).

A node is a feet cell (x, y, z) where a 0.6×1.8 body fits: feet and head cells passable and
something to stand on (a solid block below, water, or a ladder/vine). Moves: walk (4 + diagonal),
jump up one block, drop down (≤ ``max_drop`` onto ground, any height into water), swim/climb
up and down, open doors, and — with ``allow_dig`` — dig through blocks (walk, stairs up/down, or
straight down), never next to liquids.

The local area is copied out of the world once per search and classified with numpy into a byte
array of flags, so the search itself only does byte lookups.

    p = find_path(world, start, goal=(x, y, z), near=1.5)            # → Path | None
    p = find_path(world, start, reach=(bx, by, bz))                   # stand where a block is in reach
    p.steps: [Step(x, y, z, move, dig)]  (dig = cells to clear before stepping in)
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field

import numpy as np

from . import blocks as B

PASS, FLOOR, WATER, CLIMB, DIG, DANGER, DOOR, NEARLAVA = 1, 2, 4, 8, 16, 32, 64, 128
REACH = 4.5
EYE = 1.62

_np_pass = np.array([(not b["solid"]) and not b["liquid"] or b["base"] == "water" for b in B.BLOCKS])
_np_pass &= ~np.array([b["base"] in ("lava", "fire", "cactus", "campfire") for b in B.BLOCKS])
_np_floor = np.array([b["solid"] for b in B.BLOCKS]) & ~np.array([b["base"] in ("cactus", "campfire")
                                                                   for b in B.BLOCKS])
_np_water = np.array([b["base"] == "water" for b in B.BLOCKS])
_np_climb = np.array([b["climbable"] and not b["solid"] for b in B.BLOCKS])
_np_danger = np.array([b["base"] in ("lava", "fire", "cactus", "campfire") for b in B.BLOCKS])
_np_lava = np.array([b["base"] == "lava" for b in B.BLOCKS])
_np_liquid = np.array([b["liquid"] for b in B.BLOCKS])
_np_door = np.array([b["base"] == "door" for b in B.BLOCKS])
# never tunnel through built things (houses, stations) — only natural terrain, ores and plants
_np_diggable = np.array([b["hardness"] >= 0 and not b["liquid"] and b["category"] in ("terrain", "ore", "life")
                         and b["base"] not in ("bedrock", "obsidian") for b in B.BLOCKS])


@dataclass
class Step:
    x: int
    y: int
    z: int
    move: str = "walk"
    dig: list = field(default_factory=list)


@dataclass
class Path:
    steps: list
    partial: bool = False
    nodes: int = 0
    cost: float = 0.0


def _dilate6(m):
    o = m.copy()
    o[1:] |= m[:-1]
    o[:-1] |= m[1:]
    o[:, 1:] |= m[:, :-1]
    o[:, :-1] |= m[:, 1:]
    o[:, :, 1:] |= m[:, :, :-1]
    o[:, :, :-1] |= m[:, :, 1:]
    return o


def find_path(world, start, goal=None, *, near=0.0, reach=None, reach_dist=REACH - 0.25, goal_fn=None,
              max_nodes=6000, allow_dig=False, dig_cost=None, max_drop=3, margin=10, partial=True,
              avoid=None) -> Path | None:
    """Search from feet cell ``start`` to ``goal`` (within ``near``) or to a spot where block ``reach``
    is within ``reach_dist`` of the eye. ``dig_cost(block_id) -> seconds | None`` enables digging."""
    sx, sy, sz = (int(math.floor(v)) for v in start)
    tgt = goal if goal is not None else reach
    if tgt is None:
        raise ValueError("goal or reach required")
    tx, ty, tz = (int(math.floor(v)) for v in tgt)
    X0 = min(sx, tx) - margin
    X1 = max(sx, tx) + margin + 1
    Z0 = min(sz, tz) - margin
    Z1 = max(sz, tz) + margin + 1
    Y0 = max(0, min(sy, ty) - margin)
    Y1 = min(256, max(sy, ty) + margin + 1)
    blocks = world.region_blocks(X0, Y0, Z0, X1, Y1, Z1)
    SX, SZ = X1 - X0, Z1 - Z0
    UP = SX * SZ
    flags = np.zeros(blocks.shape, dtype=np.uint8)
    flags |= _np_pass[blocks].astype(np.uint8) * PASS
    flags |= _np_floor[blocks].astype(np.uint8) * FLOOR
    flags |= _np_water[blocks].astype(np.uint8) * WATER
    flags |= _np_climb[blocks].astype(np.uint8) * CLIMB
    flags |= _np_danger[blocks].astype(np.uint8) * DANGER
    door = _np_door[blocks]
    flags |= door.astype(np.uint8) * (DOOR | PASS)
    lava_near = _dilate6(_np_lava[blocks])
    flags |= lava_near.astype(np.uint8) * NEARLAVA
    dig_tab = None
    if allow_dig:
        dig_tab = {}
        liq_near = _dilate6(_np_liquid[blocks])
        dg = _np_diggable[blocks] & ~liq_near & ~_np_pass[blocks] & ~door
        if dig_cost is not None:
            for bid in np.unique(blocks[dg]).tolist():
                c = dig_cost(bid)
                if c is None:
                    dg &= blocks != bid
                else:
                    dig_tab[bid] = 1.0 + c * 2.0
        flags |= dg.astype(np.uint8) * DIG
    # standable (feet+head passable, something to stand on) and two-tall passable, precomputed
    pas = (flags & PASS) > 0
    tall = np.zeros_like(pas)
    tall[:-1] = pas[:-1] & pas[1:]
    support = np.zeros_like(pas)
    support[1:] = (flags[:-1] & FLOOR) > 0
    support |= (flags & (WATER | CLIMB)) > 0
    stand_a = tall & support
    F = flags.tobytes()
    S = stand_a.tobytes()
    T = tall.tobytes()
    BL = blocks.ravel()
    n_cells = len(F)

    def idx(x, y, z):
        return (y - Y0) * UP + (z - Z0) * SX + (x - X0)

    def inb(x, y, z):
        return X0 < x < X1 - 1 and Y0 < y < Y1 - 2 and Z0 < z < Z1 - 1

    if not inb(sx, sy, sz):
        return None
    start_i = idx(sx, sy, sz)
    if F[start_i] & PASS == 0 and F[start_i] & FLOOR:
        # standing inside a partial block (farmland, bed): start one up
        sy += 1
        start_i = idx(sx, sy, sz)

    if reach is not None:
        rcx, rcy, rcz = tx + 0.5, ty + 0.5, tz + 0.5
        rd2 = reach_dist * reach_dist

        def is_goal(x, y, z):
            if (x, z) == (tx, tz) and ty in (y, y + 1):
                return False
            dx, dy, dz = x + 0.5 - rcx, y + EYE - rcy, z + 0.5 - rcz
            return dx * dx + dy * dy + dz * dz <= rd2
        hx, hy, hz = tx, ty - 1, tz
        hoff = reach_dist * 0.7
    else:
        n2 = near * near

        def is_goal(x, y, z):
            dx, dy, dz = x - tx, y - ty, z - tz
            if near <= 0:
                return dx == 0 and dz == 0 and dy == 0
            return dx * dx + dy * dy * 0.5 + dz * dz <= n2 + 1e-9
        hx, hy, hz = tx, ty, tz
        hoff = near
    if goal_fn is not None:
        base_goal = is_goal

        def is_goal(x, y, z):
            return base_goal(x, y, z) and goal_fn(x, y, z)

    HW = 1.3   # heuristic weight: slightly greedy, much faster on open ground

    def clear(i):
        f = F[i]
        if f & PASS:
            return 0.0
        if f & DIG:
            return dig_tab.get(BL[i], 4.0) if dig_tab is not None else 4.0
        return None

    sqrt = math.sqrt
    push = heapq.heappush
    pop = heapq.heappop
    h0 = max(0.0, sqrt((sx - hx) ** 2 + (sz - hz) ** 2) + abs(sy - hy) * 0.7 - hoff) * HW
    open_h = [(h0, 0.0, 0, start_i)]
    came = {start_i: (None, "start", None)}
    g_best = {start_i: 0.0}
    closed = set()
    best_node, best_h = start_i, h0
    count = 0
    found = None
    cnt = 0
    UP2 = 2 * UP
    card = ((1, 1, 0), (-1, -1, 0), (SX, 0, 1), (-SX, 0, -1))
    diag = ((1, SX), (1, -SX), (-1, SX), (-1, -SX))
    while open_h:
        f_, g, _, i = pop(open_h)
        if i in closed:
            continue
        closed.add(i)
        count += 1
        y = i // UP + Y0
        r = i % UP
        z = r // SX + Z0
        x = r % SX + X0
        if is_goal(x, y, z):
            found = i
            break
        hh = f_ - g
        if hh < best_h:
            best_h, best_node = hh, i
        if count >= max_nodes:
            break
        if not (X0 < x < X1 - 1 and Y0 < y < Y1 - 2 and Z0 < z < Z1 - 1):
            continue
        fi = F[i]
        in_water = fi & WATER
        on_climb = fi & CLIMB
        grounded = F[i - UP] & FLOOR
        head_free = F[i + UP2] & PASS
        cand = []
        for off, _dx, _dz in card:
            j = i + off
            if S[j]:
                fj = F[j]
                w = 1.0
                if fj & WATER:
                    w += 1.0
                if (fj | F[j + UP]) & DOOR:
                    w += 1.0
                cand.append((j, w, "swim" if fj & WATER else "walk", None))
            elif T[j]:
                # drop down
                k = j - UP
                fall = 1
                while k >= UP and T[k] and not S[k] and fall <= 40:
                    k -= UP
                    fall += 1
                if k >= UP and S[k] and (fall <= max_drop or F[k] & WATER):
                    cand.append((k, 1.0 + fall * 0.3, "drop", None))
            # jump up one
            if (grounded or in_water or on_climb) and head_free and F[j] & FLOOR and not F[j] & DOOR and \
                    S[j + UP] and not (F[j + UP] & DOOR):
                cand.append((j + UP, 2.0, "jump", None))
            if allow_dig:
                c1 = clear(j)
                c2 = clear(j + UP)
                if c1 is not None and c2 is not None and (c1 or c2):
                    if F[j - UP] & FLOOR or F[j] & (WATER | CLIMB):
                        dg = [kk for kk, c in ((j, c1), (j + UP, c2)) if c]
                        cand.append((j, 1.0 + c1 + c2, "dig", dg))
                if c1 is not None and c2 is not None and not S[j]:
                    c3 = clear(j - UP)
                    if c3 is not None and c3 > 0 and F[j - UP2] & FLOOR:
                        dg = [kk for kk, c in ((j + UP, c2), (j, c1), (j - UP, c3)) if c]
                        cand.append((j - UP, 1.5 + c1 + c2 + c3, "dig", dg))
                if (grounded or in_water or on_climb) and F[j] & FLOOR and not F[j] & DOOR:
                    u1 = clear(j + UP)
                    u2 = clear(j + UP2)
                    u0 = clear(i + UP2)
                    if u1 is not None and u2 is not None and u0 is not None and (u0 or u1 or u2) and \
                            not (F[j + UP] & DOOR):
                        dg = [kk for kk, c in ((i + UP2, u0), (j + UP, u1), (j + UP2, u2)) if c]
                        cand.append((j + UP, 2.0 + u0 + u1 + u2, "dig", dg))
        for ox, oz in diag:
            j = i + ox + oz
            if S[j] and S[i + ox] and S[i + oz] and not ((F[j] | F[j + UP] | F[i + ox] | F[i + oz] |
                                                         F[i + ox + UP] | F[i + oz + UP]) & DOOR):
                cand.append((j, 2.828 if F[j] & WATER else 1.414, "walk", None))
        # vertical: climb / swim up and down
        if in_water or on_climb:
            t = i + UP
            if T[t] and (S[t] or F[t] & (WATER | CLIMB)):
                cand.append((t, 1.5, "climb" if on_climb else "swim", None))
        t = i - UP
        if t >= UP and S[t] and (F[t] & (WATER | CLIMB) or on_climb):
            cand.append((t, 1.0, "climb" if (on_climb or F[t] & CLIMB) else "swim", None))
        if allow_dig and t >= UP:
            c = clear(t)
            if c and F[t - UP] & FLOOR:
                cand.append((t, 4.0 + c, "dig", [t]))
        for j, w, mv, dg in cand:
            if j in closed or j < UP or j + UP2 >= n_cells:
                continue
            if (F[j] | F[j + UP]) & NEARLAVA:
                w += 6.0
            if avoid is not None:
                w += avoid(j)
            ng = g + w
            if ng < g_best.get(j, 1e18):
                g_best[j] = ng
                came[j] = (i, mv, dg)
                jy = j // UP + Y0
                jr = j % UP
                jz = jr // SX + Z0
                jx = jr % SX + X0
                hv = sqrt((jx - hx) ** 2 + (jz - hz) ** 2) + abs(jy - hy) * 0.7 - hoff
                cnt += 1
                push(open_h, (ng + (hv * HW if hv > 0 else 0.0), ng, cnt, j))
    end = found
    is_partial = False
    if end is None:
        if not partial or best_node == start_i:
            return None
        end = best_node
        is_partial = True
    steps = []
    k = end
    while k is not None:
        prev, mv, dg = came[k]
        y = k // UP + Y0
        r = k % UP
        z = r // SX + Z0
        x = r % SX + X0
        cells = []
        for c in (dg or []):
            cy = c // UP + Y0
            cr = c % UP
            cells.append((cr % SX + X0, cy, cr // SX + Z0))
        steps.append(Step(x, y, z, mv, cells))
        k = prev
    steps.reverse()
    return Path(steps=steps[1:] if len(steps) > 1 else steps, partial=is_partial, nodes=count,
                cost=g_best.get(end, 0.0))
