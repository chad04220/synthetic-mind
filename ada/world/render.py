"""Turning Zen's work into something the Sprite can see or hear: PNG pictures of its paintings and
sculptures, and WAV recordings of its songs. Pure Python (zlib and wave), no extra packages.
"""
from __future__ import annotations

import io
import math
import struct
import wave
import zlib

PAPER = (247, 244, 236)


def png(width: int, height: int, rgb: bytearray) -> bytes:
    """Encode an RGB buffer (width*height*3 bytes) as a PNG."""
    raw = bytearray()
    row = width * 3
    for y in range(height):
        raw.append(0)
        raw += rgb[y * row:(y + 1) * row]

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b""))


def _hex(c: str) -> tuple[int, int, int]:
    return int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)


def painting_png(data: dict, scale: int = 7) -> bytes:
    """The painting as it is: each cell a square of its colour, blank cells the paper."""
    w, h = data["w"], data["h"]
    pal = [_hex(c) for c in data["palette"]]
    codes = "0123456789abcdefghijklmnopqrstuvwxyz"
    px = data["pixels"]
    W, H = w * scale, h * scale
    buf = bytearray(W * H * 3)
    for y in range(H):
        for x in range(W):
            ch = px[(y // scale) * w + x // scale]
            r, g, b = PAPER if ch == "." else pal[codes.index(ch)]
            i = (y * W + x) * 3
            buf[i:i + 3] = bytes((r, g, b))
    return png(W, H, buf)


MATERIAL = {"clay": (194, 112, 61), "wood": (164, 113, 72), "stone": (168, 162, 158), "log": (164, 113, 72)}


def sculpture_png(data: dict, size: int = 320) -> bytes:
    """An isometric view of the clay (lit from the upper left), on a light background."""
    n = data["n"]
    vox = data["voxels"]
    base = MATERIAL.get(data.get("material", "clay"), MATERIAL["clay"])
    buf = bytearray(bytes((236, 232, 224)) * (size * size))
    s = size / (n * 2.2)                   # pixels per voxel edge
    ox, oy = size / 2, size * 0.78

    def proj(x, y, z):                     # x right, y up, z towards the viewer
        return ox + (x - z) * s * 0.866, oy + (x + z) * s * 0.5 - y * s

    def fill(poly, color):
        ys = [p[1] for p in poly]
        y0, y1 = max(0, int(min(ys))), min(size - 1, int(max(ys)) + 1)
        for yy in range(y0, y1 + 1):
            xs = []
            for (ax, ay), (bx, by) in zip(poly, poly[1:] + poly[:1]):
                if (ay <= yy < by) or (by <= yy < ay):
                    xs.append(ax + (yy - ay) * (bx - ax) / (by - ay))
            xs.sort()
            for a, b in zip(xs[::2], xs[1::2]):
                for xx in range(max(0, int(a)), min(size - 1, int(b)) + 1):
                    i = (yy * size + xx) * 3
                    buf[i:i + 3] = bytes(color)

    def shade(k):
        return tuple(max(0, min(255, int(c * k))) for c in base)

    filled = lambda x, y, z: 0 <= x < n and 0 <= y < n and 0 <= z < n and vox[x + n * (z + n * y)] == "1"
    # back to front: far (small x+z) first, low y first
    cells = [(x, y, z) for y in range(n) for z in range(n) for x in range(n) if vox[x + n * (z + n * y)] == "1"]
    cells.sort(key=lambda c: (c[0] + c[2], c[1]))
    for x, y, z in cells:
        if not filled(x, y + 1, z):        # top
            fill([proj(x, y + 1, z), proj(x + 1, y + 1, z), proj(x + 1, y + 1, z + 1), proj(x, y + 1, z + 1)], shade(1.15))
        if not filled(x, y, z + 1):        # front-left
            fill([proj(x, y, z + 1), proj(x + 1, y, z + 1), proj(x + 1, y + 1, z + 1), proj(x, y + 1, z + 1)], shade(0.85))
        if not filled(x + 1, y, z):        # front-right
            fill([proj(x + 1, y, z), proj(x + 1, y, z + 1), proj(x + 1, y + 1, z + 1), proj(x + 1, y + 1, z)], shade(0.65))
    return png(size, size, buf)


def music_wav(data: dict, rate: int = 16000, max_seconds: float = 30.0) -> bytes:
    """Play the notes on a simple piano-like voice (a few decaying harmonics)."""
    tempo = data.get("tempo", 100)
    changes = {i: t for i, t in data.get("tempo_changes", [])}
    out = []
    for k, (midi, beats) in enumerate(data.get("notes", [])):
        tempo = changes.get(k, tempo)
        dur = beats * 60.0 / tempo
        n = int(dur * rate)
        if midi < 0:
            out.extend([0.0] * n)
        else:
            f = 440.0 * 2 ** ((midi - 69) / 12)
            for i in range(n):
                t = i / rate
                env = math.exp(-3.0 * t) * min(1.0, i / (0.005 * rate))
                v = (math.sin(2 * math.pi * f * t) + 0.45 * math.sin(4 * math.pi * f * t)
                     + 0.2 * math.sin(6 * math.pi * f * t))
                out.append(0.28 * env * v)
        if len(out) > max_seconds * rate:
            out = out[:int(max_seconds * rate)]
            break
    out.extend([0.0] * int(0.3 * rate))
    bio = io.BytesIO()
    with wave.open(bio, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"".join(struct.pack("<h", max(-32767, min(32767, int(x * 32767)))) for x in out))
    return bio.getvalue()
