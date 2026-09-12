#include "gizmo/friend.h"
#include "gizmo/friend_connection.h"
#include <Arduino.h>
#include <string.h>
#include <esp_heap_caps.h>
#include <freertos/task.h>

namespace gizmo {
void FriendLink::begin() {
  if (commands_) return;
  commands_ = xQueueCreate(32, sizeof(Command));
  speaker_ = xQueueCreate(80, sizeof(Speaker));
  statuses_ = xQueueCreate(1, sizeof(Status));
  shows_ = xQueueCreate(1, sizeof(ShowRequest));
  for (int i = 0; i < 2; ++i) {
    jpeg_slot_[i] = static_cast<uint8_t*>(heap_caps_malloc(kJpegMax, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    if (jpeg_slot_[i] == nullptr) {
      jpeg_slot_[i] = static_cast<uint8_t*>(heap_caps_malloc(kJpegMax, MALLOC_CAP_8BIT));
    }
  }
  // Pinned to core 0 with the radio stack: TLS crypto bursts there can never
  // preempt loopTask on core 1 (the boot flipbook and film blits live there).
  if (!commands_ || !speaker_ || !statuses_ || !shows_ || jpeg_slot_[0] == nullptr || jpeg_slot_[1] == nullptr ||
      xTaskCreatePinnedToCore(task, "friend-net", 16384, this, 3, nullptr, 0) != pdPASS) {
    if (commands_) vQueueDelete(commands_);
    if (speaker_) vQueueDelete(speaker_);
    if (statuses_) vQueueDelete(statuses_);
    if (shows_) vQueueDelete(shows_);
    shows_ = nullptr;
    commands_ = speaker_ = statuses_ = nullptr;
    status_.phase = FriendPhase::kNeedConfig;
    strncpy(status_.detail, "NETWORK TASK NO MEMORY", sizeof(status_.detail));
  }
}

void FriendLink::update(bool wifi_online) {
  wifi_online_.store(wifi_online);
  if (statuses_) xQueueReceive(statuses_, &status_, 0);
}
bool FriendLink::take_show(ShowRequest& request) {
  return shows_ && xQueueReceive(shows_, &request, 0) == pdTRUE;
}
bool FriendLink::take_line(char* dest, size_t cap) {
  if (!dest || cap == 0 || seen_line_revision_ == status_.line_revision) return false;
  seen_line_revision_ = status_.line_revision;
  strlcpy(dest, status_.line, cap);
  return true;
}

bool FriendLink::configure(Kind kind, const char* value) {
  if (!commands_ || !value || strlen(value) >= sizeof(Command::data.text)) return false;
  Command command{};
  command.kind = kind;
  strncpy(command.data.text, value, sizeof(command.data.text) - 1);
  return xQueueSend(commands_, &command, 0) == pdTRUE;
}
bool FriendLink::set_url(const char* value) { return configure(Kind::kUrl, value); }
bool FriendLink::set_token(const char* value) { return configure(Kind::kToken, value); }
void FriendLink::forget() { queue(Kind::kForget); }
bool FriendLink::queue(Kind kind) {
  if (!commands_) return false;
  Command command{};
  command.kind = kind;
  command.generation = status_.generation;
  const bool sent = xQueueSend(commands_, &command, 0) == pdTRUE;
  if (!sent) overflow_.store(true);
  return sent;
}
bool FriendLink::send_ptt(bool active) {
  if (active && !ready()) return false;
  return queue(active ? Kind::kPttDown : Kind::kPttUp);
}
bool FriendLink::send_select() { return ready() && queue(Kind::kSelect); }
bool FriendLink::send_glass_ready(const GlassReady& ack) {
  if (!commands_ || !ready() || ack.cue == 0) return false;
  Command command{};
  command.kind = Kind::kGlassReady;
  command.generation = status_.generation;
  command.data.glass = ack;
  // A dropped ack only costs the brain its short wait; never cancel the turn for it.
  return xQueueSend(commands_, &command, 0) == pdTRUE;
}
bool FriendLink::send_jpeg(const uint8_t* jpeg, size_t length) {
  if (!ready() || jpeg == nullptr || length == 0 || length > kJpegMax || jpeg_slot_[0] == nullptr ||
      jpeg_slot_[1] == nullptr) {
    return false;
  }
  const int sending = jpeg_sending_.load();
  const int published = jpeg_published_.load();
  int wr = 0;
  if (sending == 0) wr = 1;
  else if (sending == 1) wr = 0;
  else wr = published == 0 ? 1 : 0;
  memcpy(jpeg_slot_[wr], jpeg, length);
  jpeg_len_[wr] = length;
  jpeg_published_.store(wr, std::memory_order_release);
  jpeg_generation_.fetch_add(1, std::memory_order_release);
  return true;
}
bool FriendLink::send_pcm16k(const int16_t* samples, size_t count) {
  if (!commands_ || !ready() || !samples || count == 0 || count > 256) return false;
  // Reserve control slots so release/interrupt cannot be crowded out by PCM.
  if (uxQueueSpacesAvailable(commands_) <= 2) {
    overflow_.store(true);
    return false;
  }
  Command command{};
  command.kind = Kind::kPcm;
  command.generation = status_.generation;
  command.count = count;
  memcpy(command.data.pcm, samples, count * sizeof(int16_t));
  if (xQueueSend(commands_, &command, 0) == pdTRUE) return true;
  overflow_.store(true);
  return false;
}
void FriendLink::interrupt_speaker() {
  pending_.count = pending_read_ = 0;
  queue(Kind::kInterrupt);
}
bool FriendLink::take_barge_in() {
  if (seen_interrupt_ == status_.interrupt) return false;
  seen_interrupt_ = status_.interrupt;
  pending_.count = pending_read_ = 0;
  return true;
}
size_t FriendLink::take_speaker(int16_t* dest, size_t cap) {
  if (!speaker_ || !dest || !cap) return 0;
  if (pending_.generation != status_.generation) pending_.count = pending_read_ = 0;
  while (pending_read_ == pending_.count) {
    if (xQueueReceive(speaker_, &pending_, 0) != pdTRUE) return 0;
    pending_read_ = 0;
    if (pending_.generation == status_.generation) break;
    pending_.count = 0;
  }
  const size_t n = min(cap, pending_.count - pending_read_);
  memcpy(dest, pending_.pcm + pending_read_, n * sizeof(int16_t));
  pending_read_ += n;
  return n;
}
void FriendLink::task(void* context) { static_cast<FriendLink*>(context)->run(); }
void FriendLink::run() {
  FriendConnection connection;
  connection.begin();
  Status status;
  bool was_ready = false;
  bool ptt = false;
  for (;;) {
    if (overflow_.exchange(false)) {
      // Never submit a turn with silently missing mic chunks. Disconnect
      // cancels the server's PTT owner and recovery starts a new generation.
      connection.abort();
      xQueueReset(commands_);
      ptt = false;
      Serial.println("friend: outbound queue full; turn cancelled");
    }
    Command command{};
    for (int i = 0; i < 32 && xQueueReceive(commands_, &command, 0) == pdTRUE; ++i) {
      if (command.kind == Kind::kUrl) connection.set_url(command.data.text);
      else if (command.kind == Kind::kToken) connection.set_token(command.data.text);
      else if (command.kind == Kind::kForget) connection.forget();
      else if (command.kind == Kind::kInterrupt) connection.interrupt_speaker();
      else if (connection.ready() && command.generation == status.generation) {
        bool ok = true;
        switch (command.kind) {
          case Kind::kPttDown: ptt = connection.send_ptt(true); ok = ptt; break;
          case Kind::kPttUp: if (ptt) ok = connection.send_ptt(false); ptt = false; break;
          case Kind::kPcm: if (ptt) ok = connection.send_pcm16k(command.data.pcm, command.count); break;
          case Kind::kSelect: ok = connection.send_select(); break;
          case Kind::kGlassReady:
            connection.send_glass_ready(command.data.glass.cue, command.data.glass.motion, command.data.glass.ok);
            break;
          default: break;
        }
        if (!ok) { connection.abort(); ptt = false; }
      }
    }
    const uint32_t jpeg_gen = jpeg_generation_.load(std::memory_order_acquire);
    if (jpeg_gen != jpeg_seen_) {
      const int idx = jpeg_published_.load(std::memory_order_acquire);
      if (idx == 0 || idx == 1) {
        jpeg_sending_.store(idx, std::memory_order_release);
        if (!connection.send_frame(jpeg_slot_[idx], jpeg_len_[idx])) {
          Serial.println("friend vision: send failed");
        }
        jpeg_sending_.store(-1, std::memory_order_release);
      }
      jpeg_seen_ = jpeg_gen;
    }
    connection.update(wifi_online_.load());
    ShowRequest show;
    if (connection.take_show(show)) xQueueOverwrite(shows_, &show);
    if (connection.take_line(status.line, sizeof(status.line))) ++status.line_revision;
    status.thinking = connection.session_thinking();
    status.talking = connection.session_talking();
    if (connection.ready() != was_ready) {
      ++status.generation;
      was_ready = connection.ready();
      ptt = false;
      xQueueReset(speaker_);
    }
    if (connection.take_barge_in()) {
      ++status.interrupt;
      xQueueReset(speaker_);
    }
    status.phase = connection.phase();
    status.hello = connection.hello_ok();
    status.token = connection.has_token();
    strncpy(status.detail, connection.detail(), sizeof(status.detail));
    strncpy(status.url, connection.brain_url(), sizeof(status.url));
    strncpy(status.device, connection.device_id(), sizeof(status.device));
    xQueueOverwrite(statuses_, &status);
    while (uxQueueSpacesAvailable(speaker_) > 0) {
      Speaker packet{};
      packet.generation = status.generation;
      packet.count = connection.take_speaker(packet.pcm, 256);
      if (!packet.count) break;
      xQueueSend(speaker_, &packet, 0);
    }
    vTaskDelay(pdMS_TO_TICKS(2));
  }
}
}
