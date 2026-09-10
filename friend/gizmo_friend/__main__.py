from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path

from gizmo_friend import default_data_dir
from gizmo_friend.body_protocol import Frame, Navigate, Power, Select, TextLine
from gizmo_friend.brain.show_budget import ShowBudget
from gizmo_friend.server import _device_id
from gizmo_friend.session import GizmoSession


def main() -> None:
    logging.basicConfig(format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("gizmo_friend").setLevel(logging.INFO)
    # Keys live in .env at the repo root; the simulator launches the brain from there.
    from dotenv import load_dotenv

    load_dotenv()
    parser = argparse.ArgumentParser(prog="gizmo", description="Gizmo brain")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("GIZMO_PORT") or os.environ.get("PORT") or "43147"),
    )
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--cli", action="store_true", help="keyboard only, no browser")
    args = parser.parse_args()
    data_dir = args.data_dir or default_data_dir()
    if args.cli:
        asyncio.run(_cli(data_dir))
        return
    import uvicorn

    from gizmo_friend.server import app_factory

    app = app_factory(data_dir)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


async def _cli(data_dir: Path) -> None:
    device_id = _device_id(os.environ.get("GIZMO_USER_ID", ""), "gizmo-local-user")
    friend = GizmoSession(
        data_dir / "devices" / device_id, user_id=device_id,
        show_budget=ShowBudget(data_dir),
    )
    queue = friend.subscribe()

    async def printer() -> None:
        while True:
            event = await queue.get()
            kind = event.get("type")
            if kind == "transcript" and event.get("role") == "gizmo":
                print(f"gizmo: {event.get('text')}")
            elif kind == "error":
                print(f"error: {event.get('message')}")
            elif kind in {"state", "interrupted"}:
                print(f"[{event.get('state')}]")
            elif kind in {"glass", "tool"}:
                print(json.dumps(event, ensure_ascii=False))

    task = asyncio.create_task(printer())
    print("Gizmo. Type a line. /power on  /power off  /select  /up  /down  /look <hint>  /quit")
    try:
        while True:
            line = await asyncio.to_thread(input, "> ")
            raw = line.strip()
            if raw in {"/quit", "/q"}:
                break
            if raw in {"/power on", "/on"}:
                await friend.handle(Power(on=True))
            elif raw in {"/power off", "/off"}:
                await friend.handle(Power(on=False))
            elif raw in {"/select", "/s", ""}:
                await friend.handle(Select())
            elif raw in {"/up", "/down"}:
                await friend.handle(Navigate(direction=raw.removeprefix("/")))
            elif raw.startswith("/look"):
                hint = raw[5:].strip() or "a pinecone on the table"
                await friend.handle(Frame(hint=hint))
                print(f"(camera) {hint}")
            else:
                await friend.handle(TextLine(text=raw))
                await asyncio.sleep(0.05)
    finally:
        task.cancel()
        await friend.close()


if __name__ == "__main__":
    main()
