# Body

ESP32-S3 handheld: stick, mic, speaker, 1.54" 240×240, world camera.

**Not in v1.** Do not add fake firmware here. Friend runs on a laptop and speaks this protocol in software.

## Protocol Friend already understands

The laptop maps keys onto these events. Firmware should emit the same later (exact framing TBD: serial, BLE, or Wi-Fi).

| Event | Stick | Friend |
| --- | --- | --- |
| `click` | Short press | Wake / interrupt / sleep |
| `hold` | Press and hold | `reach()` — queue the current page to the parent outbox |
| `frame` | World camera JPEG/RGB | `see()` / `show()` source |
| `mic` | PCM 24 kHz 16-bit mono | Realtime input |
| `speaker` | PCM 24 kHz 16-bit mono | Mouth output (realtime voice now; Cartesia later) |
| `blit` | 240×240 page | Glass on only for show / saved page |

No character art in this tree. No second brain. Body is a body.
