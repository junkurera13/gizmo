# Story continuity

The Blueprint demo should show the user changing a story and Gizmo carrying that
change into its narration and scene choices.

Saved-media routing is the first checkpoint. Fresh illustration, motion, and
whether two consecutive scenes hold together as one story are the second.

## First checkpoint — routing

Saved-media evidence: `data/show-checkpoints/2026-09-05-story-continuity-072701/`.
5/5 interactions passed. The director follows Live's narration, keeps the castle
picture through a motive change and “Then what?”, and requests a new ocean-floor
scene only after the move.

Fresh-scene evidence: `data/show-checkpoints/2026-09-05-story-scenes-073729/`.
Two generated scenes arrived during speech. The motive change kept the first
picture. The two stills share the print look and not the characters; story images
are environments, not a cast.

Typed kid-language evidence: `data/show-checkpoints/2026-09-05-kid-story-080522/`.
Four ordinary lines — a story, a wait-he's-scared-of-bells, a submarine, then
what — kept one fox, one fear change, and two unlabeled places. The first still
was observed after a short chapter finished talking. Its recorded 18-second
arrival is not reliable: the old recorder timestamped queued post-speech media
after waiting for all generation jobs. Do not use that number as latency evidence.

## Interaction

1. “Tell me a story about a fox who's scared of dragons.”
2. “Wait. He's actually scared of bells.”
3. “They should escape in a submarine.”
4. “Then what?”

## Implementation

Live remains the sole narrator. The visual director reads the actual opening
narration, latest utterance, existing picture subject, and eight recent completed
dialogue turns. It does not independently invent the next chapter. Completed
narrations enter session-local context; cold boot clears that context.

One meaningful complete opening sentence starts direction while speech continues;
short replies fall back to completion. “Make it move” stays words and keeps
the current still. At most one visual is applied per ask. A words-only story opening can request one follow-up at chapter completion, with a 35-second wait bound. That follow-up uses the full narration to catch a later move and cannot request a third call. New asks cancel pending directions
and unfinished stills. Existing displayed media remains available for follow-ups.

An installed story picture carries a broad setting key. Matching that key suppresses redundant still/film requests in the controller unless the user requested a redraw or a new story. The key changes only when its replacement picture arrives, and clears on dismissal.

Stories keep one main setting per chapter. Changes in action, mood, cast position,
or nearby parts of the same location do not require a new picture. A story opening
or an actual move to a new setting plays Cinema (H3 Max Director), not a Fal
still→clip. Story pictures are unlabeled scenes of a lived-in place. Labels belong
only on diagrams and maps.

## Run

```sh
.venv/bin/python -m pytest friend/tests -q
.venv/bin/python friend/checkpoints/story_continuity.py
```

The second command is an explicit live-provider check. It uses the repository's
ignored Gemini key for voice and the director. Image and clip providers replay
existing files; memory and deep reasoning providers are disabled. It saves
synthetic story speech and transcripts to a unique ignored evidence directory.
No microphone recording, deployment, or physical-device validation occurs.

## Limits to review

- Opening-sentence detection uses punctuation and a minimum length, not a semantic
  scene planner. Actual timing depends on Live's transcription delivery.
- The voice instruction establishes a location early. If an opening already generated a scene and narration moves elsewhere
  later in the same chapter, there is no second automatic scene generation.
  Words-only openings may request one completed-chapter follow-up.
- Eight recent turns are bounded context, not durable storage for long stories.
- Saved media proves requests, delivery, reuse, and cancellation; it cannot prove
  fresh visual fidelity, matching character designs, or image-generation latency.
- Simulator and physical screen behavior use the existing Show contract unchanged.

## Second checkpoint — fresh scenes

Generate one opening scene and one moved scene through the actual image and clip
providers. The twist still must keep the first picture. Inspect the two stills
for shared print look and whether they read as the same story. Character likeness
across scenes is an unknown this checkpoint is meant to reveal, not a pass gate
assumed in advance.

```sh
.venv/bin/python friend/checkpoints/story_scenes.py
```

This spends two still generations and up to two clip generations. Memory and deep
reasoning stay disabled. Evidence, including the generated JPEG/MP4 files, is
saved under `data/show-checkpoints/`. No microphone, deployment, or device check.


## Character continuity and timing — September 5

The director now supplies a session-local appearance description for the main
fictional non-human character. The controller keeps that description across
setting and fear changes and passes the first successfully installed scene back
as an image reference for later scenes. The original reference is retained rather
than chaining every new image, which limits accumulating visual drift. Starting
an explicitly new story or cold boot clears it; dismissing a picture does not.
Ordinary diagrams and factual pictures receive no character reference.

Characters are now visible within the scene, with a recognizable silhouette and
simple surroundings. This first version supports one protagonist per active
story, not an enduring cast library. Explicit redesigns and multiple recurring
characters need a separate identity-editing contract; it does not infer them
from mood changes. A remembered name is used only if explicitly identified as
the user's own, never just because a person, pet, or character appears in memory.

The checkpoint consumes events continuously through speech and media completion.
Its timestamps measure receipt of server events, not pixels reaching a physical
screen. A regression check ensures a late still is recorded while the clip task
is still running.

Verified live evidence: `data/show-checkpoints/2026-09-05-kid-story-135809/`.
The narrator named this run's fox Finley; no fox name is hardcoded. Forest and
submarine stills preserve his silhouette, face markings, pink tail tip and collar.
The second generation received the first still as its character reference.
Both JPEGs and a frame three seconds into each clip were inspected. This is a
sampled visual check, not a frame-by-frame guarantee or a physical-panel test.

| Turn | Still event | Clip event | Voice finished | New generations |
| --- | --- | --- | --- | --- |
| Forest | 15.102 s | 20.737 s | 52.185 s | One still, one clip |
| Fear changes to bells | Reused | Reused | 25.448 s | None |
| Submarine | 16.631 s | 21.803 s | 25.709 s | One still, one clip |
| Then what? | Reused | Reused | 28.683 s | None |

The first narration exceeded the intended short chapter length. Character
continuity passed this sample; chapter pacing remains inconsistent. These
server-event timings do not establish actual device playback latency.

Name ownership was checked against the actual Live voice transport with three
synthetic memory contexts: other people's names, ambiguous ownership, and an
explicit user name. Results were “Never told me.”, “I don't know your name. You
haven't told me.”, and “You're Alex.” respectively. Evidence:
`data/show-checkpoints/2026-09-05-name-ownership-140151/`. This is three sampled
responses, not a deterministic guarantee of future model behavior.

```sh
.venv/bin/python friend/checkpoints/name_ownership.py
```

Name checks use synthetic memory only and spend voice calls. They never read or
write the user's persistent memory. Reference-image generation follows the
provider's [documented image-input interface](https://ai.google.dev/gemini-api/docs/generate-content/image-generation).
