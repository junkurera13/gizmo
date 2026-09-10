# Gizmo live film

A working private prototype at `/cinema`: ask a question, watch an illustrated explanation with Gizmo's narration, interrupt, and steer it. Video is generated continuously by **H3 Max Director**, not the older five-second image-to-video endpoint. A film ends after its narrated idea; it does not autoplay another topic.

## Run locally

Install the project dependencies with `uv sync`. The existing `.env` needs `FAL_KEY` and `GEMINI_API_KEY`.

```sh
uv run gizmo --host 127.0.0.1 --port 8768 --data-dir data/director-local
```

Open http://127.0.0.1:8768/cinema. Type a question or hold the pink microphone button. The pause button freezes and silences the film immediately. A follow-up carries the previous explanation and last generated picture forward. The first request can take tens of seconds; this is still a prototype, not an accepted latency target.

The current desktop run uses the same app through a local Uvicorn launcher under `data/director-spike/`. It is not deployed to Railway.

## How it works

- `cinema/plan.py`: `gemini-3.1-flash-lite` writes a compact connected score. Three short narration beats synthesize concurrently using Google TTS. Their actual PCM sample lengths define each beat's timeline. The combined WAV is uploaded to Fal and used as Director's target soundtrack. `GIZMO_FILM_MODEL` can override planning; the default remains the model with successful end-to-end runs. A Sonnet comparison hit the 12-second planning deadline.
- Film narration uses Charon with brisk, clear conversational delivery (`GIZMO_FILM_VOICE` overrides it). The regular conversational/story voice keeps its own settings. In one identical 22-word comparison, the previous Umbriel delivery took 13.28 seconds and the revised delivery took 8.44 seconds. Visual timings continue to use the resulting audio samples, not an assumed speaking rate.
- `cinema/stream.py`: the brain owns Director's authenticated WebRTC peer and heartbeat. It relays both media tracks to the browser. Signaling follows the official WMA client contract; no provider credential enters browser code. Loopback viewing avoids unnecessary TURN discovery for the local relay; remote viewing keeps ICE/TURN.
- `cinema/runtime.py`: owns preparation, playback generation numbers, cancellation, context, the last-frame continuation anchor, and a bounded session lease. Independent prep overlaps: Director WebRTC connect starts with planning; continuation-frame upload starts with TTS; the browser starts ICE on the plan event. WAV upload still follows finished PCM. Director `configure` waits for the hosted WAV URL, the warmed peer, and an attached viewer. Provider completion is not treated as something the listener heard. Only the viewer's media-clock completion or the device's completed PCM delivery marks narration complete.
- `cinema/routes.py`: private session cookies, same-origin requests, one active browser per identity, bounded concurrent sessions and daily film reservations. Local preview sessions can run without an access code; cloud provisioning requires explicit enablement and a code.
- `cinema/capability.py`: Friend starts and stops that same CinemaSession on the existing body `/ws` glass/audio/held-cue contract. Browser `/cinema` is not this path.
- `oddity/film.py`: Oddity lab and public moments start and stop that same CinemaSession on the browser glass. No held-cue firmware; the Oddity client attaches over `/oddity/offer`.
- `static/cinema.*`: the film is the primary surface. A typed question or hold-to-talk interrupts without camera access. Stale requests/results cannot reopen an interrupted film. Browser media time determines progress and the end, rather than a generation-finished notification.

An interruption currently closes the generating peer. The next turn opens a new one with the last frame and conversation context. This deliberately avoids old buffered narration leaking through a changed direction, but adds reconnection latency and incurs the provider's per-session minimum. In-place replanning with a proven audio/video cut boundary is a future improvement, not something this implementation claims to do.

## Private cloud and device switches

Browser provisioning off loopback requires:

- `GIZMO_DIRECTOR_ENABLED=1`
- `GIZMO_DIRECTOR_TOKEN` (or the existing `ODDITY_LAB_TOKEN`)

Cloud WebRTC/TURN reachability and throughput have **not** been verified on Railway.

Friend owns the `/ws` session. Cinema is one capability that session can start and stop. The silent visual director chooses `film` by **difficulty and usefulness**, not vocabulary: super easy questions stay talk (a still only if a picture truly helps); somewhat-to-very-difficult asks where a moving illustration would make understanding better play Cinema; greetings, feelings, jokes, and simple facts never film. The kid does not need to say film, movie, or cinema, and those words are not a gate. Story openings and actual setting changes also use Cinema. Friend then reuses `cinema/runtime.py` (H3 Max Director) plus `DeviceFilmPlayer` to play 320×240 held-cue MJPEG and the original PCM on the body. PTT, Select, settings, stills, memory, and ordinary talk stay on `GizmoSession`. After the film ends or is interrupted, conversation returns to Friend. The old `GIZMO_DIRECTOR_DEVICE` whole-session swap is gone.

The old Fal `minimax/h3-max/image-to-video` still→short-clip path is **not** used on Friend or Oddity. Moving explanations are Cinema only. A bare “make it move” on a still already on the glass stays words and keeps the still: not a 60-second film, and not a Fal clip. Oddity stills, diagrams, and the computed orbit experiment stay as they are; only a moving explanation starts Cinema.

For a desk test that should prefer a film for every ask on one body, set `GIZMO_DIRECTOR_DEVICE=<exact-device-id>`. That is now a Friend routing hint, not a replacement brain. Leave it unset for normal conversation. Held-cue firmware (`X-Gizmo-Glass-Cues: 1`) is still required for on-device playback; without it the film cannot preload.

`cinema/device.py` buffers five seconds of incoming video, preserves the frame's aspect ratio at 320×240, produces ESP-compatible 12 fps MJPEG through the existing Show store, and pairs each segment with the corresponding original 24 kHz PCM. The next segment downloads while the current segment plays. Motion acknowledgement is required before `go`; failures stop the speech instead of letting it drift. Select dismisses, PTT stops the film and returns to Friend listening, and brightness/volume retain their existing Friend controls.

The bridge is software-tested, not accepted on a physical XIAO. Friend-owned start/stop of the same player is also software-tested. Full A/V sync on the XIAO still needs desk acceptance. The earlier microphone queue overflow and idle speaker-static reports remain separate unresolved issues. The body still needs tests for actual speaker start delay, JPEG decode, PSRAM use, network throughput, missed frames, interruption, settings, and reconnect. A downloaded/ready acknowledgement is not a presentation timestamp.

## Evidence from September 10

Live provider and browser runs:

- Director accepted a Google-generated narration recording and streamed video plus audio. The captured proof contains 409 video frames and audio.
- Comparing the original narration with the captured stream gave waveform correlation 0.914 after codec/resampling and an estimated 6.5 ms audio offset. This verifies the supplied recording survives the stream; it does **not** establish frame-perfect semantic action timing.
- The browser visibly played “Why Rockets Need Fire”, then answered “But how can it push anything if space is empty?” as “Push Without Air”, retaining the illustrated rocket.
- Concurrent synthesis produced 24.8 seconds of narration in 9.77 seconds in one sample. Complete request-to-first-frame measurements in the browser were 23.34, 27.22, and 29.33 seconds. These are samples, not a latency guarantee.
- Interruption during preparation visibly froze the current picture and cancelled the new work. Stale completion and interrupted-narration handling also have regression coverage.
- The initial plan included incorrect physical shorthand about exhaust pushing on the ground. Planning instructions now explicitly preserve scientific causality in both words and images. This is a prompt improvement, not a factual verification system; broader educational review is still required.

Offline device replay of the actual Director capture:

- ESP ROM TJpgDec equivalent decoded every frame: 60 + 60 + 52 = 172 frames.
- `go` at 5.199, 10.200, and 15.202 seconds from replay start.
- The next held cues arrived before their scheduled `go`.
- All 687,360 bytes of source PCM were preserved exactly.

Generated evidence is under the ignored `data/director-spike/`, including `live-proof.mp4`, `audio-verification.json`, `device-replay.json`, and provider probes. Per-session plans, actual audio timings, WAVs, and event logs live under `data/director-local/cinema/`.

## Verification

Browser `/cinema` is unchanged: same HTML/JS, session cookie, `/cinema/ws`, `/cinema/offer`, plan/Director stream, interrupt, and follow-ups. Re-check it locally before treating a Friend change as done:

```sh
uv run gizmo --host 127.0.0.1 --port 8768 --data-dir data/director-local
```

Open http://127.0.0.1:8768/cinema. Type a question or hold the pink microphone button. Pause must freeze and silence immediately. A follow-up should carry the previous explanation and last picture forward.

```sh
uv run python -m pytest friend/tests -q
uvx ruff check friend/gizmo_friend/cinema friend/gizmo_friend/oddity/film.py friend/gizmo_friend/session.py friend/tests/test_cinema.py
node --check friend/gizmo_friend/static/cinema.js
node --check friend/gizmo_friend/static/oddity.js
uv lock --check
```

Regression coverage includes cloud gating and origin checks, waiting for an attached viewer before generation, cancellation, stale completion, heard-versus-interrupted context, concurrent narration with exact PCM timing, overlapping continuation-image upload and ICE-during-TTS races, the existing device JPEG sampling contract, Friend `/ws` remaining a GizmoSession even when `GIZMO_DIRECTOR_DEVICE` is set, and Friend start/stop of the film capability.

## Remaining experience work

The initial wait is still tens of seconds of model work; overlapping prep does not change that. Planning must finish before TTS (the score writes the words). All beats must finish before the WAV is combined and uploaded. Director generation (`configure`) must not start until that hosted WAV exists. Browser `/cinema` still does not play until `ready`, and Friend still does not send device PCM until the first video segment exists. `playing.phases` on the event log is the local breakdown (plan, synthesize, audio_upload, director_peer, viewer, configure, first_frame). Avoid masking remaining latency with a fake pre-generated answer or a Friend voice bridge. Physical acceptance should use a continuous screen/audio/button recording from the cofounder.

The provider API is experimental. At the time of implementation, Fal documents a two-minute public-session limit, a 60-second billing minimum, $0.02 per generated second through the launch discount, and $0.08 after September 14. Defaults here reserve eight films per identity and thirty globally per day; interrupted generations still count. No production switch was enabled during implementation.

References: [Director API](https://fal.ai/models/minimax/h3-max/director/api), [Director capabilities and pricing](https://fal.ai/h3-max-director).
