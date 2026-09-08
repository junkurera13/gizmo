#!/usr/bin/env python3
"""Compile the real firmware audio/connection code against deterministic host I/O."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
host = Path(__file__).resolve().parent
with tempfile.TemporaryDirectory(prefix="gizmo-host-") as temp:
    for name in ("audio", "friend", "worker", "stream", "show_format", "show"):
        binary = Path(temp) / name
        subprocess.run([
            "c++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
            "-I", str(host / "stubs"),
            "-I", str(root / ".pio/libdeps/xiao_esp32s3_sense/ArduinoJson/src"), "-I", str(root / "include"),
            str(host / f"test_{name}.cpp"),
            *([str(root / "src/hardware/show_format.cpp")] if name in ("friend", "worker", "stream", "show") else []),
            *([str(root / "src/hardware/friend.cpp"), str(root / "src/hardware/audio.cpp")]
              if name == "stream" else
              [str(root / "src/hardware/friend_worker.cpp"), str(root / "src/hardware/friend.cpp")]
              if name == "worker" else [str(root / f"src/hardware/{name}.cpp")]),
            "-o", str(binary),
        ], check=True)
        subprocess.run([str(binary), *([str(root / "assets/home_base.jpg")] if name in ("show_format", "show") else [])], check=True)
