#pragma once

#include <Arduino.h>
#include <IPAddress.h>
#include <stdint.h>

// One-time phone setup: open AP, captive-portal list of nearby networks,
// save the chosen SSID/password in NVS immediately, then auto-join on later
// boots. The ESP32 radio cannot hop channels while the setup AP is up, so a
// join drops that AP, connects STA-only, and brings the AP back only if the
// join fails. A saved network that is out of range is tried a few times, then
// the setup AP opens again; credentials stay until the portal saves a new
// network. Serial `w` forgets them. The portal runs inside loop().
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
  // Join a saved network, or open the setup AP. Call after the boot
  // flipbook so Wi-Fi TX is not stacked on display decode.
  void start_portal_if_unconfigured();
  // Lower TX power when the LiPo is the supply. The hub feeds battery
  // voltage into the XIAO 5V pin; 19.5 dBm TX browns out 3V3.
  void set_battery_budget(bool on_battery);
  WifiPhase phase() const { return phase_; }
  bool portal() const { return phase_ == WifiPhase::kPortal; }
  bool online() const { return phase_ == WifiPhase::kOnline; }
  bool card_visible() const;
  const char* card_title() const;
  const char* card_line() const;
  const char* ap_ssid() const { return ap_ssid_; }
  const char* sta_ssid() const { return sta_ssid_; }
  const char* detail() const { return detail_; }
  IPAddress ip() const { return ip_; }

 private:
  void apply_tx_power();
  void start_portal();
  void resume_portal();
  void bring_up_ap();
  void bind_routes();
  void stop_portal();
  void start_sta(const char* ssid, const char* pass, bool from_portal);
  void give_up_saved_network();
  void finish_online();
  void send_portal();
  void handle_join();
  void poll_scan();
  void build_scan_html();
  void save_credentials();
  bool load_credentials();
  void clear_credentials();

  WifiPhase phase_ = WifiPhase::kOff;
  bool battery_budget_ = false;
  bool portal_up_ = false;
  bool routes_bound_ = false;
  bool scan_pending_ = false;
  bool pending_sta_ = false;
  bool join_from_portal_ = false;
  uint8_t saved_attempts_ = 0;
  uint32_t connect_started_ = 0;
  uint32_t pending_sta_at_ = 0;
  uint32_t last_scan_ = 0;
  uint32_t last_status_ = 0;
  uint32_t online_ok_at_ = 0;
  IPAddress ip_{};
  char ap_ssid_[16] = "Gizmo";
  char sta_ssid_[33] = "";
  char sta_pass_[65] = "";
  char detail_[48] = "";
  String scan_html_;
};

const char* wifi_phase_name(WifiPhase phase);

}  // namespace gizmo
