#pragma once
#include <stddef.h>
#include <stdint.h>

namespace gizmo {
// esp_jpg_decode is chip-global and not reentrant. Every JPEG decode on the
// device — boot flipbook, home/listening/thinking faces, show stills, the
// film decode-ahead task, camera preview — must run under this one lock.
void jpeg_lock();
void jpeg_unlock();
bool jpeg_decode_locked(const uint8_t* bytes, size_t length, uint16_t* pixels);
}
