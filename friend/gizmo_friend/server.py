from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from gizmo_friend.body_protocol import Click, Frame, Hold, MicChunk, Navigate, Power, PushToTalk, TextLine
from gizmo_friend.session import Friend

STATIC = Path(__file__).parent / "static"


def app_factory(data_dir: Path) -> FastAPI:
    friend = Friend(data_dir)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.friend = friend
        yield
        await friend.close()

    app = FastAPI(title="Gizmo Friend", docs_url=None, redoc_url=None, lifespan=lifespan)
    media = data_dir / "media"
    media.mkdir(parents=True, exist_ok=True)

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/health")
    async def health() -> dict:
        return {
            "ok": True,
            "state": friend.state.value,
            "transport": friend.transport_name,
            "name": friend.memory.get_name(),
        }

    @app.get("/api/outbox")
    async def outbox() -> dict:
        pages = [p.__dict__ for p in friend.outbox.list_pages()]
        return {"pages": pages}

    @app.get("/api/pages")
    async def pages() -> dict:
        prefix = friend.memory.prefix_memory()
        last = friend.memory.last_page()
        return {
            "name": prefix.name,
            "facts": prefix.facts,
            "objects": prefix.objects,
            "last": None
            if last is None
            else {
                "id": last.id,
                "subject": last.subject,
                "line": last.line,
                "still": f"/media/{Path(last.still_path).name}",
            },
        }

    @app.get("/media/{name}")
    async def media_file(name: str) -> FileResponse:
        path = media / Path(name).name
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="no page")
        media_type = "image/svg+xml" if path.suffix.lower() == ".svg" else None
        return FileResponse(path, media_type=media_type)

    @app.websocket("/ws")
    async def ws(socket: WebSocket) -> None:
        await socket.accept()
        queue = friend.subscribe()
        await socket.send_json(
            {
                "type": "hello",
                "state": friend.state.value,
                "screen": friend.machine.awake(),
                "viewing": friend.machine.screen_on(friend.viewing_page),
                "transport": friend.transport_name,
                "name": friend.memory.get_name(),
            }
        )

        async def pump() -> None:
            while True:
                event = await queue.get()
                await socket.send_json(event)

        task = asyncio.create_task(pump())
        try:
            while True:
                message = await socket.receive_json()
                await _dispatch(friend, message)
        except WebSocketDisconnect:
            pass
        finally:
            task.cancel()
            friend.unsubscribe(queue)

    if STATIC.exists():
        app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


async def _dispatch(friend: Friend, message: dict) -> None:
    kind = message.get("type")
    if kind == "click":
        await friend.handle(Click())
    elif kind == "hold":
        await friend.handle(Hold())
    elif kind == "power":
        await friend.handle(Power(on=bool(message.get("on", True))))
    elif kind == "ptt":
        await friend.handle(PushToTalk(active=bool(message.get("active", False))))
    elif kind == "navigate":
        direction = str(message.get("direction") or "").lower()
        if direction in {"up", "down", "left", "right"}:
            await friend.handle(Navigate(direction=direction))
    elif kind == "text":
        await friend.handle(TextLine(text=str(message.get("text") or "")))
    elif kind == "audio":
        raw = str(message.get("pcm") or "")
        pcm = base64.b64decode(raw) if raw else b""
        if pcm:
            await friend.handle(MicChunk(pcm=pcm))
    elif kind == "frame":
        hint = message.get("hint")
        image_b64 = message.get("image")
        image = base64.b64decode(image_b64) if image_b64 else None
        await friend.handle(Frame(image=image, hint=hint if isinstance(hint, str) else None))
