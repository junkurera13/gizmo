import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {createIceStore, gatherIce, viewerIceConfig} from '../gizmo_friend/static/cinema-ice.mjs';

test('empty ICE list stays empty so loopback can use host candidates', () => {
  assert.deepEqual(viewerIceConfig([]), {iceServers: []});
});

test('missing ICE falls back to public STUN', () => {
  assert.equal(viewerIceConfig(undefined).iceServers[0].urls, 'stun:stun.l.google.com:19302');
});

test('ice store resolves waiters when servers arrive', async () => {
  const ice = createIceStore();
  const pending = ice.config(1000);
  ice.set([{urls: 'turn:relay.example:80?transport=tcp', username: 'device', credential: 'secret'}]);
  const config = await pending;
  assert.equal(config.iceServers[0].urls, 'turn:relay.example:80?transport=tcp');
});

test('gatherIce resolves immediately when gathering is already complete', async () => {
  await gatherIce({iceGatheringState: 'complete', addEventListener() {}, removeEventListener() {}});
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
