# Gizmo

A wizard in a kid's pocket. One face, one voice, one coat. Kids 9–14. Dry, a little weird, two sentences then stop. Magic is a chore he's good at.

This repo is the device: GizmoSession (brain), Body (firmware later), Glass (device renderer), and the native emulator. The public site lives in `web/`.

**v1 runs on a laptop.** The existing emulator connects to the same WebSocket contract the eventual ESP32-S3 body will use. Gemini 3.1 Flash Live handles realtime voice and vision; Memobase supplies persistent user memory; Gemini 3.7 Flash is available only through `deep_think()`.

## Tree

```
docs/PRODUCT.md   product principles
docs/FRIEND.md    current brain architecture and runtime contract
docs/V1.md        what v1 is and is not
docs/ROADMAP.md   from held prototype to magic
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
pip install -e ".[dev]"
cp .env.example .env   # optional
gizmo                  # http://127.0.0.1:43147
```

Or: `python -m gizmo_friend` from a venv with this repo installed.

### Env

| Variable | Required | What |
| --- | --- | --- |
| `GEMINI_API_KEY` | for live agent | Gemini 3.1 Flash Live and Gemini 3.7 Flash `deep_think()`. If absent, the local fake transport keeps device flows testable. |
| `GIZMO_USER_ID` | recommended | Stable owner/device identity across separate sessions. |
| `MEMOBASE_URL` | for persistent memory | Root URL of the self-hosted Railway Memobase service. |
| `MEMOBASE_API_KEY` | for persistent memory | Memobase project token. |
| `GIZMO_DATA_DIR` | no | Final transcript JSONL and transitional device data. Default `./data`. |

### Talk to him

**Native emulator:** launch `Gizmo Simulator.app`. **Power on** cold-boots Gizmo. Tap **PTT** to sleep or wake; hold it while talking. Use **Up**, **Down**, and **Select** for device UI. Camera frames and 24 kHz PCM travel over the existing body WebSocket; the backend resamples mic audio to Gemini's 16 kHz input.

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

Railway contains four services: `gizmo-brain`, `memobase`, `postgres`, and `redis`. The complete Singapore-region project is declared in `.railway/railway.ts`. Railway manages the database credentials and volumes; the Postgres resource uses the pgvector image required by Memobase. `gizmo-brain` has its own persistent `/data` volume for transcripts.

After creating and linking an empty Railway project, provision it with:

```bash
npm install
npx railway config plan
npx railway config apply
```

Set `GEMINI_API_KEY` on `gizmo-brain`, and `ACCESS_TOKEN` plus `MEMOBASE_LLM_API_KEY` on `memobase`, using Railway secrets rather than source files. The IaC file marks those values with `preserve()` so future applies retain them. Generate a public Railway domain for `gizmo-brain` after its first healthy deployment; Postgres, Redis, and Memobase remain on Railway's private network.

## Tools

The model-facing V1 functions are `deep_think(question)` and `set_expression(expression)`. Google Search is Gemini's native grounding tool, not a custom search function. `make`, `reach`, `see`, `show`, and the old text-router fallback are not part of the active agent. `show_image()` and `show_video()` exist only as future interfaces; no Adaptive Media pipeline is implemented.

## Tests

```bash
pytest
```

Tests cover the device state machine, PTT pre-roll, 24→16 kHz conversion, Gemini event mapping, native Search configuration, camera forwarding, transcript persistence, provider memory flow, and fail-soft controls.

## Who owns what

| | |
| --- | --- |
| GizmoSession | session lifecycle, identity, transcripts, memory, tools, and recovery in `friend/` |
| Body | hardware protocol; firmware not in this slice |
| Glass | character display renderer |
| Memobase | persistent user memory, self-hosted on Railway |
| Web | public site in `web/`; not the device |

Frozen prompt is in `friend/gizmo_friend/prompt.py` and `docs/FRIEND.md`. Do not invent a second personality.
