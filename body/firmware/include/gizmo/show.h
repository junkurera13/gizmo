#pragma once
#include <atomic>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include "gizmo/show_format.h"

namespace gizmo {
// Body loop owns playback and the display. A separate, low-priority task owns
// media HTTP/TLS, so slow cache creation/download never stalls voice sockets.
//
// Two slots: the picture on the glass, and one held picture for a story cue
// that is fetched and indexed ahead of its words. "go" swaps the held slot in
// without a download in between, so the change lands on the sentence.
class ShowPlayer {
 public:
  void begin();
  void submit(const ShowRequest& request);
  void cancel(bool dismiss = true);
  void update();
  bool viewing() const { return request_.viewing; }
  bool available() const { return still_.bytes != nullptr; }
  bool render(uint16_t* pixels, bool force = false);
  bool take_glass_ready(GlassReady& ack);
  void diagnose() const;
 private:
  struct Job { ShowRequest request; uint32_t revision; bool still; bool held; };
  struct Media {
    uint8_t* bytes = nullptr;
    size_t length = 0, count = 0;
    ShowFrame frames[kShowMaxFrames];
    uint32_t revision = 0;
    uint32_t cue = 0;
    bool motion = false;
    bool held = false;
    bool failed = false;
  };
  static void task(void* context);
  void run();
  bool download(const Job& job, bool motion, Media& media);
  void publish(Media& media);
  void release(Media& media);
  void hold(const ShowRequest& request);
  bool swap_held(const ShowRequest& request);
  void drop_held();
  void ack(uint32_t cue, bool motion, bool ok);
  QueueHandle_t jobs_ = nullptr, held_jobs_ = nullptr, results_ = nullptr;
  std::atomic<uint32_t> revision_{0};
  std::atomic<uint32_t> held_revision_{0};
  ShowRequest request_;
  ShowRequest held_request_;
  char dismissed_[128] = "";
  Media still_, clip_;
  Media held_still_, held_clip_;
  static constexpr size_t kAckCap = 8;
  GlassReady acks_[kAckCap];
  size_t ack_r_ = 0, ack_w_ = 0;
  uint32_t started_ = 0;
  int drawn_ = -1;
  bool changed_ = false;
};
}
