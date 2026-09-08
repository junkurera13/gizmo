#include "gizmo/friend_connection.h"

#include <Arduino.h>
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <Preferences.h>
#include <WebSocketsClient.h>
#include <WiFi.h>
#include <WiFiClient.h>
#include <WiFiClientSecure.h>
#include <esp_heap_caps.h>
#include <mbedtls/base64.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include "gizmo/trust_roots.h"

#ifndef GIZMO_BRAIN_URL
#define GIZMO_BRAIN_URL ""
#endif
#ifndef GIZMO_DEVICE_TOKEN
#define GIZMO_DEVICE_TOKEN ""
#endif

namespace gizmo {
namespace {

WebSocketsClient ws;
FriendConnection* g_link = nullptr;
bool ws_used_ = false;

bool is_host_char(char c) {
  return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '.' ||
         c == '-' || c == '_';
}

bool is_local_host(const char* host) {
  return strcmp(host, "127.0.0.1") == 0 || strcmp(host, "localhost") == 0 ||
         strcmp(host, "::1") == 0;
}

size_t resample_16k_to_24k(const int16_t* in, size_t in_n, int16_t* out, size_t out_cap) {
  if (in == nullptr || out == nullptr || in_n == 0 || out_cap == 0) return 0;
  size_t out_n = in_n * 3 / 2;
  if (out_n > out_cap) out_n = out_cap;
  for (size_t i = 0; i < out_n; ++i) {
    const size_t pos_x2 = i * 2;
    const size_t idx = pos_x2 / 3;
    const size_t frac = pos_x2 % 3;
    const int16_t a = in[idx < in_n ? idx : in_n - 1];
    const int16_t b = in[(idx + 1) < in_n ? (idx + 1) : in_n - 1];
    const int32_t v =
        (static_cast<int32_t>(a) * static_cast<int32_t>(3 - frac) + static_cast<int32_t>(b) * static_cast<int32_t>(frac)) /
        3;
    out[i] = static_cast<int16_t>(v);
  }
  return out_n;
}

// 3 wire samples at 24 kHz → 2 device samples at 16 kHz. Caller holds leftovers.
const char* skip_json_ws(const char* p, const char* end) {
  while (p < end && (*p == ' ' || *p == '\n' || *p == '\r' || *p == '\t')) ++p;
  return p;
}

bool json_string_field(const char* json, size_t len, const char* key, const char** out, size_t* out_len) {
  if (json == nullptr || key == nullptr || out == nullptr || out_len == nullptr) return false;
  const char* end = json + len;
  const size_t klen = strlen(key);
  for (const char* p = json; p + klen + 3 < end; ++p) {
    if (*p != '"') continue;
    if (memcmp(p + 1, key, klen) != 0 || p[1 + klen] != '"') continue;
    const char* q = skip_json_ws(p + 2 + klen, end);
    if (q >= end || *q != ':') continue;
    q = skip_json_ws(q + 1, end);
    if (q >= end || *q != '"') continue;
    const char* start = q + 1;
    const char* r = start;
    while (r < end && *r != '"') {
      if (*r == '\\' && r + 1 < end) r += 2;
      else ++r;
    }
    if (r >= end) return false;
    *out = start;
    *out_len = static_cast<size_t>(r - start);
    return true;
  }
  return false;
}

size_t resample_24k_to_16k(const int16_t* in, size_t in_n, int16_t* out, size_t out_cap) {
  if (in == nullptr || out == nullptr || in_n < 3 || out_cap < 2) return 0;
  const size_t groups = in_n / 3;
  const size_t max_groups = out_cap / 2;
  const size_t use = groups < max_groups ? groups : max_groups;
  size_t out_n = 0;
  for (size_t g = 0; g < use; ++g) {
    const int16_t a = in[g * 3];
    const int16_t b = in[g * 3 + 1];
    const int16_t c = in[g * 3 + 2];
    out[out_n++] = a;
    const int32_t mid = (static_cast<int32_t>(b) + static_cast<int32_t>(c)) / 2;
    out[out_n++] = static_cast<int16_t>(mid);
  }
  return out_n;
}

void socket_event(WStype_t type, uint8_t* payload, size_t length) {
  if (g_link == nullptr) return;
  g_link->on_socket_event(static_cast<int>(type), payload, length);
}

}  // namespace

const char* friend_phase_name(FriendPhase phase) {
  switch (phase) {
    case FriendPhase::kNeedConfig: return "need_config";
    case FriendPhase::kHealth: return "health";
    case FriendPhase::kConnecting: return "connecting";
    case FriendPhase::kOnline: return "online";
    case FriendPhase::kBackoff: return "backoff";
    default: return "off";
  }
}

void FriendConnection::begin() {
  g_link = this;
  speaker_cap_ = kSpeakerCap;
  speaker_ = static_cast<int16_t*>(
      heap_caps_malloc(speaker_cap_ * sizeof(int16_t), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  if (speaker_ == nullptr) {
    speaker_ = static_cast<int16_t*>(heap_caps_malloc(speaker_cap_ * sizeof(int16_t), MALLOC_CAP_8BIT));
  }
  load();
  if (url_[0] == '\0') {
    phase_ = FriendPhase::kNeedConfig;
    strncpy(detail_, "SET BRAIN URL (serial F)", sizeof(detail_) - 1);
  } else {
    phase_ = FriendPhase::kOff;
    strncpy(detail_, "WAITING FOR WIFI", sizeof(detail_) - 1);
  }
  detail_[sizeof(detail_) - 1] = '\0';
  Serial.printf("friend begin: device=%s url=%s token=%s\n", device_id_, url_[0] ? url_ : "(none)",
                token_[0] ? "set" : "empty");
}

void FriendConnection::load() {
  Preferences prefs;
  prefs.begin("gizmo", true);
  if (prefs.getString("device_id", device_id_, sizeof(device_id_)) == 0 || device_id_[0] == '\0') {
    uint8_t mac[6] = {};
    WiFi.macAddress(mac);
    snprintf(device_id_, sizeof(device_id_), "gizmo-%02x%02x%02x%02x%02x%02x", mac[0], mac[1], mac[2],
             mac[3], mac[4], mac[5]);
    prefs.end();
    prefs.begin("gizmo", false);
    prefs.putString("device_id", device_id_);
  }
  prefs.getString("brain_url", url_, sizeof(url_));
  prefs.getString("brain_token", token_, sizeof(token_));
  prefs.end();
  if (url_[0] == '\0' && GIZMO_BRAIN_URL[0] != '\0') {
    strncpy(url_, GIZMO_BRAIN_URL, sizeof(url_) - 1);
    url_[sizeof(url_) - 1] = '\0';
  }
  if (token_[0] == '\0' && GIZMO_DEVICE_TOKEN[0] != '\0') {
    strncpy(token_, GIZMO_DEVICE_TOKEN, sizeof(token_) - 1);
    token_[sizeof(token_) - 1] = '\0';
  }
}

void FriendConnection::save_credentials() {
  Preferences prefs;
  prefs.begin("gizmo", false);
  prefs.putString("brain_url", url_);
  prefs.putString("brain_token", token_);
  prefs.putString("device_id", device_id_);
  prefs.end();
}

bool FriendConnection::parse_url() {
  tls_ = false;
  port_ = 80;
  host_[0] = '\0';
  path_prefix_[0] = '\0';
  const char* u = url_;
  if (strncmp(u, "https://", 8) == 0) {
    tls_ = true;
    port_ = 443;
    u += 8;
  } else if (strncmp(u, "http://", 7) == 0) {
    tls_ = false;
    port_ = 80;
    u += 7;
  } else {
    return false;
  }
  if (strchr(u, '@') != nullptr) return false;
  const char* slash = strchr(u, '/');
  const char* colon = strchr(u, ':');
  size_t host_len = 0;
  if (colon != nullptr && (slash == nullptr || colon < slash)) {
    host_len = static_cast<size_t>(colon - u);
    const int parsed = atoi(colon + 1);
    if (parsed <= 0 || parsed > 65535) return false;
    port_ = static_cast<uint16_t>(parsed);
  } else {
    host_len = slash != nullptr ? static_cast<size_t>(slash - u) : strlen(u);
  }
  if (host_len == 0 || host_len >= sizeof(host_)) return false;
  memcpy(host_, u, host_len);
  host_[host_len] = '\0';
  for (size_t i = 0; host_[i]; ++i) {
    if (!is_host_char(host_[i]) && host_[i] != ':') return false;
  }
  if (slash != nullptr) {
    strncpy(path_prefix_, slash, sizeof(path_prefix_) - 1);
    path_prefix_[sizeof(path_prefix_) - 1] = '\0';
    size_t n = strlen(path_prefix_);
    while (n > 1 && path_prefix_[n - 1] == '/') path_prefix_[--n] = '\0';
  }
  if (path_prefix_[0] && strcmp(path_prefix_, "/") != 0) {
    snprintf(ws_path_, sizeof(ws_path_), "%s/ws", path_prefix_);
  } else {
    strncpy(ws_path_, "/ws", sizeof(ws_path_) - 1);
  }
  return host_[0] != '\0';
}

void FriendConnection::build_headers() {
  extra_headers_[0] = '\0';
  char* p = extra_headers_;
  size_t left = sizeof(extra_headers_);
  int n = snprintf(p, left, "X-Gizmo-Device: %s\r\nX-Gizmo-Protocol: %u", device_id_,
                   static_cast<unsigned>(kProtocolVersion));
  if (n < 0 || static_cast<size_t>(n) >= left) {
    extra_headers_[0] = '\0';
    return;
  }
  p += n;
  left -= static_cast<size_t>(n);
  if (token_[0]) {
    n = snprintf(p, left, "\r\nAuthorization: Bearer %s", token_);
    if (n < 0 || static_cast<size_t>(n) >= left) extra_headers_[0] = '\0';
  }
}

bool FriendConnection::set_url(const char* url) {
  if (url == nullptr || url[0] == '\0' || strlen(url) >= sizeof(url_)) {
    Serial.println("friend: url must be http(s)://host 1–159 chars");
    return false;
  }
  char previous[sizeof(url_)];
  strncpy(previous, url_, sizeof(previous));
  strncpy(url_, url, sizeof(url_) - 1);
  url_[sizeof(url_) - 1] = '\0';
  if (!parse_url()) {
    strncpy(url_, previous, sizeof(url_));
    Serial.println("friend: url rejected (need http(s)://host, no credentials)");
    return false;
  }
  save_credentials();
  disconnect();
  backoff_ms_ = 250;
  backoff_until_ = 0;
  phase_ = FriendPhase::kOff;
  strncpy(detail_, "URL SAVED", sizeof(detail_) - 1);
  Serial.printf("friend: brain url %s host=%s port=%u tls=%d path=%s\n", url_, host_, port_, tls_,
                ws_path_);
  return true;
}

bool FriendConnection::set_token(const char* token) {
  if (token == nullptr) token = "";
  if (strlen(token) >= sizeof(token_)) {
    Serial.println("friend: token too long");
    return false;
  }
  for (size_t i = 0; token[i]; ++i) {
    const unsigned char c = static_cast<unsigned char>(token[i]);
    if (c < 32 || c > 126) {
      Serial.println("friend: token must be printable ASCII");
      return false;
    }
  }
  strncpy(token_, token, sizeof(token_) - 1);
  token_[sizeof(token_) - 1] = '\0';
  save_credentials();
  disconnect();
  backoff_ms_ = 250;
  backoff_until_ = 0;
  phase_ = FriendPhase::kOff;
  Serial.printf("friend: token %s\n", token_[0] ? "saved" : "cleared");
  return true;
}

void FriendConnection::forget() {
  url_[0] = '\0';
  token_[0] = '\0';
  save_credentials();
  disconnect();
  phase_ = FriendPhase::kNeedConfig;
  strncpy(detail_, "SET BRAIN URL (serial F)", sizeof(detail_) - 1);
  Serial.println("friend: url and token cleared");
}

void FriendConnection::disconnect() {
  hello_ok_ = false;
  session_ready_ = false;
  glass_seen_ = false;
  speaker_n_ = speaker_r_ = speaker_w_ = 0;
  down_n_ = 0;
  up_hold_valid_ = false;
  barge_in_ = true;
  if (ws_used_) {
    ws.disconnect();
  }
  if (phase_ == FriendPhase::kOnline || phase_ == FriendPhase::kConnecting) {
    phase_ = FriendPhase::kOff;
  }
}

void FriendConnection::schedule_backoff() {
  hello_ok_ = false;
  session_ready_ = false;
  glass_seen_ = false;
  phase_ = FriendPhase::kBackoff;
  backoff_until_ = millis() + backoff_ms_;
  snprintf(detail_, sizeof(detail_), "RETRY IN %ums", static_cast<unsigned>(backoff_ms_));
  backoff_ms_ = backoff_ms_ * 2;
  if (backoff_ms_ > 4000) backoff_ms_ = 4000;
}

bool FriendConnection::inspect_health() {
  if (!parse_url()) {
    strncpy(detail_, "BAD BRAIN URL", sizeof(detail_) - 1);
    phase_ = FriendPhase::kNeedConfig;
    return false;
  }
  if (tls_ && !is_local_host(host_) && token_[0] == '\0') {
    strncpy(detail_, "NEED DEVICE TOKEN (K)", sizeof(detail_) - 1);
    phase_ = FriendPhase::kNeedConfig;
    return false;
  }
  if (tls_ && time(nullptr) < 1735689600) {
    strncpy(detail_, "WAITING FOR NETWORK TIME", sizeof(detail_) - 1);
    return false;
  }
  char health_url[192];
  snprintf(health_url, sizeof(health_url), "%s://%s:%u%s/health", tls_ ? "https" : "http", host_,
           port_, (path_prefix_[0] && strcmp(path_prefix_, "/") != 0) ? path_prefix_ : "");
  strncpy(detail_, "GET /health", sizeof(detail_) - 1);
  Serial.printf("friend health: %s\n", health_url);

  HTTPClient http;
  http.setTimeout(2500);
  http.setConnectTimeout(2500);
  bool begun = false;
  WiFiClientSecure tls_client;
  WiFiClient plain;
  if (tls_) {
    tls_client.setCACert(kFriendRootCAs);
    begun = http.begin(tls_client, health_url);
  } else {
    begun = http.begin(plain, health_url);
  }
  if (!begun) {
    strncpy(detail_, "HEALTH BEGIN FAIL", sizeof(detail_) - 1);
    return false;
  }
  const int code = http.GET();
  String body;
  if (code > 0) body = http.getString();
  http.end();
  if (code != 200) {
    snprintf(detail_, sizeof(detail_), "HEALTH HTTP %d", code);
    Serial.printf("friend health: HTTP %d\n", code);
    return false;
  }
  StaticJsonDocument<128> filter;
  filter["body_protocol"]["version"] = true;
  StaticJsonDocument<256> health;
  const auto parsed = deserializeJson(health, body.c_str(), DeserializationOption::Filter(filter));
  const int version = parsed ? -1 : (health["body_protocol"]["version"] | -1);
  if (version != static_cast<int>(kProtocolVersion)) {
    snprintf(detail_, sizeof(detail_), "PROTOCOL %d != %u", version,
             static_cast<unsigned>(kProtocolVersion));
    Serial.printf("friend health: incompatible protocol %d\n", version);
    return false;
  }
  strncpy(detail_, "HEALTH OK", sizeof(detail_) - 1);
  return true;
}

bool FriendConnection::open_socket() {
  if (!parse_url()) return false;
  build_headers();
  if (ws_used_) ws.disconnect();
  ws.onEvent(socket_event);
  ws.setReconnectInterval(0);  // update() owns backoff; first attempt must be immediate
  ws.setExtraHeaders(extra_headers_);
  if (tls_) {
    ws.beginSslWithCA(host_, port_, ws_path_, kFriendRootCAs);
  } else {
    ws.begin(host_, port_, ws_path_);
  }
  ws_used_ = true;
  hello_ok_ = false;
  session_ready_ = false;
  glass_seen_ = false;
  phase_ = FriendPhase::kConnecting;
  last_try_ = millis();
  strncpy(detail_, "WS HANDSHAKE", sizeof(detail_) - 1);
  Serial.printf("friend ws: %s://%s:%u%s\n", tls_ ? "wss" : "ws", host_, port_, ws_path_);
  return true;
}

void FriendConnection::on_socket_event(int type, uint8_t* payload, size_t length) {
  switch (static_cast<WStype_t>(type)) {
    case WStype_DISCONNECTED:
      interrupt_speaker();
      Serial.println("friend ws: disconnected");
      if (phase_ == FriendPhase::kOnline || phase_ == FriendPhase::kConnecting) {
        strncpy(detail_, "WS DROPPED", sizeof(detail_) - 1);
        schedule_backoff();
      }
      hello_ok_ = false;
  session_ready_ = false;
      glass_seen_ = false;
      break;
    case WStype_CONNECTED:
      strncpy(detail_, "WS CONNECTED", sizeof(detail_) - 1);
      Serial.printf("friend ws: connected %s\n", payload ? reinterpret_cast<char*>(payload) : "");
      break;
    case WStype_TEXT:
      if (payload != nullptr && length > 0) {
        on_message(reinterpret_cast<const char*>(payload), length);
      }
      break;
    case WStype_ERROR:
      strncpy(detail_, "WS ERROR", sizeof(detail_) - 1);
      Serial.println("friend ws: error");
      break;
    default:
      break;
  }
}

void FriendConnection::enqueue_speaker(const int16_t* samples, size_t count) {
  if (speaker_ == nullptr || samples == nullptr || count == 0) return;
  size_t dropped = 0;
  auto push16 = [this, &dropped](int16_t sample) {
    if (speaker_n_ >= speaker_cap_) {
      ++dropped;
      return;
    }
    speaker_[speaker_w_] = sample;
    speaker_w_ = (speaker_w_ + 1) % speaker_cap_;
    ++speaker_n_;
  };
  // Play wire PCM as 16 kHz. Gemini Live native audio on this brain is 16 kHz
  // even though /health advertises 24 kHz; the old 24→16 decimate made speech
  // 1.5× fast (brief/garbled). Device I2S and local memos stay 16 kHz.
  if (down_n_ > 0) {
    for (uint8_t i = 0; i < down_n_; ++i) push16(down_hold_[i]);
    down_n_ = 0;
  }
  for (size_t i = 0; i < count; ++i) push16(samples[i]);
  if (dropped) Serial.printf("friend speaker: dropped %u samples (ring full)\n", static_cast<unsigned>(dropped));
}

size_t FriendConnection::take_speaker(int16_t* dest, size_t cap) {
  if (dest == nullptr || cap == 0 || speaker_n_ == 0) return 0;
  const size_t take = speaker_n_ < cap ? speaker_n_ : cap;
  for (size_t i = 0; i < take; ++i) {
    dest[i] = speaker_[speaker_r_];
    speaker_r_ = (speaker_r_ + 1) % speaker_cap_;
  }
  speaker_n_ -= take;
  return take;
}

void FriendConnection::interrupt_speaker() {
  speaker_n_ = speaker_r_ = speaker_w_ = 0;
  down_n_ = 0;
  barge_in_ = true;
}

bool FriendConnection::take_barge_in() {
  if (!barge_in_) return false;
  barge_in_ = false;
  return true;
}

void FriendConnection::accept_session_state(const char* state) {
  Serial.printf("friend state: %s\n", state);
  if (strcmp(state, "booting") == 0) last_try_ = millis();
  session_ready_ = strcmp(state, "listening") == 0 || strcmp(state, "talking") == 0 ||
                   strcmp(state, "thinking") == 0 || strcmp(state, "asleep") == 0;
  if (strcmp(state, "powered_off") == 0) {
    // A new device identity starts powered off. Never cold-boot an already
    // powered session just because the Wi-Fi socket reconnected.
    send_json("{\"type\":\"power\",\"on\":true}");
  }
  if (!session_ready_) {
    phase_ = FriendPhase::kConnecting;
    strncpy(detail_, "WAITING FOR BRAIN BOOT", sizeof(detail_) - 1);
  } else if (hello_ok_ && glass_seen_) {
    phase_ = FriendPhase::kOnline;
    strncpy(detail_, "ONLINE", sizeof(detail_) - 1);
  }
}

void FriendConnection::on_message(const char* json, size_t len) {
  if (len > 98304) {
    Serial.printf("friend: ws message %u dropped (too large)\n", static_cast<unsigned>(len));
    return;
  }
  const char* type = nullptr;
  size_t type_len = 0;
  if (json_string_field(json, len, "type", &type, &type_len) && type_len == 5 && memcmp(type, "audio", 5) == 0) {
    const char* b64 = nullptr;
    size_t b64_len = 0;
    if (!json_string_field(json, len, "pcm", &b64, &b64_len) || b64_len == 0) return;
    size_t decoded_len = 0;
    const size_t bound = (b64_len * 3) / 4 + 4;
    uint8_t* decoded = static_cast<uint8_t*>(
        heap_caps_malloc(bound, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    if (decoded == nullptr) decoded = static_cast<uint8_t*>(heap_caps_malloc(bound, MALLOC_CAP_8BIT));
    if (decoded == nullptr) {
      Serial.println("friend speaker: decode alloc failed");
      return;
    }
    const int rc =
        mbedtls_base64_decode(decoded, bound, &decoded_len, reinterpret_cast<const unsigned char*>(b64), b64_len);
    if (rc == 0 && decoded_len >= 2 && (decoded_len % 2) == 0) {
      if (speaker_n_ == 0) {
        Serial.printf("friend speaker: start %u pcm bytes\n", static_cast<unsigned>(decoded_len));
      }
      enqueue_speaker(reinterpret_cast<const int16_t*>(decoded), decoded_len / 2);
    }
    free(decoded);
    return;
  }

  StaticJsonDocument<192> filter;
  for (const char* key : {"type", "state", "protocol_version"}) filter[key] = true;
  DynamicJsonDocument document(len > 2048 ? 2048 : len + 512);
  if (deserializeJson(document, json, len, DeserializationOption::Filter(filter))) return;
  type = document["type"] | "";

  if (strcmp(type, "hello") == 0) {
    const int version = document["protocol_version"] | -1;
    if (version != static_cast<int>(kProtocolVersion)) {
      Serial.printf("friend hello: protocol %d rejected\n", version);
      strncpy(detail_, "HELLO PROTOCOL", sizeof(detail_) - 1);
      disconnect();
      schedule_backoff();
      return;
    }
    hello_ok_ = true;
    const char* state = document["state"];
    if (state == nullptr) {
      disconnect();
      schedule_backoff();
      return;
    }
    accept_session_state(state);
    backoff_ms_ = 250;
    strncpy(detail_, "HELLO", sizeof(detail_) - 1);
    Serial.println("friend hello: protocol 1");
    return;
  }

  if (strcmp(type, "glass") == 0) {
    glass_seen_ = true;
    if (hello_ok_ && session_ready_) {
      phase_ = FriendPhase::kOnline;
      strncpy(detail_, "ONLINE", sizeof(detail_) - 1);
      Serial.println("friend: online (hello + glass)");
    }
    return;
  }

  if (!hello_ok_) return;

  if (strcmp(type, "state") == 0) {
    const char* state = document["state"];
    if (state != nullptr) accept_session_state(state);
    return;
  }

  if (strcmp(type, "interrupted") == 0) {
    interrupt_speaker();
    return;
  }
  // settings / glass media: stubbed. Local Settings still owns the menu.
}

bool FriendConnection::send_json(const char* json) {
  if (json == nullptr || !ws_used_ || !ws.isConnected()) return false;
  return ws.sendTXT(json);
}

bool FriendConnection::send_frame(const uint8_t* jpeg, size_t length) {
  if (jpeg == nullptr || length == 0 || length > 48 * 1024 || !ready()) return false;
  if (!ws_used_ || !ws.isConnected()) return false;
  const size_t b64_cap = 4 * ((length + 2) / 3) + 1;
  const char prefix[] = "{\"type\":\"frame\",\"image\":\"";
  const char suffix[] = "\"}";
  const size_t prefix_len = sizeof(prefix) - 1;
  const size_t suffix_len = sizeof(suffix) - 1;
  const size_t total = prefix_len + b64_cap + suffix_len;
  char* json = static_cast<char*>(heap_caps_malloc(total + 8, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  if (json == nullptr) json = static_cast<char*>(heap_caps_malloc(total + 8, MALLOC_CAP_8BIT));
  if (json == nullptr) {
    Serial.println("friend vision: json alloc failed");
    return false;
  }
  memcpy(json, prefix, prefix_len);
  size_t b64_len = 0;
  const int rc = mbedtls_base64_encode(reinterpret_cast<unsigned char*>(json + prefix_len), b64_cap, &b64_len,
                                       jpeg, length);
  if (rc != 0 || b64_len == 0) {
    free(json);
    Serial.println("friend vision: base64 failed");
    return false;
  }
  memcpy(json + prefix_len + b64_len, suffix, suffix_len + 1);
  const bool ok = ws.sendTXT(reinterpret_cast<uint8_t*>(json), prefix_len + b64_len + suffix_len);
  free(json);
  Serial.printf("friend vision: %s %u jpeg bytes\n", ok ? "sent" : "dropped", static_cast<unsigned>(length));
  return ok;
}

bool FriendConnection::send_ptt(bool active) {
  if (!active && up_hold_valid_) {
    const int16_t pad[2] = {up_hold_, up_hold_};
    up_hold_valid_ = false;
    send_pcm16k(pad, 2);
  }
  char json[40];
  snprintf(json, sizeof(json), "{\"type\":\"ptt\",\"active\":%s}", active ? "true" : "false");
  const bool ok = send_json(json);
  Serial.printf("friend send ptt %s %s\n", active ? "down" : "up", ok ? "ok" : "dropped");
  return ok;
}

bool FriendConnection::send_select() {
  return send_json("{\"type\":\"select\"}");
}

bool FriendConnection::send_pcm16k(const int16_t* samples, size_t count) {
  if (samples == nullptr || count == 0 || !ready()) return false;
  int16_t inbuf[258];
  size_t in_n = 0;
  if (up_hold_valid_) {
    inbuf[in_n++] = up_hold_;
    up_hold_valid_ = false;
  }
  for (size_t i = 0; i < count && in_n < 257; ++i) inbuf[in_n++] = samples[i];
  if ((in_n % 2) == 1) {
    up_hold_ = inbuf[--in_n];
    up_hold_valid_ = true;
  }
  if (in_n == 0) return true;
  int16_t resampled[390];
  const size_t out_n = resample_16k_to_24k(inbuf, in_n, resampled, 390);
  if (out_n == 0) return false;
  unsigned char b64[1104];
  size_t b64_len = 0;
  const int rc = mbedtls_base64_encode(b64, sizeof(b64) - 1, &b64_len,
                                       reinterpret_cast<const unsigned char*>(resampled), out_n * 2);
  if (rc != 0 || b64_len == 0) return false;
  b64[b64_len] = '\0';
  char json[1200];
  const int n = snprintf(json, sizeof(json), "{\"type\":\"audio\",\"pcm\":\"%s\"}", b64);
  if (n < 0 || static_cast<size_t>(n) >= sizeof(json)) return false;
  return send_json(json);
}

void FriendConnection::update(bool wifi_online) {
  if (wifi_online && ws_used_ &&
      (phase_ == FriendPhase::kConnecting || phase_ == FriendPhase::kOnline)) ws.loop();

  if (!wifi_online) {
    if (phase_ != FriendPhase::kNeedConfig && phase_ != FriendPhase::kOff) {
      disconnect();
      phase_ = FriendPhase::kOff;
      strncpy(detail_, "WAITING FOR WIFI", sizeof(detail_) - 1);
    }
    return;
  }

  if (url_[0] == '\0') {
    phase_ = FriendPhase::kNeedConfig;
    return;
  }

  const uint32_t now = millis();
  if (phase_ == FriendPhase::kBackoff) {
    if (static_cast<int32_t>(now - backoff_until_) < 0) return;
    phase_ = FriendPhase::kOff;
  }

  if (phase_ == FriendPhase::kConnecting && hello_ok_ && glass_seen_ && session_ready_) {
    phase_ = FriendPhase::kOnline;
    strncpy(detail_, "ONLINE", sizeof(detail_) - 1);
  }

  if (phase_ == FriendPhase::kConnecting && now - last_try_ > 8000) {
    Serial.println("friend: handshake timed out");
    disconnect();
    schedule_backoff();
    return;
  }

  if (phase_ == FriendPhase::kOnline || phase_ == FriendPhase::kConnecting) return;
  if (phase_ == FriendPhase::kNeedConfig) return;

  phase_ = FriendPhase::kHealth;
  last_try_ = now;
  if (!inspect_health()) {
    if (phase_ != FriendPhase::kNeedConfig) schedule_backoff();
    return;
  }
  if (!open_socket()) {
    strncpy(detail_, "WS BEGIN FAIL", sizeof(detail_) - 1);
    schedule_backoff();
  }
}

}  // namespace gizmo
