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
      id, dataset:{}, style:{}, hidden: id === 'moments' || id === 'preview-gate',
      textContent:'', value:'',
      classList:{add(){},remove(){},contains(){return false;},toggle(){}},
      addEventListener(){}, setAttribute(){}, replaceChildren(){},
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
    captionChunks:()=>[], captionAt:()=>'', console, URLSearchParams, JSON,
  });
  context.globalThis = context;
  let source = await fs.readFile(new URL('../gizmo_friend/static/oddity.js', import.meta.url), 'utf8');
  source = source.replace(/^import .*;\r?\n/gm, '').replace(/\r?\nsyncPower\(\);[\s\S]*$/, '');
  vm.runInContext(source, context);
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
  assert.equal(ui.element('caption').textContent, "Eleven more days. That's close enough to start getting excited. Your birthday will be here before you know it.");
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
  assert.equal(ui.element('caption').textContent, 'Three');
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
