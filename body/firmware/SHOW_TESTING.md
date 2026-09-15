# Generated pictures and live film: hardware acceptance

This is the source of truth for taking Gizmo from a working local film fixture
to an accepted live H3 Director experience on the physical XIAO. Do not call the
feature complete because a build, host test, Railway event, or downloaded cue
passed. Every checkpoint below needs its own stated evidence.

The existing panel wiring and peripheral ownership are unchanged. The physical
target remains 320x192 motion plus one 48-pixel caption band at 8 fps. The cue
budget is 256 KiB and each JPEG frame stays below 7 KiB. Do not raise these
limits or retune the display driver while diagnosing live-film cadence.

## Checkpoint rule

Stop when a checkpoint fails. Diagnose that layer with the same saved material;
do not spend another provider generation or change a different layer to hide the
failure. In particular:

- corruption already present in Railway's stored MJPEG is an upstream/server
  failure, not a display failure;
- a clean stored MJPEG that stalls only on the XIAO is a firmware scheduling or
  decode failure;
- a smooth film with broken narration is an audio delivery failure;
- a deterministic fixture pass is necessary but does not prove the live route.

## Status on 2026-09-13

| Checkpoint | Current evidence | State |
| --- | --- | --- |
| Deterministic 8 fps fixture | A 37.16-second Pompeii run previously completed with stable audio and no dropped, repeated, or decode-failed frames on older firmware. | Must be rerun after the latest decoder changes. |
| Upstream Director transport | `ef4bcce` selects Fal's TCP TURN relay and forces relay-only ICE. | Pushed; require a live log containing `Director upstream ICE: relay-only TURN/TCP` plus inspection of the stored cue. |
| Live device cadence | The 19:53 physical run stalled 349-845 ms, dropped 1-5 frames, and repeated 3-8 frames in four of five cues. | Failed on the experimental post-baseline firmware; a recovery candidate now restores the earlier playback path. |
| Narration | That run reported `starts=1`, `starvations=0`, but a 1546 ms maximum packet gap and only 778 ms peak buffer. | Not accepted by counters alone; requires an uncut listening test. |
| Interruption and recovery | Select previously failed to cancel a long thinking state. | Pending physical proof. |
| End-to-end latency | The 19:53 run took about 61.5 seconds from PTT release to `talking`. | Failed the demo target. |
| Final two-topic acceptance | No two distinct live questions have passed consecutively. | Pending. |

The 19:53 run included the first next-cue predecode experiment and predates both
`067f45b` and `445b7ff`. Those later commits attempted to fix exactly what its
logs exposed:

- `067f45b` schedules the next cue's narration lead during the current cue
  instead of sending a PCM burst at each `go` boundary;
- `445b7ff` fetches a held cue's motion before its fallback still, avoids the
  still download when motion succeeds, and reserves six decoded opening frames
  for the next cue.

They were layered onto an architecture that had already regressed physically.
The recovery candidate therefore restores the firmware player, device audio
scheduler, and their tests to the exact `ef4bcce` versions. It keeps the TCP
TURN relay in `cinema/stream.py`, the stable 8 fps/caption/byte-budget work, and
all unrelated product work. This recovery is not accepted until it is flashed.

## Remaining live-film roadmap

### Checkpoint A: current firmware regression, zero provider calls

1. Record `git rev-parse --short HEAD`; it must be the dedicated recovery
   commit that restores the five playback files to `ef4bcce` behavior.
2. Run the software regression checks at the end of this document.
3. Build and flash that exact checkout. The two newest playback changes include
   firmware, so a Railway deployment alone is insufficient.
4. Run the deterministic local fixture three times without rebooting. If those
   pass, perform the longer ten-run soak before final acceptance.

Pass the three-run gate only when every cue has:

- `stalls=0`, `decode_failed=0`, and `dropped=0`;
- ideally `repeats=0`, with no visible freeze or catch-up;
- `present_gap_max_ms` below 220 ms and `blit_max_us` below 45000;
- uninterrupted audio with `starts=1` and `starvations=0`;
- no reboot, watchdog, `motion unavailable`, or PSRAM failure.

This recovery intentionally does not emit `show: swap ... predecoded=...`; that
telemetry belonged to the reverted pipeline. If the earlier deterministic
cadence does not return, stop and compare this flashed commit, fixture bytes,
and serial metrics with the earlier accepted run before changing anything.

### Checkpoint B: one live H3 transport and source-integrity test

Restore `Fhttps://gizmo-brain-production.up.railway.app`, confirm `friend:
online`, and ask exactly, "How does a heavy steel ship float?" Make one
generation only. Capture:

- the continuous phone video from PTT through return to listening;
- the complete timestamped serial log;
- Railway logs from PTT release through completion;
- the stored first MJPEG cue and a contact sheet made from all its frames.

Pass the upstream half only if Railway logs relay-only TURN/TCP with no STUN
401/`CHANNEL_BIND` failure and the stored frames contain no green fill,
macroblock damage, frozen region, or old-frame strip. If the stored cue is bad,
stop at the server/upstream layer and do not touch the ESP32.

### Checkpoint C: live physical cadence

Using that same run, pass the device half only if:

- all cues report `decode_failed=0`, `dropped=0`, and `stalls=0`;
- repeats are zero or at most one isolated repeat without a visible freeze;
- no cue begins with only an old bottom strip or half-updated picture;
- motion stays at one consistent speed with no catch-up burst;
- mild isolated panel scan-line tearing may be recorded separately, but split
  objects, vibrating output, frozen bars, or multi-frame tears fail.

If the stored cue is clean and this checkpoint fails, replay saved/prebuilt
content instead of making another H3 call. Keep the fault on the device side.

### Checkpoint D: narration and A/V timing

Use the same live run. Narration must remain brisk and intelligible with no
cuts, stuck syllables, sudden speed changes, or restart. Require `starts=1`,
`starvations=0`, enough buffered audio to cover the largest packet gap, and no
visibly accumulating drift between cue changes and narration. Keep the final
picture visible until the last buffered syllable finishes.

### Checkpoint E: interruption and recovery

Prove each case on the physical device and return to `listening` without a
reboot:

1. Press PTT during an actively playing film; playback and narration stop and a
   new audio turn can begin.
2. Press Select during `thinking`; it cancels preparation instead of opening
   Camera after repeated presses.
3. Press Select during playback; it dismisses the film and late cues do not
   reappear.
4. Start another fixture film afterward to prove the decoder, audio ring, and
   controls recovered.

### Checkpoint F: latency

Measure, rather than infer, these timestamps in the next live run: PTT release,
route selection, plan complete, TTS complete, audio upload, Director configured,
first provider frame, first cue encoded, device download complete, and
`talking`. The demo target is film playback within roughly 30-35 seconds, with
an immediate honest making-your-film state during the wait. Do not hide a
60-second wait behind a fake generated answer.

### Checkpoint G: final acceptance and demo freeze

After checkpoints A-F pass, make one additional live generation using a
different educational question. Accept only if both topics produce a factual,
coherent 25-35 second film, synchronized narration, stable motion, and clean
recovery. Then pin the commit and deployment, stop tuning, rehearse three times,
and retain the Pompeii fixture below as the application fallback.

## Demo-only Pompeii shortcut

For the application recording, the local fixture can serve the bundled,
prebuilt 37-second Pompeii film. This is deliberately isolated from the real
agent: it makes no transcription, planner, TTS, Gemini, Fal, H3, or Railway
request, and it does not change production behavior. Gizmo still performs the
real HTTP download, MJPEG decoding, panel playback, PCM buffering, and A/V
timing.

Start it from the repository root on a laptop connected to the same Wi-Fi as
Gizmo:

```sh
.venv/bin/python body/firmware/test/local_film_fixture.py --demo-pompeii
```

Send the printed `Fhttp://<mac-ip>:8765` command over serial. After
`friend: online`, hold PTT and ask exactly, "Gizmo, what happened to Pompeii a
long time ago?" The first cue downloads while PTT is held. On release, expect
the finished film and narration to begin without a cloud-generation wait.

Keep the fixture terminal and laptop awake for the entire take. Film one
uncut rehearsal before the application take, and retain the serial log. After
recording, restore the real backend with
`Fhttps://gizmo-brain-production.up.railway.app`. Describe this honestly as a
curated prototype demo of the intended interaction, not live generation.

## Checkpoint 1: deterministic 30-second local film

Run this before any provider or Railway test. It exercises the production
WebSocket/audio/held-cue/HTTP/MJPEG path over local Wi-Fi, but removes Gemini,
Fal, H3, and Railway from the experiment. The picture has a moving scan bar and
whole-second counter; the soundtrack ticks on those same boundaries.

In terminal 1, start the fixture from the repository root:

```sh
.venv/bin/python body/firmware/test/local_film_fixture.py
```

It prints an `Fhttp://<mac-ip>:8765` command. Keep that process running. Flash
the exact checkout under test, then open a timestamped monitor in terminal 2:

```sh
body/firmware/.venv/bin/pio run -d body/firmware -t upload --upload-port <XIAO-port>
body/firmware/.venv/bin/pio device monitor -b 115200 --port <XIAO-port> --filter time
```

Send the printed `Fhttp://...` command over serial. Do not change `K`; the local
fixture ignores the stored production token. Wait for `friend: online`, then
press and release PTT (`p`, then `p` over serial also works). No speech is
required. Record the whole display and audible soundtrack at 60 fps if the
phone permits it. Repeat ten times without rebooting the board.

Each run must show six `HOLD -> READY -> GO` cues on the fixture console and six
`show perf: end` records on serial. Acceptance is:

- no reboot, Guru Meditation, watchdog, JPEG error, `motion unavailable`, or
  audio overflow;
- `decode_failed=0`, `dropped=0`, and ideally `repeats=0` for every cue;
- `present_gap_max_ms` stays below 220 ms and `blit_max_us` below 45000;
- the final `audio perf: end` reports `queued_ms` near 30000, `starts=1`, and
  `starvations=0`;
- motion never races through missed frames, and the audible tick stays aligned
  with each displayed second without accumulating visible drift;
- no split object, vibrating output, frozen bar, or multi-frame tear is visible;
  record any isolated thin panel scan line separately.

Send `?` during cue 3 and again after completion. Return the full timestamped
serial log, fixture-console log, and uncut phone video. This fixture now runs
at the hardware-derived fixed 8 fps; do not reintroduce the cloud, Fal, H3, or
Railway until its cadence passes. Restore the production URL afterward
with `Fhttps://gizmo-brain-production.up.railway.app`.

## Build and flash

From the checkout containing these changes, build and identify the XIAO's
serial port. Use that exact port for upload and monitor:

```sh
body/firmware/.venv/bin/pio run -d body/firmware
body/firmware/.venv/bin/pio device list
body/firmware/.venv/bin/pio run -d body/firmware -t upload --upload-port <XIAO-port>
body/firmware/.venv/bin/pio device monitor -b 115200 --port <XIAO-port>
```

Join Wi-Fi and keep the existing brain URL/device token. `f` must report
Friend online. If configuration is needed, use the `F` / `K` serial commands
in [README.md](README.md). Do not include credentials in returned logs.

## Display and controls

1. Hold PTT and ask for a picture. Expect `show: ready still frames=1 ...`,
   then a full-screen 320×240 image. Verify natural colors, correct orientation,
   no stretching, and no home HUD painted over it. Generation can fail or the
   agent can choose words; absence of a `glass` media event is distinct from
   download/render failure.
2. Ask to make that picture move. The still should remain until
   `show: ready motion frames=... bytes=... 320x240 fps=8`, followed by silent
   looping motion. The device does not play the source MP4 or its audio.
3. While it moves, ask a spoken follow-up. Check that PTT, the whole spoken
   reply, and buttons remain responsive with no watchdog reset or audio gaps.
4. Press Select (serial `e` also works). After the usual 320 ms double-Select
   window, home returns. Dismiss another picture while motion is downloading:
   the late result must never reappear. Repeat while waiting for the first still.
5. Request a new picture while one is visible. Only the new picture's motion
   may attach. Check Up to Settings, Down to Camera, and return home. Old media
   must not reappear over these local worlds. Check camera and local recording
   again after five show/open/dismiss cycles.
6. Disconnect Wi-Fi during a download. Home and local controls must remain
   usable; no partial image or animation should display. Reconnect and confirm
   the backend's current Show snapshot can load again.

Run `?` while a clip plays and after dismissal. Motion uses up to 4 MiB of
encoded PSRAM, plus its still and existing audio/display allocations. A clip
over that bound or with invalid frame metadata stays a still. The downloader
does not retry paid generation. A cache miss can wait up to 35 seconds for
HTTP response headers in the media task; body transfer is bounded to 30 seconds
with a 5-second idle timeout. Local dismissal takes effect during those waits.

Send the checkout commit, boot log, `?`, `f`, `i`, and a short video showing
still → motion → PTT reply → Select → home. Include camera sensor PID/status
and speaker results from [TESTING.md](TESTING.md) if either regresses. A build
or desktop playback result does not establish physical acceptance.

## Software regression checks

```sh
body/firmware/.venv/bin/python body/firmware/test/host/run.py
.venv/bin/python body/firmware/test/test_show_routes.py
.venv/bin/python body/firmware/test/test_clock_export.py
git diff --check
```

The root `.venv` supplies Friend's Python dependencies (Pillow, FastAPI,
imageio-ffmpeg). The route test generates a one-second local test clip, calls
the real authenticated JPEG/MJPEG endpoints, and passes their bytes through
the firmware's C++ parser with AddressSanitizer/UndefinedBehaviorSanitizer.
It makes zero model, image-provider, or fal calls and uses temporary data only.

Host tests cover media route ownership, baseline/dimension validation,
JPEG segment framing, byte/frame limits, HTTP/auth/metadata failures,
truncation, deadlines, loop timing, cancellation, and a blocked media download
while the body interface is pumped. JPEG decoding and physical I/O are mocked
in those tests; the real ESP32 decoder and panel still require the board pass.
