import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {
  candidateIsRelay,
  createIceStore,
  gatherIce,
  sdpHasCandidate,
  viewerIceConfig,
} from '../gizmo_friend/static/cinema-ice.mjs';

test('empty ICE list stays empty so loopback can use host candidates', () => {
  assert.deepEqual(viewerIceConfig([]), {iceServers: []});
});

test('missing ICE falls back to public STUN', () => {
  assert.equal(viewerIceConfig(undefined).iceServers[0].urls, 'stun:stun.l.google.com:19302');
});

test('ice store resolves waiters when servers arrive', async () => {
  const ice = createIceStore();
  const pending = ice.config(1000);
  ice.set([{urls: 'turns:relay.example:443?transport=tcp', username: 'device', credential: 'secret'}]);
  const config = await pending;
  assert.equal(config.iceServers[0].urls, 'turns:relay.example:443?transport=tcp');
});

test('ice store does not let an empty plan payload wipe TURN servers', async () => {
  const ice = createIceStore();
  ice.set([{urls: 'turns:relay.example:443?transport=tcp'}]);
  ice.set([]);
  const config = await ice.config(10);
  assert.equal(config.iceServers[0].urls, 'turns:relay.example:443?transport=tcp');
});

test('gatherIce resolves immediately when gathering is already complete', async () => {
  await gatherIce({iceGatheringState: 'complete', addEventListener() {}, removeEventListener() {}});
});

function fakePeer(sdp = '') {
  const listeners = new Map();
  return {
    iceGatheringState: 'gathering',
    localDescription: {sdp},
    addEventListener(name, fn) {
      const list = listeners.get(name) || [];
      list.push(fn);
      listeners.set(name, list);
    },
    removeEventListener(name, fn) {
      listeners.set(name, (listeners.get(name) || []).filter(item => item !== fn));
    },
    emit(name, event) {
      for (const fn of listeners.get(name) || []) fn(event);
    },
  };
}

test('relay lines are detected in SDP and ICE candidates', () => {
  assert.equal(sdpHasCandidate('v=0\r\na=candidate:1 1 UDP 1 1.1.1.1 9 typ host\r\n'), true);
  assert.equal(sdpHasCandidate('v=0\r\n'), false);
  assert.equal(candidateIsRelay({candidate: 'candidate:2 1 UDP 1 2.2.2.2 9 typ relay raddr 0.0.0.0 rport 0'}), true);
  assert.equal(candidateIsRelay({candidate: 'candidate:1 1 UDP 1 1.1.1.1 9 typ host'}), false);
});

test('gatherIce resolves on the first relay candidate without waiting for complete', async () => {
  const pc = fakePeer('v=0\r\na=candidate:1 1 UDP 1 1.1.1.1 9 typ host\r\n');
  const pending = gatherIce(pc, 1000);
  pc.emit('icecandidate', {
    candidate: {candidate: 'candidate:2 1 UDP 1 2.2.2.2 9 typ relay raddr 0.0.0.0 rport 0'},
  });
  await pending;
  assert.equal(pc.iceGatheringState, 'gathering');
});

test('gatherIce timeout posts the offer if any candidate is already in the SDP', async () => {
  const pc = fakePeer('v=0\r\na=candidate:1 1 UDP 1 1.1.1.1 9 typ host\r\n');
  await gatherIce(pc, 20);
});

test('gatherIce still times out when no candidate was gathered', async () => {
  const pc = fakePeer('v=0\r\n');
  await assert.rejects(() => gatherIce(pc, 20), /Connection timed out/);
});

test('cinema skins do not ship the rocket poster or play-with-sound overlay', async () => {
  const files = [
    '../gizmo_friend/static/cinema.html',
    '../gizmo_friend/static/cinema.js',
    '../gizmo_friend/static/cinema.css',
    '../gizmo_friend/static/oddity.html',
    '../gizmo_friend/static/oddity-cinema.mjs',
    '../gizmo_friend/static/oddity-device.css',
  ];
  for (const file of files) {
    const text = await fs.readFile(new URL(file, import.meta.url), 'utf8');
    assert.equal(text.includes('Play with sound'), false, file);
    assert.equal(text.includes('cinema-poster.jpg'), false, file);
    assert.equal(text.includes('Bringing it to life'), false, file);
  }
});

test('cinema glass uses a solid black caption band and on-device PTT', async () => {
  const cinemaHtml = await fs.readFile(new URL('../gizmo_friend/static/cinema.html', import.meta.url), 'utf8');
  const cinemaCss = await fs.readFile(new URL('../gizmo_friend/static/cinema.css', import.meta.url), 'utf8');
  const cinemaJs = await fs.readFile(new URL('../gizmo_friend/static/cinema.js', import.meta.url), 'utf8');
  const oddityHtml = await fs.readFile(new URL('../gizmo_friend/static/oddity.html', import.meta.url), 'utf8');
  const oddityCss = await fs.readFile(new URL('../gizmo_friend/static/oddity-device.css', import.meta.url), 'utf8');
  const oddityCinema = await fs.readFile(new URL('../gizmo_friend/static/oddity-cinema.mjs', import.meta.url), 'utf8');

  assert.equal(cinemaCss.includes('height:var(--caption-band);background:#000'), true);
  assert.equal(cinemaCss.includes('background:#05111f'), false);
  assert.equal(cinemaCss.includes('#progress'), false);
  assert.equal(cinemaCss.includes('#f5a3b9'), false);
  assert.equal(cinemaHtml.includes('id="progress"'), false);
  assert.equal(cinemaHtml.includes('<svg'), false);
  assert.equal(cinemaHtml.includes('class="device-talk"'), true);
  assert.equal(cinemaHtml.includes('device-reference-ptt-pressed.png'), true);
  assert.equal(cinemaHtml.includes('Hold the pink button on the device to talk'), false);
  assert.equal(cinemaHtml.includes('Ask something. See where it takes us.'), false);
  assert.equal(cinemaHtml.includes('What are you curious about?'), false);
  assert.equal(cinemaHtml.includes('You can interrupt anytime'), false);
  assert.equal(cinemaHtml.includes('placeholder='), false);
  assert.equal(cinemaHtml.includes('id="hint"'), false);
  assert.equal(cinemaJs.includes("dataset.ptt"), true);
  assert.equal(cinemaJs.includes('mouseleave'), true);
  assert.equal(cinemaJs.includes('touchstart'), true);
  assert.equal(cinemaJs.includes('mousedown'), true);
  assert.equal(cinemaJs.includes("$('ptt')"), false);
  assert.equal(cinemaJs.includes('catch(error){held=false;setPressed(false)'), false);

  assert.equal(oddityCss.includes('height:20%;z-index:2;background:#000'), true);
  assert.equal(oddityCss.includes('background:#05111f'), false);
  assert.equal(oddityCss.includes('#cinema-progress'), false);
  assert.equal(oddityHtml.includes('id="cinema-talk"'), false);
  assert.equal(oddityHtml.includes('id="cinema-progress"'), false);
  assert.equal(oddityHtml.includes('class="device-control device-talk"'), true);
  assert.equal(oddityHtml.includes('Ask something. See where it takes us.'), false);
  assert.equal(oddityHtml.includes('Hold the pink button on the device to talk'), false);
  assert.equal(oddityHtml.includes('What are you curious about?'), false);
  assert.equal(oddityHtml.includes('cinema-hint'), false);
  assert.equal(oddityCinema.includes('progress.firstElementChild'), false);
  assert.equal(oddityCinema.includes('mouseleave'), true);
  assert.equal(oddityCinema.includes('Ask something. See where it takes us.'), false);
  assert.equal(oddityCinema.includes('Where does that take your curiosity?'), false);
  assert.equal(oddityCinema.includes('placeholder'), false);
  const cinemaCaption = oddityCss.split('.stage.cinema-mode .caption{')[1].split('}')[0];
  assert.equal(cinemaCaption.includes('overflow:hidden'), true);
  assert.equal(cinemaCaption.includes('overflow:auto'), false);
  assert.equal(cinemaCss.includes('overflow:hidden'), true);
  assert.equal(cinemaJs.includes('captionTimings'), true);
  assert.equal(oddityCinema.includes('captionTimings'), true);
});

test('browser cinema paths wait for a non-empty ICE list and load the TURNS gatherer', async () => {
  const cinema = await fs.readFile(new URL('../gizmo_friend/static/cinema.js', import.meta.url), 'utf8');
  const oddityCinema = await fs.readFile(new URL('../gizmo_friend/static/oddity-cinema.mjs', import.meta.url), 'utf8');
  const oddity = await fs.readFile(new URL('../gizmo_friend/static/oddity.js', import.meta.url), 'utf8');
  for (const text of [cinema, oddityCinema, oddity]) {
    assert.equal(text.includes('cinema-ice.mjs?v=turns1'), true);
    assert.equal(text.includes('event.ice_servers.length'), true);
    assert.equal(text.includes("if (event.ice_servers) ice.set"), false);
  }
});
