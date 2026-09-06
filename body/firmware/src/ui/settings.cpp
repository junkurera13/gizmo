#include "gizmo/settings.h"

namespace gizmo {
namespace {

constexpr uint16_t kBlack = 0x0000;
constexpr uint16_t kWhite = 0xFFFF;
constexpr uint16_t kDim = 0x7BEF;    // ~50% grey
constexpr uint16_t kMute = 0x39C7;   // ~20% grey

void fill(uint16_t* dest, int width, int height, int x, int y, int w, int h, uint16_t color) {
  if (w <= 0 || h <= 0) return;
  const int x0 = x < 0 ? 0 : x;
  const int y0 = y < 0 ? 0 : y;
  const int x1 = x + w > width ? width : x + w;
  const int y1 = y + h > height ? height : y + h;
  for (int row = y0; row < y1; ++row) {
    uint16_t* line = dest + row * width;
    for (int col = x0; col < x1; ++col) line[col] = color;
  }
}

// 5x7 capitals used by the two labels. Bit 0 is the left pixel.
uint8_t glyph_row(char letter, int row) {
  struct Glyph {
    char letter;
    uint8_t rows[7];
  };
  static const Glyph kGlyphs[] = {
      {'B', {0x1E, 0x11, 0x11, 0x1E, 0x11, 0x11, 0x1E}},
      {'E', {0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x1F}},
      {'G', {0x0E, 0x11, 0x10, 0x17, 0x11, 0x11, 0x0E}},
      {'H', {0x11, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11}},
      {'I', {0x1F, 0x04, 0x04, 0x04, 0x04, 0x04, 0x1F}},
      {'L', {0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x1F}},
      {'M', {0x11, 0x1B, 0x15, 0x15, 0x11, 0x11, 0x11}},
      {'N', {0x11, 0x19, 0x15, 0x13, 0x11, 0x11, 0x11}},
      {'O', {0x0E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E}},
      {'R', {0x1E, 0x11, 0x11, 0x1E, 0x14, 0x12, 0x11}},
      {'S', {0x0F, 0x10, 0x10, 0x0E, 0x01, 0x01, 0x1E}},
      {'T', {0x1F, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04}},
      {'U', {0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E}},
      {'V', {0x11, 0x11, 0x11, 0x11, 0x11, 0x0A, 0x04}},
  };
  for (const auto& entry : kGlyphs) {
    if (entry.letter == letter) return entry.rows[row];
  }
  return 0;
}

void text(uint16_t* dest, int width, int height, int x, int y, const char* label, uint16_t color) {
  for (int index = 0; label[index]; ++index) {
    const char letter = label[index];
    if (letter == ' ') {
      x += 6;
      continue;
    }
    for (int row = 0; row < 7; ++row) {
      const uint8_t bits = glyph_row(letter, row);
      for (int col = 0; col < 5; ++col) {
        if (bits & (1 << (4 - col))) {
          fill(dest, width, height, x + col, y + row, 1, 1, color);
        }
      }
    }
    x += 6;
  }
}

void meter(uint16_t* dest, int width, int height, int x, int y, int w, int h, int value, int steps, bool lit) {
  if (steps <= 0 || w <= 0) return;
  const int gap = 2;
  const int pip = (w - gap * (steps - 1)) / steps;
  if (pip <= 0) return;
  for (int index = 0; index < steps; ++index) {
    const bool on = index < value;
    const int pipH = on ? h : (h * 62) / 100;
    const int pipY = y + (h - pipH) / 2;
    fill(dest, width, height, x + index * (pip + gap), pipY, pip, pipH, on ? (lit ? kWhite : kDim) : kMute);
  }
}

}  // namespace

void render_settings(uint16_t* dest, int width, int height, const SettingsSnapshot& snapshot) {
  if (dest == nullptr || width <= 0 || height <= 0) return;
  fill(dest, width, height, 0, 0, width, height, kBlack);
  if (!snapshot.open) return;

  const int rowH = height / 4;
  const int caretW = 3;
  const int left = width / 16;
  for (int row = 0; row < 2; ++row) {
    const bool focused = snapshot.focus == row;
    const bool adjusting = focused && snapshot.adjusting;
    const uint16_t color = focused ? kWhite : kDim;
    const int y = height / 2 - rowH + row * rowH;
    if (focused) {
      fill(dest, width, height, left, y + rowH / 4, caretW, rowH / 2, kWhite);
    }
    const char* label = row == 0 ? "BRIGHTNESS" : "VOLUME";
    text(dest, width, height, left + 12, y + 6, label, color);
    const int value = row == 0 ? snapshot.brightness : snapshot.volume;
    meter(dest, width, height, left + 12, y + 20, width - left * 2 - 28, 10, value, snapshot.steps, focused);
    if (adjusting) {
      fill(dest, width, height, width - left - 6, y + 8, 5, 2, kWhite);
      fill(dest, width, height, width - left - 6, y + rowH - 12, 5, 2, kWhite);
    }
  }
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
