#include "gizmo/battery.h"
#include "gizmo/board.h"
#include <Arduino.h>

namespace gizmo {

void Battery::begin() {
  pinMode(board::battery_adc, INPUT);
  analogReadResolution(12);
  analogSetPinAttenuation(board::battery_adc, ADC_11db);
  lastSample_ = millis();
  update();
}

void Battery::update() {
  const uint32_t now = millis();
  if (primed_ && now - lastSample_ < kSamplePeriodMs) return;
  lastSample_ = now;
  uint32_t sum = 0;
  uint32_t low = 0xFFFFFFFF;
  uint32_t high = 0;
  for (int i = 0; i < 8; ++i) {
    const uint32_t sample = analogReadMilliVolts(board::battery_adc);
    sum += sample;
    if (sample < low) low = sample;
    if (sample > high) high = sample;
  }
  const uint32_t pin_mv = sum / 8;
  const uint32_t battery_mv = static_cast<uint32_t>(pin_mv * board::battery_divider);
  if (!primed_) {
    filtered_mv_ = battery_mv;
    primed_ = true;
  } else {
    // ~1/8 IIR: settles in a couple of seconds, ignores PTT/haptic sag.
    filtered_mv_ = (filtered_mv_ * 7 + battery_mv) / 8;
  }
  // A real divider is quiet and sits in the LiPo window. A floating pin
  // wanders and is noisy between consecutive samples.
  const bool quiet = high - low <= kMaxSpreadMv;
  const bool plausible = filtered_mv_ >= 3000 && filtered_mv_ <= 4500;
  present_ = quiet && plausible;
}

uint8_t Battery::percent() const {
  // Coarse LiPo curve; resting voltage only. 4.20V full, 3.30V empty.
  const int mv = static_cast<int>(filtered_mv_);
  if (mv >= 4150) return 100;
  if (mv >= 4000) return static_cast<uint8_t>(85 + (mv - 4000) * 15 / 150);
  if (mv >= 3850) return static_cast<uint8_t>(60 + (mv - 3850) * 25 / 150);
  if (mv >= 3700) return static_cast<uint8_t>(30 + (mv - 3700) * 30 / 150);
  if (mv >= 3550) return static_cast<uint8_t>(10 + (mv - 3550) * 20 / 150);
  if (mv >= 3300) return static_cast<uint8_t>((mv - 3300) * 10 / 250);
  return 0;
}

}  // namespace gizmo
