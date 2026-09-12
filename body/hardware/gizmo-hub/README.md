# Gizmo interconnect PCB — revision A

KiCad 10 project: **Gizmo_Hub.kicad_pro**. Open **Gizmo_Hub.kicad_sch** for the schematic and **Gizmo_Hub.kicad_pcb** for the fully routed PCB. Local symbol and footprint libraries are included; no library installation is needed.

The board is **75 × 70 mm**, two copper layers, nominal 1.6 mm FR-4. It accommodates the user's corrected **3,000 mAh, 60 × 40 × 8 mm** battery, rather than the 300 mAh battery in the initial request. The rear has a **62 × 42 mm** marked clearance area (x=6.5–68.5 mm, y=23–65 mm), with no components, header pins, or vias inside. Allow additional enclosure space for the lead exit, insulation, and battery expansion. The listing dimensions and connector polarity have not been physically measured.

## What is fitted

- U1: XIAO ESP32S3 Sense on its 14 castellated side contacts. The Seeed footprint coordinates are retained; underside BAT, USB, and debug contacts are intentionally omitted for this supply arrangement. Camera and PDM microphone remain on the Sense assembly. The USB end points toward the upper board edge. The manufacturer's full module outline is on F.Fab; the top/bottom outline and pin labels are on silkscreen.
- R1=10k, R2=4.7k, R3=15k, C1=100nF: idle-low switch ladder on D4/GPIO5.
- R4=100k and R5=100k: battery divider on D5/GPIO6, ratio 2.0.
- Edge headers and front-side test pads. No display, speaker amplifier, transistor, motor, switches, charger, battery holder, or additional USB connector.

R1–R5 are 0805, 1% resistors; C1 is 0805, X7R, at least 10 V. All six passives mount on the front. Signal routing is 0.25 mm, power routing is nominally 0.60 mm, clearance is 0.20 mm, and vias are 0.60/0.30 mm. Ground pours are filled on both layers. The four 2.2 mm nonplated mounting holes accept M2 hardware. No headers or tall hardware belong under the battery.

## Confirmed power wiring

This revision preserves the user's working breadboard connection; it does **not** add a boost converter:

1. Battery verified positive/negative leads go to the off-board TP4056 **B+ / B−**.
2. TP4056 **OUT−** goes to hub **J6 pin 2, GND**.
3. TP4056 **OUT+** goes through the off-board on/off switch to hub **J6 pin 3, 5V**.
4. TP4056 **OUT+** also goes to hub **J6 pin 1, BAT+** for battery measurement.

**J6 is a three-signal wiring header, NOT a socket for the battery's three-pin plug.** Its pins are BAT sense, GND, and switched VUSB. Do not guess the battery's third lead function or plug it into J6; verify the pack's pinout and leave any unused third lead individually insulated.

The net labeled **5V** is the XIAO **5V/VUSB rail**, also connected to display VCC and the utility headers. When driven from a battery through the switch, it follows the battery voltage; it is **not regulated to 5 V**. The display datasheet specifies 3.3–5 V. The hub does not guarantee display operation near battery cutoff or under Wi-Fi/speaker current peaks; test the completed assembly over the intended battery range.

**Open the battery power switch before connecting powered USB to the XIAO.** There is no backfeed isolation on this hub. Simultaneous USB and battery operation requires an appropriate off-board blocking/power-path circuit, as recommended by Seeed. No automatic source selection is implied by the labels. The XIAO underside BAT pads are unconnected, so the external TP4056 and XIAO charger are not paralleled through a BAT connection.

The sense divider remains connected when the switch is off and draws approximately 21 µA at 4.2 V. It is not galvanic isolation from the switched-off MCU input. For complete battery disconnection, disconnect both the power feed and the sense feed. The external TP4056 is a charger/protection module, not a regulated 5 V supply or guaranteed load-sharing controller; verify charge termination with the load off.

## Header pinout

Square pad = pin 1. Read the front view: vertical groups number downward; horizontal groups number left to right. Every jumper pin is silkscreen-labeled. Bottom PWR labels are mirrored correctly for reading from the battery side.

| Header | Pins in numerical order |
|---|---|
| J1 DISPLAY, 1×9 | 1 VCC→5V/VUSB; 2 GND; 3 CS→D7/GPIO44; 4 RESET→3V3; 5 DC→D6/GPIO43; 6 SDI→D10/GPIO9; 7 SCK→D8/GPIO7; 8 LED→3V3; 9 SDO→NC |
| J2 SPEAKER, 1×3 | 1 IN→D9/GPIO8 (STEMMA white); 2 3V3 (red); 3 GND (black) |
| J3 BUTTONS, 1×5 | 1 UP→D4/GPIO5 directly; 2 DOWN→4.7k→D4; 3 SEL→15k→D4; 4 3V3 switch common; 5 GND |
| J4 PTT, 1×2 | 1 PTT→D1/GPIO2; 2 GND |
| J5 HAPTIC, 1×3 | 1 D2/GPIO3; 2 GND; 3 optional 3V3 |
| J6 PWR, 1×3 | 1 protected BAT+ sense; 2 GND; 3 switched 5V/VUSB input |
| J7 UTIL, 1×6 | 1 5V; 2 5V; 3 GND; 4 GND; 5 3V3; 6 GND |
| J8 AUX A, 1×2 | 1 5V; 2 GND, left edge |
| J9 AUX B, 1×2 | 1 5V; 2 GND, right edge |
| J10 FUTURE, 1×2 | 1 unused D0/GPIO1; 2 unused D3/GPIO4 |
| TP1 / TP2 | Front SMD test pads: 3V3 / GND |

Use individual jumpers from the display's first nine pins in the order above. The display's pins 10–14 (T_CLK, T_CS, T_DIN, T_DO, T_IRQ) are not represented or connected. Never tie display CS to ground. Keep 40 MHz SPI jumpers short and provide a nearby ground return; the completed cable harness has not been signal-integrity tested.

Remote UP/DOWN/SEL switches each close their signal to J3's 3V3 common. **Do not wire these switches to ground.** The ladder idles at 0 V; nominal SELECT is 1.32 V, DOWN 2.24 V, and UP 3.3 V. The 10k pulldown and 100nF capacitor are on the hub. PTT is separate and closes to GND, using the firmware's internal pull-up.

J5 is a logic/control header, not a motor output. The off-board assembly contains the 1k base resistor, C1815, flyback diode, and motor. **GPIO3 is a strapping pin**: do not add an external pull-up or drive it high during reset. Firmware drives it low at boot. No GPIO was remapped.

The speaker is the complete Adafruit STEMMA 3885 module. There are no SPK+/SPK− pads, MAX98357A, I2S clocks, or audio signals on D0/D3/D10. Current firmware uses 10-bit/62.5 kHz PWM on D9. Route GPIO8 through an audio low-pass filter before the STEMMA SIGNAL input; a direct PWM jumper is prototype-only. GPIO21 remains reserved for the unused Sense microSD CS; GPIO41/42 stay on the PDM microphone.

## Assembly and verification

Solder U1 and the six front-side passives first. Use the marked USB orientation and verify its castellated-pad alignment against the physical module before reflow. Attach the Sense expansion/camera as normal. Install optional 2.54 mm headers on the front or solder wires through the edge pads. Trim protruding leads and use an insulating sheet and a non-compressing spacer under the pouch. Do not place bare battery foil against solder joints.

The source and copper have passed KiCad ERC/DRC and netlist parity checks; see `outputs/erc.rpt`, `outputs/drc.rpt`, `outputs/drc.json`, and `outputs/validation.json`. `check_hub.py` independently compares every electrical pad to the exported schematic netlist, checks the fixed firmware GPIO mapping, resistor values, isolated SDO, power-net separation, and rear keepout. This is a design verification, not a physical prototype test.

Before powering the assembled board, check rail-to-ground resistance and power polarity; then verify 3V3, BAT_SENSE=BAT+/2, ladder voltages, PTT, speaker playback, and display operation. The battery's third lead and exact enclosure fit remain physical assembly checks.

## Files and reproduction

- `outputs/board-top.png`: KiCad bare-board render (U1 and optional headers are not modeled in 3D).
- `outputs/front.svg`, `back.svg`, `schematic.png`, `Gizmo_Hub.svg`: layout/schematic previews.
- `outputs/gerbers/`: copper, soldermask, silkscreen, outline, separate plated/nonplated drill files and drill maps. `Gizmo_Hub-fabrication.zip` contains the fabrication outputs. No fabrication order has been placed.
- `build_hub.py`: regenerates placement, libraries, and schematic; **resets routing**.
- `finish_hub.py`: imports `outputs/Gizmo_Hub.ses`, applies schematic net names, and fills both ground planes. Run after exporting the schematic XML netlist.
- `check_hub.py`: validates the finished board and writes `outputs/validation.json`.

Run the Python scripts with `C:/Program Files/KiCad/10.0/bin/python.exe`. The saved routing session was produced locally by Freerouting 1.9.0, single-threaded, analytics disabled, from `outputs/Gizmo_Hub.dsn`. Tool binaries are excluded from Git. To regenerate routing, supply that DSN to Freerouting and save the SES at the same path. Do not replace a hand-edited board by running the generator without preserving your edits.

## Sources

- [Seeed XIAO ESP32-S3 documentation and power-pin guidance](https://wiki.seeedstudio.com/xiao_esp32s3_getting_started/)
- [Seeed official XIAO footprints](https://files.seeedstudio.com/wiki/XIAO-KiCad-Library/New_XIAO_Series_Footprints.zip) — XIAO-ESP32-S3-SMD side-pad geometry; unused underside contacts omitted.
- [Akizuki MSP2807 datasheet](https://akizukidenshi.com/goodsaffix/msp2807.pdf) — connector order, voltage range, LED and SDO behavior.
- [Adafruit STEMMA Speaker pinout](https://learn.adafruit.com/adafruit-stemma-speaker/pinouts)
- Local `body/firmware/include/gizmo/board.h` and the user's confirmed wiring and battery dimensions.
