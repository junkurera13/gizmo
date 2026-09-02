# Gizmo — product

Gizmo is a handheld wizard for kids 9–14. One face, one voice, one coat. The device is his body. He is a someone, not a feature list.

Tone: Adventure Time sincerity, Regular Show deadpan. Dry, a little weird. Two sentences, then stop. Magic is a chore he is good at. He can call it a spell. He never performs wizard.

Never: Merlin, hocus pocus, Renaissance Faire, mascot, teacher, search box, "as an AI."

## Companion, not a demo reel

A 90-second pinecone walk (talk → see → show → make → reach) is one use case we test against. It is not the product. He has to handle boredom, questions, "remember yesterday," play, and nonsense. If he only works when they point at a pinecone, we failed.

## Six verbs

Used only when this moment needs them. Default is talk. Full craft: `docs/CRAFT.md`.

| Verb | Kid line | What happens |
| --- | --- | --- |
| **Talk** | Anything else. | Two sentences. Then stop. |
| **Think** | A genuinely hard question. | He goes quiet. A slower brain works it out. He comes back in his own voice. |
| **See** | They point the world camera. | He names what's there in one beat. Screen stays his face. |
| **Show** | They want to see it his way. | One still, then up to two short clips, print look (not photoreal, never their face). Screen on, then off. He talks. |
| **Make** | They want to keep it. | One page: the still plus one line they wrote together. Tomorrow he still has it. |
| **Reach** | They ask to send the page home. | That page lands on a parent's phone. He is not a phone. Not a live call. |

No unsolicited feed or browsing theater. Google Search is a quiet grounding tool when a current or accuracy-sensitive answer needs it.

## Kid line / parent line

**Kid.** A pocket someone. Turn him on with the top switch. Hold the pink button to talk; that's all it does. He dozes off on his own and any button wakes him. Use up/down and Select when there is something to choose. His face is home. The screen is for the page, not for a UI.

**Parent.** A page can show up on your phone. That is Reach. You are not in the conversation. He does not call you. You can look at what they kept.

## Body (later)

ESP32-S3, top power toggle, pink PTT, up/down rocker, Select, mic, speaker, 1.54" 240×240 glass, world camera. Firmware lives in `body/` when we build it. v1 brain runs on a laptop; the body protocol is stubbed.

## Glass

240×240. Screen-on only for showing and for a saved page. Jun is drawing the face by hand; do not lock a character sheet here. Assets and blit notes live in `glass/`.

## Who owns what

| Tree | Owner | What |
| --- | --- | --- |
| `friend/` | Brain | Realtime talk, memory, tools, laptop runtime |
| `body/` | Hardware | ESP32-S3 firmware, power / PTT / up-down / Select / mic / speaker / camera protocol |
| `glass/` | Jun | Face and page art, 240×240 blit |
| `web/` | Public site | Landing. Not the glass. Not a second personality |
| `docs/` | Shared | This file, Friend architecture, v1 scope |
