# Gizmo

A wizard in a kid's pocket. One face, one voice, one coat. Kids 9–14. Dry, a little weird, two sentences then stop. Magic is a chore he's good at.

This repo is the device: Friend (brain), Body (firmware later), Glass (jun's 240×240 art later), Reach (parent-phone outbox). The public site lives in `web/`.

**v1 runs on a laptop.** Click the stick (space / button) to wake him. Talk with the mic or by typing. Hold to send a page home. The 90-second pinecone walk is a use case, not the product — he also has to handle boredom, questions, "remember yesterday," play, and nonsense.

## Tree

```
docs/PRODUCT.md   companion + six verbs
docs/CRAFT.md     what he actually does — talk / think / see / show / make / reach
docs/FRIEND.md    realtime talk, memory, tools, states, frozen prompt
docs/V1.md        what v1 is and is not
docs/ROADMAP.md   from held prototype to magic
friend/           THE laptop brain — all agent code
body/             ESP32-S3 firmware later (README only)
glass/            1.54" 240×240 page/blit (jun drawing the face)
reach/            parent-phone outbox stub
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
| `OPENAI_API_KEY` | for live voice | OpenAI Realtime, model `gpt-realtime-2.1-mini`. Also powers `think()`. If missing, a local fake transport still runs the state machine and tools. |
| `OPENROUTER_API_KEY` | no | Deep think fallback when `OPENAI_API_KEY` is unset. No realtime speech — live voice still needs the OpenAI key. |
| `GIZMO_THINK_MODEL` | no | Reasoning model for hard questions. Default `gpt-5.6-terra` (`openai/gpt-5.6-terra` via OpenRouter). |
| `FAL_KEY` | no | MiniMax H3 Max image-to-video for `show()` clips. If missing, he still does the still and the spoken line. |
| `GIZMO_DATA_DIR` | no | sqlite + saved pages. Default `./data`. Survives restart. |

### Talk to him

**Browser (laptop body stub):** open the URL. Space or **Stick** wakes / interrupts / sleeps. Type a line or turn **Mic** on. **Hold to reach** (or `R`) queues the current page to the parent outbox. **Point** injects a world-camera hint (there is no ESP32 camera yet).

The glass is 240×240 and **off** unless he is showing or you are looking at a saved page. No player UI. At most two clips.

**Terminal:** `gizmo --cli`

```
> /click              wake
> I'm Maya
> I have a dog named Toast
> /look a pinecone on the table
> what is this
> show me
> keep it
> /reach
> /click              sleep
```

## Memory

Sqlite at `$GIZMO_DATA_DIR/gizmo.db` (or `./data/gizmo.db`).

- identity: name + facts they told him
- running summary (rewritten when he sleeps)
- timestamped episodes
- objects: saved pages

Tell him your name and a fact, quit, start again. He still has it. He will not dump memory at you.

## Pinecone use case (not the whole product)

1. Wake. If he doesn't know the name, he asks once.
2. Point the camera at a pinecone (`/look a pinecone` or the Point field).
3. Ask what it is — `see`.
4. Ask him to show it — still, then at most two clips, print look. Screen off. Something like "Yeah. That's the whole spell."
5. Keep a page — `make`. "Yours. I don't lose stuff."
6. Hold the stick — `reach`. The page is in `data/outbox.jsonl`, not a live call.

Then talk about nothing. If he only works for the pinecone, we failed.

## Tests

```bash
pytest
```

State machine, memory round-trip, tool allowlist (no web), prefix assembly (frozen prompt first), interrupt, open conversation + pinecone path on the fake transport.

## Who owns what

| | |
| --- | --- |
| Friend | realtime brain in `friend/` |
| Body | hardware protocol; firmware not in this slice |
| Glass | jun's face and pages; do not lock a character sheet |
| Reach | parent phone; local outbox only in v1 |
| Web | public site in `web/`; not the device |

Frozen prompt is in `friend/gizmo_friend/prompt.py` and `docs/FRIEND.md`. Do not invent a second personality.
