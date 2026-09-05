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

## Interaction

1. Request an original story. Gizmo establishes one setting in his opening sentence.
2. Change a character's fear or motive. The same story continues and its scene stays.
3. Say "Then what?". Gizmo continues with the established characters and events.
4. Move them somewhere new. The narration establishes the new location and the
   director requests that scene.
5. Ask an unrelated question. Gizmo answers normally; no new story media is requested.

## Implementation

Live remains the sole narrator. The visual director reads the actual opening
narration, latest utterance, existing picture subject, and eight recent completed
dialogue turns. It does not independently invent the next chapter. Completed
narrations enter session-local context; cold boot clears that context.

One meaningful complete opening sentence starts direction while speech continues;
short replies fall back to completion. Bare "make it move" keeps its immediate
silent path. At most one visual is applied per ask. A words-only story opening can request one follow-up at chapter completion, with a 35-second wait bound. That follow-up uses the full narration to catch a later move and cannot request a third call. New asks cancel pending directions
and unfinished stills. Existing displayed media remains available for follow-ups.

An installed story picture carries a broad setting key. Matching that key suppresses redundant still/motion requests in the controller unless the user requested a redraw or a new story. The key changes only when its replacement picture arrives, and clears on dismissal.

Stories keep one main setting per chapter. Changes in action, mood, cast position,
or nearby parts of the same location do not require a new picture. Story pictures
are unlabeled scenes of a lived-in place. Labels belong only on diagrams and maps.

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
