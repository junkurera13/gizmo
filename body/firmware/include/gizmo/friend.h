#pragma once
#include <stddef.h>
#include <stdint.h>
#include <atomic>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include "gizmo/friend_phase.h"

namespace gizmo {
// Main-loop facade. The network task exclusively owns HTTP, TLS and WebSocket
// objects. Every crossing is a bounded queue with zero wait on the body loop.
class FriendLink {
 public:
  static constexpr uint32_t kWireSampleRate = 24000;
  static constexpr uint8_t kProtocolVersion = 1;
  void begin();
  void update(bool wifi_online);
  bool ready() const { return status_.phase == FriendPhase::kOnline; }
  FriendPhase phase() const { return status_.phase; }
  const char* detail() const { return status_.detail; }
  const char* brain_url() const { return status_.url; }
  const char* device_id() const { return status_.device; }
  bool has_token() const { return status_.token; }
  bool hello_ok() const { return status_.hello; }
  bool set_url(const char* url);
  bool set_token(const char* token);
  void forget();
  bool send_ptt(bool active);
  bool send_select();
  bool send_pcm16k(const int16_t* samples, size_t count);
  bool send_jpeg(const uint8_t* jpeg, size_t length);
  size_t take_speaker(int16_t* dest, size_t cap);
  void interrupt_speaker();
  bool take_barge_in();

 private:
  enum class Kind : uint8_t { kUrl, kToken, kForget, kPttDown, kPttUp, kPcm, kSelect, kInterrupt };
  struct Command {
    Kind kind;
    uint32_t generation = 0;
    size_t count = 0;
    union { char text[160]; int16_t pcm[256]; } data;
  };
  struct Speaker { uint32_t generation; size_t count; int16_t pcm[256]; };
  struct Status {
    FriendPhase phase = FriendPhase::kOff;
    uint32_t generation = 0;
    uint32_t interrupt = 0;
    bool token = false;
    bool hello = false;
    char detail[56] = "NETWORK STARTING";
    char url[160] = "";
    char device[32] = "";
  };
  bool queue(Kind kind);
  bool configure(Kind kind, const char* value);
  static void task(void* context);
  void run();
  QueueHandle_t commands_ = nullptr;
  QueueHandle_t speaker_ = nullptr;
  QueueHandle_t statuses_ = nullptr;
  std::atomic<bool> wifi_online_{false};
  std::atomic<bool> overflow_{false};
  static constexpr size_t kJpegMax = 48 * 1024;
  uint8_t* jpeg_slot_[2] = {};
  size_t jpeg_len_[2] = {};
  std::atomic<int> jpeg_published_{-1};
  std::atomic<int> jpeg_sending_{-1};
  std::atomic<uint32_t> jpeg_generation_{0};
  uint32_t jpeg_seen_ = 0;
  Status status_;
  uint32_t seen_interrupt_ = 0;
  Speaker pending_{};
  size_t pending_read_ = 0;
};
}
