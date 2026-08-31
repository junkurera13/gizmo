# Friend

Laptop brain. Realtime talk, sqlite memory, six verbs. This is the only place agent code lives.

Run from the **repo root** (see root `README.md`).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
gizmo                  # http://127.0.0.1:43147
gizmo --cli            # keyboard in the terminal
pytest
```

- `OPENAI_API_KEY` — live OpenAI Realtime (`gpt-realtime-2.1-mini`)
- without a key — fake transport, same state machine and tools
- `OPENROUTER_API_KEY` — optional deep-think fallback (no realtime speech)
- `GIZMO_THINK_MODEL` — optional reasoning model for `think()` (default `gpt-5.6-terra`)
- `FAL_KEY` — optional MiniMax H3 Max clips for `show()`
- `GIZMO_DATA_DIR` — sqlite + pages (default `./data`)

Architecture: `docs/FRIEND.md`. Product: `docs/PRODUCT.md`. Craft: `docs/CRAFT.md`.
