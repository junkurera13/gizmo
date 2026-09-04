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

`glass/sprites/boot/` begins with a 1.25-second, ten-slot drop from the top at
8 fps. The illustration reaches its centered source position, then the existing
double blink plays unchanged and lands on the wordmark (`24.png`). The wordmark
holds until the body's 5.05 s splash ends. The body owns that timer
(`SimulatorModel.splashMinimum`); the brain finishing early or late never cuts
the sequence short.

The seven preserved drawings live in `glass/boot-source/` (open, closing, shut,
opening, wordmark). Run `python glass/build_boot.py` to generate the entry plus
the original sequence `01 01 01 02 03 04 05 06 01 01 03 04 05 07`. The drop is
baked into full-screen frames, so the Mac preview and physical display perform
the same work: decode and swap images. No simulator transition is involved.

Drop `glass/sounds/boot.wav` for the ding; it fires when `24.png` first appears.
Missing wav is a silent boot.

To make the hold feel alive, add frames after the wordmark (a breathing logo, loading dots, a slow shimmer).

After the splash, home is the full-body drawing in `idle/` (`01.png`, 1024×742). The uncropped original is `glass/character-source/full.png`.

`body/assets/export_bundle.py` is the hardware handoff for these source drawings.
It emits panel-sized boot/home assets without rewriting this folder. The output
profile is provisional until the display is selected; boot remains local and does
not wait for the brain.

## Fonts

The home clock is [Outfit](https://fonts.google.com/specimen/Outfit) (SIL OFL), in `glass/fonts/`. Same file is what the body should rasterize later. Missing file falls back to the Mac system face.

## Sounds

Cold-boot chime: `glass/sounds/boot.wav`. Short, mono, 24 kHz, 16-bit PCM WAV. Missing file means a silent boot.

## Stills

Show / Make stills are not wired. Do not put generated media in this tree.
