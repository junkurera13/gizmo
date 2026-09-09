"""Bounded, local FFmpeg work for saved Show clips."""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path

import imageio_ffmpeg

MAX_FRAME_DIMENSION = 1024
MAX_FRAME_FPS = 24
TRANSCODE_TIMEOUT_SECONDS = 30
MAX_MEDIA_BYTES = 64 * 1024 * 1024
_WORKERS = threading.BoundedSemaphore(2)


class MediaError(RuntimeError):
    """The saved media could not be processed; retain the original still."""


def _ffmpeg(source: Path, target: Path | str, output_arguments: list[str]) -> int:
    """Run bounded FFmpeg work and read its progress counter, when available."""
    try:
        executable = imageio_ffmpeg.get_ffmpeg_exe()
        with _WORKERS:
            result = subprocess.run(
                [
                    executable, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                    "-protocol_whitelist", "file,pipe", "-threads", "1",
                    "-i", str(source), "-map", "0:v:0", "-an", "-sn", "-dn",
                    "-map_metadata", "-1", "-threads", "1", "-filter_threads", "1",
                    "-progress", "pipe:1", *output_arguments, str(target),
                ],
                capture_output=True, text=True, check=True,
                timeout=TRANSCODE_TIMEOUT_SECONDS,
            )
        frames = [int(line.partition("=")[2]) for line in result.stdout.splitlines()
                  if line.startswith("frame=")]
        return frames[-1] if frames else 0
    except subprocess.CalledProcessError as error:
        # Only local filenames are passed to FFmpeg. Bound its diagnostic and
        # remove those paths; HTTP handlers still return a generic error.
        detail = (error.stderr or "").replace(str(source), "<source>").replace(str(target), "<target>")
        detail = " ".join(detail.split())[-2000:]
        raise MediaError(f"FFmpeg exited with status {error.returncode}: {detail}") from error
    except subprocess.TimeoutExpired as error:
        raise MediaError(f"FFmpeg exceeded {TRANSCODE_TIMEOUT_SECONDS} seconds") from error
    except (OSError, subprocess.SubprocessError, ValueError, RuntimeError) as error:
        # Provider contents and filesystem paths do not belong in HTTP errors.
        raise MediaError("Video processing unavailable") from error


def _run(source: Path, target: Path, output_arguments: list[str], *, remux: bool = False) -> int:
    """Write a complete, bounded file and return a verified output frame count."""
    count = _ffmpeg(source, target, output_arguments)
    if not target.is_file() or target.stat().st_size == 0:
        raise MediaError("Video output is missing or empty")
    if target.stat().st_size > MAX_MEDIA_BYTES:
        raise MediaError("Video output exceeds its size limit")
    if remux and count < 1:
        # FFmpeg 7.0.2 on Linux reports frame=0 for a successful stream copy.
        # Decode the saved video to a null sink to verify/count actual frames;
        # a nonempty MP4 header alone does not prove there is playable video.
        count = _ffmpeg(target, "-", ["-xerror", "-f", "null"])
    if count < 1:
        raise MediaError("Video output contains no frames")
    target.chmod(0o600)
    return count


def strip_audio(source: Path, target: Path) -> int:
    """Remux the video stream unchanged into an MP4 with no audio/extra streams."""
    return _run(source, target, ["-c:v", "copy", "-movflags", "+faststart", "-f", "mp4"], remux=True)


def encode_mjpeg(source: Path, target: Path, *, width: int, height: int, fps: int) -> int:
    """A finite sequence of JPEGs, each center-cover-cropped without stretching."""
    filters = (
        f"fps={fps},scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={width}:{height}:exact=1,setsar=1"
    )
    return _run(source, target, [
        "-vf", filters, "-c:v", "mjpeg", "-q:v", "4", "-pix_fmt", "yuvj444p", "-f", "mjpeg",
    ])
