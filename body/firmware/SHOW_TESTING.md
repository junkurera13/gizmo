# Generated pictures and motion: hardware acceptance

Software implementation is complete; physical display, decode speed, PSRAM
headroom, and simultaneous voice playback still need a flashed XIAO test.
The existing panel wiring and peripheral ownership are unchanged.

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
   `show: ready motion frames=... bytes=... 320x240 fps=12`, followed by silent
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
