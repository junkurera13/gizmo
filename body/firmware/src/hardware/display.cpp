#include "gizmo/display.h"
#include "gizmo/board.h"
#include <Arduino.h>
#include <SPI.h>

namespace gizmo {
namespace {
constexpr uint8_t kSwreset = 0x01;
constexpr uint8_t kSlpout = 0x11;
constexpr uint8_t kDispoff = 0x28;
constexpr uint8_t kDispon = 0x29;
constexpr uint8_t kCaset = 0x2A;
constexpr uint8_t kRaset = 0x2B;
constexpr uint8_t kRamwr = 0x2C;
constexpr uint8_t kMadctl = 0x36;
constexpr uint8_t kColmod = 0x3A;
constexpr uint8_t kMadctlMy = 0x80;
constexpr uint8_t kMadctlMx = 0x40;
constexpr uint8_t kMadctlMv = 0x20;
constexpr uint8_t kMadctlBgr = 0x08;
constexpr uint32_t kSpiHz = 40000000;
}  // namespace

void Display::command(uint8_t value) {
  digitalWrite(board::display_dc, LOW);
  digitalWrite(board::display_cs, LOW);
  SPI.write(value);
  digitalWrite(board::display_cs, HIGH);
}

void Display::data(uint8_t value) {
  digitalWrite(board::display_dc, HIGH);
  digitalWrite(board::display_cs, LOW);
  SPI.write(value);
  digitalWrite(board::display_cs, HIGH);
}

void Display::window(int x0, int y0, int x1, int y1) {
  command(kCaset);
  data(static_cast<uint8_t>(x0 >> 8));
  data(static_cast<uint8_t>(x0));
  data(static_cast<uint8_t>(x1 >> 8));
  data(static_cast<uint8_t>(x1));
  command(kRaset);
  data(static_cast<uint8_t>(y0 >> 8));
  data(static_cast<uint8_t>(y0));
  data(static_cast<uint8_t>(y1 >> 8));
  data(static_cast<uint8_t>(y1));
  command(kRamwr);
}

void Display::set_rotation(uint8_t rotation) {
  rotation_ = rotation & 3;
  uint8_t madctl = kMadctlBgr;
  switch (rotation_) {
    case 0:
      madctl |= kMadctlMx;
      width_ = 240;
      height_ = 320;
      break;
    case 1:
      madctl |= kMadctlMv;
      width_ = 320;
      height_ = 240;
      break;
    case 2:
      madctl |= kMadctlMy;
      width_ = 240;
      height_ = 320;
      break;
    default:
      madctl |= kMadctlMx | kMadctlMy | kMadctlMv;
      width_ = 320;
      height_ = 240;
      break;
  }
  if (!ready_) return;
  SPI.beginTransaction(SPISettings(kSpiHz, MSBFIRST, SPI_MODE0));
  command(kMadctl);
  data(madctl);
  SPI.endTransaction();
}

esp_err_t Display::begin() {
  pinMode(board::display_cs, OUTPUT);
  pinMode(board::display_dc, OUTPUT);
  digitalWrite(board::display_cs, HIGH);
  digitalWrite(board::display_dc, HIGH);
  SPI.begin(board::display_sck, board::display_miso, board::display_mosi, board::display_cs);

  SPI.beginTransaction(SPISettings(kSpiHz, MSBFIRST, SPI_MODE0));
  command(kSwreset);
  delay(150);
  command(kSlpout);
  delay(150);
  command(0xCF);
  data(0x00);
  data(0xC1);
  data(0x30);
  command(0xED);
  data(0x64);
  data(0x03);
  data(0x12);
  data(0x81);
  command(0xE8);
  data(0x85);
  data(0x00);
  data(0x78);
  command(0xCB);
  data(0x39);
  data(0x2C);
  data(0x00);
  data(0x34);
  data(0x02);
  command(0xF7);
  data(0x20);
  command(0xEA);
  data(0x00);
  data(0x00);
  command(0xC0);
  data(0x23);
  command(0xC1);
  data(0x10);
  command(0xC5);
  data(0x3E);
  data(0x28);
  command(0xC7);
  data(0x86);
  command(kColmod);
  data(0x55);
  command(0xB1);
  data(0x00);
  data(0x18);
  command(0xB6);
  data(0x08);
  data(0x82);
  data(0x27);
  command(kDispoff);
  SPI.endTransaction();

  ready_ = true;
  set_rotation(1);
  SPI.beginTransaction(SPISettings(kSpiHz, MSBFIRST, SPI_MODE0));
  command(kDispon);
  SPI.endTransaction();
  delay(20);
  return ESP_OK;
}

void Display::fill(uint16_t color) {
  if (!ready_) return;
  uint16_t line[320];
  const int rows = height_;
  const int cols = width_;
  if (cols <= 0 || rows <= 0 || cols > 320) return;
  for (int i = 0; i < cols; ++i) line[i] = color;
  SPI.beginTransaction(SPISettings(kSpiHz, MSBFIRST, SPI_MODE0));
  window(0, 0, cols - 1, rows - 1);
  digitalWrite(board::display_dc, HIGH);
  digitalWrite(board::display_cs, LOW);
  const uint32_t row_bytes = static_cast<uint32_t>(cols) * 2;
  for (int y = 0; y < rows; ++y) {
    SPI.writePixels(line, row_bytes);
  }
  digitalWrite(board::display_cs, HIGH);
  SPI.endTransaction();
}

void Display::blit_rgb565(const uint16_t* pixels, int width, int height) {
  if (!ready_ || pixels == nullptr || width <= 0 || height <= 0) return;
  const int cols = width < width_ ? width : width_;
  const int rows = height < height_ ? height : height_;
  SPI.beginTransaction(SPISettings(kSpiHz, MSBFIRST, SPI_MODE0));
  window(0, 0, cols - 1, rows - 1);
  digitalWrite(board::display_dc, HIGH);
  digitalWrite(board::display_cs, LOW);
  if (width == cols) {
    SPI.writePixels(pixels, static_cast<uint32_t>(cols) * rows * 2);
  } else {
    const uint32_t row_bytes = static_cast<uint32_t>(cols) * 2;
    for (int y = 0; y < rows; ++y) {
      SPI.writePixels(pixels + y * width, row_bytes);
    }
  }
  digitalWrite(board::display_cs, HIGH);
  SPI.endTransaction();
}
}  // namespace gizmo
