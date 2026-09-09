# OddityOS 1 — browser simulator

OddityOS 1 is the software vision prototype of Gizmo. The physical device remains the handheld prototype, and the native Mac simulator remains the hardware-protocol test client. This browser client explores the richer audiovisual experience without rewriting the physical device's voice or Show behavior.

The important capability is the agent's direction: deciding what the moment needs, coordinating narration and imagery, and adapting when the kid interrupts. Generated video is central to that vision. A collection of generation buttons would not demonstrate it. Product context and the manifesto are linked in [PRODUCT.md](PRODUCT.md).

## Run

From the repo root, using the existing Python environment:

```sh
source .venv/bin/activate
gizmo --host 127.0.0.1 --port 43148
```

Open [OddityOS 1](http://127.0.0.1:43148/oddity). No separate frontend build or Node server is required. `gizmo` loads the existing root `.env`; all provider keys stay on the server. Local `/oddity` is the full sandbox. Add `?embedded=1` to see the public moment rail, or `?lab=1` for the explicit lab gate.

Click **Wake Gizmo**. Hold the pink button or Space to record; release to send. Typing works too. Select pauses or continues playback. Up and Down revisit scenes already presented. The return arrow restores the character. Speaking or sending a new thought interrupts the old sequence. Session notes show the conversation and the current plan's short editorial labels.

The browser uses the native Mac emulator's current device skin: byte-for-byte copies of `device-reference.png`, `device-reference-ptt-pressed.png`, and `skin.json` from `simulator/DeviceSkins/current/`. The live screen, pink PTT hit area, right-side Up/Down pill, and Select button use that manifest's normalized coordinates. Holding PTT immediately swaps to the pressed artwork; release, cancellation, loss of focus, and microphone failure restore the resting artwork. Screen content stays independently rendered inside the bezel. When updating the native skin, sync these three copies in `friend/gizmo_friend/static/` (`skin.json` is named `oddity-skin.json` there).

The microphone requires localhost or HTTPS and browser permission. It captures only while held, ends after 45 seconds, and never requests a camera. Browser speech recording is transcribed after release; this is not streaming Gemini Live input. The same Umbriel voice used by the device is generated as narrated audio.

## How an experience runs

1. The director receives the new utterance, bounded conversation history, and the actual current scene/playback state. It uses the existing Gizmo personality and safety canon with a browser-specific delivery contract.
2. It returns 1–4 connected beats. Each specifies narration, face/keep/image/diagram/video, a concrete visual brief, a motion brief where needed, and whether to narrate over the visual or after it plays.
3. The runtime prepares two beats ahead. Narration and visuals are generated concurrently; output is delivered in plan order. Character-based story images share an identity and first-image reference.
4. The browser waits for the actual media to play. A video can run with narration, or play silently to its end before narration starts. Short caption cues follow audio progress approximately; they are not word-aligned timestamps.
5. Playback acknowledgements record what was actually presented. Interruptions cancel pending work, stop audio/video locally, and retain the interrupted scene for the next turn. Unplayed planned narration is not inserted as completed conversation.

The initial implementation plans one short sequence per user turn. It does not autonomously run an endless film. It can replan on every new question; it does not edit frames of an already playing video in place.

## Providers and storage

| Component | Current implementation |
| --- | --- |
| Experience direction | `anthropic/claude-haiku-4.5` through Fal; `ODDITY_DIRECTOR_MODEL` override |
| Narration | `gemini-2.5-flash-preview-tts`; `ODDITY_TTS_MODEL` override; `GIZMO_VOICE` or Umbriel |
| Recorded speech transcription | `gemini-3.1-flash-lite`; `ODDITY_TRANSCRIBE_MODEL` override |
| Drawings / video first frames | Fal FLUX.2 Klein 9B with reference editing and Gizmo's violet/pink print style |
| Generated video | Existing fal H3 Max provider, five-second MP4, with a browser-specific motion brief and 120-second timeout |
| Conversation continuity | Local server session history; existing Memobase adapter when both Memobase settings are configured |

Files live under `data/oddity/<random-browser-id>/`. The public preview provisions a random, unguessable browser-session token after the reviewer enters `ODDITY_PREVIEW_TOKEN`; the unlisted lab uses a separate `ODDITY_LAB_TOKEN`. The provider and device credentials never enter browser code. A matching HttpOnly, SameSite cookie supports direct same-origin use, while the explicit session token keeps the embedded `oddware.xyz/gizmo/oddity` client working when browsers partition iframe storage. Media endpoints only serve that session's files, and filenames are opaque validated IDs. The socket also checks its origin. A second tab for the same session must wait until the first closes. Each session has its own identity; it is not automatically paired with a physical Gizmo.

Generated media is retained on disk for revisiting. Conversation context is bounded to 24 entries and the visible scene archive to 40. There is no automatic disk cleanup yet. The public preview has separate durable daily limits: 16 turns, 8 stills, and 4 videos per browser session, with default global caps of 120, 80, and 20. Failed or superseded requests still consume a reservation, and there is no automatic paid retry. The global caps can be changed with `ODDITY_DAILY_TURN_LIMIT`, `ODDITY_DAILY_SHOW_LIMIT`, and `ODDITY_DAILY_MOTION_LIMIT`.

## Status and limits

The browser interface, director, narrated playback, image/video pipeline, interruptions, history, and scene revisiting are implemented. Fal is the selected video provider. During the first live check on September 8, 2026, fal returned HTTP 403 with `User is locked. Reason: TOP_UP.` The user will top up that account. The same configured key will be used on the next request; no code change is needed for a balance top-up.

Provider failures are visible: a failed video keeps its generated first-frame drawing with a notice, while unavailable voice shows captions and requires explicit continuation. Media generation latency is real and can leave gaps between beats. This is a working preview, not yet the finished editorial quality of the reference films.

The private reviewer page is `https://oddware.xyz/gizmo/oddity`. It is a moment player: visitors cycle through a small set of curated first lines and talk to Gizmo inside that window. The website embeds the Railway-hosted simulator while Railway provisions isolated moment sessions behind `ODDITY_PREVIEW_TOKEN`. The unlisted sandbox is `https://oddware.xyz/gizmo/oddity/lab` (`?lab=1` on the brain), gated by `ODDITY_LAB_TOKEN`, with the full composer and no public daily caps. The route is framed as an adult product preview because the current [Gemini API terms](https://ai.google.dev/gemini-api/terms) prohibit API clients directed toward or likely to be accessed by people under 18. A child-facing release needs a provider contract that permits the intended audience; this deployment does not certify child-testing readiness. Games, simulations, camera input, and live web grounding are not part of this first client.

## Validation

```sh
.venv/bin/python -m unittest discover -s friend/tests -v
node --test friend/tests/oddity_*.test.mjs
node --check friend/gizmo_friend/static/oddity.js
```

- Live Gemini planning, TTS, generated illustrations, recorded-audio transcription, and a complete browser turn were exercised. Additional director samples covered a science question, an interruption, and emotional support. These are samples, not a guarantee of factual or editorial quality.
- Browser playback was exercised with saved generated audio and video on an isolated local fixture server: narration over video, silent video before narration, pausing both media, and interrupting into another turn. The fixture is not a mode exposed by the product. A one-off Gemini video probe completed before fal top-up was deferred; its saved clip was used only for playback QA. Production configuration stays on fal.
- At 390px, the page has no horizontal overflow; desktop and mobile layouts were visually inspected. Browser microphone capture requires a real user permission and speech check; transcription was verified using recorded audio, not a recording of the user's microphone.
- Runtime tests cover cancellation, stale playback events, unseen-script exclusion, persistence, failed-image fallback, media ownership, and cross-origin socket rejection.

## Code map

- `friend/gizmo_friend/oddity/director.py`: structured plan, speech generation, transcription.
- `friend/gizmo_friend/oddity/runtime.py`: preparation, cancellation, playback-aware history, private media.
- `friend/gizmo_friend/oddity/moments.py`: public moment catalog, seed memory, director addenda.
- `friend/gizmo_friend/oddity/routes.py`: browser session and WebSocket routes.
- `friend/gizmo_friend/static/oddity.*`: simulator UI and playback controller.
- `friend/gizmo_friend/static/oddity-timing.mjs`: bounded caption cues.
- `web/app/oddity/page.tsx`: public embedded moment player.
- `web/app/oddity/lab/page.tsx`: unlisted full-chrome sandbox.

The character and font are copies of the current assets in `glass/`, not a new Gizmo design. The font license is bundled alongside them.
