# Roadmap — from held prototype to magic

Where this goes: a pocket someone who can conjure anything — explain with a custom
video, tell a story that draws itself, eventually make a game on the spot.
"Infinite Disney in a pocket." No menus, no apps. You talk; he does.

Rules that never change: one face, one voice, voice switches everything,
the screen serves the moment and then gets out of the way.

The current sprint (Blueprint II application, Sep 14) is `docs/SPRINT.md`. It pulls
the first slice of 2 and the first slice of 4 forward; the order below is otherwise unchanged.

## 0 — Alive (done)

He has a lifecycle, not just a socket.

- Power on → boot moment → home: the glass is his face (Jun's art, when it lands)
- Face reacts to listen / talk / think once the character architecture exists
- Auto-sleep after 2 idle minutes, like a phone
- Conversation, see, memory that survives restart. Show / make / reach are next, not done.

## 1 — Feels like a someone

Close the gap between "demo" and "friend." Mostly polish, highest leverage.

- Real voice by default (`.env` key loads everywhere, including the Dock app)
- Judgment that holds in live talk: easy questions from the hip, hard ones through think, visual ones through show
- Jun's hand-drawn face on the glass. Character animation architecture is after the design, not before.
- One button, one meaning: PTT only ever means talk; sleep is idle-only; the top toggle is for cold boot and hard shutdown
- Interrupt is instant; silence is comfortable; he never repeats his greeting
- Memory that carries days: "remember the pinecone" actually lands

**Magic bar:** a kid talks to him for ten minutes about nothing and wants to come back tomorrow.

## 2 — Show becomes conjuring

The first real spell. Show stops being a still and becomes a custom clip.

- Explore H3 Max only when Adaptive Media work begins; it is outside the brain V1
- "How did the rocket take off?" → he talks while a short clip he conjured plays on the glass
- Print look holds: stylized, never photoreal, never their face
- Cache clips, cap spend, degrade gracefully to the still when the cloud is slow

**Magic bar:** a kid asks about something real and gets a moving answer no one else has ever seen.

## 3 — Infinite Disney

One clip becomes a told world. Stories that draw themselves.

- Multi-beat stories: his narration drives a sequence of conjured clips
- The kid steers by voice mid-story; he adapts without breaking stride
- Stories can be kept (Make) and sent home (Reach)
- Still in chapters the kid pulls, never a stream. A storyteller, not a TV.

**Magic bar:** "tell me a story about my dog on the moon" produces something worth keeping.

## 4 — Out of the laptop

The body catches up to the brain.

- ESP32-S3 firmware in `body/`: top power toggle, pink PTT, up/down rocker, Select, mic, speaker, world camera, 69 × 50 mm landscape glass
- See uses the real camera; boot/home/sleep run on the device
- Reach lands on an actual parent phone, not a local outbox
- Battery honesty: auto-sleep tuned for hardware, wake is instant

**Magic bar:** hand it to a kid with no laptop in the room and everything above still works.

## 5 — Infinite Steam (parked)

Conjured games — "make me a maze" and the rocker plus Select play it. Parked on purpose
until stories prove the conjuring pipeline. Same shape: no store, no menu, just ask.

## Order of operations

1 and 2 can run in parallel (polish is brain-side, conjuring is tool-side).
3 needs 2. 4 is independent but expensive — start when 2 feels magic.
5 waits its turn.
