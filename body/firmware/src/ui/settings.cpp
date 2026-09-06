#include "gizmo/settings.h"
#include "gizmo/draw.h"

namespace gizmo {

void render_settings(uint16_t* dest, int width, int height, const SettingsSnapshot& snapshot) {
  const draw::Canvas canvas{dest, width, height};
  if (!canvas.valid()) return;
  draw::clear(canvas, draw::kBlack);
  if (!snapshot.open) return;

  const int rowH = height / 4;
  const int caretW = 3;
  const int left = width / 16;
  draw::text(canvas, left + 12, height / 2 - rowH - 22, "SETTINGS", draw::kDim);
  for (int row = 0; row < 2; ++row) {
    const bool focused = snapshot.focus == row;
    const bool adjusting = focused && snapshot.adjusting;
    const uint16_t color = focused ? draw::kWhite : draw::kDim;
    const int y = height / 2 - rowH + row * rowH;
    if (focused) {
      draw::fill_rect(canvas, left, y + rowH / 4, caretW, rowH / 2, draw::kWhite);
    }
    const char* label = row == 0 ? "BRIGHTNESS" : "VOLUME";
    draw::text(canvas, left + 12, y + 6, label, color);
    const int value = row == 0 ? snapshot.brightness : snapshot.volume;
    draw::meter(canvas, left + 12, y + 20, width - left * 2 - 28, 10, value, snapshot.steps, focused);
    if (adjusting) {
      draw::fill_rect(canvas, width - left - 6, y + 8, 5, 2, draw::kWhite);
      draw::fill_rect(canvas, width - left - 6, y + rowH - 12, 5, 2, draw::kWhite);
    }
  }
  const char* hint = snapshot.adjusting ? "^ _ ADJUST   SELECT DONE" : "^ _ MOVE   SELECT ADJUST   _ PAST VOLUME HOME";
  draw::text(canvas, left + 12, height - 20, hint, draw::kMute);
}

uint8_t backlight_duty(uint8_t step, uint8_t steps) {
  if (steps == 0) return 255;
  if (step > steps) step = steps;
  const int minimum = 46;  // ~18% so step 0 stays operable
  return static_cast<uint8_t>(minimum + (255 - minimum) * step / steps);
}

void apply_volume(int16_t* samples, size_t count, uint8_t step, uint8_t steps) {
  if (samples == nullptr || count == 0 || steps == 0) return;
  if (step == 0) {
    for (size_t index = 0; index < count; ++index) samples[index] = 0;
    return;
  }
  if (step >= steps) return;
  for (size_t index = 0; index < count; ++index) {
    const int32_t scaled = static_cast<int32_t>(samples[index]) * step / steps;
    samples[index] = static_cast<int16_t>(scaled);
  }
}

}  // namespace gizmo
