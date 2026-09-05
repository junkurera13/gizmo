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
during that initial audit. No physical board was exercised in that review.

**Current correction, September 5:** the H3 PTT-camera implementation described
below was rejected as the wrong product interaction and removed from both body
clients. Pink PTT is audio-only. The historical capture evidence remains here as
an engineering audit trail, not as the current contract; See is unwired until it
has an explicit interaction design.

**Fix status, September 4 (historical):** H1 is fixed in the local backend and verified through
both the WebSocket and native app. H2's microphone wire mismatch is now fixed and
verified at the WebSocket boundary. H3 temporarily captured a real Mac-camera JPEG on PTT
and sent it through the shared brain. Native verification reached the Gemini
adapter's SDK boundary with a local receiver; no cloud vision result was claimed.
H3's historical camera checkpoint was reviewed, body handoff checkpoints 1 and 2 pass, and
H4 now has a verified offline asset export/loader plus the Oddity boot entrance.
H5 now has a hardware-shaped native Show preview at the route's 24 fps maximum.
H6–H8 still require physical integration or selected hardware, and firmware
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

**Body handoff checkpoint 2, September 4 (historical camera variant):** the reference client then used the
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
temporary cache. Checkpoint 2 used the then-default 2 MiB cap and 320 × 240 at
12 fps; H5 subsequently raised the configurable starting cap to 4 MiB and the
default fps to 24. Width and height still default to zero, so media fetching
remains disabled until a provisional profile is supplied. None is a selected screen.

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

**Offline boot/home checkpoint 3, September 4:**
[`export_bundle.py`](/Users/jun/gizmo/body/assets/export_bundle.py:1) converts the
current source drawings into one explicit panel profile without modifying them.
The current 14-slot, 8 fps boot sequence references five unique baseline JPEGs,
so repeated drawings cost timing slots rather than flash copies. Its manifest
also carries the 3.8-second minimum splash, the wordmark/chime time, the existing
24 kHz mono PCM16 WAV, a composited home base, resized heart states, a clock glyph
atlas, source hashes and output hashes. Time and battery resources are marked
`home_only`.

The matching
[`OfflineAssetBundle`](/Users/jun/gizmo/body/reference/offline_assets.py:1)
validates every hash and panel dimension, reads one encoded frame at a time, skips
redundant consecutive decodes while preserving all timing slots, and reaches home
without HTTP, WebSocket or brain configuration. The generated 320 × 240 profile
is explicitly provisional. Its encoded asset payload is 95,411 bytes; the largest
resident encoded frame during playback is 11,237 bytes.

One focused real-time run used no brain or network route. The wordmark and real
speaker chime fired at 1,628 ms against the 1,625 ms target, and home arrived at
3,802 ms against the 3,800 ms minimum. The speaker accepted all 32,160 PCM bytes
with no queue drop. No source art changed and no persistent test file was added.
Evidence: [checkpoint-3 result](/Users/jun/gizmo/data/hardware-audit/2026-09-04/offline-assets/checkpoint-3.json),
[provisional bundle](/Users/jun/gizmo/data/hardware-audit/2026-09-04/offline-assets/320x240/manifest.json),
and [visual checkpoint](/Users/jun/gizmo/data/hardware-audit/2026-09-04/offline-assets/checkpoint-preview.png).

**Oddity boot-animation checkpoint 4, September 4:** the illustration enters
from above the display, reaches its original centered position, and then plays
the preserved 14-slot blink/wordmark sequence without changing those source
pixels. Motion is baked into full-screen frames; the Mac and the intended
physical route both decode and swap images rather than depending on a SwiftUI
transform or another simulator-only transition.

The rebuilt, signed native app was cold-booted and reviewed live. Captures around
250 ms, 750 ms, 1,100 ms, 2,700 ms and 4,900 ms showed the top entry, descent,
centered blink, wordmark and home in order. The focused body-loader run validated
the new manifest and every hash, preserved the old sequence exactly, sent the
wordmark chime to the real speaker at 2,653 ms against a 2,625 ms target, and
reached home at 4,803 ms against a 4,800 ms minimum. All 32,160 PCM bytes were
accepted with no queue drop. The provisional 320 × 240 bundle stores 147,382
asset bytes across 22 timing slots and 13 unique boot JPEGs; its largest resident
encoded frame is 11,237 bytes. No brain, provider, HTTP or WebSocket route was
used, and no persistent test file was added. This proves the device-shaped frame
contract, not decode timing on an unselected physical panel. Evidence:
[checkpoint-4 result](/Users/jun/gizmo/data/hardware-audit/2026-09-04/boot-drop/checkpoint-4-1s.json),
[provisional manifest](/Users/jun/gizmo/data/hardware-audit/2026-09-04/boot-drop/320x240-1s/manifest.json),
and [visual checkpoint](/Users/jun/gizmo/data/hardware-audit/2026-09-04/boot-drop/contact-sheet-1s.png).

After that review, the entrance was slowed slightly at Jun's request. The current
build uses ten slots at 8 fps, so the descent lasts 1.25 seconds. The unchanged
sequence now lands the wordmark at 2,875 ms, and the splash minimum is 5,050 ms
to preserve its hold. The rebuilt provisional bundle contains 24 timing slots,
15 unique boot JPEGs and 161,479 total asset bytes. The native app was rebuilt;
Jun performed and accepted the feel check. At his request, no new automated,
timed-loader or speaker test was run for this revision. Current artifacts:
[provisional manifest](/Users/jun/gizmo/data/hardware-audit/2026-09-04/boot-drop/320x240/manifest.json)
and [frame sheet](/Users/jun/gizmo/data/hardware-audit/2026-09-04/boot-drop/contact-sheet.png).

**Hardware-shaped Show checkpoint H5, September 4:** the native device screen no
longer uses AVPlayer or the 24 fps MP4. It now consumes the same authenticated,
finite MJPEG URL sent to the body. An explicit packaged profile starts at the
route's maximum: provisional 320 × 240, 24 fps and a 4 MiB encoded-sequence cap.
The still remains visible until the bounded sequence is complete and validated
against its content type plus `X-Gizmo-Frame-*` headers. Playback retains the
compressed JPEG frames and decodes one display frame at a time; no transition,
audio, controls, time or battery are layered over Show.

The saved rocket produced 124 frames and 2,502,648 encoded bytes at 24 fps. The
rebuilt native app fetched `/shows/...mjpeg?w=320&h=240&fps=24`, displayed visibly
different frames 250 ms apart, and completed its first loop in 5,168 ms against
the 5,167 ms media target. Select stopped the loop and restored home. The same
media would have exceeded the old 2 MiB reference cache, so the configurable
starting cap is now 4 MiB. A local transport and saved providers made zero model,
image or fal calls; no automated tests were added or run. This validates the
software path and pacing on the Mac. It does not establish the physical limit;
the selected board and panel must repeat a 24 → 20 → 18 → 15 → 12 fps sweep under
simultaneous Wi-Fi, audio and button load. Evidence:
[checkpoint result](/Users/jun/gizmo/data/hardware-audit/2026-09-04/show-24fps/results.json),
[native log](/Users/jun/gizmo/data/hardware-audit/2026-09-04/show-24fps/simulator.log),
and [fixture metadata](/Users/jun/gizmo/data/hardware-audit/2026-09-04/show-24fps/fixture.json).

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

**Superseded September 5:** H3 replaced the unused file-picker/viewfinder paths with one real camera snapshot
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
| **H3 — superseded: camera was coupled to PTT** | The September 4 experiment proved bounded capture and transport, but the interaction was not authorized product behavior. On September 5 the native simulator and laptop reference client stopped constructing camera capture from PTT; the app also dropped its camera permission declaration and camera-status UI. | Design See's explicit entry/exit interaction, viewfinder, privacy feedback, and protocol ownership before reconnecting any camera adapter. Keep pink PTT audio-only. |
| **H4 — fixed at the software handoff: offline boot/home assets** | The configurable [exporter](/Users/jun/gizmo/body/assets/export_bundle.py:1) packages panel-sized boot/home assets, timing, chime, home-only status resources and integrity metadata. The [boot builder](/Users/jun/gizmo/glass/build_boot.py:1) adds the accepted 1.25-second top entry as full-screen frames before the preserved blink. The [reference loader](/Users/jun/gizmo/body/reference/offline_assets.py:1) completed the prior 4.8-second variant with no brain and a largest resident encoded frame of 11,237 bytes; Jun accepted the current 5.05-second timing by feel. Existing source drawings remain the authoring assets. | Re-export for the selected panel, put the bundle in device-local flash/storage, and connect the manifest callbacks to the real JPEG/display/audio drivers. The checkpoint proves delivery and local timing, not board decode time or the final character/screen. |
| **H5 — fixed locally: hardware-shaped Show preview** | The packaged [preview profile](/Users/jun/gizmo/simulator/hardware-preview.json:1) is explicitly provisional. [SimulatorModel](/Users/jun/gizmo/simulator/Sources/GizmoSimulator/SimulatorModel.swift:1) requests the authenticated MJPEG at 320 × 240 / 24 fps under a 4 MiB cap, and [LoopingClipView](/Users/jun/gizmo/simulator/Sources/GizmoSimulator/LoopingClipView.swift:1) decodes one retained JPEG at a time. The saved 124-frame rocket loop was 1 ms from its 5,167 ms target; Select restored home. | Repeat the configurable fps sweep after selecting the physical board and panel. Check labels, crop, decode time and input/audio responsiveness there; the Mac run does not establish the hardware limit. |
| **H6 — software bounds exist; board memory and playback remain unverified** | Native Show and the checkpoint-2 [reference adapter](/Users/jun/gizmo/body/reference/io_macos.py:1) now use finite MJPEG with a configurable 4 MiB encoded cap; the native view retains compressed frames and one decoded display frame. Speaker PCM remains bounded at 96,000 bytes. These Mac paths prove the protocol shape, not ESP32 memory, storage, bus or simultaneous decode/audio timing. Server subscriber queues remain unbounded. | Implement measured PCM pacing/backpressure, JPEG decode and finite-loop storage on the selected board. Keep network reception and button handling independent of decode/display. Size the profile from actual PSRAM/storage and do not copy the Mac adapters into firmware. |
| **H7 — reference reconnect fixed; physical sleep mode remains open** | The checkpoint-2 [reference runtime](/Users/jun/gizmo/body/reference/gizmo_body.py:1) preserves up to ten seconds of microphone PCM locally while its WSS connection is absent. A replacement connection sends a fresh PTT-down edge before replay, and the focused run proved byte delivery in that order. The native simulator still models sleep as a connected Mac, and no ESP32 wake source, Wi-Fi resume time or power draw has been measured. | Port the verified edge/buffer ordering into firmware, then choose and measure the actual hardware sleep mode. Distinguish cold boot from sleep wake. A physical hard power cut cannot guarantee a final `power:false` transmission. |
| **H8 — P2: battery, clock, and haptics are placeholders/adapters** | [Battery](/Users/jun/gizmo/simulator/Sources/GizmoSimulator/SimulatorModel.swift:60) starts at 100% and is changed by a debug method. The offline bundle now supplies panel-sized clock glyph and heart resources scoped to home, but there is no body time/battery input. [Haptics](/Users/jun/gizmo/simulator/Sources/GizmoSimulator/DeviceHaptics.swift:9) use Mac APIs, with no specified physical actuator/driver. | Supply real battery readings and a device time source/timezone, then render them from the bundled resources on home only. Treat tactile feedback as conditional on the selected hardware. |

Measured resource implications:

- The current provisional 320 × 240 offline boot/home bundle stores 161,479
  encoded asset bytes plus its manifest. Fifteen unique boot JPEGs preserve all
  24 timing slots, including the 1.25-second entry; the largest encoded frame in
  the bundle is 11,237 bytes. A decoded
  RGB565 display buffer still requires 153,600 bytes, so this does not establish
  board heap fit.
- The saved 320 × 240 rocket sequence contains 124 JPEGs totaling **2,502,648
  bytes** at 24 fps, or 62 JPEGs totaling 1,250,954 bytes at 12 fps. One RGB565
  display buffer adds 153,600 bytes; two add 307,200. This is compressed clip
  storage plus display buffers, before decoder, network, camera, audio, or
  application memory. It is not an estimate for every generated clip. Server
  media limits allow up to 64 MiB and are not a device memory budget.
- The saved voice turn contains 432,990 PCM bytes: 9.02 seconds of speech arrived
  in 2.447 seconds. Assuming immediate continuous playback, its estimated peak
  queue is **315,534 PCM bytes**, before JSON/base64 or player overhead. This is a
  calculation from captured arrival times, not measured board heap usage. Longer
  answers need a bounded strategy.
- One 1024 × 742 boot frame expands to **1,519,616 bytes in RGB565**. The current
  24-slot sequence has 15 distinct images; loading all 24 decoded frames would
  require 36,470,784 bytes. That is a hypothetical direct port, not a claim about
  Mac NSImage allocation. Resize and deduplicate the export.
- A 320 × 240 full-frame RGB565 update transfers 3,686,400 bytes/second at 24 fps
  or 1,843,200 bytes/second at 12 fps, before bus overhead. The actual panel
  interface and shared-bus load must support the chosen resolution and frame rate.

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

The slowed Oddity boot is accepted and H5's constrained media preview passes.
The next physical checkpoint is H6's fps, memory and playback sweep on the selected
board and panel, followed by H7/H8 power, clock, battery and haptic integration.
Keep profiles configurable while the screen remains open. Until that hardware is
available, software work can return to SHOW.md checkpoint 4 or measurements 6/12.
Stop for review at each agreed implementation checkpoint.

Evidence: [connection reproduction](/Users/jun/gizmo/data/hardware-audit/2026-09-04/connection-reproduction.json)
and [asset/media measurements](/Users/jun/gizmo/data/hardware-audit/2026-09-04/resource-measurements.json).
