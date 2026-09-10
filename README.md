# Gizmo

Gizmo is a first computer for kids, built around an AI friend that brings explanations to life with words, drawings, and videos, all generated in real time. Kids steer the conversation; Gizmo creates what the moment needs, blending learning and storytelling into playful experiences.

Read [`docs/PRODUCT.md`](docs/PRODUCT.md) for the full product vision and priorities, and the [manifesto](https://oddware.xyz/gizmo/manifesto) for why we're building it. Real-time video generation is the highest-priority feature of that vision; the implementation described below is the current prototype.

A wizard in a kid's pocket. One face, one voice, one coat. Kids 9–14. Dry, a little weird, warm underneath. He says the one line that matters and lets the kid steer; a story or a walkthrough runs longer, in chapters they pull. Magic is a chore he's good at.

This repo is the device: GizmoSession (brain), Body (XIAO firmware bring-up), Glass (device renderer), and the native emulator. The public site lives in `web/`.

**v1 runs on a laptop.** The Mac emulator speaks the same WebSocket contract firmware will use. The XIAO already runs a local terminal OS (boot, home, Settings, voice memo) without that socket; Wi-Fi and Friend transport are still to come. Gemini 3.1 Flash Live handles realtime voice and vision; Gemini 3.1 Flash-Lite silently chooses words, still, motion, or animate; Memobase supplies persistent user memory; Gemini 3.7 Flash is available only through `deep_think()`.

## Tree

```
docs/PRODUCT.md   product principles
docs/FRIEND.md    current brain architecture and runtime contract
docs/V1.md        what v1 is and is not
docs/ROADMAP.md   from held prototype to magic
docs/SPRINT.md    the next eleven days: Blueprint II application, due Sep 14
docs/SHOW.md      Show: design and build plan
docs/ODDITY.md    OddityOS 1 browser simulator: run, architecture, and limits
docs/DEMO.md      the 90-second film: script, staging, what's real
friend/           GizmoSession, providers, Gemini transport, and server
body/             XIAO ESP32S3 Sense firmware, hardware notes, protocol reference
glass/            device renderer assets
simulator/        native macOS emulator
friend/gizmo_friend/oddity/  browser experience director and runtime
web/              public site (Next.js on Vercel, /gizmo)
```

## Run (Mac / Linux)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env   # then set GEMINI_API_KEY and FAL_KEY
gizmo                  # http://127.0.0.1:43147
```

Or: `python -m gizmo_friend` from a venv with this repo installed.

### Env

| Variable | Required | What |
| --- | --- | --- |
| `GEMINI_API_KEY` | yes | Gemini Live voice conversation, plus Oddity speech and transcription. All separate planning, reasoning, and generated media use Fal. Gizmo has no offline brain; if Gemini is unreachable he reports the outage and retries. |
| `FAL_KEY` | for visuals and planning | Klein 9B images, Cinema (H3 Max Director), Claude director and reasoning. |
| `GIZMO_DIRECTOR_MODEL` | no | Visual-director override. Default `anthropic/claude-haiku-4.5` through Fal. |
| `GIZMO_USER_ID` | optional | Fallback identity for a body that sends no `X-Gizmo-Device` header. Each device otherwise gets its own memory. |
| `MEMOBASE_URL` | for persistent memory | Root URL of the self-hosted Railway Memobase service. |
| `MEMOBASE_API_KEY` | for persistent memory | Memobase project token. |
| `GIZMO_DATA_DIR` | no | Final transcript JSONL. Default `./data`. |

### Talk to him

**OddityOS 1 browser simulator:** run `gizmo --host 127.0.0.1 --port 43148`, then open [localhost:43148/oddity](http://127.0.0.1:43148/oddity). This richer client coordinates generated narration, drawings, and Cinema films in connected beats. It uses the same server environment and Cinema runtime as Friend, with its own browser session and experience director. See [`docs/ODDITY.md`](docs/ODDITY.md).

**Native emulator:** launch `Gizmo Simulator.app`. **Power on** cold-boots Gizmo. Hold **PTT** while talking; release to send. **Up** from home opens Settings (brightness and volume); Friend owns that menu so every protocol body paints the same snapshot. Down from home opens the Mac camera world; its live viewfinder is local preview only. The pink button sends only 24 kHz microphone PCM over the body WebSocket; the backend resamples it to Gemini's 16 kHz input. XIAO firmware, including a local Settings/memo OS that does not yet speak `/ws`, is in `body/firmware/`. Pins and acceptance notes are in `body/hardware/`.

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

Railway contains four services: `gizmo-brain`, `memobase`, `postgres`, and `redis`. The complete Singapore-region project is declared in `.railway/railway.ts`. Railway manages the database credentials and volumes; its Postgres 18 image includes pgvector. `gizmo-brain` has its own persistent `/data` volume for transcripts. Memobase uses Claude Haiku 4.5 and Qwen3 Embedding 8B through Fal's OpenAI-compatible endpoint; no Google calls or separate OpenAI account are needed. Existing embeddings must be regenerated before changing embedding models.

After creating and linking an empty Railway project, provision it with:

```bash
npm install
npx @railway/cli config plan
npx @railway/cli config apply
npx @railway/cli up --service memobase
npx @railway/cli up --service gizmo-brain
```

Set `GEMINI_API_KEY`, `FAL_KEY`, and a randomly generated `GIZMO_DEVICE_TOKEN` on `gizmo-brain`, and a random `ACCESS_TOKEN` plus the Fal key as `MEMOBASE_LLM_API_KEY` on `memobase`, using Railway secrets rather than source files. The IaC file marks those values with `preserve()` so future applies retain them. Generate a public Railway domain for `gizmo-brain` after its first healthy deployment; Postgres, Redis, and Memobase remain on Railway's private network. All public device/data routes require the device token; `/health` is the only unauthenticated cloud route.

## Tools and Show

Gemini Live can call only `deep_think(question)` and the placeholder `set_expression()` bus (not the character). Google Search is Gemini's native grounding tool, not a custom search function. A separate structured visual director reads the same final user utterance and silently chooses words, a still, or a Cinema film (H3 Max Director). Stills use FLUX.2 Klein 9B on Fal. Moving explanations and moving story scenes use Cinema, not Fal image-to-video. Friend does not grow a short clip; “make it move” keeps the still. Explicit standalone visual requests start directing before narration completes. Google has no image-generation fallback.

## Who owns what

| | |
| --- | --- |
| GizmoSession | session lifecycle, identity, transcripts, memory, tools, and recovery in `friend/` |
| Body | XIAO ESP32S3 Sense firmware (local terminal OS today; Friend `/ws` next), hardware notes, protocol reference |
| Glass | character display renderer |
| Memobase | persistent user memory, self-hosted on Railway |
| Web | public site in `web/` on Vercel; not the device |

Frozen prompt is in `friend/gizmo_friend/prompt.py` and `docs/FRIEND.md`. Do not invent a second personality.
