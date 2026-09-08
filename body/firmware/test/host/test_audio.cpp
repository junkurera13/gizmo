#include <cassert>
#include <driver/i2s.h>
#include "gizmo/audio.h"
namespace gizmo {
void apply_volume(int16_t* p,size_t n,uint8_t step,uint8_t steps) {
  for(size_t i=0;i<n;++i)p[i]=static_cast<int16_t>(int32_t(p[i])*step/steps);
}
}
int main() {
  gizmo::Audio audio;
  assert(audio.begin()==ESP_OK);
  audio.set_volume(5,10);
  int16_t pcm[256];for(auto& p:pcm)p=1000;
  audio.enqueue_live(pcm,256);
  audio.update();assert(!audio.playing()); // short packet waits for prebuffer deadline
  mock_now+=249;audio.update();assert(!audio.playing());
  mock_now+=1;audio.update();assert(audio.playing());
  const int cleared=mock_dma_clears,stopped=mock_amp_stops;
  mock_now+=2;audio.update();assert(mock_dma_clears==cleared&&mock_amp_stops==stopped);
  mock_now+=491;audio.update();assert(audio.playing());
  mock_now+=2;audio.update();assert(!audio.playing());
  assert(mock_written.size()==256);
  for(auto p:mock_written)assert(p==500);
  // A timeout can still have accepted half a chunk. No lost or duplicate PCM.
  mock_written.clear();mock_write_limit=128*2;
  audio.enqueue_live(pcm,256);mock_now+=250;audio.update();
  assert(mock_written.size()==128);
  mock_write_limit=SIZE_MAX;audio.update();
  assert(mock_written.size()==256);
  for(auto p:mock_written)assert(p==500);
  // An explicit interrupt must discard the pending tail immediately.
  audio.stop_live();assert(!audio.playing());
  puts("audio: jitter, DMA drain, partial timeout, interrupt passed");
}
