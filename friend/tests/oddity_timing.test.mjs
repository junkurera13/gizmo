import test from 'node:test';
import assert from 'node:assert/strict';
import {captionChunks,captionAt} from '../gizmo_friend/static/oddity-timing.mjs';

test('long narration stays readable and keeps every word in order', () => {
  const text = 'Imagine an indestructible probe. It falls into Jupiter through layer after layer of clouds. The pressure grows, and eventually the hydrogen behaves very differently from the gas we know on Earth.';
  const chunks = captionChunks(text);
  assert.equal(chunks.join(' '), text);
  assert.ok(chunks.length > 1);
  assert.ok(chunks.every(c => c.length <= 95));
});
test('captions wait for a valid duration and follow pauses and rewinds', () => {
  assert.equal(captionAt(['first','second'], 0, NaN), 'first');
  assert.equal(captionAt(['first','second'], 9, 10), 'second');
  assert.equal(captionAt(['first','second'], 0, 10), 'first');
  assert.equal(captionAt(['first','second'], 10, 10), 'second');
  assert.equal(captionAt([], 0, 0), '');
});
