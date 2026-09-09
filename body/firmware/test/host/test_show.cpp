#include <Arduino.h>
#include <HTTPClient.h>
#include <img_converters.h>
#include <freertos/task.h>
#include <fstream>
#include <iterator>
#include <cassert>
#define private public
#include "gizmo/show.h"
#undef private

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
      {"X-Gizmo-Frame-Count","2"},{"X-Gizmo-Frame-Rate","12"},
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
  player.publish(media);player.update();assert(player.clip_.count==2);
  assert(player.render(pixels));
  const auto* first=mock_decoded_frame;
  mock_now+=84;assert(player.render(pixels));assert(mock_decoded_frame!=first);
  mock_now+=84;assert(player.render(pixels));assert(mock_decoded_frame==first);
  mock_jpeg_failures=1;
  assert(player.render(pixels,true)); // damaged motion falls back to the retained still
  assert(player.available() && player.clip_.bytes==nullptr);
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
  mock_health_blocked=false;mock_task_stop=true;mock_task.join();
  async.update();assert(!async.available());
  puts("show: authenticated downloads, still-to-motion, loop timing, HTTP/metadata/truncation failures, stale cancellation, blocked-HTTP responsiveness passed");
}
