#!/usr/bin/env python3
"""Export the current local boot and home art for one provisional panel profile."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import tempfile
import wave
from pathlib import Path

from PIL import features, Image, ImageDraw, ImageFont, ImageOps


SCHEMA_VERSION = 1
SPLASH_MINIMUM_MS = 3_800
CLOCK_CHARACTERS = "0123456789:"
CLOCK_WEIGHT = 500  # Outfit Medium; matches simulator GlassFonts.clock


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fit_on_black(source: Path, size: tuple[int, int]) -> Image.Image:
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGBA")
    image.thumbnail(size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", size, (0, 0, 0, 255))
    canvas.alpha_composite(image, ((size[0] - image.width) // 2, (size[1] - image.height) // 2))
    return canvas


def encode_jpeg(image: Image.Image, quality: int) -> bytes:
    import io

    output = io.BytesIO()
    image.convert("RGB").save(
        output,
        format="JPEG",
        quality=quality,
        optimize=True,
        progressive=False,
        subsampling=2,
    )
    return output.getvalue()


def write_bytes(root: Path, relative: str, data: bytes) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    os.chmod(target, 0o644)


def source_record(root: Path, path: Path) -> dict[str, object]:
    data = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": len(data),
        "sha256": sha256(data),
    }


def load_outfit_medium(font_path: Path, font_size: int) -> tuple[ImageFont.FreeTypeFont, dict[str, object]]:
    """Load Outfit with wght=500 (Medium). Tabular figures if the rasteriser supports them."""
    font = ImageFont.truetype(str(font_path), font_size)
    try:
        axes = font.get_variation_axes()
    except OSError as error:
        raise SystemExit(f"clock font is not a variable face: {error}") from error
    values: list[float] = []
    has_wght = False
    for axis in axes:
        name = axis["name"]
        if isinstance(name, bytes):
            name = name.decode("ascii")
        tag = name.replace(" ", "").lower()
        if tag in {"wght", "weight"}:
            values.append(float(CLOCK_WEIGHT))
            has_wght = True
        else:
            values.append(float(axis["default"]))
    if not has_wght:
        raise SystemExit("clock font has no wght axis; cannot bake Outfit Medium")
    font.set_variation_by_axes(values)
    return font, {
        "weight": CLOCK_WEIGHT,
        "weight_axis": "wght",
        "variation_applied": True,
        "axis_names": [
            (axis["name"].decode("ascii") if isinstance(axis["name"], bytes) else axis["name"])
            for axis in axes
        ],
    }


def draw_clock_glyph(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    character: str,
    font: ImageFont.FreeTypeFont,
) -> bool:
    """Draw one atlas glyph. Prefer OpenType `tnum` when raqm/Pillow exposes it."""
    if not features.check("raqm"):
        draw.text(xy, character, font=font, fill=255, anchor="ls")
        return False
    try:
        draw.text(xy, character, font=font, fill=255, anchor="ls", features=["tnum"])
        return True
    except (TypeError, ValueError, KeyError):
        draw.text(xy, character, font=font, fill=255, anchor="ls")
        return False


def export_clock_atlas(font_path: Path, panel_width: int) -> tuple[bytes, dict[str, object], ImageFont.FreeTypeFont]:
    import io

    font_size = max(8, round(panel_width * 0.044))
    font, variation = load_outfit_medium(font_path, font_size)
    ascent, descent = font.getmetrics()
    advances = [font.getlength(character, **({"features": ["tnum"]} if features.check("raqm") else {}))
                for character in CLOCK_CHARACTERS]
    cell_width = max(1, math.ceil(max(advances)))
    cell_height = max(1, ascent + descent)
    atlas = Image.new("L", (cell_width * len(CLOCK_CHARACTERS), cell_height), 0)
    draw = ImageDraw.Draw(atlas)
    tabular = True
    for index, (character, advance) in enumerate(zip(CLOCK_CHARACTERS, advances, strict=True)):
        x = index * cell_width + (cell_width - advance) / 2
        if not draw_clock_glyph(draw, (x, ascent), character, font):
            tabular = False
    output = io.BytesIO()
    atlas.save(output, format="PNG", optimize=True)
    metadata = {
        "path": "home/status/clock-atlas.png",
        "format": "L8 PNG alpha mask",
        "characters": CLOCK_CHARACTERS,
        "cell_width": cell_width,
        "cell_height": cell_height,
        "baseline": ascent,
        "font_size": font_size,
        "color": "#ffffff",
        "tabular_figures": tabular,
        **variation,
    }
    return output.getvalue(), metadata, font


def home_base(source: Path, size: tuple[int, int]) -> Image.Image:
    width, height = size
    with Image.open(source) as opened:
        character = ImageOps.exif_transpose(opened).convert("RGBA")
    box = (max(1, round(width * 0.66)), max(1, round(height * 0.78)))
    character.thumbnail(box, Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", size, (0, 0, 0, 255))
    x = (width - character.width) // 2 - round(width * 0.02)
    y = round((height - character.height) / 2 + height * 0.015)
    canvas.alpha_composite(character, (x, y))
    return canvas


def render_home_preview(
    base: Image.Image,
    font: ImageFont.FreeTypeFont,
    heart_sources: dict[str, Path],
    half_steps: int = 10,
) -> Image.Image:
    width, height = base.size
    preview = base.copy()
    draw = ImageDraw.Draw(preview)
    cap_height = max(1, round(height * 0.045))
    clock = "12:34"
    clock_width = math.ceil(draw.textlength(clock, font=font))
    heart_layout_side = cap_height
    heart_asset_side = max(1, round(cap_height * 96 / 78))
    heart_spacing = heart_layout_side * 0.2
    group_spacing = cap_height * 0.7
    hearts_width = 5 * heart_layout_side + 4 * heart_spacing
    group_width = clock_width + group_spacing + hearts_width
    top = height * 0.065
    x = (width - group_width) / 2
    heart_x = x + clock_width + group_spacing
    draw.text((x, top), clock, font=font, fill="white", anchor="lt")
    for index in range(5):
        filled = half_steps - index * 2
        state = "full" if filled >= 2 else "half" if filled == 1 else "empty"
        with Image.open(heart_sources[state]) as opened:
            heart = opened.convert("RGBA").resize(
                (heart_asset_side, heart_asset_side), Image.Resampling.LANCZOS
            )
        asset_x = round(heart_x + index * (heart_layout_side + heart_spacing) - (heart_asset_side - heart_layout_side) / 2)
        asset_y = round(top + cap_height - heart_asset_side)
        preview.alpha_composite(heart, (asset_x, asset_y))
    return preview


def write_preview(
    path: Path,
    boot_sequence: list[Image.Image],
    home: Image.Image,
) -> None:
    thumb = (128, 96)
    margin, label_height = 12, 22
    columns = 7
    rows = math.ceil(len(boot_sequence) / columns)
    grid_width = columns * thumb[0] + (columns + 1) * margin
    grid_height = rows * (thumb[1] + label_height) + (rows + 1) * margin
    width = max(grid_width, home.width + margin * 2)
    height = grid_height + home.height + label_height + margin * 2
    canvas = Image.new("RGB", (width, height), "#202124")
    draw = ImageDraw.Draw(canvas)
    for index, image in enumerate(boot_sequence):
        row, column = divmod(index, columns)
        x = margin + column * thumb[0]
        y = margin + row * (thumb[1] + label_height)
        frame = image.convert("RGB").resize(thumb, Image.Resampling.LANCZOS)
        canvas.paste(frame, (x, y))
        draw.text((x + 4, y + thumb[1] + 4), f"BOOT {index + 1:02}", fill="white")
    home_x = (width - home.width) // 2
    home_y = grid_height + margin
    canvas.paste(home.convert("RGB"), (home_x, home_y))
    draw.text((home_x, home_y + home.height + 5), "HOME — STATUS ONLY HERE", fill="white")
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path, format="PNG", optimize=True)


def export(args: argparse.Namespace) -> dict[str, object]:
    repository = Path(__file__).resolve().parents[2]
    glass = repository / "glass"
    output = args.output.expanduser().resolve()
    if output == repository or repository not in output.parents:
        raise SystemExit("output must be a directory inside this repository")
    if glass == output or glass in output.parents:
        raise SystemExit("output must not overwrite the source glass directory")
    if output.exists() and not args.force:
        raise SystemExit(f"output already exists: {output}; pass --force to replace this generated bundle")

    boot_dir = glass / "sprites/boot"
    boot_sources = sorted(boot_dir.glob("*.png"))
    sprite_config = json.loads((glass / "sprites/sprites.json").read_text())
    fps = int(sprite_config.get("boot", {}).get("fps", 8))
    minimum_duration_ms = int(sprite_config.get("boot", {}).get("minimum_duration_ms", SPLASH_MINIMUM_MS))
    if not boot_sources or fps <= 0 or minimum_duration_ms <= 0:
        raise SystemExit("the current boot source needs numbered frames, positive fps and duration")

    parent = output.parent
    parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=parent))
    size = (args.width, args.height)
    boot_images: list[Image.Image] = []
    sequence: list[str] = []
    sources = [source_record(repository, path) for path in boot_sources]
    try:
        for source in boot_sources:
            image = fit_on_black(source, size)
            boot_images.append(image)
            encoded = encode_jpeg(image, args.jpeg_quality)
            digest = sha256(encoded)
            relative = f"boot/frames/{digest[:16]}.jpg"
            if not (temporary / relative).exists():
                write_bytes(temporary, relative, encoded)
            sequence.append(relative)

        idle_dir = glass / "sprites/idle"
        idle_sources = sorted(idle_dir.glob("*.png"))
        idle_source = idle_sources[0]
        idle_config = sprite_config.get("idle", {})
        idle_frames: list[str] = []
        home: Image.Image | None = None
        for frame_index, idle_frame_source in enumerate(idle_sources):
            home_frame = home_base(idle_frame_source, size)
            if home is None:
                home = home_frame
            relative = f"home/idle/{frame_index:02d}.jpg"
            write_bytes(temporary, relative, encode_jpeg(home_frame, args.jpeg_quality))
            idle_frames.append(relative)
        # home/base.jpg stays the open pose; the camera backdrop and any consumer
        # that does not animate still reads it.
        write_bytes(temporary, "home/base.jpg", (temporary / idle_frames[0]).read_bytes())

        listening_dir = glass / "sprites/listening"
        listening_sources = sorted(listening_dir.glob("*.png"))
        listening_config = sprite_config.get("listening", {})
        listening_frames: list[str] = []
        for frame_index, listening_source in enumerate(listening_sources):
            listening_frame = home_base(listening_source, size)
            relative = f"home/listening/{frame_index:02d}.jpg"
            write_bytes(temporary, relative, encode_jpeg(listening_frame, args.jpeg_quality))
            listening_frames.append(relative)

        font_path = glass / "fonts/Outfit[wght].ttf"
        atlas, clock_metadata, clock_font = export_clock_atlas(font_path, args.width)
        write_bytes(temporary, str(clock_metadata["path"]), atlas)

        # Heart size tracks the panel, not the clock face, so the time can be
        # tuned without dragging the battery glyphs with it.
        cap_height = max(1, round(args.height * 0.045))
        heart_asset_side = max(1, round(cap_height * 96 / 78))
        heart_sources = {
            state: glass / f"sprites/hearts/{state}.png"
            for state in ("empty", "half", "full")
        }
        heart_paths: dict[str, str] = {}
        for state, source in heart_sources.items():
            with Image.open(source) as opened:
                heart = opened.convert("RGBA").resize(
                    (heart_asset_side, heart_asset_side), Image.Resampling.LANCZOS
                )
            relative = f"home/status/heart-{state}.png"
            heart.save(temporary / relative, format="PNG", optimize=True)
            heart_paths[state] = relative

        chime_source = glass / "sounds/boot.wav"
        with wave.open(str(chime_source), "rb") as audio:
            audio_metadata = {
                "path": "audio/boot.wav",
                "format": "PCM16 little-endian WAV",
                "sample_rate_hz": audio.getframerate(),
                "channels": audio.getnchannels(),
                "sample_width_bytes": audio.getsampwidth(),
                "frames": audio.getnframes(),
                "duration_ms": round(audio.getnframes() * 1000 / audio.getframerate()),
            }
        if (audio_metadata["sample_rate_hz"], audio_metadata["channels"], audio_metadata["sample_width_bytes"]) != (24_000, 1, 2):
            raise SystemExit("boot.wav must be 24 kHz mono PCM16")
        write_bytes(temporary, "audio/boot.wav", chime_source.read_bytes())

        wordmark_index = len(sequence) - 1
        frame_period_ms = round(1000 / fps)
        files: dict[str, dict[str, object]] = {}
        for path in sorted(item for item in temporary.rglob("*") if item.is_file()):
            data = path.read_bytes()
            files[path.relative_to(temporary).as_posix()] = {
                "bytes": len(data),
                "sha256": sha256(data),
            }

        manifest: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "profile": {
                "width": args.width,
                "height": args.height,
                "provisional": True,
                "background": "#000000",
                "frame_encoding": "baseline JPEG",
            },
            "boot": {
                "fps": fps,
                "frame_period_ms": frame_period_ms,
                "minimum_duration_ms": minimum_duration_ms,
                "sequence": sequence,
                "frame_slots": len(sequence),
                "unique_frame_files": len(set(sequence)),
                "wordmark_frame": wordmark_index + 1,
                "chime_at_ms": round(wordmark_index * 1000 / fps),
                "entrance": sprite_config.get("boot", {}).get("entrance"),
                "chime": audio_metadata,
            },
            "home": {
                "base": "home/base.jpg",
                "idle": {
                    "frames": idle_frames,
                    "period_ms": int(idle_config.get("period_ms", 110)),
                    "slots": idle_config.get("slots") or [0],
                },
                "listening": {
                    "frames": listening_frames,
                    "period_ms": int(listening_config.get("period_ms", 130)),
                    "slots": listening_config.get("slots") or [0],
                },
                "status_scope": "home_only",
                "status_top_fraction": 0.065,
                "clock": clock_metadata,
                "battery": {
                    "half_steps": 10,
                    "hearts": 5,
                    "layout_side": cap_height,
                    "asset_side": heart_asset_side,
                    "paths": heart_paths,
                },
            },
            "files": files,
            "total_asset_bytes": sum(int(record["bytes"]) for record in files.values()),
            "sources": {
                "boot": sources,
                "home": source_record(repository, idle_source),
                "hearts": {
                    state: source_record(repository, source)
                    for state, source in heart_sources.items()
                },
                "clock_font": source_record(repository, font_path),
                "chime": source_record(repository, chime_source),
            },
        }
        (temporary / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        os.chmod(temporary / "manifest.json", 0o644)

        if output.exists():
            shutil.rmtree(output)
        os.replace(temporary, output)
        if args.preview:
            preview_home = render_home_preview(home, clock_font, heart_sources)
            write_preview(args.preview.expanduser().resolve(), boot_images, preview_home)
        return manifest
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Export offline Gizmo boot/home assets")
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--jpeg-quality", type=int, default=90)
    parser.add_argument("--preview", type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if not (1 <= args.width <= 1024 and 1 <= args.height <= 1024):
        parser.error("width and height must be 1–1024 pixels")
    if not (60 <= args.jpeg_quality <= 95):
        parser.error("JPEG quality must be 60–95")
    manifest = export(args)
    print(json.dumps({
        "status": "exported",
        "output": str(args.output.expanduser().resolve()),
        "profile": manifest["profile"],
        "frame_slots": manifest["boot"]["frame_slots"],
        "unique_frame_files": manifest["boot"]["unique_frame_files"],
        "total_asset_bytes": manifest["total_asset_bytes"],
    }, indent=2))


if __name__ == "__main__":
    main()
