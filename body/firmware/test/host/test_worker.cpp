#include <Arduino.h>
#include <cassert>
#include <chrono>
#include <thread>
#include <HTTPClient.h>
#include <freertos/task.h>
#include "gizmo/friend.h"
int main() {
  gizmo::FriendLink link;
  mock_health_blocked.store(true);
  link.begin();
  assert(link.set_url("http://192.0.2.1:43147"));
  link.update(true);
  for(int i=0;i<1000&&!mock_health_entered.load();++i)std::this_thread::sleep_for(std::chrono::milliseconds(1));
  assert(mock_health_entered.load());
  const auto start=std::chrono::steady_clock::now();
  int16_t output[256];
  for(int i=0;i<10000;++i) {
    link.update(true);
    assert(link.take_speaker(output,256)==0);
    assert(!link.send_ptt(true)); // not ready; local recording remains available
  }
  const auto elapsed=std::chrono::steady_clock::now()-start;
  assert(elapsed<std::chrono::milliseconds(100));
  // Configuration is also queued, never executed on the body loop.
  assert(link.set_token("test-token"));
  mock_health_blocked.store(false);
  mock_task_stop.store(true);
  mock_task.join();
  puts("worker: body loop stays responsive while HTTP is blocked; commands queue without waiting");
}
