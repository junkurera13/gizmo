#include <Arduino.h>
#include <HTTPClient.h>
#include <img_converters.h>
#include <freertos/task.h>
#include <freertos/semphr.h>
#include <fstream>
#include <iterator>
#include <cassert>
#include <thread>
#include <chrono>
#define private public
#include "gizmo/show.h"
#undef private

using namespace gizmo;

// Motion frames are decoded off the body loop now; render() is a memcpy over
// the decode-ahead ring, so tests poll for the task to publish a frame.
static bool wait_render(ShowPlayer& player, uint16_t* pixels, int tries = 300) {
  for (int i = 0; i < tries; ++i) {
    if (player.render(pixels)) return true;
    std::this_thread::sleep_for(std::chrono::milliseconds(2));
  }
  return false;
}

int main(int argc,char** argv) {
  using namespace gizmo;
  assert(argc == 2);
  std::ifstream file(argv[1],std::ios::binary);
  const std::vector<uint8_t> jpeg{std::istreambuf_iterator<char>(file),{}};
  assert(!jpeg.empty());
  ShowRequest request;
  request.viewing=true;
  strcpy(request.device,"device");
  strcpy(request.token,"test-secret");
  strcpy(request.base,"https://brain.test/prefix");
  strcpy(request.still,"/shows/device/0123456789abcdef0123456789abcdef.jpg");
  ShowPlayer player;
  player.jobs_=xQueueCreate(1,sizeof(ShowPlayer::Job));
  player.results_=xQueueCreate(2,sizeof(ShowPlayer::Media));
  player.submit(request);
  ShowPlayer::Job job;
  assert(xQueueReceive(player.jobs_,&job,0));
  auto response = [&](bool motion) {
    mock_media_body=jpeg;
    if(motion)mock_media_body.insert(mock_media_body.end(),jpeg.begin(),jpeg.end());
    mock_media_length=int(mock_media_body.size());
    mock_media_status=200;
    mock_media_headers={{"Content-Type",motion?"video/x-motion-jpeg":"image/jpeg"},
      {"X-Gizmo-Frame-Count","2"},{"X-Gizmo-Frame-Rate",std::to_string(kShowFps)},
      {"X-Gizmo-Frame-Width","320"},{"X-Gizmo-Frame-Height","240"}};
  };
  response(false);
  ShowPlayer::Media media;
  assert(player.download(job,false,media));
  assert(mock_request_url==std::string("https://brain.test")+request.still+"?w=320&h=240");
  assert(mock_request_headers["Authorization"]=="Bearer test-secret");
  assert(mock_request_headers["X-Gizmo-Device"]=="device");
  assert(mock_redirects==HTTPC_DISABLE_FOLLOW_REDIRECTS);
  player.publish(media);player.update();assert(player.available());
  uint16_t pixels[320*240];
  assert(player.render(pixels));assert(!player.render(pixels));
  strcpy(request.frames,"/shows/device/0123456789abcdef0123456789abcdef.mjpeg");
  player.submit(request);assert(player.available());
  assert(xQueueReceive(player.jobs_,&job,0));assert(!job.still);
  response(true);assert(player.download(job,true,media));
  assert(mock_request_url==std::string("https://brain.test")+request.frames+"?w=320&h=240&fps="+std::to_string(kShowFps));
  player.publish(media);player.update();assert(player.clip_.count==2);
  // Wire the decode-ahead path the way begin() does: buffers, muxes, task.
  player.media_mux_=xSemaphoreCreateMutex();
  player.dec_scratch_=new uint8_t[ShowPlayer::kDecScratch];
  for(int b=0;b<ShowPlayer::kDecBufs;++b){
    player.dec_pixels_[b]=new uint16_t[320*240];
    player.dec_index_[b].store(-1);player.dec_gen_[b].store(0);player.dec_bad_[b].store(false);
  }
  xTaskCreate(ShowPlayer::decode_task,"dec",8192,&player,1,nullptr);
  // Clock starts on the first presented frame, not when the clip lands, so a
  // slow first decode cannot skip the opening frames.
  assert(wait_render(player,pixels));
  assert(player.drawn_==0);
  constexpr uint32_t frame_ms=1000/kShowFps+1;
  mock_now+=frame_ms;assert(wait_render(player,pixels));assert(player.drawn_==1);
  mock_now+=frame_ms;assert(wait_render(player,pixels));assert(player.drawn_==0);
  // Same still with no frames must freeze: drop the looping cue, keep the poster.
  ShowRequest freeze=request;freeze.frames[0]=0;freeze.go=true;
  player.submit(freeze);
  assert(player.available());
  assert(player.clip_.bytes==nullptr);
  assert(wait_render(player,pixels));
  // A freeze that names a different poster must not drop the framebuffer.
  ShowRequest other=freeze;
  strcpy(other.still,"/shows/device/fedcba9876543210fedcba9876543210.jpg");
  player.submit(other);
  assert(player.available());
  assert(player.clip_.bytes==nullptr);
  // A failed frame is marked bad and skipped: render repeats the previous
  // frame instead of decoding inline, and the clip is retained. Republishing
  // bumps the generation, so the decode task re-decodes and the injected
  // failure lands there — not on the next still's decode.
  mock_jpeg_failures=1;
  ShowPlayer::Job again{request,player.revision_.load(),false,false};
  response(true);assert(player.download(again,true,media));
  player.publish(media);player.update();
  bool marked=false;
  for(int i=0;i<100 && !marked;++i){
    for(int b=0;b<ShowPlayer::kDecBufs;++b)
      if(player.dec_bad_[b].load()&&player.dec_gen_[b].load()==player.media_gen_.load())marked=true;
    std::this_thread::sleep_for(std::chrono::milliseconds(4));
  }
  assert(marked);
  assert(player.available() && player.clip_.bytes!=nullptr);
  // Opening frame 0 is bad; render still starts on the first good ring slot.
  bool recovered=false;
  for(int i=0;i<300 && !recovered;++i){recovered=player.render(pixels);mock_now+=84;std::this_thread::sleep_for(std::chrono::milliseconds(2));}
  assert(recovered);
  // Errors leave the already-visible still intact.
  for(int status:{302,401,404,503}) {response(true);mock_media_status=status;assert(!player.download(job,true,media));assert(player.available());}
  response(true);mock_media_length=int(kShowMaxBytes)+1;assert(!player.download(job,true,media));
  response(true);mock_media_length=-1;assert(!player.download(job,true,media));
  response(true);mock_media_headers["X-Gizmo-Frame-Width"]="321";assert(!player.download(job,true,media));
  response(true);mock_media_headers["X-Gizmo-Frame-Count"]="3";assert(!player.download(job,true,media));
  response(true);mock_media_body.pop_back();assert(!player.download(job,true,media));
  response(true);mock_media_stalled=true;assert(!player.download(job,true,media));mock_media_stalled=false;
  response(true);assert(player.download(job,true,media));
  player.cancel();player.publish(media);player.update();assert(!player.available());
  player.submit(request);assert(!player.viewing()); // locally dismissed id stays dismissed
  request.viewing=false;player.submit(request);
  request.viewing=true;player.submit(request);assert(!player.viewing()); // clear ack cannot revive the dismissed id
  request.still[14]='1';request.frames[14]='1';
  player.submit(request);assert(player.viewing()); // a different Show can display
  ShowRequest cleared;player.submit(cleared);
  player.submit(request);assert(player.viewing()); // network clear alone permits reconnect restoration
  assert(!player.download(job,true,media)); // old revision never starts a request
  // Storytelling: a held cue is fetched behind the current picture, acked, and
  // swapped in on "go" without a download in between.
  player.held_jobs_=xQueueCreate(1,sizeof(ShowPlayer::Job));
  player.results_=xQueueCreate(4,sizeof(ShowPlayer::Media));
  response(false);player.submit(request);
  assert(xQueueReceive(player.jobs_,&job,0)&&player.download(job,false,media));
  player.publish(media);player.update();assert(player.available());
  const uint8_t* on_glass=player.still_.bytes;
  ShowRequest held=request;held.cue=5;held.hold=true;held.frames[0]=0;
  held.still[20]='2';
  player.submit(held);
  assert(!xQueueReceive(player.jobs_,&job,0)); // nothing for the glass
  assert(xQueueReceive(player.held_jobs_,&job,0)&&job.held&&job.still&&job.request.cue==5);
  response(false);assert(player.download(job,false,media));assert(media.held&&media.cue==5);
  player.publish(media);player.update();
  assert(player.still_.bytes==on_glass); // the current picture did not change
  assert(player.held_still_.bytes!=nullptr);
  GlassReady ack;
  assert(player.take_glass_ready(ack)&&ack.cue==5&&!ack.motion&&ack.ok&&!player.take_glass_ready(ack));
  ShowRequest go=held;go.hold=false;go.go=true;
  strcpy(go.frames,go.still);memcpy(go.frames+strlen(go.frames)-4,".mjpeg",7);
  const uint8_t* was_held=player.held_still_.bytes;
  player.submit(go);
  assert(player.still_.bytes==was_held&&player.held_still_.bytes==nullptr&&player.request_.cue==5);
  assert(player.render(pixels)); // no download between go and the new picture
  assert(!xQueueReceive(player.jobs_,&job,0));
  assert(xQueueReceive(player.held_jobs_,&job,0)&&job.held&&!job.still); // frames the hold did not carry
  response(true);assert(player.download(job,true,media));
  player.publish(media);player.update();
  assert(player.clip_.count==2&&player.clip_.cue==5); // adopted by the picture that already went
  assert(player.take_glass_ready(ack)&&ack.cue==5&&ack.motion&&ack.ok);
  // A held fetch that fails reports so; the brain speaks over the picture it has.
  ShowPlayer::Media failed;failed.failed=true;failed.held=true;failed.cue=6;failed.revision=player.held_revision_.load();
  player.publish(failed);player.update();
  assert(player.take_glass_ready(ack)&&ack.cue==6&&!ack.ok);
  // A plain conversation picture drops whatever was held.
  ShowRequest later=held;later.cue=9;later.still[21]='3';player.submit(later);
  assert(player.held_request_.cue==9);
  ShowRequest plain=request;plain.still[22]='4';plain.frames[0]=0;player.submit(plain);
  assert(player.held_request_.cue==0&&player.held_still_.bytes==nullptr);
  // A genuinely blocked HTTP request never runs on the body loop.
  ShowPlayer async;
  mock_health_entered=false;mock_health_blocked=true;
  response(false);request.frames[0]=0;
  async.begin();async.submit(request);
  for(int i=0;i<1000&&!mock_health_entered;++i)std::this_thread::sleep_for(std::chrono::milliseconds(1));
  assert(mock_health_entered);
  const auto started=std::chrono::steady_clock::now();
  for(int i=0;i<10000;++i)async.update();
  async.cancel();
  assert(std::chrono::steady_clock::now()-started<std::chrono::milliseconds(100));
  mock_health_blocked=false;join_mock_tasks();
  async.update();assert(!async.available());
  puts("show: authenticated downloads, still-to-motion, loop timing, HTTP/metadata/truncation failures, stale cancellation, blocked-HTTP responsiveness passed");
}
