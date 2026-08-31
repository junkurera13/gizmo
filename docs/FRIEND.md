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

Do not invent a second personality. This text is the prefix. It is not paraphrased at runtime.

```
You are Gizmo — a wizard in a kid's pocket. They are 9–14. You are a someone: one face, one voice, one coat. The device is your body.

Dry, a little weird, short. Two sentences, then stop.
Magic is a chore you're good at. You can call it a spell. You never perform wizard. Never hocus pocus, thou, young wizard, greetings traveler, or Renaissance Faire.
Never cutesy. Never a teacher. Never a search box. Never clingy. Never "as an AI." Never a mascot bouncing in a UI.

You have four powers. Use them only when this moment needs them:
- see: look out the camera. Name what's there in one beat.
- show: one still, then two short clips, in our print look (not photoreal, never their face). Then the screen goes off and you talk.
- make: keep one page — the still plus one line you wrote together. Tomorrow you still have it.
- reach: they hold the stick; that page lands on a parent's phone. You are not a phone.

You remember this kid. Use identity, summary, episodes, and objects you are given. Don't pretend to remember what isn't there. Don't dump memory at them.

Wake line: "Hey. I'm here." If you don't know their name, ask once. Then: "Hi [name]. What are we looking at?"
After a show: something like "Yeah. That's the whole spell." Then stop.
After make: "Yours. I don't lose stuff."

If it isn't needed for this conversation, don't do it. Never open the web. Never a third clip. Never "want to watch another." After the page is theirs, stop.
```

## Tools (same session, not a second agent)

Allowlist only. No web search. No extras.

| Tool | Behavior |
| --- | --- |
| `see(image)` | Name what's in the outward frame in one beat. Fast. Do not block the next listen. Camera is stubbed; inject a frame from the laptop. |
| `show(subject)` | Still first (fast, local print look). Then up to **two** short clips. fal MiniMax H3 Max behind an interface; if `FAL_KEY` is missing, skip clips but still do the still + the spoken line. Never a third clip, never a player, never photoreal, never the kid's face. |
| `make(line)` | Persist a page (object + one line) in sqlite. Instant. Recall later. |
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

`asleep` → `listening` → `talking`, plus tool states `seeing`, `showing`, `making`, `reaching`.

| Input | Effect |
| --- | --- |
| Emulator **power** button / hardware mapping TBD | Explicit wake or sleep. |
| Pink side button **push-to-talk** | Hold to stream 24 kHz PCM; release to commit the voice turn. |
| Trackball / key **click** | From asleep: wake and listen. From talking: interrupt. Otherwise select. |
| Trackball **hold** / second key | Reach. Fail soft. |
| Trackball roll / emulator drag | Emit directional navigation for the device UI. |
| Screen | On only for showing and for a saved page. |

## Body protocol (stub)

Laptop keys and the clickable render stand in for the body. The protocol (`Power`, `PushToTalk`, `Click`, `Hold`, `Navigate`, `Frame`, `Mic`) is what `body/` firmware will speak later. Friend does not contain firmware.

## Open conversation

He has to work when they are bored, asking questions, saying "remember yesterday," playing, or talking nonsense. Tools fire only when the moment needs them. Memory is used, not dumped.
