from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path

import httpx

from gizmo_friend.tools.print_still import render_still

MAX_CLIPS = 2
FAL_MODEL = "minimax/h3-max/image-to-video"
FAL_URL = "https://fal.run/minimax/h3-max/image-to-video"

PRINT_MOTION = (
    "print look, woodcut / risograph, limited ink on paper, not photoreal, "
    "no human faces, no child, no photograph. Short quiet motion."
)


class VideoBackend(ABC):
    @abstractmethod
    async def clip(self, subject: str, still_svg: str) -> str | None:
        """Return a video URL, or None to skip."""


class NullVideo(VideoBackend):
    async def clip(self, subject: str, still_svg: str) -> str | None:
        del subject, still_svg
        return None


class FalH3Max(VideoBackend):
    """MiniMax H3 Max image-to-video. Skip if FAL_KEY is missing."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key if api_key is not None else os.environ.get("FAL_KEY")

    async def clip(self, subject: str, still_svg: str) -> str | None:
        if not self.api_key:
            return None
        prompt = f"{PRINT_MOTION} {subject.strip() or 'the object'}."
        try:
            async with httpx.AsyncClient(timeout=40.0) as client:
                response = await client.post(
                    FAL_URL,
                    headers={
                        "Authorization": f"Key {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "prompt": prompt,
                        "prompt_expansion_mode": "disabled",
                        "duration": 5,
                    },
                )
                if response.status_code >= 400:
                    return None
                data = response.json()
        except httpx.HTTPError:
            return None
        video = data.get("video") if isinstance(data, dict) else None
        if isinstance(video, dict):
            url = video.get("url")
            return url if isinstance(url, str) else None
        return None


def video_backend_from_env() -> VideoBackend:
    key = os.environ.get("FAL_KEY")
    if key:
        return FalH3Max(key)
    return NullVideo()


async def show(
    subject: str,
    media_dir: Path,
    video: VideoBackend | None = None,
) -> dict:
    """Still first. Then at most two clips. Never a third. Never a player."""
    cleaned = subject.strip() or "thing"
    media_dir = Path(media_dir)
    media_dir.mkdir(parents=True, exist_ok=True)
    still_svg = render_still(cleaned)
    slug = _slug(cleaned)
    still_path = media_dir / f"{slug}.svg"
    still_path.write_text(still_svg, encoding="utf-8")

    backend = video if video is not None else video_backend_from_env()
    clips: list[str] = []
    for _ in range(MAX_CLIPS):
        url = await backend.clip(cleaned, still_svg)
        if not url:
            break
        clips.append(url)
        if len(clips) >= MAX_CLIPS:
            break

    return {
        "subject": cleaned,
        "still": str(still_path),
        "clips": clips[:MAX_CLIPS],
        "clip_count": len(clips[:MAX_CLIPS]),
    }


def _slug(subject: str) -> str:
    chars = [c.lower() if c.isalnum() else "-" for c in subject]
    slug = "".join(chars).strip("-") or "page"
    return slug[:40]
