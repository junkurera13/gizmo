#pragma once

#include <stdint.h>

// LiPo monitor through the external 2:1 divider on board::battery_adc.
// Samples are averaged slowly in the background; reads never block.
namespace gizmo {

class Battery {
 public:
  void begin();
  void update();  // call from loop()
  uint32_t millivolts() const { return filtered_mv_; }
  uint8_t percent() const;
  bool present() const { return present_; }  // false while the divider is unwired/floating

 private:
  static constexpr uint32_t kSamplePeriodMs = 250;
  static constexpr uint32_t kMaxSpreadMv = 120;
  uint32_t lastSample_ = 0;
  uint32_t filtered_mv_ = 0;
  bool primed_ = false;
  bool present_ = false;
};

}  // namespace gizmo
