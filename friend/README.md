# Friend

Gizmo brain. Gemini Live, the silent visual director and Show providers, Memobase-backed persistent memory, transcripts, and typed tools. This is the only place agent code lives.

Run from the **repo root** (see root `README.md`).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
gizmo                  # http://127.0.0.1:43147
gizmo --cli            # keyboard in the terminal
```

- `GEMINI_API_KEY` — required. Gemini Live voice, plus Oddity speech and transcription
- `GIZMO_DIRECTOR_MODEL` — optional visual-director override; default `anthropic/claude-haiku-4.5` through Fal
- `FAL_KEY` — Klein 9B stills, H3 Max motion, Claude director and `deep_think()` reasoning; required for visuals and planning
- `MEMOBASE_URL` / `MEMOBASE_API_KEY` — self-hosted Memobase on Railway (without them, memory is off)
- `GIZMO_USER_ID` — fallback identity for bodies that send no `X-Gizmo-Device` header (the browser harness); real bodies identify themselves
- `GIZMO_DATA_DIR` — final transcript JSONL (default `./data`)

Architecture: `docs/FRIEND.md`. Product: `docs/PRODUCT.md`. Craft: `docs/CRAFT.md`.
