# Sprint — Blueprint II application, due Sep 14

Written Sep 3 for that window. The tree has moved: XIAO firmware is a local
terminal OS, Friend owns a Settings overlay on the protocol path, Show is
wired, and `web/` is on Vercel. This file is the application plan of that
week, not the current hardware or Settings contract. Current firmware:
`body/firmware/README.md`. Current wire: `body/README.md`.

Founders, Inc. Blueprint II. Hardware and frontier tech, 3 months in SF starting
Sep 30, $150k for 5%. Applications close **Sep 14, 11:59 PM PST**
(that is 3:59 PM Sep 15 in Tokyo). Rolling review — earlier is better; hear back by Sep 20.
Program: https://f.inc/blueprint · FAQ: https://f.inc/blueprint/faq

Long-horizon roadmap is `docs/ROADMAP.md`. This file is only the next eleven days.

## Two lanes

| Lane | Owner | Delivers by Sep 12 |
| --- | --- | --- |
| **Body** | Cofounder (EE) | An ESP32-S3 board in a shell that speaks the body protocol to the Railway brain: buttons, mic, speaker, glass, camera. His call on kit, parts, and firmware stack. |
| **Brain + glass + story** | Jun | Show wired, face that reacts, panel-ready frames for the body, waitlist, kid tests, demo video, the application itself. |

The lanes meet at one contract, below. Everything the software side owes the body is in
that section; the rest of this file is the software lane and the application.

## What the brain owes the body (contract, freeze by Sep 6)

The body needs nothing from the brain that doesn't already exist, except panel-sized
images. Firmware should never have to decode a 1024×742 PNG or resize anything.

- **Protocol as-is.** WebSocket `/ws`, JSON wire contract in `body/README.md`:
  `power` / `ptt` / `navigate` / `select` / `frame` / `audio` in; `audio` / `state` /
  `glass` / `error` out, plus `hello` and control/transcript events. `mic` is an
  input compatibility alias; new firmware should use `audio`. PCM16 little-endian
  mono 24 kHz base64 both ways, without a WAV header. PTT down, PCM, and PTT up
  must use the same socket in that order. `Authorization: Bearer
  $GIZMO_DEVICE_TOKEN` and `X-Gizmo-Device: <chip id>` on the handshake.
- **Glass stream.** Everything that appears on the glass — state frames and Show — is
  announced as a `glass` event carrying a URL, and the body fetches it at its own size
  (`?w=320&h=240`). Stills come as one JPEG; clips come as a JPEG frame loop
  (`.mjpeg`) the body decodes with esp_jpeg and loops from local storage.
  This is a finite sequence of JPEGs with frame count, fps and dimensions in the
  `X-Gizmo-Frame-*` response headers. Start the selected board at the 24 fps source
  maximum and step down only if measured performance requires it. The saved 5.167 s
  rocket is **124 frames / 2,502,648 bytes** at 320×240 / 24 fps and 62 frames /
  1,250,954 bytes at 12 fps; use measured size for the memory
  budget. Requests include the same device authorization and `X-Gizmo-Device`
  headers as the socket. No panel setting on the server. The simulator now uses
  the same finite MJPEG route through an explicit provisional 320×240 / 24 fps /
  4 MiB profile, keeps compressed frames, and decodes one at a time.
- **Reference client.** Checkpoint 2 now provides the Python protocol-v1 client in
  `body/reference/`: authenticated health/hello compatibility, stable identity,
  every physical control edge, real macOS microphone/speaker adapters,
  authenticated still/MJPEG fetching, bounded queues, and local wake audio replayed
  after a fresh PTT edge on reconnect. Panel dimensions are explicit provisional
  inputs until the screen is selected. This is an executable handoff, not firmware.
- **One health page.** `/health` now publishes protocol v1, canonical events and media
  limits so the body can assert what it is talking to. It does not publish a panel
  size while no panel has been selected.

Anything not in this list, the body owner decides.

## Where we are (Sep 3)

| | State | Blueprint reads it as |
| --- | --- | --- |
| Brain | Done and deployed. Live voice, audio-only PTT, deep_think, per-device memory, sleep/wake, Railway. Camera input is deliberately unwired pending See interaction design. | Real engineering. Good. |
| Glass | Boot splash, start card, home = one static frame + clock + hearts. Face does not react to listen / talk / think. | A voice chatbot with a picture. |
| Show / Make | Not wired. Prompt tells him he can't make media. | The pitch ("Infinite Disney in a pocket") is not in the demo. |
| Body | Wire contract plus checkpoint-2 laptop reference client with bounded real I/O and reconnect. No firmware, board, or shell. | The software handoff is executable; the physical body is still the gap. |
| Web | Hero + "Register Interest" linking to nothing. Not deployed. | No motion, no waitlist. |
| Kids | `data/transcripts/` is empty. No kid has used him. | No evidence anyone wants this. |

Blueprint I's cohort: Pixar-lamp desk robot, screen-free AI tutor for kids, "physical AI
companions." Gizmo is squarely their kind of thing. What they fund is a person who has
already put a real object in a kid's hand, not a person who is going to.

## What "magical" means for this application

Three things, in priority order. Everything else waits.

1. **A held object.** A kid holds a thing, presses the pink button, talks, and his face on
   the glass answers. No laptop in the frame.
2. **He conjures.** The kid asks about something real and the answer takes the form it
   should — words, a picture, or a picture that moves — with nobody choosing. In the
   video: a rocket that lifts while he talks. That is the beat no other kid device has.
3. **He remembers.** Day two, he picks up what they left hanging. Already works; show it.

If the demo video has those three beats, the application is strong. If it has a Mac
window with a device render, it is a software application to a hardware program.

## The eleven days

### Sep 3–5 (Thu–Fri): Show first, because it's where the unknowns are

Show is the beat that makes this not another voice toy, and it carries the risks we
can't schedule around: image latency inside a live turn, whether the print look holds,
how Live behaves while a tool takes several seconds. Nobody is waiting on the body
contract until a board exists, so Show goes first.

- **Show: words, a picture, or a moving picture — his call.** Full plan in
  `docs/SHOW.md`. The judgment is in the prompt; the pipeline makes whichever he chose
  arrive mid-sentence. A still lands ~4 s after the call (Gemini
  `gemini-3.1-flash-image`, ~$0.07); when he asked for motion, a 5 s loop grown from that
  still lands ~6 s later (fal H3 Max image-to-video, ~$0.25 at list, 75% off until
  Sep 7). "Make it move" animates the still that's up. Thursday night is the still;
  Friday is motion; Show is not done until he has all three answers. Tools return
  instantly and generate in the background, so his voice never waits and a failure is
  silent — the answer already stood alone.
- **Body decides its size.** Stills and clips are served resized on request
  (`/shows/...?w=&h=`), so there is no panel setting on the server. The simulator and
  board supply their explicit provisional or selected profile. Both device views use
  the finite JPEG frame loop (`.mjpeg`); the MP4 remains a source master.
- **Prompt.** Replace "Image and video generation are not available yet" with the Show
  judgment from `docs/CRAFT.md`. He never announces the picture; it is just there.
- **Measure.** PTT release → still on glass, and → motion, ten asks each. Those two
  medians choreograph the demo video.
- **Contract** (previous section) is Saturday's work, once the board is picked.

### Sep 6–9 (Sat–Tue): make him alive, get him in hands

- **Contract frozen (Sep 6).** Show media stays on the authenticated `glass` stream;
  cold-boot/home assets come from the configurable offline bundle in `body/assets/`.
  The reference loaders live in `body/reference/`, and `/health` advertises protocol
  and media limits without claiming an unselected panel. Sent to the body lane.
- **Face reacts.** Preview frames for `listen`, `talk`, `think`, `asleep` in
  `glass/sprites/` driven by the state events the brain already emits. Two or three
  frames each is enough (eyes, mouth). `talk` can flip mouth frames on output audio
  amplitude — the simulator already has the PCM. This is the temporary hook the glass
  README describes, not the character architecture; do not build an expression enum.
- **Make.** `keep(line)` tool saves the last shown still plus the kid's line to
  `data/cards/<device>/`. "Show me my card" brings it back. Small once Show exists.
- **Body checkpoint (Sep 9).** Board talks to the Railway brain on a desk: PTT hold →
  spoken answer → a frame on the panel. Whatever isn't working, we know which lane it's
  in because the reference client either reproduces it or doesn't.
- **Waitlist live.** `web/` gets a real email form (Vercel + a KV or a Google Sheet, no
  backend to babysit), deployed at the domain. One line of copy from `PRODUCT.md`.
- **Kid test #1.** Two or three kids, 9–14, on the simulator if the board isn't up.
  Ten minutes each, no script. Record (with permission). Save transcripts. Write down
  the one moment each kid's face changed.

### Sep 10–12 (Wed–Fri): shell, video, draft

- **Shell (body lane).** Whatever reads as the device on camera: yellow body, pink side
  button, speaker grille. Ugly seams are fine. The software lane's only ask is that the
  render in `simulator/DeviceSkins/current/` and the real shell agree on where the
  glass sits.
- **Fix the skin.** Redraw the simulator screen rectangle to the real panel's aspect so
  the simulator and the board show the same frame. If the board isn't talking by
  Sep 11, the video is shot on the simulator and the application says so plainly.
- **Demo film, 90 s.** Script, staging rules, and honesty labels in `docs/DEMO.md`.
  One kid, one evening and one morning, every verb, none announced. Pre-warm the shows
  from real runs (`GIZMO_DEMO_CACHE`) so the timing is ours. Shoot the board running the
  real cloud brain. Cut on Sep 12.
- **Application draft.** Problem, why now (realtime multimodal + memory in one model,
  cheap ESP32-class silicon), what's built, what's not, kid-test findings and quotes,
  the team (one on the brain and character, one EE on the body — say it plainly, it's a
  strength here), BOM and rough unit cost from the body lane, what $150k buys (DVT,
  first 100 units, kid pilots), why SF. Link the video, the site, the repo if public.
  Do not pitch a feature list; pitch the one character and the three beats.

### Sep 13–14 (Sat–Sun): submit early

- Kid test #2 on the real body. Photos of hands holding it.
- Submit **Sep 13**. Rolling review means Sep 13 beats Sep 14. Keep Sep 14 for
  anything that broke.

## Not in this sprint

A second clip per show, clips over 5 s, Play / games, Reach, parent view, a character
animation architecture, Google Search citation metadata, binary WebSocket frames, a
second personality anywhere.
Board, parts, and firmware choices are the body lane's, not this file's.
`docs/V1.md` exclusions still hold except Show and Make, which this sprint adds.

## Cut order if we fall behind

Software lane, drop in this order: Make → `animate` → face frames beyond two per state
→ waitlist polish → health-page extras. Never drop: the glass stream and reference
client (the body lane is blocked without them), Show with motion (a still alone is a
chatbot with a picture; the rocket lifting is the pitch), the demo video with a real kid,
submitting on time. If fal is unusable by Sep 11, the fallback is stills and the
application says so — a failure to report, not a version to plan for.

## Definition of done

A stranger watches the video and can say what Gizmo is in one sentence, believes it
exists, and wants to hand one to a kid they know.
