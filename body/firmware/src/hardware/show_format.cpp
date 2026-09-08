#include "gizmo/show_format.h"
#include <stdio.h>
#include <string.h>

namespace gizmo {
bool show_path(const char* path, const char* device, const char* extension) {
  if (!path || !device || !*device) return false;
  char prefix[80];
  const int n = snprintf(prefix, sizeof(prefix), "/shows/%s/", device);
  if (n <= 0 || static_cast<size_t>(n) >= sizeof(prefix) || strncmp(path, prefix, n)) return false;
  const char* id = path + n;
  if (strlen(id) != 32 + strlen(extension)) return false;
  for (int i = 0; i < 32; ++i)
    if (!((id[i] >= '0' && id[i] <= '9') || (id[i] >= 'a' && id[i] <= 'f'))) return false;
  return strcmp(id + 32, extension) == 0;
}
bool show_same(const char* still, const char* frames) {
  const size_t n = strlen(still);
  return n >= 4 && strlen(frames) == n + 2 && strncmp(still, frames, n - 4) == 0 &&
         strcmp(still + n - 4, ".jpg") == 0 && strcmp(frames + n - 4, ".mjpeg") == 0;
}

bool show_index(const uint8_t* b, size_t n, ShowFrame* frames, size_t count) {
  if (!b || !frames || !count || count > kShowMaxFrames || n > kShowMaxBytes) return false;
  size_t p = 0;
  for (size_t f = 0; f < count; ++f) {
    const size_t start = p;
    if (n - p < 2 || b[p++] != 0xff || b[p++] != 0xd8) return false;
    bool sized = false, scan = false, ended = false;
    while (p < n) {
      if (b[p++] != 0xff) { if (scan) continue; return false; }
      while (p < n && b[p] == 0xff) ++p;
      if (p == n) return false;
      const uint8_t marker = b[p++];
      if (scan && (marker == 0 || (marker >= 0xd0 && marker <= 0xd7))) continue;
      if (marker == 0xd9) { ended = sized && scan; break; }
      if (marker == 0xd8 || marker == 0 || (marker >= 0xd0 && marker <= 0xd7)) return false;
      if (n - p < 2) return false;
      const size_t len = (b[p] << 8) | b[p + 1];
      if (len < 2 || len > n - p) return false;
      if (marker >= 0xc0 && marker <= 0xcf && marker != 0xc4 && marker != 0xc8 && marker != 0xcc) {
        if (marker != 0xc0 || sized || len < 11 || b[p + 2] != 8 ||
            ((b[p + 3] << 8) | b[p + 4]) != kShowHeight ||
            ((b[p + 5] << 8) | b[p + 6]) != kShowWidth ||
            (b[p + 7] != 1 && b[p + 7] != 3) || len != size_t(8 + 3 * b[p + 7])) return false;
        sized = true;
      }
      if (marker == 0xda) { if (!sized || len < 6) return false; scan = true; }
      p += len;
    }
    if (!ended) return false;
    frames[f] = {start, p - start};
  }
  return p == n;
}
}
