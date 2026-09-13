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
  int half_steps = 10;    // 0..10 -> battery fill in tenths
};

// Clock + battery along the top, centred as a group. Draw over a home base.
void render_hud(const draw::Canvas& canvas, const Hud& hud);

// Device-only overlays for the voice memo states, drawn over the home base.
void render_recording_overlay(const draw::Canvas& canvas, uint8_t vu, uint32_t elapsed_ms, uint32_t capacity_ms);
void render_playback_overlay(const draw::Canvas& canvas, uint8_t vu, float progress, uint32_t memo_ms);

// Camera world: the viewfinder fills the whole panel (simulator
// CameraWorldView). Matches Down / double-Select entry. Local preview only;
// no Friend `frame`.
//
// If `viewfinder_ready`, the canvas already holds a full-panel RGB565 capture
// and nothing is drawn. Otherwise the panel is black with optional `status`
// text (starting / error).
void render_camera_world(const draw::Canvas& canvas, bool viewfinder_ready, const char* status);

// Setup / join card over home while Wi-Fi still needs attention.
void render_wifi_setup(const draw::Canvas& canvas, const char* title, const char* line, const char* detail);

// Brain-sent caption line (the kid's own words, or film subtitles), drawn as a
// strip at the bottom over whatever is on screen. Empty line draws nothing.
constexpr int kCaptionBandHeight = 24;
void render_caption(const draw::Canvas& canvas, const char* line);

}  // namespace gizmo
