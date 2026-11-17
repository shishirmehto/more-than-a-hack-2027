import test from 'node:test';
import assert from 'node:assert/strict';
import {harness} from './app_harness.mjs';

test('short video cannot overwrite a later tracking selection; tracking clock remains available', async () => {
  const {api,video,node} = harness(); video.duration = 10;
  api.setFrame(1000); video.listeners.seeked(); api.videoFrame(0,{mediaTime:9.999});
  assert.equal(api.state.frame,1000); assert.equal(node('video-placeholder').hidden,false);
  await api.togglePlay(); api.clock(1000);
  assert.equal(api.state.frame,1025); assert.equal(video.paused,true);
});
test('long video pauses at the last tracking frame', async () => {
  const {api,video} = harness(); video.duration = 100;
  api.setFrame(1798); video.listeners.seeked(); await api.togglePlay();
  api.videoFrame(0,{mediaTime:75});
  assert.equal(api.state.frame,1799); assert.equal(api.state.playing,false); assert.equal(video.paused,true);
});
test('incompatible video dimensions warn and suppress projection', () => {
  const {api,video,node} = harness(); video.videoWidth=960; video.videoHeight=540;
  video.listeners.loadedmetadata(); video.listeners.seeked();
  api.state.row={players:[{x:.5,y:.5,team:'H',slot:1}],ball:null,
    homography:[1600,0,160,0,900,90,0,0,1],reprojection_error:.25};
  api.drawSpatial();
  assert.match(node('notice').textContent,/overlay disabled.*1920/);
  assert.equal(node('overlay').arcs.length,0);
});
test('paused stale callbacks preserve exact selected frame and pending seeks suppress overlays', () => {
  const {api,video,node} = harness(); api.setFrame(305);
  api.videoFrame(0,{mediaTime:0}); video.listeners.seeked();
  assert.equal(api.state.frame,305);
  api.state.row={players:[{x:.5,y:.5,team:'H',slot:1}],ball:null,
    homography:[1600,0,160,0,900,90,0,0,1],reprojection_error:.25};
  video.listeners.seeking(); assert.equal(node('overlay').arcs.length,0);
  video.listeners.seeked(); assert.equal(node('overlay').arcs.length,1);
  api.setFrame(305); assert.equal(api.state.pendingSeek,false);
});
test('pause during unresolved media play is not undone by its resolution', async () => {
  const {api,video} = harness(); let resolve;
  video.play=()=>{video.paused=false; return new Promise(r=>{resolve=r;});};
  const pending=api.togglePlay(); api.pause(); resolve(); await pending;
  assert.equal(api.state.playing,false); assert.equal(video.paused,true);
});
test('video selected before manifest loading survives startup and early media events', () => {
  const {api,video,node} = harness(); const manifest=api.state.manifest;
  api.state.manifest=null;
  assert.doesNotThrow(()=>node('video-file').listeners.change({target:{files:[{name:'synthetic.mp4'}]}}));
  assert.equal(video.src,'blob:new');
  video.readyState=1; video.listeners.loadedmetadata();
  assert.equal(api.state.videoReady,false);
  assert.doesNotThrow(()=>{video.listeners.seeking(); video.listeners.seeked(); api.renderDetails();});
  api.prepareManifest({...manifest,title:'Test',teams:{H:'Home',A:'Away'},ball_visible:1800,
    video_url:'/video',demo:true});
  assert.equal(video.src,'blob:new'); assert.equal(api.state.videoReady,true);
});
test('next tag reflects the current gap even with no predictions', () => {
  const {api,node} = harness();
  node('tag-filter').value='';
  api.state.manifest.tags=[{start:100,end:110,code:'First',tags:{}},{start:200,end:210,code:'Second',tags:{}}];
  api.setFrame(0); assert.match(node('tag-list').children[1].textContent,/First/);
  api.setFrame(150); const button=node('tag-list').children[1];
  assert.match(button.textContent,/Second/); button.listeners.click(); assert.equal(api.state.frame,200);
  api.setFrame(250); assert.equal(node('tag-list').children.length,1);
});
test('failed chunks display unavailable on revisit and support retry', () => {
  const {api,node} = harness(); api.state.failedChunks.add(4); api.setFrame(500);
  assert.equal(node('loading').textContent,'Tracking unavailable');
  assert.equal(node('ball-status').textContent,'Unavailable');
  assert.equal(node('player-count').textContent,'Unavailable');
  assert.equal(node('retry-tracking').hidden,false);
  node('retry-tracking').listeners.click();
  assert.equal(api.state.failedChunks.has(4),false);
  assert.equal(node('loading').textContent,'Loading tracking…');
});
test('late failure from a previous seek cannot overwrite ready tracking', async () => {
  let reject;
  const {api,node} = harness({fetch:url => url.includes('/api/frames') ? new Promise((_,r)=>{reject=r;}) : new Promise(()=>{})});
  api.setFrame(0);
  api.state.cache.set(4,Array.from({length:125},(_,i)=>({frame:500+i,players:[],ball:null,homography:null})));
  api.setFrame(500); reject(new Error('Previous window failed'));
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(node('loading').textContent,'Tracking ready');
  assert.equal(node('ball-status').textContent,'Missing');
  assert.equal(node('retry-tracking').hidden,true);
  assert.equal(api.state.failedChunks.has(0),false);
});
test('rapid seeks cancel old requests and keep at most current plus prefetch work', async () => {
  const requests=[];
  const {api,node}=harness({fetch:(url,options)=>url.includes('/api/frames') ? new Promise((resolve,reject)=>{
    requests.push({url,resolve,signal:options.signal});
    options.signal.addEventListener('abort',()=>reject(new Error('cancelled transport')));
  }) : new Promise(()=>{})});
  api.state.manifest.n_frames=199319; api.state.playing=true;
  for(let i=0;i<160;i++){ api.setFrame(i*125); assert.ok(api.state.pending.size<=2); }
  assert.ok(requests.filter(r=>!r.signal.aborted).length<=2);
  const current=requests.findLast(r=>!r.signal.aborted && r.url.includes('start=19875&'));
  current.resolve({ok:true,json:async()=>({frames:Array.from({length:125},(_,i)=>({frame:19875+i,players:[],ball:null,homography:null}))})});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(api.state.failedChunks.size,0); assert.equal(node('loading').textContent,'Tracking ready');
});
test('full-match fragmented overview paints at pixel scale and retains exact detail label', () => {
  const {api,node}=harness(); const n=199319;
  api.state.manifest.n_frames=n;
  const segments=Array.from({length:n},(_,i)=>({start:i,end:i+1,label:i%2?'H':'A'}));
  api.state.manifest.predictions=Array.from({length:8},(_,i)=>({name:`p${i}`,segments}));
  api.setFrame(100000);
  assert.ok(node('timeline').counts.fillRect<10000);
  assert.equal(node('prediction-list').children[0].children[0].textContent,'A');
});
test('prediction-only mode shows supplied labels and explicitly absent tracking', () => {
  const {api,node,video}=harness(); api.state.videoReady=false;
  api.prepareManifest({...api.state.manifest,predictions_only:true,demo:false,title:'Prediction timelines',
    teams:{H:'Home',A:'Away'},ball_visible:null,video_url:null,has_homography:false,
    predictions:[{name:'supplied_csv',segments:[{start:0,end:1800,label:'A'}]}]});
  api.setFrame(850);
  assert.equal(node('mode-badge').textContent,'Prediction files only');
  assert.equal(node('loading').textContent,'Tracking not loaded');
  assert.equal(node('ball-status').textContent,'Not loaded');
  assert.equal(node('player-count').textContent,'Not loaded');
  assert.equal(node('next-gap').disabled,true);
  assert.equal(api.state.pending.size,0); assert.equal(api.state.row,null);
  assert.equal(node('prediction-list').children[0].children[0].textContent,'A');
  assert.match(node('notice').textContent,/not ground truth/);
  assert.match(node('video-placeholder:p').textContent,/alongside the predictions/);
  assert.equal(node('overlay-toggle').disabled,true);
  assert.equal(node('slots-toggle').disabled,true);
  video.duration=5; video.videoWidth=960; video.videoHeight=540;
  video.listeners.loadedmetadata();
  assert.match(node('notice').textContent,/prediction timeline/);
  assert.match(node('notice').textContent,/Predictions remain/);
  assert.doesNotMatch(node('notice').textContent,/Tracking remains|calibration requires/);
  assert.match(node('video-placeholder:p').textContent,/Predictions remain/);
  video.listeners.error(); assert.match(node('notice').textContent,/prediction inspection/);
});
