Import("env")

from pathlib import Path

header = (
    Path(env["PROJECT_LIBDEPS_DIR"])
    / "xiao_esp32s3_sense"
    / "WebSockets"
    / "src"
    / "WebSockets.h"
)
if header.exists():
    text = header.read_text(encoding="utf-8")
    old = "#define WEBSOCKETS_MAX_DATA_SIZE (15 * 1024)"
    new = (
        "#ifndef WEBSOCKETS_MAX_DATA_SIZE\n"
        "#define WEBSOCKETS_MAX_DATA_SIZE (15 * 1024)\n"
        "#endif"
    )
    if old in text and "#ifndef WEBSOCKETS_MAX_DATA_SIZE" not in text:
        header.write_text(text.replace(old, new, 1), encoding="utf-8")
        print("patched WebSockets.h so WEBSOCKETS_MAX_DATA_SIZE can be overridden")
