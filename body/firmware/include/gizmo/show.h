#pragma once
#include <atomic>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/semphr.h>
#include "gizmo/show_format.h"

namespace gizmo {
// Body loop owns playback and the display. Download and decode-ahead share the
// media core, but the next download waits for a decoded-frame cushion before
// competing with the clip on screen. friend-net stays higher so spoken PCM
// still wins the core.
//
// Two slots: the picture on the glass, and one held picture for a story cue
// that is fetched and indexed ahead of its words. "go" swaps the held slot in
// without a download in between, so the change lands on the sentence.
class ShowPlayer {
 public:
  void begin();
  void submit(const ShowRequest& request);
  void cancel(bool dismiss = true);
  void update();
  bool viewing() const { return request_.viewing; }
  bool available() const { return still_.bytes != nullptr; }
  bool motion_playing() const { return clip_.bytes != nullptr; }
  bool render(uint16_t* pixels, bool force = false);
  // Decodes under the chip-global gizmo::jpeg_lock (esp_jpg_decode is not
  // reentrant); the camera preview shares it through this entry point.
  bool decode_jpeg(const uint8_t* bytes, size_t length, uint16_t* pixels);
  bool take_glass_ready(GlassReady& ack);
  // Record the panel transfer that follows a successful render(). Together
  // with the decode and cadence counters this makes physical film timing
  // visible in serial logs instead of relying on subjective "choppy" reports.
  void note_display(uint32_t elapsed_us);
  void diagnose() const;
 private:
  struct Job { ShowRequest request; uint32_t revision; bool still; bool held; };
  struct Media {
    uint8_t* bytes = nullptr;
    size_t length = 0, count = 0;
    ShowFrame frames[kShowMaxFrames];
    uint32_t revision = 0;
    uint32_t cue = 0;
    bool motion = false;
    bool held = false;
    bool failed = false;
  };
  static void task(void* context);
  void run();
  static void decode_task(void* context);
  void decode_run();
  size_t decoded_headroom(bool& active);
  void wait_for_decode_headroom(const Job& job);
  bool download(const Job& job, bool motion, Media& media);
  void publish(Media& media);
  void release(Media& media);
  bool decode_media_frame(const Media& media, size_t index, uint16_t* pixels);
  void hold(const ShowRequest& request);
  bool swap_held(const ShowRequest& request);
  void drop_held();
  void ack(uint32_t cue, bool motion, bool ok);
  size_t motion_index(size_t count) const;
  void arm_clip();
  void note_presented(size_t index, size_t count);
  void report_perf(const char* reason);
  QueueHandle_t jobs_ = nullptr, held_jobs_ = nullptr, results_ = nullptr;
  SemaphoreHandle_t media_mux_ = nullptr;
  // Decoded-ahead ring for motion playback. A JPEG frame decode costs ~50 ms
  // on the body loop — over half the 83 ms frame budget — so a separate task
  // copies the next frames' JPEG bytes under media_mux_, decodes them into
  // these SPIRAM buffers, and render() becomes a memcpy. Buffers tagged with
  // the media generation they came from; a stale generation is skipped.
  // Ten slots is ~830 ms at 12 fps. Eight must be ready before a look-ahead
  // download competes for this core, which absorbs the measured ~900 ms local
  // cue transfer while decoding continues at reduced throughput.
  static constexpr int kDecBufs = 10;
  static constexpr size_t kDownloadHeadroom = 8;
  static constexpr size_t kDecScratch = 40 * 1024;
  static constexpr size_t kDecPixels = kShowWidth * kShowHeight * sizeof(uint16_t);
  uint16_t* dec_pixels_[kDecBufs] = {};
  uint8_t* dec_scratch_ = nullptr;
  std::atomic<uint32_t> media_gen_{0};
  std::atomic<int> dec_index_[kDecBufs];
  std::atomic<uint32_t> dec_gen_[kDecBufs];
  // Set when the decoder failed on this frame: render skips it (repeats the
  // previous frame) and the pipeline moves on instead of retrying forever.
  std::atomic<bool> dec_bad_[kDecBufs];
  std::atomic<int> dec_w_{0};
  std::atomic<uint32_t> revision_{0};
  std::atomic<uint32_t> held_revision_{0};
  ShowRequest request_;
  ShowRequest held_request_;
  char dismissed_[128] = "";
  Media still_, clip_;
  Media held_still_, held_clip_;
  static constexpr size_t kAckCap = 8;
  GlassReady acks_[kAckCap];
  size_t ack_r_ = 0, ack_w_ = 0;
  std::atomic<uint32_t> started_{0};
  int drawn_ = -1;
  bool changed_ = false;
  bool perf_active_ = false;
  uint32_t perf_cue_ = 0;
  uint32_t perf_started_ms_ = 0;
  uint32_t perf_last_presented_ms_ = 0;
  uint32_t perf_presented_ = 0;
  uint32_t perf_dropped_ = 0;
  uint32_t perf_repeats_ = 0;
  int perf_missed_index_ = -1;
  std::atomic<uint32_t> perf_decode_failed_{0};
  std::atomic<uint32_t> perf_decode_max_ms_{0};
  uint32_t perf_blit_max_us_ = 0;
  uint32_t perf_present_gap_max_ms_ = 0;
};
}
