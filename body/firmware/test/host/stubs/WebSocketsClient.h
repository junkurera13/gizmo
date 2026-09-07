#pragma once
#include <Arduino.h>
enum WStype_t {WStype_DISCONNECTED,WStype_CONNECTED,WStype_TEXT,WStype_ERROR};
inline std::vector<std::string> mock_sent;
inline const char* mock_socket_ca=nullptr;
inline unsigned mock_reconnect=0;
struct WebSocketsClient {
  void disconnect() {} void onEvent(void(*)(WStype_t,uint8_t*,size_t)) {}
  void setReconnectInterval(unsigned n) {mock_reconnect=n;} void setExtraHeaders(const char*) {}
  void begin(const char*,uint16_t,const char*) {}
  void beginSslWithCA(const char*,uint16_t,const char*,const char* ca) {mock_socket_ca=ca;}
  bool isConnected() {return true;} bool sendTXT(const char* s) {mock_sent.emplace_back(s);return true;}
  void loop() {}
};
