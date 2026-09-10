#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include "gizmo/settings.h"

int main() {
  assert(gizmo::backlight_duty(0, 10) == 46);
  assert(gizmo::backlight_duty(10, 10) == 255);
  assert(gizmo::backlight_duty(5, 10) > gizmo::backlight_duty(0, 10));
  assert(gizmo::backlight_duty(5, 10) < gizmo::backlight_duty(10, 10));
  assert(gizmo::backlight_duty(0, 0) == 255);

  int16_t half[2] = {1000, -1000};
  gizmo::apply_volume(half, 2, 5, 10);
  assert(half[0] == 500 && half[1] == -500);

  int16_t mute[1] = {12345};
  gizmo::apply_volume(mute, 1, 0, 10);
  assert(mute[0] == 0);

  int16_t full[1] = {12345};
  gizmo::apply_volume(full, 1, 10, 10);
  assert(full[0] == 12345);

  assert(gizmo::dim_rgb565(0xFFFF, 255) == 0xFFFF);
  assert(gizmo::dim_rgb565(0xFFFF, 0) == 0);
  const uint16_t mid = gizmo::dim_rgb565(0xFFFF, 128);
  assert(mid != 0 && mid < 0xFFFF);
  const uint16_t step0 = gizmo::dim_rgb565(0xFFFF, gizmo::backlight_duty(0, 10));
  const uint16_t step10 = gizmo::dim_rgb565(0xFFFF, gizmo::backlight_duty(10, 10));
  assert(step0 < step10);
  assert(step10 == 0xFFFF);

  uint16_t pixels[3] = {0xFFFF, 0x07E0, 0x001F};
  gizmo::apply_pixel_gain(pixels, pixels, 3, 255);
  assert(pixels[0] == 0xFFFF && pixels[1] == 0x07E0 && pixels[2] == 0x001F);
  gizmo::apply_pixel_gain(pixels, pixels, 3, 0);
  assert(pixels[0] == 0 && pixels[1] == 0 && pixels[2] == 0);

  int16_t tick[gizmo::kVolumeTickSamples];
  gizmo::fill_volume_tick(tick, gizmo::kVolumeTickSamples);
  int32_t peak = 0;
  bool has_pos = false;
  bool has_neg = false;
  for (size_t i = 0; i < gizmo::kVolumeTickSamples; ++i) {
    const int32_t mag = tick[i] < 0 ? -tick[i] : tick[i];
    if (mag > peak) peak = mag;
    if (tick[i] > 0) has_pos = true;
    if (tick[i] < 0) has_neg = true;
  }
  assert(has_pos && has_neg);
  assert(peak > 1000);
  const int32_t early = tick[32] < 0 ? -tick[32] : tick[32];
  const int32_t late = tick[gizmo::kVolumeTickSamples - 1] < 0
                           ? -tick[gizmo::kVolumeTickSamples - 1]
                           : tick[gizmo::kVolumeTickSamples - 1];
  assert(late < early);
  assert(gizmo::volume_tick()[0] == 0);

  int16_t scaled[gizmo::kVolumeTickSamples];
  gizmo::fill_volume_tick(scaled, gizmo::kVolumeTickSamples);
  gizmo::apply_volume(scaled, gizmo::kVolumeTickSamples, 3, 10);
  int32_t scaled_peak = 0;
  for (size_t i = 0; i < gizmo::kVolumeTickSamples; ++i) {
    const int32_t mag = scaled[i] < 0 ? -scaled[i] : scaled[i];
    if (mag > scaled_peak) scaled_peak = mag;
  }
  assert(scaled_peak > 0);
  assert(scaled_peak < peak);
  assert(scaled_peak <= (peak * 3) / 10 + 1);

  static uint16_t dest[320 * 240];
  gizmo::render_settings(dest, 320, 240, gizmo::SettingsSnapshot{});
  gizmo::SettingsSnapshot open;
  open.open = true;
  open.adjusting = true;
  open.focus = 1;
  open.volume = 4;
  gizmo::render_settings(dest, 320, 240, open);
  bool lit = false;
  for (int i = 0; i < 320 * 240; ++i) {
    if (dest[i] != 0) {
      lit = true;
      break;
    }
  }
  assert(lit);

  puts("settings: duty, volume, pixel gain, tick passed");
  return 0;
}
