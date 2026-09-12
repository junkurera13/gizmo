// Run against a static server rooted at friend/gizmo_friend on port 8769.
// PLAYWRIGHT_PATH may point to the bundled Playwright runtime.
const { chromium } = require(process.env.PLAYWRIGHT_PATH || 'playwright');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const catalog = JSON.parse(execFileSync('.venv/Scripts/python.exe', ['-c',
  'import json; from gizmo_friend.oddity.moments import catalog; print(json.dumps(catalog()))'],
  {env:{...process.env, PYTHONPATH:'friend'}}));
(async () => {
  const browser = await chromium.launch({channel:'msedge', headless:true});
  const page = await browser.newPage({viewport:{width:1000,height:950}});
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/static/oddity.js*', async route => {
    let source = fs.readFileSync('friend/gizmo_friend/static/oddity.js','utf8');
    source = source.replace(/\nsyncPower\(\);[\s\S]*$/, '');
    source += `
      await mountDevice($('device'));
      awake = true; deviceReady = true;
      document.documentElement.classList.remove('oddity-locked');
      $('preview-gate').hidden = true;
      stage.dataset.glass = 'home'; $('glass-home').hidden = false;
      glass = {world:'home', syncReply(text){
        $('glass-camera').classList.toggle('is-replying', Boolean(String(text || '').trim()));
      }, closeCamera(){
        cameraFeed.pause(); $('glass-camera').hidden=true; stage.dataset.glass='home';
      }, openDemoCamera(src){
        cameraFeed.src=src; cameraFeed.hidden=false; $('glass-camera').hidden=false;
        stage.dataset.glass='camera'; return cameraFeed;
      }};
      const realStart = startMedia;
      startMedia = async (media, signal) => { media.playbackRate=8; await realStart(media, signal); };
      const realDelay=delay; delay=(ms,signal)=>realDelay(Math.min(ms,100),signal);
      playDemoRecordingFor = async (src, signal, text) => playDemoRecording(src, signal, text);
      window.runDemo = async item => {stopDemo(); moments=[item]; syncMoment(item.id); await sayMoment();};
      window.showMathAt = (math,seconds) => {showDemoMath(math,new AbortController().signal);syncDemoMath(seconds);};
      window.inspectDemo = () => ({running:demoRunning, caption:$('caption').textContent,
        spoken:demoCaptions.length, timed:demoTimed, camera:stage.dataset.glass==='camera',
        audio:demoAudio.src, paused:demoAudio.paused, time:demoAudio.currentTime,
        scene:stage.classList.contains('has-scene'), step:$('demo-math').dataset.step});
    `;
    await route.fulfill({contentType:'application/javascript',body:source});
  });
  await page.goto('http://localhost:8769/static/oddity.html?embedded=1');
  await page.waitForFunction(()=>window.runDemo);
  for (const item of catalog) {
    await page.evaluate(item=>{window.done=false;runDemo(item).then(()=>window.done=true);},item);
    let samples=0, plantKidFullscreen=false, plantAgentCaptioned=false;
    while (!await page.evaluate(()=>window.done)) {
      const state=await page.evaluate(()=>inspectDemo());
      if (!state.paused && /kid|question/.test(state.audio)) {
        assert.equal(state.caption,'',item.id+' kid captions'); samples++;
        if (item.id==='plant') {
          const clip=await page.locator('.camera-finder').evaluate(node=>getComputedStyle(node).clipPath);
          plantKidFullscreen ||= clip === 'inset(0px)';
        }
      }
      if (item.id==='plant' && /plant-refreshed/.test(state.audio) && !state.paused && state.caption) {
        const clip=await page.locator('.camera-finder').evaluate(node=>getComputedStyle(node).clipPath);
        plantAgentCaptioned ||= clip !== 'inset(0px)';
      }
      if (item.id==='mathcheck' && /mathcheck-refreshed/.test(state.audio) && !state.paused)
        assert.equal(state.camera,false);
      await page.waitForTimeout(30);
    }
    assert.ok(samples>0,item.id+' sampled kid speech');
    if (item.id==='plant') {
      assert.ok(plantKidFullscreen,'plant camera is fullscreen during kid speech');
      assert.ok(plantAgentCaptioned,'plant camera makes room for Gizmo captions');
    }
    assert.equal(await page.locator('#notice').textContent(),'');
    assert.equal(await page.locator('#caption').textContent(),'');
    if(item.id==='draw') {
      await page.waitForTimeout(1000);
      assert.equal(await page.evaluate(()=>inspectDemo().scene),true);
      assert.equal(await page.locator('#still').isVisible(),true);
    }
    console.log('PASS',item.id);
  }
  assert.equal(await page.locator('.rainbow-kicker,.rainbow-progress,.rainbow-label').count(),0);
  const math=catalog.find(x=>x.id==='mathcheck').demo.math;
  for(const [at,step] of math.visual_timed) {
    await page.evaluate(({math,at})=>showMathAt(math,at),{math,at});
    assert.equal(await page.locator('#demo-math').getAttribute('data-step'),String(step));
  }
  await page.waitForTimeout(450);
  await page.screenshot({path:'build/demo-math-verified.png'});
  assert.deepEqual(errors,[]);
  await browser.close();
})().catch(error=>{console.error(error);process.exit(1);});
