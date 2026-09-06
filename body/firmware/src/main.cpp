#include <Arduino.h>
#include <Preferences.h>
#include <esp_heap_caps.h>
#include <sys/time.h>
#include <time.h>
#include "esp_jpg_decode.h"
#include "img_converters.h"
#include "gizmo/assets.h"
#include "gizmo/audio.h"
#include "gizmo/battery.h"
#include "gizmo/board.h"
#include "gizmo/camera.h"
#include "gizmo/display.h"
#include "gizmo/draw.h"
#include "gizmo/haptic.h"
#include "gizmo/input.h"
#include "gizmo/screens.h"
#include "gizmo/settings.h"

// Operating loop for the handheld. One cooperative loop() owns every
// peripheral; nothing blocks longer than a panel blit (~30 ms at 40 MHz).
namespace {

enum class State : uint8_t { kBoot, kIdle, kRecording, kPlayback, kSettings, kCamera };

const char* state_name(State state) {
  switch (state) {
    case State::kBoot: return "BOOT";
    case State::kIdle: return "IDLE";
    case State::kRecording: return "RECORDING";
    case State::kPlayback: return "PLAYBACK";
    case State::kSettings: return "SETTINGS";
    case State::kCamera: return "CAMERA";
  }
  return "?";
}

constexpr uint32_t kLiveRedrawMs = 80;    // VU / progress refresh cadence
constexpr uint32_t kIdleRedrawMs = 1000;  // HUD change check
constexpr time_t kEpochKnown = 1600000000;  // clock is hidden below this

gizmo::Camera camera;
gizmo::Display display;
gizmo::Audio audio;
gizmo::Battery battery;
gizmo::Haptic haptic;
gizmo::Input input;
Preferences prefs;

uint16_t* framebuffer = nullptr;
uint16_t* home_base = nullptr;  // decoded once, copied under every home screen
gizmo::draw::Canvas canvas;
gizmo::SettingsSnapshot settings;

State state = State::kBoot;
uint32_t state_since = 0;
uint32_t last_redraw = 0;
uint32_t record_started = 0;
int boot_slot_drawn = -1;
bool boot_chimed = false;
bool dirty = true;
bool audio_ok = false;
gizmo::Hud last_hud;
char time_entry[8];
uint8_t time_entry_len = 0;
bool time_entry_active = false;

// Camera bring-up counters (unchanged from the previous target).
uint32_t lastFrame = 0;
uint32_t frames = 0;
uint32_t lastReport = 0;
uint32_t failures = 0;
uint32_t blit_failures = 0;

const char* backlight_wiring() {
  return gizmo::board::display_bl < 0 ? "tied_3v3" : "gpio";
}

bool ensure_framebuffer() {
  if (framebuffer != nullptr) return true;
  const size_t bytes = static_cast<size_t>(gizmo::kSettingsWidth) * gizmo::kSettingsHeight * sizeof(uint16_t);
  framebuffer = static_cast<uint16_t*>(heap_caps_malloc(bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  if (framebuffer == nullptr) {
    framebuffer = static_cast<uint16_t*>(heap_caps_malloc(bytes, MALLOC_CAP_8BIT));
  }
  canvas.pixels = framebuffer;
  canvas.width = gizmo::kSettingsWidth;
  canvas.height = gizmo::kSettingsHeight;
  return framebuffer != nullptr;
}

bool ensure_home_base() {
  if (home_base != nullptr) return true;
  if (!ensure_framebuffer()) return false;
  const size_t bytes = static_cast<size_t>(canvas.width) * canvas.height * sizeof(uint16_t);
  home_base = static_cast<uint16_t*>(heap_caps_malloc(bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  if (home_base == nullptr) return false;
  const gizmo::draw::Canvas target{home_base, canvas.width, canvas.height};
  if (!gizmo::assets::decode_home_base(target)) {
    Serial.println("home base: jpeg decode failed");
    gizmo::draw::clear(target, gizmo::draw::kBlack);
  }
  return true;
}

gizmo::Hud current_hud() {
  gizmo::Hud hud;
  const time_t now = time(nullptr);
  if (now > kEpochKnown) {
    struct tm local;
    localtime_r(&now, &local);
    hud.has_time = true;
    hud.hour = local.tm_hour;
    hud.minute = local.tm_min;
  }
  // Hearts follow the LiPo reading. Without a divider wired the device is on
  // USB, shown as full like the simulator's default battery level.
  hud.half_steps = battery.present() ? (battery.percent() + 5) / 10 : gizmo::assets::kHalfSteps;
  return hud;
}

bool hud_changed(const gizmo::Hud& a, const gizmo::Hud& b) {
  return a.has_time != b.has_time || a.hour != b.hour || a.minute != b.minute || a.half_steps != b.half_steps;
}

void paint_home_base() {
  if (ensure_home_base()) {
    gizmo::draw::copy(canvas, home_base);
  } else {
    gizmo::draw::clear(canvas, gizmo::draw::kBlack);
  }
  last_hud = current_hud();
  gizmo::render_hud(canvas, last_hud);
}

void set_clock(int hour, int minute) {
  struct tm local{};
  local.tm_year = 2026 - 1900;  // date is irrelevant; only H:mm is shown
  local.tm_mon = 0;
  local.tm_mday = 1;
  local.tm_hour = hour;
  local.tm_min = minute;
  const time_t seconds = mktime(&local);
  struct timeval now{seconds, 0};
  settimeofday(&now, nullptr);
  dirty = true;
  Serial.printf("clock set to %d:%02d (serial; no RTC/NTP source yet)\n", hour, minute);
}

void apply_brightness() {
  // LED is tied to 3V3 on the current build, so there is no duty to drive.
  if (gizmo::board::display_bl >= 0) {
    ledcWrite(1, gizmo::backlight_duty(settings.brightness, settings.steps));
  }
}

void apply_volume() {
  audio.set_volume(settings.volume, settings.steps);
}

void save_settings() {
  prefs.putUChar("brightness", settings.brightness);
  prefs.putUChar("volume", settings.volume);
}

void load_settings() {
  prefs.begin("gizmo", false);
  settings.brightness = prefs.getUChar("brightness", 8);
  settings.volume = prefs.getUChar("volume", 6);
  settings.steps = 10;
  if (settings.brightness > settings.steps) settings.brightness = settings.steps;
  if (settings.volume > settings.steps) settings.volume = settings.steps;
}

void enter(State next) {
  if (state == next) return;
  Serial.printf("state %s -> %s\n", state_name(state), state_name(next));
  state = next;
  state_since = millis();
  dirty = true;
}

void render() {
  if (!ensure_framebuffer()) {
    Serial.println("render: no framebuffer");
    return;
  }
  const uint32_t now = millis();
  switch (state) {
    case State::kBoot: {
      // 24 slots at 125 ms: ten-slot drop, blink, wordmark held to 5050 ms.
      int slot = static_cast<int>((now - state_since) / gizmo::assets::kBootFramePeriodMs);
      if (slot >= gizmo::assets::kBootSlots) slot = gizmo::assets::kBootSlots - 1;
      if (slot == boot_slot_drawn) {
        dirty = false;
        return;
      }
      if (!gizmo::assets::decode_boot_slot(slot, canvas)) {
        Serial.printf("boot frame %d: jpeg decode failed\n", slot);
        gizmo::draw::clear(canvas, gizmo::draw::kBlack);
      }
      boot_slot_drawn = slot;
      break;
    }
    case State::kIdle:
      paint_home_base();
      break;
    case State::kRecording:
      paint_home_base();
      gizmo::render_recording_overlay(canvas, audio.vu_level(), now - record_started, audio.capacity_ms());
      break;
    case State::kPlayback:
      paint_home_base();
      gizmo::render_playback_overlay(canvas, audio.vu_level(), audio.progress(), audio.memo_ms());
      break;
    case State::kSettings:
      settings.open = true;
      gizmo::render_settings(framebuffer, canvas.width, canvas.height, settings);
      break;
    case State::kCamera:
      return;  // camera frames own the panel
  }
  display.blit_rgb565(framebuffer, canvas.width, canvas.height);
  last_redraw = now;
  dirty = false;
}

void start_recording() {
  if (!audio_ok) {
    Serial.println("ptt: audio not ready, recording skipped");
    return;
  }
  if (state == State::kCamera) return;
  if (audio.start_recording()) {
    record_started = millis();
    haptic.pulse(30);
    enter(State::kRecording);
  } else {
    Serial.println("ptt: start_recording failed");
  }
}

void finish_recording() {
  audio.stop_recording();
  Serial.printf("memo: %u ms, peak=%d\n", audio.memo_ms(), audio.last_peak());
  haptic.pulse(20);
  enter(State::kIdle);
}

void start_playback() {
  if (!audio.has_memo()) {
    Serial.println("select: no memo to play");
    return;
  }
  if (audio.start_playback()) {
    haptic.pulse(20);
    enter(State::kPlayback);
  } else {
    Serial.println("select: start_playback failed");
  }
}

void stop_playback() {
  audio.stop_playback();
  enter(State::kIdle);
}

void settings_button(gizmo::Button button) {
  using gizmo::Button;
  uint8_t& value = settings.focus == 0 ? settings.brightness : settings.volume;
  if (settings.adjusting) {
    if (button == Button::kUp && value < settings.steps) ++value;
    if (button == Button::kDown && value > 0) --value;
    if (button == Button::kSelect) {
      settings.adjusting = false;
      save_settings();
    }
    if (settings.focus == 0) apply_brightness(); else apply_volume();
    Serial.printf("settings: %s=%u\n", settings.focus == 0 ? "brightness" : "volume", value);
  } else {
    if (button == Button::kUp && settings.focus > 0) --settings.focus;
    if (button == Button::kDown) {
      if (settings.focus == 0) {
        settings.focus = 1;
      } else {
        settings.open = false;
        enter(State::kIdle);  // down past Volume returns home
        return;
      }
    }
    if (button == Button::kSelect) settings.adjusting = true;
  }
  dirty = true;
}

void on_button(const gizmo::InputEvent& event) {
  using gizmo::Button;
  Serial.printf("button %s %s%s\n", gizmo::button_name(event.button), event.pressed ? "down" : "up",
                event.repeat ? " (repeat)" : "");

  if (event.button == Button::kPtt) {
    if (state == State::kBoot) return;  // splash is not interruptible
    if (event.pressed && state != State::kRecording) {
      if (state == State::kPlayback) audio.stop_playback();
      if (state == State::kSettings) settings.open = false;
      start_recording();
    } else if (!event.pressed && state == State::kRecording) {
      finish_recording();
    }
    return;
  }

  if (!event.pressed) return;  // UP/DOWN/SELECT act on press and repeat
  if (state == State::kBoot || state == State::kRecording) return;
  if (!event.repeat) haptic.pulse(12);

  switch (state) {
    case State::kIdle:
      if (event.button == Button::kUp) {
        settings.focus = 0;
        settings.adjusting = false;
        enter(State::kSettings);
      } else if (event.button == Button::kSelect) {
        start_playback();
      }
      break;
    case State::kSettings:
      settings_button(event.button);
      break;
    case State::kPlayback:
      if (event.button == Button::kSelect) stop_playback();
      break;
    case State::kCamera:
      if (event.button == Button::kSelect) {
        Serial.printf("camera stop: %s\n", esp_err_to_name(camera.stop()));
        enter(State::kIdle);
      }
      break;
    default:
      break;
  }
}

void simulate(gizmo::Button button, bool pressed) {
  gizmo::InputEvent event;
  event.button = button;
  event.pressed = pressed;
  on_button(event);
}

// `t` followed by HH:MM and Enter sets the displayed clock.
bool collect_time(char value) {
  if (!time_entry_active) {
    if (value != 't') return false;
    time_entry_active = true;
    time_entry_len = 0;
    return true;
  }
  if (value == '\r' || value == '\n') {
    time_entry[time_entry_len] = '\0';
    time_entry_active = false;
    int hour = -1, minute = -1;
    if (sscanf(time_entry, "%d:%d", &hour, &minute) == 2 && hour >= 0 && hour < 24 && minute >= 0 && minute < 60) {
      set_clock(hour, minute);
    } else {
      Serial.println("clock: expected tHH:MM");
    }
    return true;
  }
  if (value == ' ') return true;
  if (time_entry_len < sizeof(time_entry) - 1) time_entry[time_entry_len++] = value;
  return true;
}

void command(char value) {
  using gizmo::Button;
  if (collect_time(value)) return;
  switch (value) {
    case 'c': {
      if (state == State::kRecording || state == State::kPlayback) {
        Serial.println("camera: busy with audio");
        return;
      }
      if (ensure_framebuffer()) {
        gizmo::render_camera_hint(canvas);
        display.blit_rgb565(framebuffer, canvas.width, canvas.height);
      }
      const auto result = camera.start();
      Serial.printf("camera start: %s\n", esp_err_to_name(result));
      if (result == ESP_OK) {
        const auto* sensor = esp_camera_sensor_get();
        Serial.printf("sensor PID=0x%04x; QVGA JPEG; PSRAM buffers\n", sensor->id.PID);
        frames = failures = blit_failures = 0;
        lastReport = millis();
        enter(State::kCamera);
      } else {
        dirty = true;
      }
      break;
    }
    case 'x':
      Serial.printf("camera stop: %s\n", esp_err_to_name(camera.stop()));
      if (state == State::kCamera) enter(State::kIdle);
      break;
    case 's':
      if (state == State::kIdle) {
        settings.focus = 0;
        settings.adjusting = false;
        enter(State::kSettings);
      }
      break;
    case 'h':
      if (state == State::kSettings) {
        settings.open = false;
        enter(State::kIdle);
      }
      break;
    case 'u': simulate(Button::kUp, true); simulate(Button::kUp, false); break;
    case 'd': simulate(Button::kDown, true); simulate(Button::kDown, false); break;
    case 'e': simulate(Button::kSelect, true); simulate(Button::kSelect, false); break;
    case 'p':
      simulate(Button::kPtt, state != State::kRecording);
      break;
    case 'v':
      haptic.pulse(60);
      Serial.println("haptic: 60 ms pulse");
      break;
    case 'g':
      // Screen grab: what the panel was last given, as raw RGB565 over USB.
      if (framebuffer != nullptr) {
        Serial.printf("FRAME %d %d\n", canvas.width, canvas.height);
        Serial.write(reinterpret_cast<const uint8_t*>(framebuffer),
                     static_cast<size_t>(canvas.width) * canvas.height * sizeof(uint16_t));
        Serial.println("\nENDFRAME");
      }
      break;
    case 'r': {
      const uint8_t next = display.rotation() == 1 ? 3 : 1;
      display.set_rotation(next);
      dirty = true;
      Serial.printf("display rotation=%u %dx%d\n", display.rotation(), display.width(), display.height());
      break;
    }
    case 'i':
      Serial.printf("inputs: ladder=%umV (%s) ptt=%s battery=%umV (%u%%%s)\n",
                    input.ladder_millivolts(), gizmo::button_name(input.ladder_button()),
                    input.held(Button::kPtt) ? "down" : "up",
                    battery.millivolts(), battery.percent(), battery.present() ? "" : ", unwired");
      break;
    case '?':
      Serial.printf("state=%s camera=%s audio=%s memo=%ums display=%s rotation=%u heap=%u psram_free=%u backlight=%s "
                    "brightness=%u volume=%u\n",
                    state_name(state), camera.running() ? "running" : "off",
                    audio_ok ? "ready" : "failed", audio.memo_ms(),
                    display.ready() ? "commands_sent" : "off", display.rotation(),
                    ESP.getFreeHeap(), ESP.getFreePsram(), backlight_wiring(),
                    settings.brightness, settings.volume);
      break;
    default:
      break;
  }
}

void camera_loop() {
  if (!camera.running() || millis() - lastFrame < 100) return;
  lastFrame = millis();
  auto* frame = camera.acquire();
  if (frame) {
    if (frame->format == PIXFORMAT_JPEG && frame->len > 0 && frame->len <= 128 * 1024) {
      ++frames;
      if (ensure_framebuffer() &&
          jpg2rgb565(frame->buf, frame->len, reinterpret_cast<uint8_t*>(framebuffer), JPG_SCALE_NONE)) {
        display.blit_rgb565(framebuffer, static_cast<int>(frame->width), static_cast<int>(frame->height));
      } else {
        ++blit_failures;
      }
    } else {
      ++failures;
    }
    camera.release();
  } else {
    ++failures;
  }
  if (millis() - lastReport >= 2000) {
    Serial.printf("frames=%u failures=%u blit_failures=%u heap=%u psram_free=%u\n",
                  frames, failures, blit_failures, ESP.getFreeHeap(), ESP.getFreePsram());
    lastReport = millis();
  }
}

}  // namespace

void setup() {
  // Hold the Sense microSD chip select HIGH before any SPI or I2S clock runs:
  // the slot shares SCK/MOSI with the panel and its MISO pad is the amp BCLK.
  pinMode(gizmo::board::sd_cs, OUTPUT);
  digitalWrite(gizmo::board::sd_cs, HIGH);
  haptic.begin();

  // Panel first: the 5.05 s boot flipbook starts before the USB wait so a
  // battery-powered boot is not delayed by a missing host.
  const auto panel = display.begin();
  state_since = millis();
  render();

  Serial.begin(115200);
  const auto started = millis();
  while (!Serial && millis() - started < 1500) {
    delay(10);
    render();  // keep the drop animating while waiting for the host
  }
  Serial.println("Gizmo / XIAO ESP32S3 Sense / terminal OS");
  Serial.printf("flash=%u psram=%u\n", ESP.getFlashChipSize(), ESP.getPsramSize());
  Serial.printf("display begin: %s ILI9341 %dx%d sck=%d mosi=%d cs=%d dc=%d rst=tied_3v3 bl=%s\n",
                esp_err_to_name(panel), display.width(), display.height(),
                gizmo::board::display_sck, gizmo::board::display_mosi,
                gizmo::board::display_cs, gizmo::board::display_dc, backlight_wiring());
  Serial.printf("assets: boot %d slots/%d frames @%ums, chime at %ums (%u samples @%uHz), splash %ums, hearts %dpx, clock atlas %dx%d\n",
                gizmo::assets::kBootSlots, gizmo::assets::kBootUniqueFrames, gizmo::assets::kBootFramePeriodMs,
                gizmo::assets::kBootChimeAtMs, static_cast<unsigned>(gizmo::assets::kChimeSamples),
                gizmo::assets::kChimeSampleRate, gizmo::assets::kBootMinimumMs, gizmo::assets::kHeartAssetSide,
                gizmo::assets::kClockAtlasWidth, gizmo::assets::kClockAtlasHeight);

  load_settings();
  if (gizmo::board::display_bl >= 0) {
    ledcSetup(1, 5000, 8);
    ledcAttachPin(gizmo::board::display_bl, 1);
  }
  input.begin();
  battery.begin();
  const auto sound = audio.begin();
  audio_ok = sound == ESP_OK;
  apply_volume();
  apply_brightness();
  Serial.printf("audio begin: %s mic=I2S0 PDM clk=%d data=%d amp=I2S1 bclk=%d lrc=%d din=%d %uHz memo=%us\n",
                esp_err_to_name(sound), gizmo::board::microphone_clock, gizmo::board::microphone_data,
                gizmo::board::amp_bclk, gizmo::board::amp_lrc, gizmo::board::amp_din,
                gizmo::Audio::kSampleRate, gizmo::Audio::kCapacitySeconds);
  Serial.printf("inputs: ptt=D1/GPIO%d ladder=D4/GPIO%d battery=D5/GPIO%d haptic=D2/GPIO%d sd_cs=GPIO%d held high\n",
                gizmo::board::ptt, gizmo::board::buttons_adc, gizmo::board::battery_adc,
                gizmo::board::haptic, gizmo::board::sd_cs);
  Serial.printf("settings: brightness=%u volume=%u (nvs)\n", settings.brightness, settings.volume);
  Serial.println("keys: u/d/e = up/down/select, p = PTT toggle, s = settings, h = home, v = haptic,");
  Serial.println("      tHH:MM<enter> = set clock, i = input voltages, c/x = camera, r = rotate, ? = status");
}

void loop() {
  while (Serial.available()) command(static_cast<char>(Serial.read()));

  gizmo::InputEvent event;
  while (input.poll(event)) on_button(event);

  audio.update();
  battery.update();
  haptic.update();

  const uint32_t now = millis();
  switch (state) {
    case State::kBoot:
      if (!boot_chimed && audio_ok && now - state_since >= gizmo::assets::kBootChimeAtMs) {
        boot_chimed = true;
        if (!audio.start_clip(gizmo::assets::chime(), gizmo::assets::kChimeSamples)) {
          Serial.println("boot chime: start failed");
        }
      }
      if (now - state_since >= gizmo::assets::kBootMinimumMs) {
        enter(State::kIdle);
      } else {
        dirty = true;  // render() only decodes when the slot advances
      }
      break;
    case State::kRecording:
      if (!audio.recording()) {
        Serial.println("memo: buffer full");
        finish_recording();
      } else if (now - last_redraw >= kLiveRedrawMs) {
        dirty = true;
      }
      break;
    case State::kPlayback:
      if (!audio.playing()) {
        Serial.println("playback: finished");
        enter(State::kIdle);
      } else if (now - last_redraw >= kLiveRedrawMs) {
        dirty = true;
      }
      break;
    case State::kIdle:
      if (now - last_redraw >= kIdleRedrawMs && hud_changed(current_hud(), last_hud)) dirty = true;
      break;
    case State::kCamera:
      camera_loop();
      break;
    case State::kSettings:
      break;
  }

  if (dirty && state != State::kCamera) render();
  delay(1);
}
