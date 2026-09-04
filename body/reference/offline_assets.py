#!/usr/bin/env python3
"""Validate and exercise an exported boot/home bundle without a brain connection."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import inspect
import json
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from PIL import Image


Callback = Callable[[dict[str, Any]], object | Awaitable[object]]


class AssetBundleError(RuntimeError):
    pass


async def invoke(callback: Callback | None, event: dict[str, Any]) -> None:
    if callback is None:
        return
    result = callback(event)
    if inspect.isawaitable(result):
        await result


class OfflineAssetBundle:
    def __init__(self, directory: Path) -> None:
        self.directory = directory.resolve()
        try:
            self.manifest = json.loads((self.directory / "manifest.json").read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise AssetBundleError("offline asset manifest is missing or invalid") from error
        self._validate()

    def path(self, relative: str) -> Path:
        candidate = (self.directory / relative).resolve()
        if self.directory not in candidate.parents:
            raise AssetBundleError("asset path escapes the bundle")
        return candidate

    def _validate(self) -> None:
        manifest = self.manifest
        if manifest.get("schema_version") != 1:
            raise AssetBundleError("unsupported offline asset schema")
        profile = manifest.get("profile")
        if not isinstance(profile, dict) or not all(
            isinstance(profile.get(key), int) and profile[key] > 0 for key in ("width", "height")
        ):
            raise AssetBundleError("bundle profile is invalid")
        files = manifest.get("files")
        if not isinstance(files, dict) or not files:
            raise AssetBundleError("bundle file inventory is empty")
        for relative, record in files.items():
            if not isinstance(relative, str) or not isinstance(record, dict):
                raise AssetBundleError("bundle file inventory is invalid")
            data = self.path(relative).read_bytes()
            if len(data) != record.get("bytes") or hashlib.sha256(data).hexdigest() != record.get("sha256"):
                raise AssetBundleError(f"asset integrity failed: {relative}")
        boot = manifest.get("boot")
        if not isinstance(boot, dict) or boot.get("frame_slots") != len(boot.get("sequence", [])):
            raise AssetBundleError("boot sequence is invalid")
        if not boot.get("sequence") or not all(path in files for path in boot["sequence"]):
            raise AssetBundleError("boot sequence references a missing frame")
        home = manifest.get("home")
        if not isinstance(home, dict) or home.get("base") not in files:
            raise AssetBundleError("home base is missing")
        chime = boot.get("chime")
        if not isinstance(chime, dict) or chime.get("path") not in files:
            raise AssetBundleError("boot chime is missing")

    def _read_frame(self, relative: str) -> tuple[int, tuple[int, int]]:
        path = self.path(relative)
        data = path.read_bytes()
        with Image.open(path) as image:
            dimensions = image.size
        expected = self.manifest["profile"]
        if dimensions != (expected["width"], expected["height"]):
            raise AssetBundleError(f"asset has wrong dimensions: {relative}")
        return len(data), dimensions

    async def cold_boot(
        self,
        on_frame: Callback | None = None,
        on_chime: Callback | None = None,
        on_home: Callback | None = None,
        *,
        realtime: bool = True,
    ) -> dict[str, Any]:
        boot = self.manifest["boot"]
        period = boot["frame_period_ms"] / 1000
        started = time.monotonic()
        decoded = 0
        maximum_resident_bytes = 0
        last_frame: str | None = None
        for index, relative in enumerate(boot["sequence"]):
            if relative != last_frame:
                size, dimensions = self._read_frame(relative)
                decoded += 1
                maximum_resident_bytes = max(maximum_resident_bytes, size)
                await invoke(on_frame, {
                    "type": "local_glass",
                    "state": "boot",
                    "slot": index + 1,
                    "asset": relative,
                    "bytes": size,
                    "width": dimensions[0],
                    "height": dimensions[1],
                })
                last_frame = relative
            if index + 1 == boot["wordmark_frame"]:
                chime = boot["chime"]
                await invoke(on_chime, {
                    "type": "local_audio",
                    "state": "boot",
                    "at_ms": boot["chime_at_ms"],
                    "asset": chime["path"],
                    "bytes": self.path(chime["path"]).stat().st_size,
                })
            if realtime:
                target = started + (index + 1) * period
                await asyncio.sleep(max(0, target - time.monotonic()))

        if realtime:
            target = started + boot["minimum_duration_ms"] / 1000
            await asyncio.sleep(max(0, target - time.monotonic()))
        home = self.manifest["home"]["base"]
        home_bytes, dimensions = self._read_frame(home)
        maximum_resident_bytes = max(maximum_resident_bytes, home_bytes)
        await invoke(on_home, {
            "type": "local_glass",
            "state": "home",
            "asset": home,
            "bytes": home_bytes,
            "width": dimensions[0],
            "height": dimensions[1],
            "status_scope": self.manifest["home"]["status_scope"],
        })
        return {
            "frame_slots": boot["frame_slots"],
            "frame_decodes": decoded,
            "unique_frame_files": boot["unique_frame_files"],
            "minimum_duration_ms": boot["minimum_duration_ms"],
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "maximum_resident_encoded_frame_bytes": maximum_resident_bytes,
            "home": home,
        }


async def run(args: argparse.Namespace) -> None:
    bundle = OfflineAssetBundle(args.bundle)

    def report(event: dict[str, Any]) -> None:
        print(json.dumps(event, separators=(",", ":")), flush=True)

    result = await bundle.cold_boot(report, report, report, realtime=args.realtime)
    print(json.dumps({"type": "offline_boot_complete", **result}, separators=(",", ":")))


def main() -> None:
    parser = argparse.ArgumentParser(description="Exercise a local Gizmo boot/home asset bundle")
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--realtime", action="store_true", help="honor the bundle's full cold-boot timing")
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except AssetBundleError as error:
        raise SystemExit(f"offline assets: {error}") from error


if __name__ == "__main__":
    main()
