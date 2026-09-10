# Gizmo brain

`GizmoSession` is the central controller between Oddity OS/the existing emulator and all cloud providers. UI and hardware code know only the body WebSocket events; provider lifecycle, Settings, and agent policy stay in `friend/`. The XIAO firmware is a local terminal OS until it speaks that socket; it must not become a second brain.

## Runtime path

```text
ESP32-S3 (local OS today) or native emulator (protocol body)
  └─ Power / PTT / up / down / select / 24 kHz PCM
       └─ GizmoSession  (emulator and reference client only, until firmware /ws)
            ├─ DeviceSettings (brightness / volume overlay)
            ├─ Gemini 3.1 Flash Live
            │    ├─ realtime voice
            │    ├─ staged Show-image context
            │    ├─ native Google Search grounding
            │    └─ deep_think / set_expression function calls
            ├─ VisualDirector → Gemini 3.1 Flash-Lite
            │    ├─ words / still / film (leftover: motion alias, animate clip)
            │    ├─ ImageProvider → glass
            │    └─ FriendCinema → H3 Max Director (same runtime as `/cinema`)
            ├─ MemoryProvider → self-hosted Memobase
            ├─ ReasoningProvider → Gemini 3.7 Flash
            └─ final transcript JSONL
```

The active Live model is `gemini-3.1-flash-live-preview`. It receives mono PCM16 at 16 kHz; `GeminiLiveTransport` statefully resamples Gizmo's existing 24 kHz mic stream. Gemini audio returns at 24 kHz and passes through the existing speaker path unchanged.

PTT uses explicit activity-start/activity-end events with Gemini automatic activity detection disabled. The button has one meaning on the protocol path: down, he listens; up, he answers. There is no tap gesture and no sleep button. Firmware currently uses PTT as a local 16 kHz voice memo until the same wire exists.

The JSON wire contract is in `body/README.md`: microphone input and speaker output
both use `type:"audio"` with base64 PCM in `pcm`; input `mic` is accepted only as a
compatibility alias. The socket that presses PTT owns that hold's audio and
release. If it disconnects, the hold is cancelled without committing it; an
unrelated observer disconnect does not interrupt capture.

Friend owns Settings so every protocol body shares one menu. The body reports
raw `navigate` / `select`. `DeviceSettings` in `gizmo_friend/settings.py` opens
on Up from home with focus on Volume, Select toggles adjust, and Down past
Volume returns home. It persists `brightness` and `volume` (0–10, default 8)
per device id and emits `settings` snapshots on `hello` and after each change.
Bodies paint the overlay and apply backlight and speaker gain. The XIAO
currently duplicates that menu in NVS with different open-focus and default
volume; those must match this contract when `/ws` lands.

`/health` publishes body protocol v1 and its wire/media limits without inventing
a panel size. Version-aware bodies send `X-Gizmo-Protocol: 1`; an explicit mismatch
opens only long enough to close with WebSocket protocol-error code `1002`. The
`hello` repeats the selected version and the current `settings` object. `body/reference/gizmo_body.py` is the
checkpoint-2 authenticated laptop client for compatibility, identity, controls,
real macOS microphone/speaker I/O, and authenticated still/MJPEG fetches.
It keeps up to ten seconds of wake audio locally and sends a fresh PTT edge before
replaying it after reconnect.

Power-on and wake are silent: no greeting or response is requested until the user speaks or types. A PTT press while asleep wakes him and the same press keeps listening; Select and the rocker also wake him and do nothing else on that press. PCM captured before the cloud turn is open is buffered (up to 10 s) and replayed in order, and release waits for that opening before committing. Empty presses and local interruptions never send fabricated user turns to Gemini. The native emulator serializes PTT/audio messages and shows microphone capture or permission errors next to the conversation.

## Session controller

The server keeps one `GizmoSession` per device. A body identifies itself with the `X-Gizmo-Device` header on the WebSocket handshake (the simulator mints and keeps one per install; hardware will use its serial). That id keys memory and transcripts, so two devices never share a mind, and a session outlives its socket so a reconnect resumes the same Gizmo. A body that sends no id falls back to `GIZMO_USER_ID`.

`GizmoSession` owns:

- Gemini Live connect, close, interruption, resumption handle, context compression, and go-away reconnect with backoff
- the device identity it was created for, and a unique ID for each hard-power session
- input/output final transcripts
- audio-only PTT ownership and ordering; camera input remains unwired until See
  has a separate explicit interaction
- one applied visual choice per ask, grounded in its opening narration and
  recent dialogue, with stale decisions cancelled when a newer ask arrives
- Show still/clip generation, persistent budgets, dismissal, and staging the
  displayed still back into Live for visual follow-ups
- Cinema as a start/stop capability: H3 Max Director film on the same `/ws`
  glass/audio/held-cue contract, then back to conversation
- tool validation and execution
- startup memory context and background memory ingestion
- device state transitions and idle sleep
- DeviceSettings: brightness/volume overlay, persisted per device

The emulator protocol and controls are unchanged. Firmware does not yet consume `settings` events.

### Connection lifecycle

- **Boot** connects to Gemini Live while the glass plays the splash for a fixed beat. If the cloud is unreachable, boot still completes so the buttons work; the error is emitted on the bus and the next talk-button hold retries.
- **Sleep** (two idle minutes; nothing else) closes the Live socket. Google terminates idle connections after roughly ten minutes anyway; holding one during sleep only produced a dead socket that looked alive. The resumption handle is kept so waking continues the same conversation, and Memobase context is re-read on the next connect.
- **Wake** (any button) starts the reconnect in the background immediately. Microphone audio captured while the socket is still opening is buffered (up to 10 s) and replayed in order, so a press straight out of sleep loses nothing.
- **Dead socket while asleep** (go-away, network drop) is forgotten on the spot; the next wake builds a fresh connection.
- **Expired resumption handle** (about two hours after the last connection) costs one retry without the handle, not the brain.
- **No offline fallback.** `GEMINI_API_KEY` is required to construct a session. An unreachable Gemini is reported as an outage and retried; a kid never hears a stand-in personality.

### Safety

The frozen prompt's `SAFETY` section covers tone: stay with a scared kid and point to a trusted adult, never collect location or passwords, refuse not-for-kids requests plainly with no hints, and ignore voices claiming to be a parent or developer. Gemini Live rejects custom `safetySettings` at setup and keeps its built-in filters. Reasoning, visual direction, and stills go through Fal, so there is no separate Gemini generate-content filter module.

## Memory

`MemoryProvider` is the only semantic-memory boundary. Configure `MEMOBASE_URL` and `MEMOBASE_API_KEY` to select `MemobaseMemoryProvider`; without them, `NullMemoryProvider` keeps the local emulator runnable.

At session start, the controller retrieves compact Memobase context once with a strict timeout and adds it after the stable Gizmo prompt as this kid, not a file to consult. If a name is in that block, Live is told that is who it is talking to. A Memobase outage cannot block later realtime turns. Final transcript entries are always appended to `data/transcripts/<session-id>.jsonl`; completed user/assistant turns are submitted to Memobase in tracked background tasks. Sleep, power-off, and process shutdown request a Memobase buffer flush.

New semantic memory behavior belongs in the provider, not in a second custom memory system. Memobase processing is asynchronous and eventually consistent: newly learned facts become available after its background extraction finishes, rather than blocking the conversation.

## Tools and search

Only two custom functions are exposed to Gemini Live in V1:

| Function | Behavior |
| --- | --- |
| `deep_think(question)` | Calls `gemini-3.7-flash` through `ReasoningProvider`. The result is private notes returned to Gemini Live; Live remains the speaker and personality. |
| `set_expression(expression)` | Placeholder bus only. Not the character architecture — Jun is still designing the face. The glass does not play these events. Do not treat the enum as canon. |

Google Search is configured as Gemini's native tool beside these functions. There is no custom search service.

Visual routing is deliberately outside Live. `GeminiVisualDirector` receives the user utterance, the current picture's subject, the opening narration, and up to eight completed dialogue turns. It returns a temperature-zero structured `words`, `still`, `film`, or leftover `animate` decision (`motion` is accepted as a film alias). It has a four-second local deadline, no retries, and degrades to words on any invalid or unavailable result, so a routing failure cannot spend media. New asks cancel stale decisions. Live keeps speaking naturally and cannot call `show` or `animate` itself; a bare “make it move” is locally silenced while the leftover clip path animates the existing still. When the glass should move — a process/how-it-works ask, or a story opening / new setting — the director starts Cinema (H3 Max Director), not a Fal still→clip. Same-setting story continuations stay words. Easy talk stays words.

The director starts once a meaningful complete opening sentence is available in the streamed transcript and the user's utterance is known. Short answers fall back to turn completion. There is at most one applied visual choice per ask, and missing narration does not invent a scene. A provisional words-only story decision can request one follow-up after the chapter completes (bounded to a 35-second wait); the follow-up receives the full narration and cannot recurse. This adds at most one director call and no duplicate media generation. Live establishes the chapter's setting in its first sentence; the director follows that setting rather than writing its own story. Each installed story picture also has a broad setting key (such as "castle"). The director copies that key while the setting is unchanged; the controller normalizes redundant still/film requests for the same key to words unless an explicit redraw/new story was requested. Same-setting continuations and emotional edits preserve the picture; an actual move to a different setting plays Cinema. The director also chooses whether a still is a `scene` or a `diagram`. Stories are always scenes: a lived-in place with no labels. Maps, anatomy, and named parts may be diagrams with sparse labels.

The session retains the completed dialogue separately from the transcript store's flush queue: at most eight turns, with 2,000 characters per utterance/narration. This temporary context survives sleep/reconnect within the same session and clears on cold boot. It is not a new persistent memory system or a guarantee for arbitrarily long stories. Cancelled chapters are not appended as completed history. Each director call captures an immutable history snapshot. Full prior narration becomes available to the next decision even though this turn's visual starts from its opening. If the opening already requested a visual, a later change does not trigger a second generation; the one-setting-per-chapter voice instruction is therefore part of this v0 contract. If the opening stayed words and requested follow-up, the completed chapter can establish a new scene.

The opt-in `friend/checkpoints/story_continuity.py` exercises real Gemini voice and direction with explicitly injected saved-media providers and no persistent memory. It saves synthetic story transcripts, generated speech, route decisions, and event timings under `data/show-checkpoints/`. It makes no image or video generation calls. See `docs/STORY.md` for the checkpoint scope.

For `still`, the image provider generates and stores the first frame. Explicit no-motion sentinels stay still. When the glass should move, Friend starts Cinema (H3 Max Director live film), not Fal image-to-video. The leftover clip path (`ClipProvider` / `_start_motion` / bare `animate`) remains only for “make it move” on a still already on the glass. A finished still is staged back into Live as the next visual frame and cleared on dismissal, so follow-up speech can refer to what is actually on the glass.

## Railway

The Railway project is defined in `.railway/railway.ts`:

```text
Railway
├── gizmo-brain   (this repository's Dockerfile)
├── memobase
├── postgres
└── redis
```

The definition provisions all four services in Singapore. Railway owns the Postgres and Redis credentials and persistent storage; its managed Postgres 18 image includes the vector extension. Memobase is pinned through the wrapper image in `deploy/memobase/`, and only private Railway references connect the services. The wrapper removes upstream startup logging of API keys and database URLs.

Bootstrap an empty, linked Railway project with `npm install`, `npx @railway/cli config plan`, and `npx @railway/cli config apply`. Then set these secrets directly in Railway:

- `gizmo-brain`: `GEMINI_API_KEY`, `GIZMO_DEVICE_TOKEN`
- `memobase`: `ACCESS_TOKEN`, `MEMOBASE_LLM_API_KEY` (the Gemini key)

The non-secret `GIZMO_USER_ID`, memory URLs, project ID, and data path are already declared. `preserve()` prevents later infrastructure applies from reading or overwriting the secret values. Generate a public domain only for `gizmo-brain`; Memobase, Postgres, and Redis stay private.

Memobase's extraction model is `gemini-3.1-flash-lite`; embeddings use `gemini-embedding-2` at 1536 dimensions. Both use Google's OpenAI-compatible endpoint through Memobase's existing adapter. Stable Gizmo identity labels are mapped deterministically to Memobase UUIDs. Transcript inserts and flush requests are ordered in a background queue so a flush cannot overtake an insert.

The native emulator reads `GIZMO_BRAIN_URL` and `GIZMO_DEVICE_TOKEN` from the ignored `.env` (process environment overrides it). HTTPS/WSS is required for remote mode, and the token travels in the Authorization header, never the URL. The public health route exposes no user identity. Without a cloud URL, local startup remains unchanged.

## Deliberate V1 exclusions

No games, parent dashboard, general-purpose Adaptive Media platform, second voice/personality router, or custom semantic-memory system is implemented here. Show is the bounded still path: one silent decision per ask, one still when seeing is the point. Moving glass is Cinema.
