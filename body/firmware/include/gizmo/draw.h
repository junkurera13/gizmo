#pragma once

#include <stddef.h>
#include <stdint.h>

// Minimal RGB565 software rasteriser shared by every screen. All drawing is
// clipped to the canvas; nothing here touches the panel or the SPI bus.
namespace gizmo::draw {

struct Canvas {
  uint16_t* pixels = nullptr;
  int width = 0;
  int height = 0;
  bool valid() const { return pixels != nullptr && width > 0 && height > 0; }
};

constexpr uint16_t kBlack = 0x0000;
constexpr uint16_t kWhite = 0xFFFF;
constexpr uint16_t kDim = 0x7BEF;    // ~50% grey
constexpr uint16_t kMute = 0x39C7;   // ~20% grey
constexpr uint16_t kFaint = 0x2104;  // ~12% grey
constexpr uint16_t kRed = 0xF800;
constexpr uint16_t kAmber = 0xFD20;
constexpr uint16_t kGreen = 0x07E0;

constexpr int kGlyphWidth = 5;
constexpr int kGlyphHeight = 7;
constexpr int kGlyphAdvance = 6;

void clear(const Canvas& canvas, uint16_t color);
void fill_rect(const Canvas& canvas, int x, int y, int w, int h, uint16_t color);
void rect(const Canvas& canvas, int x, int y, int w, int h, uint16_t color);

// 5x7 capitals, digits and a few symbols. Lowercase is drawn as capitals.
// '^' is an up arrow and '_' a down arrow. Unknown characters advance blank.
void text(const Canvas& canvas, int x, int y, const char* label, uint16_t color, int scale = 1);
int text_width(const char* label, int scale = 1);
void text_centered(const Canvas& canvas, int cx, int y, const char* label, uint16_t color, int scale = 1);

// Row of `steps` pips, `value` of them lit. Unlit pips are drawn shorter.
void meter(const Canvas& canvas, int x, int y, int w, int h, int value, int steps, bool lit);

// Horizontal progress bar with an outline; `fraction` is 0..1.
void progress(const Canvas& canvas, int x, int y, int w, int h, float fraction, uint16_t color);

// Alpha-blend a sprite stored as interleaved little-endian RGB565 + A8
// (three bytes per pixel, row-major) onto the canvas.
void blit_rgb565a(const Canvas& canvas, int x, int y, const uint8_t* sprite, int w, int h);

// Alpha-blend a solid colour through an 8-bit mask. `mask` points at the
// top-left of the region inside an atlas whose rows are `stride` bytes apart.
void blit_mask(const Canvas& canvas, int x, int y, const uint8_t* mask, int stride, int w, int h, uint16_t color);

// Copy a same-size RGB565 image over the whole canvas.
void copy(const Canvas& canvas, const uint16_t* source);

}  // namespace gizmo::draw
