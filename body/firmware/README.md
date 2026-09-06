# Gizmo firmware

Target: **Seeed Studio XIAO ESP32S3 Sense**. This folder contains code compiled
for the actual ESP32-S3; the Mac simulator remains in `../../simulator/`.

Current scope is **board/camera bring-up**, not complete device firmware. It
initializes the onboard camera on explicit USB serial command, captures bounded
QVGA JPEG frames into PSRAM, returns every frame to the driver, reports capture
health, and deinitializes the camera on exit. It does not implement a screen,
physical controls, microphone/speaker playback, Wi-Fi, or Friend connection yet.
Those are not represented by fake success adapters.

## Organization

```
platformio.ini            pinned toolchain and exact board target
include/gizmo/board.h     verified onboard pin mapping
include/gizmo/camera.h    camera ownership/lifetime interface
include/gizmo/settings.h  Settings snapshot, RGB565 renderer, backlight/volume helpers
src/hardware/camera.cpp  ESP32 camera driver adapter
src/ui/settings.cpp      320×240 Settings overlay (no display GPIO yet)
src/main.cpp             USB serial camera bring-up; `s` exercises the Settings renderer
../hardware/             selected parts, wiring and hardware acceptance evidence
../assets/               existing character/boot export tools
../reference/            laptop protocol reference; not firmware
```

The board pin map belongs to Body, character source artwork belongs to Glass,
and the agent/provider code stays in Friend. The eventual panel driver must use
its confirmed controller and wiring; display dimensions are not inferred from
the Mac window or from camera capture resolution.

## Build from the repository root

```sh
python3 -m venv body/firmware/.venv
body/firmware/.venv/bin/pip install -r body/firmware/requirements.txt
body/firmware/.venv/bin/pio run -d body/firmware
```

PlatformIO pins Espressif32 6.12.0, which supplies Arduino-ESP32 2.0.17 and its
camera driver. The board definition enables OPI PSRAM and native USB serial.
Build outputs and the local tool environment are ignored by Git.

## Flash and check an attached board

Identify the board's port first; never flash an arbitrary connected device.

```sh
body/firmware/.venv/bin/pio device list
body/firmware/.venv/bin/pio run -d body/firmware -t upload --upload-port /dev/cu.YOUR_BOARD
body/firmware/.venv/bin/pio device monitor -b 115200 -p /dev/cu.YOUR_BOARD
```

`c` starts capture, `x` stops it, `?` reports state and free memory. No images are
saved or transmitted; USB prints counters only. The camera begins off. Repeated
start/stop must recover memory and report zero failed captures before proceeding.
Use the reported sensor PID to confirm which camera revision is installed.

## Remaining integration

After [hardware confirmation](../hardware/xiao-esp32s3-sense.md): implement the
panel driver and blit the existing Settings RGB565 renderer (`src/ui/settings.cpp`)
onto the ILI9341, plus character/caption rendering, physical button inputs and
camera world controller, PDM microphone and amplifier output, authenticated Friend
transport and explicit vision lifecycle. Friend already owns the Settings menu
(`type: settings`); firmware paints the snapshot and applies backlight PWM /
PCM gain. Preserve audio-only PTT. Match the
agreed Camera layout (78% viewfinder, 22% persistent character strip, no Vision
label) and Down/double-Select entry with on-device acceptance evidence.

A successful compile is not hardware verification. Do not label this target the
complete Gizmo product firmware until those integrations run on the board.
