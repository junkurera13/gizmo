import test from 'node:test';
import assert from 'node:assert/strict';
import {orbitOutcome, trajectory} from '../gizmo_friend/static/oddity-orbit.mjs';
test('circular launch holds its radius through multiple revolutions', () => {
  const {points, outcome} = trajectory(1);
  assert.equal(outcome, 'circular');
  for (const [x,y] of points) assert.ok(Math.abs(Math.hypot(x,y)-1.4) < .0001);
});
test('suborbital launch reaches the surface; escape heads outward', () => {
  const slow = trajectory(.6), fast = trajectory(1.6);
  assert.equal(slow.outcome,'surface'); assert.ok(Math.hypot(...slow.points.at(-1)) <= 1);
  assert.equal(fast.outcome,'escape'); assert.ok(Math.hypot(...fast.points.at(-1)) > 6);
  assert.equal(orbitOutcome(.95),'elliptical'); assert.equal(orbitOutcome(1.2),'elliptical');
  assert.equal(orbitOutcome(Math.SQRT2),'escape');
  for (const speed of [NaN,Infinity,-1,4]) assert.throws(()=>trajectory(speed));
});
