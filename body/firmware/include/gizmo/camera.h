#pragma once
#include <esp_camera.h>

namespace gizmo {
// Single owner; all calls must be made on the same task. A framebuffer is
// borrowed until release(). Stop is forbidden while a frame is borrowed.
class Camera {
 public:
  esp_err_t start();
  esp_err_t stop();
  camera_fb_t* acquire();
  void release();
  bool running() const { return running_; }
  ~Camera();
  Camera() = default;
  Camera(const Camera&) = delete;
  Camera& operator=(const Camera&) = delete;
 private:
  bool running_ = false;
  camera_fb_t* borrowed_ = nullptr;
};
}  // namespace gizmo
