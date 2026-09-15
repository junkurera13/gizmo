import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';

async function app() {
  const elements = new Map();
  const fetches = [];
  const sent = [];
  function element(id) {
    if (!elements.has(id)) elements.set(id, {
      id, dataset:{}, style:{}, hidden: id === 'moments',
      textContent:'', value:'',
      classList:{add(){},remove(){},contains(){return false;},toggle(){}},
      addEventListener(){}, removeEventListener(){}, setAttribute(){}, replaceChildren(){},
      pause(){}, load(){}, removeAttribute(){},
    });
    return elements.get(id);
  }
  const location = {search:'?embedded=1', host:'example.test', protocol:'http:'};
  class FakeSocket {
    static OPEN = 1; static CONNECTING = 0; static CLOSING = 2; static CLOSED = 3;
    readyState = 1;
    close() { this.readyState = 3; }
  }
  const context = vm.createContext({
    document: {
      getElementById:element, querySelectorAll:()=>[], querySelector:()=>null,
      documentElement:{classList:{add(){},remove(){},contains(){return false;}}},
      createTextNode:text=>({textContent:text}), createElement:()=>({append(){}, textContent:''}), addEventListener(){},
    },
    window:{addEventListener(){}, location},
    location, navigator:{mediaDevices:{}},
    fetch: async (url, options={}) => {
      fetches.push({url, options});
      return {
        ok: true, status: 200,
        json: async () => ({
          session: 'a'.repeat(32), mode: 'moment',
          moment: options.headers?.['X-Oddity-Moment'] || 'birthday',
          moments: [
            {id:'birthday', line:'How many more days until my birthday?', demo:{prompt:'Gizmo, how many more days until my birthday?', prompt_audio:'/static/demo-birthday-kid.mp3', reply:'Eleven more days.', reply_audio:'/static/demo-birthday-gizmo.wav'}},
            {id:'draw', line:'What should I draw?'},
          ],
        }),
      };
    },
    setTimeout, clearTimeout, setInterval, clearInterval, AbortController, DOMException,
    WebSocket: FakeSocket, MediaRecorder: class {}, Image: class {},
    captionChunks:()=>[], captionAt:()=>'', captionTimings:(entries)=>Array.isArray(entries)?entries:[], console, URLSearchParams, JSON,
  });
  context.globalThis = context;
  let source = await fs.readFile(new URL('../gizmo_friend/static/oddity.js', import.meta.url), 'utf8');
  source = source.replace(/^import .*;\r?\n/gm, '').replace(/\r?\nsyncPower\(\);[\s\S]*$/, '');
  vm.runInContext(`'use strict';\n${source}`, context);
  context.sent = sent;
  vm.runInContext('mountDevice = async () => {}; deviceReady = true; awake = true; socket = {readyState:1, send(value){sent.push(value)}};', context);
  return {element, context, fetches, sent, run: code => vm.runInContext(code, context)};
}

test('embedded player shows the current kid line on the rail', async () => {
  const ui = await app();
  assert.equal(ui.run('playMoments'), true);
  ui.run('moments = [{id:"birthday", line:"How many more days until my birthday?"}, {id:"draw", line:"What should I draw?"}]');
  ui.run('syncMoment("draw")');
  assert.equal(ui.element('moments').hidden, false);
  assert.equal(ui.element('moment-line').textContent, 'What should I draw?');
});

test('scenario navigation is available only while the device is on', async () => {
  const ui = await app();
  ui.run('moments = [{id:"birthday", line:"Birthday"}, {id:"draw", line:"What should I draw?"}]; syncMoment("birthday")');
  assert.equal(ui.element('moments').hidden, false);
  ui.run('awake = false; syncPower()');
  assert.equal(ui.element('moments').hidden, true);
  ui.run('awake = true; syncPower()');
  assert.equal(ui.element('moments').hidden, false);
});

test('a single completed demo hides scenario navigation', async () => {
  const ui = await app();
  ui.run('moments = [{id:"birthday", line:"How many more days until my birthday?", demo:{prompt:"Gizmo, how many more days until my birthday?", prompt_audio:"/static/demo-birthday-kid.mp3"}}]; syncMoment("birthday")');
  assert.equal(ui.element('moment-prev').hidden, true);
  assert.equal(ui.element('moment-next').hidden, true);
});

test('two completed demos show left and right navigation', async () => {
  const ui = await app();
  ui.run('moments = [{id:"birthday", line:"Birthday", demo:{prompt_audio:"kid.mp3", reply_audio:"gizmo.wav"}}, {id:"pompeii", line:"Pompeii", demo:{prompt_audio:"kid.mp3", beats:[{reply_audio:"gizmo.wav"}]}}]; syncMoment("birthday")');
  assert.equal(ui.element('moment-prev').hidden, false);
  assert.equal(ui.element('moment-next').hidden, false);
});

test('only completed moments expose a playable demo', async () => {
  const ui = await app();
  ui.run('moments = [{id:"birthday", line:"How many more days until my birthday?", demo:{prompt:"Gizmo, how many more days until my birthday?", prompt_audio:"/static/demo-birthday-kid.mp3", reply_audio:"/static/demo-birthday-gizmo.wav"}}, {id:"draw", line:"What should I draw?"}]');
  ui.run('syncMoment("birthday")');
  assert.equal(ui.element('moment-say').disabled, false);
  assert.equal(ui.element('moment-say').textContent, 'Play demo');
  ui.run('syncMoment("draw")');
  assert.equal(ui.element('moment-say').disabled, true);
  assert.equal(ui.element('moment-say').textContent, 'Coming soon');
});

test('the recorded kid question is followed by the real Gizmo voice', async () => {
  const ui = await app();
  ui.context.recorded = [];
  ui.run('moments = [{id:"birthday", line:"How many more days until my birthday?", demo:{prompt:"Gizmo, how many more days until my birthday?", prompt_audio:"/static/demo-birthday-kid.mp3", reply:"Eleven more days. That\'s close enough to start getting excited. Your birthday will be here before you know it.", reply_audio:"/static/demo-birthday-gizmo.wav"}}]; syncMoment("birthday"); playDemoRecording = async (src, signal, text) => { recorded.push(src); setCaption(text); }');
  await ui.run('sayMoment()');
  assert.deepEqual([...ui.context.recorded], [
    '/static/demo-birthday-kid.mp3',
    '/static/demo-birthday-gizmo.wav',
  ]);
  assert.equal(ui.element('caption').textContent, '');
  assert.match(ui.element('status').textContent, /Demo finished/);
  assert.equal(ui.element('device').dataset.ptt, 'false');
});

test('Pompeii plays three synchronized narrated videos', async () => {
  const ui = await app();
  ui.context.recorded = []; ui.context.videos = [];
  ui.run('delay = async () => {}; playDemoRecording = async (src, signal, text) => { recorded.push(src); setCaption(text); }; showDemoVideo = async (src) => videos.push(src); moments = [{id:"pompeii", line:"What happened to Pompeii?", demo:{prompt:"Gizmo, what happened to Pompeii a long time ago?", prompt_audio:"kid.mp3", beats:[{reply:"One", reply_audio:"one.wav", video:"one.mp4"},{reply:"Two", reply_audio:"two.wav", video:"two.mp4"},{reply:"Three", reply_audio:"three.wav", video:"three.mp4"}]}}]; syncMoment("pompeii")');
  await ui.run('sayMoment()');
  assert.deepEqual([...ui.context.recorded], ['kid.mp3', 'one.wav', 'two.wav', 'three.wav']);
  assert.deepEqual([...ui.context.videos], ['one.mp4', 'two.mp4', 'three.mp4']);
  assert.equal(ui.element('caption').textContent, '');
  assert.match(ui.element('status').textContent, /Demo finished/);
});

test('Antarctica locates the continent in a synchronized educational film', async () => {
  const ui = await app();
  ui.context.recorded = []; ui.context.videos = []; ui.context.fullscreenExpansions = 0; ui.context.interruptedTimings = [];
  ui.run(`
    delay = async () => {};
    playDemoRecording = async (src, signal, text) => { recorded.push(src); setCaption(text); };
    playDemoRecordingFor = async (src, signal, text, milliseconds, timed) => { recorded.push(src); interruptedTimings.push(timed); setCaption(text); };
    showDemoVideo = async (src) => { videos.push(src); demoOwnsScene = true; };
    expandDemoSceneFullscreen = () => { fullscreenExpansions += 1; };
    moments = [{id:'antarctica', line:'What does Antarctica look like?', demo:{
      prompt:'Gizmo, what does Antarctica look like?', prompt_audio:'kid.mp3',
      reply:'Antarctica surrounds the South Pole.', reply_audio:'gizmo.wav', video:'antarctica.mp4',
      beats:[
        {reply:'Antarctica has icebergs and penguins.', reply_audio:'gizmo.wav', video:'antarctica.mp4',
          reply_timed:[[0,'Antarctica has icebergs'],[3.2,'and penguins.']],
          interruption:{after_ms:22000, prompt:'Do penguins live anywhere else besides Antarctica?',
            audio:'penguin-kid.mp3', think_wait_ms:650, fullscreen_during_prompt:true}},
        {reply:'Penguins also live in South America and the Galapagos Islands.',
          reply_audio:'penguin-gizmo.wav', video:'penguin-world.mp4'},
      ],
    }}]; syncMoment('antarctica');
  `);
  await ui.run('sayMoment()');
  assert.deepEqual([...ui.context.recorded], ['kid.mp3', 'gizmo.wav', 'penguin-kid.mp3', 'penguin-gizmo.wav']);
  assert.deepEqual([...ui.context.videos], ['antarctica.mp4', 'penguin-world.mp4']);
  assert.equal(JSON.stringify(ui.context.interruptedTimings), JSON.stringify([[[0,'Antarctica has icebergs'],[3.2,'and penguins.']]]));
  assert.equal(ui.context.fullscreenExpansions, 1);
  assert.deepEqual([...ui.run('history.map(item => item.text)')], [
    'Gizmo, what does Antarctica look like?', 'Antarctica has icebergs and penguins.',
    'Do penguins live anywhere else besides Antarctica?',
    'Penguins also live in South America and the Galapagos Islands.',
  ]);
  assert.equal(ui.element('caption').textContent, '');
});

test('Pompeii continues with the recorded kid follow-up and its answer video', async () => {
  const ui = await app();
  ui.context.recorded = []; ui.context.videos = []; ui.context.fullscreenExpansions = 0;
  ui.run(`
    delay = async () => {};
    playDemoRecording = async (src, signal, text) => { recorded.push(src); setCaption(text); };
    showDemoVideo = async (src) => { videos.push(src); demoOwnsScene = true; };
    expandDemoSceneFullscreen = () => { fullscreenExpansions += 1; };
    moments = [{id:'pompeii', line:'What happened to Pompeii?', demo:{
      prompt:'Gizmo, what happened to Pompeii?', prompt_audio:'opening-kid.mp3',
      reply:'Pompeii was buried in ash.', reply_audio:'main.wav', video:'main.mp4',
      followup:{prompt:'How were the paintings still there?', audio:'followup-kid.mp3', fullscreen_during_prompt:true,
        video:'followup.mp4', reply_wait_ms:800, reply:'The ash protected them.', reply_audio:'followup.wav'},
    }}]; syncMoment('pompeii');
  `);
  await ui.run('sayMoment()');
  assert.deepEqual([...ui.context.recorded], ['opening-kid.mp3', 'main.wav', 'followup-kid.mp3', 'followup.wav']);
  assert.deepEqual([...ui.context.videos], ['main.mp4', 'followup.mp4']);
  assert.equal(ui.context.fullscreenExpansions, 1);
  assert.deepEqual([...ui.run('history.map(item => item.text)')], [
    'Gizmo, what happened to Pompeii?', 'Pompeii was buried in ash.',
    'How were the paintings still there?', 'The ash protected them.',
  ]);
});

test('drawing demo shows Jake before Umbriel recommends the easy drawing', async () => {
  const ui = await app();
  ui.context.recorded = []; ui.context.images = []; ui.context.fullscreenExpansions = 0;
  ui.context.holds = []; ui.context.sceneDismissals = 0;
  ui.run(`
    delay = async (milliseconds) => { if (milliseconds === 5000) holds.push(milliseconds); };
    playDemoRecording = async (src, signal, text) => { recorded.push(src); setCaption(text); };
    showDemoImage = async (src, subject) => { images.push([src, subject]); demoOwnsScene = true; };
    expandDemoSceneFullscreen = () => { fullscreenExpansions += 1; };
    dissolveScene = () => { sceneDismissals += 1; };
    moments = [{id:'draw', line:'What should I draw?', demo:{
      prompt:'Gizmo, what should I draw?', prompt_audio:'kid.mp3',
      reply:"You're always talking about Adventure Time, so I recommend Jake the Dog. His round body, simple legs, and big eyes make him easy and fun to draw.",
      reply_audio:'umbriel.wav', image:'jake.png', subject:'Jake the Dog from Adventure Time',
      fullscreen_after_reply:true, post_reply_hold_ms:5000,
    }}]; syncMoment('draw');
  `);
  await ui.run('sayMoment()');
  assert.deepEqual([...ui.context.recorded], ['kid.mp3', 'umbriel.wav']);
  assert.equal(JSON.stringify(ui.context.images), JSON.stringify([['jake.png', 'Jake the Dog from Adventure Time']]));
  assert.equal(ui.context.fullscreenExpansions, 1);
  assert.deepEqual([...ui.context.holds], [5000]);
  assert.equal(ui.context.sceneDismissals, 1);
  assert.equal(ui.element('caption').textContent, '');
  assert.match(ui.element('status').textContent, /Demo finished/);
});

test('plant demo keeps Camera moving while the single kid recording and Umbriel play', async () => {
  const ui = await app();
  ui.context.events = [];
  ui.element('camera-feed').pause = () => ui.context.events.push('pause:video');
  ui.run(`
    delay = async () => {};
    glass = {
      openDemoCamera(src) { events.push('open:' + src); return document.getElementById('camera-feed'); },
      closeCamera() { events.push('home'); }, syncReply() {},
    };
    startMedia = async () => events.push('video');
    waitForMediaTime = async (media, at) => events.push('cue:' + at);
    playDemoRecording = async (src, signal, text, timed, playbackRate = 1) => {
      events.push('audio:' + src);
      if (src === 'umbriel.wav') {
        events.push('reply-video-rate:' + document.getElementById('camera-feed').playbackRate);
        events.push('reply-audio-rate:' + playbackRate);
      }
      if (text) setCaption(text);
    };
    moments = [{id:'plant', line:"What's wrong with this plant?", demo:{
      prompt:"Gizmo, what's wrong with this plant?", prompt_audio:'question.mp3',
      reply:'The leaf looks damaged.', reply_audio:'umbriel.wav', reply_audio_rate:1,
      camera:{video:'plant.mp4', start_at:2.6, cues:[
        {at:3.05, prompt:"Gizmo, what's wrong with this plant?", audio:'question.mp3'},
      ]},
    }}]; syncMoment('plant');
  `);
  await ui.run('sayMoment()');
  assert.deepEqual([...ui.context.events], [
    'open:plant.mp4', 'video',
    'cue:3.05', 'audio:question.mp3',
    'audio:umbriel.wav', 'reply-video-rate:1', 'reply-audio-rate:1', 'pause:video', 'home',
  ]);
  assert.equal(ui.element('camera-feed').loop, false);
  assert.equal(ui.element('camera-feed').playbackRate, 1);
  assert.equal(ui.element('camera-feed').currentTime, 2.6);
  assert.deepEqual([...ui.run('history.map(item => item.text)')], [
    "Gizmo, what's wrong with this plant?",
    'The leaf looks damaged.',
  ]);
  assert.equal(ui.element('caption').textContent, '');
  assert.equal(ui.element('device').dataset.ptt, 'false');
  assert.match(ui.element('status').textContent, /Demo finished/);
});

test('math-check closes camera and reveals math without the Gizmo painting animation', async () => {
  const ui = await app();
  ui.context.events = [];
  ui.element('camera-feed').pause = () => ui.context.events.push('pause:video');
  ui.run(`
    delay = async (milliseconds) => events.push('wait:' + milliseconds);
    status = (text, state) => {
      events.push('status:' + state);
      document.getElementById('status').textContent = text;
    };
    glass = {
      openDemoCamera(src) { events.push('open:' + src); return document.getElementById('camera-feed'); },
      closeCamera() { events.push('home'); }, syncReply() {},
    };
    startMedia = async () => events.push('video');
    waitForMediaTime = async (media, at) => events.push('cue:' + at);
    playDemoRecording = async (src, signal, text, timed, playbackRate = 1) => {
      events.push('audio:' + src);
      if (src === 'umbriel.wav') events.push('reply-video-loop:' + document.getElementById('camera-feed').loop);
      if (text) setCaption(text);
    };
    moments = [{id:'mathcheck', line:'Did I get this right?', demo:{
      prompt:'Gizmo, did I get this right?', prompt_audio:'kid.mp3',
      reply:'Almost! Two blue parts out of four is two-fourths, or one-half.',
      reply_audio:'umbriel.wav', reply_audio_rate:1, math:{attempt:'2/3'},
      camera:{video:'fraction.mp4', start_at:0, home_wait_ms:1000, post_question_hold_ms:4000, reply_wait_ms:900, loop:true, cues:[
        {at:0.8, prompt:'Gizmo, did I get this right?', audio:'kid.mp3'},
      ]},
    }}]; syncMoment('mathcheck');
  `);
  ui.run("showDemoMath = () => events.push('math')");
  await ui.run('sayMoment()');
  assert.deepEqual([...ui.context.events], [
    'status:idle', 'wait:1000', 'status:idle', 'wait:120', 'open:fraction.mp4', 'wait:100', 'video',
    'cue:0.8', 'status:listening', 'audio:kid.mp3',
    'status:idle', 'wait:4000',
    'pause:video', 'home', 'math', 'status:playing', 'wait:900', 'status:playing',
    'audio:umbriel.wav', 'reply-video-loop:true', 'pause:video', 'status:idle',
  ]);
  assert.equal(ui.context.events.includes('status:thinking'), false);
  assert.equal(ui.element('camera-feed').loop, true);
  assert.equal(ui.element('camera-feed').currentTime, 0);
  assert.deepEqual([...ui.run('history.map(item => item.text)')], [
    'Gizmo, did I get this right?',
    'Almost! Two blue parts out of four is two-fourths, or one-half.',
  ]);
  assert.equal(ui.element('caption').textContent, '');
  assert.match(ui.element('status').textContent, /Demo finished/);
});

test('rainbow demo animates, gets interrupted, then zooms in for the simpler answer', async () => {
  const ui = await app();
  ui.context.events = [];
  ui.run(`
    delay = async (milliseconds) => events.push('wait:' + milliseconds);
    showDemoRainbow = (rainbow) => { events.push('rainbow:' + rainbow.focus); demoOwnsScene = true; };
    playDemoRecordingFor = async (src, signal, text, milliseconds) => {
      events.push('partial:' + src + ':' + milliseconds);
      setCaption(text);
    };
    playDemoRecording = async (src, signal, text) => {
      events.push('audio:' + src);
      if (text) setCaption(text);
    };
    moments = [{id:'rainbow', line:'How does a rainbow happen?', demo:{
      prompt:'Gizmo, how does a rainbow happen?', prompt_audio:'rainbow-kid.mp3',
      beats:[
        {
          reply:'Sunlight enters a raindrop and bends.', reply_audio:'rainbow-intro.wav',
          rainbow:{focus:'overview'},
          interruption:{after_ms:12600, prompt:'Wait, why does the light split?', audio:'rainbow-followup.mp3', think_wait_ms:1200},
        },
        {
          reply:'White sunlight is actually many colors traveling together.', reply_audio:'rainbow-split.wav',
          rainbow:{focus:'split'},
        },
      ],
    }}]; syncMoment('rainbow');
  `);
  await ui.run('sayMoment()');
  assert.deepEqual([...ui.context.events], [
    'wait:260', 'audio:rainbow-kid.mp3', 'wait:650',
    'rainbow:overview', 'partial:rainbow-intro.wav:12600', 'audio:rainbow-followup.mp3',
    'wait:1200', 'wait:180', 'rainbow:split', 'audio:rainbow-split.wav',
  ]);
  assert.deepEqual([...ui.run('history.map(item => item.text)')], [
    'Gizmo, how does a rainbow happen?',
    'Sunlight enters a raindrop and bends.',
    'Wait, why does the light split?',
    'White sunlight is actually many colors traveling together.',
  ]);
  assert.equal(ui.element('caption').textContent, '');
  assert.match(ui.element('status').textContent, /Demo finished/);
});

test('lab mode keeps the rail hidden', async () => {
  const ui = await app();
  ui.run('playMoments = false; moments = [{id:"birthday", line:"How many more days until my birthday?"}]; syncMoment("birthday")');
  assert.equal(ui.element('moments').hidden, true);
});

test('cycling a moment starts a new session without the previous id', async () => {
  const ui = await app();
  ui.run('moments = [{id:"birthday", line:"How many more days until my birthday?"}, {id:"draw", line:"What should I draw?"}]');
  ui.run('session = "b".repeat(32); momentId = "birthday"; momentIndex = 0; playMoments = true');
  await ui.run('selectMoment(1)');
  assert.equal(ui.run('momentId'), 'draw');
  const provision = ui.fetches.find(entry => entry.url === '/oddity/session');
  assert.ok(provision);
  assert.equal(provision.options.headers['X-Oddity-Moment'], 'draw');
  assert.equal(provision.options.headers['X-Oddity-Mode'], 'moment');
  assert.equal(provision.options.headers['X-Oddity-Session'], undefined);
});

test('live film uses its hosted recording as the stable audio clock', async () => {
  const ui = await app();
  ui.context.playback = [];
  ui.element('beat-dots').children = [];
  await ui.run(`
    showScene = async () => {};
    startMedia = async media => playback.push('play:' + media.id);
    mediaEnded = media => { playback.push('wait:' + media.id); return Promise.resolve(); };
    waitFilm = async () => playback.push('stream-clock');
    breathingRoom = async () => {};
    turn = 'turn'; ready = true; plan = [{}];
    queue = [{id:'beat', index:0, title:'Moon', narration:'Mostly gray.', subject:'Moon',
      visual:'film', film:{revision:1, duration:2, title:'Moon', timings:[]},
      audio:'/oddity/media/voice.wav', warnings:[], pause_seconds:0, interaction:null}];
    playQueue();
  `);
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.ok(ui.context.playback.includes('play:voice'));
  assert.ok(ui.context.playback.includes('wait:voice'));
  assert.equal(ui.context.playback.includes('stream-clock'), false);
});
