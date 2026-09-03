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
Stopped at the camera checkpoint for Jun's review.
H4–H8 and the broader firmware reference client/version handoff remain open.
No deployment has been made.

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
| **H6 — P1 for a resident loop without enough memory; otherwise unverified: media buffering assumes Mac resources** | [Native video](/Users/jun/gizmo/simulator/Sources/GizmoSimulator/LoopingClipView.swift:34) relies on AVPlayer and a downloaded local MP4. The alternative JPEG route exists, but has no board consumer yet. [SpeakerPlayback](/Users/jun/gizmo/simulator/Sources/GizmoSimulator/SpeakerPlayback.swift:14) schedules incoming audio without an application queue bound, and server subscriber queues are unbounded. Resource measurements below show why the same strategy cannot be copied to bare on-chip SRAM. | Choose a bounded audio buffer, playback pacing/backpressure, JPEG decoder, and a measured clip cache in PSRAM or other storage. Keep network reception and button handling independent of decode/display. Do not make a low-memory board hold the whole clip in internal SRAM. |
| **H7 — P2: sleep currently means a live Mac with a dark screen** | The [session sleep path](/Users/jun/gizmo/friend/gizmo_friend/session.py:507) closes the Gemini connection, while the body WebSocket remains available. Native PTT [requires that socket to be connected](/Users/jun/gizmo/simulator/Sources/GizmoSimulator/SimulatorModel.swift:292). Its 10-second microphone preroll is in the server, so it cannot save samples that never left an offline board. | Define the hardware sleep mode and preserve the wake press/audio locally while Wi-Fi and WSS reconnect. Distinguish a cold boot from sleep wake. A physical hard power cut also cannot guarantee the simulator's final `power:false` transmission. |
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

Remaining order before further emulator polish: review H3, then
H4/H5/H6 shared assets and constrained media
preview. Prepare those with configurable profiles while the screen remains open.
Finalize H7/H8 with the actual board, power circuit and panel. Stop for review at
each agreed implementation checkpoint; this audit does not advance SHOW.md.

Evidence: [connection reproduction](/Users/jun/gizmo/data/hardware-audit/2026-09-04/connection-reproduction.json)
and [asset/media measurements](/Users/jun/gizmo/data/hardware-audit/2026-09-04/resource-measurements.json).
