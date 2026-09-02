from __future__ import annotations

import asyncio
import base64
import hmac
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from gizmo_friend.body_protocol import Frame, MicChunk, Navigate, Power, PushToTalk, Select, TextLine
from gizmo_friend.session import GizmoSession

STATIC = Path(__file__).parent / "static"


def app_factory(data_dir: Path) -> FastAPI:
    device_token = os.environ.get("GIZMO_DEVICE_TOKEN", "").strip()
    deployed = bool(os.environ.get("RAILWAY_ENVIRONMENT_ID"))
    if deployed and not device_token:
        raise RuntimeError("GIZMO_DEVICE_TOKEN is required for a cloud deployment")
    # One Gizmo per device. The body identifies itself with X-Gizmo-Device on
    # the socket handshake; that id keys memory and transcripts, so two
    # devices never share a mind. Sessions outlive their sockets: a reconnect
    # picks up the same Gizmo mid-thought.
    sessions: dict[str, GizmoSession] = {}
    default_device = os.environ.get("GIZMO_USER_ID", "gizmo-local-user")

    def session_for(device_id: str) -> GizmoSession:
        friend = sessions.get(device_id)
        if friend is None:
            friend = GizmoSession(data_dir / "devices" / device_id, user_id=device_id)
            sessions[device_id] = friend
        return friend

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.sessions = sessions
        yield
        await asyncio.gather(*(friend.close() for friend in sessions.values()), return_exceptions=True)

    app = FastAPI(title="Gizmo Friend", docs_url=None, redoc_url=None, lifespan=lifespan)

    def authorized(connection: Request | WebSocket) -> bool:
        # Preserve the local browser harness; cloud connections always need a token.
        if not deployed and connection.client and connection.client.host in {"127.0.0.1", "::1"}:
            return True
        if not device_token:
            return True
        scheme, _, credential = connection.headers.get("authorization", "").partition(" ")
        return scheme.lower() == "bearer" and hmac.compare_digest(credential.encode(), device_token.encode())

    @app.middleware("http")
    async def require_device_token(request: Request, call_next):
        if request.url.path != "/health" and not authorized(request):
            return JSONResponse({"detail": "unauthorized"}, status_code=401)
        return await call_next(request)

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/health")
    async def health() -> dict:
        return {
            "ok": True,
            "devices": len(sessions),
            "authentication_required": bool(device_token),
        }

    @app.websocket("/ws")
    async def ws(socket: WebSocket) -> None:
        if not authorized(socket):
            await socket.close(code=1008)
            return
        device_id = _device_id(socket.headers.get("x-gizmo-device", ""), default_device)
        friend = session_for(device_id)
        await socket.accept()
        queue = friend.subscribe()
        await socket.send_json(
            {
                "type": "hello",
                "state": friend.state.value,
                "power": friend.machine.powered(),
                "screen": friend.machine.awake(),
                "transport": friend.transport_name,
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
                try:
                    await _dispatch(friend, message)
                except Exception as error:  # noqa: BLE001 - one bad action must not drop the body
                    await friend.emit(
                        {
                            "type": "error",
                            "message": f"device action failed: {error}",
                        }
                    )
        except WebSocketDisconnect:
            pass
        finally:
            task.cancel()
            friend.unsubscribe(queue)

    if STATIC.exists():
        app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def _device_id(header: str, default: str) -> str:
    """A device id is an opaque label, kept filesystem- and URL-safe."""
    cleaned = "".join(ch for ch in header.strip() if ch.isalnum() or ch in "-_.")[:64]
    return cleaned or default


async def _dispatch(friend: GizmoSession, message: dict) -> None:
    kind = message.get("type")
    if kind == "select":
        await friend.handle(Select())
    elif kind == "power":
        await friend.handle(Power(on=bool(message.get("on", True))))
    elif kind == "ptt":
        await friend.handle(PushToTalk(active=bool(message.get("active", False))))
    elif kind == "navigate":
        direction = str(message.get("direction") or "").lower()
        if direction in {"up", "down"}:
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
