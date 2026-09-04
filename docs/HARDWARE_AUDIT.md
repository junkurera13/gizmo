# Hardware compatibility audit — September 4, 2026

The current experience is a working Mac prototype, not yet a verified hardware
implementation. The shared cloud brain is the right boundary, but several body
assumptions need work before the emulator can serve as evidence for the device.
Jun confirmed the screen has not been chosen. The 69 × 50 mm glass in the product
notes is a design target; neither its aspect nor the old 240 × 240 skin metadata
is a selected panel specification. The exact board/PSRAM configuration is also
unconfirmed in this audit.

The initial review inspected the implemented native app, shared session, WebSocket and
media routes, current assets, and saved run evidence. One local WebSocket
reproduction used null providers and a stub voice transport. No new provider
generation, persistent test files, product-code changes, or deployment occurred
during that initial audit. No physical board was exercised. Checkpoint 4 has not
started.

**Fix status, September 4:** H1 is fixed in the local backend and verified through
both the WebSocket and native app. H2's microphone wire mismatch is now fixed and
verified at the WebSocket boundary. H3 now captures a real Mac-camera JPEG on PTT
and sends it through the shared brain. Native verification reached the Gemini
adapter's SDK boundary with a local receiver; no cloud vision result is claimed.
H3's camera checkpoint was reviewed, and body handoff checkpoints 1 and 2 now
pass. H4–H8 still require physical integration or selected hardware, and firmware
remains open. No deployment has been made.

**Body handoff checkpoint 1, September 4:** protocol v1 is now explicit in
`/health`, `hello`, and the `X-Gizmo-Protocol` request header. Health advertises
canonical input/output events, 24 kHz PCM16 mono audio, the camera ceiling, and
Show MJPEG route limits. It does not publish a made-up panel size. An explicit
incompatible version is accepted only long enough to close with WebSocket code
`1002`; old clients that omit the new header remain compatible during rollout.

The executable [reference client](/Users/jun/gizmo/body/reference/gizmo_body.py:1)
checks health before connecting, requires protocol v1 again in `hello`, sends a
stable device identity and optional bearer token, disables WebSocket compression,
and exposes power, PTT, rocker and Select edges plus diagnostic text. It summarizes
incoming audio rather than printing PCM. Remote plaintext and missing remote tokens
are rejected locally. This checkpoint intentionally does not implement real
microphone, camera, speaker, glass-media or reconnect buffering adapters.

One focused local run used actual HTTP and WebSocket connections with authentication
enabled. It confirmed health and hello v1, the initial glass snapshot, cold boot,
up/down/Select acknowledgements, hard power-off, and protocol-v2 rejection with
code `1002`. The first rejection attempt exposed a pre-accept HTTP 403; the handshake
was corrected and the same checkpoint passed. Null providers prevented model and
media calls. No test suite or test file was added. Evidence:
[checkpoint-1 result](/Users/jun/gizmo/data/hardware-audit/2026-09-04/reference-client/checkpoint-1.json).

**Body handoff checkpoint 2, September 4:** the reference client now uses the
bundled FFmpeg binary for real Mac microphone and camera input and AudioToolbox
speaker output. PTT starts 24 kHz PCM16 mono capture and one warmed-up camera
snapshot. Camera output is re-encoded under the protocol's 640 × 480 / 128 KiB
ceiling. The speaker has a 96,000-byte application queue and drops new chunks at
the bound. A disconnect cancels stale camera and speaker work but leaves an active
microphone hold running into a first-word-preserving ten-second local PCM buffer.
The replacement socket sends a fresh PTT-down edge before replaying that buffer;
it never sends a cold-boot power event on reconnect.

Glass-media fetching is same-origin and repeats the bearer token, device id and
protocol version. It requests explicit panel dimensions and fps, validates the
returned JPEG or finite MJPEG metadata/frame count, and writes only to a private
temporary cache capped at 2 MiB by default. Width and height default to zero, so
media fetching remains disabled until a provisional profile is supplied; 320 ×
240 at 12 fps was used only for this checkpoint and is not a selected screen.

One focused run used a local authenticated stub brain and deliberately closed the
first WebSocket during a real hold. The reference opened a second authenticated
socket, sent PTT down first, replayed 11,264 locally buffered PCM bytes, then
continued live audio. A real 640 × 480, 15,533-byte Mac-camera JPEG followed on
that reconnected hold before release. The client authenticated and validated a
320 × 240 still plus a two-frame 12 fps MJPEG, accepted 4,800 response PCM bytes
through the real speaker adapter with no queue drop, and handled interruption.
No raw room audio or camera image was saved, no provider was called, and no test
file or test suite was added. Evidence:
[checkpoint-2 result](/Users/jun/gizmo/data/hardware-audit/2026-09-04/reference-client/checkpoint-2.json).

The PTT fix tracks the connection owning a hold, rejects audio/releases from
other connections, and clears an abandoned hold on owner disconnect. It closes
the unfinished voice connection without committing the abandoned audio and
retains the session identity/resumption state. An input lock orders teardown
before the next connection's press. Dropping an observer leaves active PTT alone.

The local WebSocket check covered owner/observer disconnects, foreign audio and
release, a reconnect that starts a fresh turn with the same session id, and a
disconnect while the voice turn was still opening. The native app used real
Gemini voice with image/clip/memory providers disabled: PTT opened, Device →
Reconnect closed that socket while held, the backend emitted
`ptt:false, reason:body_disconnected`, and the next native press and release were
acknowledged. The microphone captured ambient input; this was a control/recovery
check, not a controlled spoken-answer evaluation. No automated test files or
image/video generations were added. The isolated process exited and its local
port was released.

Evidence: [PTT socket results](/Users/jun/gizmo/data/hardware-audit/2026-09-04/ptt-fix/websocket-results.json),
[native events](/Users/jun/gizmo/data/hardware-audit/2026-09-04/ptt-fix/native-events.jsonl),
and [recovered native microphone](/Users/jun/gizmo/data/hardware-audit/2026-09-04/ptt-fix/native-recovered.png).

The microphone correction keeps `audio` canonical and accepts the previously
documented `mic` as an input alias. Both create the same internal `MicChunk` and
pass through the PTT ownership gate. Invalid base64, non-string PCM and incomplete
16-bit samples now emit explicit errors; empty chunks remain harmless. The body
handoff, sprint notes, controller documentation and native README now agree on
the JSON event names, 24 kHz PCM16 little-endian mono format, and same-socket PTT
ordering. The stale tap-to-sleep wording was removed.

A local WebSocket check sent known signed PCM samples through both names and
confirmed exact byte preservation, rejection of foreign/out-of-hold audio, clear
malformed-input errors, and continued delivery after errors. It used a stub voice
transport and null providers. No native audio code changed; the existing Swift
sender already uses `audio`. No new test files, live microphone recording, model
calls or media generations were needed for this checkpoint. This verifies the
wire correction, not physical microphone electronics or playback.
Evidence: [microphone contract results](/Users/jun/gizmo/data/hardware-audit/2026-09-04/microphone-contract/results.json).

H3 replaces the unused file-picker/viewfinder paths with one real camera snapshot
per PTT hold. Capture begins alongside microphone input, preserves the camera's
aspect, and produces a JPEG no larger than 640 × 480 / 128 KiB. The Mac adapter
allows a brief exposure warm-up and stops after one snapshot, release, disconnect,
power-off or a five-second capture timeout. Permission replies and frames from an
old press cannot attach to another press. Camera errors leave voice usable. The
face stays on glass; camera diagnostics live only in the desktop panel.

Camera frames now use the PTT ownership gate. The backend validates base64 and
the byte ceiling, clears its stored capture at turn end/disconnect, and clears a
silent turn's unsent image in the Gemini adapter. The focused check confirmed
exact JPEG delivery between activity-start and activity-end, rejection of foreign
and late frames, and no image carried from a silent hold into the next typed turn.

The rebuilt native app captured real 640 × 360 JPEGs through the MacBook Air
camera; the final non-black frame was 16,695 bytes. These crossed the actual
WebSocket and shared session into the real
Gemini adapter, whose network session was replaced by a local SDK receiver.
Image/clip/memory providers were disabled, and the voice gate was lowered only in
this isolated run so ambient PCM could exercise frame ordering without a spoken
request. Evidence records dimensions, byte counts, hashes and order; raw camera
images and microphone audio were not saved. Initial images were black; Jun
confirmed the room lights were off. Dark scenes remain valid input. A final native
press delivered one frame, and reconnect during a subsequent opening capture
cancelled it with no late image delivered. The release and reconnect paths both
completed cleanly. This proves
capture and delivery, not recognition of a book, small-text readability or cloud
vision comprehension. No permanent tests or media generations were added.
The release build and bundle signature passed verification. The isolated backend
was closed and the normal app configuration restored.

The provisional hardware path is direct sensor JPEG capture with one frame buffer,
followed by the same bounded upload. The Mac's BGRA/Core Image conversion is an
adapter, not code to port to the MCU. Espressif's camera driver supports ESP32-S3
and a one-buffer capture mode, but requires PSRAM above CIF JPEG resolution; VGA
capture is therefore conditional on the selected board/sensor and memory budget.
The 128 KiB cap is an upload ceiling, not a claim that total camera/audio/network
memory fits the board. [Espressif camera driver](https://github.com/espressif/esp32-camera).

Evidence: [camera delivery metadata](/Users/jun/gizmo/data/hardware-audit/2026-09-04/camera-capture/native-delivery.jsonl),
[camera ownership/turn results](/Users/jun/gizmo/data/hardware-audit/2026-09-04/camera-capture/wire-results.json),
and [native checkpoint preview](/Users/jun/gizmo/data/hardware-audit/2026-09-04/camera-capture/native-camera.png).

| Finding | Evidence and consequence | Required work |
| --- | --- | --- |
| **H1 — fixed locally: dropped connections left PTT down** | Before the fix, closing the socket left `pressed`, `active`, and `audio_ready` true and blocked a fresh press. [WebSocket cleanup](/Users/jun/gizmo/friend/gizmo_friend/server.py:190) now invokes [owner-specific teardown](/Users/jun/gizmo/friend/gizmo_friend/session.py:187). The local socket and native checks above passed. | Deploy after review; verify a real board disconnect/power cut when available. A silent network loss is handled once the WebSocket detects it; this does not promise instantaneous physical power-cut detection. |
| **H2 — microphone mismatch fixed locally** | Before the fix, the notes said `mic` while the server silently ignored it. [The server](/Users/jun/gizmo/friend/gizmo_friend/server.py:223) now accepts canonical `audio` and compatible `mic`, with PCM validation. [The body wire contract](/Users/jun/gizmo/body/README.md:9) distinguishes actual JSON messages from Python controller names. Exact-byte and ownership checks passed for both input names. | Deploy after review. The planned general reference client and protocol-version handoff remain separate unfinished work before firmware integration; this correction does not claim those are complete. |
| **H3 — fixed locally: real PTT camera capture** | [CameraFeed](/Users/jun/gizmo/simulator/Sources/GizmoSimulator/CameraFeed.swift:37) captures a bounded JPEG and stops. [The native PTT flow](/Users/jun/gizmo/simulator/Sources/GizmoSimulator/SimulatorModel.swift:307) sends it on the hold's socket. The unused viewfinder and file-picker paths were removed. Real camera bytes reached the Gemini adapter's local SDK receiver; ownership and stale-frame checks passed. | Deploy the shared backend after review. Verify a lit book and actual vision response, then implement/measure capture with the selected sensor and board. VGA needs PSRAM; a lower capture resolution may be necessary. No physical-camera firmware or text-readability result is claimed. |
| **H4 — P1: home and boot have no hardware asset delivery** | [SpriteStore](/Users/jun/gizmo/simulator/Sources/GizmoSimulator/SpriteStore.swift:59) reads original PNGs directly from the Mac checkout. The implemented `glass` URLs and routes cover Show; there is no equivalent state-art endpoint or firmware asset export. Body remains a README. | Export/cache panel-sized boot and home assets, with frame timing and the chime, or implement the planned shared state-frame route. Keep source drawings as authoring assets; decode one suitably sized frame at a time on the body. This needs no new character design. |
| **H5 — P2: the preview does not constrain itself to hardware pixels or timing** | [Still request sizing](/Users/jun/gizmo/simulator/Sources/GizmoSimulator/SimulatorModel.swift:732) uses the window size times the Mac display scale, up to 2048 pixels. The last run requested 1167 × 974. The visible skin is about 1.199:1; the design target is 1.38:1; its unused metadata says 240 × 240. Native video uses the 24 fps MP4, while the board route defaults to 12 fps. | Add explicit provisional device profiles for resolution, aspect and fps, then use the selected panel profile when known. Use the board frame path in a hardware-oriented preview. Check generated labels at those actual pixels; the large Mac preview cannot establish readability or matching crop. |
| **H6 — reference bounds exist; board memory and playback remain unverified** | [Native video](/Users/jun/gizmo/simulator/Sources/GizmoSimulator/LoopingClipView.swift:34) still relies on AVPlayer and a downloaded local MP4. The checkpoint-2 [reference adapter](/Users/jun/gizmo/body/reference/io_macos.py:1) now caps speaker PCM at 96,000 bytes and authenticated still/MJPEG cache storage at 2 MiB. Its AudioToolbox and temporary-disk paths prove the protocol flow, not ESP32 memory or decode timing. Server subscriber queues remain unbounded. | Implement measured PCM pacing/backpressure, JPEG decode and finite-loop storage on the selected board. Keep network reception and button handling independent of decode/display. Size the profile from actual PSRAM/storage and do not copy the Mac adapters into firmware. |
| **H7 — reference reconnect fixed; physical sleep mode remains open** | The checkpoint-2 [reference runtime](/Users/jun/gizmo/body/reference/gizmo_body.py:1) preserves up to ten seconds of microphone PCM locally while its WSS connection is absent. A replacement connection sends a fresh PTT-down edge before replay, and the focused run proved byte delivery in that order. The native simulator still models sleep as a connected Mac, and no ESP32 wake source, Wi-Fi resume time or power draw has been measured. | Port the verified edge/buffer ordering into firmware, then choose and measure the actual hardware sleep mode. Distinguish cold boot from sleep wake. A physical hard power cut cannot guarantee a final `power:false` transmission. |
| **H8 — P2: battery, clock, and haptics are placeholders/adapters** | [Battery](/Users/jun/gizmo/simulator/Sources/GizmoSimulator/SimulatorModel.swift:60) starts at 100% and is changed by a debug method. [The clock](/Users/jun/gizmo/simulator/Sources/GizmoSimulator/HeartRowView.swift:29) uses Mac time; there is no body time/battery integration. [Haptics](/Users/jun/gizmo/simulator/Sources/GizmoSimulator/DeviceHaptics.swift:9) use Mac APIs, with no specified physical actuator/driver. | Supply real battery readings and a device time source/timezone. Export clock glyphs or use an appropriate body renderer. Treat tactile feedback as conditional on the selected hardware. Keep time and battery on home only. |

Measured resource implications:

- The existing 320 × 240, 12 fps rocket sequence contains 62 JPEGs totaling
  **1,250,954 bytes**. One RGB565 display buffer adds 153,600 bytes; two add
  307,200. This is compressed clip storage plus display buffers, before decoder,
  network, camera, audio, or application memory. It is not an estimate for every
  generated clip. Server media limits allow up to 64 MiB and are not a device
  memory budget.
- The saved voice turn contains 432,990 PCM bytes: 9.02 seconds of speech arrived
  in 2.447 seconds. Assuming immediate continuous playback, its estimated peak
  queue is **315,534 PCM bytes**, before JSON/base64 or player overhead. This is a
  calculation from captured arrival times, not measured board heap usage. Longer
  answers need a bounded strategy.
- One original 1024 × 742 boot drawing expands to **1,519,616 bytes in RGB565**.
  The 14-frame sequence has only five distinct images; loading all 14 decoded
  frames would require 21,274,624 bytes. That is a hypothetical direct port, not a
  claim about Mac NSImage allocation. Resize and deduplicate the export.
- A 320 × 240 full-frame RGB565 update at 12 fps transfers 1,843,200 bytes/second
  to the display before bus overhead. The actual panel interface and shared-bus
  load must support the chosen resolution and frame rate.

Espressif specifies 512 KB of on-chip SRAM and memory variants with differing
PSRAM. The measured resident clip alone exceeds the on-chip SRAM, so additional
storage or a different buffering strategy is required. The exact total budget
depends on the chosen board. [ESP32-S3 datasheet](https://documentation.espressif.com/esp32_s3_datasheet_en.pdf).

JPEG playback is a credible hardware path: Espressif provides RGB565 JPEG decoding
and reports ESP32-S3 decoder benchmarks. Those isolated benchmarks do not validate
our YUV444 output, display bus, simultaneous audio/Wi-Fi, or sustained playback on
the eventual board. Silent loops and direct frame changes can stay as the intended
behavior. [Espressif JPEG implementation](https://github.com/espressif/esp-adf-libs/blob/master/esp_new_jpeg/README.md).

Explicit light/deep sleep does not preserve Wi-Fi connections; modem sleep with
automatic light sleep is a different option. Therefore the Mac's instant connected
wake is not evidence for a particular battery-saving mode.
[Espressif sleep documentation](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/system/sleep_modes.html).

The cloud-side voice/model tools, generation, storage, memory and transcoding can
remain server-side. Physical PTT/rocker/Select inputs, silent looping pictures, the
boot flipbook/chime and the home clock/hearts are implementable behaviors; the
missing work is their resource-bounded body implementation and integration.
SwiftUI/AppKit themselves are Mac adapters, not libraries expected to run on the
ESP32. The desktop conversation panel and local backend launcher are development
tools and need no counterpart on the device.

Remaining order before further emulator polish: review body reference checkpoint 2,
then H4/H5/H6 shared assets and constrained media preview. Prepare those with
configurable profiles while the screen remains open.
Finalize H7/H8 with the actual board, power circuit and panel. Stop for review at
each agreed implementation checkpoint; this audit does not advance SHOW.md.

Evidence: [connection reproduction](/Users/jun/gizmo/data/hardware-audit/2026-09-04/connection-reproduction.json)
and [asset/media measurements](/Users/jun/gizmo/data/hardware-audit/2026-09-04/resource-measurements.json).
