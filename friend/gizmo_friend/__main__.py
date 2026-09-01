from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from gizmo_friend import default_data_dir
from gizmo_friend.session import Friend


def main() -> None:
    # Keys live in .env at the repo root; the simulator launches Friend from there.
    from dotenv import load_dotenv

    load_dotenv()
    parser = argparse.ArgumentParser(prog="gizmo", description="Gizmo Friend — laptop brain")
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
    friend = Friend(data_dir)
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

    task = asyncio.create_task(printer())
    print("Gizmo Friend. Type a line. /power on  /power off  /select  /up  /down  /look <hint>  /quit")
    print(f"memory: {data_dir / 'gizmo.db'}")
    print(f"talk path: {friend.transport_name}")
    try:
        while True:
            line = await asyncio.to_thread(input, "> ")
            raw = line.strip()
            if raw in {"/quit", "/q"}:
                break
            if raw in {"/power on", "/on"}:
                from gizmo_friend.body_protocol import Power

                await friend.handle(Power(on=True))
                continue
            if raw in {"/power off", "/off"}:
                from gizmo_friend.body_protocol import Power

                await friend.handle(Power(on=False))
                continue
            if raw in {"/select", "/s", ""}:
                from gizmo_friend.body_protocol import Select

                await friend.handle(Select())
                continue
            if raw in {"/up", "/down"}:
                from gizmo_friend.body_protocol import Navigate

                await friend.handle(Navigate(direction=raw.removeprefix("/")))
                continue
            if raw.startswith("/look"):
                hint = raw[5:].strip() or "a pinecone on the table"
                from gizmo_friend.body_protocol import Frame

                await friend.handle(Frame(hint=hint))
                print(f"(camera) {hint}")
                continue
            from gizmo_friend.body_protocol import TextLine

            await friend.handle(TextLine(text=raw))
            await asyncio.sleep(0.05)
    finally:
        task.cancel()
        await friend.close()


if __name__ == "__main__":
    main()
