#pragma once
#include <stddef.h>
#include <stdint.h>

namespace gizmo {
// Twelve fps misses its 83 ms deadline on the physical XIAO even with no
// download active. Eight evenly paced frames fit the measured decoder budget.
constexpr int kShowWidth = 320, kShowHeight = 240, kShowFps = 8;
// Two clips can be resident at once (the one on the glass and the next beat,
// held), plus a 20 s speaker ring, inside the 8 MiB PSRAM.
constexpr size_t kShowMaxBytes = 2560 * 1024;
constexpr size_t kShowMaxStillBytes = 256 * 1024;
constexpr size_t kShowMaxFrames = 240;
struct ShowRequest {
  bool viewing = false;
  // Storytelling cues. hold: fetch and decode, keep showing the current
  // picture. go: swap the held cue onto the glass. Neither: show on arrival.
  uint32_t cue = 0;
  bool hold = false;
  bool go = false;
  char still[128] = "";
  char frames[128] = "";
  char base[160] = "";
  char token[96] = "";
  char device[32] = "";
};
// The body's answer to a held cue: its still or motion is decoded and waiting.
struct GlassReady { uint32_t cue = 0; bool motion = false; bool ok = false; };
struct ShowFrame { size_t offset = 0, length = 0; };
// Only this device's immutable Show routes may receive its credentials.
bool show_path(const char* path, const char* device, const char* extension);
bool show_same(const char* still, const char* frames);
// Strict baseline JPEG framing. Segment payloads may contain FF D8 / FF D9.
// Reject dimensions before a decoder can write outside the panel framebuffer.
bool show_index(const uint8_t* bytes, size_t length, ShowFrame* frames, size_t count);
}
