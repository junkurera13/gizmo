#include "gizmo/camera.h"
#include "gizmo/board.h"
#include <esp32-hal-psram.h>

namespace gizmo {
esp_err_t Camera::start() {
  if (running_) return ESP_OK;
  if (!psramFound()) return ESP_ERR_NO_MEM;
  camera_config_t config{};
  config.pin_pwdn = -1;
  config.pin_reset = -1;
  config.pin_xclk = board::camera_xclk;
  config.pin_sccb_sda = board::camera_sda;
  config.pin_sccb_scl = board::camera_scl;
  config.pin_d0 = board::camera_d0;
  config.pin_d1 = board::camera_d1;
  config.pin_d2 = board::camera_d2;
  config.pin_d3 = board::camera_d3;
  config.pin_d4 = board::camera_d4;
  config.pin_d5 = board::camera_d5;
  config.pin_d6 = board::camera_d6;
  config.pin_d7 = board::camera_d7;
  config.pin_vsync = board::camera_vsync;
  config.pin_href = board::camera_href;
  config.pin_pclk = board::camera_pclk;
  config.xclk_freq_hz = 20000000;
  config.ledc_timer = LEDC_TIMER_0;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.pixel_format = PIXFORMAT_JPEG;
  // A conservative bring-up resolution, not the unselected display profile.
  config.frame_size = FRAMESIZE_QVGA;
  config.jpeg_quality = 12;
  config.fb_count = 2;
  config.fb_location = CAMERA_FB_IN_PSRAM;
  config.grab_mode = CAMERA_GRAB_LATEST;
  const auto result = esp_camera_init(&config);
  running_ = result == ESP_OK;
  return result;
}

esp_err_t Camera::stop() {
  if (borrowed_) return ESP_ERR_INVALID_STATE;
  if (!running_) return ESP_OK;
  const auto result = esp_camera_deinit();
  if (result == ESP_OK) running_ = false;
  return result;
}

camera_fb_t* Camera::acquire() {
  if (!running_ || borrowed_) return nullptr;
  borrowed_ = esp_camera_fb_get();
  return borrowed_;
}

void Camera::release() {
  if (!borrowed_) return;
  esp_camera_fb_return(borrowed_);
  borrowed_ = nullptr;
}

Camera::~Camera() {
  release();
  stop();
}
}  // namespace gizmo
