from __future__ import annotations

import asyncio
import base64
import hmac
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from gizmo_friend.body_protocol import (
    BODY_AUDIO_CHANNELS,
    BODY_AUDIO_SAMPLE_FORMAT,
    BODY_AUDIO_SAMPLE_RATE_HZ,
    BODY_CAMERA_MAX_BYTES,
    BODY_CAMERA_MAX_HEIGHT,
    BODY_CAMERA_MAX_WIDTH,
    BODY_PROTOCOL_VERSION,
    BODY_SETTING_STEPS,
    Frame,
    GlassReady,
    MicChunk,
    Navigate,
    Power,
    PushToTalk,
    Select,
    TextLine,
)
from gizmo_friend.brain.shows import MAX_IMAGE_DIMENSION, ShowStore, valid_device_id
from gizmo_friend.brain.show_media import MAX_FRAME_DIMENSION, MAX_FRAME_FPS, MediaError
from gizmo_friend.brain.show_budget import ShowBudget
from gizmo_friend.session import GizmoSession

STATIC = Path(__file__).parent / "static"
ODDITY_PUBLIC_ASSETS = {
    "/static/device-reference-ptt-pressed.png",
    "/static/device-reference.png",
    "/static/oddity-blink-10.jpg",
    "/static/oddity-blink-11.jpg",
    "/static/oddity-blink-12.jpg",
    "/static/oddity-blink-13.jpg",
    "/static/oddity-character.png",
    "/static/oddity-device.css",
    "/static/oddity-device.mjs",
    "/static/oddity-michroma.ttf",
    "/static/oddity-outfit.ttf",
    "/static/oddity-skin.json",
    "/static/oddity-timing.mjs",
    "/static/oddity-orbit.mjs",
    "/static/oddity-glass.mjs",
    "/static/oddity-boot.wav",
    "/static/demo-birthday-kid.mp3",
    "/static/demo-birthday-gizmo.wav",
    "/static/demo-pompeii-kid.mp3",
    "/static/demo-pompeii-1.mp4",
    "/static/demo-pompeii-1.wav",
    "/static/demo-pompeii-2.mp4",
    "/static/demo-pompeii-2.wav",
    "/static/demo-pompeii-3.mp4",
    "/static/demo-pompeii-3.wav",
    "/static/oddity-heart-full.png",
    "/static/oddity-heart-half.png",
    "/static/oddity-heart-empty.png",
    "/static/oddity-boot-00.jpg",
    "/static/oddity-boot-01.jpg",
    "/static/oddity-boot-02.jpg",
    "/static/oddity-boot-03.jpg",
    "/static/oddity-boot-04.jpg",
    "/static/oddity-boot-05.jpg",
    "/static/oddity-boot-06.jpg",
    "/static/oddity-boot-07.jpg",
    "/static/oddity-boot-08.jpg",
    "/static/oddity-boot-09.jpg",
    "/static/oddity-boot-10.jpg",
    "/static/oddity-boot-11.jpg",
    "/static/oddity-boot-12.jpg",
    "/static/oddity-boot-13.jpg",
    "/static/oddity-boot-14.jpg",
    "/static/oddity-interaction.mjs",
    "/static/oddity-experience.css",
    "/static/oddity-boot.css",
    "/static/oddity.css",
    "/static/oddity.js",
}


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
    default_device = _device_id(os.environ.get("GIZMO_USER_ID", ""), "gizmo-local-user")
    show_budget = ShowBudget(data_dir)

    def session_for(device_id: str) -> GizmoSession:
        friend = sessions.get(device_id)
        if friend is None:
            friend = GizmoSession(
                data_dir / "devices" / device_id, user_id=device_id,
                show_budget=show_budget,
            )
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
        public_oddity = (
            request.url.path in {"/oddity", "/oddity/session", "/oddity/moments"}
            or request.url.path.startswith("/oddity/media/")
            or request.url.path in ODDITY_PUBLIC_ASSETS
            or request.url.path == "/cinema" or request.url.path.startswith("/cinema/")
            or request.url.path in {"/static/cinema.css", "/static/cinema.js", "/static/cinema-poster.jpg"}
        )
        if request.url.path != "/health" and not public_oddity and not authorized(request):
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
            "body_protocol": {
                "version": BODY_PROTOCOL_VERSION,
                "websocket_path": "/ws",
                "input_events": ["power", "ptt", "navigate", "select", "frame", "audio", "glass_ready"],
                "output_events": [
                    "hello", "state", "glass", "audio", "ptt", "navigate",
                    "select", "frame", "transcript", "interrupted", "error",
                    "settings",
                ],
                "audio": {
                    "sample_rate_hz": BODY_AUDIO_SAMPLE_RATE_HZ,
                    "channels": BODY_AUDIO_CHANNELS,
                    "sample_format": BODY_AUDIO_SAMPLE_FORMAT,
                    "encoding": "base64",
                },
                "camera": {
                    "format": "jpeg",
                    "max_width": BODY_CAMERA_MAX_WIDTH,
                    "max_height": BODY_CAMERA_MAX_HEIGHT,
                    "max_bytes": BODY_CAMERA_MAX_BYTES,
                },
                "show_frames": {
                    "format": "mjpeg",
                    "default_width": 320,
                    "default_height": 240,
                    "default_fps": 12,
                    "max_dimension": MAX_FRAME_DIMENSION,
                    "max_fps": MAX_FRAME_FPS,
                },
                "settings": {
                    "steps": BODY_SETTING_STEPS,
                    "keys": ["brightness", "volume"],
                },
            },
        }

    def show_store(request: Request, device_id: str) -> ShowStore:
        requesting_device = _device_id(request.headers.get("x-gizmo-device", ""), default_device)
        if not valid_device_id(device_id) or device_id != requesting_device:
            # Avoid disclosing whether another device has this show.
            raise HTTPException(status_code=404, detail="show not found")
        return ShowStore(data_dir / "devices" / device_id, device_id=device_id)

    media_headers = {
        "Cache-Control": "private, max-age=86400, immutable",
        "Vary": "Authorization, X-Gizmo-Device",
        "X-Content-Type-Options": "nosniff",
    }

    @app.get("/shows/{device_id}/{show_id}.jpg")
    def show_still(
        request: Request,
        device_id: str,
        show_id: str,
        w: int | None = Query(default=None, ge=1, le=MAX_IMAGE_DIMENSION),
        h: int | None = Query(default=None, ge=1, le=MAX_IMAGE_DIMENSION),
    ) -> FileResponse:
        store = show_store(request, device_id)
        try:
            path = store.still_path(show_id, width=w, height=h)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="show not found") from None
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None
        return FileResponse(
            path,
            media_type="image/jpeg",
            headers=media_headers,
        )

    @app.get("/shows/{device_id}/{show_id}.mp4")
    def show_clip(request: Request, device_id: str, show_id: str) -> FileResponse:
        store = show_store(request, device_id)
        try:
            path = store.clip_path(show_id)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="clip not found") from None
        return FileResponse(path, media_type="video/mp4", headers=media_headers)

    @app.get("/shows/{device_id}/{show_id}.mjpeg")
    def show_frames(
        request: Request, device_id: str, show_id: str,
        w: int = Query(default=320, ge=1, le=MAX_FRAME_DIMENSION),
        h: int = Query(default=240, ge=1, le=MAX_FRAME_DIMENSION),
        fps: int = Query(default=12, ge=1, le=MAX_FRAME_FPS),
    ) -> FileResponse:
        store = show_store(request, device_id)
        try:
            frames = store.mjpeg(show_id, width=w, height=h, fps=fps)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="clip not found") from None
        except MediaError:
            raise HTTPException(status_code=503, detail="video processing unavailable") from None
        return FileResponse(
            frames.path, media_type="video/x-motion-jpeg",
            headers={
                **media_headers,
                "X-Gizmo-Frame-Count": str(frames.frame_count),
                "X-Gizmo-Frame-Rate": str(frames.fps),
                "X-Gizmo-Frame-Width": str(frames.width),
                "X-Gizmo-Frame-Height": str(frames.height),
            },
        )

    @app.websocket("/ws")
    async def ws(socket: WebSocket) -> None:
        if not authorized(socket):
            await socket.close(code=1008)
            return
        requested_protocol = socket.headers.get("x-gizmo-protocol", "").strip()
        if requested_protocol and requested_protocol != str(BODY_PROTOCOL_VERSION):
            await socket.accept()
            await socket.close(code=1002, reason="unsupported body protocol")
            return
        device_id = _device_id(socket.headers.get("x-gizmo-device", ""), default_device)
        # Cinema is a Friend capability on this same session. The old
        # GIZMO_DIRECTOR_DEVICE whole-session swap is gone; that env var now
        # only tells Friend to prefer film for this device's asks.
        friend = session_for(device_id)
        await socket.accept()
        queue = friend.subscribe(glass_cues=socket.headers.get("x-gizmo-glass-cues") == "1")
        await socket.send_json(
            {
                "type": "hello",
                "protocol_version": BODY_PROTOCOL_VERSION,
                "state": friend.state.value,
                "power": friend.machine.powered(),
                "screen": friend.machine.awake(),
                "transport": friend.transport_name,
                "settings": friend.settings.public(),
            }
        )
        await socket.send_json(friend.show_event() or {"type": "glass", "viewing": False})

        async def pump() -> None:
            while True:
                event = await queue.get()
                await socket.send_json(event)

        task = asyncio.create_task(pump())
        try:
            while True:
                message = await socket.receive_json()
                try:
                    await _dispatch(friend, message, source=socket)
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
            await friend.body_disconnected(socket)

    if STATIC.exists():
        from gizmo_friend.oddity.routes import router as oddity_router

        app.include_router(oddity_router(data_dir, STATIC))
        from gizmo_friend.cinema.routes import router as cinema_router
        app.include_router(cinema_router(data_dir, STATIC))
        app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def _device_id(header: str, default: str) -> str:
    """A device id is an opaque label, kept filesystem- and URL-safe."""
    cleaned = "".join(ch for ch in header.strip() if ch.isalnum() or ch in "-_.")[:64]
    if valid_device_id(cleaned):
        return cleaned
    return default if valid_device_id(default) else "gizmo-local-user"


async def _dispatch(friend: GizmoSession, message: dict, *, source: object | None = None) -> None:
    kind = message.get("type")
    event = None
    if kind == "select":
        event = Select()
    elif kind == "power":
        event = Power(on=bool(message.get("on", True)))
    elif kind == "ptt":
        event = PushToTalk(active=bool(message.get("active", False)))
    elif kind == "navigate":
        direction = str(message.get("direction") or "").lower()
        if direction in {"up", "down"}:
            event = Navigate(direction=direction)
    elif kind == "text":
        event = TextLine(text=str(message.get("text") or ""))
    elif kind == "glass_ready":
        cue = message.get("cue")
        glass_kind = str(message.get("kind") or "still")
        if (isinstance(cue, int) and not isinstance(cue, bool) and 0 < cue <= 0xFFFFFFFF
                and glass_kind in {"still", "motion"} and isinstance(message.get("ok", True), bool)):
            event = GlassReady(cue=cue, kind=glass_kind, ok=bool(message.get("ok", True)))
    elif kind in {"audio", "mic"}:
        # `audio` is the wire name used by the native body. Keep `mic` as
        # an alias for firmware based on the earlier body handoff notes.
        raw = message.get("pcm", "")
        if not isinstance(raw, str):
            raise ValueError("audio.pcm must be a base64 string")
        try:
            pcm = base64.b64decode(raw, validate=True)
        except ValueError:
            raise ValueError("audio.pcm must be valid base64") from None
        if len(pcm) % 2:
            raise ValueError("audio.pcm must contain complete 16-bit samples")
        if pcm:
            event = MicChunk(pcm=pcm)
    elif kind == "frame":
        hint = message.get("hint")
        image_b64 = message.get("image")
        image = None
        if image_b64 is not None:
            if not isinstance(image_b64, str):
                raise ValueError("frame.image must be a base64 string")
            if len(image_b64) > 4 * ((BODY_CAMERA_MAX_BYTES + 2) // 3):
                raise ValueError(f"frame.image must be at most {BODY_CAMERA_MAX_BYTES // 1024} KiB decoded")
            try:
                image = base64.b64decode(image_b64, validate=True)
            except ValueError:
                raise ValueError("frame.image must be valid base64") from None
            if len(image) > BODY_CAMERA_MAX_BYTES:
                raise ValueError(f"frame.image must be at most {BODY_CAMERA_MAX_BYTES // 1024} KiB decoded")
        event = Frame(image=image, hint=hint if isinstance(hint, str) else None)
    if event is not None:
        if source is None:
            await friend.handle(event)
        else:
            await friend.handle_body(event, source)
