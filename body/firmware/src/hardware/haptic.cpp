#include "gizmo/haptic.h"
#include "gizmo/board.h"
#include <Arduino.h>

namespace gizmo {

void Haptic::begin() {
  // GPIO3 is a strapping pin; drive it LOW before anything else so the motor
  // does not buzz while the pin mode settles.
  digitalWrite(board::haptic, LOW);
  pinMode(board::haptic, OUTPUT);
  digitalWrite(board::haptic, LOW);
}

void Haptic::pulse(uint16_t ms) {
  if (ms == 0) return;
  active_ = true;
  off_at_ = millis() + ms;
  digitalWrite(board::haptic, HIGH);
}

void Haptic::update() {
  if (!active_) return;
  if (static_cast<int32_t>(millis() - off_at_) >= 0) {
    digitalWrite(board::haptic, LOW);
    active_ = false;
  }
}

}  // namespace gizmo
