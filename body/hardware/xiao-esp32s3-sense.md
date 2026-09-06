# Gizmo hardware: XIAO ESP32S3 Sense

Selected by Jun on 2026-09-06: **Seeed Studio XIAO ESP32S3 Sense**, manufacturer
part **113991115**, pictured retailer code **118079**. This replaces earlier
candidate-board assumptions. External wiring still needs the hardware builder's pin map.

Hardware is assembled by Jun's friend in Tokyo; Jun owns software/AI. Firmware
can be built here and flashed/tested there, with serial logs and device video
returned as physical evidence. Local USB access is not required for development.

## Confirmed board resources

- ESP32-S3, 8 MB flash and 8 MB PSRAM; PlatformIO board `seeed_xiao_esp32s3`.
- Sense expansion board provides the camera connector, PDM microphone and microSD.
- Camera sensor revision must be read at runtime: Seeed replaced OV2640 with
  OV3660 in later stock. A retailer image does not establish the shipped sensor.
- Camera pins are isolated in `../firmware/include/gizmo/board.h`.
- PDM microphone: data GPIO41, clock GPIO42.

## Selected external parts

- Display: Akizuki **116265**, title **MSP2807**, catalog model **AA317**;
  2.8-inch **ILI9341**, **320 × 240** landscape, 4-wire SPI. Includes a touch
  controller and SD slot; their use is not selected. Module power is listed as
  3.3–5 V; this does not establish that every signal accepts 5 V.
- Amplifier: user-supplied purchase screenshot identifies a **Youmile MAX98357**
  I2S Class-D module. Confirm A/B suffix, physical pin labels, supply and gain/SD
  strapping before implementing the audio interface. The speaker itself is unknown.

## External hardware awaiting confirmation

| Part | Required before implementation |
| --- | --- |
| Display | GPIO map, supply, backlight/reset wiring, physical rotation; whether touch/SD are connected |
| Speaker and amplifier | Speaker impedance/wattage, amplifier A/B suffix, supply, I2S pins, gain/SD strapping |
| Select, Up, Down, PTT | Switch wiring, GPIO assignment or expander |
| Power and battery | Switch circuit, battery/charging arrangement, voltage sensing |
| Storage | Whether the Sense microSD slot will be used for character/media assets |

Do not assign external pins from a generic ESP32 diagram. Check camera, PDM,
microSD, flash/PSRAM, USB, and boot-strapping reservations before approving the
combined wiring. Record the final pin table here alongside the exact parts.

## Evidence and acceptance

A cross-compiled binary proves the source/toolchain agree. It does not prove
camera detection, RAM behavior, pin wiring, display geometry or frame rate.
No board was visible among this Mac's serial ports when work started.

2026-09-06: camera bring-up cross-build passed with PlatformIO 6.1.18,
Espressif32 6.12.0, Arduino framework 3.20017.241212+sha.dcc1105b (2.0.17),
Xtensa toolchain 8.4.0+2021r2-patch5 and esptool 4.9.0. The linker reported
22,820 bytes static RAM and 314,649 bytes application flash. These figures
exclude runtime camera/PSRAM allocations and are not a frame-rate or memory
stress test. The binary has not been flashed or tested on hardware.

First connected-board check: flash the bring-up target, record detected flash,
PSRAM and sensor PID; start capture with `c`, stop with `x`; repeat and check
memory/capture failures. Keep images local. Once the peripherals are selected,
verify both camera-entry gestures, debouncing, preview plus character/captions,
audio during preview, and capture shutdown on every exit on the actual device.

## Primary sources

- [Selected Akizuki display](https://akizukidenshi.com/catalog/g/g116265/)

- [Seeed board overview and camera revision](https://wiki.seeedstudio.com/xiao_esp32s3_getting_started/)
- [Seeed camera wiring and API](https://wiki.seeedstudio.com/xiao_esp32s3_camera_usage/)
- [Seeed microphone pins](https://wiki.seeedstudio.com/xiao_esp32s3_sense_mic/)
- [Pinned PlatformIO board definition](https://github.com/platformio/platform-espressif32/blob/v6.12.0/boards/seeed_xiao_esp32s3.json)

## Forward to the hardware builder

Please send:

1. A schematic or GPIO-to-pin table for the display, MAX98357 module, four
   buttons (Up, Down, Select, PTT), and any power-sense/control circuit. Include
   display CS/DC/reset/backlight and amplifier BCLK/LRC/DIN/SD/GAIN connections.
   If wiring is not decided, say so; agree on one complete pin budget first.
2. Speaker model or impedance/wattage, amplifier board photos/pin labels, battery
   and power/charging setup, and the buttons/rocker being used.
3. Whether either SD slot and the display touch controller will be used; whether
   an I/O expander is already present. These affect the available GPIO budget.
4. Whether the assembled board is ready to flash, and whether the builder uses
   macOS, Windows or Linux. We will supply build/flash instructions and request
   serial logs plus short videos of the physical acceptance checks.
