# Web

The public site. Not the device. Not Friend. Not the 240×240 glass.

Empty until we design it. Copy and tone still come from `docs/PRODUCT.md`. Do not invent a second personality.

## Background video

The whole page is a full-viewport loop. Drop the file here — do not rename:

```
web/public/bg.mp4
```

H.264 `.mp4`. Landscape or portrait; it covers and crops (`object-fit: cover`). Keep it lean (aim under ~15 MB). Mute the audio track. Loop-friendly if you can (first and last frame similar).

Until that file exists, the page is black.

```
cd web
npm install
npm run dev
```

http://localhost:3000

When we deploy, Vercel root directory is `web`.
