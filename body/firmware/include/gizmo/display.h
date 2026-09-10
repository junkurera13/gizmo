#pragma once

#include <esp_err.h>
#include <stdint.h>

namespace gizmo {
// ILI9341 SPI panel. MISO is unused, so begin() cannot read a chip ID.
class Display {
 public:
  esp_err_t begin();
  void fill(uint16_t color);
  void blit_rgb565(const uint16_t* pixels, int width, int height);
  void set_rotation(uint8_t rotation);
  // 0–255 software pixel gain applied at blit time. Used because the
  // current panel LED is tied to 3V3 (no backlight PWM pin).
  void set_pixel_gain(uint8_t duty);
  uint8_t pixel_gain() const { return pixel_gain_; }
  uint8_t rotation() const { return rotation_; }
  bool ready() const { return ready_; }
  int width() const { return width_; }
  int height() const { return height_; }

 private:
  void command(uint8_t value);
  void data(uint8_t value);
  void window(int x0, int y0, int x1, int y1);

  bool ready_ = false;
  uint8_t rotation_ = 1;
  uint8_t pixel_gain_ = 255;
  int width_ = 320;
  int height_ = 240;
};
}  // namespace gizmo
