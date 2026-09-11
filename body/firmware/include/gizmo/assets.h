#pragma once

#include <stddef.h>
#include <stdint.h>
#include "gizmo/assets_generated.h"
#include "gizmo/draw.h"

// Access to the export_bundle.py output embedded in flash. Timing and layout
// constants come from the manifest via assets_generated.h.
namespace gizmo::assets {

using namespace generated;

enum class Heart : uint8_t { kEmpty, kHalf, kFull };

// Decode the boot frame for `slot` (0..kBootSlots-1) into the canvas.
bool decode_boot_slot(int slot, const draw::Canvas& canvas);
// Decode the home base (character on black) into the canvas.
bool decode_home_base(const draw::Canvas& canvas);
// Decode the idle animation frame for `slot` (0..kIdleSlots-1) into the canvas.
bool decode_idle_slot(int slot, const draw::Canvas& canvas);

// RGB565+A8 heart sprite, kHeartAssetSide square.
const uint8_t* heart(Heart state);
// L8 clock atlas, kClockAtlasWidth x kClockAtlasHeight.
const uint8_t* clock_atlas();
// Boot chime as 16 kHz mono PCM16.
const int16_t* chime();

}  // namespace gizmo::assets
