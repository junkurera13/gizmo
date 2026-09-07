#pragma once
#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <cstdio>
#include <string>
#include <vector>
using std::min;
inline uint32_t mock_now = 100;
inline uint32_t millis() { return mock_now; }
struct SerialMock { template<class... T> void printf(const char*, T...) {} void println(const char*) {} };
inline SerialMock Serial;
class String : public std::string {
 public:
  using std::string::string;
  String(const std::string& value) : std::string(value) {}
  int indexOf(const char* s, int from = 0) const { auto n=find(s,from); return n==npos?-1:static_cast<int>(n); }
  int indexOf(char c, int from = 0) const { auto n=find(c,from); return n==npos?-1:static_cast<int>(n); }
  String substring(int from) const { return substr(from); }
  int toInt() const { return atoi(c_str()); }
};
