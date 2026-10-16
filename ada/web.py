"""The web server, running inside the Hub process. Every handler is quick: requests to the World are
forwarded and awaited without blocking."""
from __future__ import annotations

import asyncio
import json
import math
import time
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse, Response

from .hub import Hub

WEB = Path(__file__).resolve().parent.parent / "web"

WORLD = {"chat": ["text", "who"],
         "visitor": ["action", "x", "y", "z", "yaw", "pitch", "id", "item", "count", "slot", "face", "text", "creative", "name"],
         "agent": ["action", "id", "value", "text"]}


def clean(o):
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    return o


def dumps(o) -> str:
    try:
        return json.dumps(o, allow_nan=False)
    except ValueError:
        return json.dumps(clean(o))


@lru_cache(maxsize=1)
def registry() -> dict:
    """The blocks, items and recipes, straight from the world's tables (static for a run)."""
    from .vox import blocks, items, recipes

    return {"blocks": blocks.public() if hasattr(blocks, "public") else blocks.BLOCKS,
            "items": items.public() if hasattr(items, "public") else items.ITEMS,
            "recipes": recipes.public() if hasattr(recipes, "public") else recipes.RECIPES}


def create_app(hub: Hub) -> FastAPI:
    async def watch_lag():
        """How late the web server wakes up: if this grows, something is starving the Hub."""
        while True:
            t = time.perf_counter()
            await asyncio.sleep(0.5)
            hub.perf.add("event loop lag", max(0.0, time.perf_counter() - t - 0.5))

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(watch_lag())
        yield
        task.cancel()

    app = FastAPI(title=f"Synthetic Mind · {hub.cfg.name}", lifespan=lifespan)

    @app.get("/")
    def index():
        return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/static/{path:path}")
    def static(path: str):
        p = (WEB / path).resolve()
        if not p.is_file() or WEB.resolve() not in p.parents:
            raise HTTPException(404)
        return FileResponse(p, headers={"Cache-Control": "no-cache"})

    async def wait(f, timeout=60):
        try:
            return await asyncio.wait_for(asyncio.wrap_future(f), timeout)
        except asyncio.TimeoutError:
            raise HTTPException(504, "It is taking too long to answer. Try again in a moment.")
        except RuntimeError as e:
            raise HTTPException(409, str(e))

    @app.get("/api/health")
    def health():
        return clean(hub.health())

    @app.get("/api/diagnostics")
    async def diagnostics():
        text = await asyncio.to_thread(hub.report)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        return PlainTextResponse(text, headers={
            "Content-Disposition": f'attachment; filename="synthetic-mind-diagnostics-{stamp}.txt"'})

    @app.get("/api/archive/{kind}")
    async def archive(kind: str, before: float | None = None, limit: int = 60, q: str = "", who: str = ""):
        if kind not in ("thoughts", "conversations"):
            raise HTTPException(404, f"no archive called {kind}")
        return clean(await asyncio.to_thread(hub.archive.page, kind, before, limit, q, who))

    @app.get("/api/blocks")
    def blocks():
        return registry()["blocks"]

    @app.get("/api/items")
    def items():
        return registry()["items"]

    @app.get("/api/recipes")
    def recipes():
        return registry()["recipes"]

    @app.get("/api/chunk")
    async def chunk(cx: int, cz: int):
        data = await wait(hub.request("world", "chunk", cx=cx, cz=cz), 30)
        return Response(content=data, media_type="application/octet-stream")

    @app.get("/api/model")
    def model():
        return clean(hub.model_info())

    @app.get("/api/decisions")
    async def decisions(limit: int = 100):
        return clean(await wait(hub.request("world", "decisions", limit=limit), 30))

    @app.post("/api/client_perf")
    def client_perf(body: dict):
        hub.record_client_perf({k: v for k, v in body.items() if isinstance(v, (int, float, str, bool))})
        return {"ok": True}

    @app.post("/api/{name}")
    async def command(name: str, body: dict | None = None):
        b = body or {}
        if name in WORLD:
            args = {k: b.get(k) for k in WORLD[name] if k in b}
            if name == "chat" and not str(b.get("text") or "").strip():
                raise HTTPException(400, "Say something first.")
            result = await wait(hub.request("world", name, **args))
            if name == "chat":
                hub.event("chat", who=b.get("who") or "you", text=b.get("text"))
            return {"result": clean(result)}
        if name == "set":
            try:
                return {"result": hub.set(b["key"], b["value"])}
            except (KeyError, ValueError, TypeError) as e:
                raise HTTPException(400, str(e))
        if name == "practice":
            try:
                return {"result": clean(hub.practice(str(b.get("action")), b.get("name"), b.get("value")))}
            except ValueError as e:
                raise HTTPException(409, str(e))
        raise HTTPException(404, f"unknown command {name}")

    @app.websocket("/ws")
    async def ws(sock: WebSocket):
        await sock.accept()
        try:
            init = hub.init_payload()
            await sock.send_text(dumps(init))
            eid, wseq = init["event_id"], init["world_seq"]
            settings, model = hub.settings(), dumps(init["model"])
            n = 0
            while True:
                await asyncio.sleep(0.1)
                n += 1
                msg = {"type": "tick"}
                wseq, delta = hub.world_delta(wseq)
                if delta:
                    msg["world"] = delta
                evs = hub.events_since(eid)
                if evs:
                    eid = evs[-1]["id"]
                    msg["events"] = evs
                if n % 5 == 0:
                    mi = dumps(hub.model_info())
                    if mi != model:
                        model, msg["model"] = mi, json.loads(mi)
                    s = hub.settings()
                    if s != settings:
                        settings = msg["settings"] = s
                if len(msg) > 1:
                    t = time.perf_counter()
                    text = dumps(msg)
                    await sock.send_text(text)
                    hub.perf.add("sending to the browser", time.perf_counter() - t)
                    hub.ws_bytes += len(text)
        except (WebSocketDisconnect, RuntimeError):
            pass

    return app
