#include <Arduino.h>
#include <cassert>
#include <deque>
#include <WebSocketsClient.h>
#include <driver/i2s.h>
#define private public
#include "gizmo/friend_connection.h"
#undef private
#include "gizmo/audio.h"

namespace gizmo {
void apply_volume(int16_t*, size_t, uint8_t, uint8_t) {}
}

int main() {
  gizmo::FriendConnection connection;
  connection.begin();
  assert(connection.set_url("http://localhost:43147"));
  assert(connection.open_socket());
  connection.phase_ = gizmo::FriendPhase::kOnline;
  gizmo::Audio audio;
  assert(audio.begin() == ESP_OK);

  // Two minutes of speech produced 4x faster than the physical speaker.
  // Uneven packets cross resampler boundaries and wrap every device ring.
  constexpr size_t total = 24000 * 120;
  const size_t sizes[] = {2401, 4799, 36861, 961, 7199};
  std::vector<int16_t> wire(total), expected;
  for (size_t i = 0; i < total; ++i) wire[i] = static_cast<int16_t>((i * 31) % 30001 - 15000);
  for (size_t i = 0; i < total; i += 3) {
    expected.push_back(wire[i]);
    expected.push_back(static_cast<int16_t>((int32_t(wire[i + 1]) + wire[i + 2]) / 2));
  }
  size_t sent = 0, packet = 0;
  uint32_t tick = 0;
  mock_socket_loop = [&] {
    const size_t available = std::min(total, size_t(tick) * 960); // 10 ms at 4x
    const size_t count = std::min(sizes[packet % 5], total - sent);
    if (!count || sent + count > available) return;
    assert(connection.enqueue_speaker(wire.data() + sent, count));
    sent += count;
    ++packet;
  };
  std::deque<int16_t> worker;
  int16_t pcm[256];
  for (; tick < 13000; ++tick) {
    mock_now += 10;
    connection.update(true);
    while (worker.size() <= 80 * 256 - 256) {
      const size_t count = connection.take_speaker(pcm, 256);
      if (!count) break;
      worker.insert(worker.end(), pcm, pcm + count);
    }
    // 160 stereo frames per 10 ms, with a DMA-sized write allowance.
    mock_write_limit = 160 * 4;
    audio.update();
    while (!worker.empty() && audio.live_capacity_left()) {
      const size_t count = std::min({size_t(256), worker.size(), audio.live_capacity_left()});
      for (size_t i = 0; i < count; ++i) { pcm[i] = worker.front(); worker.pop_front(); }
      assert(audio.enqueue_live(pcm, count) == count);
    }
    if (sent == total && worker.empty() && !connection.speaker_pending() &&
        audio.live_capacity_left() == 16000 * 3 && !audio.playing()) break;
  }
  assert(sent == total);
  assert(mock_written.size() == expected.size() * 2);
  for (size_t i = 0; i < expected.size(); ++i) {
    assert(mock_written[i * 2] == expected[i]);
    assert(mock_written[i * 2 + 1] == expected[i]);
  }
  assert(tick >= 12000 && tick < 12100);

  // A full downstream queue pauses reads, but a local interrupt immediately
  // frees the receive window and discards the old resampler tail.
  assert(connection.enqueue_speaker(wire.data(), 60001));
  const size_t queued = connection.speaker_n_;
  assert(!connection.enqueue_speaker(wire.data(), 24000));
  assert(connection.speaker_n_ == queued && connection.down_n_ == 1);
  int reads = 0;
  mock_socket_loop = [&] { ++reads; };
  connection.update(true);
  assert(reads == 0);
  connection.interrupt_speaker();
  audio.stop_live();
  assert(!connection.speaker_pending() && connection.down_n_ == 0);
  assert(connection.take_barge_in());
  connection.update(true);
  assert(reads == 1);
  // Wi-Fi loss must still clear a full ring even while reads are paused.
  assert(connection.enqueue_speaker(wire.data(), 60000));
  connection.update(false);
  assert(!connection.ready() && !connection.speaker_pending());
  mock_socket_loop = nullptr;
  puts("stream: 120 seconds at 4x arrival, irregular packets, resampling, queue/ring wraps and stereo output preserved");
}
