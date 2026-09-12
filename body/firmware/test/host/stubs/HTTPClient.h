#pragma once
#include <Arduino.h>
#include <WiFiClient.h>
#include <atomic>
#include <chrono>
#include <thread>
#include <map>
inline std::atomic<bool> mock_health_blocked{false},mock_health_entered{false};
inline std::map<std::string,String> mock_media_headers;
inline std::map<std::string,String> mock_request_headers;
inline int mock_media_status=200, mock_media_length=-1, mock_redirects=-1;
inline std::string mock_request_url;
constexpr int HTTPC_DISABLE_FOLLOW_REDIRECTS=0;
struct HTTPClient {
  WiFiClient stream;
  void setTimeout(int) {} void setConnectTimeout(int) {}
  template<class T> bool begin(T&,const char* url) {mock_request_url=url;mock_request_headers.clear();mock_media_cursor=0;return true;}
  int GET() {mock_health_entered.store(true);while(mock_health_blocked.load())std::this_thread::sleep_for(std::chrono::milliseconds(1));return mock_media_status;}
  String getString() {return "{\"body_protocol\":{\"version\":1}}";}
  void end() {}
  void setReuse(bool) {}
  void setFollowRedirects(int value) {mock_redirects=value;}
  void collectHeaders(const char**,size_t) {}
  void addHeader(const char* key,const char* value) {mock_request_headers[key]=value;}
  String header(const char* key) {return mock_media_headers[key];}
  int getSize() {return mock_media_length;}
  WiFiClient* getStreamPtr() {return &stream;}
  bool connected() {return mock_media_stalled || mock_media_cursor<mock_media_body.size();}
};
