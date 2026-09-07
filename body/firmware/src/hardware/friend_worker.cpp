#include "gizmo/friend.h"
#include "gizmo/friend_connection.h"
#include <Arduino.h>
#include <string.h>
#include <freertos/task.h>

namespace gizmo {
void FriendLink::begin() {
  commands_ = xQueueCreate(32, sizeof(Command));
  speaker_ = xQueueCreate(48, sizeof(Speaker));
  statuses_ = xQueueCreate(1, sizeof(Status));
  if (!commands_ || !speaker_ || !statuses_ ||
      xTaskCreate(task, "friend-net", 12288, this, 1, nullptr) != pdPASS) {
    if (commands_) vQueueDelete(commands_);
    if (speaker_) vQueueDelete(speaker_);
    if (statuses_) vQueueDelete(statuses_);
    commands_ = speaker_ = statuses_ = nullptr;
    status_.phase = FriendPhase::kNeedConfig;
    strncpy(status_.detail, "NETWORK TASK NO MEMORY", sizeof(status_.detail));
  }
}

void FriendLink::update(bool wifi_online) {
  wifi_online_.store(wifi_online);
  if (statuses_) xQueueReceive(statuses_, &status_, 0);
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
          default: break;
        }
        if (!ok) { connection.abort(); ptt = false; }
      }
    }
    connection.update(wifi_online_.load());
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
