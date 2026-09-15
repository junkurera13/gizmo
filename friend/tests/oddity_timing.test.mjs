import test from 'node:test';
import assert from 'node:assert/strict';
import {MAX_CAPTION_CHARS,captionChunks,captionAt,captionTimings,timedCaptionAt,wrapCaption} from '../gizmo_friend/static/oddity-timing.mjs?v=gate45';

test('long narration stays readable and keeps every word in order', () => {
  const text = 'Imagine an indestructible probe. It falls into Jupiter through layer after layer of clouds. The pressure grows, and eventually the hydrogen behaves very differently from the gas we know on Earth.';
  const chunks = captionChunks(text);
  assert.equal(chunks.join(' '), text);
  assert.ok(chunks.length > 1);
  assert.ok(chunks.every(c => c.length <= MAX_CAPTION_CHARS));
});
test('cinema captions page a long magma sentence into the band', () => {
  const text = "Pressure builds until the gas-rich magma forces its way up through the mountain's central vent.";
  const chunks = wrapCaption(text);
  assert.ok(chunks.length > 1);
  assert.ok(chunks.every(c => c.length <= MAX_CAPTION_CHARS));
  assert.equal(chunks.join(' '), text);
  const timed = captionTimings([{start: 0, end: 8, narration: text}]);
  assert.equal(timed.length, chunks.length);
  assert.equal(timed[0].start, 0);
  assert.equal(timed.at(-1).end, 8);
  assert.ok(timed.every(row => row.narration.length <= MAX_CAPTION_CHARS));
});
test('already short caption cues are left alone', () => {
  const timed = captionTimings([{start: 0, end: 2, narration: 'Pressure builds.'}]);
  assert.deepEqual(timed, [{start: 0, end: 2, narration: 'Pressure builds.'}]);
});
test('captions wait for a valid duration and follow pauses and rewinds', () => {
  assert.equal(captionAt(['first','second'], 0, NaN), 'first');
  assert.equal(captionAt(['first','second'], 9, 10), 'second');
  assert.equal(captionAt(['first','second'], 0, 10), 'first');
  assert.equal(captionAt(['first','second'], 10, 10), 'second');
  assert.equal(captionAt([], 0, 0), '');
});
test('timed captions swap at measured speech boundaries', () => {
  const timed = [[0.25, 'Gizmo,'], [1.29, 'what happened to'], [2.26, 'Pompeii']];
  assert.equal(timedCaptionAt(timed, 0), '');
  assert.equal(timedCaptionAt(timed, 0.4), 'Gizmo,');
  assert.equal(timedCaptionAt(timed, 1.5), 'what happened to');
  assert.equal(timedCaptionAt(timed, 3), 'Pompeii');
  assert.equal(timedCaptionAt([], 1), '');
});
