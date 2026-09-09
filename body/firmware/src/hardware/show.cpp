#include "gizmo/show.h"
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
  jobs_ = xQueueCreate(1, sizeof(Job));
  held_jobs_ = xQueueCreate(1, sizeof(Job));
  results_ = xQueueCreate(4, sizeof(Media));
  if (!jobs_ || !held_jobs_ || !results_ || xTaskCreate(task, "show-download", 16384, this, 1, nullptr) != pdPASS) {
    if (jobs_) vQueueDelete(jobs_);
    if (held_jobs_) vQueueDelete(held_jobs_);
    if (results_) vQueueDelete(results_);
    jobs_ = held_jobs_ = results_ = nullptr;
    Serial.println("show: download task unavailable");
  }
}
void ShowPlayer::release(Media& media) { free(media.bytes); media = Media{}; }
void ShowPlayer::cancel(bool dismiss) {
  if (dismiss && *request_.still) strlcpy(dismissed_, request_.still, sizeof(dismissed_));
  // Keep an explicit local dismissal across the server's clear acknowledgement
  // and reconnect. An already-queued old still must not revive that Show.
  ++revision_;
  request_ = ShowRequest{};
  release(still_);
  release(clip_);
  drawn_ = -1;
  if (jobs_) xQueueReset(jobs_);
  drop_held();
  ack_r_ = ack_w_ = 0;
}
void ShowPlayer::drop_held() {
  ++held_revision_;
  held_request_ = ShowRequest{};
  release(held_still_);
  release(held_clip_);
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
    release(held_still_);
    release(held_clip_);
    if (held_jobs_) xQueueReset(held_jobs_);
  }
  held_request_ = r;
  Job job{r, held_revision_.load(), !held_still_.bytes, true};
  xQueueOverwrite(held_jobs_, &job);
}
bool ShowPlayer::swap_held(const ShowRequest& r) {
  if (!r.cue || r.cue != held_request_.cue || !held_still_.bytes || strcmp(held_request_.still, r.still)) return false;
  ++revision_;  // whatever was downloading for the old picture is moot
  if (jobs_) xQueueReset(jobs_);
  release(still_);
  release(clip_);
  still_ = held_still_;
  clip_ = held_clip_;
  held_still_ = Media{};
  held_clip_ = Media{};
  request_ = r;
  request_.hold = false;
  request_.go = false;
  // A held clip still downloading for this cue is adopted when it lands
  // (update() routes held results by cue), so the held revision stays valid
  // until another cue replaces it.
  held_request_ = ShowRequest{};
  held_request_.cue = r.cue;  // remember which cue the in-flight held job belongs to
  strlcpy(held_request_.still, r.still, sizeof(held_request_.still));
  started_ = millis();
  drawn_ = -1;
  changed_ = true;
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
  if (!same) { release(still_); release(clip_); drawn_ = -1; }
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
        // This cue already went; its late clip (or still) joins the picture on the glass.
        Media& target = media.motion ? clip_ : still_;
        release(target);
        target = media;
        started_ = millis();
        drawn_ = -1;
        changed_ = true;
      } else if (media.cue == held_request_.cue) {
        Media& target = media.motion ? held_clip_ : held_still_;
        release(target);
        target = media;
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
    Media& target = media.motion ? clip_ : still_;
    release(target);
    target = media;
    started_ = millis();
    drawn_ = -1;
    changed_ = true;
    Serial.printf("show: ready %s frames=%u bytes=%u 320x240 fps=%d\n",
                  media.motion ? "motion" : "still", unsigned(media.count), unsigned(media.length), kShowFps);
  }
}
bool ShowPlayer::render(uint16_t* pixels, bool force) {
  if (!pixels || !available()) return false;
  Media& media = clip_.bytes ? clip_ : still_;
  const size_t index = media.motion ? (uint64_t(uint32_t(millis() - started_)) * kShowFps / 1000) % media.count : 0;
  if (!force && !changed_ && drawn_ == int(index)) return false;
  const ShowFrame& frame = media.frames[index];
  if (!jpg2rgb565(media.bytes + frame.offset, frame.length, reinterpret_cast<uint8_t*>(pixels), JPG_SCALE_NONE)) {
    Serial.println("show: JPEG decode failed; retaining still or returning home");
    if (media.motion) { release(clip_); changed_ = true; return render(pixels, true); }
    cancel();
    return false;
  }
  drawn_ = int(index);
  changed_ = false;
  return true;
}
void ShowPlayer::diagnose() const {
  Serial.printf("show: viewing=%d still=%u clip=%u frames=%u held_cue=%lu held_still=%u held_clip=%u fps=%d free_psram=%u\n",
                viewing(), unsigned(still_.length), unsigned(clip_.length), unsigned(clip_.count),
                static_cast<unsigned long>(held_request_.cue), unsigned(held_still_.length), unsigned(held_clip_.length),
                kShowFps, unsigned(heap_caps_get_free_size(MALLOC_CAP_SPIRAM)));
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
  snprintf(url, sizeof(url), "%s%s?w=%d&h=%d%s", origin, path, kShowWidth, kShowHeight,
           motion ? "&fps=12" : "");
  WiFiClientSecure tls;
  WiFiClient plain;
  HTTPClient http;
  http.setConnectTimeout(2500);
  // Server may need to build its first MJPEG cache. Only this media task waits.
  http.setTimeout(35000);
  http.setFollowRedirects(HTTPC_DISABLE_FOLLOW_REDIRECTS);
  tls.setCACert(kFriendRootCAs);
  if (!(secure ? http.begin(tls, url) : http.begin(plain, url))) return false;
  const char* keys[] = {"Content-Type", "X-Gizmo-Frame-Count", "X-Gizmo-Frame-Rate",
                        "X-Gizmo-Frame-Width", "X-Gizmo-Frame-Height"};
  http.collectHeaders(keys, 5);
  http.addHeader("X-Gizmo-Device", r.device);
  if (*r.token) { char auth[104]; snprintf(auth, sizeof(auth), "Bearer %s", r.token); http.addHeader("Authorization", auth); }
  const int status = http.GET();
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
        uint32_t(millis() - progress) > 5000) { ok = false; break; }
    const int available = stream->available();
    if (available > 0) {
      const size_t chunk = min(size_t(4096), min(size_t(available), size_t(length) - received));
      const int read = stream->read(media.bytes + received, chunk);
      if (read <= 0) { ok = false; break; }
      received += size_t(read);
      progress = millis();
    } else if (!http.connected()) { ok = false; break; }
    vTaskDelay(pdMS_TO_TICKS(1));
  }
  http.end();
  ok = ok && received == size_t(length) && show_index(media.bytes, received, media.frames, count);
  if (!ok) {
    release(media);
    Serial.printf("show: %s unavailable (http=%d); retaining current picture\n", motion ? "motion" : "still", status);
    return false;
  }
  media.length = received;
  media.count = count;
  media.motion = motion;
  media.revision = job.revision;
  media.cue = job.request.cue;
  media.held = job.held;
  return true;
}
void ShowPlayer::run() {
  for (;;) {
    Job job;
    // The picture on the glass first, then the one waiting behind it.
    if (xQueueReceive(jobs_, &job, 0) == pdTRUE || xQueueReceive(held_jobs_, &job, 0) == pdTRUE) {
      Media media;
      bool still_ok = !job.still;
      if (job.still) {
        if (download(job, false, media)) { publish(media); still_ok = true; }
        else if (job.held) {
          Media failed;
          failed.failed = true; failed.held = true; failed.motion = false;
          failed.cue = job.request.cue; failed.revision = job.revision;
          publish(failed);
        }
      }
      if (still_ok && *job.request.frames) {
        if (download(job, true, media)) publish(media);
        else if (job.held) {
          Media failed;
          failed.failed = true; failed.held = true; failed.motion = true;
          failed.cue = job.request.cue; failed.revision = job.revision;
          publish(failed);
        }
      }
    }
    vTaskDelay(pdMS_TO_TICKS(5));
  }
}
}
