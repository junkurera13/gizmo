#pragma once
#include <cstdint>
struct WiFiMock { void macAddress(uint8_t* mac) { for(int i=0;i<6;++i)mac[i]=i+1; } };
inline WiFiMock WiFi;
