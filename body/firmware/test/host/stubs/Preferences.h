#pragma once
#include <Arduino.h>
struct Preferences { void begin(const char*,bool) {} void end() {} size_t getString(const char*,char* p,size_t) {p[0]=0;return 0;} void putString(const char*,const char*) {} };
