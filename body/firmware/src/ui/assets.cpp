#include "gizmo/assets.h"
#include "gizmo/jpeg_lock.h"
#include <stdlib.h>
#include "img_converters.h"

namespace gizmo::assets {
namespace {
bool decode(const uint8_t* begin, const uint8_t* end, const draw::Canvas& canvas) {
  if (begin == nullptr || end == nullptr || end <= begin) return false;
  if (!canvas.valid() || canvas.width != kPanelWidth || canvas.height != kPanelHeight) return false;
  // jpg2rgb565 writes width*height*2 bytes at the JPEG's own size, which the
  // exporter fixed to the panel profile. It runs under the chip-global jpeg
  // lock so boot/home frames cannot race the show decode-ahead task.
  return jpeg_decode_locked(begin, static_cast<size_t>(end - begin), canvas.pixels);
}
}  // namespace

bool decode_boot_slot(int slot, const draw::Canvas& canvas) {
  if (slot < 0) slot = 0;
  if (slot >= kBootSlots) slot = kBootSlots - 1;
  const int unique = kBootSlotFrame[slot];
  return decode(boot_frame_start(unique), boot_frame_end(unique), canvas);
}

bool decode_home_base(const draw::Canvas& canvas) {
  return decode(_binary_assets_home_base_jpg_start, _binary_assets_home_base_jpg_end, canvas);
}

bool decode_idle_slot(int slot, const draw::Canvas& canvas) {
  if (slot < 0) slot = 0;
  if (slot >= kIdleSlots) slot = kIdleSlots - 1;
  const int unique = kIdleSlotFrame[slot];
  return decode(idle_frame_start(unique), idle_frame_end(unique), canvas);
}

bool decode_listening_slot(int slot, const draw::Canvas& canvas) {
  if (slot < 0) slot = 0;
  if (slot >= kListeningSlots) slot = kListeningSlots - 1;
  const int unique = kListeningSlotFrame[slot];
  return decode(listening_frame_start(unique), listening_frame_end(unique), canvas);
}

bool decode_thinking_slot(int slot, const draw::Canvas& canvas) {
  if (slot < 0) slot = 0;
  if (slot >= kThinkingSlots) slot = kThinkingSlots - 1;
  const int unique = kThinkingSlotFrame[slot];
  return decode(thinking_frame_start(unique), thinking_frame_end(unique), canvas);
}

const uint8_t* clock_atlas() { return _binary_assets_clock_atlas_a8_start; }

const int16_t* chime() {
  // Embedded blobs are byte-aligned; Xtensa faults on misaligned 16-bit loads,
  // so the chime is copied once into an aligned heap buffer.
  static int16_t* aligned = nullptr;
  if (aligned == nullptr) {
    aligned = static_cast<int16_t*>(malloc(kChimeSamples * sizeof(int16_t)));
    if (aligned == nullptr) return nullptr;
    const uint8_t* src = _binary_assets_boot_chime_pcm16_start;
    for (size_t i = 0; i < kChimeSamples; ++i) {
      aligned[i] = static_cast<int16_t>(src[i * 2] | (src[i * 2 + 1] << 8));
    }
  }
  return aligned;
}

}  // namespace gizmo::assets
