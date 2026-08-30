# Friend

Laptop brain. Realtime talk, sqlite memory, four tools. This is the only place agent code lives.

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
- `FAL_KEY` — optional MiniMax H3 Max clips for `show()`
- `GIZMO_DATA_DIR` — sqlite + pages (default `./data`)

Architecture: `docs/FRIEND.md`. Product: `docs/PRODUCT.md`.
