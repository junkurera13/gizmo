# Show — build plan

The first real spell. A kid asks something that seeing answers better than telling, and
while he talks, a picture he made appears on the glass — and if it's the kind of thing
that moves, it moves. Then his face again.

He has three ways to answer any ask: words, a picture, a moving picture. **He chooses,
from the ask.** That judgment lives in the prompt, not in code; the code's job is to make
whichever he chose arrive seamlessly. A moving picture is made in two stages — a first
frame from an image model, then a clip grown from that frame — because the frame lands in
~4 s and the clip in ~10 s, and the kid should not look at a black glass for his whole
beat. A still picture is stage one alone.

This is the design and the build plan for the version that ships in the sprint
(`docs/SPRINT.md`). The craft — what the kid experiences and what he never does — is the
Show section of `docs/CRAFT.md`; this file is how we build it. If they ever disagree, fix
whichever one is wrong, not the code.

**V1 checkpoint update (Sep 3, Jun):** generation time is measured, not a pass/fail
requirement. The timings below describe the intended beat, not a speed gate for V1.
Short, accurate labels or essential numbers are welcome when they help explain the
subject, such as in a biology diagram or map. Text is judged for usefulness and
readability on the glass; its presence alone is not a failure.

## The beat, from the kid's side

1. Hold pink. "How does a rocket actually take off?"
2. Release. He starts answering within a second, in his voice, one beat.
3. Three to five seconds into his answer, the glass changes: a picture of a rocket on the
   pad, in his print look. He does not announce it. He does not say "look." It is just
   there, the way a wizard's things are just there.
4. Around ten seconds in, while he is still talking or just after, the picture moves: the
   flame catches, smoke pours, the rocket lifts. Same picture — it came alive. Five
   seconds of motion, looping, silent. He is the only sound.
5. He finishes his beat and stops. The moving picture stays. The kid watches it.
6. The kid asks about a part of it; he answers. It stays.
7. The kid presses Select, or asks about something else and he draws that instead, or he
   dozes off — and his face is home again.

Three rules from that: he never narrates the magic, the show is never load-bearing
(if nothing comes his answer already stood alone; if the motion fails the first frame
stands), and the kid decides when it leaves, not a timer.

## What is true today

- `GeminiLiveTransport` declares tools as BLOCKING or NON_BLOCKING from
  `tools/allowlist.py`; NON_BLOCKING results go back with `SILENT` scheduling.
  `deep_think` is BLOCKING (Live waits); `set_expression` is NON_BLOCKING.
- `GizmoSession._run_tool` runs the tool inline and submits its result. Nothing runs in
  the background yet except memory writes.
- The simulator already handles `{"type":"glass","still":"<path>"}` by fetching that
  path from the brain (with the device token) and, while `viewing` is true, drawing it
  full-screen with `.interpolation(.none)` and 10 pt of padding. The brain currently
  never emits it and has no route to serve a still.
- The prompt says "Image and video generation are not available yet."
- `CRAFT.md` (Show) says: words, a picture, or a moving picture — he picks; "make it
  move"; arrives while he talks; one look forever; one per ask; never load-bearing; the
  kid decides when it goes. `PRODUCT.md` puts the small head-at-the-edge on See, not Show.

## Design

### The tool

```
show(subject: string, motion?: string)
animate(motion: string)
```

`subject` is *what to depict*, a concrete noun phrase with the one detail that matters:
"a rocket on the launch pad at night, flame just starting under it." Not style, not a
paragraph. Style is ours, fixed, and never in Live's hands.

`motion` is *what happens*, one short phrase: "flame and smoke pour out as it slowly
lifts." Given when the point of the ask is what the thing *does*; left out when the point
is what it *is* — a trilobite, a heart's chambers, a map. The choice is his, from the ask,
and the prompt teaches it. The pipeline never decides; it makes what he chose.

`animate` is the second wish. A still is on the glass and the kid says "make it move" (or
he judges, mid-answer, that it should) — stage two runs on the picture already up, same
frame, same id. No `subject`; there is nothing to redraw. Returns
`{"ok": false, "reason": "nothing up"}` if no still is showing.

Both declared NON_BLOCKING. The brain answers the call **immediately** with
`{"ok": true, "status": "conjuring", "subject": ...}` and `SILENT` scheduling, then
generates in a background task. Live never waits on the picture, so his voice never
stalls, and we do not depend on how Gemini behaves while a slow async tool is in flight.
If generation fails, nothing appears and nobody says anything; the answer was already
complete. Show is additive by construction.

Why not BLOCKING with a beat first: that is Think's shape ("Hold on. Big one."), and it
makes the kid wait for a picture. Why not return the result when the image lands with
`WHEN_IDLE`: it invites a second turn where he describes the picture he just made, which
is exactly the narration we don't want.

### Stage one: the first frame

`friend/gizmo_friend/brain/images.py`, same shape as `memory.py` and `reasoning.py`.
The still is the whole answer when he didn't ask for motion, and the first frame of the
clip when he did. Same object either way, which is what makes `animate` free.

```
class ImageProvider(ABC):
    async def conjure(self, subject: str) -> ConjuredStill | None
class NullImageProvider     # no key → Show declared but returns "unavailable"
class GeminiImageProvider   # gemini-3.1-flash-image, 512px, 4:3, JPEG out
```

- Model `gemini-3.1-flash-image` (Nano Banana 2). 512px is the smallest it makes and is
  plenty for a ~320×240 panel; 4:3 is the closest supported ratio to the 69∶50 glass.
  About $0.07 a picture. `gemini-3.1-flash-lite-image` is an optional later speed
  experiment (1K only, faster), not required for V1 acceptance.
- Same `google-genai` client as `deep_think`. No new dependency for generation; Pillow
  for resizing (new, small).
- Kid safety settings from `safety.py` on the request, plus the style prefix below,
  which also carries the content rules.
- Hard timeout 12 s. Past that the still is dropped, not shown late.
- Never given the camera frame. Show draws the subject, not the room or the kid.

### Stage two: it moves

`friend/gizmo_friend/brain/clips.py`, same provider shape:

```
class ClipProvider(ABC):
    async def animate(self, still: bytes, motion: str) -> ConjuredClip | None
class NullClipProvider    # no FAL_KEY → stills only; degraded, logged loudly
class H3MaxClipProvider   # fal `minimax/h3-max/image-to-video`
```

- **H3 Max on fal**, image-to-video, first frame = our still. Launched Sep 1: a 5 s clip
  in ~3 s of inference, ~6 s end to end in hands-on tests. Output follows the input's
  aspect ratio, so a 4:3 still gives a 4:3 clip. 24 fps.
- **480p, 5 s** (the minimum duration). 480p is already more than a ~320×240 panel can
  show. List price $0.05/s → **$0.25 a clip**; 75% off until Sep 7 ($0.06). Plan on
  list. 768p is $0.08/s and buys nothing on this glass.
- Runs when `show` carried `motion`, or on `animate`. For `show`, it starts the moment
  the still is on disk and its glass event is sent. A tracked background continuation
  renders the clip while the picture stays up. For `animate`, it starts on the still
  already up. Neither waits for generation before acknowledging the tool call.
- Motion prompt = a fixed prefix + the model's `motion` phrase. The prefix holds the
  look and the restraint: keep the exact style, palette and composition; lock the
  camera; keep the subject fully in frame; limit whole-subject travel to five
  percent of the frame; prevent progressive enlargement and spreading smoke;
  preserve shapes, proportions and stationary educational labels; add no objects,
  text or faces; make no cuts. Use natural repeating motion, never reverse a
  physical process merely to force a loop. The exact prefix lives in `clips.py`
  and is preserved with each generated result.
  `prompt_expansion_mode: "disabled"` — we do not want fal's rewriter adding
  cinema. The API rejects the literal string `"off"` (verified Sep 3).
  `enable_safety_checker` on.
- The clip's audio is discarded at transcode. He is the only voice in the room.
- Hard timeout 20 s. Past that the still simply stays.
- A clip is shown **only if its still is still on the glass**. If the kid dismissed it,
  or a newer subject replaced it, the clip is dropped (saved to disk, never shown).
  Motion arriving into a different conversation is a bug; the still rule already covers
  the kid's own ask catching up.
- An in-flight or completed clip is reused for repeated `animate` requests against
  that still; only one clip is generated per show. A reconnect snapshot includes both
  the still and clip URLs when that clip is currently visible.

Why two stages instead of text-to-video in one shot, now that video is fast: the frame
lands in ~4 s and the clip in ~10 s, and those six seconds are the difference between
"something appeared while he talked" and "the glass was black for his whole beat." The
image model also holds the look far more reliably than a video model prompted from text,
and the clip inherits it for free because our still *is* its first frame — so the clip is
the picture coming alive, not a second picture. And it is what makes still and moving
one system rather than two: same object, same look, same route, and "make it move" is
just stage two arriving late. The still is also the kept object for Make and the
fallback when fal is slow.

### The look

A fixed prefix the model never sees or changes, applied to every subject. Proposal:

> Flat-color print illustration, like a risograph or screenprint: two or three spot inks
> on a dark ground, bold simple shapes, visible paper grain, no gradients, no photoreal
> rendering, no logos, no human faces, no children. Short, accurate labels or essential
> numbers only when they help explain the subject; sparse and readable on a small
> screen. No decorative writing, titles, or captions. One subject, centered, filling
> the frame. Landscape.

Dark ground on purpose: the glass is black and sits in a bezel. A white paper still
flashes; a dark one feels like the glass itself changed. Whether the inks are his coat
(purple, pink) or a fixed print palette (ochre, moss, ink) is Jun's call — see questions.
Whichever it is, it is *one* palette for every still, forever, so his pictures are
recognizably his.

Always the same ratio and same size. If the model returns something else, we crop, not
letterbox.

### Storage and delivery

Everything is saved at source size and served sized for the asker, so the body decides
its own panel:

```
data/devices/<device>/shows/<id>.jpg           still, 512×384
data/devices/<device>/shows/<id>.mp4           clip master, 640×480 24 fps, audio stripped
data/devices/<device>/shows/<id>.json          {subject, motion, prompts, created, session}
GET /shows/<device>/<id>.jpg?w=320&h=240        still, cover-cropped, cached
GET /shows/<device>/<id>.mp4                    clip master as-is (later a phone)
GET /shows/<device>/<id>.mjpeg?w=320&h=240&fps=24   clip as a JPEG frame sequence (body and simulator)
```

- Routes require the device token like everything else. A body fetches only its own.
- The `.json` sidecar is what makes Make trivial later: keeping a card is tagging a show
  with a line, not a new pipeline.
- Sizing on request means no `GIZMO_PANEL` setting on the server. The simulator sends
  its explicit provisional profile; the ESP32 sends its selected panel profile.
  Cover-crop; never distort.
- **MJPEG for the body.** An ESP32-S3 will not decode H.264, but it can decode
  panel-sized JPEG frames. Start physical profiling at the 24 fps source maximum
  and step down only when the selected board/panel misses timing, memory or input
  responsiveness. The saved 5.167-second rocket produced 62 frames / 1,250,954
  bytes at 12 fps and 124 frames / 2,502,648 bytes at 24 fps, both 320×240. Budget
  from measured payloads, not the original ~600 KB estimate. The brain transcodes once with a bundled
  ffmpeg (`imageio-ffmpeg` wheel; no apt in the image) and caches per size. This is a
  line item in the body contract (`SPRINT.md`): the glass plays a frame loop, not just
  one frame.
- The MJPEG response is a finite, concatenated JPEG sequence (`video/x-motion-jpeg`),
  with frame count, frame rate and dimensions in `X-Gizmo-Frame-*` headers. Defaults
  remain 320×240 at 12 fps for an unspecified caller; the provisional simulator/body
  profile explicitly requests 320×240 at 24 fps. Accepted dimensions are 1–1024 pixels
  and frame rates 1–24.
  The client downloads the sequence and paces its loop; this is not a live multipart
  camera stream. MP4 supports byte-range requests for the simulator player.

### Events on the bus

```
{"type":"glass","still":"/shows/<device>/<id>.jpg","subject":"…","viewing":true}
{"type":"glass","clip":"/shows/<device>/<id>.mp4","frames":"/shows/<device>/<id>.mjpeg","viewing":true}
{"type":"glass","viewing":false}
```

First when the still is on disk; second when the clip is (same `id`, so the body knows
it belongs to what's already up); third when the show leaves. The simulator already
understands `still` and `viewing:false`; `clip` is new.

### When the show leaves

The kid decides. Still or clip, it stays through his answer and through follow-ups about
it. It leaves on:

- **Select.** "Selects the focused item or interrupts output" — here it dismisses what
  he put in front of you. Rocker and Select are for when he has put something on the
  glass; this is that.
- **A new still.** One subject on the glass at a time; the new one replaces the old
  with no gap to black.
- **Sleep or power-off.** Obviously.
- **Idle.** No interaction for 90 s while a still is up → home. Sleep would take it
  anyway at 120 s; this just returns his face a little earlier.

Not on: the end of his turn, a fixed hold, the next PTT press. A kid who asks "what's the
red part?" must still be looking at the red part when he answers.

In-flight generation when the kid moves on: the **still** lands unless it was superseded
by a newer `show`, or the device slept or powered off — a picture arriving a few seconds
into the next exchange is the kid's own ask catching up. The **clip** lands only onto its
own still (see stage two). Nothing ever animates a picture the kid is no longer looking
at.

### Grounding his follow-ups (optional, test it)

When the still lands, hand the finished image to Live as a pending frame (the same
`send_image` path camera frames use), so "what's that bit?" is answered from the actual
picture. Costs some input tokens per turn while a still is up. Try it; keep it if it
makes follow-ups better and doesn't slow the first reply.

### Prompt

Replace the "not available yet" line. Proposal for the CAPABILITIES and JUDGMENT blocks:

> You have three ways to answer: words, a picture, or a moving picture. Pick from the
> ask; never offer the choice. Most asks are words. show(subject) puts a picture you made
> on the glass — use it when the point is what something is or how it's laid out: a
> creature, a machine's parts, a map, a place. show(subject, motion) makes it move — use
> it when the point is what something does: a rocket lifting, a heart beating, a wave
> breaking, a story's new place with weather or life in it. `motion` is one short phrase
> of quiet motion; nothing new enters the scene. animate(motion) makes the picture already
> on the glass move, when they ask for that or it should. Call these at the start of your
> answer, then keep talking — it arrives on its own while you speak. Never announce it,
> never say "look" or "here's a picture," never describe what you made. It is just there.
> One per ask. Never for feelings, small talk, people, or the kid themself.

> JUDGMENT: ... Something with a look: show, then talk. Something that does something:
> show with motion, then talk. A story chapter opening on a new place: show (with motion if
> the place is alive), then tell.

Stories are included deliberately: one show per chapter, as a chapter opens a new place,
is the "story that draws itself" from `ROADMAP.md` §3 at its smallest true size, and it
is the most magical thing this can do on the demo video.

### Spend

At list: a still is ~$0.07, motion adds ~$0.25. A picture is $0.07; a moving picture or
an `animate` is ~$0.32. (75% off on fal until Sep 7; plan on list.)

- Per device: 40 shows a day and 20 motions a day (~$7.80 worst case). Past the show
  cap, `show` returns `{"ok": false, "reason": "quiet day"}` silently and the answer
  stands alone. Past the motion cap, `motion` is dropped and the still shows; `animate`
  returns `quiet day`. He is never told a number; he just finds the well dry.
- Global: env-set daily ceilings on stills and motions across the whole brain.
  `GIZMO_DAILY_SHOW_LIMIT` defaults to 400; `GIZMO_DAILY_MOTION_LIMIT` defaults to 200.
  Zero disables that generation stage; zero motions still allows pictures.
- Counters are reserved before provider calls under file locks in `show-usage.json`
  and `motion-usage.json` at the shared data root, with mirrors in each device's data
  directory. Restarts and concurrent sessions share the same UTC day. Failed or
  superseded requests still count; no automatic retry spends another slot.
- Two vendors, two keys: `GEMINI_API_KEY` (already) and `FAL_KEY` (new, Railway secret).
  No `FAL_KEY` or fal down → stills only, nothing said to the kid, a loud warning in the
  logs. That is a degraded brain, not a mode.

### Glass rendering (simulator)

- The physical device is the priority. Simulator APIs are display adapters;
  user-visible behavior must also be implementable on the board. No simulator-only
  effects, and a successful Mac preview does not establish hardware performance.
- Full-bleed, cover-cropped, no padding. Default interpolation, not `.none` — this is a
  picture, not pixel art.
- Still arrival and departure: direct frame swap, with no transition or sound.
  Sep 3 update from Jun: keep the simulator faithful to the physical device;
  defer fades until they are proven on the board and panel.
- Clip arrival: **no transition.** Frame 0 of the clip is the still, so the clip simply
  starts playing where the still was. If it looks like a cut, the transcode or crop is
  wrong, not the design. The native device view keeps the still up while it fetches
  the authenticated finite MJPEG, retains compressed JPEGs under the profile cap,
  decodes one frame at a time and loops silently at the requested rate.
- Time and battery belong only to home, never to another screen. Home is a separate
  view, not an overlay; pictures and video own the whole glass.
- No head at the edge for Show. That is See's device. The picture owns the glass.
- **No conjuring state.** Between the call and the picture, the glass is his face, same
  as always. No spinner, no shimmer, no glance. Nothing on the glass ever says "loading";
  the first sign that anything happened is the picture.
- Request size = the explicit preview/body profile, so the simulator and board can
  request and compare the same crop at the same fps.

## Sequence

Each step ends at a checkpoint you can see. If a checkpoint fails, stop and rethink
before the next. Steps 1–7 are the still and are tonight's work; 8–12 are motion and are
Friday's. Show is not done until step 11: without motion he has two ways to answer, not
three.

Current execution status: **checkpoint 11 native playback and the subsequent H5
hardware-preview checkpoint pass with the saved rocket clip; stopped for review.**
The device screen now ignores the MP4 playback URL and requests the matching finite
MJPEG through the authenticated device request. It holds the still until the complete
bounded sequence is ready, decodes one JPEG at a time, loops silently, and stops on
Select. Home's time/battery never overlays the video. There are no transitions or
player controls. Stale frame downloads cannot attach to another still. Reconnect
snapshots handle both URLs in one event.

The actual Gemini Live session chose `show` with motion from a voiced sample sent
through the device audio connection. Media providers replayed the existing rocket
still/clip; zero new image or fal generations, and no new automated tests. The native
log recorded still display, muted playback, a completed loop, and player teardown.
A 7.48-second recording shows the actual app. This verifies native playback, not
new generation speed, human microphone input, or physical-board playback.
The explicit provisional profile is 320×240 at 24 fps with a 4 MiB encoded cap.
The saved rocket delivered 124 JPEGs totaling 2,502,648 bytes and completed its
first native loop in 5,168 ms against a 5,167 ms target. This is Mac evidence for
the hardware-shaped path, not the physical board's limit; the same profile sweep
still needs to run with the selected board and panel under Wi-Fi, audio and button
load. Checkpoint 4's Sep 5 prompt-only evaluation did not clear repeatability after
the planned three-revision limit: the full isolated run reached 18/20 raw choices,
but a targeted repeat sent the Silk Road map back to words. The fallback is now
implemented. Gemini 3.1 Flash-Lite makes one structured words/still/motion/animate
decision from each final user utterance; Gemini Live no longer receives the visual
tools, so the two models cannot compete. Invalid, incomplete, late, or timed-out
decisions degrade to words without spending media, and explicit no-motion sentinels
degrade to a still. A displayed still is staged into Live for the next visual
follow-up and cleared when Show leaves the glass.

The final direct-director matrix scored 20/20 at 1.042 s median, including five of
five repeated Silk Road still-map choices and the existing-still `animate` route.
A real Gemini Live integration with a replayed trilobite still confirmed the picture
arrived while Live spoke and bare “Make it move” emitted no transcript or audio.
No still or clip generations ran during either evaluation. Checkpoint 4 is cleared
for the silent-director architecture. Measurements 6/12 and
optional grounding 7 remain pending. No deployment was made. Evidence:
`data/hardware-audit/2026-09-04/show-24fps/results.json` and
`data/show-checkpoints/2026-09-04-checkpoint-11/REVIEW.md`, plus ignored local
evidence in `data/show-checkpoints/2026-09-05-checkpoint-4/`.

Checkpoint 5 native still display was implemented and
visually verified, then stopped for review before native video playback. The rebuilt
app requests its actual screen size, fills the glass without padding, keeps home
visible until the image is decoded, and returns to home on Select. Time and battery
are part of home only. Jun removed the planned fade: frame swaps are direct until
effects are proven on the physical board. One real image was generated; no fal
request or new automated test was added. The spoken sample was fed through the
device audio WebSocket after the Mac's mic did not understand its own playback.
The native app displayed the image after the reply, in `listening`, not mid-speech;
generation took 9.89 seconds. Generation time remains a V1 measurement, not a gate.
The complete human-microphone-to-image check and physical-board rendering are still
unverified. Native video was subsequently completed in checkpoint 11 above.
No deployment was made.
Evidence: `data/show-checkpoints/2026-09-03-checkpoint-5/REVIEW.md`.

Checkpoint 10 passed local wiring checks with replayed media. The actual CLI and real Gemini
Live selected `show` with motion for the rocket, still-only `show` for trilobite,
and `animate` for "make it move". Still and clip events kept the same ID. Dismissing
an in-flight clip saved its result without displaying it. Both tools are
NON_BLOCKING / SILENT; the 20-motion device cap and global motion ceiling persist
across restarts. After Jun requested a leaner suite, seven focused regression
checks remain for spending and stale clips; the checkpoint originally ran 59.
A dialogue correction was checked in Live:
no offering the picture afterward, and a bare "make it move" is a silent action.
The existing rocket clip was replayed; trilobite motion used a synthetic static
fixture solely to verify lifecycle, not video quality. Zero new fal or image
generations. All verification CLI sessions exited; no deployment was made.
Evidence: `data/show-checkpoints/2026-09-03-checkpoint-10/REVIEW.md`.

Checkpoint 9 passed locally: the existing rocket clip was saved without audio
and served by both protected routes. Curl received MP4 HTTP 200 (and 206 for a
byte range), plus 62 MJPEG frames at 320×240 / 12 fps. All 41 tests passed. No fal
generation was needed, and the isolated verification server was stopped afterward.
Evidence: `data/show-checkpoints/2026-09-03-checkpoint-9/REVIEW.md`.

Prior checkpoint decision: **checkpoint 8 accepted for V1 after Jun's visual
review** ("it looks good"). The rocket launch is a useful moving illustration;
strict stationary motion is not a V1 acceptance gate. Prompt adherence and the
visible loop reset remain known limitations. Acceptance covers the reviewed
rocket sample, not untested subjects or educational-label stability. Stopped
before the next checkpoint; no additional generation was authorized.

Execution history, Sep 3: checkpoints 1 and 2 reviewed and cleared. Checkpoint 3
initially failed because the real CLI rocket ask produced no `show` call. At
Jun's request, the minimal still-capability correction was brought forward from
step 4. The same real CLI ask now calls `show`, produces a saved JPEG and glass
event while talking, and Select dismisses it. Checkpoint 3 passed; stopped for
review before the full step 4 judgment prompt and twenty-question evaluation.
Evidence: `data/show-checkpoints/2026-09-03-checkpoint-3-retry/REVIEW.md`.

Jun then prioritized video and asked to continue to the next checkpoint, bringing
step 8 (clip provider alone) forward. The missing-key preflight was resolved using
Jun's existing Cast key, copied to the private local `.env` and Railway's
`gizmo-brain` production variables without triggering a deployment. Jun reduced
the test to **one clip** because credits are limited; the other nine are deferred.

One rocket clip was generated: 640×480, 24 fps, 5.17 seconds, 5.31 seconds end to
end. The initial `"off"` parameter was rejected with zero billable units; the
correct API value `"disabled"` produced the single clip (five billed seconds).
Its look and starting composition survive, but the rocket leaves the frame and
smoke expands substantially, exceeding the restrained-motion brief. **Checkpoint
8 is not cleared.** Stopped for Jun's review without another generation request.
Steps 4–7 and 9–12 remain pending. Do not generate additional clips until Jun
authorizes more; the current sample can be inspected without spending credits.
Evidence: `data/show-checkpoints/2026-09-03-checkpoint-8/REVIEW.md`.

On Jun's next "continue", the motion prefix was tightened and a revised rocket
brief prepared. Jun then explicitly approved one additional test clip. Exactly
one request ran (5.421 seconds end to end, five additional billed video-second
units). Despite the instruction to hold the rocket fixed and confine exhaust and
smoke, the rocket still leaves the frame and the smoke spreads. **Checkpoint 8
failed again.** Two rocket clips have been generated in total; the additional
one-clip approval is consumed. Stopped for review, with no further requests and
no work on step 9.
Review: `data/show-checkpoints/2026-09-03-checkpoint-8/motion-revision/generated/REVIEW.md`.

1. **Still provider alone.** `images.py` + a throwaway script in `/tmp` that conjures
   ten subjects and writes JPEGs. *Checkpoint:* look at the ten. Is the look right?
   Record median latency without a V1 speed gate. Any human faces? If there is text,
   does it help explain the subject, is it accurate, and can it be read on the glass?
   This decides the style prefix before any plumbing exists.
2. **Storage and route.** Save + sidecar + `GET /shows/...jpg?w=&h=` with cover-crop and
   disk cache. *Checkpoint:* curl a still at three sizes.
3. **Tool wiring.** `show` in the allowlist as NON_BLOCKING; `_run_tool` returns
   immediately and spawns the background task; `glass` events; leave rules (Select,
   new show, sleep, power, idle). *Checkpoint:* `gizmo --cli`, type "how does a rocket
   take off", see `glass` events on the bus and a JPEG on disk.
4. **Prompt.** Swap the capability and judgment lines. *Checkpoint:* twenty text asks in
   the CLI — five that want words, five a picture, five a moving picture, five stories —
   and count: did he pick the right form each time? Is every `motion` phrase quiet and
   true to the subject (no cinema, no new objects)? Did he ever announce it? Then say
   "make it move" to a still and check he calls `animate`, not `show`. Fix the prompt
   until all of it is clean. This step is the product; the rest is plumbing.
   *Bar:* right form on 17 of 20, zero announcements, after at most three prompt
   revisions. If the Live model can't clear it, do not keep tuning — the fallback is a
   **silent director**: a Flash text call on Live's input transcription that decides
   `show`/`animate` itself, fired the moment the transcript lands, with the still fed
   back to Live as a frame so he can talk about it. Live keeps the voice; the director
   keeps the judgment. Stop and report before building it.
5. **Simulator, still.** Full-bleed, direct frame swap, home hidden, request at screen size.
   Remove the `.interpolation(.none)` and padding. *Checkpoint:* ask him out loud, watch
   the picture land while he is still talking.
6. **Measure.** Ten spoken asks, PTT release to still on glass. Write the median in
   `SPRINT.md`. That number choreographs the demo video.
7. **Grounding (optional).** Pending-frame handoff; ask "what's the red part?" five
   times with and without. Keep or cut.
8. **Clip provider alone.** `clips.py` + a `/tmp` script that animates the ten stills
   from step 1 with hand-written motion phrases. *Checkpoint:* watch the ten. Does the
   look survive motion? Does frame 0 match the still? End-to-end latency? Anything the
   prefix should forbid? Get a fal key and set the Railway secret first.
   *Sep 3 scope update from Jun:* test one rocket clip for now; defer the other
   nine because fal credits are limited. Generation time remains a measurement,
   not a V1 acceptance gate.
9. **Transcode and routes.** Strip audio; `.mp4` as-is; `.mjpeg?w=&h=&fps=` frame
   sequence, cached per size. *Checkpoint:* curl both; count frames in the mjpeg.
10. **Wire and gate.** Stage two runs after the still is saved when `motion` is set, and
    on `animate` against the still that's up; `glass` clip event; the "only onto its own
    still" gate; motion cap. *Checkpoint:*
    "how does a rocket take off" in the CLI → still event, then clip event ~6 s later
    with the same id. Then dismiss the still before the clip lands and confirm it's
    dropped. Then "what did a trilobite look like" → still only; "make it move" → clip
    event on that same id.
11. **Simulator, clip.** The native device view uses the authenticated finite MJPEG
    path, retains compressed frames under the explicit preview cap, decodes one frame
    at a time, loops silently, and makes no transition from the still. *Checkpoint:*
    ask out loud; the picture appears mid-beat and starts moving a few seconds later
    with no visible cut.
12. **Measure again.** Ten spoken asks with motion: release → still, release → motion.
    Both medians into `SPRINT.md`.

## Not in this

A second clip for the same ask, clips longer than 5 s, 768p, clip audio, Make (Saturday,
but the sidecar is ready for it), a head at the edge, a shutter or gallery, any UI on top
of a show, editing a show ("make it bigger," "add a dragon"), shows from camera frames,
a second style.

## Open questions for Jun

1. **Palette.** His coat (purple/pink inks on black) or a print palette (ochre/moss/ink on
   dark paper)? One choice, then it never changes. Whatever it is, the clip inherits it
   from the still, so this is decided once. *Default if unanswered before step 1: his
   coat — it ties every picture to him and to the yellow body with the pink button.*
   Step 1's ten test stills will show whether it holds; switch there or never.
2. **Stories.** One show per chapter as a new place opens — yes? $0.07–0.32 a chapter at
   list depending on whether the place moves. The best demo beat we have.
3. **Select dismisses.** Comfortable with Select meaning "put your face back" while a
   show is up? It fits "rocker and Select are for when he's put something in front of
   you," but it is a new meaning for the button.
4. **Grounding the follow-ups.** Worth the tokens, or keep the still out of his context
   and let him answer from the subject he chose?
5. **Caps.** 40 shows and 20 motions a device a day (~$7.80 worst case at list) — say if
   you want other numbers.
6. **Two vendors.** Stills from Gemini, motion from fal. It is the right split today (fast
   video lives on fal; the still keeps the look controllable and lands first), but it is
   a second key, a second bill, and a second thing that can be down. Fine for the sprint?
