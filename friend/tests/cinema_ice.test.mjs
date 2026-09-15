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
