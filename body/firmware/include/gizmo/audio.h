#pragma once

#include <esp_err.h>
#include <stddef.h>
#include <stdint.h>

// Voice memo path: Sense PDM microphone (I2S_NUM_0) into a PSRAM buffer, out
// as 9-bit / 62.5 kHz LEDC PWM on D9 (Adafruit STEMMA analog IN). PDM TX is I2S0-only,
// so the speaker cannot share that peripheral with the mic. update() pumps
// samples from loop(). PWM stops when idle so D9 sits low.
namespace gizmo {

class Audio {
 public:
  static constexpr uint32_t kSampleRate = 16000;
  static constexpr uint32_t kCapacitySeconds = 20;

  esp_err_t begin();
  bool ready() const { return ready_; }

  bool start_recording();
  void stop_recording();
  bool recording() const { return recording_; }
  // Drain one mic chunk captured since the last take. Used to stream PTT to
  // Friend without replacing the local memo path (memo still fills).
  size_t take_capture(int16_t* dest, size_t cap);

  bool start_playback();  // the recorded memo
  // Any 16 kHz mono PCM16 clip that stays valid until playback ends (e.g. the
  // embedded boot chime). Interrupts a memo playback.
  bool start_clip(const int16_t* samples, size_t count);
  void stop_playback();
  bool playing() const { return playing_; }
  bool playing_memo() const { return playing_ && source_ == memo_ && !live_playing_; }
  bool live_playing() const { return live_playing_; }
  // Queue already-downsampled 16 kHz mono PCM16 (Friend wire is 24 kHz; the
  // body resamples before this). I2S clocks start only while the ring has
  // samples so idle D9 is quiet.
  size_t enqueue_live(const int16_t* samples, size_t count);
  void stop_live();
  size_t live_capacity_left() const { return live_cap_ - live_n_; }

  void set_volume(uint8_t step, uint8_t steps);
  void update();

  uint8_t vu_level() const { return vu_; }           // 0..10, decays when idle
  float progress() const;                             // playback 0..1
  uint32_t memo_ms() const;                           // recorded length
  uint32_t capacity_ms() const { return kCapacitySeconds * 1000; }
  bool has_memo() const { return memo_samples_ > 0; }
  void clear_memo() { memo_samples_ = 0; }
  int16_t last_peak() const { return peak_; }

 private:
  esp_err_t install_mic();
  esp_err_t install_amp();
  void pump_recording();
  void pump_playback();
  void pump_live();
  void track_level(const int16_t* samples, size_t count);
  bool arm_live();

  static constexpr size_t kChunkSamples = 256;
  static constexpr size_t kWarmupSamples = kSampleRate / 8;  // 125 ms discarded on record start
  static constexpr size_t kCaptureRingChunks = 8;
  static constexpr size_t kLiveSamples = kSampleRate * 3;  // 3 s inbound at 16 kHz

  bool ready_ = false;
  bool recording_ = false;
  bool playing_ = false;
  bool live_armed_ = false;    // accepting inbound PCM; speaker may be stopped
  bool live_playing_ = false;  // PWM running for live inbound audio
  bool draining_ = false;   // last samples queued, waiting for DMA to finish
  uint32_t drain_until_ = 0;
  int16_t* memo_ = nullptr;
  size_t memo_capacity_ = 0;
  size_t memo_samples_ = 0;
  const int16_t* source_ = nullptr;  // what is playing: memo_ or a clip
  size_t source_samples_ = 0;
  size_t play_cursor_ = 0;
  size_t warmup_left_ = 0;
  uint8_t volume_step_ = 8;
  uint8_t volume_steps_ = 10;
  uint8_t vu_ = 0;
  int16_t peak_ = 0;
  uint32_t last_vu_decay_ = 0;
  int16_t chunk_[kChunkSamples];

  int16_t capture_ring_[kCaptureRingChunks][kChunkSamples];
  uint16_t capture_len_[kCaptureRingChunks] = {};
  uint8_t capture_w_ = 0;
  uint8_t capture_r_ = 0;
  uint8_t capture_n_ = 0;

  int16_t* live_ = nullptr;
  size_t live_cap_ = 0;
  size_t live_w_ = 0;
  size_t live_r_ = 0;
  size_t live_n_ = 0;
  uint32_t live_wait_since_ = 0;
  uint32_t live_drain_until_ = 0;
};

}  // namespace gizmo
