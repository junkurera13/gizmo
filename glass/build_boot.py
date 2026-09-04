#!/usr/bin/env python3
"""Build the device-playable boot flipbook from preserved source drawings."""

from __future__ import annotations

import argparse
import os
import shutil
import tempfile
from pathlib import Path

from PIL import Image, ImageChops


FPS = 8
DROP_DURATION_MS = 1_250
DROP_SLOTS = FPS * DROP_DURATION_MS // 1_000
ORIGINAL_SEQUENCE = (1, 1, 1, 2, 3, 4, 5, 6, 1, 1, 3, 4, 5, 7)


def shifted_entry(source: Image.Image, offset_y: int) -> Image.Image:
    frame = Image.new("RGB", source.size, "black")
    frame.paste(source, (0, offset_y))
    return frame


def build(root: Path) -> dict[str, object]:
    source_dir = root / "boot-source"
    output = root / "sprites/boot"
    sources: dict[int, Image.Image] = {}
    for number in set(ORIGINAL_SEQUENCE):
        path = source_dir / f"{number:02}.png"
        with Image.open(path) as opened:
            sources[number] = opened.convert("RGB")

    open_eye = sources[1]
    bounds = ImageChops.difference(open_eye, Image.new("RGB", open_eye.size, "black")).getbbox()
    if bounds is None:
        raise SystemExit("boot entry source is empty")
    start_offset = -bounds[3]

    temporary = Path(tempfile.mkdtemp(prefix=".boot-build-", dir=output.parent))
    backup = output.parent / ".boot-previous"
    try:
        frame_number = 1
        # At 8 fps, these ten slots occupy exactly 1.25 seconds. The old first
        # frame becomes the centered endpoint at t=1.25 s. Linear travel keeps
        # the low-frame-rate physical motion measured and avoids a sudden jump.
        for slot in range(DROP_SLOTS):
            progress = slot / DROP_SLOTS
            offset = round(start_offset * (1 - progress))
            shifted_entry(open_eye, offset).save(
                temporary / f"{frame_number:02}.png", format="PNG", optimize=True
            )
            frame_number += 1
        for source_number in ORIGINAL_SEQUENCE:
            sources[source_number].save(
                temporary / f"{frame_number:02}.png", format="PNG", optimize=True
            )
            frame_number += 1

        if backup.exists():
            shutil.rmtree(backup)
        if output.exists():
            os.replace(output, backup)
        os.replace(temporary, output)
        shutil.rmtree(backup, ignore_errors=True)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        if backup.exists() and not output.exists():
            os.replace(backup, output)
        raise

    return {
        "fps": FPS,
        "drop_duration_ms": DROP_DURATION_MS,
        "drop_slots": DROP_SLOTS,
        "original_slots": len(ORIGINAL_SEQUENCE),
        "total_slots": DROP_SLOTS + len(ORIGINAL_SEQUENCE),
        "start_offset_source_pixels": start_offset,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the Oddity cold-boot flipbook")
    parser.parse_args()
    result = build(Path(__file__).resolve().parent)
    print(result)


if __name__ == "__main__":
    main()
