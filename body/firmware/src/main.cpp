#include <Arduino.h>
#include <esp_heap_caps.h>
#include "gizmo/camera.h"
#include "gizmo/settings.h"

namespace {
gizmo::Camera camera;
uint32_t lastFrame = 0;
uint32_t frames = 0;
uint32_t lastReport = 0;
uint32_t failures = 0;

void command(char value) {
  if (value == 'c') {
    const auto result = camera.start();
    Serial.printf("camera start: %s\n", esp_err_to_name(result));
    if (result == ESP_OK) {
      const auto* sensor = esp_camera_sensor_get();
      Serial.printf("sensor PID=0x%04x; QVGA JPEG; PSRAM buffers\n", sensor->id.PID);
      frames = failures = 0;
      lastReport = millis();
    }
  } else if (value == 'x') {
    Serial.printf("camera stop: %s\n", esp_err_to_name(camera.stop()));
  } else if (value == 's') {
    gizmo::SettingsSnapshot snapshot;
    snapshot.open = true;
    snapshot.focus = 0;
    snapshot.brightness = 8;
    snapshot.volume = 6;
    const size_t bytes = static_cast<size_t>(gizmo::kSettingsWidth) * gizmo::kSettingsHeight * sizeof(uint16_t);
    auto* buffer = static_cast<uint16_t*>(heap_caps_malloc(bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    if (buffer == nullptr) {
      buffer = static_cast<uint16_t*>(heap_caps_malloc(bytes, MALLOC_CAP_8BIT));
    }
    if (buffer == nullptr) {
      Serial.println("settings render: no buffer");
      return;
    }
    gizmo::render_settings(buffer, gizmo::kSettingsWidth, gizmo::kSettingsHeight, snapshot);
    uint32_t checksum = 0;
    for (int i = 0; i < gizmo::kSettingsWidth * gizmo::kSettingsHeight; ++i) checksum += buffer[i];
    Serial.printf("settings render %dx%d checksum=%u backlight=%u\n",
                  gizmo::kSettingsWidth, gizmo::kSettingsHeight, checksum,
                  gizmo::backlight_duty(snapshot.brightness));
    heap_caps_free(buffer);
  } else if (value == '?') {
    Serial.printf("camera=%s heap=%u psram_free=%u backlight=%u\n",
                  camera.running() ? "running" : "off",
                  ESP.getFreeHeap(), ESP.getFreePsram(),
                  gizmo::backlight_duty(8));
  }
}
}  // namespace

void setup() {
  Serial.begin(115200);
  // A standalone board must boot even when no serial monitor is attached.
  const auto started = millis();
  while (!Serial && millis() - started < 1500) delay(10);
  Serial.println("Gizmo / XIAO ESP32S3 Sense / camera bring-up");
  Serial.printf("flash=%u psram=%u\n", ESP.getFlashChipSize(), ESP.getPsramSize());
  Serial.println("c: start camera, x: stop camera, s: render settings, ?: status");
  Serial.println("No display/audio/network configured. Camera stays off until c.");
}

void loop() {
  while (Serial.available()) command(static_cast<char>(Serial.read()));
  if (camera.running() && millis() - lastFrame >= 100) {
    lastFrame = millis();
    auto* frame = camera.acquire();
    if (frame) {
      if (frame->format == PIXFORMAT_JPEG && frame->len > 0 && frame->len <= 128 * 1024) {
        ++frames;
      } else {
        ++failures;
      }
      // Nothing is uploaded or saved. A panel renderer will consume the
      // borrowed frame here once its controller and bus are confirmed.
      camera.release();
    } else {
      ++failures;
    }
    if (millis() - lastReport >= 2000) {
      Serial.printf("frames=%u failures=%u heap=%u psram_free=%u\n",
                    frames, failures, ESP.getFreeHeap(), ESP.getFreePsram());
      lastReport = millis();
    }
  }
  delay(1);
}
