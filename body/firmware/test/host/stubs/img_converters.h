#pragma once
#include <cstddef>
#include <cstdint>
constexpr int JPG_SCALE_NONE=0;
inline bool mock_jpeg_ok=true;
inline int mock_jpeg_failures=0;
inline const uint8_t* mock_decoded_frame=nullptr;
inline bool jpg2rgb565(const uint8_t* bytes,size_t,uint8_t*,int) {mock_decoded_frame=bytes;if(mock_jpeg_failures>0){--mock_jpeg_failures;return false;}return mock_jpeg_ok;}
