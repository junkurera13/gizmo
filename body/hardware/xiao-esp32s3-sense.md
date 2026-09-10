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
- Speaker: **Adafruit STEMMA Speaker** (PID **3885**), TS2012 Class-D plus a
  1 W / 8 Ω speaker. Analog input only (STEMMA white = IN, red = 3–5 V,
  black = GND). Signal on **D9** (GPIO8) as 9-bit / 62.5 kHz LEDC PWM. Replaces the earlier
  Youmile MAX98357 I2S breadboard amp (BCLK/LRC/DIN). On-board trim pot is
  analog gain; firmware volume still scales PCM before PWM.

## Confirmed ILI9341 wiring (2026-09-06)

Builder pin table for Akizuki **116265** / MSP2807. Touch (`T_*`) and SDO/MISO
are disconnected. RESET and LED are tied high, so firmware cannot pulse reset or
PWM the backlight. VCC is on the XIAO **VUSB** rail.

| Display label | XIAO pin / rail | ESP32-S3 GPIO |
| --- | --- | --- |
| VCC | VUSB | 5 V switched rail |
| GND | GND | GND |
| CS | D7 | 44 |
| RESET | 3V3 | tied high (`-1`) |
| DC | D6 | 43 |
| SDI (MOSI) | D10 | 9 |
| SCK | D8 | 7 |
| LED | 3V3 | tied high (`-1`) |
| SDO (MISO) | leave empty | `-1` |
| All T_ pins | leave empty | unused |

These pads are free of the Sense camera and PDM microphone pins.

## Full header budget (breadboard, 2026-09-06)

Every XIAO header pin is now assigned. `../firmware/include/gizmo/board.h` is
the source of truth; this table mirrors it.

| XIAO pin | GPIO | Function | Notes |
| --- | --- | --- | --- |
| D0 | 1 | unused | Freed when the MAX98357A was removed |
| D1 | 2 | PTT (5-way centre click) | Active-LOW, internal pull-up |
| D2 | 3 | Haptic transistor base | 1k series. Strapping pin; driven LOW first thing in `setup()` |
| D3 | 4 | unused | Freed when the MAX98357A was removed |
| D4 | 5 | UP / DOWN / SELECT ladder | ADC1_CH4, idle-low ladder below |
| D5 | 6 | Battery divider | ADC1_CH5, battery+ → 100k → node → 100k → GND |
| D6 | 43 | ILI9341 `DC` | UART0 TX at ROM boot; harmless |
| D7 | 44 | ILI9341 `CS` | Keep as a real chip select; do not tie to GND |
| D8 | 7 | ILI9341 `SCK` | Shared with the Sense microSD SCK (4.7k pull-up via J3) |
| D9 | 8 | STEMMA Speaker IN (LEDC PWM) | Adafruit 3885 analog IN (white). Also Sense microSD MISO; SD CS is held HIGH |
| D10 | 9 | ILI9341 `SDI/MOSI` | Shared with the Sense microSD MOSI. Never route audio here |
| B2B | 21 | Sense microSD `CS` | Firmware drives HIGH at boot; leave the slot empty |
| B2B | 41 / 42 | PDM mic `DATA` / `CLK` | I2S_NUM_0, the only PDM-capable controller |

### UP / DOWN / SELECT: one ADC ladder on D4

```
3V3 ──┬── UP switch ─────────────────────┐
      ├── DOWN switch ── 4.7k ───────────┤
      └── SELECT switch ── 15k ──────────┤
                                         ├──── D4 (GPIO5)
                          10k ───────────┤
                          100nF ─────────┤
GND ─────────────────────────────────────┘
```

Idle 0 V, SELECT ≈ 1.32 V, DOWN ≈ 2.24 V, UP = 3.3 V. Decode bands in
`../firmware/src/hardware/input.cpp` leave ≥300 mV on each side with 5%
resistors. The ladder idles **low** on purpose: the ESP-IDF ADC driver disables
the internal pull-up on every read, so an unwired or broken ladder reads ~0 V
and produces no phantom presses (verified on the bench: a floating D4 read
0 mV). The 100 nF gives ~1 ms RC settle; firmware debounces 30 ms on top.

### Battery divider on D5

battery+ → 100k → **D5** → 100k → GND. Firmware multiplies by
`board::battery_divider = 2.0`. Move the divider off D0: an I2S word-select
line cannot double as an analog sense node. Until wired, D5 floats and the UI
shows `NO BAT`.

### Bus isolation rules (unchanged)

- Display SPI: D7 CS, D6 DC, D8 SCK, D10 MOSI at 40 MHz. No audio on D10.
- Speaker PWM lives on D9 (GPIO8, LEDC channel 4 / timer 2). PDM RX lives on
  I2S_NUM_0 (GPIO41/42). PWM is detached when idle so D9 sits LOW (no carrier).
- GPIO21 (microSD CS) is set HIGH before any SPI or PWM starts because
  the slot's MISO pad is the speaker signal.

## External hardware awaiting confirmation

| Part | Required before implementation |
| --- | --- |
| Display rotation / mount | Physical 320×240 landscape orientation on the assembled shell; `r` cycles firmware rotation |
| Speaker and amplifier | Adafruit STEMMA Speaker 3885 on D9; analog IN + onboard TS2012, not I2S |
| Select, Up, Down | Ladder above is designed, not yet soldered; confirm decoded mV with the `i` serial key |
| Power and battery | Switch circuit, battery/charging arrangement; divider moves to D5 |
| Storage | Sense microSD slot is reserved but unused; GPIO8 is the speaker PWM pin so the slot cannot be used with audio |
| Backlight PWM | LED is currently tied to 3V3; Settings brightness scales RGB565 on blit until a GPIO exists |

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

2026-09-06 (Windows, COM6): the terminal OS build flashed and booted on the
assembled breadboard. Serial evidence: `display begin: ESP_OK`, `audio begin:
ESP_OK` for both I2S controllers, PDM recording produced non-zero peaks and
the memo played back through I2S_NUM_1, settings persisted across reset in
NVS, and the unwired D4 ladder decoded as `NONE`. Panel contents were not
inspected from here; button hardware was not yet installed.

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
