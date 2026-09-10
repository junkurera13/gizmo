#!/usr/bin/env python3
"""Compile the real firmware audio/connection code against deterministic host I/O."""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
host = Path(__file__).resolve().parent
cxx = os.environ.get("CXX", "c++")
with tempfile.TemporaryDirectory(prefix="gizmo-host-") as temp:
    for name in ("audio", "friend", "worker", "stream", "show_format", "show", "settings"):
        binary = Path(temp) / name
        sources = [str(host / f"test_{name}.cpp")]
        if name == "settings":
            sources += [str(root / "src/ui/settings.cpp"), str(root / "src/ui/draw.cpp")]
        elif name in ("friend", "worker", "stream", "show"):
            sources.append(str(root / "src/hardware/show_format.cpp"))
            if name == "stream":
                sources += [str(root / "src/hardware/friend.cpp"), str(root / "src/hardware/audio.cpp")]
            elif name == "worker":
                sources += [str(root / "src/hardware/friend_worker.cpp"), str(root / "src/hardware/friend.cpp")]
            else:
                sources.append(str(root / f"src/hardware/{name}.cpp"))
        else:
            sources.append(str(root / f"src/hardware/{name}.cpp"))
        subprocess.run([
            cxx, "-std=c++17", "-Wall", "-Wextra", "-Werror",
            "-I", str(host / "stubs"),
            "-I", str(root / ".pio/libdeps/xiao_esp32s3_sense/ArduinoJson/src"), "-I", str(root / "include"),
            *sources,
            "-o", str(binary),
        ], check=True)
        subprocess.run([str(binary), *([str(root / "assets/home_base.jpg")] if name in ("show_format", "show") else [])], check=True)
