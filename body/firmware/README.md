# Gizmo firmware

Target: **Seeed Studio XIAO ESP32S3 Sense**. This folder contains code compiled
for the actual ESP32-S3; the Mac simulator remains in `../../simulator/`.

### Generated pictures and motion

Firmware now consumes Friend's `glass.still`, `glass.frames`, and
`glass.viewing:false` events. It downloads a 320×240 JPEG and paints it over
home, without HUD or captions. When motion arrives, the still stays visible
until the entire silent MJPEG sequence is downloaded and validated, then loops
at 12 fps. Select dismisses the picture; opening Settings or Camera dismisses
it too. PTT can continue while the picture is visible.

The device requests media from the configured brain using its existing bearer
token and `X-Gizmo-Device` identity. It never downloads provider URLs or MP4s.
The backend generates stills using Gemini, generates motion using fal's
MiniMax image-to-video model, and serves its saved JPEG/MJPEG versions.

Media HTTP/TLS has a separate task from the voice WebSocket. Encoded clips are
bounded to 4 MiB / 240 frames in PSRAM (stills to 256 KiB); every frame must be
a baseline 320×240 JPEG before it can reach the decoder. Bad, unavailable, or
oversized motion leaves the still visible. Dismissal, replacement, and network
disconnect invalidate pending results. `?` reports Show state, media sizes,
frame count, and free PSRAM.

See [SHOW_TESTING.md](SHOW_TESTING.md) for software verification and the required
flash/panel pass. The 12 fps target is provisional until measured on hardware.

Current scope is a **local terminal OS** on the breadboard hardware showing the
same boot and home as the Mac simulator: the Glass boot flipbook (1.25 s drop,
blink, ODDITY wordmark, chime at 2.875 s, held to 5.05 s), the home character
with the clock and five Minecraft-style hearts, push-to-talk voice memo into
PSRAM with a VU meter, memo playback through the STEMMA PWM speaker, and the Settings
menu driven by UP/DOWN/SELECT. Down from IDLE (and serial `d`) opens the local
Camera world: 78% viewfinder + 22% character strip. Double-Select within 320 ms
toggles it, matching the Mac simulator. Wi-Fi is a one-time phone captive portal:
the board opens an AP named `Gizmo-XXXX`, the phone joins it (no password), a
page lists nearby networks (or open `http://192.168.4.1` if the sheet does not
appear), and the chosen SSID/password is stored in NVS. Later boots auto-join
that network in the background; serial `w` forgets it and reopens the portal.
NTP (JST) starts after join so the home clock can appear. After
Wi-Fi is online and a brain URL is stored, firmware opens authenticated Friend
`/ws` (health + hello + PTT audio: 16 kHz mic upsampled to 24 kHz on the wire,
inbound 24 kHz PCM downsampled to 16 kHz before the amp). Local
memo playback stays available when the socket is down. LED is tied to 3V3, so
Settings brightness scales the framebuffer on blit instead of PWM until a
backlight GPIO exists.

### Artwork pipeline

The panel shows the **export_bundle.py output**, not a redrawn copy. The bundle
is embedded in flash so a single `pio run -t upload` carries everything:

```sh
# Re-export (Outfit Medium wght=500 atlas + boot/home) and embed in firmware:
body/firmware/.venv/bin/python body/assets/export_bundle.py --width 320 --height 240 \
    --output data/body-assets/320x240 --force && \
body/firmware/.venv/bin/python body/firmware/tools/embed_assets.py --bundle data/body-assets/320x240
```

The clock atlas is baked from `glass/fonts/Outfit[wght].ttf` at **wght=500**
(Outfit Medium, same axis the Mac simulator uses). Tabular figures (`tnum`) are
requested when Pillow/raqm can apply them; otherwise glyphs are still centred in
equal cells. `manifest.json` records `home.clock.weight`. `assets_generated.h`
exposes `kClockWeight`. REC/PLAY timers still use the 5×7 draw font.

`tools/embed_assets.py` writes `assets/` (15 unique boot JPEGs, `home_base.jpg`,
hearts as RGB565+A8, the Outfit clock atlas as an 8-bit mask, the chime
resampled 24 → 16 kHz PCM16) and rewrites the `board_build.embed_files` block
in `platformio.ini`. All timing and layout constants (125 ms slots, 5050 ms
minimum, 2875 ms chime, 0.045 status top, heart layout/asset px, atlas cells, clock
weight) come from `manifest.json` into `assets_generated.h`; nothing is
hand-copied. `assets/` and the generated header are committed so a clean
checkout builds. Rerun both steps after changing anything under `glass/`.
Pillow is required (`pip install -r body/firmware/requirements.txt`).

On device, JPEG frames are decoded with the camera driver's `jpg2rgb565` into
the PSRAM framebuffer only when the 125 ms slot advances; the home base is
decoded once and copied under the HUD. The clock is hidden until the device
knows the time (NTP after Wi-Fi join, or `tHH:MM` over serial). Hearts
follow the battery divider in half steps; with no divider wired (USB power)
they show full, matching the simulator's default level.

### OS states

| State | Enter | Leave |
| --- | --- | --- |
| `BOOT` | power-on; Glass flipbook, chime at 2875 ms, wordmark held to 5050 ms; buttons ignored | automatically to `IDLE` |
| `IDLE` | home: character, clock (when set), hearts | PTT down → `RECORDING` (and Friend `ptt` if `/ws` is up); UP → `SETTINGS`; Down or serial `d` → `CAMERA`; double-Select (≤320 ms) → `CAMERA`; single Select → local memo `PLAYBACK` if Friend is down, or Friend `select` if `/ws` is up |
| `RECORDING` | PTT held; 16 kHz PDM mic → PSRAM memo (20 s cap) and, when Friend is online, resampled 24 kHz chunks on `/ws`; REC band with VU over the home character (skipped if PTT started from Camera) | PTT up or buffer full → `IDLE` (Camera stays Camera) |
| `PLAYBACK` | memo → 9-bit PWM on D9 at 16 kHz and the Volume setting; PLAY band with progress over the character | end of memo or SELECT → `IDLE`; PTT → `RECORDING` |
| `SETTINGS` | two rows, Brightness / Volume. Local menu; not yet the Friend `settings` overlay. Brightness scales RGB565 on blit (LED is tied to 3V3). Volume scales PCM and plays a short local tick on each step | UP/DOWN move rows, SELECT toggles adjust (UP/DOWN change the level, auto-repeat on hold), DOWN past Volume → `IDLE`. Values persist in NVS |
| `CAMERA` | Down / serial `d` / double-Select / serial `c`. 78% viewfinder + 22% character strip. Local preview only: no Friend `navigate` or `frame` | Up, single Select, double-Select, serial `x` / `h` → `IDLE` |

All inputs are polled and debounced with `millis()`; audio DMA is pumped in
small non-blocking chunks from `loop()`; the haptic motor is timed the same way.
The PDM mic stops when idle. Friend inbound PCM is downsampled 24→16 on the
body, then played through the 16 kHz PWM speaker on D9. PWM drops as soon as
the live ring is empty so D9 sits low.

## Organization

```
platformio.ini             pinned toolchain and exact board target
include/gizmo/board.h      every pin: camera, mic, ILI9341, amp, PTT, ladder, battery, haptic, SD CS
include/gizmo/audio.h      PDM mic (I2S_NUM_0) + STEMMA PWM speaker (D9) + PSRAM memo
include/gizmo/battery.h    divider ADC on D5 with presence detection
include/gizmo/camera.h     camera ownership/lifetime interface
include/gizmo/display.h    ILI9341 SPI panel interface
include/gizmo/draw.h       RGB565 rasteriser: rects, 5x7 font, meters, alpha sprite/mask blits
include/gizmo/haptic.h     non-blocking motor pulse
include/gizmo/input.h      PTT GPIO + UP/DOWN/SELECT ADC ladder, debounced edge events
include/gizmo/friend.h     Friend /ws client: health, hello, PTT audio, inbound PCM
include/gizmo/assets.h     embedded bundle access: boot slot / home base decode, hearts, clock atlas, chime
include/gizmo/assets_generated.h   GENERATED by tools/embed_assets.py from manifest.json
include/gizmo/screens.h    HUD (clock + hearts) and the memo overlays
include/gizmo/wifi.h       open-AP captive portal, NVS credentials, NTP after join
assets/                    GENERATED blobs embedded via board_build.embed_files
tools/embed_assets.py      bundle -> assets/ + assets_generated.h + platformio.ini list
src/hardware/*.cpp         drivers for the above
src/ui/*.cpp               renderers and asset access
src/main.cpp               the OS loop and serial diagnostics
../hardware/               selected parts, full pin budget, ladder schematic, acceptance evidence
../assets/                 export_bundle.py, the source of every on-device image
../reference/              laptop protocol reference; not firmware
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

On Windows the same commands are `body\firmware\.venv\Scripts\pio.exe ... --upload-port COM6`.
Close the Arduino IDE Serial Monitor first; an open monitor holds the port and
the upload fails with "Access is denied".

Serial keys (115200):

| Key | Action |
| --- | --- |
| `u` / `d` / `e` | simulate UP / DOWN / SELECT (use these until the ladder is soldered). **`d` from IDLE opens Camera** |
| `p` | toggle PTT (press, then release) |
| `s` / `h` | open Settings / return home (`h` also leaves Camera) |
| `v` | 60 ms haptic pulse |
| `tHH:MM` + Enter | set the home clock (e.g. `t14:07`) |
| `g` | screen grab: `FRAME 320 240`, raw RGB565 framebuffer, `ENDFRAME` |
| `i` | ladder mV and decoded button, PTT level, battery mV and presence |
| `n` | Wi-Fi phase, AP name, SSID, IP |
| `w` | forget saved Wi-Fi and reopen the setup AP |
| `F<url>` + Enter | store Friend brain URL in NVS (`http://192.168.x.x:43147` or `https://…`) |
| `K<token>` + Enter | store `GIZMO_DEVICE_TOKEN` in NVS (required for remote HTTPS brains) |
| `f` | Friend phase, device id, url, hello flag |
| `c` / `x` | camera start / stop; `r` rotate; `?` full status |

`d` is the unsoldered-ladder stand-in for Down. From IDLE it must log
`button DOWN down` then `state IDLE -> CAMERA` and paint the 78/22 layout even
if the sensor fails (`CAMERA UNAVAILABLE`). Serial `ee` within 320 ms is
double-Select and also toggles Camera. Up / `u` / single `e` (after 320 ms) /
`x` leave Camera. Camera edges are not sent as Friend `navigate`.

### Friend `/ws`

After Wi-Fi reports `online`, firmware GET `/health` and requires
`body_protocol.version == 1`, then opens `/ws` with `X-Gizmo-Device`,
`X-Gizmo-Protocol: 1`, and `Authorization: Bearer <token>` when a token is
stored. Hello must confirm protocol 1. A powered-off session receives
`power:on`; firmware waits for the backend boot to finish before enabling
Friend PTT. Reconnecting to an already-powered session preserves it. The
`glass` snapshot is acknowledged and not fetched. PTT while connected sends `ptt` then 24 kHz
`audio` chunks (mic stays 16 kHz; body resamples 3/2). Inbound `audio` PCM is
downsampled 24→16 and queued onto the 16 kHz PWM speaker path. Local memo still
fills during PTT and still plays with Select when the socket is down.

Point the board at a brain (serial, 115200):

```
Fhttp://192.168.1.10:43147
K<the GIZMO_DEVICE_TOKEN>
f
```

Or compile-time in `platformio.ini` `build_flags`:
`-DGIZMO_BRAIN_URL='"https://…"'` and `-DGIZMO_DEVICE_TOKEN='"…"'`.
NVS/serial overrides those. `?` includes `friend=` phase. HTTPS/WSS verifies
the certificate chain and hostname using the committed ISRG X1/X2 public roots
(see [certs](certs/README.md)); it waits for network time before connecting.

HTTP, TLS, and WebSocket work run in a dedicated FreeRTOS task. The body loop
uses bounded, nonblocking queues, so retries cannot stall mic servicing or
buttons. Queue overflow cancels the voice turn rather than submitting missing
audio. Connection generations prevent stale audio from being replayed after
reconnect. Live playback buffers briefly for jitter and drains DMA before
stopping the amplifier clocks.

Stubbed, do not treat as done: glass/show JPEG-MJPEG fetch, Friend-owned
Settings overlay, `navigate` events, a physical power-off event, vision `frame`, wake-audio buffer
across reconnect. Agent voice is only the PTT + PCM path above — not Show, not
a full session UI.

`g` returns exactly what was last pushed to the panel, which is how the
2026-09-06 grabs in the hardware note were captured; the checks there are
against the export bundle's own preview, not against a description.

Every button edge and state change is logged (`button UP down`, `state IDLE ->
SETTINGS`). After wiring the ladder, press each button and check `i` reports
SELECT ≈ 1300 mV, DOWN ≈ 2200 mV, UP ≥ 2900 mV, idle ≈ 0 mV.

The camera begins off. Repeated start/stop must recover memory and report zero
failed captures before proceeding. Use the reported sensor PID to confirm which
camera revision is installed. LED/RESET are hard-wired to 3V3, so a blank
screen is a wiring or rotation issue, not a PWM duty of zero.

## Remaining integration

Recorded in [hardware](../hardware/xiao-esp32s3-sense.md): full header budget,
ladder schematic, and the 2026-09-06 on-device serial evidence. Remaining:
physical UP/DOWN/SELECT and battery divider soldering with measured mV,
listening check of memo playback, boot chime, and Friend inbound PCM
(`kMicGain` in `audio.cpp` is a fixed x4),
Friend-owned Settings / `navigate` / Show-frame fetch / vision `frame`, and a
wake-audio buffer across reconnect. Phone Wi-Fi setup is on-device; a later
app can replace the captive portal. LED stays tied to 3V3; Settings brightness
scales the framebuffer on blit instead of PWM until a backlight GPIO exists.
Preserve audio-only PTT.
Camera world entry and the 78/22 layout are in this firmware; agent vision is
not.

A successful compile is not hardware verification. Do not label this target the
complete Gizmo product firmware until those integrations run on the board.

## Review fixes and board acceptance

See [TESTING.md](TESTING.md) for pull/build/flash commands, expected serial
output, and the short voice/camera/clock board pass. Host regression tests and
a cross-compile cannot substitute for that physical pass.
