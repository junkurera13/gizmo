#pragma once

#include <stdint.h>

namespace gizmo {
// Condition 16 kHz PCM boundaries before interpolating onto the PWM clock.
// Only stream boundaries are faded; continuous PCM retains its full amplitude.
struct PwmAudio {
  static constexpr int kFadeSamples = 64;  // 4 ms at 16 kHz
  int16_t current = 0;
  int16_t previous = 0;
  int16_t fade_from = 0;
  int fade_left = 0;
  bool gap = true;

  // Called by the IRAM ISR: do not emit an out-of-line flash-resident call.
  __attribute__((always_inline)) constexpr int16_t midpoint(int16_t input, bool available) {
    previous = current;
    if (available) {
      if (gap) {
        fade_from = current;
        fade_left = kFadeSamples;
      }
      gap = false;
      current = static_cast<int16_t>(static_cast<int32_t>(input) +
          (static_cast<int32_t>(fade_from) - input) * fade_left / kFadeSamples);
      if (fade_left > 0) --fade_left;
    } else {
      if (!gap) {
        fade_from = current;
        fade_left = kFadeSamples;
      }
      gap = true;
      if (fade_left > 0) --fade_left;
      current = static_cast<int16_t>(static_cast<int32_t>(fade_from) * fade_left / kFadeSamples);
    }
    return static_cast<int16_t>((static_cast<int32_t>(previous) + current) / 2);
  }
};

// 64 input samples per 125 output ticks: exactly 16 kHz -> 31.25 kHz.
// A rational phase accumulator preserves pitch instead of treating the new
// interrupt rate as 32 kHz. No floating point or flash lookup tables in the ISR.
struct PwmClock {
  static constexpr uint32_t kOutputRate = 31250;
  uint32_t phase = 0;
  __attribute__((always_inline)) constexpr bool advance() {
    phase += 64;
    if (phase < 125) return false;
    phase -= 125;
    return true;
  }
  __attribute__((always_inline)) constexpr int16_t sample(int16_t previous, int16_t current) const {
    return static_cast<int16_t>((static_cast<int32_t>(previous) * (125 - static_cast<int32_t>(phase)) +
        static_cast<int32_t>(current) * static_cast<int32_t>(phase)) / 125);
  }
};

// Rounded 9-bit quantization without periodic error-feedback patterns.
// Exact digital silence always produces a constant half-duty carrier.
__attribute__((always_inline)) inline constexpr uint32_t pwm_duty(int16_t sample) {
  const uint32_t rounded = (static_cast<int32_t>(sample) + 32768 + 64) >> 7;
  return rounded > 511 ? 511 : rounded;
}
}  // namespace gizmo
