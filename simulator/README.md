# Gizmo Simulator

Native macOS device simulator. The product render is the device: hold its pink side button to talk through the Mac microphone, hover the trackball to navigate, and click it to select. The glass is live, power lives in the conversation header, and the conversation panel shows the same Friend session beside it.

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
device-transparent.png
```

`skin.json` uses normalized coordinates from `0` to `1`, so the source render can be any resolution. It defines the active screen rectangle, its pixel dimensions/content mode, and every clickable hardware region. Replace `DeviceSkins/current/device-transparent.png`, adjust the manifest, and rebuild the app. No agent, protocol, or firmware code changes are required, and there is no skin-management UI in the product simulator.

The included skin keeps the 240×240 framebuffer square and fitted inside the wider black display window until the hardware display specification is confirmed.
