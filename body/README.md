# Body

ESP32-S3 handheld: top power toggle, pink push-to-talk button, up/down rocker, circular Select button, mic, speaker, landscape screen, world camera. The screen is not selected yet; 69 × 50 mm is the design target.

**Not in v1.** Do not add fake firmware here. Friend runs on a laptop and speaks this protocol in software.

## Protocol Friend already understands

The native simulator uses JSON text messages over WebSocket `/ws`. Firmware uses
the same wire messages below. Python classes in `friend/gizmo_friend/body_protocol.py`
are internal controller events; their names are not necessarily the JSON names.

Connect to `wss://<brain-host>/ws` with `Authorization: Bearer <device-token>` and
`X-Gizmo-Device: <device-id>` headers. Keep the same device id across reconnects.
Local development uses `ws://127.0.0.1:43147/ws`. The body needs the device token,
not any provider API key.

| Wire event | Body input | Friend |
| --- | --- | --- |
| `power` | Top toggle on / off | Cold boot / hard shutdown |
| `ptt` | Pink side button down / up | Down: listen (wakes him if asleep). Up: answer. No tap gesture; sleep is idle-only |
| `select` | Circular Select button | Select the focused item or interrupt output; wakes him if asleep; never opens the camera |
| `navigate` | Up/down rocker | Move the device UI selection up or down; wakes him if asleep |
| `frame` | One camera JPEG, base64 in `image`, during PTT | Visual context for that hold; same owning socket as audio |
| `audio` | PCM in `pcm` while PTT is down | Realtime microphone input; `mic` is an accepted compatibility alias |
| `audio` (brain → body) | PCM in `pcm` | Realtime speaker output; there is no `speaker` wire event |

For both audio directions, `pcm` is standard base64 of signed, little-endian,
16-bit mono PCM at **24,000 Hz**, with no WAV header. Each chunk must contain whole
two-byte samples. There is no sample-rate negotiation: convert device audio to
this format before sending. The server handles the separate 16 kHz conversion
required by Gemini. Invalid base64, non-string PCM and partial samples emit an
`error`; an empty chunk is ignored.

One microphone turn, in order on the **same socket**:

```json
{"type":"ptt","active":true}
{"type":"audio","pcm":"AAA="}
{"type":"ptt","active":false}
```

`AAA=` is one silent sample to illustrate the encoding, not a spoken request.
In use, stream captured PCM chunks between press and release. Preserve that order
and do not wait for the server's `ptt:true` acknowledgement before sending PCM;
the server buffers incoming audio while opening the voice turn. That buffer does
not cover a disconnected body: wake/reconnect audio needs a local firmware buffer.
Only the connection owning the hold may send its audio, camera frame or release.
Audio and frames sent outside a hold or from another socket are ignored, for
both audio input names.
If the owning socket disconnects, the backend drops that hold without committing
it. Reconnect and report a fresh physical press for the next turn.

Camera policy for this v1: start one snapshot on PTT down, alongside the microphone.
Send it as `{"type":"frame","image":"<base64 JPEG>"}` between press and release,
as soon as it is ready. Do not delay audio for the camera. Preserve the full camera
aspect; the provisional capture ceiling is **640 × 480 pixels and 128 KiB of JPEG**,
independent of the undecided screen. The server enforces the byte ceiling and
valid base64, and acknowledges accepted frames with a `frame` event containing
`bytes`. That acknowledgement means the brain received the frame, not that a
model has understood it.

Stop capture after the snapshot, or on release, disconnect, shutdown or failure.
The native adapter gives an authorized camera five seconds to deliver a frame,
including a brief exposure warm-up. A dark scene remains valid input.
If release wins, discard the unfinished capture; never send it in the next hold.
A failed/unavailable camera leaves voice usable, and a silent hold discards its
unconsumed snapshot. The face stays on glass; no viewfinder is part of this flow.
Aim before pressing. Book-text readability and the eventual sensor/PSRAM budget
still require a real device check. Firmware should capture JPEG directly into a
bounded buffer; the Mac's BGRA-to-JPEG conversion is only its camera adapter.

Other device inputs:

```json
{"type":"power","on":true}
{"type":"navigate","direction":"up"}
{"type":"navigate","direction":"down"}
{"type":"select"}
{"type":"power","on":false}
```

The examples are separate actions, not a sequence to send together. `power:true`
means a cold boot; an ordinary socket reconnect resumes the existing session and
must not blindly cold-boot it. A physical hard cut cannot guarantee a final
`power:false` message. Wait for boot to complete before sending a talk turn; PTT
from sleep wakes and captures on the same press.

On connect, the server sends `hello` with `state`, `power`, `screen`, and
`transport`, followed by a `glass` snapshot. State changes arrive in `state`
events and accompanying event fields. Show uses `glass` with `still`, then
`clip`/`frames`, or `viewing:false` on dismissal; `show` is a model tool name, not
the output event. The `frames` URL serves the finite JPEG sequence described in
`docs/SHOW.md`. Media fetches use the same authorization and device-id headers.

The broader firmware handoff still needs its reference client and protocol-version
negotiation. Those are not implemented by this microphone-contract correction.

No character art in this tree. No second brain. Body is a body.
