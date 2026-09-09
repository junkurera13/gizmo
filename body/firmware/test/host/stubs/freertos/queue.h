#pragma once
#include <freertos/FreeRTOS.h>
#include <mutex>
#include <deque>
#include <vector>
#include <cstring>
struct MockQueue { size_t cap,size;std::mutex lock;std::deque<std::vector<char>> data;MockQueue(size_t c,size_t s):cap(c),size(s){} };
using QueueHandle_t=MockQueue*;
inline QueueHandle_t xQueueCreate(size_t cap,size_t size) {return new MockQueue(cap,size);}
inline void vQueueDelete(QueueHandle_t q) {delete q;}
inline int xQueueSend(QueueHandle_t q,const void* p,TickType_t wait) {
  if(wait)std::abort();
  std::lock_guard<std::mutex> lock(q->lock);if(q->data.size()==q->cap)return 0;
  auto* bytes=static_cast<const char*>(p);q->data.emplace_back(bytes,bytes+q->size);return pdTRUE;
}
inline int xQueueReceive(QueueHandle_t q,void* p,TickType_t wait) {
  if(wait)std::abort();
  std::lock_guard<std::mutex> lock(q->lock);if(q->data.empty())return 0;
  memcpy(p,q->data.front().data(),q->size);q->data.pop_front();return pdTRUE;
}
inline void xQueueReset(QueueHandle_t q) {std::lock_guard<std::mutex> lock(q->lock);q->data.clear();}
inline unsigned uxQueueSpacesAvailable(QueueHandle_t q) {std::lock_guard<std::mutex> lock(q->lock);return q->cap-q->data.size();}
inline unsigned uxQueueMessagesWaiting(QueueHandle_t q) {std::lock_guard<std::mutex> lock(q->lock);return q->data.size();}
inline void xQueueOverwrite(QueueHandle_t q,const void* p) {
  std::lock_guard<std::mutex> lock(q->lock);q->data.clear();auto* bytes=static_cast<const char*>(p);q->data.emplace_back(bytes,bytes+q->size);
}
