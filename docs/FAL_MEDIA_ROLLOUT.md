# Fal media and Show latency — 2026-09-09

Production `gizmo-brain` deployment: `dc3425e0-e727-4d19-9060-efdfbcf2ba05`.
Production `memobase` deployment: `5a297980-c18b-43db-aaff-fcebac563617`.

## Provider selection

| Work | Provider/model |
| --- | --- |
| Live voice conversation | Google Gemini Live, unchanged |
| Oddity speech/transcription | Google, unchanged |
| Images and story reference edits | Fal `fal-ai/flux-2/klein/9b` and `/edit` |
| Motion | Fal `minimax/h3-max/image-to-video` |
| Visual/experience director | Fal `anthropic/claude-haiku-4.5` |
| Deep reasoning | Fal `anthropic/claude-sonnet-4.6` |
| Memory extraction | Fal `anthropic/claude-haiku-4.5` |
| Memory embeddings | Fal `qwen/qwen3-embedding-8b`, 1536 dimensions |

There is no Google still-generation fallback. `FAL_KEY` is required for generated visuals and separate planning/reasoning. Google remains the conversational voice agent, including its native grounding and interpretation of staged visuals.

Klein was selected for interactive scenes and character reference editing. Direct Fal samples:

| Candidate | Measured request time | Observation |
| --- | --- | --- |
| Klein 9B | 1.2–2.7 s across scene/reference samples | Good scene style and reference continuity in samples |
| FLUX.2 Turbo | 3.2 s scene / 3.9 s diagram | A reasonable alternative, no demonstrated quality advantage here |
| GPT Image 2, low | 17.0 s diagram | Correct labels in one Earth-cutaway sample, too slow as the default |
| Seedream 5 Pro | Exceeded 60 s test deadline | Not suitable for this interactive latency target in the sampled call |

These are small samples, not percentile benchmarks. Klein, Turbo, and FLUX.2 Pro produced incorrect or duplicate Earth-layer labels. Scientific diagram correctness is not established and remains a product limitation.

Official model pages: [Klein](https://fal.ai/models/fal-ai/flux-2/klein/9b), [Turbo](https://fal.ai/models/fal-ai/flux-2/turbo), [GPT Image 2](https://fal.ai/models/openai/gpt-image-2).

## Latency finding and fix

Google supplied the complete spoken request about 0.26 s after microphone release, with `input_transcription.finished=None`. The transport retained it until `turn_complete`, which arrived after the spoken answer. Visual planning therefore waited for narration even though the request was already available.

The transport now exposes a cumulative transcript preview. When voice output starts, explicit standalone visual requests can use it to start the director. Previews are not written to memory or emitted as final transcripts. The final utterance cannot generate another image for the same turn. Story scenes still use narration and existing character/setting context. New microphone holds clear an interrupted turn's transcript buffer.

Other reductions: four-step Klein generation at 768×576; inline JPEG response avoids a separate CDN fetch; motion starts immediately after the still is committed and emitted. Existing deadlines, budgets, cancellation, and authenticated media routes remain in force.

## Public service verification

Both tests used the same synthetic 24 kHz PCM spoken request over the production protocol-1 WebSocket:
“Show me a jellyfish gently pulsing underwater. Make it a video.”

Times are measured from microphone release by the test client in Korea:

| Event | Fal images, before transcript fix | After transcript fix |
| --- | --- | --- |
| First voice packet | 1.60 s | 1.64 s |
| Still glass event | 17.04 s | 5.83 s |
| Motion glass event | 22.02 s | 10.64 s |
| Full MJPEG downloaded and decoded | 22.69 s | 11.26 s |

Both MJPEG responses were HTTP 200, 62 frames, 320×240, 12 fps. The final response was 599,275 bytes and every frame decoded. Voice was still speaking when the second test's still and motion arrived. Health returned 200; unauthenticated media access returned 401. Seven deployed brain source hashes matched local files.

This builds on the Linux remux fix in commit `ea0cc0a`. No firmware change or flash was needed. A physical XIAO was not attached: this proves the server and wire media, not display playback. Device acceptance still needs `show: ready motion frames=N` with N > 1.

The existing typed-text-to-Gemini voice path did not produce a reply in a separate probe. This change validates the actual push-to-talk audio path; it does not claim to repair typed voice prompts.

## Memory migration and verification

Embeddings were temporarily disabled during migration. Original event tables were backed up in the private database; 34 events and 75 summaries were re-embedded atomically through Fal. Search was re-enabled with an explicit deployment, then a catch-up found no missing vectors. After the synthetic memory test, all 35 events and 79 summaries had vectors. Original record content and timestamps matched their backups.

A synthetic isolated user successfully inserted a conversation, flushed it, and retrieved the saved jellyfish/marine interest in context (9.25 s). Live memory chat and 1536-dimensional embedding requests returned 200 from Fal. Claude Sonnet reasoning and the Oddity Haiku experience schema also passed live requests.

See `deploy/memobase/scripts/README.md` for the migration sequence and retained backup tables. Do not roll the embedding model back without restoring/rebuilding matching vectors.

## Local validation and evidence

`python -m pytest friend/tests -q`: 79 passed, 18 subtests. Coverage includes Fal credentials/no Google fallback, image safety results, story reference edits, request timeout/cancellation, JSON fences, early transcript previews, exactly one generation, and existing remux/session behavior. `git diff --check` and Python compilation passed.

Local diagnostic artifacts are under `data/fal-images-20260909/` (ignored by git): benchmark images/scripts, `before-transcript-fix.json`, `live-events.json`, and the verified `live.mjpeg`. Earlier Linux/Fal remux reproduction is under `data/show-motion-fix/`.

## Physical follow-up: ESP32 JPEG format rejection

The cofounder's flashed XIAO subsequently logged `show: ready motion frames=62`, followed by `JPG Header Parse Failed! Not supported JPEG standard`. The file downloaded successfully; the embedded decoder rejected it. Desktop decoding and the firmware framing parser had passed because neither enforced the ROM decoder's component-sampling restrictions.

FFmpeg `yuvj444p` emitted Y/Cb/Cr sampling factors of 1×2 each. ESP32's TJpgDec requires Cb/Cr to be 1×1 and supports Y 1×1, 2×1, or 2×2. Espressif's software implementation of the ROM decoder API reproduced error 8 on frame zero of a real device clip. Re-encoding to `yuvj420p` produced 2×2/1×1/1×1 and all 62 frames fully decompressed with that decoder.

The server now emits 4:2:0 and uses internal MJPEG cache version 2, rebuilding old caches from saved MP4s at the same authenticated public URL. No firmware change is needed for this correction. Tests validate actual generated JPEG sampling and rebuilding of legacy caches. Local reproduction source, files, and results are in `data/rocket-device-debug/RESULT.md`. Physical panel playback must still be rechecked after deployment.
