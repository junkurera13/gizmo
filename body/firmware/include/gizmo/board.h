#pragma once

// Seeed XIAO ESP32S3 Sense expansion board, NOT a generic ESP32-CAM.
// Source and unresolved external wiring: body/hardware/xiao-esp32s3-sense.md.
namespace gizmo::board {
constexpr int camera_xclk = 10;
constexpr int camera_sda = 40;
constexpr int camera_scl = 39;
constexpr int camera_d0 = 15;
constexpr int camera_d1 = 17;
constexpr int camera_d2 = 18;
constexpr int camera_d3 = 16;
constexpr int camera_d4 = 14;
constexpr int camera_d5 = 12;
constexpr int camera_d6 = 11;
constexpr int camera_d7 = 48;
constexpr int camera_vsync = 38;
constexpr int camera_href = 47;
constexpr int camera_pclk = 13;
constexpr int microphone_data = 41;
constexpr int microphone_clock = 42;
}  // namespace gizmo::board
