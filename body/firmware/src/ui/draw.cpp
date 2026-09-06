#include "gizmo/draw.h"

namespace gizmo::draw {
namespace {

struct Glyph {
  char letter;
  uint8_t rows[kGlyphHeight];  // bit 4 is the left pixel
};

const Glyph kGlyphs[] = {
    {'A', {0x0E, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11}},
    {'B', {0x1E, 0x11, 0x11, 0x1E, 0x11, 0x11, 0x1E}},
    {'C', {0x0E, 0x11, 0x10, 0x10, 0x10, 0x11, 0x0E}},
    {'D', {0x1E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x1E}},
    {'E', {0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x1F}},
    {'F', {0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x10}},
    {'G', {0x0E, 0x11, 0x10, 0x17, 0x11, 0x11, 0x0E}},
    {'H', {0x11, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11}},
    {'I', {0x1F, 0x04, 0x04, 0x04, 0x04, 0x04, 0x1F}},
    {'J', {0x07, 0x02, 0x02, 0x02, 0x02, 0x12, 0x0C}},
    {'K', {0x11, 0x12, 0x14, 0x18, 0x14, 0x12, 0x11}},
    {'L', {0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x1F}},
    {'M', {0x11, 0x1B, 0x15, 0x15, 0x11, 0x11, 0x11}},
    {'N', {0x11, 0x19, 0x15, 0x13, 0x11, 0x11, 0x11}},
    {'O', {0x0E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E}},
    {'P', {0x1E, 0x11, 0x11, 0x1E, 0x10, 0x10, 0x10}},
    {'Q', {0x0E, 0x11, 0x11, 0x11, 0x15, 0x12, 0x0D}},
    {'R', {0x1E, 0x11, 0x11, 0x1E, 0x14, 0x12, 0x11}},
    {'S', {0x0F, 0x10, 0x10, 0x0E, 0x01, 0x01, 0x1E}},
    {'T', {0x1F, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04}},
    {'U', {0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E}},
    {'V', {0x11, 0x11, 0x11, 0x11, 0x11, 0x0A, 0x04}},
    {'W', {0x11, 0x11, 0x11, 0x15, 0x15, 0x15, 0x0A}},
    {'X', {0x11, 0x11, 0x0A, 0x04, 0x0A, 0x11, 0x11}},
    {'Y', {0x11, 0x11, 0x11, 0x0A, 0x04, 0x04, 0x04}},
    {'Z', {0x1F, 0x01, 0x02, 0x04, 0x08, 0x10, 0x1F}},
    {'0', {0x0E, 0x11, 0x13, 0x15, 0x19, 0x11, 0x0E}},
    {'1', {0x04, 0x0C, 0x04, 0x04, 0x04, 0x04, 0x0E}},
    {'2', {0x0E, 0x11, 0x01, 0x02, 0x04, 0x08, 0x1F}},
    {'3', {0x1F, 0x02, 0x04, 0x02, 0x01, 0x11, 0x0E}},
    {'4', {0x02, 0x06, 0x0A, 0x12, 0x1F, 0x02, 0x02}},
    {'5', {0x1F, 0x10, 0x1E, 0x01, 0x01, 0x11, 0x0E}},
    {'6', {0x06, 0x08, 0x10, 0x1E, 0x11, 0x11, 0x0E}},
    {'7', {0x1F, 0x01, 0x02, 0x04, 0x08, 0x08, 0x08}},
    {'8', {0x0E, 0x11, 0x11, 0x0E, 0x11, 0x11, 0x0E}},
    {'9', {0x0E, 0x11, 0x11, 0x0F, 0x01, 0x02, 0x0C}},
    {'%', {0x18, 0x19, 0x02, 0x04, 0x08, 0x13, 0x03}},
    {':', {0x00, 0x04, 0x04, 0x00, 0x04, 0x04, 0x00}},
    {'.', {0x00, 0x00, 0x00, 0x00, 0x00, 0x0C, 0x0C}},
    {'-', {0x00, 0x00, 0x00, 0x1F, 0x00, 0x00, 0x00}},
    {'+', {0x00, 0x04, 0x04, 0x1F, 0x04, 0x04, 0x00}},
    {'/', {0x01, 0x01, 0x02, 0x04, 0x08, 0x10, 0x10}},
    {'<', {0x02, 0x04, 0x08, 0x10, 0x08, 0x04, 0x02}},
    {'>', {0x08, 0x04, 0x02, 0x01, 0x02, 0x04, 0x08}},
    {'!', {0x04, 0x04, 0x04, 0x04, 0x04, 0x00, 0x04}},
    {'?', {0x0E, 0x11, 0x01, 0x02, 0x04, 0x00, 0x04}},
    {'(', {0x02, 0x04, 0x08, 0x08, 0x08, 0x04, 0x02}},
    {')', {0x08, 0x04, 0x02, 0x02, 0x02, 0x04, 0x08}},
    {'^', {0x04, 0x0E, 0x15, 0x04, 0x04, 0x04, 0x04}},
    {'_', {0x04, 0x04, 0x04, 0x04, 0x15, 0x0E, 0x04}},
};

const Glyph* find_glyph(char letter) {
  if (letter >= 'a' && letter <= 'z') letter = static_cast<char>(letter - 'a' + 'A');
  for (const auto& entry : kGlyphs) {
    if (entry.letter == letter) return &entry;
  }
  return nullptr;
}

}  // namespace

void clear(const Canvas& canvas, uint16_t color) {
  if (!canvas.valid()) return;
  const int count = canvas.width * canvas.height;
  for (int i = 0; i < count; ++i) canvas.pixels[i] = color;
}

void fill_rect(const Canvas& canvas, int x, int y, int w, int h, uint16_t color) {
  if (!canvas.valid() || w <= 0 || h <= 0) return;
  const int x0 = x < 0 ? 0 : x;
  const int y0 = y < 0 ? 0 : y;
  const int x1 = x + w > canvas.width ? canvas.width : x + w;
  const int y1 = y + h > canvas.height ? canvas.height : y + h;
  for (int row = y0; row < y1; ++row) {
    uint16_t* line = canvas.pixels + row * canvas.width;
    for (int col = x0; col < x1; ++col) line[col] = color;
  }
}

void rect(const Canvas& canvas, int x, int y, int w, int h, uint16_t color) {
  if (w <= 0 || h <= 0) return;
  fill_rect(canvas, x, y, w, 1, color);
  fill_rect(canvas, x, y + h - 1, w, 1, color);
  fill_rect(canvas, x, y, 1, h, color);
  fill_rect(canvas, x + w - 1, y, 1, h, color);
}

void text(const Canvas& canvas, int x, int y, const char* label, uint16_t color, int scale) {
  if (label == nullptr || scale <= 0) return;
  for (int index = 0; label[index]; ++index) {
    const Glyph* glyph = find_glyph(label[index]);
    if (glyph != nullptr) {
      for (int row = 0; row < kGlyphHeight; ++row) {
        const uint8_t bits = glyph->rows[row];
        for (int col = 0; col < kGlyphWidth; ++col) {
          if (bits & (1 << (kGlyphWidth - 1 - col))) {
            fill_rect(canvas, x + col * scale, y + row * scale, scale, scale, color);
          }
        }
      }
    }
    x += kGlyphAdvance * scale;
  }
}

int text_width(const char* label, int scale) {
  if (label == nullptr || scale <= 0) return 0;
  int count = 0;
  while (label[count]) ++count;
  if (count == 0) return 0;
  return count * kGlyphAdvance * scale - scale;
}

void text_centered(const Canvas& canvas, int cx, int y, const char* label, uint16_t color, int scale) {
  text(canvas, cx - text_width(label, scale) / 2, y, label, color, scale);
}

void meter(const Canvas& canvas, int x, int y, int w, int h, int value, int steps, bool lit) {
  if (steps <= 0 || w <= 0) return;
  const int gap = 2;
  const int pip = (w - gap * (steps - 1)) / steps;
  if (pip <= 0) return;
  for (int index = 0; index < steps; ++index) {
    const bool on = index < value;
    const int pipH = on ? h : (h * 62) / 100;
    const int pipY = y + (h - pipH) / 2;
    fill_rect(canvas, x + index * (pip + gap), pipY, pip, pipH, on ? (lit ? kWhite : kDim) : kMute);
  }
}

namespace {
inline uint16_t blend(uint16_t under, uint16_t over, uint8_t alpha) {
  if (alpha == 255) return over;
  if (alpha == 0) return under;
  const int ur = (under >> 11) & 0x1F, ug = (under >> 5) & 0x3F, ub = under & 0x1F;
  const int orr = (over >> 11) & 0x1F, og = (over >> 5) & 0x3F, ob = over & 0x1F;
  const int inv = 255 - alpha;
  const int r = (orr * alpha + ur * inv) / 255;
  const int g = (og * alpha + ug * inv) / 255;
  const int b = (ob * alpha + ub * inv) / 255;
  return static_cast<uint16_t>((r << 11) | (g << 5) | b);
}
}  // namespace

void blit_rgb565a(const Canvas& canvas, int x, int y, const uint8_t* sprite, int w, int h) {
  if (!canvas.valid() || sprite == nullptr) return;
  for (int row = 0; row < h; ++row) {
    const int py = y + row;
    if (py < 0 || py >= canvas.height) continue;
    uint16_t* line = canvas.pixels + py * canvas.width;
    const uint8_t* src = sprite + static_cast<size_t>(row) * w * 3;
    for (int col = 0; col < w; ++col, src += 3) {
      const int px = x + col;
      if (px < 0 || px >= canvas.width) continue;
      const uint16_t color = static_cast<uint16_t>(src[0] | (src[1] << 8));
      line[px] = blend(line[px], color, src[2]);
    }
  }
}

void blit_mask(const Canvas& canvas, int x, int y, const uint8_t* mask, int stride, int w, int h, uint16_t color) {
  if (!canvas.valid() || mask == nullptr) return;
  for (int row = 0; row < h; ++row) {
    const int py = y + row;
    if (py < 0 || py >= canvas.height) continue;
    uint16_t* line = canvas.pixels + py * canvas.width;
    const uint8_t* src = mask + static_cast<size_t>(row) * stride;
    for (int col = 0; col < w; ++col) {
      const int px = x + col;
      if (px < 0 || px >= canvas.width) continue;
      line[px] = blend(line[px], color, src[col]);
    }
  }
}

void copy(const Canvas& canvas, const uint16_t* source) {
  if (!canvas.valid() || source == nullptr) return;
  const size_t count = static_cast<size_t>(canvas.width) * canvas.height;
  for (size_t i = 0; i < count; ++i) canvas.pixels[i] = source[i];
}

void progress(const Canvas& canvas, int x, int y, int w, int h, float fraction, uint16_t color) {
  if (w <= 2 || h <= 2) return;
  if (fraction < 0.0f) fraction = 0.0f;
  if (fraction > 1.0f) fraction = 1.0f;
  rect(canvas, x, y, w, h, kDim);
  const int inner = static_cast<int>((w - 2) * fraction);
  fill_rect(canvas, x + 1, y + 1, inner, h - 2, color);
}

}  // namespace gizmo::draw
