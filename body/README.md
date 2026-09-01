# Body

ESP32-S3 handheld: top power toggle, pink push-to-talk button, up/down rocker, circular Select button, mic, speaker, 1.54" 240×240 screen, world camera.

**Not in v1.** Do not add fake firmware here. Friend runs on a laptop and speaks this protocol in software.

## Protocol Friend already understands

The laptop maps keys onto these events. Firmware should emit the same later (exact framing TBD: serial, BLE, or Wi-Fi).

| Event | Body input | Friend |
| --- | --- | --- |
| `power` | Top toggle on / off | Cold boot / hard shutdown |
| `ptt` | Pink side button down / up | Tap to sleep/wake while powered; hold to talk and release to commit |
| `select` | Circular Select button | Select the focused item or interrupt output; never open the camera |
| `navigate` | Up/down rocker | Move the device UI selection up or down |
| `frame` | World camera JPEG/RGB | `see()` / `show()` source |
| `mic` | PCM 24 kHz 16-bit mono while PTT is down | Realtime input |
| `speaker` | PCM 24 kHz 16-bit mono | Mouth output (realtime voice now; Cartesia later) |
| `blit` | 240×240 page | Glass on only for show / saved page |

No character art in this tree. No second brain. Body is a body.
