#include "gizmo/audio.h"
#include "gizmo/board.h"
#include "gizmo/settings.h"
#include "gizmo/pwm_audio.h"
#include <Arduino.h>
#include <driver/i2s.h>
#include <esp_heap_caps.h>
#ifdef ARDUINO
#include <driver/ledc.h>
#endif

namespace gizmo {
namespace {
constexpr i2s_port_t kMicPort = I2S_NUM_0;  // PDM RX/TX exist only on controller 0
constexpr i2s_port_t kAmpPort = I2S_NUM_1;  // host tests only; device speaker is LEDC PWM
constexpr int kDmaBuffers = 12;
constexpr int kDmaFrames = 256;
constexpr int32_t kMicGain = 3;
constexpr int kMaxChunksPerUpdate = 16;
constexpr uint32_t kVuDecayMs = 60;

#ifdef ARDUINO
// Exact XTAL divider: 40 MHz / (512 * 1.25) = 62.5 kHz. Two carrier
// periods per update avoid the former 39.0625 kHz vs 32 kHz clock mismatch.
// Keep XTAL as the LEDC source so the camera's separate timer is unaffected.
constexpr size_t kAmpRingSamples = kDmaBuffers * kDmaFrames;
constexpr uint8_t kPwmChannel = 4;  // LEDC_TIMER_2; camera XCLK keeps TIMER_0
constexpr uint8_t kPwmBits = 9;
constexpr uint32_t kPwmFreq = 62500;
constexpr uint32_t kPwmIdleDuty = 1u << (kPwmBits - 1);
constexpr uint8_t kPwmTimerIndex = 0;
constexpr uint16_t kPwmTimerDivider = 80;  // 80 MHz / 80 = 1 MHz
constexpr uint64_t kPwmTimerAlarm = 32;    // 1 MHz / 32 = 31.25 kHz ISR
static_assert(80000000ULL / kPwmTimerDivider / kPwmTimerAlarm == PwmClock::kOutputRate);
static_assert(kPwmFreq == PwmClock::kOutputRate * 2);
static_assert(Audio::kSampleRate * 125 == PwmClock::kOutputRate * 64);

portMUX_TYPE amp_mux = portMUX_INITIALIZER_UNLOCKED;
hw_timer_t* amp_timer = nullptr;
int16_t amp_ring[kAmpRingSamples];
volatile size_t amp_w = 0;
volatile size_t amp_r = 0;
volatile size_t amp_n = 0;
bool amp_running = false;
PwmAudio pwm_audio;
PwmClock pwm_clock;
int32_t mic_hp_x_ = 0;
int32_t mic_hp_y_ = 0;

void IRAM_ATTR amp_isr() {
  if (pwm_clock.advance()) {
    int16_t fetched = 0;
    bool available = false;
    portENTER_CRITICAL_ISR(&amp_mux);
    if (amp_n > 0) {
      fetched = amp_ring[amp_r];
      amp_r = (amp_r + 1) % kAmpRingSamples;
      --amp_n;
      available = true;
    }
    portEXIT_CRITICAL_ISR(&amp_mux);
    pwm_audio.midpoint(fetched, available);
  }
  const uint32_t duty = pwm_duty(pwm_clock.sample(pwm_audio.previous, pwm_audio.current));

  ledc_set_duty(LEDC_LOW_SPEED_MODE, static_cast<ledc_channel_t>(kPwmChannel), duty);
  ledc_update_duty(LEDC_LOW_SPEED_MODE, static_cast<ledc_channel_t>(kPwmChannel));
}

void amp_hold_low() {
  ledcDetachPin(board::amp_out);
  pinMode(board::amp_out, OUTPUT);
  digitalWrite(board::amp_out, LOW);
}

void reset_mic_filters() {
  mic_hp_x_ = mic_hp_y_ = 0;
}

int16_t condition_mic_sample(int16_t raw) {
  const int32_t x = raw;
  const int32_t hp = x - mic_hp_x_ + (mic_hp_y_ * 31) / 32;
  mic_hp_x_ = x;
  mic_hp_y_ = hp;
  int32_t value = hp * kMicGain;
  if (value > 32767) value = 32767;
  if (value < -32768) value = -32768;
  return static_cast<int16_t>(value);
}
#endif

esp_err_t amp_start() {
#ifdef ARDUINO
  if (amp_running) return ESP_OK;
  portENTER_CRITICAL(&amp_mux);
  amp_w = amp_r = amp_n = 0;
  portEXIT_CRITICAL(&amp_mux);
  pwm_audio = {};
  pwm_clock = {};
  const uint32_t actual_freq = ledcSetup(kPwmChannel, kPwmFreq, kPwmBits);
  if (actual_freq != kPwmFreq) {
    Serial.printf("speaker: expected %lu Hz PWM, got %lu\n",
                  static_cast<unsigned long>(kPwmFreq), static_cast<unsigned long>(actual_freq));
    return ESP_FAIL;
  }
  Serial.printf("speaker: PWM %lu Hz, %u-bit, updates %lu Hz\n",
                static_cast<unsigned long>(actual_freq), kPwmBits,
                static_cast<unsigned long>(PwmClock::kOutputRate));
  ledcAttachPin(board::amp_out, kPwmChannel);
  ledcWrite(kPwmChannel, kPwmIdleDuty);
  if (amp_timer == nullptr) {
    amp_timer = timerBegin(kPwmTimerIndex, kPwmTimerDivider, true);
    if (amp_timer == nullptr) {
      amp_hold_low();
      return ESP_FAIL;
    }
    timerAttachInterrupt(amp_timer, &amp_isr, true);
    timerAlarmWrite(amp_timer, kPwmTimerAlarm, true);
  }
  timerAlarmEnable(amp_timer);
  amp_running = true;
  return ESP_OK;
#else
  i2s_zero_dma_buffer(kAmpPort);
  return i2s_start(kAmpPort);
#endif
}

void amp_stop() {
#ifdef ARDUINO
  if (amp_timer != nullptr) timerAlarmDisable(amp_timer);
  portENTER_CRITICAL(&amp_mux);
  amp_w = amp_r = amp_n = 0;
  portEXIT_CRITICAL(&amp_mux);
  if (amp_running) {
    ledcWrite(kPwmChannel, 0);
    amp_hold_low();
  }
  amp_running = false;
#else
  i2s_zero_dma_buffer(kAmpPort);
  i2s_stop(kAmpPort);
#endif
}

void amp_clear() {
#ifdef ARDUINO
  if (amp_timer != nullptr) timerAlarmDisable(amp_timer);
  portENTER_CRITICAL(&amp_mux);
  amp_w = amp_r = amp_n = 0;
  portEXIT_CRITICAL(&amp_mux);
  pwm_audio = {};
  pwm_clock = {};
#else
  i2s_zero_dma_buffer(kAmpPort);
#endif
}

esp_err_t amp_write(const int16_t* samples, size_t count, size_t* written) {
#ifdef ARDUINO
  size_t n = 0;
  portENTER_CRITICAL(&amp_mux);
  while (n < count && amp_n < kAmpRingSamples) {
    amp_ring[amp_w] = samples[n++];
    amp_w = (amp_w + 1) % kAmpRingSamples;
    ++amp_n;
  }
  portEXIT_CRITICAL(&amp_mux);
  *written = n * sizeof(int16_t);
  return n < count ? ESP_ERR_TIMEOUT : ESP_OK;
#else
  return i2s_write(kAmpPort, samples, count * sizeof(int16_t), written, 0);
#endif
}

i2s_config_t base_config(i2s_mode_t mode, i2s_channel_fmt_t channels) {
  i2s_config_t config{};
  config.mode = mode;
  config.sample_rate = Audio::kSampleRate;
  config.bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT;
  config.channel_format = channels;
  config.communication_format = I2S_COMM_FORMAT_STAND_I2S;
  config.intr_alloc_flags = ESP_INTR_FLAG_LEVEL1;
  config.dma_buf_count = kDmaBuffers;
  config.dma_buf_len = kDmaFrames;
  config.use_apll = false;
  config.tx_desc_auto_clear = true;  // underrun plays silence, never stale data
  config.fixed_mclk = 0;
  config.mclk_multiple = I2S_MCLK_MULTIPLE_DEFAULT;
  config.bits_per_chan = I2S_BITS_PER_CHAN_DEFAULT;
  return config;
}
}  // namespace

esp_err_t Audio::install_mic() {
  const auto config = base_config(
      static_cast<i2s_mode_t>(I2S_MODE_MASTER | I2S_MODE_RX | I2S_MODE_PDM), I2S_CHANNEL_FMT_RIGHT_LEFT);
  esp_err_t result = i2s_driver_install(kMicPort, &config, 0, nullptr);
  if (result != ESP_OK) return result;
  i2s_pin_config_t pins{};
  pins.mck_io_num = I2S_PIN_NO_CHANGE;
  pins.bck_io_num = I2S_PIN_NO_CHANGE;
  pins.ws_io_num = board::microphone_clock;
  pins.data_out_num = I2S_PIN_NO_CHANGE;
  pins.data_in_num = board::microphone_data;
  result = i2s_set_pin(kMicPort, &pins);
  if (result != ESP_OK) return result;
  // IDF 4.4 PDM RX defaults to 8-sample downsample, which pitches recordings up.
  result = i2s_set_pdm_rx_down_sample(kMicPort, I2S_PDM_DSR_16S);
  if (result != ESP_OK) return result;
  result = i2s_set_clk(kMicPort, Audio::kSampleRate, I2S_BITS_PER_SAMPLE_16BIT, I2S_CHANNEL_STEREO);
  if (result != ESP_OK) return result;
  return i2s_stop(kMicPort);
}

esp_err_t Audio::install_amp() {
#ifdef ARDUINO
  amp_hold_low();
  return ESP_OK;
#else
  const auto config = base_config(
      static_cast<i2s_mode_t>(I2S_MODE_MASTER | I2S_MODE_TX), I2S_CHANNEL_FMT_ONLY_LEFT);
  esp_err_t result = i2s_driver_install(kAmpPort, &config, 0, nullptr);
  if (result != ESP_OK) return result;
  i2s_pin_config_t pins{};
  pins.mck_io_num = I2S_PIN_NO_CHANGE;
  pins.bck_io_num = I2S_PIN_NO_CHANGE;
  pins.ws_io_num = I2S_PIN_NO_CHANGE;
  pins.data_out_num = board::amp_out;
  pins.data_in_num = I2S_PIN_NO_CHANGE;
  result = i2s_set_pin(kAmpPort, &pins);
  if (result != ESP_OK) return result;
  i2s_zero_dma_buffer(kAmpPort);
  return i2s_stop(kAmpPort);
#endif
}

esp_err_t Audio::begin() {
  if (ready_) return ESP_OK;
  memo_capacity_ = static_cast<size_t>(kSampleRate) * kCapacitySeconds;
  memo_ = static_cast<int16_t*>(
      heap_caps_malloc(memo_capacity_ * sizeof(int16_t), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  if (memo_ == nullptr) return ESP_ERR_NO_MEM;
  live_cap_ = kLiveSamples;
  live_ = static_cast<int16_t*>(
      heap_caps_malloc(live_cap_ * sizeof(int16_t), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  if (live_ == nullptr) {
    live_ = static_cast<int16_t*>(heap_caps_malloc(live_cap_ * sizeof(int16_t), MALLOC_CAP_8BIT));
  }
  if (live_ == nullptr) return ESP_ERR_NO_MEM;
  esp_err_t result = install_mic();
  if (result != ESP_OK) return result;
  result = install_amp();
  if (result != ESP_OK) return result;
  ready_ = true;
  return ESP_OK;
}

void Audio::set_volume(uint8_t step, uint8_t steps) {
  volume_step_ = step;
  volume_steps_ = steps == 0 ? 10 : steps;
}

bool Audio::start_recording() {
  if (!ready_ || recording_) return false;
  if (playing_) stop_playback();
  memo_samples_ = 0;
  warmup_left_ = kWarmupSamples;
  peak_ = 0;
  vu_ = 0;
  capture_w_ = capture_r_ = capture_n_ = 0;
#ifdef ARDUINO
  reset_mic_filters();
#endif
  i2s_zero_dma_buffer(kMicPort);
  if (i2s_start(kMicPort) != ESP_OK) return false;
  recording_ = true;
  return true;
}

void Audio::stop_recording() {
  if (!recording_) return;
  pump_recording();  // take whatever DMA already captured
  recording_ = false;
  i2s_stop(kMicPort);
}

bool Audio::start_playback() {
  if (memo_samples_ == 0) return false;
  stop_live();
  return start_clip(memo_, memo_samples_);
}

bool Audio::start_clip(const int16_t* samples, size_t count) {
  if (!ready_ || samples == nullptr || count == 0) return false;
  if (recording_) stop_recording();
  stop_live();
  if (playing_) stop_playback();
  source_ = samples;
  source_samples_ = count;
  play_cursor_ = 0;
  draining_ = false;
  live_playing_ = false;
  live_armed_ = false;
  peak_ = 0;
  amp_clear();
  if (amp_start() != ESP_OK) return false;
  playing_ = true;
  pump_playback();  // prime the speaker ring before returning
  return true;
}

void Audio::stop_playback() {
  if (!playing_ && !live_playing_ && !live_armed_) return;
  playing_ = false;
  live_playing_ = false;
  live_armed_ = false;
  draining_ = false;
  source_ = nullptr;
  live_n_ = live_r_ = live_w_ = 0;
  amp_stop();
}

void Audio::stop_live() {
  if (!live_armed_ && !live_playing_ && live_n_ == 0) {
    live_n_ = live_r_ = live_w_ = 0;
    return;
  }
  stop_playback();
}

size_t Audio::take_capture(int16_t* dest, size_t cap) {
  if (dest == nullptr || cap == 0 || capture_n_ == 0) return 0;
  const size_t n = capture_len_[capture_r_];
  const size_t take = n < cap ? n : cap;
  for (size_t i = 0; i < take; ++i) dest[i] = capture_ring_[capture_r_][i];
  capture_r_ = static_cast<uint8_t>((capture_r_ + 1) % kCaptureRingChunks);
  --capture_n_;
  return take;
}

bool Audio::arm_live() {
  if (!ready_ || live_ == nullptr) return false;
  if (recording_) return false;
  if (playing_ && !live_playing_ && !live_armed_) stop_playback();
  if (live_armed_) return true;
  draining_ = false;
  peak_ = 0;
  source_ = nullptr;
  live_armed_ = true;
  // PWM stays off until pump_live sees samples (no idle carrier).
  return true;
}

size_t Audio::enqueue_live(const int16_t* samples, size_t count) {
  if (samples == nullptr || count == 0 || live_ == nullptr) return 0;
  if (recording_) return 0;
  if (!live_armed_ && !arm_live()) return 0;
  if (live_n_ == 0) live_wait_since_ = millis();
  size_t written = 0;
  while (written < count && live_n_ < live_cap_) {
    live_[live_w_] = samples[written++];
    live_w_ = (live_w_ + 1) % live_cap_;
    ++live_n_;
  }
  return written;
}

void Audio::track_level(const int16_t* samples, size_t count) {
  int16_t peak = 0;
  for (size_t i = 0; i < count; ++i) {
    const int16_t magnitude = samples[i] < 0 ? static_cast<int16_t>(-samples[i]) : samples[i];
    if (magnitude > peak) peak = magnitude;
  }
  peak_ = peak;
  int level = peak / 1600;  // ~16000 peak lights all ten pips
  if (level > 10) level = 10;
  if (level > vu_) {
    vu_ = static_cast<uint8_t>(level);
  }
}

void Audio::pump_recording() {
  int16_t pdm_stereo[kChunkSamples * 2];
  for (int chunk = 0; chunk < kMaxChunksPerUpdate && recording_; ++chunk) {
    size_t bytes = 0;
    if (i2s_read(kMicPort, pdm_stereo, sizeof(pdm_stereo), &bytes, 0) != ESP_OK || bytes == 0) return;
    size_t count = 0;
    if (bytes >= 4 && (bytes % 4) == 0) {
      const size_t frames = bytes / 4;
      int32_t energy_left = 0;
      int32_t energy_right = 0;
      const size_t probe = frames < 32 ? frames : 32;
      for (size_t i = 0; i < probe; ++i) {
        const int16_t left = pdm_stereo[i * 2];
        const int16_t right = pdm_stereo[i * 2 + 1];
        energy_left += left < 0 ? -left : left;
        energy_right += right < 0 ? -right : right;
      }
      const size_t channel = energy_right > energy_left * 2 ? 1 : 0;
      count = frames < kChunkSamples ? frames : kChunkSamples;
      for (size_t i = 0; i < count; ++i) chunk_[i] = pdm_stereo[i * 2 + channel];
    } else {
      count = bytes / sizeof(int16_t);
      if (count > kChunkSamples) count = kChunkSamples;
      for (size_t i = 0; i < count; ++i) chunk_[i] = pdm_stereo[i];
    }
    if (warmup_left_ > 0) {
      const size_t skip = count < warmup_left_ ? count : warmup_left_;
      warmup_left_ -= skip;
      for (size_t i = 0; i + skip < count; ++i) chunk_[i] = chunk_[i + skip];
      count -= skip;
    }
    for (size_t i = 0; i < count; ++i) {
#ifdef ARDUINO
      chunk_[i] = condition_mic_sample(chunk_[i]);
#else
      int32_t value = static_cast<int32_t>(chunk_[i]) * kMicGain;
      if (value > 32767) value = 32767;
      if (value < -32768) value = -32768;
      chunk_[i] = static_cast<int16_t>(value);
#endif
    }
    track_level(chunk_, count);
    if (capture_n_ < kCaptureRingChunks) {
      const size_t keep = count < kChunkSamples ? count : kChunkSamples;
      for (size_t i = 0; i < keep; ++i) capture_ring_[capture_w_][i] = chunk_[i];
      capture_len_[capture_w_] = static_cast<uint16_t>(keep);
      capture_w_ = static_cast<uint8_t>((capture_w_ + 1) % kCaptureRingChunks);
      ++capture_n_;
    }
    const size_t room = memo_capacity_ - memo_samples_;
    const size_t take = count < room ? count : room;
    for (size_t i = 0; i < take; ++i) memo_[memo_samples_ + i] = chunk_[i];
    memo_samples_ += take;
    if (memo_samples_ >= memo_capacity_) {
      recording_ = false;
      i2s_stop(kMicPort);
      return;
    }
    if (bytes < sizeof(pdm_stereo)) return;  // DMA drained for now
  }
}

void Audio::pump_playback() {
  if (live_armed_ || live_playing_ || live_n_ > 0) {
    pump_live();
    return;
  }
  if (draining_) {
    if (static_cast<int32_t>(millis() - drain_until_) >= 0) stop_playback();
    return;
  }
  for (int chunk = 0; chunk < kMaxChunksPerUpdate && playing_; ++chunk) {
    const size_t remaining = source_samples_ - play_cursor_;
    if (remaining == 0) {
      // Let I2S DMA finish the queued tail before cutting the bitstream.
      draining_ = true;
      drain_until_ = millis() + (kDmaBuffers * kDmaFrames * 1000UL) / kSampleRate + 10;
      return;
    }
    const size_t count = remaining < kChunkSamples ? remaining : kChunkSamples;
    for (size_t i = 0; i < count; ++i) chunk_[i] = source_[play_cursor_ + i];
    apply_volume(chunk_, count, volume_step_, volume_steps_);
    track_level(chunk_, count);
    size_t written = 0;
    if (amp_write(chunk_, count, &written) != ESP_OK && written == 0) return;
    play_cursor_ += written / sizeof(int16_t);
    if (written < count * sizeof(int16_t)) return;  // DMA full for now
  }
}

void Audio::pump_live() {
  if (live_n_ == 0) {
    // Empty software ring does not mean DMA has played its tail. Keep the
    // bitstream running for at least the DMA depth after the last write.
    if (live_playing_ && static_cast<int32_t>(millis() - live_drain_until_) >= 0) {
      amp_stop();
      live_playing_ = false;
      playing_ = false;
    }
    return;
  }
  if (!live_playing_) {
    // ~200 ms prebuffer so the first WS jitter does not underrun later.
    constexpr size_t kPrebuffer = kSampleRate / 5;
    if (live_n_ < kPrebuffer && millis() - live_wait_since_ < 250) return;
    amp_clear();
    if (amp_start() != ESP_OK) return;
    live_playing_ = true;
    playing_ = true;
  }
  for (int chunk = 0; chunk < kMaxChunksPerUpdate && live_n_ > 0; ++chunk) {
    const size_t count = live_n_ < kChunkSamples ? live_n_ : kChunkSamples;
    for (size_t i = 0; i < count; ++i) chunk_[i] = live_[(live_r_ + i) % live_cap_];
    apply_volume(chunk_, count, volume_step_, volume_steps_);
    size_t written = 0;
    const auto result = amp_write(chunk_, count, &written);
    const size_t consumed = written / sizeof(int16_t);
    live_r_ = (live_r_ + consumed) % live_cap_;
    live_n_ -= consumed;
    if (consumed) {
      track_level(chunk_, consumed);
      constexpr uint32_t drain_ms =
          (kDmaBuffers * kDmaFrames * 1000 + kSampleRate - 1) / kSampleRate + 2;
      // Keep the bitstream running across Gemini chunk gaps so the tail does
      // not restart the speaker (that restart is the late-reply “glitch”).
      live_drain_until_ = millis() + drain_ms + 300;
    }
    // A full ring can still have accepted half a chunk. Keep every unwritten
    // sample in the live ring, in its original (unscaled) form, for the next pump.
    if (result != ESP_OK || consumed < count) return;
  }
}

void Audio::update() {
  if (!ready_) return;
  if (recording_) pump_recording();
  if (playing_ || live_armed_ || live_n_ > 0) pump_playback();
  const uint32_t now = millis();
  if (now - last_vu_decay_ >= kVuDecayMs) {
    last_vu_decay_ = now;
    if (vu_ > 0) --vu_;
  }
}

float Audio::progress() const {
  if (source_samples_ == 0) return 0.0f;
  return static_cast<float>(play_cursor_) / static_cast<float>(source_samples_);
}

uint32_t Audio::memo_ms() const {
  return static_cast<uint32_t>((static_cast<uint64_t>(memo_samples_) * 1000ULL) / kSampleRate);
}

}  // namespace gizmo
