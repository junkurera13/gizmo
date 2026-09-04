# Gizmo

A wizard in a kid's pocket. One face, one voice, one coat. Kids 9–14. Dry, a little weird, warm underneath. He says the one line that matters and lets the kid steer; a story or a walkthrough runs longer, in chapters they pull. Magic is a chore he's good at.

This repo is the device: GizmoSession (brain), Body (firmware later), Glass (device renderer), and the native emulator. The public site lives in `web/`.

**v1 runs on a laptop.** The existing emulator connects to the same WebSocket contract the eventual ESP32-S3 body will use. Gemini 3.1 Flash Live handles realtime voice and vision; Gemini 3.1 Flash-Lite silently chooses words, still, motion, or animate; Memobase supplies persistent user memory; Gemini 3.7 Flash is available only through `deep_think()`.

## Tree

```
docs/PRODUCT.md   product principles
docs/FRIEND.md    current brain architecture and runtime contract
docs/V1.md        what v1 is and is not
docs/ROADMAP.md   from held prototype to magic
docs/SPRINT.md    the next eleven days: Blueprint II application, due Sep 14
docs/SHOW.md      Show: design and build plan
docs/DEMO.md      the 90-second film: script, staging, what's real
friend/           GizmoSession, providers, Gemini transport, and server
body/             ESP32-S3 firmware later (README only)
glass/            device renderer assets
simulator/        native macOS emulator
web/              public site (empty until we design it)
```

## Run (Mac / Linux)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env   # then set GEMINI_API_KEY
gizmo                  # http://127.0.0.1:43147
```

Or: `python -m gizmo_friend` from a venv with this repo installed.

### Env

| Variable | Required | What |
| --- | --- | --- |
| `GEMINI_API_KEY` | yes | Gemini Live voice/vision, the Flash-Lite visual director, still generation, and Gemini 3.7 Flash `deep_think()`. Gizmo has no offline brain; if Gemini is unreachable he reports the outage and retries. |
| `GIZMO_DIRECTOR_MODEL` | no | Visual-director override. Default `gemini-3.1-flash-lite`. |
| `GIZMO_USER_ID` | optional | Fallback identity for a body that sends no `X-Gizmo-Device` header. Each device otherwise gets its own memory. |
| `MEMOBASE_URL` | for persistent memory | Root URL of the self-hosted Railway Memobase service. |
| `MEMOBASE_API_KEY` | for persistent memory | Memobase project token. |
| `GIZMO_DATA_DIR` | no | Final transcript JSONL. Default `./data`. |

### Talk to him

**Native emulator:** launch `Gizmo Simulator.app`. **Power on** cold-boots Gizmo. Hold **PTT** while talking; release to send. Use **Up**, **Down**, and **Select** for device UI. Camera frames and 24 kHz PCM travel over the existing body WebSocket; the backend resamples mic audio to Gemini's 16 kHz input.

Gizmo waits silently after power-on or wake. He sleeps on his own after two idle minutes; any button wakes him, and a PTT press from sleep wakes him *and* captures that first spoken turn. There is no sleep gesture. The conversation panel shows microphone status and any permission/input errors.

For cloud mode, set `GIZMO_BRAIN_URL` to the Railway HTTPS domain and `GIZMO_DEVICE_TOKEN` to the matching service secret in the ignored `.env`. The native emulator reads only those two connection settings, uses an authenticated WSS connection, and plays the returned 24 kHz audio. It never needs the Gemini key in the client. Omit `GIZMO_BRAIN_URL` to retain the existing local-launch workflow.

**Terminal:** `gizmo --cli`

```
> /power on
> I'm Maya
> I have a dog named Toast
> why is the sky blue?
> /power off
```

## Memory

Self-hosted Memobase is behind a `MemoryProvider` interface. `GizmoSession` fetches compact context once at session start and appends it after the stable system prompt. Final user/Gizmo transcripts are saved to `$GIZMO_DATA_DIR/transcripts/<session>.jsonl`; completed turns are sent to Memobase in background tasks and flushed on sleep or shutdown.

Railway contains four services: `gizmo-brain`, `memobase`, `postgres`, and `redis`. The complete Singapore-region project is declared in `.railway/railway.ts`. Railway manages the database credentials and volumes; its Postgres 18 image includes pgvector. `gizmo-brain` has its own persistent `/data` volume for transcripts. Memobase uses Gemini 3.1 Flash-Lite and Gemini Embedding 2 through Google's OpenAI-compatible endpoint; an OpenAI account is not required.

After creating and linking an empty Railway project, provision it with:

```bash
npm install
npx @railway/cli config plan
npx @railway/cli config apply
npx @railway/cli up --service memobase
npx @railway/cli up --service gizmo-brain
```

Set `GEMINI_API_KEY` and a randomly generated `GIZMO_DEVICE_TOKEN` on `gizmo-brain`, and a random `ACCESS_TOKEN` plus the Gemini key as `MEMOBASE_LLM_API_KEY` on `memobase`, using Railway secrets rather than source files. The IaC file marks those values with `preserve()` so future applies retain them. Generate a public Railway domain for `gizmo-brain` after its first healthy deployment; Postgres, Redis, and Memobase remain on Railway's private network. All public device/data routes require the device token; `/health` is the only unauthenticated cloud route.

## Tools and Show

Gemini Live can call only `deep_think(question)` and the placeholder `set_expression()` bus (not the character). Google Search is Gemini's native grounding tool, not a custom search function. A separate structured visual director reads the same final user utterance and silently executes `show` or `animate`; stills use Gemini image generation, and optional motion uses H3 Max on fal when `FAL_KEY` is configured.

## Who owns what

| | |
| --- | --- |
| GizmoSession | session lifecycle, identity, transcripts, memory, tools, and recovery in `friend/` |
| Body | hardware protocol; firmware not in this slice |
| Glass | character display renderer |
| Memobase | persistent user memory, self-hosted on Railway |
| Web | public site in `web/`; not the device |

Frozen prompt is in `friend/gizmo_friend/prompt.py` and `docs/FRIEND.md`. Do not invent a second personality.
