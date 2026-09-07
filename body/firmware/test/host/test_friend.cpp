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
  // Wi-Fi reconnect to the same powered session must not cold-boot it again.
  c.abort();mock_sent.clear();c.open_socket();
  message(c,"{\"type\":\"hello\",\"protocol_version\":1,\"state\":\"asleep\"}");
  message(c,"{\"type\":\"glass\",\"viewing\":false}");assert(c.ready());assert(mock_sent.empty());
  message(c,"{\"type\":\"hello\",\"protocol_version\":2,\"state\":\"listening\"}");assert(!c.ready());
  puts("friend: cold boot, readiness, reconnect, protocol, TLS CA, immediate connect passed");
}
