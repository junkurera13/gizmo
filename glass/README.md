# Glass

Jun's. The 240×240 screen. Home is his face. Anything else is conjured for a moment and then leaves.

**The character is still being designed.** Nothing in this folder, the sprite player, or `set_expression` is the character architecture. After the design lands, we build that together. Do not invent a second face system, do not lock a sheet, do not treat the folder names below as canon.

## Scratch player

The simulator can preview numbered PNG flipbooks so Jun can try drawings on the device. Drop a folder in `glass/sprites/` and hit **Device → Reload Sprites** (⌘R). No rebuild. Empty glass is black — there is no stand-in character.

```
glass/sprites/
  idle/   01.png  02.png  03.png ...
```

Today the emulator looks for folders named after *device states* (`idle`, `listen`, `talk`, `think`, `boot`, …). That mapping is a temporary hook for previews. It is not the animation set. Missing folders stay black, except that some names currently fall back to `idle` if it exists.

### Frame rules (for previews)

- PNG with transparency. The glass is black behind it.
- 240×240, or a clean multiple (480, 960). The player scales down and never smooths.
- Number the frames so they sort: `01.png`, `02.png`, …

Aseprite, Procreate Animation Assist, or Photoshop timeline all export this.

Optional `glass/sprites/sprites.json` can override fps / loop per folder name. Defaults are a preview convenience, not spec.

## Sounds

`glass/sounds/boot.wav` is the cold-boot chime until Jun replaces it. Short, mono WAV.

## Stills

Show / Make stills are not wired. Do not put generated media in this tree.
