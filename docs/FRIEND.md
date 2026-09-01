# Friend — laptop brain

Friend is Gizmo's mind for v1. It runs on a laptop. Hardware is later. All agent code lives in `friend/`.

## Talk path (latency-critical)

Not STT → LLM → TTS. One realtime speech-to-speech session.

- **API:** OpenAI Realtime, WebSocket
- **Model:** `gpt-realtime-2.1-mini`
- **Reasoning:** `reasoning.effort = low`
- **Prompt:** frozen system prompt (see below) is a **cacheable prefix** — stable, front of context. Memory is appended after it, never before.
- **Audio:** streaming mic → model → speaker. Target: first audio under 1s.
- **Interrupt:** pressing push-to-talk while Gizmo speaks barges in and cancels the response.
- **Voice:** built-in realtime voice now. `Mouth` is an interface so a Cartesia mouth can replace playback later without a rewrite.
- **Key:** `OPENAI_API_KEY`. If missing, a **local fake transport** still runs the state machine and tools so tests and an offline demo work.

## Frozen system prompt

Do not invent a second personality. The prefix lives in `friend/gizmo_friend/prompt.py`. It is not paraphrased at runtime. Memory is appended after it, never before.

Voice: dry, a little weird, warm underneath. Two sentences, then stop. Magic is a chore he's good at. He never performs wizard.

Care: he shows it by paying attention, not by gushing. One small question back when curious. Never two.

Judgment: easy → talk. Hard → think. Visual → show. Keep it → make. Ask to send it home → reach. Craft: `docs/CRAFT.md`.

## Tools (same session, not a second agent)

Allowlist only. No web search. No extras.

| Tool | Behavior |
| --- | --- |
| `see(image)` | Name what's in the outward frame in one beat. Fast. Camera is stubbed; inject a frame from the laptop. |
| `show(subject)` | Still first (fast, local print look). Then up to **two** short clips. fal MiniMax H3 Max behind an interface; if `FAL_KEY` is missing, skip clips but still do the still + the spoken line. Never a third clip, never a player, never photoreal, never the kid's face. |
| `make(line)` | Persist a page (object + one line) in sqlite. Instant. Recall later. |
| `think(question)` | Slow brain. Realtime voice is fast and shallow; this calls a reasoning model (`GIZMO_THINK_MODEL`, default `gpt-5.6-terra`) and returns a short kid-true answer Gizmo re-voices. Fail-soft if the key is missing. Never for chat or feelings. |
| `reach()` | Queue that page to the parent-phone outbox (`reach/`). Not a live call. Fail soft. |

## Memory (not three slots)

Local sqlite, survives restart. Path: `$GIZMO_DATA_DIR` or `./data/gizmo.db`.

- **identity** — name + small list of facts they told us
- **running_summary** — ≤500 tokens, rewritten at end of session
- **episodes** — timestamped what happened
- **objects** — saved pages

On wake: inject identity + running_summary + last few episodes + object index into the prompt **after** the frozen prefix. Never block first audio on retrieval (local file, loaded at process start and on remember).

**Remember-this path:** during a session, a name or a "remember that…" / "I have…" line updates identity and episodes immediately. No waiting for shutdown.

## States

`powered_off` → `booting` → `listening` ⇄ `talking`, plus soft `asleep` and tool states `thinking`, `seeing`, `showing`, `making`, `reaching`.

| Input | Effect |
| --- | --- |
| Top **power** toggle | On cold-boots the device. Off is a hard shutdown. |
| Pink **push-to-talk** button | Tap while powered on to sleep or wake. Hold to stream 24 kHz PCM; release to commit the voice turn. |
| **Up / down** rocker | Move the focused item vertically. Left/right navigation does not exist. |
| Circular **select** button | Select the focused item or interrupt output. It never opens the camera. |
| Screen | Face on whenever he's awake. A still covers the face only during show / a saved page. |

## Body protocol (stub)

Laptop keys and the clickable render stand in for the body. The protocol (`Power`, `PushToTalk`, `Select`, `Navigate(up/down)`, `Frame`, `Mic`) is what `body/` firmware will speak later. Friend does not contain firmware. Camera capture comes from the agent's visual path, never a select-button gesture.

## Open conversation

He has to work when they are bored, asking questions, saying "remember yesterday," playing, or talking nonsense. Tools fire only when the moment needs them. Memory is used, not dumped.
