#include "gizmo/screens.h"
#include <stdio.h>
#include <string.h>
#include "gizmo/assets.h"

namespace gizmo {
namespace {

void format_clock(char* out, size_t size, uint32_t ms) {
  const uint32_t total = ms / 1000;
  snprintf(out, size, "%u:%02u", static_cast<unsigned>(total / 60), static_cast<unsigned>(total % 60));
}

int clock_cell(char c) {
  for (int i = 0; assets::kClockCharacters[i]; ++i) {
    if (assets::kClockCharacters[i] == c) return i;
  }
  return -1;
}

// Advance per character. The atlas centres every glyph in a cell as wide as
// the widest digit; the colon is narrow, so it advances about half a cell to
// match the proportional text in the simulator.
int clock_advance(char c) {
  return c == ':' ? assets::kClockCellWidth / 2 + 1 : assets::kClockCellWidth;
}

int clock_width(const char* text) {
  int width = 0;
  for (int i = 0; text[i]; ++i) width += clock_advance(text[i]);
  return width;
}

void draw_clock(const draw::Canvas& canvas, int x, int y, const char* text) {
  const uint8_t* atlas = assets::clock_atlas();
  for (int i = 0; text[i]; ++i) {
    const int cell = clock_cell(text[i]);
    const int advance = clock_advance(text[i]);
    if (cell >= 0) {
      const int cellX = x - (assets::kClockCellWidth - advance) / 2;
      draw::blit_mask(canvas, cellX, y, atlas + cell * assets::kClockCellWidth, assets::kClockAtlasWidth,
                      assets::kClockCellWidth, assets::kClockCellHeight, draw::kWhite);
    }
    x += advance;
  }
}

// Bottom band shared by the memo overlays.
constexpr int kBandHeight = 46;

void band(const draw::Canvas& canvas) {
  draw::fill_rect(canvas, 0, canvas.height - kBandHeight, canvas.width, kBandHeight, draw::kBlack);
  draw::fill_rect(canvas, 0, canvas.height - kBandHeight, canvas.width, 1, draw::kFaint);
}

}  // namespace

void render_hud(const draw::Canvas& canvas, const Hud& hud) {
  if (!canvas.valid()) return;
  // Mirrors export_bundle.render_home_preview / the emulator glass HUD:
  // the clock, then a battery outline with a charge fill and nub.
  const int capHeight = assets::kStatusCapHeight;
  const float groupSpacing = capHeight * 0.7f;
  const int top = static_cast<int>(canvas.height * assets::kStatusTopFraction + 0.5f);

  // Battery proportions follow the emulator's glass icon: a ~2:1 body one cap
  // height tall, a 1px wall, 2px padding, then the nub.
  const int bodyW = capHeight * 2;
  const int bodyH = capHeight;
  const int pad = 2;
  const int nubGap = 1;
  const int nubW = 2;
  const int nubH = capHeight * 2 / 5;
  const float batteryWidth = bodyW + nubGap + nubW;

  char clock[8] = "";
  int clockW = 0;
  if (hud.has_time) {
    snprintf(clock, sizeof(clock), "%d:%02d", hud.hour, hud.minute);
    clockW = clock_width(clock);
  }
  const float groupWidth = hud.has_time ? clockW + groupSpacing + batteryWidth : batteryWidth;
  const float x = (canvas.width - groupWidth) / 2.0f;
  float batteryX = x;
  if (hud.has_time) {
    draw_clock(canvas, static_cast<int>(x + 0.5f), top, clock);
    batteryX = x + clockW + groupSpacing;
  }
  const int bx = static_cast<int>(batteryX + 0.5f);
  const int by = top + capHeight / 5;
  // 1px outline with a single-pixel diagonal step at each corner.
  draw::fill_rect(canvas, bx + 2, by, bodyW - 4, 1, draw::kWhite);
  draw::fill_rect(canvas, bx + 2, by + bodyH - 1, bodyW - 4, 1, draw::kWhite);
  draw::fill_rect(canvas, bx, by + 2, 1, bodyH - 4, draw::kWhite);
  draw::fill_rect(canvas, bx + bodyW - 1, by + 2, 1, bodyH - 4, draw::kWhite);
  draw::fill_rect(canvas, bx + 1, by + 1, 1, 1, draw::kWhite);
  draw::fill_rect(canvas, bx + bodyW - 2, by + 1, 1, 1, draw::kWhite);
  draw::fill_rect(canvas, bx + 1, by + bodyH - 2, 1, 1, draw::kWhite);
  draw::fill_rect(canvas, bx + bodyW - 2, by + bodyH - 2, 1, 1, draw::kWhite);
  int level = hud.half_steps;
  if (level < 0) level = 0;
  if (level > assets::kHalfSteps) level = assets::kHalfSteps;
  if (level) {
    const int innerW = bodyW - 2 * (1 + pad);
    draw::fill_rect(canvas, bx + 1 + pad, by + 1 + pad, innerW * level / assets::kHalfSteps,
                    bodyH - 2 * (1 + pad), draw::kWhite);
  }
  draw::fill_rect(canvas, bx + bodyW + nubGap, by + (bodyH - nubH) / 2, nubW, nubH, draw::kWhite);
}

void render_recording_overlay(const draw::Canvas& canvas, uint8_t vu, uint32_t elapsed_ms, uint32_t capacity_ms) {
  if (!canvas.valid()) return;
  band(canvas);
  const int y = canvas.height - kBandHeight + 8;
  const bool dot = (elapsed_ms / 500) % 2 == 0;
  if (dot) draw::fill_rect(canvas, 12, y + 2, 10, 10, draw::kRed);
  draw::text(canvas, 28, y, "REC", draw::kWhite, 2);
  char clock[12];
  format_clock(clock, sizeof(clock), elapsed_ms);
  draw::text(canvas, 76, y, clock, draw::kWhite, 2);
  const int meterX = 140;
  const int meterW = canvas.width - meterX - 12;
  const int gap = 3;
  const int pip = (meterW - gap * 9) / 10;
  for (int i = 0; i < 10; ++i) {
    const bool on = i < vu;
    uint16_t color = draw::kMute;
    if (on) color = i >= 8 ? draw::kAmber : draw::kWhite;
    draw::fill_rect(canvas, meterX + i * (pip + gap), y, pip, 14, color);
  }
  const float fraction = capacity_ms == 0 ? 0.0f : static_cast<float>(elapsed_ms) / capacity_ms;
  draw::progress(canvas, 12, canvas.height - 14, canvas.width - 24, 6, fraction, draw::kDim);
}

void render_playback_overlay(const draw::Canvas& canvas, uint8_t vu, float progress, uint32_t memo_ms) {
  if (!canvas.valid()) return;
  band(canvas);
  const int y = canvas.height - kBandHeight + 8;
  for (int row = 0; row < 12; ++row) {
    const int half = row < 6 ? row : 11 - row;
    draw::fill_rect(canvas, 12, y + 1 + row, half + 1, 1, draw::kGreen);
  }
  draw::text(canvas, 28, y, "PLAY", draw::kWhite, 2);
  char clock[12], total[12], both[28];
  format_clock(clock, sizeof(clock), static_cast<uint32_t>(progress * memo_ms));
  format_clock(total, sizeof(total), memo_ms);
  snprintf(both, sizeof(both), "%s/%s", clock, total);
  draw::text(canvas, 88, y + 4, both, draw::kDim, 1);
  draw::meter(canvas, 160, y, canvas.width - 160 - 12, 14, vu, 10, true);
  draw::progress(canvas, 12, canvas.height - 14, canvas.width - 24, 6, progress, draw::kWhite);
}

void render_camera_world(const draw::Canvas& canvas, bool viewfinder_ready, const char* status) {
  if (!canvas.valid()) return;
  if (viewfinder_ready) return;  // the canvas already holds the full-panel capture
  draw::fill_rect(canvas, 0, 0, canvas.width, canvas.height, draw::kBlack);
  const char* label = status && status[0] ? status : "CAMERA";
  draw::text_centered(canvas, canvas.width / 2, canvas.height / 2 - 4, label, draw::kDim, 1);
}

void render_wifi_setup(const draw::Canvas& canvas, const char* title, const char* line, const char* detail) {
  if (!canvas.valid()) return;
  const int h = 78;
  const int y = canvas.height - h;
  draw::fill_rect(canvas, 0, y, canvas.width, h, draw::kBlack);
  draw::fill_rect(canvas, 0, y, canvas.width, 1, draw::kFaint);
  draw::text_centered(canvas, canvas.width / 2, y + 10, title && title[0] ? title : "OPEN PHONE WIFI", draw::kDim, 1);
  draw::text_centered(canvas, canvas.width / 2, y + 26, line && line[0] ? line : "GIZMO", draw::kWhite, 2);
  draw::text_centered(canvas, canvas.width / 2, y + 52, detail && detail[0] ? detail : "WAITING FOR PHONE", draw::kDim,
                      1);
}

void render_caption(const draw::Canvas& canvas, const char* line) {
  if (!canvas.valid() || !line || !line[0]) return;
  const int y = canvas.height - kCaptionBandHeight;
  draw::fill_rect(canvas, 0, y, canvas.width, kCaptionBandHeight, draw::kBlack);
  draw::fill_rect(canvas, 0, y, canvas.width, 1, draw::kFaint);
  char shown[160];
  strlcpy(shown, line, sizeof(shown));
  while (shown[0] && draw::text_width(shown, 1) > canvas.width - 16) {
    shown[strlen(shown) - 1] = '\0';
  }
  const int text_y = y + (kCaptionBandHeight - draw::kGlyphHeight) / 2;
  draw::text_centered(canvas, canvas.width / 2, text_y, shown, draw::kWhite, 1);
}

}  // namespace gizmo
