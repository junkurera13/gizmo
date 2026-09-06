#pragma once

#include <stddef.h>
#include <stdint.h>

// Friend owns the Settings menu. Firmware paints this snapshot on the glass.
// Panel SPI is in board.h. LED is tied to 3V3, so backlight PWM is not driven.
namespace gizmo {

struct SettingsSnapshot {
  bool open = false;
  bool adjusting = false;
  uint8_t focus = 0;  // 0 brightness, 1 volume
  uint8_t brightness = 8;
  uint8_t volume = 8;
  uint8_t steps = 10;
};

constexpr int kSettingsWidth = 320;
constexpr int kSettingsHeight = 240;

// RGB565, row-major, width*height entries. Safe to call with width/height
// smaller than the panel; extra destination is left untouched.
void render_settings(uint16_t* dest, int width, int height, const SettingsSnapshot& snapshot);

// 0–255 PWM duty for the panel backlight. Step 0 stays just readable.
uint8_t backlight_duty(uint8_t step, uint8_t steps = 10);

// Scale signed 16-bit little-endian PCM by the volume step.
void apply_volume(int16_t* samples, size_t count, uint8_t step, uint8_t steps = 10);

}  // namespace gizmo
