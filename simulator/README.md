# Gizmo Simulator

Native macOS device simulator. The supplied product render is the device: hold its pink side button to talk through the Mac microphone, use the right-side arrow pill to move up and down, and press the circular button to select. Sleep is idle-only; a PTT press while asleep wakes and captures on that same press. The glass is live, the top hardware toggle is represented by the power control in the conversation header, and the conversation panel shows the same Friend session beside it. The JSON body wire contract is in `body/README.md`.

## Build

```bash
./simulator/build_app.sh
open "dist/Gizmo Simulator.app"
```

With no `GIZMO_BRAIN_URL` in `.env`, the app owns its brain: at launch it evicts anything already on port `43147` and starts the repo-local Friend fresh, so a leftover brain on old code is never reachable. With `GIZMO_BRAIN_URL` set it talks to that cloud brain instead. Either way the power switch is the source of truth: a brain that disagrees on connect is told the switch position and follows it.

Each install mints a device id on first launch (kept in user defaults, shown in `simulator.log`) and sends it as `X-Gizmo-Device`, so every install is its own Gizmo with its own memory. Set `GIZMO_DEVICE_ID` in the environment to impersonate a device or start fresh.

PTT also requests one real Mac-camera snapshot for visual context. Aim before
pressing. The capture keeps its full aspect, fits within 640 × 480, and sends a
JPEG of at most 128 KiB on the same socket while the button is held. Capture stops
after that frame or on release/disconnect/power-off; a late permission response or
frame cannot attach to another hold. A missing/denied camera leaves voice usable.
Camera status appears in the desktop conversation panel, while the face stays
on the device. Allow Gizmo Simulator's Camera and Microphone permissions when
macOS asks. Launch the `.app` with `open` so macOS attributes those permissions
to Gizmo rather than the parent terminal application.

Logs land in `data/` (gitignored): `simulator.log` is the app's event trail, `brain.log` is the local brain's output.

Show playback uses the same authenticated finite MJPEG route intended for the
physical body. `simulator/hardware-preview.json` supplies an explicit provisional
width, height, fps and encoded-byte cap; the packaged default is 320 × 240 at the
route maximum of 24 fps with a 4 MiB cap. The app keeps compressed JPEG frames and
decodes one display frame at a time. Change that profile to repeat the eventual
board/panel sweep; a Mac pass is not evidence of physical performance.

## Change the device render

Each skin is a folder containing:

```text
skin.json
device-reference.png
device-reference-ptt-pressed.png
```

`skin.json` uses normalized coordinates from `0` to `1`, so the source render can be any resolution or aspect ratio. It defines the active screen rectangle, every clickable hardware region, and the optional pressed PTT render. The separate hardware preview profile defines requested media pixels and timing. Replace the images in `DeviceSkins/current`, adjust the manifest, and rebuild the app. No agent, protocol, or firmware code changes are required, and there is no skin-management UI in the product simulator.

The glass design target is 69 × 50 mm landscape (69∶50, about 1.38∶1); no panel
has been selected. The included skin's screen rectangle is roughly 1.2∶1 to
match the reference render's bezel. Actual device resolution, crop and timing
remain unverified until the panel/profile is chosen.
