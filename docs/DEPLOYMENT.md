# Gizmo deployment

Railway project: https://railway.com/project/4e9d895f-7559-4def-8700-bea6a5301320

Brain health: https://gizmo-brain-production.up.railway.app/health

All four services run in Singapore: `gizmo-brain`, `memobase`, `postgres`, and `redis`. Only the brain has a public domain. Device/data routes and the device WebSocket require `Authorization: Bearer <GIZMO_DEVICE_TOKEN>`. The OddityOS shell and its exact static assets are public so `oddware.xyz/gizmo/oddity` can embed them; live public sessions require `ODDITY_PREVIEW_TOKEN`, and the unlisted lab at `/gizmo/oddity/lab` requires `ODDITY_LAB_TOKEN`. Public sessions use isolated random identities, enforce same-origin sockets, and have separate daily spend caps. Lab sessions skip those caps.

Pushes to `main` deploy automatically: `.github/workflows/test.yml` runs the suite, then deploys `gizmo-brain` on every main push and `memobase` when `deploy/memobase/` changed. One-time setup — create a project-scoped token in Railway → project `gizmo` → Settings → Tokens → New Token (environment: production), then `gh secret set RAILWAY_TOKEN -R junkurera13/gizmo`. Until that secret exists the deploy job skips with a warning, so a merge to `main` does NOT reach production. Manual fallback: `npx @railway/cli up --service gizmo-brain` and `npx @railway/cli up --service memobase` from the repo root. Railway's GitHub App still lacks access to `junkurera13/gizmo`; if that is ever granted, a native GitHub source connection can replace the CI deploy.

The native simulator uses the ignored repository `.env` for `GIZMO_BRAIN_URL` and `GIZMO_DEVICE_TOKEN`. API keys are backend credentials, not client configuration. The current local env file is permission mode 600 and is not tracked by Git.

The public site is a separate Vercel project (`gizmo`, Oddware team) with root directory `web/`. It is not the brain. The main Oddware Vercel project forwards `/gizmo/*` to this project, so the simulator page does not need a DNS or subdomain change. Hobby Git deploys require the commit author to be the team owner.

## Verified on 2026-09-02

- Railway health checks for all four services.
- Unauthenticated device/data access is rejected.
- Existing device WebSocket: 24 kHz PTT input, Gemini input resampling, voice reply, and final input/output transcripts.
- Gemini Live calls `deep_think`, receives Gemini 3.7's result, and voices the answer.
- Camera snapshot recognition was verified through the deployed brain, then removed
  from PTT on Sep 5; the pink control is audio-only and See is currently unwired.
- Memobase extraction, retrieval, and recall in a new `GizmoSession` with a separate local transcript directory. Synthetic test identities were removed afterward.
- Rebuilt native app: cloud connection, typed conversation, PTT hold-to-talk, and hard power-off. (PTT tap-to-sleep was removed afterwards; sleep is idle-only.)

## Operational notes

Memobase uses Gemini 3.1 Flash-Lite and Gemini Embedding 2 through Google's OpenAI-compatible endpoint. The old OpenAI credential had exhausted its balance; no OpenAI API balance is required for this deployment.

Memory processing is asynchronous. A fact becomes available to a later session after Memobase finishes its background extraction; an immediate power cycle can precede that completion.

Native Google Search is enabled according to the Live API tool contract. Current-fact questions returned spoken answers, but the provider did not return grounding/citation metadata in the smoke tests. Source-attributed Search is therefore not yet verified. No custom search service was added.

`set_expression` is a placeholder bus. It is not the character. No image/video generation or Adaptive Media was added.
