# Friend

Gizmo brain. Gemini Live, Memobase-backed persistent memory, transcripts, and typed tools. This is the only place agent code lives.

Run from the **repo root** (see root `README.md`).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
gizmo                  # http://127.0.0.1:43147
gizmo --cli            # keyboard in the terminal
pytest
```

- `GEMINI_API_KEY` — Gemini 3.1 Flash Live plus Gemini 3.7 Flash for `deep_think()`
- without a key — fake transport, same state machine and tools
- `MEMOBASE_URL` / `MEMOBASE_API_KEY` — self-hosted Memobase on Railway
- `GIZMO_USER_ID` — stable owner/device identity across sessions
- `GIZMO_DATA_DIR` — final transcript JSONL and transitional device data (default `./data`)

Architecture: `docs/FRIEND.md`. Product: `docs/PRODUCT.md`. Craft: `docs/CRAFT.md`.
