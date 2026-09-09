# Story mode review — September 10, 2026

The prepared-scene conductor is a useful direction for longer stories: plan a chapter, generate its narration and media concurrently, preload the next scene, and let PTT interrupt it. It is experimental. Ordinary conversation and the existing automatic Show path remain the default.

Enable it on a development brain with `GIZMO_STORY_ENABLED=1`. Explicitly injected planners enable it in tests. Do not enable it on production solely because the automated checks pass.

## Review fixes

- Held scenes only reach WebSocket clients advertising `X-Gizmo-Glass-Cues: 1`. Legacy clients receive a scene when it goes live, so a future picture cannot replace the current narration's picture early. Updated XIAO firmware advertises the header.
- Cue numbers increase across stories within a session. Unissued acknowledgements are ignored. Acknowledgements mean the media downloaded and its JPEG boundaries/dimensions were indexed; they do **not** prove successful panel decoding or actual presentation time.
- Story-owned planner/render/playback tasks are cancelled and joined on close. Interrupting an opener preserves its pending plan for continuation. Timer expiry and failed-plan fallback no longer cancel their own cleanup/reply task.
- A missing narration falls back to the conversational voice. Unheard beats are not recorded as a completed chapter.
- Character scenes wait for the first reference image before generating subsequent shots. Other scenes still render concurrently.
- The body can preload a scene while its narration is rendering. The narration provider deadline is now 20 seconds because a valid live response exceeded the original 12-second deadline. This avoids a demonstrated false failure; it does not solve first-response latency.
- Select retains the physical device's existing dismissal behavior. PTT pauses; spoken requests continue or steer. Disconnecting the last listener pauses narration.
- Planning instructions now keep the central requested subject/action visible instead of substituting atmospheric background motion. Generic fictional premises should not silently become real historical missions.

## Actual provider evidence

One local live-provider sample, not a latency distribution or production/device acceptance:

| Stage | Observed result |
| --- | --- |
| Fal Haiku scout | 1.75 s, selected story mode |
| Fal Sonnet chapter plan, one beat | 6.16 s |
| Fal FLUX.2 Klein 9B image | 2.01 s |
| Gemini 3.1 scripted narration, original 12 s deadline | Timed out |
| Fal H3 Max motion plus local save/MJPEG conversion | 4.99 s, 62 frames |
| ESP ROM TJpgDec equivalent, host build | Decoded all 62 generated frames |

A separate identical 22-word narration comparison returned valid audio in 12.77 seconds with Gemini 3.1 Flash TTS and 9.23 seconds with Gemini 2.5 Flash TTS. These are single measurements. The default remains 3.1; one faster sample does not establish a consistently better voice/provider. Google documents the model at https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-tts-preview.

Generated local evidence lives under `data/story-review-20260910/` (ignored): provider reports, audio samples, still, MP4, and device-format MJPEG. These probes used real provider credentials without exposing them or altering Railway.

The initial narrative sample also substituted a historical mission for a generic rocket story and illustrated an empty launchpad. The prompt changes address those observed tendencies, but content quality and factual reliability still need evaluation across multiple stories.

## Validation and next checkpoint

Automated regressions cover cancellation while planning, prefetched-work cleanup, timer expiry during suspended delivery, legacy-client filtering, cue reuse, narration failure, consistent character references, and overlapping picture download with narration. Run:

```sh
.venv/bin/python -m pytest friend/tests -q
python3 body/firmware/test/host/run.py
body/firmware/.venv/bin/pio run -d body/firmware
uv lock --check
```

Before enabling broadly, measure complete multi-beat stories, including time to first audible response, first picture, motion arrival, and scene/voice alignment. Test late and failed media, interrupt during the opener/download/speech, continue, steer, dismiss, and reconnect. Keep paid speculative generation bounded and assess narration latency before increasing prefetch.

Physical acceptance requires the updated XIAO firmware plus a continuous screen/audio/button recording and serial logs. The existing microphone outbound-queue cancellation and idle speaker static reports are separate unresolved hardware/runtime issues; this change does not establish fixes for them. Host decoding and a successful firmware build do not prove panel playback, PSRAM headroom during audio, smooth frame timing, or physical sound quality.

No production deployment or firmware flash was performed for this review.
