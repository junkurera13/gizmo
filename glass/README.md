# Glass

1.54" 240×240. The glass shows the wizard when Gizmo is awake, a print-look still during **show** and on a kept page, and nothing when asleep.

Jun draws the wizard. Do not drop stock art in here.

## Sprites

The wizard is a set of short flipbooks — one folder per animation, numbered PNG frames inside. Drop a folder in `glass/sprites/` and the simulator plays it. No folder yet? The procedural face fills in, so animations can land one at a time.

```
glass/sprites/
  idle/   01.png  02.png  03.png ...
  talk/   01.png  02.png ...
  sprites.json        (optional, see below)
```

### Frame rules

- **Format**: PNG with transparency. Background stays empty — the glass paints it black.
- **Canvas**: 240×240 pixels, every frame the same size. Draw bigger if you like (480×480, 960×960) as long as all frames in one animation match; the glass scales down. Pixel art should be authored at 240×240 or a clean multiple so it stays crisp — the renderer never smooths.
- **Names**: number them so they sort — `01.png`, `02.png`, … Nothing else matters about the name.
- **Frame counts**: idle can live on 4–8 frames (blink, sway). Big moments (boot, think) earn more. Cuphead runs on 24; Game Boy characters on 2–4. Land where it feels right.

### The animation set

One folder per state the brain broadcasts. Build in this order — each one shows up as soon as its folder exists:

| Folder    | When it plays                        | Notes                                        |
| --------- | ------------------------------------ | -------------------------------------------- |
| `idle`    | awake, waiting                       | **Start here.** Loops. Falls in for everything missing. |
| `talk`    | speaking                             | Loops while he talks.                        |
| `think`   | deep thinking / making / reaching    | Loops. The "gone inward" pose.               |
| `listen`  | talk button held                     | Loops. Ears up, eyes on you.                 |
| `boot`    | waking up                            | Plays **once**, then idle takes over.        |
| `see`     | camera on                            | **The floating head.** Draw only the head — the glass drifts it around by itself. Loops. |
| `show`    | a still is being made                | Loops until the picture lands.               |
| `sleep`   | powering down                        | Plays **once**. (Wired up later.)            |

### sprites.json (optional)

Defaults: 10 frames per second, everything loops except `boot` and `sleep`, only `see` drifts. Override per animation if a scene needs it:

```json
{
  "idle": { "fps": 6 },
  "boot": { "fps": 12, "loop": false },
  "see":  { "fps": 8, "wander": true }
}
```

### Iterating

Draw, export the PNGs into the folder, then in the simulator hit **Device → Reload Sprites** (⌘R). No rebuild, no restart.

Tools that export numbered PNG sequences: Aseprite (built for exactly this), Procreate (Animation Assist → export PNG frames), Photoshop timeline. Any of them works.

## Sounds

`glass/sounds/` holds Gizmo's few fixed noises. WAV files, short, mono.

| File       | When it plays        | Notes                                        |
| ---------- | -------------------- | -------------------------------------------- |
| `boot.wav` | the moment he wakes  | The Game Boy ding. Under 2 seconds. Design the boot flipbook so its landing beat matches. |

A placeholder chime lives there until Jun replaces it. jsfxr (browser, free) makes exactly this kind of 8-bit sound.

## Stills

Friend already blits:

- print-look stills (local SVG, 240×240) during `show` and on a kept page
- up to two short clips after the still (skipped if `FAL_KEY` is missing)
- then off

Friend should keep treating glass as a small page, not a UI toolkit.
