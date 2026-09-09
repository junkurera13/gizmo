"""Persistent Show masters and sized JPEG/MJPEG caches, independent of generation."""

from __future__ import annotations

import io
import fcntl
import hashlib
import json
import os
import re
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from PIL import Image, ImageOps

from gizmo_friend.brain.images import ConjuredStill
from gizmo_friend.brain.clips import ConjuredClip
from gizmo_friend.brain.show_media import MAX_FRAME_DIMENSION, MAX_FRAME_FPS, encode_mjpeg, strip_audio

MAX_IMAGE_DIMENSION = 2048
_SHOW_ID = re.compile(r"[0-9a-f]{32}")


def valid_device_id(value: str) -> bool:
    """Match the body identity alphabet, excluding filesystem dot segments."""
    return (
        0 < len(value) <= 64
        and value not in {".", ".."}
        and all(character.isalnum() or character in "-_." for character in value)
    )


@dataclass(frozen=True)
class StoredShow:
    id: str
    device_id: str
    still_path: Path
    metadata_path: Path

    @property
    def still_url(self) -> str:
        return f"/shows/{quote(self.device_id, safe='')}/{self.id}.jpg"

    @property
    def clip_path(self) -> Path:
        return self.still_path.with_suffix(".mp4")

    @property
    def clip_url(self) -> str:
        return self.still_url.removesuffix(".jpg") + ".mp4"

    @property
    def frames_url(self) -> str:
        return self.still_url.removesuffix(".jpg") + ".mjpeg"


@dataclass(frozen=True)
class StoredFrames:
    path: Path
    width: int
    height: int
    fps: int
    frame_count: int


def _atomic_write(path: Path, data: bytes) -> None:
    """Readers see either the old complete file or the new complete file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class ShowStore:
    """One device's shows. Call synchronous disk/image work outside the event loop."""

    def __init__(self, device_directory: Path, *, device_id: str) -> None:
        if not valid_device_id(device_id):
            raise ValueError("invalid device id")
        self.directory = Path(device_directory) / "shows"
        self.device_id = device_id

    @contextmanager
    def _lock(self, show_id: str, name: str):
        """Serialize a cache fill across threads/processes without a lock registry."""
        directory = self.directory / ".cache" / show_id
        directory.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(directory / f".{name}.lock", os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(descriptor, "a+b") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield directory
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def save(
        self,
        still: ConjuredStill,
        *,
        session_id: str,
        motion: str | None = None,
    ) -> StoredShow:
        show_id = uuid.uuid4().hex
        result = StoredShow(
            id=show_id,
            device_id=self.device_id,
            still_path=self.directory / f"{show_id}.jpg",
            metadata_path=self.directory / f"{show_id}.json",
        )
        metadata = {
            "id": show_id,
            "device": self.device_id,
            "subject": still.subject,
            "motion": motion,
            "prompts": {"image": still.prompt},
            "created": datetime.now(UTC).isoformat(),
            "session": session_id,
            "model": still.model,
            "width": still.width,
            "height": still.height,
            "source_width": still.source_width,
            "source_height": still.source_height,
            "generation_latency_seconds": still.latency_seconds,
            "generation_timings": still.timings,
        }
        encoded = (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        _atomic_write(result.still_path, still.jpeg)
        try:
            # The sidecar is the commit marker: an unfinished save is never served.
            _atomic_write(result.metadata_path, encoded)
        except BaseException:
            result.still_path.unlink(missing_ok=True)
            raise
        return result

    def still_path(self, show_id: str, *, width: int | None = None, height: int | None = None) -> Path:
        if not _SHOW_ID.fullmatch(show_id):
            raise FileNotFoundError("show not found")
        if (width is None) != (height is None):
            raise ValueError("w and h must be supplied together")
        if width is not None and height is not None:
            if not (1 <= width <= MAX_IMAGE_DIMENSION and 1 <= height <= MAX_IMAGE_DIMENSION):
                raise ValueError(f"w and h must be between 1 and {MAX_IMAGE_DIMENSION}")

        source = self.directory / f"{show_id}.jpg"
        sidecar = self.directory / f"{show_id}.json"
        if not source.is_file() or not sidecar.is_file():
            raise FileNotFoundError("show not found")
        if width is None or height is None:
            return source

        cached = self.directory / ".cache" / show_id / f"{width}x{height}.jpg"
        if cached.is_file():
            return cached
        with Image.open(source) as original:
            image = ImageOps.fit(
                ImageOps.exif_transpose(original).convert("RGB"),
                (width, height),
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            )
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=92, subsampling=0)
        # Concurrent first requests may resize twice; atomic replacement keeps
        # either result complete, without an unbounded per-size lock registry.
        _atomic_write(cached, output.getvalue())
        return cached

    def save_clip(self, show_id: str, clip: ConjuredClip) -> StoredShow:
        """Attach one immutable silent clip to its exact source still."""
        source = self.still_path(show_id)
        if hashlib.sha256(source.read_bytes()).hexdigest() != clip.source_image_sha256:
            raise ValueError("clip does not belong to this still")
        result = StoredShow(show_id, self.device_id, source, source.with_suffix(".json"))
        with self._lock(show_id, "clip"):
            metadata = json.loads(result.metadata_path.read_text())
            existing = metadata.get("clip")
            if existing:
                if existing.get("request_id") == clip.request_id:
                    self.clip_path(show_id)
                    return result
                raise ValueError("show already has a clip")
            with tempfile.TemporaryDirectory(prefix=".clip-", dir=self.directory) as temporary:
                raw = Path(temporary) / "source.mp4"
                output = Path(temporary) / "silent.mp4"
                _atomic_write(raw, clip.mp4)
                frame_count = strip_audio(raw, output)
                metadata["motion"] = clip.motion
                metadata["prompts"]["video"] = clip.prompt
                metadata["clip"] = {
                    "model": clip.model,
                    "request_id": clip.request_id,
                    "source_image_sha256": clip.source_image_sha256,
                    "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                    "created": datetime.now(UTC).isoformat(),
                    "generation_latency_seconds": clip.latency_seconds,
                    "timings": clip.timings,
                    "expanded_prompt": clip.expanded_prompt,
                    "frame_count": frame_count,
                    "bytes": output.stat().st_size,
                    "audio_stripped": True,
                }
                os.replace(output, result.clip_path)
                try:
                    _atomic_write(result.metadata_path, (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode())
                except BaseException:
                    result.clip_path.unlink(missing_ok=True)
                    raise
        return result

    def clip_path(self, show_id: str) -> Path:
        source = self.still_path(show_id)
        path = source.with_suffix(".mp4")
        metadata = json.loads(source.with_suffix(".json").read_text())
        if not path.is_file() or not isinstance(metadata.get("clip"), dict):
            raise FileNotFoundError("clip not found")
        return path

    def mjpeg(self, show_id: str, *, width: int = 320, height: int = 240, fps: int = 12) -> StoredFrames:
        if not (1 <= width <= MAX_FRAME_DIMENSION and 1 <= height <= MAX_FRAME_DIMENSION):
            raise ValueError(f"w and h must be between 1 and {MAX_FRAME_DIMENSION}")
        if not 1 <= fps <= MAX_FRAME_FPS:
            raise ValueError(f"fps must be between 1 and {MAX_FRAME_FPS}")
        source = self.clip_path(show_id)
        name = f"{width}x{height}@{fps}fps"
        directory = self.directory / ".cache" / show_id
        cached = directory / f"{name}.mjpeg"
        sidecar = directory / f"{name}.mjpeg.json"

        def ready() -> StoredFrames | None:
            if cached.is_file() and sidecar.is_file():
                try:
                    metadata = json.loads(sidecar.read_text())
                    if metadata["bytes"] == cached.stat().st_size and metadata["frame_count"] > 0:
                        return StoredFrames(cached, width, height, fps, metadata["frame_count"])
                except (OSError, ValueError, KeyError, TypeError):
                    pass
            return None

        if result := ready():
            return result
        with self._lock(show_id, name):
            if result := ready():
                return result
            with tempfile.TemporaryDirectory(prefix=".frames-", dir=directory) as temporary:
                output = Path(temporary) / "frames.mjpeg"
                count = encode_mjpeg(source, output, width=width, height=height, fps=fps)
                metadata = {"width": width, "height": height, "fps": fps,
                            "frame_count": count, "bytes": output.stat().st_size}
                os.replace(output, cached)
                try:
                    _atomic_write(sidecar, (json.dumps(metadata) + "\n").encode())
                except BaseException:
                    cached.unlink(missing_ok=True)
                    raise
        return StoredFrames(cached, width, height, fps, count)
