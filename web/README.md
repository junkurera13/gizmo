# Web

The public site. Not the device. Not Friend. Not the glass.

Next.js app under `/gizmo`: landing, Manifesto, Oddware header. Copy and tone still come from `docs/PRODUCT.md`. Do not invent a second personality.

## Background

Full-viewport still is `web/public/bg.png`. It covers and crops.

```
cd web
npm install
npm run dev
```

http://localhost:3000 (redirects to `/gizmo`)

Vercel project `gizmo` (Oddware team) builds this folder on pushes to `main`. The brain is Railway, not Vercel. Hobby only auto-deploys commits whose Git author is the team owner; merges from other GitHub users stay blocked until the owner pushes or redeploys.
