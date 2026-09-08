#include "gizmo/wifi.h"
#include <Arduino.h>
#include <DNSServer.h>
#include <Preferences.h>
#include <WebServer.h>
#include <WiFi.h>

namespace gizmo {
namespace {
constexpr uint16_t kDnsPort = 53;
constexpr uint32_t kSavedFirstAttemptMs = 25000;
constexpr uint32_t kSavedRetryMs = 12000;
constexpr uint32_t kPortalConnectTimeoutMs = 30000;
constexpr uint32_t kJoinCommitMs = 400;
constexpr uint32_t kDropDebounceMs = 3000;
constexpr uint32_t kStatusPeriodMs = 2000;
constexpr int kMaxListed = 12;

DNSServer dns;
WebServer http(80);
volatile uint8_t g_sta_disconnect_reason = 0;
bool g_wifi_events_bound = false;

void on_wifi_event(WiFiEvent_t event, WiFiEventInfo_t info) {
  if (event == ARDUINO_EVENT_WIFI_STA_DISCONNECTED) {
    g_sta_disconnect_reason = info.wifi_sta_disconnected.reason;
  }
}

bool is_auth_failure(uint8_t reason) {
  switch (reason) {
    case WIFI_REASON_AUTH_EXPIRE:
    case WIFI_REASON_4WAY_HANDSHAKE_TIMEOUT:
    case WIFI_REASON_AUTH_FAIL:
    case WIFI_REASON_HANDSHAKE_TIMEOUT:
      return true;
    default:
      return false;
  }
}

bool keep_join_error(const char* detail) {
  return detail != nullptr &&
         (strstr(detail, "WRONG") != nullptr || strstr(detail, "NOT FOUND") != nullptr ||
          strstr(detail, "TIMEOUT") != nullptr);
}

void html_escape(const String& in, String& out) {
  out = "";
  out.reserve(in.length() + 8);
  for (size_t i = 0; i < in.length(); ++i) {
    const char c = in[i];
    if (c == '&') out += "&amp;";
    else if (c == '<') out += "&lt;";
    else if (c == '>') out += "&gt;";
    else if (c == '"') out += "&quot;";
    else if (c == '\'') out += "&#39;";
    else out += c;
  }
}

void url_decode(const String& in, char* out, size_t cap) {
  if (out == nullptr || cap == 0) return;
  size_t w = 0;
  for (size_t i = 0; i < in.length() && w + 1 < cap; ++i) {
    const char c = in[i];
    if (c == '+') {
      out[w++] = ' ';
    } else if (c == '%' && i + 2 < in.length()) {
      auto hex = [](char h) -> int {
        if (h >= '0' && h <= '9') return h - '0';
        if (h >= 'A' && h <= 'F') return h - 'A' + 10;
        if (h >= 'a' && h <= 'f') return h - 'a' + 10;
        return -1;
      };
      const int hi = hex(in[i + 1]);
      const int lo = hex(in[i + 2]);
      if (hi >= 0 && lo >= 0) {
        out[w++] = static_cast<char>((hi << 4) | lo);
        i += 2;
      }
    } else {
      out[w++] = c;
    }
  }
  out[w] = '\0';
}
}  // namespace

const char* wifi_phase_name(WifiPhase phase) {
  switch (phase) {
    case WifiPhase::kConnecting: return "connecting";
    case WifiPhase::kPortal: return "portal";
    case WifiPhase::kOnline: return "online";
    case WifiPhase::kOff: return "off";
  }
  return "off";
}

bool WifiLink::card_visible() const {
  if (phase_ == WifiPhase::kPortal) return true;
  if (pending_sta_) return true;
  if (phase_ == WifiPhase::kConnecting && join_from_portal_) return true;
  if (phase_ == WifiPhase::kConnecting && saved_attempts_ == 0) return true;
  return false;
}

const char* WifiLink::card_title() const {
  if (phase_ == WifiPhase::kPortal && !pending_sta_) return "OPEN PHONE WIFI";
  return "JOINING WIFI";
}

const char* WifiLink::card_line() const {
  if (phase_ == WifiPhase::kPortal && !pending_sta_) return ap_ssid_;
  return sta_ssid_[0] ? sta_ssid_ : ap_ssid_;
}

void WifiLink::send_portal() {
  String escaped_error;
  html_escape(String(detail_), escaped_error);
  String page;
  page.reserve(2048 + scan_html_.length());
  page += F("<!DOCTYPE html><html><head><meta charset=utf-8>"
            "<meta name=viewport content=\"width=device-width,initial-scale=1\">"
            "<title>Gizmo Wi-Fi</title><style>"
            "body{font-family:-apple-system,sans-serif;background:#111;color:#eee;"
            "margin:0;padding:24px}h1{font-size:1.4rem;font-weight:600;margin:0 0 8px}"
            "p{color:#aaa;margin:0 0 16px}button,input{"
            "font-size:1rem;width:100%;box-sizing:border-box;padding:12px;border-radius:10px;"
            "border:0;margin:0 0 10px}input{background:#222;color:#fff}"
            "button{background:#fff;color:#111;font-weight:600}"
            ".net{display:block;width:100%;text-align:left;background:#1c1c1c;color:#fff;"
            "margin:0 0 8px;padding:14px} .err{color:#f66;margin:0 0 12px}</style></head><body>");
  page += F("<h1>Gizmo</h1><p>Pick your 2.4 GHz Wi-Fi. Gizmo remembers it and joins on every boot.</p>"
            "<p>If this page did not open itself, visit <b>192.168.4.1</b>.</p>");
  if (keep_join_error(detail_)) {
    page += "<p class=err>";
    page += escaped_error;
    page += "</p>";
  }
  if (scan_html_.length() == 0) {
    page += F("<p>Scanning for networks&hellip;</p>");
  } else {
    page += scan_html_;
  }
  page += F("<form method=POST action=/join>"
            "<input name=ssid id=ssid placeholder=\"Network name\" maxlength=32 required");
  if (sta_ssid_[0]) {
    String escaped_ssid;
    html_escape(String(sta_ssid_), escaped_ssid);
    page += F(" value=\"");
    page += escaped_ssid;
    page += '"';
  }
  page += F(">"
            "<input name=pass type=password placeholder=\"Password\" maxlength=63>"
            "<button type=submit>Connect</button></form>"
            "<script>function pick(s){document.getElementById('ssid').value=s}</script>"
            "</body></html>");
  http.send(200, "text/html", page);
}

void WifiLink::handle_join() {
  url_decode(http.arg("ssid"), sta_ssid_, sizeof(sta_ssid_));
  url_decode(http.arg("pass"), sta_pass_, sizeof(sta_pass_));
  if (sta_ssid_[0] == '\0') {
    strncpy(detail_, "PICK A NETWORK", sizeof(detail_) - 1);
    send_portal();
    return;
  }
  http.send(200, "text/html",
            F("<!DOCTYPE html><html><head><meta charset=utf-8>"
              "<meta name=viewport content=\"width=device-width,initial-scale=1\">"
              "<title>Gizmo</title></head><body style=\"font-family:sans-serif;background:#111;color:#eee;padding:24px\">"
              "<h1>Connecting</h1><p>Gizmo saved this network and is joining it now. Your phone will "
              "drop off Gizmo Wi-Fi &mdash; that is expected. You can leave this page.</p></body></html>"));
  save_credentials();
  pending_sta_ = true;
  pending_sta_at_ = millis();
  snprintf(detail_, sizeof(detail_), "JOINING %s", sta_ssid_);
}

void WifiLink::poll_scan() {
  // Scanning while the AP is up stops ESP32 beacons; phones then cannot see
  // Gizmo. The network list is captured once in start_portal() before the AP.
}

void WifiLink::build_scan_html() {
  scan_html_ = "";
  const int found = WiFi.scanComplete();
  const int count = found < 0 ? 0 : (found < kMaxListed ? found : kMaxListed);
  for (int i = 0; i < count; ++i) {
    String name = WiFi.SSID(i);
    if (name.length() == 0) continue;
    String escaped;
    html_escape(name, escaped);
    const bool open = WiFi.encryptionType(i) == WIFI_AUTH_OPEN;
    String js = name;
    js.replace("\\", "\\\\");
    js.replace("'", "\\'");
    js.replace("\"", "\\\"");
    scan_html_ += "<button class=net type=button onclick='pick(\"";
    scan_html_ += js;
    scan_html_ += "')\">";
    scan_html_ += escaped;
    if (open) scan_html_ += " · open";
    scan_html_ += "</button>";
  }
  WiFi.scanDelete();
  if (scan_html_.length() == 0) {
    scan_html_ = "<p>No networks heard. Stay on 2.4 GHz. Type the name below if you know it.</p>";
  }
}

void WifiLink::bind_routes() {
  if (routes_bound_) return;
  http.on("/", [this]() { send_portal(); });
  http.on("/join", HTTP_POST, [this]() { handle_join(); });
  http.on("/join", HTTP_GET, [this]() { handle_join(); });
  auto captive = [this]() { send_portal(); };
  http.on("/generate_204", captive);
  http.on("/gen_204", captive);
  http.on("/hotspot-detect.html", captive);
  http.on("/library/test/success.html", captive);
  http.on("/connecttest.txt", captive);
  http.on("/ncsi.txt", captive);
  http.on("/canonical.html", captive);
  http.on("/success.txt", captive);
  http.on("/favicon.ico", []() { http.send(204, "text/plain", ""); });
  http.onNotFound(captive);
  routes_bound_ = true;
}

void WifiLink::bring_up_ap() {
  phase_ = WifiPhase::kPortal;
  pending_sta_ = false;
  join_from_portal_ = false;
  if (!keep_join_error(detail_)) {
    strncpy(detail_, "OPEN 192.168.4.1", sizeof(detail_) - 1);
    detail_[sizeof(detail_) - 1] = '\0';
  }

  WiFi.persistent(false);
  WiFi.mode(WIFI_AP);
  WiFi.setSleep(false);
  WiFi.setTxPower(WIFI_POWER_19_5dBm);
  WiFi.softAPConfig(IPAddress(192, 168, 4, 1), IPAddress(192, 168, 4, 1), IPAddress(255, 255, 255, 0));
  const bool ok = WiFi.softAP(ap_ssid_, nullptr, 6, false, 4);
  delay(150);
  dns.stop();
  dns.start(kDnsPort, "*", WiFi.softAPIP());
  bind_routes();
  http.begin();
  portal_up_ = true;
  last_scan_ = millis();
  scan_pending_ = false;
  Serial.printf("wifi portal: softAP %s ssid=\"%s\" ch=6 ip=%s\n", ok ? "ok" : "FAIL", ap_ssid_,
                WiFi.softAPIP().toString().c_str());
  Serial.println("wifi: phone must use 2.4 GHz. Look for that SSID (open, no password).");
}

void WifiLink::start_portal() {
  pending_sta_ = false;
  join_from_portal_ = false;
  if (portal_up_) stop_portal();

  // Scan first as STA, then AP-only. Live scan while the AP is up drops phones.
  WiFi.persistent(false);
  WiFi.disconnect(false, false);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  const int found = WiFi.scanNetworks(/*async=*/false, /*hidden=*/false, /*passive=*/false, 150);
  Serial.printf("wifi scan: %d networks\n", found);
  build_scan_html();
  bring_up_ap();
}

void WifiLink::resume_portal() {
  if (scan_html_.length() == 0) {
    start_portal();
    return;
  }
  if (portal_up_) {
    phase_ = WifiPhase::kPortal;
    pending_sta_ = false;
    if (!keep_join_error(detail_)) {
      strncpy(detail_, "OPEN 192.168.4.1", sizeof(detail_) - 1);
      detail_[sizeof(detail_) - 1] = '\0';
    }
    return;
  }
  bring_up_ap();
}

void WifiLink::stop_portal() {
  if (portal_up_) {
    http.stop();
    dns.stop();
    portal_up_ = false;
  }
  WiFi.softAPdisconnect(true);
}

void WifiLink::start_sta(const char* ssid, const char* pass, bool from_portal) {
  if (ssid == nullptr || ssid[0] == '\0') {
    start_portal();
    return;
  }
  strncpy(sta_ssid_, ssid, sizeof(sta_ssid_) - 1);
  sta_ssid_[sizeof(sta_ssid_) - 1] = '\0';
  if (pass != nullptr && pass != sta_pass_) {
    strncpy(sta_pass_, pass, sizeof(sta_pass_) - 1);
    sta_pass_[sizeof(sta_pass_) - 1] = '\0';
  }
  pending_sta_ = false;
  phase_ = WifiPhase::kConnecting;
  join_from_portal_ = from_portal;
  connect_started_ = millis();
  snprintf(detail_, sizeof(detail_), "JOINING %s", sta_ssid_);
  // Own the credentials in Preferences. Do not use the SDK Wi-Fi NVS slot:
  // leftover SSIDs from other sketches used to skip our portal.
  // STA-only while joining: AP+STA is locked to channel 6, so home routers on
  // any other channel never associate.
  if (portal_up_) stop_portal();
  WiFi.persistent(false);
  WiFi.disconnect(false, false);
  delay(50);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.setTxPower(WIFI_POWER_19_5dBm);
  WiFi.setHostname("gizmo");
  WiFi.setAutoReconnect(!from_portal);
  g_sta_disconnect_reason = 0;
  WiFi.begin(sta_ssid_, sta_pass_);
  Serial.printf("wifi sta: joining \"%s\"\n", sta_ssid_);
}

void WifiLink::finish_online() {
  ip_ = WiFi.localIP();
  phase_ = WifiPhase::kOnline;
  join_from_portal_ = false;
  pending_sta_ = false;
  saved_attempts_ = 0;
  online_ok_at_ = millis();
  strncpy(sta_ssid_, WiFi.SSID().c_str(), sizeof(sta_ssid_) - 1);
  sta_ssid_[sizeof(sta_ssid_) - 1] = '\0';
  save_credentials();
  stop_portal();
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.setAutoReconnect(true);
  snprintf(detail_, sizeof(detail_), "ONLINE %s", ip_.toString().c_str());
  configTzTime("JST-9", "pool.ntp.org", "time.google.com");
  Serial.printf("wifi online: ssid=\"%s\" ip=%s (saved)\n", sta_ssid_, ip_.toString().c_str());
}

void WifiLink::save_credentials() {
  Preferences store;
  store.begin("gizmo-wifi", false);
  store.putString("ssid", sta_ssid_);
  store.putString("pass", sta_pass_);
  store.end();
}

bool WifiLink::load_credentials() {
  sta_ssid_[0] = '\0';
  sta_pass_[0] = '\0';
  Preferences store;
  store.begin("gizmo-wifi", true);
  store.getString("ssid", sta_ssid_, sizeof(sta_ssid_));
  store.getString("pass", sta_pass_, sizeof(sta_pass_));
  store.end();
  return sta_ssid_[0] != '\0';
}

void WifiLink::clear_credentials() {
  sta_ssid_[0] = '\0';
  sta_pass_[0] = '\0';
  Preferences store;
  store.begin("gizmo-wifi", false);
  store.clear();
  store.end();
}

void WifiLink::begin() {
  uint8_t mac[6] = {};
  WiFi.macAddress(mac);
  snprintf(ap_ssid_, sizeof(ap_ssid_), "Gizmo-%02X%02X", mac[4], mac[5]);
  if (!g_wifi_events_bound) {
    WiFi.onEvent(on_wifi_event);
    g_wifi_events_bound = true;
  }
  saved_attempts_ = 0;
  if (load_credentials()) {
    Serial.printf("wifi: rejoining saved \"%s\"\n", sta_ssid_);
    start_sta(sta_ssid_, sta_pass_, false);
  } else {
    phase_ = WifiPhase::kOff;
    strncpy(detail_, "WAITING FOR BOOT", sizeof(detail_) - 1);
    detail_[sizeof(detail_) - 1] = '\0';
    Serial.printf("wifi: no saved network; portal after boot on \"%s\"\n", ap_ssid_);
  }
}

void WifiLink::start_portal_if_unconfigured() {
  if (phase_ == WifiPhase::kOff) start_portal();
}

void WifiLink::forget() {
  Serial.println("wifi: forgetting saved network");
  clear_credentials();
  ip_ = IPAddress();
  join_from_portal_ = false;
  pending_sta_ = false;
  saved_attempts_ = 0;
  WiFi.disconnect(true, true);
  start_portal();
}

void WifiLink::update() {
  if (pending_sta_ && millis() - pending_sta_at_ >= kJoinCommitMs) {
    start_sta(sta_ssid_, sta_pass_, true);
  }

  if (portal_up_) {
    dns.processNextRequest();
    http.handleClient();
    poll_scan();
  }

  if (phase_ == WifiPhase::kConnecting) {
    if (WiFi.status() == WL_CONNECTED) {
      strncpy(sta_ssid_, WiFi.SSID().c_str(), sizeof(sta_ssid_) - 1);
      sta_ssid_[sizeof(sta_ssid_) - 1] = '\0';
      finish_online();
    } else {
      const uint8_t reason = g_sta_disconnect_reason;
      const uint32_t limit = join_from_portal_
                                 ? kPortalConnectTimeoutMs
                                 : (saved_attempts_ == 0 ? kSavedFirstAttemptMs : kSavedRetryMs);
      const bool auth_fail = join_from_portal_ && is_auth_failure(reason);
      const bool no_ap = join_from_portal_ && reason == WIFI_REASON_NO_AP_FOUND;
      const bool timed_out = millis() - connect_started_ >= limit;
      if (auth_fail || no_ap || timed_out) {
        if (join_from_portal_) {
          if (auth_fail) {
            strncpy(detail_, "WRONG PASSWORD", sizeof(detail_) - 1);
          } else if (no_ap) {
            strncpy(detail_, "NETWORK NOT FOUND", sizeof(detail_) - 1);
          } else {
            strncpy(detail_, "WRONG PASSWORD OR TIMEOUT", sizeof(detail_) - 1);
          }
          detail_[sizeof(detail_) - 1] = '\0';
          Serial.printf("wifi: join failed (%s); credentials kept, reopening portal\n", detail_);
          WiFi.disconnect(false, false);
          resume_portal();
        } else {
          ++saved_attempts_;
          Serial.printf("wifi: saved \"%s\" not up yet; retry %u\n", sta_ssid_,
                        static_cast<unsigned>(saved_attempts_));
          snprintf(detail_, sizeof(detail_), "RETRYING %s", sta_ssid_);
          start_sta(sta_ssid_, sta_pass_, false);
        }
      }
    }
  } else if (phase_ == WifiPhase::kOnline) {
    if (WiFi.status() == WL_CONNECTED) {
      online_ok_at_ = millis();
    } else if (millis() - online_ok_at_ >= kDropDebounceMs) {
      Serial.println("wifi: dropped, reconnecting");
      saved_attempts_ = 0;
      start_sta(sta_ssid_, sta_pass_, false);
    }
  }

  if (millis() - last_status_ >= kStatusPeriodMs) {
    last_status_ = millis();
    if (phase_ == WifiPhase::kOnline) {
      ip_ = WiFi.localIP();
    }
  }
}

}  // namespace gizmo
