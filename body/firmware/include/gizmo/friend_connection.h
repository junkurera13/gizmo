#pragma once

#include <stddef.h>
#include <stdint.h>

// Network-task-only connection. Never access this object from the body loop.
#include "gizmo/friend_phase.h"
#include "gizmo/show_format.h"

namespace gizmo {

class FriendConnection {
 public:
  static constexpr uint32_t kWireSampleRate = 24000;
  static constexpr uint8_t kProtocolVersion = 1;

  void begin();
  void update(bool wifi_online);
  bool ready() const { return phase_ == FriendPhase::kOnline; }
  FriendPhase phase() const { return phase_; }
  const char* detail() const { return detail_; }
  const char* brain_url() const { return url_; }
  const char* device_id() const { return device_id_; }
  bool has_token() const { return token_[0] != '\0'; }
  bool hello_ok() const { return hello_ok_; }

  bool set_url(const char* url);
  bool set_token(const char* token);
  void abort() { disconnect(); schedule_backoff(); }
  void forget();  // clear URL + token; device id stays

  bool send_ptt(bool active);
  // Sense mic is 16 kHz; resampled to 24 kHz mono PCM16 on the wire.
  // Odd leftover samples are held until the next chunk or PTT-up flush.
  bool send_pcm16k(const int16_t* samples, size_t count);
  bool send_select();
  // Latest camera JPEG. Brain limit is 128 KiB; the WS frame budget is smaller.
  bool send_frame(const uint8_t* jpeg, size_t length);

  size_t take_speaker(int16_t* dest, size_t cap);
  void interrupt_speaker();
  bool speaker_pending() const { return speaker_n_ > 0; }
  bool take_barge_in();
  bool take_show(ShowRequest& request);

  void on_socket_event(int type, uint8_t* payload, size_t length);

 private:
  void load();
  void save_credentials();
  void disconnect();
  void schedule_backoff();
  bool inspect_health();
  bool open_socket();
  void on_message(const char* json, size_t len);
  bool send_json(const char* json);
  bool parse_url();
  void build_headers();
  void accept_session_state(const char* state);
  bool enqueue_speaker(const int16_t* samples, size_t count);
  bool can_receive() const;

  FriendPhase phase_ = FriendPhase::kOff;
  uint32_t backoff_until_ = 0;
  uint32_t backoff_ms_ = 250;
  uint32_t last_try_ = 0;
  bool hello_ok_ = false;
  bool session_ready_ = false;
  bool glass_seen_ = false;
  bool tls_ = false;
  uint16_t port_ = 80;
  char url_[160] = "";
  char token_[96] = "";
  char device_id_[32] = "";
  char host_[80] = "";
  char path_prefix_[40] = "";
  char ws_path_[48] = "/ws";
  char detail_[56] = "";
  char extra_headers_[280] = "";

  static constexpr size_t kSpeakerCap = 16000 * 3;  // 16 kHz after 24→16
  // Reserve enough room for an entire maximum-size JSON/base64 WS frame,
  // including the resampler's two carried input samples. No audio is dropped
  // to catch up with a provider generating faster than real time.
  static constexpr size_t kMaxMessageBytes = 98304;
  static constexpr size_t kMaxFrameSamples = ((kMaxMessageBytes * 3 / 4 / 2 + 2) / 3) * 2;
  static_assert(kSpeakerCap >= kMaxFrameSamples, "speaker ring must fit a full WS frame");
  int16_t* speaker_ = nullptr;
  size_t speaker_cap_ = 0;
  size_t speaker_w_ = 0;
  size_t speaker_r_ = 0;
  size_t speaker_n_ = 0;
  int16_t up_hold_ = 0;
  bool up_hold_valid_ = false;
  int16_t down_hold_[2] = {};
  uint8_t down_n_ = 0;
  bool barge_in_ = false;
  ShowRequest show_;
  bool show_changed_ = false;
};

const char* friend_phase_name(FriendPhase phase);

}  // namespace gizmo
