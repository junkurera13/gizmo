#pragma once

#include <stdint.h>

// Coin ERM motor via NPN low-side switch. pulse() returns immediately; the
// motor is switched off from update() once the requested time has elapsed.
namespace gizmo {

class Haptic {
 public:
  void begin();
  void pulse(uint16_t ms);  // a new pulse extends/replaces the current one
  void update();            // call from loop()
  bool active() const { return active_; }

 private:
  bool active_ = false;
  uint32_t off_at_ = 0;
};

}  // namespace gizmo
