"""Actual Friend HTTP responses -> the firmware's C++ media parser, no providers.

Run from the repo root with .venv/bin/python body/firmware/test/test_show_routes.py.
FFmpeg generates a local test clip; temporary storage never touches device data.
"""
from pathlib import Path
import hashlib
import io
import os
import subprocess
import tempfile
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image
import imageio_ffmpeg

from gizmo_friend.brain.clips import ConjuredClip
from gizmo_friend.brain.images import ConjuredStill
from gizmo_friend.brain.shows import ShowStore
from gizmo_friend.server import app_factory

root = Path(__file__).resolve().parents[3]
firmware = root / "body/firmware"
with tempfile.TemporaryDirectory(prefix="gizmo-show-wire-") as directory:
    temp = Path(directory)
    source = (firmware / "assets/home_base.jpg").read_bytes()
    store = ShowStore(temp / "devices" / "firmware-test", device_id="firmware-test")
    still = store.save(ConjuredStill(
        subject="local fixture", jpeg=source, prompt="fixture", model="fixture",
        width=320, height=240, source_width=320, source_height=240, latency_seconds=0,
    ), session_id="firmware-test")
    clip_path = temp / "fixture.mp4"
    subprocess.run([
        imageio_ffmpeg.get_ffmpeg_exe(), "-nostdin", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=12", "-t", "1",
        "-an", "-c:v", "libx264", "-threads", "1", str(clip_path),
    ], check=True)
    store.save_clip(still.id, ConjuredClip(
        motion="fixture", mp4=clip_path.read_bytes(), prompt="fixture", model="fixture",
        request_id="fixture", source_image_sha256=hashlib.sha256(source).hexdigest(),
        latency_seconds=0, expanded_prompt=None, timings={},
    ))
    parser = temp / "parse"
    subprocess.run([
        "c++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-fsanitize=address,undefined",
        "-I", str(firmware / "include"), str(firmware / "test/host/test_show_format.cpp"),
        str(firmware / "src/hardware/show_format.cpp"), "-o", str(parser),
    ], check=True)
    with patch.dict(os.environ, {"GIZMO_DEVICE_TOKEN": "fixture-only-token"}):
        app = app_factory(temp)
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer fixture-only-token", "X-Gizmo-Device": "firmware-test"}
        assert client.get(still.still_url).status_code == 401
        assert client.get(still.still_url, headers={**headers, "X-Gizmo-Device": "other"}).status_code == 404
        for suffix, mime, count in ((".jpg", "image/jpeg", 1), (".mjpeg", "video/x-motion-jpeg", 12)):
            path = still.still_url.removesuffix(".jpg") + suffix
            params = {"w": 320, "h": 240, **({"fps": 12} if count > 1 else {})}
            response = client.get(path, params=params, headers=headers)
            assert response.status_code == 200, response.text[:100]
            assert response.headers["content-type"] == mime
            assert int(response.headers["content-length"]) == len(response.content)
            if count > 1:
                assert int(response.headers["x-gizmo-frame-count"]) == count
                assert int(response.headers["x-gizmo-frame-rate"]) == 12
                assert int(response.headers["x-gizmo-frame-width"]) == 320
                assert int(response.headers["x-gizmo-frame-height"]) == 240
            else:
                assert Image.open(io.BytesIO(response.content)).size == (320, 240)
            media = temp / ("wire" + suffix)
            media.write_bytes(response.content)
            subprocess.run([str(parser), str(media), str(count)], check=True)
    print("show: real authenticated JPEG/MJPEG routes accepted by firmware parser under ASan/UBSan; zero provider calls")
