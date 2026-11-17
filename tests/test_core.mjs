import test from 'node:test';
import assert from 'node:assert/strict';
import {frameFromTime, timecode, segmentAt, transition, project, nearestPlayer,
        timelineWindow, timelineFrame, timelineBins} from '../inspector/static/core.mjs';

const segments = [{start:0,end:10,label:'H'}, {start:10,end:20,label:'D'}, {start:20,end:25,label:'A'}];
test('video time maps to the correct zero-based frame, including floating-point boundaries', () => {
  assert.equal(frameFromTime(0, 25, 100), 0);
  assert.equal(frameFromTime(.04, 25, 100), 1);
  assert.equal(frameFromTime(.039, 25, 100), 0);
  assert.equal(frameFromTime(1.16, 25, 100), 29);
  assert.equal(frameFromTime(4, 25, 100), 99);
  assert.equal(timecode(11185, 25), '07:27.400');
});
test('prediction intervals use exclusive ends and navigation skips the current boundary', () => {
  assert.equal(segmentAt(segments, 9).label, 'H');
  assert.equal(segmentAt(segments, 10).label, 'D');
  assert.equal(segmentAt(segments, 25), null);
  assert.equal(transition(segments, 10, 1), 20);
  assert.equal(transition(segments, 10, -1), 0);
  assert.equal(transition(segments, 0, -1), null);
  assert.equal(transition(segments, 24, 1), null);
});
test('projection uses normalized coordinates and rejects singular/invalid transforms', () => {
  const point = project([1920,0,10,0,1080,20,0,0,1], .5, .5);
  assert.ok(Math.abs(point[0] - 970) < 1e-9 && Math.abs(point[1] - 560) < 1e-9);
  assert.equal(project(null, .5, .5), null);
  assert.equal(project([1,0,0,0,1,0,0,0,0], .5, .5), null);
  assert.equal(project([1,0,0,0,1,0,0,0,NaN], .5, .5), null);
  assert.equal(project([0,0,40,0,0,60,0,0,1], .5, .5), null);
  assert.equal(project(Array(9).fill(0), .5, .5), null);
  for (const scale of [1e-200, 1e200, -7]) {
    const point = project([1920,0,10,0,1080,20,0,0,1].map(value => value * scale), .5, .5);
    assert.ok(Math.abs(point[0] - 970) < 1e-9 && Math.abs(point[1] - 560) < 1e-9);
  }
});
test('nearest-player evidence scales axes to metres, handles missing ball, and ignores slot order', () => {
  const players = [{slot:1,team:'H',x:.1,y:0}, {slot:2,team:'A',x:0,y:.12}];
  const pitch = {length:105.3,width:68}, ball = {x:0,y:0};
  assert.equal(nearestPlayer(players, ball, pitch).slot, 2);
  assert.equal(nearestPlayer([...players].reverse(), ball, pitch).slot, 2);
  assert.equal(nearestPlayer(players, null, pitch), null);
  assert.equal(nearestPlayer([], ball, pitch), null);
});
test('zoom windows and timeline clicks are clamped at match edges', () => {
  assert.deepEqual(timelineWindow(20, 20, 25, 1800), [0,500]);
  assert.deepEqual(timelineWindow(1799, 20, 25, 1800), [1300,1800]);
  assert.deepEqual(timelineWindow(900, 0, 25, 1800), [0,1800]);
  assert.equal(timelineFrame(100, 100, 500, 1300, 1800), 1300);
  assert.equal(timelineFrame(350, 100, 500, 1300, 1800), 1550);
  assert.equal(timelineFrame(600, 100, 500, 1300, 1800), 1799);
});
test('overview bins disclose hidden state changes and retain exact labels when zoomed in', () => {
  const bins=timelineBins(segments,0,25,5);
  assert.deepEqual(bins.map(b=>b.label),['H','D','A']);
  assert.equal(timelineBins(segments,0,25,1)[0].mixed,true);
  const fragmented=Array.from({length:199319},(_,i)=>({start:i,end:i+1,label:i%2?'H':'A'}));
  assert.equal(timelineBins(fragmented,0,199319,800).every(b=>b.mixed),true);
  assert.equal(timelineBins(fragmented,0,5,5).every(b=>!b.mixed),true);
  let accesses=0;
  const counted=new Proxy(fragmented,{get(target,key){if(/^\d+$/.test(String(key)))accesses++; return target[key];}});
  assert.equal(transition(counted,100000,1),100001); assert.equal(transition(counted,100000,-1),99999);
  assert.ok(accesses<50);
});
