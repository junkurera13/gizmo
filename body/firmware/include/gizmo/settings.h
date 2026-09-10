#pragma once

#include <stddef.h>
#include <stdint.h>

// Target: Friend owns the Settings menu; firmware paints this snapshot.
// Today the local terminal OS in main.cpp owns the menu and NVS until /ws
// exists. Keep this struct aligned with friend/gizmo_friend/settings.py
// (open focus = volume, default step = 8). Panel SPI is in board.h. LED is
// tied to 3V3, so backlight PWM cannot run; brightness scales RGB565 on blit.
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

// 0–255 PWM duty for the panel backlight, and the software pixel gain used
// when LED is tied high. Step 0 stays just readable (~18%).
uint8_t backlight_duty(uint8_t step, uint8_t steps = 10);

// Scale one RGB565 pixel by an 8-bit gain (255 = unchanged).
uint16_t dim_rgb565(uint16_t pixel, uint8_t duty);

// Scale `count` RGB565 pixels from `src` into `dest`. Overlap is allowed
// when dest == src. `src`/`dest` may be null only when count == 0.
void apply_pixel_gain(uint16_t* dest, const uint16_t* src, size_t count, uint8_t duty);

// Scale signed 16-bit little-endian PCM by the volume step.
void apply_volume(int16_t* samples, size_t count, uint8_t step, uint8_t steps = 10);

// Local volume-step cue: 16 kHz mono PCM16, full-scale, ~50 ms. Playback
// applies the current volume step so mute is silent and max is loud.
constexpr uint32_t kVolumeTickRate = 16000;
constexpr size_t kVolumeTickSamples = 800;  // 50 ms
void fill_volume_tick(int16_t* dest, size_t count);
const int16_t* volume_tick();

}  // namespace gizmo
