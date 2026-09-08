import test from 'node:test';
import assert from 'node:assert/strict';
import {BOOT_SLOTS, BOOT_UNIQUE, DEFAULT_STEP, SETTING_STEPS, bootFrameSrc, DeviceSettings, dimOpacity, preloadBootFrames} from '../gizmo_friend/static/oddity-glass.mjs';

test('up from home opens settings on volume', () => {
  const settings = new DeviceSettings();
  assert.equal(settings.navigate('up'), 'opened');
  assert.equal(settings.open, true);
  assert.equal(settings.focus, 'volume');
});

test('down from home is ignored so the body can open camera', () => {
  const settings = new DeviceSettings();
  assert.equal(settings.navigate('down'), 'ignored');
  assert.equal(settings.open, false);
});

test('up from volume moves to brightness; down past volume returns home', () => {
  const settings = new DeviceSettings();
  settings.navigate('up');
  assert.equal(settings.focus, 'volume');
  assert.equal(settings.navigate('up'), 'handled');
  assert.equal(settings.focus, 'brightness');
  assert.equal(settings.navigate('down'), 'handled');
  assert.equal(settings.focus, 'volume');
  assert.equal(settings.navigate('down'), 'closed');
  assert.equal(settings.open, false);
});

test('select grabs a row and rocker changes the step', () => {
  const settings = new DeviceSettings();
  settings.navigate('up');
  assert.equal(settings.select(), true);
  const before = settings.volume;
  settings.navigate('down');
  assert.equal(settings.volume, before - 1);
});

test('boot preload fetches every unique frame before the flipbook runs', () => {
  const srcs = [];
  class FakeImage {
    set src(value) { srcs.push(value); this._src = value; }
    get src() { return this._src; }
    decode() { return Promise.resolve(); }
  }
  const frames = preloadBootFrames(FakeImage);
  assert.equal(frames.length, BOOT_UNIQUE);
  assert.equal(srcs[0], bootFrameSrc(0));
  assert.equal(srcs[11], bootFrameSrc(11));
  assert.equal(srcs[14], bootFrameSrc(14));
});

test('first blink after the drop is 10 then 11 12 13', () => {
  assert.deepEqual(BOOT_SLOTS.slice(9, 16), [9, 10, 10, 10, 11, 12, 13]);
});

test('default brightness does not put a veil over home', () => {
  assert.equal(dimOpacity(DEFAULT_STEP, 'home'), 0);
  assert.equal(dimOpacity(SETTING_STEPS, 'home'), 0);
  assert.ok(dimOpacity(0, 'home') > 0);
});
