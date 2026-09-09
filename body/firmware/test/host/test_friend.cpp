#include <Arduino.h>
#include <cassert>
#include <WebSocketsClient.h>
#include <WiFiClientSecure.h>
#define private public
#include "gizmo/friend_connection.h"
#undef private
void message(gizmo::FriendConnection& c,const char* s) { c.on_socket_event(WStype_TEXT,reinterpret_cast<uint8_t*>(const_cast<char*>(s)),strlen(s)); }
int main() {
  gizmo::FriendConnection c;c.begin();
  assert(c.set_url("https://gizmo-brain-production.up.railway.app"));
  assert(c.set_token("test-token"));
  assert(c.inspect_health());assert(mock_health_ca&&strstr(mock_health_ca,"BEGIN CERTIFICATE"));
  assert(c.open_socket());assert(mock_socket_ca==mock_health_ca);assert(mock_reconnect==0);
  message(c,"{\"type\":\"hello\",\"protocol_version\":1,\"state\":\"powered_off\"}");
  assert(mock_sent.size()==1&&mock_sent[0]=="{\"type\":\"power\",\"on\":true}");
  message(c,"{\"type\":\"glass\",\"viewing\":false}");assert(!c.ready());
  message(c,"{\"type\":\"state\",\"state\":\"booting\"}");assert(!c.ready());
  message(c,"{\"type\":\"state\",\"state\":\"listening\"}");assert(c.ready());
  gizmo::ShowRequest show;
  c.take_show(show);
  const std::string base = std::string("/shows/") + c.device_id() + "/0123456789abcdef0123456789abcdef";
  message(c, ("{\"type\":\"glass\",\"still\":\"" + base + ".jpg\",\"viewing\":true}").c_str());
  assert(c.take_show(show) && show.viewing && show.frames[0] == 0);
  assert(std::string(show.token) == "test-token");
  assert(std::string(show.still) == base + ".jpg");
  message(c, "{\"type\":\"glass\",\"frames\":\"https://evil.test/video.mjpeg\"}");
  assert(!c.take_show(show));
  message(c, ("{\"type\":\"glass\",\"frames\":\"" + base + ".mjpeg\",\"viewing\":true}").c_str());
  assert(c.take_show(show) && gizmo::show_same(show.still, show.frames));
  message(c, "{\"type\":\"glass\",\"emotion\":\"happy\"}");
  assert(!c.take_show(show)); // ordinary character updates preserve the picture
  c.send_select();
  assert(c.take_show(show) && !show.viewing);
  message(c, ("{\"type\":\"glass\",\"frames\":\"" + base + ".mjpeg\",\"viewing\":true}").c_str());
  assert(!c.take_show(show)); // a late video cannot revive a dismissed still
  // Storytelling cues: a held beat is handed over apart from the current picture,
  // "go" carries the cue, and the ack names the cue and kind.
  const std::string next = std::string("/shows/") + c.device_id() + "/abcdef0123456789abcdef0123456789";
  message(c, ("{\"type\":\"glass\",\"still\":\"" + next + ".jpg\",\"viewing\":true,\"cue\":7,\"hold\":true}").c_str());
  assert(c.take_show(show) && show.viewing && show.hold && !show.go && show.cue == 7 && show.frames[0] == 0);
  assert(std::string(show.still) == next + ".jpg");
  message(c, ("{\"type\":\"glass\",\"still\":\"" + next + ".jpg\",\"frames\":\"" + next + ".mjpeg\",\"viewing\":true,\"cue\":7,\"hold\":true}").c_str());
  assert(c.take_show(show) && show.hold && show.cue == 7 && gizmo::show_same(show.still, show.frames));
  assert(!c.take_show(show));
  message(c, ("{\"type\":\"glass\",\"still\":\"" + next + ".jpg\",\"subject\":\"x\",\"viewing\":true,\"cue\":7,\"go\":true}").c_str());
  assert(c.take_show(show) && show.viewing && show.go && !show.hold && show.cue == 7);
  mock_sent.clear();
  assert(c.send_glass_ready(7, false, true));
  assert(c.send_glass_ready(7, true, false));
  assert(!c.send_glass_ready(0, false, true));
  assert(mock_sent.size() == 2);
  assert(mock_sent[0] == "{\"type\":\"glass_ready\",\"cue\":7,\"kind\":\"still\",\"ok\":true}");
  assert(mock_sent[1] == "{\"type\":\"glass_ready\",\"cue\":7,\"kind\":\"motion\",\"ok\":false}");
  message(c, "{\"type\":\"glass\",\"viewing\":false}");
  assert(c.take_show(show) && !show.viewing);
  message(c, ("{\"type\":\"glass\",\"still\":\"" + next + ".jpg\",\"viewing\":true,\"cue\":8,\"hold\":true}").c_str());
  c.send_select();
  assert(c.take_show(show) && !show.viewing && !c.take_show(show)); // select also drops a held cue
  // Wi-Fi reconnect to the same powered session must not cold-boot it again.
  c.abort();mock_sent.clear();c.open_socket();
  message(c,"{\"type\":\"hello\",\"protocol_version\":1,\"state\":\"asleep\"}");
  message(c,"{\"type\":\"glass\",\"viewing\":false}");assert(c.ready());assert(mock_sent.empty());
  message(c,"{\"type\":\"hello\",\"protocol_version\":2,\"state\":\"listening\"}");assert(!c.ready());
  puts("friend: cold boot, readiness, reconnect, protocol, TLS CA, immediate connect passed");
}
