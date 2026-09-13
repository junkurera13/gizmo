"""Private film workbench. Provider credentials and media ownership stay on the brain."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from gizmo_friend.brain.show_budget import ShowBudget
from gizmo_friend.cinema.runtime import CinemaSession

COOKIE = "gizmo_cinema"
IDENTITY = re.compile(r"[0-9a-f]{32}")


class FilmBudget(ShowBudget):
    counter = "films"
    ledger_name = "film-usage"
    device_default = 8
    global_default = 30
    environment_name = "GIZMO_DAILY_FILM_LIMIT"
    device_environment_name = "GIZMO_DAILY_FILM_DEVICE_LIMIT"


def router(root: Path, static: Path):
    api = APIRouter()
    credentials: set[str] = set()
    active: dict[str, CinemaSession] = {}
    budget = FilmBudget(root)
    # The page is served no-store while /static responses are heuristically
    # cached — stamp the asset URLs so a fresh page can never pair with
    # another version's css/js (a rolling deploy splits them otherwise).
    asset_version = hashlib.sha256(
        (static / "cinema.css").read_bytes()
        + (static / "cinema.js").read_bytes()
    ).hexdigest()[:12]

    def same_origin(connection):
        origin = urlsplit(connection.headers.get("origin", ""))
        return origin.scheme in {
            "http",
            "https",
        } and origin.netloc == connection.headers.get("host")

    def identity(connection):
        values = (
            connection.query_params.get("key", ""),
            connection.headers.get("x-gizmo-cinema", ""),
            connection.cookies.get(COOKIE, ""),
        )
        for value in values:
            if IDENTITY.fullmatch(value) and value in credentials:
                return value
        return ""

    @api.get("/cinema")
    async def page():
        html = (static / "cinema.html").read_text()
        for name in ("cinema.css", "cinema.js"):
            html = html.replace(
                f"/static/{name}", f"/static/{name}?v={asset_version}"
            )
        return HTMLResponse(
            html,
            headers={
                "Cache-Control": "no-store",
                "X-Robots-Tag": "noindex",
                "Content-Security-Policy": "default-src 'self'; connect-src 'self' ws: wss:; media-src 'self' blob:; img-src 'self' data:; style-src 'self'; script-src 'self'; font-src 'self'; frame-ancestors 'self' https://oddware.xyz https://*.oddware.xyz https://*.vercel.app http://localhost:* http://127.0.0.1:*",
                "Permissions-Policy": "microphone=(self), camera=()",
            },
        )

    @api.post("/cinema/session")
    async def provision(request: Request):
        if not same_origin(request):
            raise HTTPException(403, "Open this page directly to begin.")
        cloud = bool(os.environ.get("RAILWAY_ENVIRONMENT_ID"))
        enabled = os.environ.get("GIZMO_DIRECTOR_ENABLED", "").lower() in {"1", "true"}
        token = os.environ.get("GIZMO_DIRECTOR_TOKEN", "")
        local = (
            request.client and request.client.host in {"127.0.0.1", "::1"} and not cloud
        )
        if not local and not enabled:
            raise HTTPException(503, "The film preview isn't open yet.")
        if (
            not local
            and token
            and not hmac.compare_digest(
                request.headers.get("x-gizmo-access", "").encode(), token.encode()
            )
        ):
            raise HTTPException(401, "Access code required.")
        if not os.environ.get("FAL_KEY") or not os.environ.get("GEMINI_API_KEY"):
            raise HTTPException(503, "The film providers aren't connected.")
        key = identity(request) or secrets.token_hex(16)
        if len(credentials) >= 64 and key not in credentials:
            raise HTTPException(503, "The preview is full.")
        credentials.add(key)
        response = JSONResponse({"ready": True, "key": key})
        response.set_cookie(
            COOKIE,
            key,
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="strict",
            path="/cinema",
            max_age=3600,
        )
        return response

    @api.post("/cinema/offer")
    async def offer(request: Request):
        key = identity(request)
        if not key or not same_origin(request) or key not in active:
            raise HTTPException(403)
        raw = await request.body()
        if len(raw) > 100_000:
            raise HTTPException(413)
        payload = json.loads(raw)
        if not isinstance(payload.get("sdp"), str) or not isinstance(
            payload.get("revision"), int
        ):
            raise HTTPException(400)
        try:
            return await active[key].offer(
                payload["sdp"],
                payload["revision"],
                local=not os.environ.get("RAILWAY_ENVIRONMENT_ID")
                and request.client.host in {"127.0.0.1", "::1"},
            )
        except (ValueError, RuntimeError):
            raise HTTPException(409, "That film has already ended.") from None

    @api.websocket("/cinema/ws")
    async def websocket(socket: WebSocket):
        key = identity(socket)
        if not key or not same_origin(socket) or key in active or len(active) >= 3:
            await socket.close(code=1008)
            return
        await socket.accept()
        lock = asyncio.Lock()

        async def emit(event):
            async with lock:
                await socket.send_json(event)

        session = CinemaSession(root / "cinema" / key, os.environ["FAL_KEY"], emit)
        active[key] = session
        transcription = None

        async def ask(text, request_id=None):
            if not await asyncio.to_thread(budget.reserve, key):
                await emit(
                    {
                        "type": "error",
                        "message": "That's today's film limit. Come back tomorrow.",
                    }
                )
                return
            await session.ask(text, request_id=request_id)

        async def transcribe(data, mime, revision, request_id):
            try:
                text = await session.maker.transcribe(data, mime)
                if revision != session.revision:
                    return
                await emit({"type": "heard", "text": text, "request_id": request_id})
                if text:
                    await ask(text, request_id)
                else:
                    await emit(
                        {
                            "type": "status",
                            "phase": "paused",
                            "message": "I didn't catch that. Try again.",
                        }
                    )
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - isolate a provider or socket failure
                await emit(
                    {
                        "type": "error",
                        "message": "I couldn't hear that. You can type it instead.",
                    }
                )

        try:
            await emit({"type": "hello"})
            while True:
                raw = await socket.receive_text()
                if len(raw) > 3_000_000:
                    await socket.close(code=1009)
                    break
                value = json.loads(raw)
                kind = value.get("type")
                if kind in {"ask", "interrupt", "audio"} and transcription:
                    transcription.cancel()
                    await asyncio.gather(transcription, return_exceptions=True)
                    transcription = None
                if kind == "ask" and isinstance(value.get("text"), str):
                    await ask(value["text"], value.get("request_id"))
                elif kind == "interrupt":
                    await session.interrupt()
                    await emit(
                        {
                            "type": "paused",
                            "revision": session.revision,
                            "request_id": value.get("request_id"),
                        }
                    )
                elif kind == "finished":
                    await session.finish(value.get("revision"))
                elif kind == "audio":
                    mime = value.get("mime", "")
                    if mime not in {
                        "audio/webm",
                        "audio/webm;codecs=opus",
                        "audio/mp4",
                        "audio/ogg;codecs=opus",
                    }:
                        continue
                    try:
                        data = base64.b64decode(value.get("data", ""), validate=True)
                    except (ValueError, TypeError):
                        continue
                    if not 100 <= len(data) <= 2_000_000:
                        continue
                    transcription = asyncio.create_task(
                        transcribe(
                            data, mime, session.revision, value.get("request_id")
                        )
                    )
        except (WebSocketDisconnect, ValueError, RuntimeError):
            pass
        finally:
            if transcription:
                transcription.cancel()
                await asyncio.gather(transcription, return_exceptions=True)
            await session.close()
            active.pop(key, None)

    return api
