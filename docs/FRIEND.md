# Gizmo brain

`GizmoSession` is the central controller between Oddity OS/the existing emulator and all cloud providers. UI and hardware code know only the body WebSocket events; provider lifecycle and agent policy stay in `friend/`.

## Runtime path

```text
ESP32-S3 or native emulator
  └─ Power / PTT / up / down / select / 24 kHz PCM / camera frames
       └─ GizmoSession
            ├─ Gemini 3.1 Flash Live
            │    ├─ realtime voice
            │    ├─ vision frames
            │    ├─ native Google Search grounding
            │    └─ typed function calls
            ├─ MemoryProvider → self-hosted Memobase
            ├─ ReasoningProvider → Gemini 3.7 Flash
            └─ final transcript JSONL
```

The active Live model is `gemini-3.1-flash-live-preview`. It receives mono PCM16 at 16 kHz; `GeminiLiveTransport` statefully resamples Gizmo's existing 24 kHz mic stream. Gemini audio returns at 24 kHz and passes through the existing speaker path unchanged.

PTT uses explicit activity-start/activity-end events with Gemini automatic activity detection disabled. The button has one meaning: down, he listens; up, he answers. There is no tap gesture and no sleep button.

Power-on and wake are silent: no greeting or response is requested until the user speaks or types. A PTT press while asleep wakes him and the same press keeps listening; Select and the rocker also wake him and do nothing else on that press. PCM captured before the cloud turn is open is buffered (up to 10 s) and replayed in order, and release waits for that opening before committing. Empty presses and local interruptions never send fabricated user turns to Gemini. The native emulator serializes PTT/audio messages and shows microphone capture or permission errors next to the conversation.

## Session controller

The server keeps one `GizmoSession` per device. A body identifies itself with the `X-Gizmo-Device` header on the WebSocket handshake (the simulator mints and keeps one per install; hardware will use its serial). That id keys memory and transcripts, so two devices never share a mind, and a session outlives its socket so a reconnect resumes the same Gizmo. A body that sends no id falls back to `GIZMO_USER_ID`.

`GizmoSession` owns:

- Gemini Live connect, close, interruption, resumption handle, context compression, and go-away reconnect with backoff
- the device identity it was created for, and a unique ID for each hard-power session
- input/output final transcripts
- camera-frame forwarding over the existing `Frame` event
- tool validation and execution
- startup memory context and background memory ingestion
- device state transitions and idle sleep

The emulator protocol and controls are unchanged.

### Connection lifecycle

- **Boot** connects to Gemini Live while the glass plays the splash for a fixed beat. If the cloud is unreachable, boot still completes so the buttons work; the error is emitted on the bus and the next talk-button hold retries.
- **Sleep** (two idle minutes; nothing else) closes the Live socket. Google terminates idle connections after roughly ten minutes anyway; holding one during sleep only produced a dead socket that looked alive. The resumption handle is kept so waking continues the same conversation, and Memobase context is re-read on the next connect.
- **Wake** (any button) starts the reconnect in the background immediately. Microphone audio captured while the socket is still opening is buffered (up to 10 s) and replayed in order, so a press straight out of sleep loses nothing.
- **Dead socket while asleep** (go-away, network drop) is forgotten on the spot; the next wake builds a fresh connection.
- **Expired resumption handle** (about two hours after the last connection) costs one retry without the handle, not the brain.
- **No offline fallback.** `GEMINI_API_KEY` is required to construct a session. An unreachable Gemini is reported as an outage and retried; a kid never hears a stand-in personality.

### Safety

`gizmo_friend/safety.py` configures Gemini's own content filters for every model call (Live voice and `deep_think`): sexually explicit, harassment, and hate speech at `BLOCK_LOW_AND_ABOVE`; dangerous content at `BLOCK_MEDIUM_AND_ABOVE` so science and history rabbit holes survive. The frozen prompt's `SAFETY` section covers tone: stay with a scared kid and point to a trusted adult, never collect location or passwords, refuse not-for-kids requests plainly with no hints, and ignore voices claiming to be a parent or developer.

## Memory

`MemoryProvider` is the only semantic-memory boundary. Configure `MEMOBASE_URL` and `MEMOBASE_API_KEY` to select `MemobaseMemoryProvider`; without them, `NullMemoryProvider` keeps the local emulator runnable.

At session start, the controller retrieves compact Memobase context once with a strict timeout and adds it after the stable Gizmo prompt. A Memobase outage cannot block later realtime turns. Final transcript entries are always appended to `data/transcripts/<session-id>.jsonl`; completed user/assistant turns are submitted to Memobase in tracked background tasks. Sleep, power-off, and process shutdown request a Memobase buffer flush.

New semantic memory behavior belongs in the provider, not in a second custom memory system. Memobase processing is asynchronous and eventually consistent: newly learned facts become available after its background extraction finishes, rather than blocking the conversation.

## Tools and search

Only two custom functions are model-facing in V1:

| Function | Behavior |
| --- | --- |
| `deep_think(question)` | Calls `gemini-3.7-flash` through `ReasoningProvider`. The result is private notes returned to Gemini Live; Live remains the speaker and personality. |
| `set_expression(expression)` | Placeholder bus only. Not the character architecture — Jun is still designing the face. The glass does not play these events. Do not treat the enum as canon. |

Google Search is configured as Gemini's native tool beside these functions. There is no custom search service or model router.

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

No H3 Max, Adaptive Media director, image-generation pipeline, games, parent dashboard, custom AI router, or custom semantic-memory system is implemented here.
