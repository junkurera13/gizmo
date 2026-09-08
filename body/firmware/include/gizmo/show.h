#pragma once
#include <atomic>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include "gizmo/show_format.h"

namespace gizmo {
// Body loop owns playback and the display. A separate, low-priority task owns
// media HTTP/TLS, so slow cache creation/download never stalls voice sockets.
class ShowPlayer {
 public:
  void begin();
  void submit(const ShowRequest& request);
  void cancel(bool dismiss = true);
  void update();
  bool viewing() const { return request_.viewing; }
  bool available() const { return still_.bytes != nullptr; }
  bool render(uint16_t* pixels, bool force = false);
  void diagnose() const;
 private:
  struct Job { ShowRequest request; uint32_t revision; bool still; };
  struct Media {
    uint8_t* bytes = nullptr;
    size_t length = 0, count = 0;
    ShowFrame frames[kShowMaxFrames];
    uint32_t revision = 0;
    bool motion = false;
  };
  static void task(void* context);
  void run();
  bool download(const Job& job, bool motion, Media& media);
  void publish(Media& media);
  void release(Media& media);
  QueueHandle_t jobs_ = nullptr, results_ = nullptr;
  std::atomic<uint32_t> revision_{0};
  ShowRequest request_;
  char dismissed_[128] = "";
  Media still_, clip_;
  uint32_t started_ = 0;
  int drawn_ = -1;
  bool changed_ = false;
};
}
