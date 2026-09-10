#pragma once

#include <cstdint>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

#ifdef ESP_PLATFORM
#include <sys/time.h>
#endif

// Wall-clock vs TLS stub: Wi-Fi stamps a nearby date so certs validate, but
// that is not local time. The HUD only renders H:mm after NTP, an HTTP Date
// header, or serial tHH:MM. HTTP Date is applied only when nothing has trusted
// the clock yet, so it does not fight NTP or a serial override.
namespace gizmo {

inline bool& wall_time_flag() {
  static bool ready = false;
  return ready;
}

inline bool wall_time_ready() { return wall_time_flag(); }
inline void note_wall_time() { wall_time_flag() = true; }

inline time_t utc_from_civil(int year, int month, int day, int hour, int minute, int sec) {
  static const int mdays[] = {0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334};
  if (month < 0 || month > 11 || day < 1 || day > 31) return 0;
  const auto leap = [](int y) { return (y % 4 == 0 && y % 100 != 0) || (y % 400 == 0); };
  int64_t days = static_cast<int64_t>(year - 1970) * 365 + (year - 1969) / 4 -
                 (year - 1901) / 100 + (year - 1601) / 400;
  days += mdays[month];
  if (month > 1 && leap(year)) days += 1;
  days += day - 1;
  return static_cast<time_t>(days * 86400LL + hour * 3600 + minute * 60 + sec);
}

inline bool apply_http_date(const char* date) {
  if (wall_time_ready() || date == nullptr || date[0] == '\0') return false;
  const char* comma = strchr(date, ',');
  const char* body = comma != nullptr ? comma + 1 : date;
  int day = 0, year = 0, hour = 0, minute = 0, sec = 0;
  char mon[4] = {};
  if (sscanf(body, " %d %3s %d %d:%d:%d", &day, mon, &year, &hour, &minute, &sec) != 6) {
    return false;
  }
  static const char* kMonths[] = {"Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"};
  int month = -1;
  for (int i = 0; i < 12; ++i) {
    if (strcmp(mon, kMonths[i]) == 0) month = i;
  }
  const time_t seconds = utc_from_civil(year, month, day, hour, minute, sec);
  if (seconds < 1735689600) return false;
#ifdef ESP_PLATFORM
  struct timeval tv = {seconds, 0};
  settimeofday(&tv, nullptr);
#endif
  note_wall_time();
  return true;
}

}  // namespace gizmo
