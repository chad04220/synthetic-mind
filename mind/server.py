"""Web server: serves the UI, streams the mind's state and events over a WebSocket and
forwards your actions to the engine thread."""
from __future__ import annotations

import asyncio
import json
import math
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .brain import Mind

WEB = Path(__file__).resolve().parent.parent / "web"

# command name -> argument names taken from the JSON body
COMMANDS = {
    "chat": ["text"], "probe": ["text"], "teach": ["text"], "feedback": ["index", "good"],
    "set": ["key", "value"], "grow": [], "save": [], "think": [], "act": ["action"],
    "refresh_models": [],
}
# Applied straight away under the world lock, so they never wait behind training or a thought.
WORLD_COMMANDS = {
    "place": ["kind", "x", "y", "text"], "join": [], "leave": [], "you": ["action", "kind", "text"],
    "reset_world": [],
}


def clean(o):
    """Replace NaN/Infinity with null: browsers' JSON.parse rejects them, which would stall the page."""
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    return o


def dumps(obj) -> str:
    try:
        return json.dumps(obj, allow_nan=False)
    except ValueError:  # a NaN somewhere: replace it (slower, so only when needed)
        return json.dumps(clean(obj))


async def send(sock: WebSocket, obj) -> None:
    await sock.send_text(dumps(obj))


def create_app(mind: Mind) -> FastAPI:
    app = FastAPI(title=f"Synthetic Mind: {mind.cfg.name}")
    app.mount("/static", StaticFiles(directory=WEB), name="static")

    @app.get("/")
    def index():
        return FileResponse(WEB / "index.html")

    def init_payload() -> dict:
        return {
            "type": "init",
            "snap": dict(mind.snapshot, world=mind.world_view()) if mind.snapshot else {},
            "history": list(mind.history),
            "thoughts": list(mind.thoughts)[-120:],
            "chat": [dict(m, index=i) for i, m in enumerate(mind.chat_log)][-120:],
            "assessments": mind.assessments[-200:],
            "events": list(mind.events)[-150:],
        }

    @app.get("/api/state")
    def state():
        return clean(init_payload())

    @app.post("/api/{name}")
    async def command(name: str, body: dict | None = None):
        body = body or {}
        if name in WORLD_COMMANDS:
            args = [body.get(k) for k in WORLD_COMMANDS[name]]
            try:
                result = await asyncio.to_thread(mind.world_command, name, *args)
            except Exception as e:
                raise HTTPException(400, f"{type(e).__name__}: {e}")
            return clean({"ok": True, "result": result, "world": mind.world_view()})
        if name not in COMMANDS:
            raise HTTPException(404, f"unknown command {name}")
        args = [body.get(k) for k in COMMANDS[name]]
        try:
            result = await asyncio.wait_for(asyncio.wrap_future(mind.call(name, *args)), timeout=120)
        except Exception as e:
            raise HTTPException(400, f"{type(e).__name__}: {e}")
        return clean({"ok": True, "result": result})

    @app.websocket("/ws")
    async def ws(sock: WebSocket):
        await sock.accept()
        try:
            while not mind.snapshot:
                await asyncio.sleep(0.2)
            await send(sock, init_payload())
            last = mind.event_id
            seen_terrain, seen_internals = None, None
            while True:
                await asyncio.sleep(0.25)
                evs = mind.events_since(last)
                if evs:
                    last = evs[-1]["id"]
                # The world is read fresh each tick, so your edits show even while the engine is busy.
                # Bulky parts that rarely change (terrain, attention maps) are sent only when they do.
                world = mind.world_view()
                if world["terrain_v"] == seen_terrain:
                    del world["terrain"]
                seen_terrain = world["terrain_v"]
                snap = dict(mind.snapshot, world=world)
                if snap.get("internals_v") == seen_internals:
                    snap.pop("internals", None)
                seen_internals = snap.get("internals_v")
                await send(sock, {"type": "tick", "snap": snap, "events": evs, "t": time.time()})
        except (WebSocketDisconnect, RuntimeError):
            pass

    return app
