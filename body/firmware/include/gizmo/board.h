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

// ILI9341 MSP2807 (Akizuki 116265). Builder pin table 2026-09-06.
// XIAO D8=GPIO7 SCK, D10=GPIO9 MOSI, D7=GPIO44 CS, D6=GPIO43 DC.
// RESET and LED are tied to 3V3; MISO and all T_ touch pins are disconnected.
constexpr int display_sck = 7;
constexpr int display_mosi = 9;
constexpr int display_cs = 44;
constexpr int display_dc = 43;
constexpr int display_miso = -1;
constexpr int display_rst = -1;
constexpr int display_bl = -1;
constexpr int display_width = 320;
constexpr int display_height = 240;

// Sense expansion board microSD chip select. The slot shares SCK/MOSI with the
// panel and MISO (GPIO8) with the amplifier BCLK, so it is held HIGH forever.
constexpr int sd_cs = 21;

// MAX98357A I2S amplifier (builder breadboard, 2026-09-06). I2S_NUM_1, Philips.
// XIAO D0=GPIO1 LRC, D3=GPIO4 DIN, D9=GPIO8 BCLK.
constexpr int amp_lrc = 1;
constexpr int amp_din = 4;
constexpr int amp_bclk = 8;

// Controls. PTT is the 5-way switch centre click on D1, active-LOW, internal
// pull-up. UP/DOWN/SELECT share one resistor ladder on D4 (GPIO5 / ADC1_CH4)
// that idles at 0V: 10k pull-DOWN to GND, UP straight to 3V3, DOWN via 4.7k
// to 3V3, SELECT via 15k to 3V3, 100nF across the node.
// Idle 0V, SELECT ~1.32V, DOWN ~2.24V, UP 3.3V (ADC saturates ~3.1V).
// Idle-low was chosen because the ADC driver drops the internal pull-up on
// every read, so an unwired or broken ladder reads ~0V = no button.
constexpr int ptt = 2;
constexpr int buttons_adc = 5;

// Haptic coin motor, C1815 base through 1k on D2 (GPIO3, a strapping pin).
constexpr int haptic = 3;

// Battery divider on D5 (GPIO6 / ADC1_CH5): battery+ -> 100k -> node -> 100k -> GND.
constexpr int battery_adc = 6;
constexpr float battery_divider = 2.0f;
}  // namespace gizmo::board
