#include "gizmo/display.h"
#include "gizmo/board.h"
#include "gizmo/settings.h"
#include <Arduino.h>
#include <driver/spi_master.h>
#include <esp_heap_caps.h>
#include <esp_lcd_panel_io.h>
#include <freertos/semphr.h>

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

// The panel's TE output is not wired, so shortening each update is our only
// way to keep it inside one scan. Arduino SPI.writePixels() refills a 64-byte
// FIFO from PSRAM and took 33-36 ms for the film band on the physical Gizmo.
// A small internal-RAM strip lets GDMA feed SPI continuously without needing a
// second full framebuffer in the scarce internal heap.
constexpr uint32_t kSpiHz = 80000000;
constexpr int kDmaRows = 16;
constexpr size_t kDmaPixels = static_cast<size_t>(board::display_width) * kDmaRows;
constexpr size_t kDmaBytes = kDmaPixels * sizeof(uint16_t);
constexpr TickType_t kTransferTimeout = pdMS_TO_TICKS(100);

inline uint16_t panel_order(uint16_t color) {
  return static_cast<uint16_t>((color >> 8) | (color << 8));
}

bool color_transfer_done(esp_lcd_panel_io_handle_t, esp_lcd_panel_io_event_data_t*, void* context) {
  BaseType_t wake = pdFALSE;
  xSemaphoreGiveFromISR(static_cast<SemaphoreHandle_t>(context), &wake);
  return wake == pdTRUE;
}
}  // namespace

void Display::command(uint8_t value) {
  if (!panel_io_) return;
  esp_lcd_panel_io_tx_param(static_cast<esp_lcd_panel_io_handle_t>(panel_io_), value, nullptr, 0);
}

void Display::data(uint8_t value) {
  if (!panel_io_) return;
  esp_lcd_panel_io_tx_param(static_cast<esp_lcd_panel_io_handle_t>(panel_io_), -1, &value, 1);
}

void Display::window(int x0, int y0, int x1, int y1) {
  const uint8_t columns[] = {static_cast<uint8_t>(x0 >> 8), static_cast<uint8_t>(x0),
                             static_cast<uint8_t>(x1 >> 8), static_cast<uint8_t>(x1)};
  const uint8_t rows[] = {static_cast<uint8_t>(y0 >> 8), static_cast<uint8_t>(y0),
                          static_cast<uint8_t>(y1 >> 8), static_cast<uint8_t>(y1)};
  auto io = static_cast<esp_lcd_panel_io_handle_t>(panel_io_);
  esp_lcd_panel_io_tx_param(io, kCaset, columns, sizeof(columns));
  esp_lcd_panel_io_tx_param(io, kRaset, rows, sizeof(rows));
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
  esp_lcd_panel_io_tx_param(static_cast<esp_lcd_panel_io_handle_t>(panel_io_), kMadctl, &madctl, 1);
}

esp_err_t Display::begin() {
  color_done_sem_ = xSemaphoreCreateBinary();
  dma_pixels_ = static_cast<uint16_t*>(
      heap_caps_malloc(kDmaBytes, MALLOC_CAP_INTERNAL | MALLOC_CAP_DMA | MALLOC_CAP_8BIT));
  if (!color_done_sem_ || !dma_pixels_) return ESP_ERR_NO_MEM;

  spi_bus_config_t bus = {};
  bus.mosi_io_num = board::display_mosi;
  bus.miso_io_num = board::display_miso;
  bus.sclk_io_num = board::display_sck;
  bus.quadwp_io_num = -1;
  bus.quadhd_io_num = -1;
  bus.data4_io_num = -1;
  bus.data5_io_num = -1;
  bus.data6_io_num = -1;
  bus.data7_io_num = -1;
  bus.max_transfer_sz = static_cast<int>(kDmaBytes);
  esp_err_t error = spi_bus_initialize(SPI2_HOST, &bus, SPI_DMA_CH_AUTO);
  if (error != ESP_OK) return error;

  esp_lcd_panel_io_spi_config_t io_config = {};
  io_config.cs_gpio_num = board::display_cs;
  io_config.dc_gpio_num = board::display_dc;
  io_config.spi_mode = 0;
  io_config.pclk_hz = kSpiHz;
  io_config.trans_queue_depth = 1;
  io_config.on_color_trans_done = color_transfer_done;
  io_config.user_ctx = color_done_sem_;
  io_config.lcd_cmd_bits = 8;
  io_config.lcd_param_bits = 8;
  esp_lcd_panel_io_handle_t io = nullptr;
  error = esp_lcd_new_panel_io_spi(
      reinterpret_cast<esp_lcd_spi_bus_handle_t>(static_cast<intptr_t>(SPI2_HOST)), &io_config, &io);
  if (error != ESP_OK) {
    spi_bus_free(SPI2_HOST);
    return error;
  }
  panel_io_ = io;

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

  ready_ = true;
  set_rotation(1);
  command(kDispon);
  delay(20);
  return ESP_OK;
}

void Display::set_pixel_gain(uint8_t duty) {
  pixel_gain_ = duty;
}

void Display::fill(uint16_t color) {
  if (!ready_) return;
  const int rows = height_;
  const int cols = width_;
  if (cols <= 0 || rows <= 0 || cols > board::display_width) return;
  const uint16_t scaled = panel_order(dim_rgb565(color, pixel_gain_));
  for (size_t i = 0; i < kDmaPixels; ++i) dma_pixels_[i] = scaled;

  auto io = static_cast<esp_lcd_panel_io_handle_t>(panel_io_);
  auto done = static_cast<SemaphoreHandle_t>(color_done_sem_);
  for (int row = 0; row < rows; row += kDmaRows) {
    const int strip_rows = min(kDmaRows, rows - row);
    window(0, row, cols - 1, row + strip_rows - 1);
    xSemaphoreTake(done, 0);
    const esp_err_t error = esp_lcd_panel_io_tx_color(
        io, kRamwr, dma_pixels_, static_cast<size_t>(cols) * strip_rows * sizeof(uint16_t));
    if (error != ESP_OK || xSemaphoreTake(done, kTransferTimeout) != pdTRUE) {
      Serial.printf("display: DMA fill failed: %s\n", esp_err_to_name(error));
      return;
    }
  }
}

bool Display::write_pixels(const uint16_t* pixels, int source_width, int cols, int y0, int rows) {
  auto io = static_cast<esp_lcd_panel_io_handle_t>(panel_io_);
  auto done = static_cast<SemaphoreHandle_t>(color_done_sem_);
  for (int row = 0; row < rows; row += kDmaRows) {
    const int strip_rows = min(kDmaRows, rows - row);
    const size_t strip_pixels = static_cast<size_t>(cols) * strip_rows;
    size_t out = 0;
    for (int strip_y = 0; strip_y < strip_rows; ++strip_y) {
      const uint16_t* source =
          pixels + static_cast<size_t>(y0 + row + strip_y) * source_width;
      for (int x = 0; x < cols; ++x) {
        const uint16_t color = pixel_gain_ >= 255 ? source[x] : dim_rgb565(source[x], pixel_gain_);
        dma_pixels_[out++] = panel_order(color);
      }
    }

    window(0, y0 + row, cols - 1, y0 + row + strip_rows - 1);
    xSemaphoreTake(done, 0);
    const esp_err_t error =
        esp_lcd_panel_io_tx_color(io, kRamwr, dma_pixels_, strip_pixels * sizeof(uint16_t));
    if (error != ESP_OK || xSemaphoreTake(done, kTransferTimeout) != pdTRUE) {
      Serial.printf("display: DMA blit failed: %s\n", esp_err_to_name(error));
      return false;
    }
  }
  return true;
}

void Display::blit_rgb565(const uint16_t* pixels, int width, int height) {
  blit_rgb565_rows(pixels, width, 0, height);
}

void Display::blit_rgb565_rows(const uint16_t* pixels, int width, int y0, int rows) {
  if (!ready_ || pixels == nullptr || width <= 0 || rows <= 0 || y0 < 0 || y0 >= height_) return;
  const int cols = width < width_ ? width : width_;
  const int count = y0 + rows > height_ ? height_ - y0 : rows;
  if (cols <= 0 || count <= 0) return;
  write_pixels(pixels, width, cols, y0, count);
}
}  // namespace gizmo
