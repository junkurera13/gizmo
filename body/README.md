# Body

ESP32-S3 handheld: trackball, push-to-talk side button, mic, speaker, 1.54" 240×240, world camera.

**Not in v1.** Do not add fake firmware here. Friend runs on a laptop and speaks this protocol in software.

## Protocol Friend already understands

The laptop maps keys onto these events. Firmware should emit the same later (exact framing TBD: serial, BLE, or Wi-Fi).

| Event | Body input | Friend |
| --- | --- | --- |
| `power` | Emulator power control; hardware mapping TBD | Explicit wake / sleep |
| `ptt` | Pink side button down / up | Start / stop push-to-talk and commit the captured turn |
| `click` | Trackball short press | Wake / interrupt / select |
| `hold` | Trackball press and hold | `reach()` — queue the current page to the parent outbox |
| `navigate` | Trackball roll / emulator drag | Move the device UI selection up, down, left, or right |
| `frame` | World camera JPEG/RGB | `see()` / `show()` source |
| `mic` | PCM 24 kHz 16-bit mono while PTT is down | Realtime input |
| `speaker` | PCM 24 kHz 16-bit mono | Mouth output (realtime voice now; Cartesia later) |
| `blit` | 240×240 page | Glass on only for show / saved page |

No character art in this tree. No second brain. Body is a body.
