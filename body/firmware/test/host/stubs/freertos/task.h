#pragma once
#include <atomic>
#include <chrono>
#include <thread>
#include <freertos/FreeRTOS.h>
inline std::atomic<bool> mock_task_stop{false};
inline std::thread mock_task;
struct StopTask {};
inline int xTaskCreate(void(*fn)(void*),const char*,int,void* context,int,void*) {
  mock_task=std::thread([=]{try{fn(context);}catch(const StopTask&) {}});return pdPASS;
}
inline void vTaskDelay(TickType_t ms) {
  if(mock_task_stop.load())throw StopTask{};
  std::this_thread::sleep_for(std::chrono::milliseconds(ms));
}
