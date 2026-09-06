#include "gizmo/wifi.h"
#include <Arduino.h>
#include <DNSServer.h>
#include <WebServer.h>
#include <WiFi.h>

namespace gizmo {
namespace {
constexpr uint16_t kDnsPort = 53;
constexpr uint32_t kConnectTimeoutMs = 20000;
constexpr uint32_t kScanPeriodMs = 8000;
constexpr uint32_t kStatusPeriodMs = 2000;
constexpr int kMaxListed = 12;

DNSServer dns;
WebServer http(80);

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
    default: return "off";
  }
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
  page += F("<h1>Gizmo</h1><p>Pick your Wi-Fi. This is saved on the device; "
            "you only do this once.</p>");
  if (detail_[0] && phase_ != WifiPhase::kPortal) {
    page += "<p class=err>";
    page += escaped_error;
    page += "</p>";
  } else if (detail_[0] && strstr(detail_, "WRONG") != nullptr) {
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
            "<input name=ssid id=ssid placeholder=\"Network name\" maxlength=32 required>"
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
              "<h1>Connecting</h1><p>You can leave this page. Gizmo will join the network "
              "and this setup Wi-Fi will disappear.</p></body></html>"));
  start_sta(sta_ssid_, sta_pass_, true);
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

void WifiLink::start_portal() {
  phase_ = WifiPhase::kPortal;
  strncpy(detail_, "WAITING FOR PHONE", sizeof(detail_) - 1);
  detail_[sizeof(detail_) - 1] = '\0';

  // Scan first as STA, then AP-only. AP_STA + live scan is why phones miss us.
  WiFi.persistent(false);
  WiFi.disconnect(false, false);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  const int found = WiFi.scanNetworks(/*async=*/false, /*hidden=*/true);
  Serial.printf("wifi scan: %d networks\n", found);
  build_scan_html();

  WiFi.mode(WIFI_AP);
  WiFi.setSleep(false);
  WiFi.setTxPower(WIFI_POWER_19_5dBm);
  WiFi.softAPConfig(IPAddress(192, 168, 4, 1), IPAddress(192, 168, 4, 1), IPAddress(255, 255, 255, 0));
  const bool ok = WiFi.softAP(ap_ssid_, nullptr, 6, false, 4);
  delay(100);
  dns.stop();
  dns.start(kDnsPort, "*", WiFi.softAPIP());
  if (!routes_bound_) {
    http.on("/", [this]() { send_portal(); });
    http.on("/join", HTTP_POST, [this]() { handle_join(); });
    http.on("/join", HTTP_GET, [this]() { handle_join(); });
    http.onNotFound([this]() { send_portal(); });
    routes_bound_ = true;
  }
  http.begin();
  portal_up_ = true;
  last_scan_ = millis();
  scan_pending_ = false;
  Serial.printf("wifi portal: softAP %s ssid=\"%s\" ch=6 ip=%s\n", ok ? "ok" : "FAIL", ap_ssid_,
                WiFi.softAPIP().toString().c_str());
  Serial.println("wifi: phone must use 2.4 GHz. Look for that SSID (open, no password).");
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
  phase_ = WifiPhase::kConnecting;
  connect_started_ = millis();
  snprintf(detail_, sizeof(detail_), "JOINING %s", sta_ssid_);
  WiFi.persistent(true);
  WiFi.mode(from_portal ? WIFI_AP_STA : WIFI_STA);
  WiFi.setHostname("gizmo");
  if (sta_pass_[0]) {
    WiFi.begin(sta_ssid_, sta_pass_);
  } else if (from_portal) {
    WiFi.begin(sta_ssid_, nullptr);
  } else {
    WiFi.begin();
  }
  Serial.printf("wifi sta: joining \"%s\"\n", sta_ssid_);
}

void WifiLink::finish_online() {
  ip_ = WiFi.localIP();
  phase_ = WifiPhase::kOnline;
  stop_portal();
  WiFi.mode(WIFI_STA);
  snprintf(detail_, sizeof(detail_), "ONLINE %s", ip_.toString().c_str());
  configTzTime("JST-9", "pool.ntp.org", "time.google.com");
  Serial.printf("wifi online: ssid=\"%s\" ip=%s\n", WiFi.SSID().c_str(), ip_.toString().c_str());
}

void WifiLink::begin() {
  uint8_t mac[6] = {};
  WiFi.macAddress(mac);
  snprintf(ap_ssid_, sizeof(ap_ssid_), "Gizmo-%02X%02X", mac[4], mac[5]);
  // Always open the setup AP first. A leftover NVS SSID from another sketch
  // used to skip the AP entirely, which looks like "Gizmo Wi-Fi missing".
  Serial.printf("wifi: opening setup AP \"%s\"\n", ap_ssid_);
  start_portal();
}

void WifiLink::forget() {
  Serial.println("wifi: forgetting saved network");
  sta_ssid_[0] = '\0';
  sta_pass_[0] = '\0';
  ip_ = IPAddress();
  WiFi.disconnect(true, true);
  start_portal();
}

void WifiLink::update() {
  if (portal_up_) {
    dns.processNextRequest();
    http.handleClient();
    poll_scan();
  }

  if (phase_ == WifiPhase::kConnecting) {
    if (WiFi.status() == WL_CONNECTED) {
      strncpy(sta_ssid_, WiFi.SSID().c_str(), sizeof(sta_ssid_) - 1);
      finish_online();
    } else if (millis() - connect_started_ >= kConnectTimeoutMs) {
      Serial.println("wifi: join timed out");
      strncpy(detail_, "WRONG PASSWORD OR TIMEOUT", sizeof(detail_) - 1);
      WiFi.disconnect(false, false);
      start_portal();
    }
  } else if (phase_ == WifiPhase::kOnline) {
    if (WiFi.status() != WL_CONNECTED) {
      Serial.println("wifi: dropped, reconnecting");
      start_sta(sta_ssid_, sta_pass_[0] ? sta_pass_ : nullptr, false);
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
