# Body reference client — checkpoint 1

This is the executable reference for body protocol v1. It verifies `/health`,
requires the same version in the WebSocket `hello`, identifies one device, and
sends the physical control messages. It deliberately disables WebSocket
compression because firmware should not need a compression implementation.

From the repository's installed virtual environment:

```bash
.venv/bin/python body/reference/gizmo_body.py \
  --url https://brain.example.com \
  --device-id gizmo-board-001
```

The client reads `GIZMO_DEVICE_TOKEN` from the environment; prefer that over a
command-line token so the credential does not appear in the process arguments.
The token is the device credential. Never put provider keys on the body.
Remote connections require HTTPS/WSS. Local development defaults to
`http://127.0.0.1:43147` and needs no token unless the local server was started
in deployed mode.

Commands mirror hardware edges: `power on`, `power off`, `ptt down`, `ptt up`,
`up`, `down`, and `select`. `say <text>` is a diagnostic stand-in. Incoming PCM
is reported only as a byte count. Microphone capture, camera capture, speaker
playback, glass-media fetching, and wake/reconnect buffering belong to
checkpoint 2.
