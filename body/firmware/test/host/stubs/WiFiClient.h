#pragma once
#include <Arduino.h>
inline std::vector<uint8_t> mock_media_body;
inline size_t mock_media_cursor = 0;
inline bool mock_media_stalled = false;
struct WiFiClient {
  int available() { if(mock_media_stalled){mock_now+=1000;return 0;} return int(mock_media_body.size()-mock_media_cursor); }
  int read(uint8_t* out,size_t size) {size=min(size,mock_media_body.size()-mock_media_cursor);memcpy(out,mock_media_body.data()+mock_media_cursor,size);mock_media_cursor+=size;return int(size);}
};
