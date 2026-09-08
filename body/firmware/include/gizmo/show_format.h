#pragma once
#include <stddef.h>
#include <stdint.h>

namespace gizmo {
constexpr int kShowWidth = 320, kShowHeight = 240, kShowFps = 12;
constexpr size_t kShowMaxBytes = 4 * 1024 * 1024;
constexpr size_t kShowMaxStillBytes = 256 * 1024;
constexpr size_t kShowMaxFrames = 240;
struct ShowRequest {
  bool viewing = false;
  char still[128] = "";
  char frames[128] = "";
  char base[160] = "";
  char token[96] = "";
  char device[32] = "";
};
struct ShowFrame { size_t offset = 0, length = 0; };
// Only this device's immutable Show routes may receive its credentials.
bool show_path(const char* path, const char* device, const char* extension);
bool show_same(const char* still, const char* frames);
// Strict baseline JPEG framing. Segment payloads may contain FF D8 / FF D9.
// Reject dimensions before a decoder can write outside the panel framebuffer.
bool show_index(const uint8_t* bytes, size_t length, ShowFrame* frames, size_t count);
}
