# Body

ESP32-S3 handheld: top power toggle, pink push-to-talk button, up/down rocker, circular Select button, mic, speaker, 69 × 50 mm landscape screen (69∶50), world camera.

**Not in v1.** Do not add fake firmware here. Friend runs on a laptop and speaks this protocol in software.

## Protocol Friend already understands

The laptop maps keys onto these events. Firmware should emit the same later (exact framing TBD: serial, BLE, or Wi-Fi).

| Event | Body input | Friend |
| --- | --- | --- |
| `power` | Top toggle on / off | Cold boot / hard shutdown |
| `ptt` | Pink side button down / up | Down: listen (wakes him if asleep). Up: answer. No tap gesture; sleep is idle-only |
| `select` | Circular Select button | Select the focused item or interrupt output; wakes him if asleep; never opens the camera |
| `navigate` | Up/down rocker | Move the device UI selection up or down; wakes him if asleep |
| `frame` | World camera JPEG/RGB | Visual context for the current turn |
| `mic` | PCM 24 kHz 16-bit mono while PTT is down | Realtime input |
| `speaker` | PCM 24 kHz 16-bit mono | Realtime voice output |

No character art in this tree. No second brain. Body is a body.
