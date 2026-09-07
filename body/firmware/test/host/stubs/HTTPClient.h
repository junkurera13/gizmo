#pragma once
#include <Arduino.h>
#include <atomic>
#include <chrono>
#include <thread>
inline std::atomic<bool> mock_health_blocked{false},mock_health_entered{false};
struct HTTPClient { void setTimeout(int) {} void setConnectTimeout(int) {} template<class T> bool begin(T&,const char*) {return true;} int GET() {mock_health_entered.store(true);while(mock_health_blocked.load())std::this_thread::sleep_for(std::chrono::milliseconds(1));return 200;} String getString() {return "{\"body_protocol\":{\"version\":1}}";} void end() {} };
