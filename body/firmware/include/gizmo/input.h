#pragma once

#include <stdint.h>

// Physical controls. PTT is a plain active-LOW GPIO. UP/DOWN/SELECT share one
// ADC resistor ladder (see board.h). Everything is polled from loop() with
// millis()-based debouncing; nothing blocks and no interrupts are used.
namespace gizmo {

enum class Button : uint8_t { kNone = 0, kUp, kDown, kSelect, kPtt, kCount };

struct InputEvent {
  Button button = Button::kNone;
  bool pressed = false;  // true on press edge, false on release edge
  bool repeat = false;   // auto-repeat while UP/DOWN are held
};

class Input {
 public:
  void begin();
  // Poll once per loop. Returns true and fills `event` when an edge occurred.
  // Call repeatedly until it returns false to drain multiple edges.
  bool poll(InputEvent& event);
  bool held(Button button) const;
  // Raw ladder voltage from the last sample, for wiring diagnostics.
  uint32_t ladder_millivolts() const { return ladder_mv_; }
  Button ladder_button() const { return ladder_stable_; }

 private:
  Button decode_ladder(uint32_t millivolts) const;
  void sample();

  static constexpr uint32_t kSamplePeriodMs = 4;
  static constexpr uint32_t kDebounceMs = 30;
  static constexpr uint32_t kRepeatDelayMs = 450;
  static constexpr uint32_t kRepeatPeriodMs = 140;

  uint32_t lastSample_ = 0;
  uint32_t ladder_mv_ = 0;

  Button ladder_stable_ = Button::kNone;
  Button ladder_candidate_ = Button::kNone;
  uint32_t ladder_candidate_since_ = 0;
  uint32_t ladder_pressed_at_ = 0;
  uint32_t ladder_last_repeat_ = 0;

  bool ptt_stable_ = false;
  bool ptt_candidate_ = false;
  uint32_t ptt_candidate_since_ = 0;

  // Small queue so one poll cycle can report a release and a new press.
  InputEvent queue_[4];
  uint8_t queue_head_ = 0;
  uint8_t queue_count_ = 0;
  void push(Button button, bool pressed, bool repeat = false);
};

const char* button_name(Button button);

}  // namespace gizmo
