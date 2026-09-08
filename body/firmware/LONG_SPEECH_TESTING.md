# Long speech audio fix

The receive ring used to discard incoming samples when speech generation ran
ahead of playback. Long replies could exhaust the buffers, joining separated
pieces of speech together and sounding rushed or broken.

The network worker now waits for enough room for a complete WebSocket audio
message before reading it. TCP provides backpressure while the body loop keeps
playing at 16 kHz. Buffer sizes and hardware wiring are unchanged. An unexpected
overflow cancels the turn instead of playing corrupted speech.

## Build and flash this checkout

Preserve the builder's local wiring changes. This is a firmware change; a brain
server deployment alone will not update the device.

```sh
body/firmware/.venv/bin/pio run -d body/firmware
body/firmware/.venv/bin/pio run -d body/firmware -t upload
body/firmware/.venv/bin/pio device monitor -b 115200
```

If needed, install the tools using `body/firmware/requirements.txt`. Use an
explicit upload/monitor port when multiple boards are attached.

## Actual device acceptance

1. Ask for a short answer; confirm normal speed and a complete ending.
2. Ask for a story lasting one to two minutes, three times. Listen through the
   ending: no accelerated/skipped syllables, broken speech, or abrupt cutoff.
3. Interrupt a long reply with PTT after 20 seconds, then ask a new question.
   Old speech must stop and the new answer must play normally.
4. Disconnect/reconnect Wi-Fi during a long reply. Controls must remain
   responsive and a fresh turn must work after reconnection.
5. Repeat a long reply with the camera viewfinder active to check simultaneous
   display, Wi-Fi, and speaker load.

If it still fails, return the firmware revision, the serial log around the
failure, and a short recording. In particular, capture any `friend speaker:`
or disconnect messages. Omit tokens and Wi-Fi credentials.

## Software regression

```sh
body/firmware/.venv/bin/python body/firmware/test/host/run.py
```

The streaming regression drives the real connection/resampler and speaker
implementations through simulated transport, worker queue, and I2S output. It
delivers 120 seconds of PCM at four times playback speed, with irregular packet
sizes, and compares every stereo output sample. It also checks interruption
and Wi-Fi loss while receive reads are paused. The pre-fix firmware fails the
sample-count comparison. This is software evidence, not a physical speaker test.
