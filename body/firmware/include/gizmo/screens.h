#pragma once

#include <stdint.h>
#include "gizmo/draw.h"

// Compositors for the OS states other than Settings (settings.h). Boot frames
// and the home base come straight from the embedded export_bundle.py output;
// the HUD reproduces the simulator's HomeClusterView layout from the manifest.
namespace gizmo {

struct Hud {
  bool has_time = false;  // clock is hidden until the device knows the time
  int hour = 0;           // 0..23, drawn without a leading zero like the Mac
  int minute = 0;
  int half_steps = 10;    // 0..10 -> five hearts in half steps
};

// Clock + hearts along the top, centred as a group. Draw over a home base.
void render_hud(const draw::Canvas& canvas, const Hud& hud);

// Device-only overlays for the voice memo states, drawn over the home base.
void render_recording_overlay(const draw::Canvas& canvas, uint8_t vu, uint32_t elapsed_ms, uint32_t capacity_ms);
void render_playback_overlay(const draw::Canvas& canvas, uint8_t vu, float progress, uint32_t memo_ms);
void render_camera_hint(const draw::Canvas& canvas);

// Setup card over home while the open AP / captive portal is up.
void render_wifi_setup(const draw::Canvas& canvas, const char* ap_ssid, const char* detail);

}  // namespace gizmo
