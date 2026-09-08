#pragma once
#include <cstdlib>
constexpr int MALLOC_CAP_SPIRAM=1, MALLOC_CAP_8BIT=2;
inline void* heap_caps_malloc(size_t n, int) { return malloc(n); }
inline size_t heap_caps_get_free_size(int) { return 8*1024*1024; }
