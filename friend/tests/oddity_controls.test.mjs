import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';

// Exercise the real PTT lifecycle with a pending browser permission request.
// No real microphone, network request or generated media is used by these tests.
async function controller(getUserMedia) {
  const elements = new Map();
  function element(id) {
    if (!elements.has(id)) elements.set(id, {
      id, dataset:{}, style:{}, hidden:false, textContent:'', value:'',
      classList:{add(){},remove(){},contains(){return false;}},
      addEventListener(){}, setAttribute(){}, replaceChildren(){},
      pause(){}, load(){}, removeAttribute(){},
    });
    return elements.get(id);
  }
  const windowEvents = {};
  const document = {
    getElementById:element, querySelectorAll:()=>[], querySelector:()=>null,
    createTextNode:text=>({textContent:text}), createElement:()=>({}), addEventListener(){},
  };
  const window = {addEventListener:(name, fn)=>{windowEvents[name]=fn;}};
  const context = vm.createContext({document,window,navigator:{mediaDevices:{getUserMedia}},
    setTimeout,clearTimeout,setInterval,clearInterval,AbortController,DOMException,
    WebSocket:{OPEN:1}, MediaRecorder:class {}, Image:class {}, captionChunks:()=>[],captionAt:()=>'',console});
  window.MediaRecorder = context.MediaRecorder;
  let source = await fs.readFile(new URL('../gizmo_friend/static/oddity.js',import.meta.url),'utf8');
  source = source.replace(/^import .*;\r?\n/gm, '').replace(/\r?\nsyncPower\(\);[\s\S]*$/, '');
  vm.runInContext(source,context);
  vm.runInContext('awake = true; socket = {readyState:1, send(){}};',context);
  return {element,context,windowEvents,run:code=>vm.runInContext(code,context)};
}

test('press is immediate; releasing before permission resolves restores skin and closes late microphone', async () => {
  let allow, stopped=0;
  const request = new Promise(resolve=>{allow=resolve;});
  const app = await controller(()=>request);
  const pending = app.run('startRecording()');
  assert.equal(app.element('device').dataset.ptt,'true');
  app.run('stopRecording()');
  assert.equal(app.element('device').dataset.ptt,'false');
  allow({getTracks:()=>[{stop(){stopped++;}}]});
  await pending;
  assert.equal(stopped,1);
  assert.equal(app.element('device').dataset.ptt,'false');
});

test('permission denial restores the button and offers typing', async () => {
  const app = await controller(async()=>{throw new DOMException('Denied','NotAllowedError');});
  await app.run('startRecording()');
  assert.equal(app.element('device').dataset.ptt,'false');
  assert.match(app.element('notice').textContent,/declined/);
  assert.equal(app.element('listening').hidden,true);
});

test('pink button press shows the pressed skin even before the microphone opens', async () => {
  const app = await controller(()=>new Promise(()=>{}));
  app.run('awake = false');
  app.run('pressTalk()');
  assert.equal(app.element('device').dataset.ptt,'true');
  assert.equal(app.run('awake'),false);
  app.run('releaseTalk()');
  assert.equal(app.element('device').dataset.ptt,'false');
});

test('losing focus cancels a held press without sending an audio turn', async () => {
  let allow;
  const request = new Promise(resolve=>{allow=resolve;});
  const app = await controller(()=>request);
  const pending = app.run('startRecording()');
  app.windowEvents.blur();
  assert.equal(app.element('device').dataset.ptt,'false');
  assert.equal(app.run('held'),false);
  allow({getTracks:()=>[{stop(){}}]});
  await pending;
});
