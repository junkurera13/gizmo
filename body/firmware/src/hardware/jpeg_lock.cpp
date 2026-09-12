#include "gizmo/jpeg_lock.h"
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include "img_converters.h"

namespace gizmo {
namespace {
SemaphoreHandle_t mux() {
  // First call happens on the setup path (boot slot decode), before the show
  // tasks exist; the static guard keeps creation single-shot and thread-safe.
  static SemaphoreHandle_t handle = xSemaphoreCreateMutex();
  return handle;
}
}  // namespace

void jpeg_lock() {
  if (SemaphoreHandle_t m = mux()) xSemaphoreTake(m, portMAX_DELAY);
}
void jpeg_unlock() {
  if (SemaphoreHandle_t m = mux()) xSemaphoreGive(m);
}
bool jpeg_decode_locked(const uint8_t* bytes, size_t length, uint16_t* pixels) {
  if (!bytes || length == 0 || !pixels) return false;
  jpeg_lock();
  const bool ok = jpg2rgb565(bytes, length, reinterpret_cast<uint8_t*>(pixels), JPG_SCALE_NONE);
  jpeg_unlock();
  return ok;
}
}
