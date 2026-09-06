#include "gizmo/input.h"
#include "gizmo/board.h"
#include <Arduino.h>

namespace gizmo {
namespace {
// Ladder thresholds in millivolts. Nominal levels with a 10k pull-down:
// idle 0 mV, SELECT 1320 mV (15k), DOWN 2245 mV (4.7k), UP 3300 mV (direct;
// the 11 dB ADC range saturates near 3100 mV). Bands leave >=300 mV margin
// on every side, including 5% resistor tolerance.
constexpr uint32_t kIdleMax = 600;
constexpr uint32_t kSelectMin = 1000;
constexpr uint32_t kSelectMax = 1650;
constexpr uint32_t kDownMin = 1900;
constexpr uint32_t kDownMax = 2600;
constexpr uint32_t kUpMin = 2850;
}  // namespace

const char* button_name(Button button) {
  switch (button) {
    case Button::kUp: return "UP";
    case Button::kDown: return "DOWN";
    case Button::kSelect: return "SELECT";
    case Button::kPtt: return "PTT";
    default: return "NONE";
  }
}

void Input::begin() {
  pinMode(board::ptt, INPUT_PULLUP);
  // No internal pull: adc_gpio_init() disables it on every read anyway. The
  // external 10k pull-down defines idle, and a floating pin reads ~0V = idle.
  pinMode(board::buttons_adc, INPUT);
  analogReadResolution(12);
  analogSetPinAttenuation(board::buttons_adc, ADC_11db);
  lastSample_ = millis();
  ptt_stable_ = ptt_candidate_ = digitalRead(board::ptt) == LOW;
  ladder_mv_ = analogReadMilliVolts(board::buttons_adc);
  ladder_stable_ = ladder_candidate_ = decode_ladder(ladder_mv_);
}

Button Input::decode_ladder(uint32_t millivolts) const {
  if (millivolts <= kIdleMax) return Button::kNone;
  if (millivolts >= kUpMin) return Button::kUp;
  if (millivolts >= kDownMin && millivolts <= kDownMax) return Button::kDown;
  if (millivolts >= kSelectMin && millivolts <= kSelectMax) return Button::kSelect;
  return Button::kNone;  // between bands: RC still settling (~1 ms) or a wiring fault
}

void Input::push(Button button, bool pressed, bool repeat) {
  if (queue_count_ >= 4) return;  // drop rather than block
  const uint8_t slot = static_cast<uint8_t>((queue_head_ + queue_count_) % 4);
  queue_[slot].button = button;
  queue_[slot].pressed = pressed;
  queue_[slot].repeat = repeat;
  ++queue_count_;
}

void Input::sample() {
  const uint32_t now = millis();

  // PTT: plain GPIO, active-LOW.
  const bool pttRaw = digitalRead(board::ptt) == LOW;
  if (pttRaw != ptt_candidate_) {
    ptt_candidate_ = pttRaw;
    ptt_candidate_since_ = now;
  } else if (pttRaw != ptt_stable_ && now - ptt_candidate_since_ >= kDebounceMs) {
    ptt_stable_ = pttRaw;
    push(Button::kPtt, ptt_stable_);
  }

  // Ladder: decode, then require the decoded button to hold steady. A press
  // passes through intermediate voltages while the 100nF settles, so a
  // change of candidate restarts the debounce window.
  ladder_mv_ = analogReadMilliVolts(board::buttons_adc);
  const Button decoded = decode_ladder(ladder_mv_);
  if (decoded != ladder_candidate_) {
    ladder_candidate_ = decoded;
    ladder_candidate_since_ = now;
  } else if (decoded != ladder_stable_ && now - ladder_candidate_since_ >= kDebounceMs) {
    if (ladder_stable_ != Button::kNone) push(ladder_stable_, false);
    ladder_stable_ = decoded;
    if (ladder_stable_ != Button::kNone) {
      push(ladder_stable_, true);
      ladder_pressed_at_ = now;
      ladder_last_repeat_ = now;
    }
  }

  if (ladder_stable_ == Button::kUp || ladder_stable_ == Button::kDown) {
    if (now - ladder_pressed_at_ >= kRepeatDelayMs && now - ladder_last_repeat_ >= kRepeatPeriodMs) {
      ladder_last_repeat_ = now;
      push(ladder_stable_, true, true);
    }
  }
}

bool Input::poll(InputEvent& event) {
  const uint32_t now = millis();
  if (now - lastSample_ >= kSamplePeriodMs) {
    lastSample_ = now;
    sample();
  }
  if (queue_count_ == 0) return false;
  event = queue_[queue_head_];
  queue_head_ = static_cast<uint8_t>((queue_head_ + 1) % 4);
  --queue_count_;
  return true;
}

bool Input::held(Button button) const {
  if (button == Button::kPtt) return ptt_stable_;
  return button != Button::kNone && ladder_stable_ == button;
}

}  // namespace gizmo
