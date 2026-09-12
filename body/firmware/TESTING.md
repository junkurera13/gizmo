# Firmware handoff: voice, camera, and clock

For generated stills and motion, also run [SHOW_TESTING.md](SHOW_TESTING.md).

Test branch: `main`. Before flashing, compare `git rev-parse --short HEAD` with
the checkpoint hash supplied by the sender. The pin map, 16 kHz device audio
rate, and audio-only PTT are unchanged. No asset export is needed to flash.
Device tokens are not committed.

## Pull, build, flash

Preserve any local circuit/firmware edits before switching branches.

```sh
git fetch origin
git switch main
git pull --ff-only
python3 -m venv body/firmware/.venv
body/firmware/.venv/bin/python -m pip install -r body/firmware/requirements.txt
body/firmware/.venv/bin/pio run -d body/firmware
body/firmware/.venv/bin/pio device list
body/firmware/.venv/bin/pio run -d body/firmware -t upload
body/firmware/.venv/bin/pio device monitor -b 115200
```

If multiple serial devices are connected, add `--upload-port <port>` to upload
and `--port <port>` to monitor. Close other serial monitors before uploading.

## 1. Boot and clock

- Confirm the usual boot animation, chime, home, and local Settings still work.
- Send `t14:07` then Enter. Compare the clock with the emulator at the same time.
  Expected: Outfit Medium; `?` reports `clock_wght=500`.
- Try `t11:11` and `t20:58` to check narrow and wide digits.

## 2. Camera, independently of Wi-Fi

- From home send `d`. Expected: `button DOWN down`, `camera start: ESP_OK`,
  a sensor PID, `state IDLE -> CAMERA`, then `camera first JPEG: 320x240, …`.
- Confirm a changing viewfinder above the character strip. A status message
  without live frames is not a camera pass.
- Send `u` to exit. Repeat `d` / `u` five times; frames should resume each time.
- Try the physical Down key. If `d` works but the key doesn't, send `i`: idle
  should be near 0 mV, Down near 2200 mV. Check the ladder wiring before changing
  the camera pins. Two quick `e` presses also enter Camera; one `e` exits after
  320 ms. Holding Select must not count as a double press.
- If initialization fails, send the exact `camera start:` error and the boot
  PSRAM values. If the sensor starts but capture fails, send the PID and
  `frames=… failures=… blit_failures=…` lines. `CAMERA NO FRAMES` and
  `CAMERA FRAME ERROR` distinguish capture from render failures.

## 3. Friend voice

- Join Wi-Fi through the phone portal. After `wifi online`, set the URL and the
  existing device token over serial (each followed by Enter):

```text
Fhttps://gizmo-brain-production.up.railway.app
K<existing GIZMO_DEVICE_TOKEN>
f
```

- Wait for Friend `online`. Network time may need a few seconds. A new identity
  should report `friend state: powered_off`, then `booting`, then `listening`.
  Wi-Fi alone does not indicate voice readiness. Reconnecting an existing
  powered session should not cold-boot it again.
- Hold PTT, say a short question, then release. Expected serial order:
  `friend send ptt down ok`, then `friend send ptt up ok`. Expect a complete
  spoken answer, including its ending, with no clipped gaps between chunks.
- Interrupt a long answer with PTT. Old speech should stop. Ask another question.
- Hold PTT for over 20 seconds in both home and Camera: the memo limit must close
  the turn; releasing afterward must not leave the brain's mic open.
- On the first spoken response, serial must print
  `speaker: PWM 62500 Hz, 9-bit, updates 31250 Hz`. Any other carrier profile
  means the software-only speaker regression fix is not the image under test.
- When idle, the speaker should become silent with no persistent clock whine.
  Hold PTT with Volume at 0: GPIO8 must remain LOW. If the speaker still squeaks,
  preserve the current wiring and return the continuous video plus serial log;
  that is the checkpoint before considering any circuit change. PTT never sends
  a camera frame to Friend; Camera is local preview only.

## 4. Failure and recovery

- Disconnect Wi-Fi. Settings/buttons and local PTT/memo must remain responsive.
  Select plays the memo while Friend is offline. Restore Wi-Fi and retry a new
  PTT turn after `f` reports online. A turn interrupted by disconnection must
  not be replayed as a new turn.
- Temporarily set `Fhttp://192.0.2.1:43147` to simulate an unreachable brain.
  Try local recording, playback, and buttons while retries run. Restore the
  HTTPS URL above afterward.
- TLS errors must fail closed; do not disable certificate verification.

## 5. Settings brightness and volume

LED is tied to 3V3, so there is no backlight PWM. Firmware dims the pixels.

- From home send `u` (or press Up). Expected: `state IDLE -> SETTINGS`.
- Brightness is the first row. Send `e` to adjust, then `u` / `d` several steps.
  Expected: the panel visibly brightens and darkens; serial `settings: brightness=… (pixel gain)`.
  `?` reports `backlight=tied_3v3` and `pixel_gain` moving with the step (46 at 0, 255 at 10).
  Step 0 must stay readable.
- Send `e` to leave adjust, `d` to Volume, `e` to adjust. Each `u` / `d` should play a
  short local tick (not Friend speech). Louder toward 10, silent at 0. Serial
  `settings: volume=…`.
- Leave Settings (`e` then `d` past Volume, or `h`). Play the local memo (Select
  while Friend is offline) or a Friend reply: loudness must follow the Volume
  step. Boot chime on the next reset should too. Brightness must still apply on
  home, Camera, and Show frames.
- Values persist across reset (`settings: brightness=… volume=… (nvs)` in the boot log).

For a failure, send the commit (`git rev-parse --short HEAD`), boot log, `?`, `f`,
`i`, the failing action, and whether it fails consistently. Omit the `K…` line,
Wi-Fi passwords, and other secrets. A short camera/speaker video is useful.

## Software checks (no board required)

```sh
body/firmware/.venv/bin/python body/firmware/test/host/run.py
body/firmware/.venv/bin/python body/firmware/test/test_clock_export.py
```

Run a PlatformIO build first to install the pinned ArduinoJson headers. The
host tests compile the real audio and connection implementations with mocked
I/O. They verify software behavior; they cannot verify sensor detection,
physical button voltages, speaker quality, or timing on the XIAO.
