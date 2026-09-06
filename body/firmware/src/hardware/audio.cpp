#include "gizmo/audio.h"
#include "gizmo/board.h"
#include "gizmo/settings.h"
#include <Arduino.h>
#include <driver/i2s.h>
#include <esp_heap_caps.h>

namespace gizmo {
namespace {
constexpr i2s_port_t kMicPort = I2S_NUM_0;  // PDM RX exists only on controller 0
constexpr i2s_port_t kAmpPort = I2S_NUM_1;
constexpr int kDmaBuffers = 8;
constexpr int kDmaFrames = 256;
// PDM output from the Sense microphone is quiet; a fixed digital gain keeps
// the memo audible without touching the amplifier's GAIN strap.
constexpr int32_t kMicGain = 4;
constexpr int kMaxChunksPerUpdate = 8;
constexpr uint32_t kVuDecayMs = 60;

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
      static_cast<i2s_mode_t>(I2S_MODE_MASTER | I2S_MODE_RX | I2S_MODE_PDM), I2S_CHANNEL_FMT_ONLY_LEFT);
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
  return i2s_stop(kMicPort);
}

esp_err_t Audio::install_amp() {
  const auto config = base_config(
      static_cast<i2s_mode_t>(I2S_MODE_MASTER | I2S_MODE_TX), I2S_CHANNEL_FMT_RIGHT_LEFT);
  esp_err_t result = i2s_driver_install(kAmpPort, &config, 0, nullptr);
  if (result != ESP_OK) return result;
  i2s_pin_config_t pins{};
  pins.mck_io_num = I2S_PIN_NO_CHANGE;
  pins.bck_io_num = board::amp_bclk;
  pins.ws_io_num = board::amp_lrc;
  pins.data_out_num = board::amp_din;
  pins.data_in_num = I2S_PIN_NO_CHANGE;
  result = i2s_set_pin(kAmpPort, &pins);
  if (result != ESP_OK) return result;
  i2s_zero_dma_buffer(kAmpPort);
  return i2s_stop(kAmpPort);  // no BCLK: MAX98357A sits in shutdown, no whine
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
  if (!set_amp_rate(kSampleRate)) return false;
  source_ = samples;
  source_samples_ = count;
  play_cursor_ = 0;
  draining_ = false;
  live_playing_ = false;
  peak_ = 0;
  i2s_zero_dma_buffer(kAmpPort);
  if (i2s_start(kAmpPort) != ESP_OK) return false;
  playing_ = true;
  pump_playback();  // prime the DMA ring before returning
  return true;
}

void Audio::stop_playback() {
  if (!playing_ && !live_playing_) return;
  playing_ = false;
  live_playing_ = false;
  draining_ = false;
  source_ = nullptr;
  live_n_ = live_r_ = live_w_ = 0;
  i2s_zero_dma_buffer(kAmpPort);
  i2s_stop(kAmpPort);
}

void Audio::stop_live() {
  if (!live_playing_ && live_n_ == 0) {
    live_n_ = live_r_ = live_w_ = 0;
    return;
  }
  stop_playback();
}

bool Audio::set_amp_rate(uint32_t hz) {
  if (hz == 0) return false;
  if (hz == amp_rate_) return true;
  const esp_err_t result = i2s_set_sample_rates(kAmpPort, hz);
  if (result != ESP_OK) {
    Serial.printf("audio: amp rate %u failed: %s\n", static_cast<unsigned>(hz), esp_err_to_name(result));
    return false;
  }
  amp_rate_ = hz;
  return true;
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

bool Audio::start_live() {
  if (!ready_ || live_ == nullptr) return false;
  if (recording_) return false;
  if (playing_ && !live_playing_) stop_playback();
  if (live_playing_) return true;
  if (!set_amp_rate(kWireSampleRate)) return false;
  draining_ = false;
  live_empty_since_ = millis();
  peak_ = 0;
  i2s_zero_dma_buffer(kAmpPort);
  if (i2s_start(kAmpPort) != ESP_OK) return false;
  live_playing_ = true;
  playing_ = true;
  source_ = nullptr;
  return true;
}

size_t Audio::enqueue_live(const int16_t* samples, size_t count) {
  if (samples == nullptr || count == 0 || live_ == nullptr) return 0;
  if (recording_) return 0;
  if (!live_playing_ && !start_live()) return 0;
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
  for (int chunk = 0; chunk < kMaxChunksPerUpdate && recording_; ++chunk) {
    size_t bytes = 0;
    if (i2s_read(kMicPort, chunk_, sizeof(chunk_), &bytes, 0) != ESP_OK || bytes == 0) return;
    size_t count = bytes / sizeof(int16_t);
    const int16_t* source = chunk_;
    if (warmup_left_ > 0) {
      const size_t skip = count < warmup_left_ ? count : warmup_left_;
      warmup_left_ -= skip;
      source += skip;
      count -= skip;
    }
    for (size_t i = 0; i < count; ++i) {
      int32_t value = static_cast<int32_t>(source[i]) * kMicGain;
      if (value > 32767) value = 32767;
      if (value < -32768) value = -32768;
      chunk_[i] = static_cast<int16_t>(value);
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
    if (bytes < sizeof(chunk_)) return;  // DMA drained for now
  }
}

void Audio::pump_playback() {
  if (live_playing_) {
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
      // Let the DMA ring finish the queued tail before cutting the clocks.
      draining_ = true;
      drain_until_ = millis() + (kDmaBuffers * kDmaFrames * 1000UL) / kSampleRate + 10;
      return;
    }
    const size_t count = remaining < kChunkSamples ? remaining : kChunkSamples;
    for (size_t i = 0; i < count; ++i) chunk_[i] = source_[play_cursor_ + i];
    apply_volume(chunk_, count, volume_step_, volume_steps_);
    track_level(chunk_, count);
    for (size_t i = 0; i < count; ++i) {
      stereo_[i * 2] = chunk_[i];
      stereo_[i * 2 + 1] = chunk_[i];
    }
    size_t written = 0;
    if (i2s_write(kAmpPort, stereo_, count * 2 * sizeof(int16_t), &written, 0) != ESP_OK) return;
    play_cursor_ += written / (2 * sizeof(int16_t));
    if (written < count * 2 * sizeof(int16_t)) return;  // DMA ring full for now
  }
}

void Audio::pump_live() {
  if (live_n_ == 0) {
    if (live_empty_since_ == 0) live_empty_since_ = millis();
    // Keep BCLK running briefly so a talk-turn gap does not pop; then drop clocks.
    if (millis() - live_empty_since_ >= 280) stop_live();
    return;
  }
  live_empty_since_ = 0;
  for (int chunk = 0; chunk < kMaxChunksPerUpdate && live_playing_ && live_n_ > 0; ++chunk) {
    const size_t count = live_n_ < kChunkSamples ? live_n_ : kChunkSamples;
    for (size_t i = 0; i < count; ++i) {
      chunk_[i] = live_[live_r_];
      live_r_ = (live_r_ + 1) % live_cap_;
    }
    live_n_ -= count;
    apply_volume(chunk_, count, volume_step_, volume_steps_);
    track_level(chunk_, count);
    for (size_t i = 0; i < count; ++i) {
      stereo_[i * 2] = chunk_[i];
      stereo_[i * 2 + 1] = chunk_[i];
    }
    size_t written = 0;
    if (i2s_write(kAmpPort, stereo_, count * 2 * sizeof(int16_t), &written, 0) != ESP_OK) return;
    const size_t consumed = written / (2 * sizeof(int16_t));
    if (consumed < count) {
      // Push unused samples back. Rare: DMA ring full.
      for (size_t i = count; i > consumed; --i) {
        live_r_ = (live_r_ + live_cap_ - 1) % live_cap_;
        ++live_n_;
      }
      return;
    }
  }
}

void Audio::update() {
  if (!ready_) return;
  if (recording_) pump_recording();
  if (playing_) pump_playback();
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
