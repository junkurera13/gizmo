#include "gizmo/show_format.h"
#include <cassert>
#include <fstream>
#include <iterator>
#include <vector>
#include <string>
#include <cstdio>
int main(int argc, char** argv) {
  using namespace gizmo;
  const char* still = "/shows/device/0123456789abcdef0123456789abcdef.jpg";
  const char* motion = "/shows/device/0123456789abcdef0123456789abcdef.mjpeg";
  assert(show_path(still, "device", ".jpg"));
  assert(show_same(still, motion));
  assert(!show_path(still, "other", ".jpg"));
  assert(!show_path("https://evil.test/a.jpg", "device", ".jpg"));
  assert(!show_path("/shows/device/../a.jpg", "device", ".jpg"));
  assert(!show_path((std::string(still)+"?redirect=1").c_str(), "device", ".jpg"));
  assert(!show_same(still, "/shows/device/1123456789abcdef0123456789abcdef.mjpeg"));
  // Marker-shaped data in APP segments and byte-stuffed entropy are legal.
  std::vector<uint8_t> jpeg = {0xff,0xd8, 0xff,0xe1,0,6,0xff,0xd9,0xff,0xd8,
    0xff,0xc0,0,11,8,0,240,1,64,1,1,0x11,0,
    0xff,0xda,0,8,1,1,0,0,63,0, 0x11,0xff,0,0xd9,0xff,0xd0,0x55,0xff,0xd9};
  ShowFrame frames[kShowMaxFrames];
  assert(show_index(jpeg.data(), jpeg.size(), frames, 1));
  assert(frames[0].length == jpeg.size());
  auto bad = jpeg; bad[18] = 65; // 321 pixels would overflow a panel row
  assert(!show_index(bad.data(), bad.size(), frames, 1));
  bad = jpeg; bad[11] = 0xc2; // progressive is unsupported by hardware decoder
  assert(!show_index(bad.data(), bad.size(), frames, 1));
  bad = jpeg; bad[5] = 255;
  assert(!show_index(bad.data(), bad.size(), frames, 1));
  for (size_t n = 0; n < jpeg.size(); ++n) assert(!show_index(jpeg.data(), n, frames, 1));
  auto sequence = jpeg; sequence.insert(sequence.end(), jpeg.begin(), jpeg.end());
  assert(show_index(sequence.data(), sequence.size(), frames, 2));
  assert(frames[1].offset == jpeg.size());
  assert(!show_index(sequence.data(), sequence.size(), frames, 1));
  assert(!show_index(sequence.data(), sequence.size(), frames, 3));
  sequence.push_back(0);
  assert(!show_index(sequence.data(), sequence.size(), frames, 2));
  assert(!show_index(jpeg.data(), jpeg.size(), frames, kShowMaxFrames+1));
  assert(!show_index(jpeg.data(), kShowMaxBytes+1, frames, 1));
  if (argc > 1) {
    std::ifstream file(argv[1], std::ios::binary);
    std::vector<uint8_t> real{std::istreambuf_iterator<char>(file), {}};
    assert(!real.empty());
    assert(show_index(real.data(), real.size(), frames, argc > 2 ? std::stoi(argv[2]) : 1));
    printf("show: real media indexed (%zu bytes)\n", real.size());
  }
  puts("show: route ownership, JPEG dimensions, segment framing, truncation, frame/byte bounds passed");
}
