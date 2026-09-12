#pragma once
#include <freertos/FreeRTOS.h>
#include <mutex>
#define portMAX_DELAY 0xffffffffu
using SemaphoreHandle_t=std::mutex*;
inline SemaphoreHandle_t xSemaphoreCreateMutex() {return new std::mutex();}
inline int xSemaphoreTake(SemaphoreHandle_t m,TickType_t) {m->lock();return pdTRUE;}
inline int xSemaphoreGive(SemaphoreHandle_t m) {m->unlock();return pdTRUE;}
