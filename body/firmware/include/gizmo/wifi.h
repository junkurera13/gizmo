#pragma once

#include <Arduino.h>
#include <IPAddress.h>
#include <stdint.h>

// One-time phone setup: open AP, captive-portal list of nearby networks,
// save the chosen SSID/password in NVS, then auto-join on later boots.
// The portal runs inside loop(); it never calls delay() around I2S or SPI.
namespace gizmo {

enum class WifiPhase : uint8_t {
  kOff = 0,
  kConnecting,
  kPortal,
  kOnline,
};

class WifiLink {
 public:
  void begin();
  void update();          // DNS + HTTP + STA state; call from loop()
  void forget();          // erase saved credentials and reopen the portal
  WifiPhase phase() const { return phase_; }
  bool portal() const { return phase_ == WifiPhase::kPortal; }
  bool online() const { return phase_ == WifiPhase::kOnline; }
  const char* ap_ssid() const { return ap_ssid_; }
  const char* sta_ssid() const { return sta_ssid_; }
  const char* detail() const { return detail_; }
  IPAddress ip() const { return ip_; }

 private:
  void start_portal();
  void stop_portal();
  void start_sta(const char* ssid, const char* pass, bool from_portal);
  void finish_online();
  void send_portal();
  void handle_join();
  void poll_scan();
  void build_scan_html();

  WifiPhase phase_ = WifiPhase::kOff;
  bool portal_up_ = false;
  bool routes_bound_ = false;
  bool scan_pending_ = false;
  uint32_t connect_started_ = 0;
  uint32_t last_scan_ = 0;
  uint32_t last_status_ = 0;
  IPAddress ip_{};
  char ap_ssid_[16] = "Gizmo";
  char sta_ssid_[33] = "";
  char sta_pass_[65] = "";
  char detail_[48] = "";
  String scan_html_;
};

const char* wifi_phase_name(WifiPhase phase);

}  // namespace gizmo
