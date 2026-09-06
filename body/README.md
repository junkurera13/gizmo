# Body

ESP32-S3 handheld: top power toggle, pink push-to-talk button, up/down rocker, circular Select button, mic, speaker, landscape screen, world camera. Selected screen: Akizuki 116265, a 2.8-inch ILI9341 SPI module, 320 × 240 landscape. The original 69 × 50 mm design target is not its verified active-area size.

**Selected board: Seeed Studio XIAO ESP32S3 Sense (113991115).**
Real board/camera bring-up firmware now lives in [`firmware/`](firmware/README.md).
Selected parts, unresolved wiring and physical acceptance checks live in
[`hardware/`](hardware/xiao-esp32s3-sense.md). The laptop reference below is
separate from firmware. On the board today: display, buttons, mic/speaker,
boot/home, a local Settings menu, PTT voice memo, phone Wi-Fi setup, a local
Camera world (Down / serial `d`), and a Friend `/ws` slice (health, hello, PTT
audio up at 24 kHz, inbound PCM play-down). A successful cross-compile is not a
hardware pass.

## Protocol Friend already understands

The native simulator, the laptop reference client, and the XIAO firmware use
JSON text messages over WebSocket `/ws`. Firmware still owns boot, home,
Settings, Camera, and local memo when the socket is down; the `/ws` slice is
health + hello + PTT audio, not the full Show/Settings overlay. Python classes
in `friend/gizmo_friend/body_protocol.py` are internal controller events; their
names are not necessarily the JSON names.

Connect to `wss://<brain-host>/ws` with `Authorization: Bearer <device-token>` and
`X-Gizmo-Device: <device-id>` headers. Keep the same device id across reconnects.
Local development uses `ws://127.0.0.1:43147/ws`. The body needs the device token,
not any provider API key.

Firmware stores the brain URL and token in NVS (`F<url>` / `K<token>` over
serial, or `GIZMO_BRAIN_URL` / `GIZMO_DEVICE_TOKEN` compile flags). The device
id is `gizmo-` plus the Wi-Fi MAC and is kept across boots. See
[`firmware/README.md`](firmware/README.md) for the on-device slice and what is
still stubbed.

The current wire version is **1**. Before opening the socket, read `/health` and
require `body_protocol.version == 1`. That response also publishes the canonical
events, audio format, the reserved visual-frame ceiling, and Show-frame route limits. It
does not publish a panel size: each body picks its own profile. The selected
module is Akizuki 116265, 320 × 240. Send
`X-Gizmo-Protocol: 1` on the WebSocket handshake. An explicit unsupported version
is closed with WebSocket code `1002`; clients from before this version header was
introduced may temporarily omit it.

| Wire event | Body input | Friend |
| --- | --- | --- |
| `power` | Top toggle on / off | Cold boot / hard shutdown |
| `ptt` | Pink side button down / up | Down: listen (wakes him if asleep). Up: answer. No tap gesture; sleep is idle-only |
| `select` | Circular Select button | In Settings, select or confirm a row. Otherwise interrupt output. Wakes him if asleep. Mac Camera gestures are local and are not this event |
| `navigate` | Up/down rocker | Friend owns Settings: up from home opens it. Inside Settings, the rocker moves rows or changes the active level; down past Volume returns home. Camera-capable bodies consume Camera rocker edges locally and do not forward them |
| `settings` (brain → body) | — | Overlay snapshot: `open`, `focus` (`brightness`\|`volume`), `adjusting`, `brightness`, `volume`, `steps`. Paint the two-row menu when `open` is true. Apply `brightness` to the panel backlight and `volume` to speaker gain. Hello repeats the same object so a reconnect restores levels |
| `frame` | Reserved visual JPEG, base64 in `image` | Not emitted by current clients; preview capture is local until the vision lifecycle is connected |
| `audio` | PCM in `pcm` while PTT is down | Realtime microphone input; `mic` is an accepted compatibility alias |
| `audio` (brain → body) | PCM in `pcm` | Realtime speaker output; there is no `speaker` wire event |

For both audio directions, `pcm` is standard base64 of signed, little-endian,
16-bit mono PCM at **24,000 Hz**, with no WAV header. Each chunk must contain whole
two-byte samples. There is no sample-rate negotiation: convert device audio to
this format before sending. The server handles the separate 16 kHz conversion
required by Gemini. Invalid base64, non-string PCM and partial samples emit an
`error`; an empty chunk is ignored.

One microphone turn, in order on the **same socket**:

```json
{"type":"ptt","active":true}
{"type":"audio","pcm":"AAA="}
{"type":"ptt","active":false}
```

`AAA=` is one silent sample to illustrate the encoding, not a spoken request.
In use, stream captured PCM chunks between press and release. Preserve that order
and do not wait for the server's `ptt:true` acknowledgement before sending PCM;
the server buffers incoming audio while opening the voice turn. That buffer does
not cover a disconnected body: wake/reconnect audio needs a local firmware buffer.
Only the connection owning the hold may send its audio or release. Audio sent
outside a hold or from another socket is ignored, for both audio input names.
If the owning socket disconnects, the backend drops that hold without committing
it. Reconnect and report a fresh physical press for the next turn.

Camera policy for this v1: **PTT is audio-only.** Neither the native simulator nor
the laptop reference client activates a camera or sends `frame` when the pink
button is pressed. The server still recognizes a bounded `frame` event as dormant
protocol capability, but current clients do not emit it. The Mac Camera world now has Down/double-Select entry and a local viewfinder.
The physical firmware opens Camera with Down (serial `d` until the ladder is
soldered), double-Select within 320 ms, or serial `c`. Up / Select leave it.
The viewfinder is local preview only.
Before agent vision is connected, define frame delivery/clearing, ownership, and
the event's relationship to voice explicitly. Do not infer camera
activation from PTT.

Other device inputs:

```json
{"type":"power","on":true}
{"type":"navigate","direction":"up"}
{"type":"navigate","direction":"down"}
{"type":"select"}
{"type":"power","on":false}
```

The examples are separate actions, not a sequence to send together. `power:true`
means a cold boot; an ordinary socket reconnect resumes the existing session and
must not blindly cold-boot it. A physical hard cut cannot guarantee a final
`power:false` message. Wait for boot to complete before sending a talk turn; PTT
from sleep wakes and captures on the same press.

On connect, the server sends `hello` with `state`, `power`, `screen`,
`transport`, and `settings`, followed by a `glass` snapshot. `navigate:up` from
home is answered with a `settings` event; the body paints that overlay and
applies backlight/volume from `brightness` and `volume`. State changes arrive in
`state` events and accompanying event fields. Show uses `glass` with `still`, then
`clip`/`frames`, or `viewing:false` on dismissal; `show` is a model tool name, not
the output event. The `frames` URL serves the finite JPEG sequence described in
`docs/SHOW.md`. Media fetches use the same authorization and device-id headers.

The protocol-v1 laptop client is in `body/reference/`. Checkpoint 2 now exercises
health/hello compatibility, authenticated identity and controls, real macOS
microphone/speaker adapters, authenticated still/MJPEG fetching, and a
ten-second local wake-audio buffer across reconnect. Its panel profile remains an
explicit provisional command-line input, and its queues and media cache are
bounded. Its current defaults start a configured panel at 24 fps with a 4 MiB
encoded-media cap; both remain command-line inputs for the physical profile sweep.
It is a hardware handoff reference, not firmware.

Boot and home do not depend on that socket. `body/assets/export_bundle.py` exports
the current local drawings, exact boot timing, chime, home base and home-only
status resources for an explicit provisional panel size. The matching
`body/reference/offline_assets.py` loader verifies the manifest and plays the
cold-boot state sequence from local storage. Firmware should place the selected
profile in device flash or equivalent local storage so network startup can run in
parallel with the 5.05-second splash.

No character art in this tree. No second brain. Body is a body.
