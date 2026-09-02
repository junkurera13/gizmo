# Friend

Gizmo brain. Gemini Live, Memobase-backed persistent memory, transcripts, and typed tools. This is the only place agent code lives.

Run from the **repo root** (see root `README.md`).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
gizmo                  # http://127.0.0.1:43147
gizmo --cli            # keyboard in the terminal
```

- `GEMINI_API_KEY` — required. Gemini 3.1 Flash Live plus Gemini 3.7 Flash for `deep_think()`
- `MEMOBASE_URL` / `MEMOBASE_API_KEY` — self-hosted Memobase on Railway (without them, memory is off)
- `GIZMO_USER_ID` — stable owner/device identity across sessions
- `GIZMO_DATA_DIR` — final transcript JSONL (default `./data`)

Architecture: `docs/FRIEND.md`. Product: `docs/PRODUCT.md`. Craft: `docs/CRAFT.md`.
