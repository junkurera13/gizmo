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

PTT uses explicit activity-start/activity-end events with Gemini automatic activity detection disabled. Gizmo buffers the first 500 ms while distinguishing a tap from a hold, so the 350 ms sleep/wake threshold does not eat the beginning of speech.

## Session controller

`GizmoSession` owns:

- Gemini Live connect, close, interruption, resumption handle, context compression, go-away reconnect, and fail-soft fallback
- stable `GIZMO_USER_ID` and a unique ID for each hard-power session
- input/output final transcripts
- camera-frame forwarding over the existing `Frame` event
- tool validation and execution
- startup memory context and background memory ingestion
- device state transitions and idle sleep

`Friend` remains an import alias while older callers migrate. The emulator protocol and controls are unchanged.

## Memory

`MemoryProvider` is the only semantic-memory boundary. Configure `MEMOBASE_URL` and `MEMOBASE_API_KEY` to select `MemobaseMemoryProvider`; without them, `NullMemoryProvider` keeps the local emulator runnable.

At session start, the controller retrieves compact Memobase context once with a strict timeout and adds it after the stable Gizmo prompt. A Memobase outage cannot block later realtime turns. Final transcript entries are always appended to `data/transcripts/<session-id>.jsonl`; completed user/assistant turns are submitted to Memobase in tracked background tasks. Sleep, power-off, and process shutdown request a Memobase buffer flush.

The existing SQLite file remains only for transitional device data and offline compatibility. Live Gemini sessions neither write semantic facts to it nor inject its old prefix. New semantic memory behavior belongs in the provider, not in a second custom memory system. Memobase processing is asynchronous and eventually consistent: newly learned facts become available after its background extraction finishes, rather than blocking the conversation.

## Tools and search

Only two custom functions are model-facing in V1:

| Function | Behavior |
| --- | --- |
| `deep_think(question)` | Calls `gemini-3.7-flash` through `ReasoningProvider`. The result is private notes returned to Gemini Live; Live remains the speaker and personality. |
| `set_expression(expression)` | Emits one validated face-expression event for the existing device renderer. |

Google Search is configured as Gemini's native tool beside these functions. There is no custom search service or model router. The retired `make`, `reach`, `see`, `show`, and `think` functions are not included in the Live schema. `FutureMediaProvider` reserves `show_image()` and `show_video()` signatures without implementing Adaptive Media.

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
