import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';

async function app() {
  const elements = new Map();
  const fetches = [];
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
      createTextNode:text=>({textContent:text}), createElement:()=>({}), addEventListener(){},
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
            {id:'birthday', line:'How many more sleeps until my birthday?', demo:{prompt:'Gizmo, how many more sleeps until my birthday?', reply:'Eleven more sleeps.', sleeps:11}},
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
  vm.runInContext('mountDevice = async () => {}; deviceReady = true; awake = true; socket = {readyState:1, send(){}};', context);
  return {element, context, fetches, run: code => vm.runInContext(code, context)};
}

test('embedded player shows the current kid line on the rail', async () => {
  const ui = await app();
  assert.equal(ui.run('playMoments'), true);
  ui.run('moments = [{id:"birthday", line:"How many more sleeps until my birthday?"}, {id:"draw", line:"What should I draw?"}]');
  ui.run('syncMoment("draw")');
  assert.equal(ui.element('moments').hidden, false);
  assert.equal(ui.element('moment-line').textContent, 'What should I draw?');
});

test('a single completed demo hides scenario navigation', async () => {
  const ui = await app();
  ui.run('moments = [{id:"birthday", line:"How many more sleeps until my birthday?", demo:{prompt:"Gizmo, how many more sleeps until my birthday?", reply:"Eleven more sleeps.", sleeps:11}}]; syncMoment("birthday")');
  assert.equal(ui.element('moment-prev').hidden, true);
  assert.equal(ui.element('moment-next').hidden, true);
});

test('only completed moments expose a playable demo', async () => {
  const ui = await app();
  ui.run('moments = [{id:"birthday", line:"How many more sleeps until my birthday?", demo:{prompt:"Gizmo, how many more sleeps until my birthday?", reply:"Eleven more sleeps.", sleeps:11}}, {id:"draw", line:"What should I draw?"}]');
  ui.run('syncMoment("birthday")');
  assert.equal(ui.element('moment-say').disabled, false);
  assert.equal(ui.element('moment-say').textContent, 'Play demo');
  ui.run('syncMoment("draw")');
  assert.equal(ui.element('moment-say').disabled, true);
  assert.equal(ui.element('moment-say').textContent, 'Coming soon');
});

test('lab mode keeps the rail hidden', async () => {
  const ui = await app();
  ui.run('playMoments = false; moments = [{id:"birthday", line:"How many more sleeps until my birthday?"}]; syncMoment("birthday")');
  assert.equal(ui.element('moments').hidden, true);
});

test('cycling a moment starts a new session without the previous id', async () => {
  const ui = await app();
  ui.run('moments = [{id:"birthday", line:"How many more sleeps until my birthday?"}, {id:"draw", line:"What should I draw?"}]');
  ui.run('session = "b".repeat(32); momentId = "birthday"; momentIndex = 0; playMoments = true');
  await ui.run('selectMoment(1)');
  assert.equal(ui.run('momentId'), 'draw');
  const provision = ui.fetches.find(entry => entry.url === '/oddity/session');
  assert.ok(provision);
  assert.equal(provision.options.headers['X-Oddity-Moment'], 'draw');
  assert.equal(provision.options.headers['X-Oddity-Mode'], 'moment');
  assert.equal(provision.options.headers['X-Oddity-Session'], undefined);
});
