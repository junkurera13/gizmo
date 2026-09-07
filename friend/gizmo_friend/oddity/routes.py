from __future__ import annotations

import asyncio
import base64
import hmac
import json
import os
import re
import secrets
import time
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

from gizmo_friend.brain.show_budget import OddityTurnBudget
from gizmo_friend.oddity.runtime import ExperienceSession, MEDIA_NAME

COOKIE = "oddity_session"
IDENTITY = re.compile(r"[0-9a-f]{32}")


def router(root: Path, static: Path) -> APIRouter:
    api = APIRouter()
    connected: set[str] = set()
    turn_budget = OddityTurnBudget(root)

    def identity(connection) -> str:
        values = (
            connection.query_params.get("session", ""),
            connection.headers.get("x-oddity-session", ""),
            connection.cookies.get(COOKIE, ""),
        )
        for value in values:
            if IDENTITY.fullmatch(value) and (root / "oddity" / value / "session.json").exists():
                return value
        return ""

    def create_session() -> str:
        session_id = secrets.token_hex(16)
        directory = root / "oddity" / session_id
        directory.mkdir(parents=True, exist_ok=False)
        (directory / "session.json").write_text("{}")
        return session_id

    @api.get("/oddity")
    async def index():
        response = FileResponse(static / "oddity.html", headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": (
                "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
                "connect-src 'self' ws: wss:; style-src 'self'; script-src 'self'; font-src 'self'; "
                "frame-ancestors 'self' https://oddware.xyz https://*.oddware.xyz "
                "https://*.vercel.app http://localhost:* http://127.0.0.1:*"
            ),
            "Permissions-Policy": "camera=(), microphone=(self)",
            "Referrer-Policy": "no-referrer",
            "X-Robots-Tag": "noindex, nofollow",
        })
        return response

    @api.post("/oddity/session")
    async def provision(request: Request):
        preview_token = os.environ.get("ODDITY_PREVIEW_TOKEN", "").strip()
        if os.environ.get("RAILWAY_ENVIRONMENT_ID") and not preview_token:
            raise HTTPException(503, "preview access is not configured")
        provided = request.headers.get("x-oddity-preview", "")
        if preview_token and not hmac.compare_digest(provided.encode(), preview_token.encode()):
            raise HTTPException(401, "preview code required")
        session_id = identity(request) or create_session()
        response = JSONResponse({"session": session_id}, headers={"Cache-Control": "no-store"})
        response.set_cookie(COOKIE, session_id, httponly=True, samesite="strict",
                            secure=request.url.scheme == "https", max_age=60 * 60 * 24 * 30, path="/oddity")
        return response

    @api.get("/oddity/media/{name}")
    async def media(request: Request, name: str):
        session_id = identity(request)
        if not session_id or not MEDIA_NAME.fullmatch(name):
            raise HTTPException(404)
        path = root / "oddity" / session_id / name
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, headers={"Cache-Control": "private, max-age=86400, immutable",
                                           "X-Content-Type-Options": "nosniff", "Vary": "Cookie"})

    @api.websocket("/oddity/ws")
    async def websocket(socket: WebSocket):
        session_id = identity(socket)
        origin = urlsplit(socket.headers.get("origin", ""))
        if (not session_id or origin.scheme not in {"http", "https"} or
                origin.netloc != socket.headers.get("host")):
            await socket.close(code=1008)
            return
        await socket.accept()
        if session_id in connected:
            await socket.send_json({"type": "error", "message": "Oddity is already open in another tab. Close that tab, then reconnect."})
            await socket.close(code=1008)
            return
        friend = None
        connected.add(session_id)
        try:
            friend = ExperienceSession(root, session_id, socket.send_json)
            await socket.send_json({"type": "hello", "history": friend.history,
                                    "library": friend.library, "current": friend.current})
            await friend.load_memory()
            last_request = 0.0
            while True:
                raw = await socket.receive_text()
                if len(raw) > 2_100_000:
                    await socket.send_json({"type": "error", "message": "That recording is too long. Keep it under 45 seconds."})
                    continue
                try:
                    message = json.loads(raw)
                    if not isinstance(message, dict):
                        raise ValueError()
                    kind = message.get("type")
                    if kind == "interrupt":
                        await friend.stop()
                        await socket.send_json({"type": "interrupted"})
                    elif kind == "playback":
                        await friend.playback(message)
                    elif kind in {"home", "revisit"}:
                        await friend.stop()
                        friend.revisit(message.get("id") if kind == "revisit" else None)
                    elif kind in {"text", "recording"}:
                        if time.monotonic() - last_request < 2:
                            await socket.send_json({"type": "error", "message": "Give that thought a moment, then try again."})
                            continue
                        last_request = time.monotonic()
                        if not await asyncio.to_thread(turn_budget.reserve, "oddity-" + session_id):
                            await socket.send_json({"type": "error", "message": "Today's preview allowance is used up. Come back tomorrow."})
                            continue
                        if kind == "text":
                            text = message.get("text", "")
                            if not isinstance(text, str) or not text.strip() or len(text) > 3000:
                                raise ValueError()
                            await friend.begin(text)
                        else:
                            mime = str(message.get("mime", "")).split(";", 1)[0]
                            if mime not in {"audio/webm", "audio/mp4", "audio/ogg", "audio/wav"}:
                                raise ValueError()
                            audio = base64.b64decode(message.get("audio", ""), validate=True)
                            if not 100 < len(audio) <= 1_500_000:
                                raise ValueError()
                            await friend.begin(audio=audio, mime=mime)
                except (ValueError, TypeError, KeyError):
                    await socket.send_json({"type": "error", "message": "That input couldn't be read. Try again."})
        except WebSocketDisconnect:
            pass
        except RuntimeError as error:
            if friend is None:
                await socket.send_json({"type": "error", "message": str(error)})
            else:
                raise
        finally:
            connected.discard(session_id)
            if friend:
                await friend.close()

    return api
