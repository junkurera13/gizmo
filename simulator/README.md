# Gizmo Simulator

Native macOS device simulator. The supplied product render is the device: tap its pink side button to sleep or wake, hold it to talk through the Mac microphone, use the right-side arrow pill to move up and down, and press the circular button to select. The glass is live, the top hardware toggle is represented by the power control in the conversation header, and the conversation panel shows the same Friend session beside it.

## Build

```bash
./simulator/build_app.sh
open "dist/Gizmo Simulator.app"
```

With no `GIZMO_BRAIN_URL` in `.env`, the app owns its brain: at launch it evicts anything already on port `43147` and starts the repo-local Friend fresh, so a leftover brain on old code is never reachable. With `GIZMO_BRAIN_URL` set it talks to that cloud brain instead. Either way the power switch is the source of truth: a brain that disagrees on connect is told the switch position and follows it.

Logs land in `data/` (gitignored): `simulator.log` is the app's event trail, `brain.log` is the local brain's output.

## Change the device render

Each skin is a folder containing:

```text
skin.json
device-reference.png
device-reference-ptt-pressed.png
```

`skin.json` uses normalized coordinates from `0` to `1`, so the source render can be any resolution or aspect ratio. It defines the active screen rectangle, its pixel dimensions/content mode, every clickable hardware region, and the optional pressed PTT render. Replace the images in `DeviceSkins/current`, adjust the manifest, and rebuild the app. No agent, protocol, or firmware code changes are required, and there is no skin-management UI in the product simulator.

The hardware glass is 69 × 50 mm landscape (69∶50, about 1.38∶1). The included skin's screen rectangle is drawn at roughly 1.2∶1 to match the reference render's bezel, so 69∶50 art is fitted with thin black bars until the skin render is redrawn to the real panel.
