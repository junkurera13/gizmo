#pragma once
#include <atomic>
#include <chrono>
#include <thread>
#include <vector>
#include <freertos/FreeRTOS.h>
inline std::atomic<bool> mock_task_stop{false};
inline std::vector<std::thread> mock_tasks;
struct StopTask {};
inline int xTaskCreate(void(*fn)(void*),const char*,int,void* context,int,void*) {
  mock_tasks.emplace_back([=]{try{fn(context);}catch(const StopTask&) {}});return pdPASS;
}
inline void join_mock_tasks() {
  mock_task_stop.store(true);
  for(auto& t:mock_tasks) if(t.joinable()) t.join();
  mock_tasks.clear();
  mock_task_stop.store(false);
}
inline void vTaskDelay(TickType_t ms) {
  if(mock_task_stop.load())throw StopTask{};
  std::this_thread::sleep_for(std::chrono::milliseconds(ms));
}
