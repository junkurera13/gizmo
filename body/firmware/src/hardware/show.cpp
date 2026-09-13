#include "gizmo/show.h"
#include "gizmo/jpeg_lock.h"
#include "gizmo/trust_roots.h"
#include <Arduino.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <esp_heap_caps.h>
#include <freertos/task.h>
#include <time.h>
#include "img_converters.h"

namespace gizmo {
void ShowPlayer::begin() {
  if (jobs_) return;
  jobs_ = xQueueCreate(1, sizeof(Job));
  held_jobs_ = xQueueCreate(1, sizeof(Job));
  results_ = xQueueCreate(4, sizeof(Media));
  media_mux_ = xSemaphoreCreateMutex();
  dec_scratch_ = static_cast<uint8_t*>(heap_caps_malloc(kDecScratch, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  for (int b = 0; b < kDecBufs; ++b) {
    dec_pixels_[b] =
        static_cast<uint16_t*>(heap_caps_malloc(kDecPixels, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    dec_index_[b].store(-1);
    dec_gen_[b].store(0);
    dec_bad_[b].store(false);
  }
  bool buffers_ok = media_mux_ != nullptr && dec_scratch_ != nullptr;
  for (int b = 0; b < kDecBufs; ++b) buffers_ok = buffers_ok && dec_pixels_[b] != nullptr;
  // Both media tasks pin to core 0: unpinned they float onto core 1 and
  // preempt loopTask — mid-boot that froze the flipbook; mid-film it stalls
  // the blit and the speaker pump. Decode outranks download because the cue on
  // screen has a 125 ms frame deadline; the next cue has almost five seconds
  // to finish its local/TLS transfer.
  if (!jobs_ || !held_jobs_ || !results_ ||
      xTaskCreatePinnedToCore(task, "show-download", 16384, this, 1, nullptr, 0) != pdPASS) {
    if (jobs_) vQueueDelete(jobs_);
    if (held_jobs_) vQueueDelete(held_jobs_);
    if (results_) vQueueDelete(results_);
    jobs_ = held_jobs_ = results_ = nullptr;
    Serial.println("show: download task unavailable");
  }
  // Decode-ahead pins to core 0 so JPEG work runs parallel to the body loop
  // instead of stealing the core that blits and pumps audio. Decode is 2,
  // download is 1, and friend-net remains 3 so live PCM always wins.
  if (!buffers_ok ||
      xTaskCreatePinnedToCore(decode_task, "show-decode", 24576, this, 2, nullptr, 0) != pdPASS) {
    Serial.println("show: decode-ahead unavailable; sync decoding only");
  }
}
void ShowPlayer::release(Media& media) { free(media.bytes); media = Media{}; }
size_t ShowPlayer::motion_index(size_t count) const {
  if (count == 0) return 0;
  const uint32_t origin = started_.load();
  if (origin == 0) return 0;
  return static_cast<size_t>((uint64_t(uint32_t(millis() - origin)) * kShowFps / 1000) % count);
}
void ShowPlayer::arm_clip() {
  report_perf("next");
  started_.store(0);
  drawn_ = -1;
  changed_ = true;
  perf_active_ = false;
  perf_cue_ = 0;
  perf_started_ms_ = 0;
  perf_last_presented_ms_ = 0;
  perf_presented_ = 0;
  perf_dropped_ = 0;
  perf_repeats_ = 0;
  perf_stalls_ = 0;
  perf_missed_index_ = -1;
  perf_decode_failed_.store(0);
  perf_decode_max_ms_.store(0);
  perf_blit_max_us_ = 0;
  perf_present_gap_max_ms_ = 0;
}
void ShowPlayer::note_presented(size_t index, size_t count) {
  const uint32_t now = millis();
  if (started_.load() == 0) {
    const uint32_t back = static_cast<uint32_t>(index * 1000 / kShowFps);
    uint32_t origin = now - back;
    if (origin == 0) origin = 1;
    started_.store(origin);
    perf_active_ = true;
    perf_cue_ = request_.cue;
    perf_started_ms_ = now;
    Serial.printf("show perf: start t=%lu cue=%lu fps=%d frames=%u psram_free=%u\n",
                  static_cast<unsigned long>(now), static_cast<unsigned long>(perf_cue_), kShowFps,
                  unsigned(count), unsigned(heap_caps_get_free_size(MALLOC_CAP_SPIRAM)));
  } else if (drawn_ >= 0 && count > 0) {
    const size_t distance = (index + count - static_cast<size_t>(drawn_)) % count;
    if (distance > 1) perf_dropped_ += static_cast<uint32_t>(distance - 1);
  }
  if (perf_last_presented_ms_ != 0) {
    const uint32_t gap = now - perf_last_presented_ms_;
    if (gap > perf_present_gap_max_ms_) perf_present_gap_max_ms_ = gap;
    if (gap >= kStallLogMs) {
      ++perf_stalls_;
      int ring = 0;
      if (count > 0) {
        for (int b = 0; b < kDecBufs; ++b) {
          if (dec_gen_[b].load() != media_gen_.load()) continue;
          const int slot = dec_index_[b].load();
          for (size_t a = 0; a < kDecAhead; ++a) {
            if (slot == int((index + a) % count)) { ++ring; break; }
          }
        }
      }
      const uint32_t last_commit = dec_last_commit_ms_.load();
      const uint8_t dl = downloading_.load();
      Serial.printf(
          "show stall: t=%lu cue=%lu index=%u gap_ms=%lu ring=%d/%d dec_idle_ms=%lu "
          "dec_busy=%d download=%s psram_free=%u\n",
          static_cast<unsigned long>(now), static_cast<unsigned long>(request_.cue),
          unsigned(index), static_cast<unsigned long>(gap), ring, int(kDecAhead),
          static_cast<unsigned long>(last_commit ? now - last_commit : 0),
          dec_in_flight_.load() ? 1 : 0,
          dl == 2 ? "motion" : dl == 1 ? "still" : "none",
          unsigned(heap_caps_get_free_size(MALLOC_CAP_SPIRAM)));
    }
  }
  perf_last_presented_ms_ = now;
  ++perf_presented_;
  perf_missed_index_ = -1;
}
void ShowPlayer::note_display(uint32_t elapsed_us) {
  if (perf_active_ && elapsed_us > perf_blit_max_us_) perf_blit_max_us_ = elapsed_us;
}
void ShowPlayer::report_perf(const char* reason) {
  if (!perf_active_) return;
  const uint32_t now = millis();
  Serial.printf(
      "show perf: end t=%lu cue=%lu reason=%s elapsed_ms=%lu presented=%lu dropped=%lu repeats=%lu "
      "decode_failed=%lu decode_max_ms=%lu blit_max_us=%lu present_gap_max_ms=%lu stalls=%lu psram_free=%u\n",
      static_cast<unsigned long>(now), static_cast<unsigned long>(perf_cue_), reason ? reason : "unknown",
      static_cast<unsigned long>(now - perf_started_ms_), static_cast<unsigned long>(perf_presented_),
      static_cast<unsigned long>(perf_dropped_), static_cast<unsigned long>(perf_repeats_),
      static_cast<unsigned long>(perf_decode_failed_.load()),
      static_cast<unsigned long>(perf_decode_max_ms_.load()), static_cast<unsigned long>(perf_blit_max_us_),
      static_cast<unsigned long>(perf_present_gap_max_ms_), static_cast<unsigned long>(perf_stalls_),
      unsigned(heap_caps_get_free_size(MALLOC_CAP_SPIRAM)));
  perf_active_ = false;
}
void ShowPlayer::cancel(bool dismiss) {
  if (dismiss && *request_.still) strlcpy(dismissed_, request_.still, sizeof(dismissed_));
  report_perf(dismiss ? "dismiss" : "clear");
  // Keep an explicit local dismissal across the server's clear acknowledgement
  // and reconnect. An already-queued old still must not revive that Show.
  ++revision_;
  request_ = ShowRequest{};
  if (media_mux_) xSemaphoreTake(media_mux_, portMAX_DELAY);
  media_gen_.store(next_gen());
  release(still_);
  release(clip_);
  if (media_mux_) xSemaphoreGive(media_mux_);
  // Clearing held_gen_ must precede the drain so a copied-but-not-started held
  // decode skips the decoder, same as the clip decodes the bump invalidated.
  drop_held();
  // esp_jpg_decode is chip-global and not reentrant. The generation bump makes
  // a copied-but-not-started decode skip inside the shared jpeg lock; this
  // drain waits out one already holding it, so no ShowPlayer decode outlives
  // cancel() into the camera's blit.
  jpeg_lock();
  jpeg_unlock();
  started_.store(0);
  drawn_ = -1;
  if (jobs_) xQueueReset(jobs_);
  ack_r_ = ack_w_ = 0;
}
void ShowPlayer::drop_held() {
  ++held_revision_;
  held_request_ = ShowRequest{};
  if (media_mux_) xSemaphoreTake(media_mux_, portMAX_DELAY);
  held_gen_.store(0);
  release(held_still_);
  release(held_clip_);
  if (media_mux_) xSemaphoreGive(media_mux_);
  if (held_jobs_) xQueueReset(held_jobs_);
}
void ShowPlayer::ack(uint32_t cue, bool motion, bool ok) {
  if (cue == 0) return;
  if ((ack_w_ + 1) % kAckCap == ack_r_) ack_r_ = (ack_r_ + 1) % kAckCap;  // oldest ack falls off
  acks_[ack_w_] = GlassReady{cue, motion, ok};
  ack_w_ = (ack_w_ + 1) % kAckCap;
}
bool ShowPlayer::take_glass_ready(GlassReady& out) {
  if (ack_r_ == ack_w_) return false;
  out = acks_[ack_r_];
  ack_r_ = (ack_r_ + 1) % kAckCap;
  return true;
}
void ShowPlayer::hold(const ShowRequest& r) {
  const bool same = held_request_.cue == r.cue && !strcmp(held_request_.still, r.still) &&
                    !strcmp(held_request_.base, r.base) && !strcmp(held_request_.device, r.device) &&
                    !strcmp(held_request_.token, r.token);
  if (same && !strcmp(held_request_.frames, r.frames)) return;
  if (!same) {
    // A new held cue replaces the old one. If the old cue already went, a clip
    // still downloading for it may finish and join the glass; otherwise it is moot.
    if (held_request_.cue != request_.cue) ++held_revision_;
    if (media_mux_) xSemaphoreTake(media_mux_, portMAX_DELAY);
    held_gen_.store(0);
    release(held_still_);
    release(held_clip_);
    if (media_mux_) xSemaphoreGive(media_mux_);
    if (held_jobs_) xQueueReset(held_jobs_);
  }
  held_request_ = r;
  Job job{r, held_revision_.load(), !held_still_.bytes, true};
  xQueueOverwrite(held_jobs_, &job);
}
bool ShowPlayer::swap_held(const ShowRequest& r) {
  // The clip alone satisfies the swap: the still URL serves the clip's first
  // frame, so the poster materializes from it when the still has not landed.
  if (!r.cue || r.cue != held_request_.cue || (!held_still_.bytes && !held_clip_.bytes) ||
      strcmp(held_request_.still, r.still)) return false;
  ++revision_;  // whatever was downloading for the old picture is moot
  if (jobs_) xQueueReset(jobs_);
  if (media_mux_) xSemaphoreTake(media_mux_, portMAX_DELAY);
  // Adopt the held clip's generation: the decode-ahead ring may already carry
  // its first frames under that tag, and they stay presentable after the swap.
  const uint32_t hg = held_gen_.exchange(0);
  media_gen_.store(hg ? hg : next_gen());
  release(still_);
  release(clip_);
  still_ = held_still_;
  clip_ = held_clip_;
  held_still_ = Media{};
  held_clip_ = Media{};
  if (!still_.bytes && clip_.bytes && clip_.count > 0) {
    const ShowFrame& first = clip_.frames[0];
    if (first.length > 0 && first.offset + first.length <= clip_.length) {
      auto* copy = static_cast<uint8_t*>(heap_caps_malloc(first.length, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
      if (copy) {
        memcpy(copy, clip_.bytes + first.offset, first.length);
        still_.bytes = copy;
        still_.length = first.length;
        still_.count = 1;
        still_.frames[0] = ShowFrame{0, first.length};
        still_.revision = clip_.revision;
        still_.cue = clip_.cue;
        still_.held = true;
      }
    }
  }
  if (media_mux_) xSemaphoreGive(media_mux_);
  int predecoded = 0;
  for (int b = 0; b < kDecBufs; ++b) {
    if (dec_gen_[b].load() == media_gen_.load()) ++predecoded;
  }
  Serial.printf("show: swap cue=%lu predecoded=%d\n", static_cast<unsigned long>(r.cue), predecoded);
  request_ = r;
  request_.hold = false;
  request_.go = false;
  // A held clip still downloading for this cue is adopted when it lands
  // (update() routes held results by cue), so the held revision stays valid
  // until another cue replaces it.
  held_request_ = ShowRequest{};
  held_request_.cue = r.cue;  // remember which cue the in-flight held job belongs to
  strlcpy(held_request_.still, r.still, sizeof(held_request_.still));
  arm_clip();
  return true;
}
void ShowPlayer::submit(const ShowRequest& r) {
  if (!r.viewing) { cancel(false); return; }
  if (!jobs_ || !show_path(r.still, r.device, ".jpg") || !strcmp(r.still, dismissed_)) return;
  if (*r.frames && (!show_path(r.frames, r.device, ".mjpeg") || !show_same(r.still, r.frames))) return;
  if (r.cue && r.hold) { hold(r); return; }
  if (!r.cue) drop_held();  // a conversation picture supersedes a held story cue
  if (r.go && swap_held(r)) {
    if (*r.frames && !clip_.bytes && uxQueueMessagesWaiting(held_jobs_) == 0) {
      // The go carried frames the hold did not have yet. Fetch them as a held
      // job so a clip already in flight for this cue and this one both land here.
      Job job{request_, held_revision_.load(), false, true};
      xQueueOverwrite(held_jobs_, &job);
    }
    return;
  }
  const bool same = !strcmp(request_.still, r.still) && !strcmp(request_.base, r.base) &&
                    !strcmp(request_.device, r.device) && !strcmp(request_.token, r.token);
  if (same && !strcmp(request_.frames, r.frames)) return;
  const uint32_t revision = ++revision_;
  if (!same) {
    if (media_mux_) xSemaphoreTake(media_mux_, portMAX_DELAY);
    media_gen_.store(next_gen());
    release(still_);
    release(clip_);
    if (media_mux_) xSemaphoreGive(media_mux_);
    drawn_ = -1;
  }
  request_ = r;
  request_.hold = false;
  request_.go = false;
  Job job{request_, revision, !still_.bytes, false};
  xQueueOverwrite(jobs_, &job);
}
void ShowPlayer::update() {
  if (!results_) return;
  Media media;
  while (xQueueReceive(results_, &media, 0) == pdTRUE) {
    if (media.failed) {
      if (media.held && media.revision == held_revision_.load()) ack(media.cue, media.motion, false);
      continue;
    }
    if (media.held) {
      if (media.revision != held_revision_.load()) { release(media); continue; }
      if (request_.viewing && request_.cue && media.cue == request_.cue) {
        // This cue already went; its late clip (or still) joins the picture on
        // the glass. Only a clip re-arms: bumping media_gen_ for a still would
        // retire every decoded frame mid-cue and arm_clip would restart the
        // playhead — a still is just the poster behind the motion.
        if (media_mux_) xSemaphoreTake(media_mux_, portMAX_DELAY);
        if (media.motion) media_gen_.store(next_gen());
        Media& target = media.motion ? clip_ : still_;
        release(target);
        target = media;
        if (media_mux_) xSemaphoreGive(media_mux_);
        if (media.motion) arm_clip();
      } else if (media.cue == held_request_.cue) {
        // The decode task reads held_clip_ under this same mutex.
        if (media_mux_) xSemaphoreTake(media_mux_, portMAX_DELAY);
        Media& target = media.motion ? held_clip_ : held_still_;
        release(target);
        target = media;
        if (media.motion) held_gen_.store(next_gen());
        if (media_mux_) xSemaphoreGive(media_mux_);
      } else {
        release(media);
        continue;
      }
      ack(media.cue, media.motion, true);
      Serial.printf("show: held %s cue=%lu frames=%u bytes=%u\n", media.motion ? "motion" : "still",
                    static_cast<unsigned long>(media.cue), unsigned(media.count), unsigned(media.length));
      continue;
    }
    if (media.revision != revision_.load() || !request_.viewing) { release(media); continue; }
    if (media_mux_) xSemaphoreTake(media_mux_, portMAX_DELAY);
    media_gen_.store(next_gen());
    Media& target = media.motion ? clip_ : still_;
    release(target);
    target = media;
    if (media_mux_) xSemaphoreGive(media_mux_);
    arm_clip();
    Serial.printf("show: ready %s frames=%u bytes=%u 320x240 fps=%d\n",
                  media.motion ? "motion" : "still", unsigned(media.count), unsigned(media.length), kShowFps);
  }
}
bool ShowPlayer::decode_jpeg(const uint8_t* bytes, size_t length, uint16_t* pixels) {
  return jpeg_decode_locked(bytes, length, pixels);
}
bool ShowPlayer::decode_media_frame(const Media& media, size_t index, uint16_t* pixels) {
  if (!pixels) return false;
  // media then jpeg: the decode task copies under media_mux_ and only then
  // takes jpeg_mux_, so this order cannot deadlock with decode_run().
  if (media_mux_) xSemaphoreTake(media_mux_, portMAX_DELAY);
  bool ok = false;
  if (media.bytes && media.count > 0 && index < media.count) {
    const ShowFrame frame = media.frames[index];
    if (frame.length > 0 && frame.offset + frame.length <= media.length) {
      ok = decode_jpeg(media.bytes + frame.offset, frame.length, pixels);
    }
  }
  if (media_mux_) xSemaphoreGive(media_mux_);
  return ok;
}
bool ShowPlayer::render(uint16_t* pixels, bool force) {
  if (!pixels || !available()) return false;
  const bool have_clip = clip_.bytes != nullptr && clip_.count > 0;
  Media& media = have_clip ? clip_ : still_;
  if (!media.bytes || media.count == 0) return false;
  const size_t index = media.motion ? motion_index(media.count) : 0;
  if (!force && !changed_ && drawn_ == int(index)) return false;
  if (media.motion) {
    const uint32_t gen = media_gen_.load();
    auto present = [&](size_t idx) -> bool {
      for (int b = 0; b < kDecBufs; ++b) {
        if (dec_index_[b].load() == int(idx) && dec_gen_[b].load() == gen &&
            !dec_bad_[b].load() && dec_pixels_[b]) {
          memcpy(pixels, dec_pixels_[b], kDecPixels);
          note_presented(idx, media.count);
          drawn_ = int(idx);
          changed_ = false;
          return true;
        }
      }
      return false;
    };
    if (present(index)) return true;
    bool current_bad = false;
    for (int b = 0; b < kDecBufs; ++b) {
      if (dec_index_[b].load() == int(index) && dec_gen_[b].load() == gen && dec_bad_[b].load()) {
        current_bad = true;
      }
    }
    // Clock has not started, or this JPEG is corrupt: take the next good ring
    // slot so a bad frame cannot freeze the playhead.
    if (started_.load() == 0 || current_bad) {
      for (size_t ahead = 1; ahead < kDecBufs && ahead < media.count; ++ahead) {
        if (present((index + ahead) % media.count)) return true;
      }
    }
    if (perf_active_ && perf_missed_index_ != static_cast<int>(index)) {
      ++perf_repeats_;
      perf_missed_index_ = static_cast<int>(index);
    }
    // Never decode motion on the body loop: a ~60 ms inline decode starves the
    // speaker pump and lands the blit mid-scan. Repeat the last frame until the
    // decode-ahead ring catches up (a failed frame is skipped via dec_bad_).
    return false;
  }
  if (decode_media_frame(media, index, pixels)) {
    drawn_ = int(index);
    changed_ = false;
    return true;
  }
  Serial.println("show: JPEG decode failed; returning home");
  cancel();
  return false;
}
void ShowPlayer::diagnose() const {
  Serial.printf("show: viewing=%d still=%u clip=%u frames=%u held_cue=%lu held_still=%u held_clip=%u fps=%d free_psram=%u\n",
                viewing(), unsigned(still_.length), unsigned(clip_.length), unsigned(clip_.count),
                static_cast<unsigned long>(held_request_.cue), unsigned(held_still_.length), unsigned(held_clip_.length),
                kShowFps, unsigned(heap_caps_get_free_size(MALLOC_CAP_SPIRAM)));
  if (perf_active_) {
    Serial.printf(
        "show perf: active t=%lu cue=%lu elapsed_ms=%lu presented=%lu dropped=%lu repeats=%lu "
        "decode_failed=%lu decode_max_ms=%lu blit_max_us=%lu present_gap_max_ms=%lu\n",
        static_cast<unsigned long>(millis()), static_cast<unsigned long>(perf_cue_),
        static_cast<unsigned long>(millis() - perf_started_ms_), static_cast<unsigned long>(perf_presented_),
        static_cast<unsigned long>(perf_dropped_), static_cast<unsigned long>(perf_repeats_),
        static_cast<unsigned long>(perf_decode_failed_.load()),
        static_cast<unsigned long>(perf_decode_max_ms_.load()), static_cast<unsigned long>(perf_blit_max_us_),
        static_cast<unsigned long>(perf_present_gap_max_ms_));
  }
}
void ShowPlayer::task(void* context) { static_cast<ShowPlayer*>(context)->run(); }
void ShowPlayer::publish(Media& media) {
  const std::atomic<uint32_t>& current = media.held ? held_revision_ : revision_;
  while (media.revision == current.load()) {
    if (xQueueSend(results_, &media, 0) == pdTRUE) { media.bytes = nullptr; return; }
    vTaskDelay(pdMS_TO_TICKS(5));
  }
  release(media);
}
bool ShowPlayer::download(const Job& job, bool motion, Media& media) {
  const std::atomic<uint32_t>& current = job.held ? held_revision_ : revision_;
  const uint32_t download_started = millis();
  if (job.revision != current.load()) return false;
  const ShowRequest& r = job.request;
  const char* path = motion ? r.frames : r.still;
  if (!show_path(path, r.device, motion ? ".mjpeg" : ".jpg")) return false;
  const bool secure = strncmp(r.base, "https://", 8) == 0;
  if (!secure && strncmp(r.base, "http://", 7)) return false;
  if (secure && time(nullptr) < 1735689600) return false;
  char origin[160];
  strlcpy(origin, r.base, sizeof(origin));
  if (char* slash = strchr(origin + (secure ? 8 : 7), '/')) *slash = '\0';
  char url[336];
  if (motion) {
    snprintf(url, sizeof(url), "%s%s?w=%d&h=%d&fps=%d", origin, path,
             kShowWidth, kShowHeight, kShowFps);
  } else {
    snprintf(url, sizeof(url), "%s%s?w=%d&h=%d", origin, path, kShowWidth, kShowHeight);
  }
  // Kept-alive sockets: a held cue's still and motion (and the next cue) reuse
  // one TLS session. A fresh handshake on this chip costs more than the file.
  static WiFiClientSecure tls;
  static WiFiClient plain;
  static HTTPClient http;
  static char open_origin[160] = "";
  if (strcmp(open_origin, origin) != 0) {
    http.end();
    tls.stop();
    plain.stop();
    open_origin[0] = '\0';
  }
  tls.setCACert(kFriendRootCAs);
  http.setConnectTimeout(2500);
  // Server may need to build its first MJPEG cache. Only this media task waits.
  http.setTimeout(35000);
  http.setFollowRedirects(HTTPC_DISABLE_FOLLOW_REDIRECTS);
  http.setReuse(true);
  const char* keys[] = {"Content-Type", "X-Gizmo-Frame-Count", "X-Gizmo-Frame-Rate",
                        "X-Gizmo-Frame-Width", "X-Gizmo-Frame-Height"};
  downloading_.store(motion ? 2 : 1);
  int status = -1;
  for (int attempt = 0; attempt < 2; ++attempt) {
    if (!(secure ? http.begin(tls, url) : http.begin(plain, url))) break;
    http.collectHeaders(keys, 5);
    http.addHeader("X-Gizmo-Device", r.device);
    if (*r.token) { char auth[104]; snprintf(auth, sizeof(auth), "Bearer %s", r.token); http.addHeader("Authorization", auth); }
    status = http.GET();
    if (status >= 0) break;
    // A kept-alive socket may have been reset mid-idle: drop it and retry fresh.
    http.end();
    tls.stop();
    plain.stop();
    open_origin[0] = '\0';
  }
  if (status < 0) { downloading_.store(0); return false; }
  const int length = http.getSize();
  const int count = motion ? http.header("X-Gizmo-Frame-Count").toInt() : 1;
  const size_t limit = motion ? kShowMaxBytes : kShowMaxStillBytes;
  bool ok = job.revision == current.load() && status == 200 && length > 0 && size_t(length) <= limit &&
            count > 0 && size_t(count) <= kShowMaxFrames &&
            http.header("Content-Type") == (motion ? "video/x-motion-jpeg" : "image/jpeg");
  if (motion) ok = ok && http.header("X-Gizmo-Frame-Rate").toInt() == kShowFps &&
                         http.header("X-Gizmo-Frame-Width").toInt() == kShowWidth &&
                         http.header("X-Gizmo-Frame-Height").toInt() == kShowHeight;
  if (ok) {
    // Never consume internal RAM for a clip; audio/network need that heap.
    media.bytes = static_cast<uint8_t*>(heap_caps_malloc(length, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    ok = media.bytes != nullptr;
  }
  size_t received = 0;
  const uint32_t started = millis();
  uint32_t progress = started;
  auto* stream = http.getStreamPtr();
  while (ok && received < size_t(length)) {
    if (job.revision != current.load() || uint32_t(millis() - started) > 30000 ||
        uint32_t(millis() - progress) > 12000) { ok = false; break; }
    const int available = stream->available();
    if (available > 0) {
      const size_t chunk = min(size_t(4096), min(size_t(available), size_t(length) - received));
      const int read = stream->read(media.bytes + received, chunk);
      if (read <= 0) { ok = false; break; }
      received += size_t(read);
      progress = millis();
    } else if (!http.connected()) { ok = false; break; }
    else vTaskDelay(1);
  }
  http.end();
  downloading_.store(0);
  // Reuse the socket only after a clean fetch; a torn connection reopens.
  if (ok) strlcpy(open_origin, origin, sizeof(open_origin));
  else open_origin[0] = '\0';
  ok = ok && received == size_t(length) && show_index(media.bytes, received, media.frames, count);
  if (!ok) {
    release(media);
    Serial.printf("show: %s unavailable (http=%d length=%d got=%u count=%d); retaining current picture\n",
                  motion ? "motion" : "still", status, length, unsigned(received), count);
    return false;
  }
  media.length = received;
  media.count = count;
  media.motion = motion;
  media.revision = job.revision;
  media.cue = job.request.cue;
  media.held = job.held;
  Serial.printf("show download: t=%lu cue=%lu kind=%s ms=%lu bytes=%u frames=%u psram_free=%u\n",
                static_cast<unsigned long>(millis()), static_cast<unsigned long>(media.cue),
                motion ? "motion" : "still", static_cast<unsigned long>(millis() - download_started),
                unsigned(media.length), unsigned(media.count),
                unsigned(heap_caps_get_free_size(MALLOC_CAP_SPIRAM)));
  return true;
}
void ShowPlayer::run() {
  for (;;) {
    Job job;
    // A film cue is time-critical (its segment plays next); a conversational
    // picture can wait. Held first so a slow ambient still never delays a cue.
    if (xQueueReceive(held_jobs_, &job, 0) == pdTRUE || xQueueReceive(jobs_, &job, 0) == pdTRUE) {
      Media media;
      auto failed_media = [&](bool motion) {
        Media failed;
        failed.failed = true; failed.held = true; failed.motion = motion;
        failed.cue = job.request.cue; failed.revision = job.revision;
        publish(failed);
      };
      if (job.held) {
        // A film cue's go is gated on the motion ack, and a landed clip
        // pre-decodes under the held generation while the current cue plays —
        // fetch the motion first so its opening frames exist seconds before
        // go instead of after the still's slower fetch. The still is now only
        // the fallback poster: swap_held materializes it from the clip's first
        // frame, which is the same JPEG the still URL serves.
        bool have_motion = false;
        if (*job.request.frames) {
          if (download(job, true, media)) { publish(media); have_motion = true; }
          else failed_media(true);
        }
        if (job.still && !have_motion) {
          if (download(job, false, media)) publish(media);
          else failed_media(false);
        }
      } else {
        bool still_ok = !job.still;
        if (job.still) {
          if (download(job, false, media)) { publish(media); still_ok = true; }
        }
        if (still_ok && *job.request.frames) {
          if (download(job, true, media)) publish(media);
        }
      }
    }
    vTaskDelay(pdMS_TO_TICKS(5));
  }
}
void ShowPlayer::decode_task(void* context) { static_cast<ShowPlayer*>(context)->decode_run(); }
void ShowPlayer::decode_run() {
  for (;;) {
    size_t target = 0;
    size_t length = 0;
    size_t index = 0;
    size_t count = 0;
    uint32_t gen = 0;
    uint32_t cur = 0;
    bool have = false;
    bool held_job = false;
    if (media_mux_ != nullptr && xSemaphoreTake(media_mux_, portMAX_DELAY) == pdTRUE) {
      Media& media = clip_;
      if (media.motion && media.bytes != nullptr && media.count > 0 && dec_scratch_ != nullptr) {
        index = motion_index(media.count);
        count = media.count;
        gen = media_gen_.load();
        // Earliest of the next few frames not already decoded for this media.
        for (size_t ahead = 0; ahead < kDecAhead && !have; ++ahead) {
          const size_t t = (index + ahead) % media.count;
          bool decoded = false;
          for (int b = 0; b < kDecBufs; ++b) {
            if (dec_gen_[b].load() == gen && dec_index_[b].load() == int(t)) decoded = true;
          }
          if (decoded) continue;
          const ShowFrame& frame = media.frames[t];
          if (frame.length <= kDecScratch) {
            memcpy(dec_scratch_, media.bytes + frame.offset, frame.length);
            target = t;
            length = frame.length;
            have = true;
          }
          break;
        }
      }
      cur = media_gen_.load();
      // The held cue's first frames decode ahead under the held generation
      // while the current clip plays, so "go" presents them with no stall.
      const uint32_t hg = held_gen_.load();
      if (!have && held_clip_.motion && held_clip_.bytes != nullptr && held_clip_.count > 0 &&
          dec_scratch_ != nullptr && hg != 0) {
        for (size_t t = 0; t < kHeldAhead && t < held_clip_.count; ++t) {
          bool decoded = false;
          for (int b = 0; b < kDecBufs; ++b) {
            if (dec_gen_[b].load() == hg && dec_index_[b].load() == int(t)) decoded = true;
          }
          if (decoded) continue;
          const ShowFrame& frame = held_clip_.frames[t];
          if (frame.length <= kDecScratch) {
            memcpy(dec_scratch_, held_clip_.bytes + frame.offset, frame.length);
            target = t;
            length = frame.length;
            gen = hg;
            have = true;
            held_job = true;
          }
          break;
        }
      }
      xSemaphoreGive(media_mux_);
    }
    if (!have) {
      vTaskDelay(pdMS_TO_TICKS(10));
      continue;
    }
    // Write into a buffer that isn't holding a frame either live generation
    // still needs. A never-committed slot (generation 0) is always free.
    const uint32_t hg = held_gen_.load();
    int w = -1;
    for (int b = 0; b < kDecBufs && w < 0; ++b) {
      const uint32_t slot_gen = dec_gen_[b].load();
      if (slot_gen == 0 || (slot_gen != cur && slot_gen != hg)) w = b;  // stale media: free to reuse
    }
    if (w < 0 && count > 0) {
      for (int b = 0; b < kDecBufs && w < 0; ++b) {
        if (dec_gen_[b].load() != cur) continue;
        const int slot = dec_index_[b].load();
        bool wanted = false;
        for (size_t a = 0; a < kDecAhead; ++a) {
          if (slot == int((index + a) % count)) wanted = true;
        }
        if (!wanted) w = b;  // behind the playhead: free to reuse
      }
    }
    if (w < 0) {
      if (held_job) {
        // Every slot is a held frame or one the playing clip wants: a
        // pre-decode must not evict the live window. Retry next round.
        vTaskDelay(pdMS_TO_TICKS(10));
        continue;
      }
      for (int tries = 0; tries < kDecBufs && w < 0; ++tries) {
        const int candidate = dec_w_.fetch_add(1) % kDecBufs;
        if (dec_gen_[candidate].load() != hg) w = candidate;
      }
      if (w < 0) w = dec_w_.fetch_add(1) % kDecBufs;
    }
    bool ok = false;
    bool attempted = false;
    const uint32_t decode_started = millis();
    dec_in_flight_.store(true);
    jpeg_lock();
    // Re-check under the lock: cancel() bumps the generation and drains this
    // lock, so a frame copied before the bump must skip the decoder here —
    // taking the lock itself is not proof the media is still current.
    if ((media_gen_.load() == gen || held_gen_.load() == gen) && dec_pixels_[w] != nullptr) {
      attempted = true;
      ok = jpg2rgb565(dec_scratch_, length, reinterpret_cast<uint8_t*>(dec_pixels_[w]), JPG_SCALE_NONE);
    }
    jpeg_unlock();
    dec_in_flight_.store(false);
    const uint32_t decode_ms = millis() - decode_started;
    // A generation can change while an old decode drains. Never attribute
    // that cancelled work to the next cue's physical-performance report.
    if (attempted && media_gen_.load() == gen) {
      uint32_t previous_max = perf_decode_max_ms_.load();
      while (decode_ms > previous_max &&
             !perf_decode_max_ms_.compare_exchange_weak(previous_max, decode_ms)) {}
      if (!ok) perf_decode_failed_.fetch_add(1);
    }
    // Publish bad-flag, index, then generation last (the commit point). A
    // failed frame is marked bad so the playhead skips it — the pipeline must
    // advance, not retry the same corrupt frame forever.
    dec_bad_[w].store(!ok);
    dec_index_[w].store(static_cast<int>(target));
    dec_gen_[w].store(gen);
    dec_last_commit_ms_.store(millis());
    // One tick every JPEG. pdMS_TO_TICKS(1) is 0 at Arduino's 100 Hz tick, so
    // the old every-fourth-frame yield never left the core. During a film,
    // friend-net (prio 3) and this task (prio 2) then occupied CPU 0 for the
    // length of the clip and IDLE0 never ran — TWDT abort, CPU 0: show-decode.
    vTaskDelay(1);
  }
}
}
