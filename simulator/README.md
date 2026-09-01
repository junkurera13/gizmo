# Gizmo Simulator

Native macOS device simulator. The supplied product render is the device: tap its pink side button to sleep or wake, hold it to talk through the Mac microphone, use the right-side arrow pill to move up and down, and press the circular button to select. The glass is live, the top hardware toggle is represented by the power control in the conversation header, and the conversation panel shows the same Friend session beside it.

## Build

```bash
./simulator/build_app.sh
open "dist/Gizmo Simulator.app"
```

The packaged app starts the repo-local Friend runtime when port `43147` is not already serving Gizmo.

## Change the device render

Each skin is a folder containing:

```text
skin.json
device-reference.png
device-reference-ptt-pressed.png
```

`skin.json` uses normalized coordinates from `0` to `1`, so the source render can be any resolution or aspect ratio. It defines the active screen rectangle, its pixel dimensions/content mode, every clickable hardware region, and the optional pressed PTT render. Replace the images in `DeviceSkins/current`, adjust the manifest, and rebuild the app. No agent, protocol, or firmware code changes are required, and there is no skin-management UI in the product simulator.

The included skin keeps the 240×240 framebuffer square and fitted inside the wider black display window until the hardware display specification is confirmed.
