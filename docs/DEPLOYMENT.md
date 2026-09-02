# Gizmo deployment

Railway project: https://railway.com/project/4e9d895f-7559-4def-8700-bea6a5301320

Brain health: https://gizmo-brain-production.up.railway.app/health

All four services run in Singapore: `gizmo-brain`, `memobase`, `postgres`, and `redis`. Only the brain has a public domain. Other HTTP routes and the device WebSocket require `Authorization: Bearer <GIZMO_DEVICE_TOKEN>`.

The native simulator uses the ignored repository `.env` for `GIZMO_BRAIN_URL` and `GIZMO_DEVICE_TOKEN`. API keys are backend credentials, not client configuration. The current local env file is permission mode 600 and is not tracked by Git.

## Verified on 2026-09-02

- Railway health checks for all four services.
- Unauthenticated device/data access is rejected.
- Existing device WebSocket: 24 kHz PTT input, Gemini input resampling, voice reply, and final input/output transcripts.
- Gemini Live calls `deep_think`, receives Gemini 3.7's result, and voices the answer.
- Camera snapshot recognition through the deployed brain.
- Memobase extraction, retrieval, and recall in a new `GizmoSession` with a separate local transcript directory. Synthetic test identities were removed afterward.
- Rebuilt native app: cloud greeting, typed conversation, PTT tap sleep/wake, and hard power-off.

## Operational notes

Memobase uses Gemini 3.1 Flash-Lite and Gemini Embedding 2 through Google's OpenAI-compatible endpoint. The old OpenAI credential had exhausted its balance; no OpenAI API balance is required for this deployment.

Memory processing is asynchronous. A fact becomes available to a later session after Memobase finishes its background extraction; an immediate power cycle can precede that completion.

Native Google Search is enabled according to the Live API tool contract. Current-fact questions returned spoken answers, but the provider did not return grounding/citation metadata in the smoke tests. Source-attributed Search is therefore not yet verified. No custom search service was added.

`set_expression` emits validated device expression events. The character artwork and future media interfaces are unchanged; no image/video generation or Adaptive Media was added.
