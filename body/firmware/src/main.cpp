#include <Arduino.h>
#include <Preferences.h>
#include <esp_heap_caps.h>
#include <string.h>
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
#include "gizmo/friend.h"
#include "gizmo/haptic.h"
#include "gizmo/input.h"
#include "gizmo/screens.h"
#include "gizmo/settings.h"
#include "gizmo/show.h"
#include "gizmo/wifi.h"
#include "gizmo/wall_time.h"

// Operating loop for the handheld. One cooperative loop() owns every
// peripheral. Friend HTTP/TLS/WebSocket operations run in their own task.
namespace {

enum class State : uint8_t { kBoot, kIdle, kRecording, kPlayback, kSettings, kCamera };
enum class LineCmd : uint8_t { kNone, kTime, kUrl, kToken };

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
constexpr uint32_t kDoubleSelectMs = 320;  // matches the Mac simulator
constexpr time_t kEpochKnown = 1600000000;  // clock is hidden below this
static_assert(gizmo::kVolumeTickRate == gizmo::Audio::kSampleRate,
              "volume tick must match the device speaker rate");

gizmo::Camera camera;
gizmo::Display display;
gizmo::Audio audio;
gizmo::Battery battery;
gizmo::Haptic haptic;
gizmo::Input input;
gizmo::WifiLink wifi;
gizmo::FriendLink friend_link;
gizmo::ShowPlayer show_player;
Preferences prefs;

uint16_t* framebuffer = nullptr;
uint16_t* home_base = nullptr;  // decoded once, copied under every home screen
int home_slot_drawn = -1;
int home_set_drawn = -1;  // 0 = idle flipbook, 1 = listening lean
int settle_left = 0;      // lean slots still to unwind after the mic lets go
uint32_t settle_next = 0;
gizmo::draw::Canvas canvas;
gizmo::SettingsSnapshot settings;

State state = State::kBoot;
uint32_t state_since = 0;
uint32_t last_redraw = 0;
uint32_t record_started = 0;
char caption_line[160] = "";
int boot_slot_drawn = -1;
bool boot_chimed = false;
bool dirty = true;
bool audio_ok = false;
bool friend_ptt_ = false;
gizmo::Hud last_hud;
char line_buf[160];
uint8_t line_len = 0;
LineCmd line_cmd = LineCmd::kNone;
bool select_pending = false;
uint32_t select_armed_at = 0;
const char* camera_status = nullptr;
constexpr size_t kVisionMax = 48 * 1024;
uint8_t* vision_jpeg = nullptr;
size_t vision_jpeg_len = 0;
uint32_t last_vision_send = 0;
uint32_t last_camera_blit = 0;

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

int current_idle_slot() {
  return static_cast<int>((millis() / gizmo::assets::kIdleFramePeriodMs) % gizmo::assets::kIdleSlots);
}

int current_listening_slot() {
  return static_cast<int>((millis() / gizmo::assets::kListeningFramePeriodMs) % gizmo::assets::kListeningSlots);
}

int current_thinking_slot() {
  return static_cast<int>((millis() / gizmo::assets::kThinkingFramePeriodMs) % gizmo::assets::kThinkingSlots);
}

bool ensure_home_base() {
  int set;
  if (state == State::kRecording) set = 1;
  else if (friend_link.session_thinking()) set = 2;
  else set = 0;
  int slot;
  if (set == 1) { slot = current_listening_slot(); settle_left = 0; }
  else if (set == 2) slot = current_thinking_slot();
  else if (settle_left > 0) { set = 1; slot = settle_left; }
  else slot = current_idle_slot();
  if (home_base != nullptr && home_set_drawn == set && home_slot_drawn == slot) return true;
  if (!ensure_framebuffer()) return false;
  const size_t bytes = static_cast<size_t>(canvas.width) * canvas.height * sizeof(uint16_t);
  if (home_base == nullptr) {
    home_base = static_cast<uint16_t*>(heap_caps_malloc(bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    if (home_base == nullptr) return false;
  }
  const gizmo::draw::Canvas target{home_base, canvas.width, canvas.height};
  const bool ok = set == 1 ? gizmo::assets::decode_listening_slot(slot, target)
                  : set == 2 ? gizmo::assets::decode_thinking_slot(slot, target)
                             : gizmo::assets::decode_idle_slot(slot, target);
  if (!ok) {
    Serial.println("home base: jpeg decode failed");
    gizmo::draw::clear(target, gizmo::draw::kBlack);
  }
  home_set_drawn = set;
  home_slot_drawn = slot;
  return true;
}

gizmo::Hud current_hud() {
  gizmo::Hud hud;
  const time_t now = time(nullptr);
  if (gizmo::wall_time_ready() && now > kEpochKnown) {
    struct tm local;
    localtime_r(&now, &local);
    hud.has_time = true;
    hud.hour = local.tm_hour;
    hud.minute = local.tm_min;
  }
  // The battery icon follows the LiPo reading. Without a divider wired the
  // device is on USB, shown as full like the simulator's default battery level.
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

void paint_camera(bool viewfinder_ready, const char* status) {
  if (!ensure_framebuffer()) return;
  ensure_home_base();
  gizmo::render_camera_world(canvas, home_base, viewfinder_ready, status);
  display.blit_rgb565(framebuffer, canvas.width, canvas.height);
  last_redraw = millis();
  dirty = false;
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
  gizmo::note_wall_time();
  dirty = true;
  Serial.printf("clock set to %d:%02d (serial)\n", hour, minute);
}

void apply_brightness() {
  const uint8_t duty = gizmo::backlight_duty(settings.brightness, settings.steps);
  display.set_pixel_gain(duty);
  if (gizmo::board::display_bl >= 0) {
    ledcWrite(1, duty);
  }
}

void apply_volume() {
  audio.set_volume(settings.volume, settings.steps);
}

void play_volume_tick() {
  if (!audio_ok || audio.recording() || settings.volume == 0) return;
  // Hear the new step on an idle speaker. Do not cut Friend speech or a memo.
  if (audio.live_playing() || audio.playing_memo()) return;
  if (!audio.start_clip(gizmo::volume_tick(), gizmo::kVolumeTickSamples)) {
    Serial.println("settings: volume tick start failed");
  }
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
  if ((next == State::kSettings || next == State::kPlayback) && show_player.viewing()) {
    show_player.cancel();
    friend_link.send_select();
  }
  Serial.printf("state %s -> %s\n", state_name(state), state_name(next));
  state = next;
  state_since = millis();
  dirty = true;
}

void cancel_select() { select_pending = false; }

void offer_vision(bool force) {
  if (!friend_link.ready() || vision_jpeg == nullptr || vision_jpeg_len == 0) return;
  const uint32_t now = millis();
  const uint32_t gap = friend_ptt_ ? 400 : 900;
  if (!force && last_vision_send != 0 && now - last_vision_send < gap) return;
  if (friend_link.send_jpeg(vision_jpeg, vision_jpeg_len)) last_vision_send = now;
}

void enter_camera();
void leave_camera();
void start_recording();
void start_playback();
void stop_playback();
void finish_recording(bool replay);

void enter_camera() {
  if (state == State::kBoot || state == State::kRecording) return;
  if (show_player.viewing()) { show_player.cancel(); friend_link.send_select(); }
  if (state == State::kCamera && camera.running()) {
    Serial.println("camera: already open");
    return;
  }
  if (state == State::kPlayback) audio.stop_playback();
  if (state == State::kSettings) settings.open = false;
  cancel_select();
  camera_status = "CAMERA STARTING";
  paint_camera(false, camera_status);
  const auto result = camera.start();
  Serial.printf("camera start: %s\n", esp_err_to_name(result));
  if (result == ESP_OK) {
    const auto* sensor = esp_camera_sensor_get();
    if (sensor != nullptr) {
      Serial.printf("sensor PID=0x%04x; QVGA JPEG; PSRAM buffers; 78/22 camera world\n", sensor->id.PID);
    }
    frames = failures = blit_failures = 0;
    lastReport = millis();
    camera_status = nullptr;
  } else {
    camera_status = "CAMERA UNAVAILABLE";
    paint_camera(false, camera_status);
  }
  enter(State::kCamera);
}

void leave_camera() {
  if (state != State::kCamera) return;
  Serial.printf("camera stop: %s\n", esp_err_to_name(camera.stop()));
  camera_status = nullptr;
  cancel_select();
  enter(State::kIdle);
}

void render() {
  if (!ensure_framebuffer()) {
    Serial.println("render: no framebuffer");
    return;
  }
  const uint32_t now = millis();
  switch (state) {
    case State::kBoot: {
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
      if (wifi.card_visible()) {
        gizmo::render_wifi_setup(canvas, wifi.card_title(), wifi.card_line(), wifi.detail());
      }
      gizmo::render_caption(canvas, caption_line);
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
      paint_camera(false, camera_status ? camera_status : "CAMERA");
      return;
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
  if (audio.start_recording()) {
    record_started = millis();
    haptic.pulse(30);
    if (state != State::kCamera) enter(State::kRecording);
  } else {
    Serial.println("ptt: start_recording failed");
  }
}

void finish_recording(bool replay) {
  audio.stop_recording();
  Serial.printf("memo: %u ms, peak=%d\n", audio.memo_ms(), audio.last_peak());
  haptic.pulse(20);
  if (state != State::kRecording) return;
  if (replay) start_playback();
  if (state == State::kRecording) enter(State::kIdle);
}

void start_playback() {
  if (!audio.has_memo()) {
    Serial.println("playback: no memo to play");
    return;
  }
  if (audio.start_playback()) {
    haptic.pulse(20);
    enter(State::kPlayback);
  } else {
    Serial.println("playback: start failed");
  }
}

void stop_playback() {
  audio.stop_playback();
  enter(State::kIdle);
}

void pump_friend_audio() {
  int16_t buf[256];
  if (friend_link.take_barge_in()) audio.stop_live();
  while (true) {
    const size_t n = audio.take_capture(buf, 256);
    if (n == 0) break;
    if (friend_ptt_ && friend_link.ready()) friend_link.send_pcm16k(buf, n);
  }
  if (friend_ptt_) return;  // do not play inbound while holding PTT
  for (int i = 0; i < 24; ++i) {
    const size_t room = audio.live_capacity_left();
    if (room == 0 || audio.recording()) break;
    const size_t n = friend_link.take_speaker(buf, room < 256 ? room : 256);
    if (n == 0) break;
    audio.enqueue_live(buf, n);
  }
}

void settings_button(gizmo::Button button) {
  using gizmo::Button;
  uint8_t& value = settings.focus == 0 ? settings.brightness : settings.volume;
  if (settings.adjusting) {
    const uint8_t before = value;
    if (button == Button::kUp && value < settings.steps) ++value;
    if (button == Button::kDown && value > 0) --value;
    if (button == Button::kSelect) {
      settings.adjusting = false;
      save_settings();
    }
    if (settings.focus == 0) {
      apply_brightness();
    } else {
      apply_volume();
      if (value != before) play_volume_tick();
    }
    Serial.printf("settings: %s=%u%s\n", settings.focus == 0 ? "brightness" : "volume", value,
                  settings.focus == 0 ? " (pixel gain)" : "");
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

void resolve_single_select() {
  if (state == State::kCamera) {
    leave_camera();
    return;
  }
  if (state != State::kIdle) return;
  if (show_player.viewing()) {
    show_player.cancel();
    friend_link.send_select();
    dirty = true;
    return;
  }
  // Friend-online: Select is the interrupt/wake event, not local memo play.
  // Disconnected: keep the local memo path Woz verified on the amp.
  if (friend_link.ready()) {
    friend_link.send_select();
    return;
  }
  start_playback();
}

void on_button(const gizmo::InputEvent& event) {
  using gizmo::Button;
  Serial.printf("button %s %s%s\n", gizmo::button_name(event.button), event.pressed ? "down" : "up",
                event.repeat ? " (repeat)" : "");

  if (event.button == Button::kPtt) {
    if (state == State::kBoot) return;
    cancel_select();
    if (event.pressed && !audio.recording()) {
      if (state == State::kPlayback) audio.stop_playback();
      if (state == State::kSettings) settings.open = false;
      audio.stop_live();
      friend_link.interrupt_speaker();
      if (friend_link.ready()) {
        offer_vision(true);
        start_recording();
        if (audio.recording()) {
          friend_ptt_ = friend_link.send_ptt(true);
        }
      } else {
        friend_ptt_ = false;
        if (state == State::kCamera) leave_camera();
        start_recording();
      }
    } else if (!event.pressed && (audio.recording() || friend_ptt_)) {
      const bool replay = !friend_ptt_;
      audio.stop_recording();  // capture DMA tail before committing the turn
      if (friend_ptt_) {
        pump_friend_audio();
        friend_link.send_ptt(false);
        friend_ptt_ = false;
      }
      finish_recording(replay);
    }
    return;
  }

  if (!event.pressed || (event.button == Button::kSelect && event.repeat)) return;
  if (state == State::kBoot || state == State::kRecording) return;
  if (!event.repeat) haptic.pulse(12);

  switch (state) {
    case State::kIdle:
      if (event.button == Button::kUp) {
        cancel_select();
        settings.focus = 0;
        settings.adjusting = false;
        enter(State::kSettings);
      } else if (event.button == Button::kDown) {
        // Camera world is local. Do not forward this edge as Friend navigate.
        cancel_select();
        enter_camera();
      } else if (event.button == Button::kSelect) {
        if (select_pending && millis() - select_armed_at < kDoubleSelectMs) {
          cancel_select();
          enter_camera();
        } else {
          select_pending = true;
          select_armed_at = millis();
        }
      }
      break;
    case State::kSettings:
      cancel_select();
      settings_button(event.button);
      break;
    case State::kPlayback:
      cancel_select();
      if (event.button == Button::kSelect) stop_playback();
      break;
    case State::kCamera:
      if (event.button == Button::kUp) {
        leave_camera();
      } else if (event.button == Button::kDown) {
        // Consume. Camera rocker edges stay local.
      } else if (event.button == Button::kSelect) {
        if (select_pending && millis() - select_armed_at < kDoubleSelectMs) {
          cancel_select();
          leave_camera();
        } else {
          select_pending = true;
          select_armed_at = millis();
        }
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

bool collect_line(char value) {
  if (line_cmd == LineCmd::kNone) {
    if (value == 't') {
      line_cmd = LineCmd::kTime;
      line_len = 0;
      return true;
    }
    if (value == 'F') {
      line_cmd = LineCmd::kUrl;
      line_len = 0;
      return true;
    }
    if (value == 'K') {
      line_cmd = LineCmd::kToken;
      line_len = 0;
      return true;
    }
    return false;
  }
  if (value == '\r' || value == '\n') {
    line_buf[line_len] = '\0';
    const LineCmd cmd = line_cmd;
    line_cmd = LineCmd::kNone;
    if (cmd == LineCmd::kTime) {
      int hour = -1, minute = -1;
      if (sscanf(line_buf, "%d:%d", &hour, &minute) == 2 && hour >= 0 && hour < 24 && minute >= 0 &&
          minute < 60) {
        set_clock(hour, minute);
      } else {
        Serial.println("clock: expected tHH:MM");
      }
    } else if (cmd == LineCmd::kUrl) {
      friend_link.set_url(line_buf);
    } else if (cmd == LineCmd::kToken) {
      friend_link.set_token(line_buf);
    }
    return true;
  }
  if (value == ' ') {
    if (line_cmd == LineCmd::kTime) return true;
  }
  if (line_len < sizeof(line_buf) - 1) line_buf[line_len++] = value;
  return true;
}

void command(char value) {
  using gizmo::Button;
  if (collect_line(value)) return;
  switch (value) {
    case 'c':
      enter_camera();
      break;
    case 'x':
      if (state == State::kCamera) leave_camera();
      else Serial.printf("camera stop: %s\n", esp_err_to_name(camera.stop()));
      break;
    case 's':
      if (state == State::kIdle) {
        settings.focus = 0;
        settings.adjusting = false;
        enter(State::kSettings);
      }
      break;
    case 'h':
      if (show_player.viewing()) { show_player.cancel(); friend_link.send_select(); dirty = true; }
      if (state == State::kSettings) {
        settings.open = false;
        enter(State::kIdle);
      } else if (state == State::kCamera) {
        leave_camera();
      }
      break;
    case 'u': simulate(Button::kUp, true); simulate(Button::kUp, false); break;
    case 'd': simulate(Button::kDown, true); simulate(Button::kDown, false); break;
    case 'e': simulate(Button::kSelect, true); simulate(Button::kSelect, false); break;
    case 'p':
      simulate(Button::kPtt, !audio.recording());
      break;
    case 'v':
      haptic.pulse(60);
      Serial.println("haptic: 60 ms pulse");
      break;
    case 'g':
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
    case 'n':
      Serial.printf("wifi: %s ap=%s ssid=%s ip=%s %s\n", gizmo::wifi_phase_name(wifi.phase()), wifi.ap_ssid(),
                    wifi.sta_ssid(), wifi.ip().toString().c_str(), wifi.detail());
      break;
    case 'w':
      wifi.forget();
      dirty = true;
      Serial.println("wifi: setup AP reopened");
      break;
    case 'i':
      Serial.printf("inputs: ladder=%umV (%s) ptt=%s battery=%umV (%u%%%s)\n",
                    input.ladder_millivolts(), gizmo::button_name(input.ladder_button()),
                    input.held(Button::kPtt) ? "down" : "up",
                    battery.millivolts(), battery.percent(), battery.present() ? "" : ", unwired");
      break;
    case 'f':
      Serial.printf("friend: %s device=%s url=%s token=%s hello=%d %s\n",
                    gizmo::friend_phase_name(friend_link.phase()), friend_link.device_id(),
                    friend_link.brain_url()[0] ? friend_link.brain_url() : "(none)",
                    friend_link.has_token() ? "set" : "empty", friend_link.hello_ok() ? 1 : 0,
                    friend_link.detail());
      break;
    case '?':
      show_player.diagnose();
      Serial.printf("state=%s camera=%s audio=%s memo=%ums wifi=%s friend=%s display=%s rotation=%u heap=%u "
                    "psram_free=%u backlight=%s pixel_gain=%u brightness=%u volume=%u clock_wght=%d\n",
                    state_name(state), camera.running() ? "running" : "off",
                    audio_ok ? "ready" : "failed", audio.memo_ms(), gizmo::wifi_phase_name(wifi.phase()),
                    gizmo::friend_phase_name(friend_link.phase()),
                    display.ready() ? "commands_sent" : "off", display.rotation(),
                    ESP.getFreeHeap(), ESP.getFreePsram(), backlight_wiring(), display.pixel_gain(),
                    settings.brightness, settings.volume, gizmo::assets::kClockWeight);
      break;
    default:
      break;
  }
}

void camera_loop() {
  if (state != State::kCamera) return;
  if (!camera.running()) {
    if (dirty || millis() - last_redraw >= 400) paint_camera(false, camera_status);
    return;
  }
  if (millis() - lastFrame < 100) return;
  lastFrame = millis();
  auto* frame = camera.acquire();
  if (frame) {
    if (frame->format == PIXFORMAT_JPEG && frame->len > 0 && frame->len <= 128 * 1024) {
      ++frames;
      if (vision_jpeg != nullptr && frame->len <= kVisionMax) {
        memcpy(vision_jpeg, frame->buf, frame->len);
        vision_jpeg_len = frame->len;
        offer_vision(false);
      }
      const bool blit_now = !audio.live_playing() || millis() - last_camera_blit >= 250;
      if (blit_now && frame->width == gizmo::assets::kPanelWidth && frame->height == gizmo::assets::kPanelHeight &&
          ensure_framebuffer() &&
          jpg2rgb565(frame->buf, frame->len, reinterpret_cast<uint8_t*>(framebuffer), JPG_SCALE_NONE)) {
        camera_status = nullptr;
        paint_camera(true, nullptr);
        last_camera_blit = millis();
        if (frames == 1) Serial.printf("camera first JPEG: %ux%u, %u bytes\n", frame->width, frame->height, frame->len);
      } else if (!blit_now) {
        camera_status = nullptr;
      } else {
        ++blit_failures;
        camera_status = "CAMERA FRAME ERROR";
        paint_camera(false, camera_status);
      }
    } else {
      ++failures;
    }
    camera.release();
  } else {
    ++failures;
    camera_status = "CAMERA NO FRAMES";
    paint_camera(false, camera_status);
  }
  if (millis() - lastReport >= 2000) {
    Serial.printf("frames=%u failures=%u blit_failures=%u heap=%u psram_free=%u\n",
                  frames, failures, blit_failures, ESP.getFreeHeap(), ESP.getFreePsram());
    lastReport = millis();
  }
}

}  // namespace

void setup() {
  pinMode(gizmo::board::sd_cs, OUTPUT);
  digitalWrite(gizmo::board::sd_cs, HIGH);
  haptic.begin();

  const auto panel = display.begin();
  load_settings();
  if (gizmo::board::display_bl >= 0) {
    ledcSetup(1, 5000, 8);
    ledcAttachPin(gizmo::board::display_bl, 1);
  }
  apply_brightness();
  state_since = millis();
  render();

  Serial.begin(115200);
  const auto started = millis();
  while (!Serial && millis() - started < 1500) {
    delay(10);
  }
  Serial.println("Gizmo / XIAO ESP32S3 Sense / terminal OS");
  Serial.printf("flash=%u psram=%u\n", ESP.getFlashChipSize(), ESP.getPsramSize());
  Serial.printf("display begin: %s ILI9341 %dx%d sck=%d mosi=%d cs=%d dc=%d rst=tied_3v3 bl=%s pixel_gain=%u\n",
                esp_err_to_name(panel), display.width(), display.height(),
                gizmo::board::display_sck, gizmo::board::display_mosi,
                gizmo::board::display_cs, gizmo::board::display_dc, backlight_wiring(),
                display.pixel_gain());
  Serial.printf("assets: boot %d slots/%d frames @%ums, chime at %ums (%u samples @%uHz), splash %ums, "
                "clock atlas %dx%d wght=%d\n",
                gizmo::assets::kBootSlots, gizmo::assets::kBootUniqueFrames, gizmo::assets::kBootFramePeriodMs,
                gizmo::assets::kBootChimeAtMs, static_cast<unsigned>(gizmo::assets::kChimeSamples),
                gizmo::assets::kChimeSampleRate, gizmo::assets::kBootMinimumMs,
                gizmo::assets::kClockAtlasWidth, gizmo::assets::kClockAtlasHeight, gizmo::assets::kClockWeight);

  input.begin();
  battery.begin();
  const auto sound = audio.begin();
  audio_ok = sound == ESP_OK;
  apply_volume();
  Serial.printf("audio begin: %s mic=I2S0 PDM clk=%d data=%d speaker=D9/GPIO%d LEDC-PWM 9bit/62.5kHz device=%uHz memo=%us wire=%uHz\n",
                esp_err_to_name(sound), gizmo::board::microphone_clock, gizmo::board::microphone_data,
                gizmo::board::amp_out,
                gizmo::Audio::kSampleRate, gizmo::Audio::kCapacitySeconds, gizmo::FriendLink::kWireSampleRate);
  Serial.printf("inputs: ptt=D1/GPIO%d ladder=D4/GPIO%d battery=D5/GPIO%d haptic=D2/GPIO%d sd_cs=GPIO%d held high\n",
                gizmo::board::ptt, gizmo::board::buttons_adc, gizmo::board::battery_adc,
                gizmo::board::haptic, gizmo::board::sd_cs);
  Serial.printf("settings: brightness=%u volume=%u (nvs)\n", settings.brightness, settings.volume);
  wifi.begin();
  Serial.printf("wifi begin: %s ap=%s (plug the Sense U.FL antenna)\n", gizmo::wifi_phase_name(wifi.phase()),
                wifi.ap_ssid());
  friend_link.begin();
  show_player.begin();
  vision_jpeg = static_cast<uint8_t*>(heap_caps_malloc(kVisionMax, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  if (vision_jpeg == nullptr) vision_jpeg = static_cast<uint8_t*>(heap_caps_malloc(kVisionMax, MALLOC_CAP_8BIT));
  Serial.printf("vision jpeg buffer: %s\n", vision_jpeg ? "ready" : "unavailable");
  Serial.println("keys: u/d/e = up/down/select, p = PTT toggle, s = settings, h = home, v = haptic,");
  Serial.println("      tHH:MM<enter> = set clock, i = input voltages, n = wifi, w = forget wifi / reopen portal,");
  Serial.println("      F<url><enter> / K<token><enter> = Friend brain, f = friend status,");
  Serial.println("      d = camera (same as Down), c/x = camera start/stop, r = rotate, ? = status");
  // Boot clock starts here. A blocking Wi-Fi scan in setup() used to eat the
  // 5 s flipbook, so the eyes-between-hands frames never reached the panel.
  state_since = millis();
  boot_slot_drawn = -1;
  boot_chimed = false;
  dirty = true;
}

void loop() {
  while (Serial.available()) command(static_cast<char>(Serial.read()));

  gizmo::InputEvent event;
  while (input.poll(event)) on_button(event);

  if (select_pending && millis() - select_armed_at >= kDoubleSelectMs) {
    select_pending = false;
    resolve_single_select();
  }

  friend_link.update(wifi.online());
  const bool had_show = show_player.available();
  gizmo::ShowRequest show_request;
  if (friend_link.take_show(show_request)) {
    if (state == State::kSettings || state == State::kCamera || state == State::kPlayback) {
      // A held story cue is not a picture yet; only a real one is declined with Select.
      if (show_request.viewing && !show_request.hold) friend_link.send_select();
      show_player.cancel();
    } else {
      show_player.submit(show_request);
    }
  }
  show_player.update();
  if (friend_link.take_line(caption_line, sizeof(caption_line))) dirty = true;
  gizmo::GlassReady glass_ack;
  while (show_player.take_glass_ready(glass_ack)) friend_link.send_glass_ready(glass_ack);
  if (had_show != show_player.available()) dirty = true;
  audio.update();
  pump_friend_audio();
  // The memo limit also applies while the camera owns the visible state.
  if (friend_ptt_ && !audio.recording()) {
    friend_link.send_ptt(false);
    friend_ptt_ = false;
    finish_recording(false);
  }
  battery.update();
  haptic.update();
  const auto wifi_phase = wifi.phase();
  const bool wifi_card = wifi.card_visible();
  wifi.update();
  if (wifi.phase() != wifi_phase || wifi.card_visible() != wifi_card) dirty = true;

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
        wifi.start_portal_if_unconfigured();
      } else {
        dirty = true;
      }
      break;
    case State::kRecording:
      if (!audio.recording()) {
        Serial.println("memo: buffer full");
        const bool replay = !friend_ptt_;
        if (friend_ptt_) {
          friend_link.send_ptt(false);
          friend_ptt_ = false;
        }
        finish_recording(replay);
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
      if (wifi.card_visible()) {
        if (now - last_redraw >= 400) dirty = true;
      } else if (now - last_redraw >= kIdleRedrawMs && hud_changed(current_hud(), last_hud)) {
        dirty = true;
      }
      {
        const int active = friend_link.session_thinking() ? 2 : 0;
        if (home_set_drawn == 1 && active == 0) {
          // Settle: walk the lean back down one slot per period before the
          // idle blink takes the face back.
          if (settle_left == 0 && home_slot_drawn > 0) {
            settle_left = home_slot_drawn;
            settle_next = now + gizmo::assets::kListeningFramePeriodMs;
          }
          if (settle_left > 0) {
            if (now >= settle_next) {
              --settle_left;
              settle_next += gizmo::assets::kListeningFramePeriodMs;
              dirty = true;
            }
          } else dirty = true;
        } else {
          const int slot = active == 2 ? current_thinking_slot() : current_idle_slot();
          if (home_set_drawn != active || slot != home_slot_drawn) dirty = true;
        }
      }
      break;
    case State::kCamera:
      camera_loop();
      break;
    case State::kSettings:
      break;
  }

  if ((state == State::kIdle || state == State::kRecording) && show_player.available() && ensure_framebuffer()) {
    if (show_player.render(framebuffer, dirty)) {
      gizmo::render_caption(canvas, caption_line);
      display.blit_rgb565(framebuffer, canvas.width, canvas.height);
      last_redraw = now;
    }
    dirty = !show_player.available();
  } else if (dirty && state != State::kCamera) render();
  delay(1);
}
