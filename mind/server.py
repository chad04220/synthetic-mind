"""Web server: serves the UI, streams the mind's state and events over a WebSocket and
forwards your actions to the engine thread."""
from __future__ import annotations

import asyncio
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
    "place": ["kind", "x", "y", "text"], "refresh_models": [], "reset_world": [],
}


def create_app(mind: Mind) -> FastAPI:
    app = FastAPI(title=f"Synthetic Mind: {mind.cfg.name}")
    app.mount("/static", StaticFiles(directory=WEB), name="static")

    @app.get("/")
    def index():
        return FileResponse(WEB / "index.html")

    def init_payload() -> dict:
        return {
            "type": "init",
            "snap": mind.snapshot,
            "history": list(mind.history),
            "thoughts": list(mind.thoughts)[-120:],
            "chat": [dict(m, index=i) for i, m in enumerate(mind.chat_log)][-120:],
            "assessments": mind.assessments[-200:],
            "events": list(mind.events)[-150:],
        }

    @app.get("/api/state")
    def state():
        return init_payload()

    @app.post("/api/{name}")
    async def command(name: str, body: dict | None = None):
        if name not in COMMANDS:
            raise HTTPException(404, f"unknown command {name}")
        body = body or {}
        args = [body.get(k) for k in COMMANDS[name]]
        try:
            result = await asyncio.wait_for(asyncio.wrap_future(mind.call(name, *args)), timeout=120)
        except Exception as e:
            raise HTTPException(400, f"{type(e).__name__}: {e}")
        return {"ok": True, "result": result}

    @app.websocket("/ws")
    async def ws(sock: WebSocket):
        await sock.accept()
        try:
            while not mind.snapshot:
                await asyncio.sleep(0.2)
            await sock.send_json(init_payload())
            last = mind.event_id
            while True:
                await asyncio.sleep(0.25)
                evs = mind.events_since(last)
                if evs:
                    last = evs[-1]["id"]
                await sock.send_json({"type": "tick", "snap": mind.snapshot, "events": evs, "t": time.time()})
        except (WebSocketDisconnect, RuntimeError):
            pass

    return app
