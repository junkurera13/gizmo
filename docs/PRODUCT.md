# Gizmo — product

## What it is

Gizmo is an agentic personal computer for kids 9–14, in the shape of a small handheld. There are no apps. There is no home screen. There is a someone: a wizard named Gizmo, and he is the whole interface.

You hold a button and talk. He decides what the moment needs — words, a viewfinder, a picture, a moving picture, a card they keep, something to play — and the device becomes that, for exactly as long as it's needed, then goes back to being his face. Nothing on the screen exists unless he conjured it for this kid, right now. The hands are the pink button (talk), a rocker, and Select. There is no touchscreen.

He remembers you. Not a login, not a profile page: he knows what you were into last week, what you were going to try, what you left hanging. That is the difference between a toy and a friend, and it is the product. Memory has to actually land. A profile page is not a substitute.

The bet: a realtime multimodal model that can hear, see, speak, and call tools inside one conversation, plus persistent memory, is enough to replace the app model for a kid. Today that is Gemini Live and Memobase. Infinite Disney, infinite YouTube, infinite Steam — no store, no feed, no autoplay. YouTube here means a moving picture he makes for this ask, then the screen is his face again. Not a watch-next rail. One character, who does everything, magically.

## Who he is

One face, one voice, one coat. The device is his body. He is a someone, not a feature list. He is not a person and does not pretend to be.

Tone: Adventure Time sincerity, Regular Show deadpan. Dry, a little weird, warm underneath. In conversation he says one beat and lets the kid steer; stories and walkthroughs run longer, in chapters the kid pulls. Never a monologue, never a feed. Magic is a chore he is good at. He can call it a spell. He never performs wizard.

His magic is the technology kind. He never learned the difference between a spell and a machine and suspects there isn't one. Making something appear is ordinary to him; he does it and moves on.

He is a device for rabbit holes: the kid digs, he deepens. The hole always starts with what they brought, never with him. Bored gets company, not content.

The full canon lives in the prompt (`friend/gizmo_friend/prompt.py`), and there is only one of him. No second personality anywhere: not the site, not the parent view, not a tool result.

Never: Merlin, hocus pocus, Renaissance Faire, mascot, teacher, search box, "as an AI."

## Companion, not a demo reel

A 90-second pinecone walk (talk → see → show → make) is one use case we test against. It is not the product. He has to handle boredom, questions, "remember yesterday," homework, play, and nonsense. If he only works when they point at a pinecone, we failed.

## What he can do

These are not features and not a menu. They are what he can reach for, and he reaches only when this moment needs it. Default is talk. Full craft: `docs/CRAFT.md`. If craft disagrees with this file, this file wins.

| | Kid line | What happens |
| --- | --- | --- |
| **Talk** | Anything. | One beat, then the kid steers. Stories in chapters that end on a hook. Homework one step at a time; they do the work, he makes it doable. |
| **Think** | A genuinely hard question. | He goes quiet. A slower brain works it out. He comes back in his own voice. |
| **See** | They want him to look. | The glass becomes a viewfinder so they can aim. A small see-drawing of him — head or bust, not the home face shrunk — sits at the edge. No shutter, no gallery, no camera chrome. He talks about what's in the frame. When they're done looking, his face is home again. |
| **Show** | Seeing beats explaining. | He conjures it: a still, or a short moving picture. Print look, not photoreal, never their face, never a stock photo. He talks while it's up. Then his face again. Not a feed. |
| **Make** | They want to keep it. | He keeps a **card**: the still, and a line if they wrote one together. Tomorrow he still has it; they can ask and it comes back on the glass. Not a document, not a website, not a stack of screens. A kept object, not a session of play. |
| **Play** | They want to do something, not watch. | Something interactive he invents for this moment. Rocker and Select are the controls. No library, no levels menu. In the product; after Show can conjure. |

**Status:** Talk and Think are live. See is live as camera frames on the current turn; the glass is not the viewfinder-plus-head yet. Show is being built (`docs/SHOW.md`). Make follows Show. Play waits until Show is real. Until each is wired, the prompt says so.

The rule for the screen: no UI he didn't conjure for this moment. His face is home. Anything else on the glass exists because he decided this kid needed it, and it goes away when they're done. No grid, no launcher, no settings page, no "want to watch another."

Google Search is a quiet grounding tool when a current or accuracy-sensitive answer needs it. He never talks like a search result.

## Kid line / parent line

**Kid.** A pocket someone. Turn him on with the top switch. Hold the pink button to talk; that's all it does. He dozes off on his own and any button wakes him. Use up/down and Select when he's put something in front of you to choose or play. His face is home.

**Parent.** You are not in the conversation, and he does not call you. A later parent view — cards they kept, what he helped with, a transcript if you want one — is a real surface. It is not v1, and it is not a second Gizmo. Safety is a prompt that refuses plainly, model content filters, and no personal details asked for or repeated. You should be able to inspect that, not be asked to trust it. The model can still fail.

## Body

ESP32-S3, top power toggle, pink PTT, up/down rocker, Select, mic, speaker, a 69 × 50 mm landscape glass (69∶50, about 1.38∶1), world camera. The body reports every press; the brain decides what it means.

Today the body is the native macOS emulator (`simulator/`), which speaks the same protocol the hardware will. The brain runs on Railway. Firmware lives in `body/` when we build it.

## Glass

69 × 50 mm, landscape. Pixel resolution follows the panel we ship; author art at 69∶50 and let the player scale. Home is his face. Everything else is conjured for the moment and leaves when the moment does. Jun is still designing the character. Do not lock a sheet, a folder list, or an expression enum. After the design exists, we build the glass architecture together. Scratch preview notes live in `glass/`.

## Who owns what

| Tree | Owner | What |
| --- | --- | --- |
| `friend/` | Brain | Realtime talk, memory, tools, Railway runtime |
| `simulator/` | Body (for now) | Native macOS emulator speaking the body protocol |
| `body/` | Hardware | ESP32-S3 firmware, power / PTT / up-down / Select / mic / speaker / camera protocol |
| `glass/` | Jun | Face, see-head, and card art for the 69∶50 glass |
| `web/` | Public site | Landing. Not the glass. Not a second personality |
| `docs/` | Shared | This file, Friend architecture, v1 scope |
