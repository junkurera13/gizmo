#pragma once

#include <stddef.h>
#include <stdint.h>

// Authenticated body → Friend WebSocket (`/ws`, protocol v1).
// Happy path this slice: /health version check, connect with Bearer + device
// headers, hello, PTT audio up at 24 kHz, inbound PCM play-down.
// Not in this slice: glass/show fetch, Friend-owned Settings, navigate/select
// forwarding, power events, vision `frame`, wake-audio reconnect buffer.
namespace gizmo {

enum class FriendPhase : uint8_t {
  kOff = 0,
  kNeedConfig,
  kHealth,
  kConnecting,
  kOnline,
  kBackoff,
};

class FriendLink {
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
  void forget();  // clear URL + token; device id stays

  bool send_ptt(bool active);
  // Sense mic is 16 kHz; resampled to 24 kHz mono PCM16 on the wire.
  bool send_pcm16k(const int16_t* samples, size_t count);
  bool send_select();

  size_t take_speaker(int16_t* dest, size_t cap);
  void interrupt_speaker();
  bool speaker_pending() const { return speaker_n_ > 0; }

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
  void enqueue_speaker(const int16_t* samples, size_t count);

  FriendPhase phase_ = FriendPhase::kOff;
  uint32_t backoff_until_ = 0;
  uint32_t backoff_ms_ = 250;
  uint32_t last_try_ = 0;
  bool hello_ok_ = false;
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

  static constexpr size_t kSpeakerCap = 24000 * 3 / 4;
  int16_t* speaker_ = nullptr;
  size_t speaker_cap_ = 0;
  size_t speaker_w_ = 0;
  size_t speaker_r_ = 0;
  size_t speaker_n_ = 0;
};

const char* friend_phase_name(FriendPhase phase);

}  // namespace gizmo
