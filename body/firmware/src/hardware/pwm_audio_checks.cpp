#include "gizmo/pwm_audio.h"

// Compile-time regression checks run in the actual board build, including the
// PWM path that the I2S-only host mocks do not exercise.
namespace {
constexpr bool ordered_ramp() {
  gizmo::PwmAudio p;
  p.gap = false;
  return p.midpoint(1000, true) == 500 && p.current == 1000 &&
         p.midpoint(2000, true) == 1500 && p.current == 2000 &&
         p.midpoint(-2000, true) == 0 && p.current == -2000;
}
constexpr bool gap_fades(int16_t level) {
  gizmo::PwmAudio p;
  p.gap = false;
  p.current = level;
  for (int i = 0; i < gizmo::PwmAudio::kFadeSamples; ++i) {
    const int16_t before = p.current;
    p.midpoint(0, false);
    if (level > 0 && (p.current < 0 || p.current > before)) return false;
    if (level < 0 && (p.current > 0 || p.current < before)) return false;
  }
  if (p.current != 0) return false;
  for (int i = 0; i < 100; ++i)
    if (p.midpoint(0, false) != 0 || p.current != 0) return false;
  if (p.midpoint(level, true) != 0 || p.current != 0) return false;
  for (int i = 0; i < gizmo::PwmAudio::kFadeSamples; ++i) p.midpoint(level, true);
  return p.current == level;
}
constexpr bool short_gap_resume() {
  gizmo::PwmAudio p;
  p.gap = false;
  p.current = 20000;
  p.midpoint(0, false);
  const int16_t tail = p.current;
  return p.midpoint(-20000, true) == tail && p.current == tail;
}
static_assert(ordered_ramp(), "PWM midpoint must precede its endpoint");
static_assert(gap_fades(32767), "Positive full-scale gap must fade to exact silence");
static_assert(gap_fades(-32768), "Negative full-scale gap must fade without overflow");
static_assert(short_gap_resume(), "A resumed stream must start at the previous tail");
constexpr bool exact_rate() {
  gizmo::PwmClock clock;
  int consumed = 0;
  for (int i = 0; i < 125; ++i) {
    if (clock.advance()) ++consumed;
    if (clock.phase >= 125) return false;
    if (clock.sample(-32768, -32768) != -32768) return false;
    if (clock.sample(32767, 32767) != 32767) return false;
  }
  return consumed == 64 && clock.phase == 0;
}
constexpr bool resampled_ramp() {
  gizmo::PwmClock clock;
  int16_t previous = 0, current = 125;
  for (int tick = 1; tick <= 125; ++tick) {
    if (clock.advance()) { previous = current; current += 125; }
    if (clock.sample(previous, current) != tick * 64) return false;
  }
  return true;
}
constexpr bool quantizer_bounds() {
  uint32_t previous = 0;
  for (int32_t sample = -32768; sample <= 32767; ++sample) {
    const auto duty = gizmo::pwm_duty(static_cast<int16_t>(sample));
    if (duty > 1023 || duty < previous) return false;
    previous = duty;
  }
  return gizmo::pwm_duty(0) == 512 && gizmo::pwm_duty(-32768) == 0 &&
         gizmo::pwm_duty(32767) == 1023;
}
static_assert(exact_rate(), "PWM conversion must preserve the 16 kHz input rate");
static_assert(resampled_ramp(), "Fractional interpolation must preserve time order");
static_assert(quantizer_bounds(), "PWM duty must be monotonic, bounded, and silent at zero");
}  // namespace
