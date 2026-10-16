"""The web server, running inside the Hub process. Every handler is quick: requests to the Academy
or World are forwarded and awaited without blocking, and Wren's model runs on worker threads."""
from __future__ import annotations

import asyncio
import json
import math
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .hub import Hub

WEB = Path(__file__).resolve().parent.parent / "web"

WORLD = {"chat": ["text"], "suggest": ["text"], "visitor": ["action", "kind", "text", "fx", "fy", "facing", "target", "to"],
         "place": ["kind", "x", "y", "text"], "sleep_now": [], "wake_now": [], "think": []}
ACADEMY = {"publish": [], "grow": [], "save": [], "evaluate": [], "probe": ["text"]}


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

    app = FastAPI(title=f"Ada · {hub.cfg.name}", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=WEB), name="static")

    @app.get("/")
    def index():
        return FileResponse(WEB / "index.html")

    async def wait(f, timeout=120):
        try:
            return await asyncio.wait_for(asyncio.wrap_future(f), timeout)
        except asyncio.TimeoutError:
            raise HTTPException(504, "It is taking too long to answer. Try again in a moment.")
        except RuntimeError as e:
            raise HTTPException(409, str(e))

    async def thread(fn, *args):
        try:
            return await asyncio.to_thread(fn, *args)
        except Exception as e:
            raise HTTPException(400, f"{type(e).__name__}: {e}")

    @app.get("/api/health")
    def health():
        return clean(hub.health())

    @app.get("/api/diagnostics")
    async def diagnostics():
        text = await asyncio.to_thread(hub.report)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        return PlainTextResponse(text, headers={
            "Content-Disposition": f'attachment; filename="ada-diagnostics-{stamp}.txt"'})

    @app.post("/api/client_perf")
    def client_perf(body: dict):
        hub.record_client_perf({k: v for k, v in body.items() if isinstance(v, (int, float, str, bool))})
        return {"ok": True}

    @app.post("/api/{name}")
    async def command(name: str, body: dict | None = None):
        b = body or {}
        if name in WORLD:
            result = await wait(hub.request("world", name, **{k: b.get(k) for k in WORLD[name]}))
            if name == "chat":
                hub.event("chat", user=b.get("text"), **(result or {}))
            return {"result": clean(result)}
        if name in ACADEMY:
            return {"result": clean(await wait(hub.request("academy", name, **{k: b.get(k) for k in ACADEMY[name]})))}
        if name == "set":
            try:
                return {"result": hub.set(b["key"], b["value"])}
            except (KeyError, ValueError, TypeError) as e:
                raise HTTPException(400, str(e))
        if name == "oracle_ask":
            return {"result": await thread(hub.ask, str(b["question"]))}
        if name == "oracle_teach":
            topic = str(b["topic"]).strip()
            if not topic:
                raise HTTPException(400, "Name a topic to teach.")
            if not hub.oracle_ready():
                raise HTTPException(409, hub.oracle.error or f"{hub.cfg.companion}'s mind is off or has no model.")
            hub.topics.append(topic)
            return {"result": f"{hub.cfg.companion} will teach {hub.cfg.name} about {topic}."}
        if name == "oracle_learn":
            hub.learn_answer(str(b["question"]), str(b["answer"]))
            return {"result": f"{hub.cfg.name} will study it."}
        if name == "models":
            await thread(hub.oracle.refresh)
            return {"result": hub.oracle_info()}
        raise HTTPException(404, f"unknown command {name}")

    @app.websocket("/ws")
    async def ws(sock: WebSocket):
        await sock.accept()
        try:
            init = hub.init_payload()
            await sock.send_text(dumps(init))
            eid, wseq, aseq = init["event_id"], init["world_seq"], -1
            settings = hub.settings()
            local = hub.local.info()
            while True:
                await asyncio.sleep(0.25)
                msg = {"type": "tick"}
                wseq, delta = hub.world_delta(wseq)
                if delta:
                    msg["world"] = delta
                if hub.academy_seq != aseq:
                    aseq = hub.academy_seq
                    msg["academy"] = hub.academy_status
                evs = hub.events_since(eid)
                if evs:
                    eid = evs[-1]["id"]
                    msg["events"] = evs
                    if any(e["kind"] in ("lesson", "error") for e in evs):
                        msg["oracle"] = hub.oracle_info()
                    if any(e["kind"] == "concepts" for e in evs):
                        msg["concepts"] = hub.concept_report
                li = hub.local.info()
                if li != local:                                  # Wren's model: setup progress
                    local = li
                    msg["oracle"] = hub.oracle_info()
                s = hub.settings()
                if s != settings:
                    settings = msg["settings"] = s
                    msg["oracle"] = hub.oracle_info()
                if len(msg) > 1:
                    t = time.perf_counter()
                    text = dumps(msg)
                    await sock.send_text(text)
                    hub.perf.add("sending to the browser", time.perf_counter() - t)
                    hub.ws_bytes += len(text)
        except (WebSocketDisconnect, RuntimeError):
            pass

    return app
