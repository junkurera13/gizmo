# Body reference client — checkpoint 2

This is the executable reference for body protocol v1. It verifies `/health`,
requires the same version in the WebSocket `hello`, identifies one device, and
sends the physical control messages. It deliberately disables WebSocket
compression because firmware should not need a compression implementation. The
macOS adapter uses the bundled FFmpeg binary for real AVFoundation microphone and
camera input and AudioToolbox speaker output.

From the repository's installed virtual environment:

```bash
.venv/bin/python body/reference/gizmo_body.py \
  --url https://brain.example.com \
  --device-id gizmo-board-001 \
  --panel-width 320 --panel-height 240 --panel-fps 24
```

The client reads `GIZMO_DEVICE_TOKEN` from the environment; prefer that over a
command-line token so the credential does not appear in the process arguments.
The token is the device credential. Never put provider keys on the body.
Remote connections require HTTPS/WSS. Local development defaults to
`http://127.0.0.1:43147` and needs no token unless the local server was started
in deployed mode.

Commands mirror hardware edges: `power on`, `power off`, `ptt down`, `ptt up`,
`up`, `down`, and `select`. `say <text>` remains a diagnostic stand-in. A PTT
hold captures real 24 kHz mono PCM and one real camera JPEG. Incoming PCM plays
through the selected AudioToolbox output and is printed only as a byte count.

The three `--*-index` options select the AVFoundation/AudioToolbox devices. The
defaults use input index 0 and the system's default output; use `--speaker-index`
when the output must be pinned. FFmpeg can list the current Mac indices:

```bash
.venv/lib/python3.11/site-packages/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1 \
  -hide_banner -f avfoundation -list_devices true -i ""
```

Panel dimensions are explicit because Gizmo's screen is not selected. Leaving
width and height at zero disables media fetching instead of treating 320 × 240
as final hardware. When enabled, still and finite MJPEG URLs must be same-origin,
carry the bearer token and device/protocol headers, and match the requested
dimensions and fps.

The laptop implementation makes the hardware constraints visible:

- PCM captured before or during a reconnect is kept locally for at most ten
  seconds. A reconnected hold sends a fresh PTT-down edge before replaying it.
- Speaker PCM has a 96,000-byte application queue; new chunks are dropped when
  that bound is full instead of growing memory without limit.
- Camera capture warms briefly, stops after one frame or five seconds, and emits
  at most 640 × 480 / 128 KiB.
- Authenticated still or MJPEG downloads use a private temporary cache capped at
  4 MiB by default. Both fps and the cap are command-line inputs for the physical
  limit sweep. The body must receive and decode independently in firmware.

This is a laptop reference, not firmware. AVFoundation, AudioToolbox, Pillow and
temporary disk storage are adapters for exercising the contract; they are not
code to port to the ESP32-S3.
