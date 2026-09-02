# Glass

Jun's. The 69 × 50 mm landscape screen (69∶50). Home is his face. Anything else is conjured for a moment and then leaves.

**The character is still being designed.** Nothing in this folder, the sprite player, or `set_expression` is the character architecture. After the design lands, we build that together. Do not invent a second face system, do not lock a sheet, do not treat the folder names below as canon.

## Scratch player

The simulator can preview numbered PNG flipbooks so Jun can try drawings on the device. Drop a folder in `glass/sprites/` and hit **Device → Reload Sprites** (⌘R). No rebuild. Empty glass is black — there is no stand-in character.

```
glass/sprites/
  idle/   01.png  02.png  03.png ...
```

Today the emulator looks for folders named after *device states* (`idle`, `listen`, `talk`, `think`, `boot`, …). That mapping is a temporary hook for previews. It is not the animation set. Missing folders stay black, except that some names currently fall back to `idle` if it exists. `boot` does not fall back — no boot frames means a black splash.

### Frame rules (for previews)

- PNG with transparency. The glass is black behind it.
- 69∶50 landscape, matching the glass. 1024×742 is the working size (the boot frames use it); the player scales to fit and never smooths, so keep edges crisp at source or expect aliasing when downscaled.
- Number the frames so they sort: `01.png`, `02.png`, …

Aseprite, Procreate Animation Assist, or Photoshop timeline all export this.

Optional `glass/sprites/sprites.json` can override fps / loop per folder name. Defaults are a preview convenience, not spec.

## Boot

`glass/sprites/boot/` is a one-shot double blink at 8 fps: the eye opens and settles, blinks slowly, opens, then a quick second blink lands on the wordmark (`14.png`). That last frame holds until the body's 3.8 s splash ends (about 1.75 s of motion, ~2 s of logo). The body owns that timer (`SimulatorModel.splashMinimum`); the brain finishing early or late never cuts the logo short.

The seven source drawings live in `glass/boot-source/` (open, closing, shut, opening, wordmark). The played sequence is copies of those in the order `01 01 01 02 03 04 05 06 01 01 03 04 05 07`. To change the rhythm, rebuild the copies in a new order; the player plays every numbered frame and holds the last one. The eye is shut on frames 06 and 12.

Drop `glass/sounds/boot.wav` for the ding; it fires when `14.png` first appears. Missing wav is a silent boot.

To make the hold feel alive, add frames after the wordmark (a breathing logo, loading dots, a slow shimmer).

## Sounds

Cold-boot chime: `glass/sounds/boot.wav`. Short, mono, 24 kHz, 16-bit PCM WAV. Missing file means a silent boot.

## Stills

Show / Make stills are not wired. Do not put generated media in this tree.
