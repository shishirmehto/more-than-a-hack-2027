import {COLORS, clamp, frameFromTime, timecode, segmentAt, transition, project,
        nearestPlayer, timelineWindow, timelineFrame, timelineBins} from './core.mjs';

const $ = id => document.getElementById(id);
const video = $('video');
const CHUNK = 125;
const state = {manifest: null, frame: 0, playing: false, rate: 1, row: null,
  cache: new Map(), pending: new Map(), clockStart: 0, clockFrame: 0, objectURL: null,
  videoReady: false, timelineBounds: [0, 1800], drag: false, dragBounds: null,
  detailsKey: '', failedChunks: new Set(), pendingSeek: false, playToken: 0, requests: new Map()};

function notice(message) {
  $('notice').textContent = message;
  $('notice').hidden = !message;
}
function datasetNotice() {
  return state.manifest?.demo ? 'Synthetic demo · Generated tracks, tags, and predictions.' :
    state.manifest?.predictions_only ? 'Prediction files only · Tracking, homography, and automatic tags are not loaded. These labels are predictions, not ground truth.' : '';
}
function element(tag, className, text) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (text !== undefined) item.textContent = text;
  return item;
}
function option(select, value, label) {
  const item = document.createElement('option');
  item.value = value; item.textContent = label; select.append(item);
}
function canvasContext(canvas, width, height) {
  const dpr = window.devicePixelRatio || 1;
  if (canvas.width !== Math.round(width * dpr) || canvas.height !== Math.round(height * dpr)) {
    canvas.width = Math.round(width * dpr); canvas.height = Math.round(height * dpr);
  }
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);
  return ctx;
}
async function chunkAt(frame) {
  const index = Math.floor(frame / CHUNK);
  if (state.cache.has(index)) return state.cache.get(index);
  if (state.pending.has(index)) return state.pending.get(index);
  const controller = new AbortController();
  state.requests.set(index, controller);
  const promise = fetch(`/api/frames?start=${index * CHUNK}&count=${CHUNK}`, {signal:controller.signal}).then(async response => {
    if (!response.ok) throw new Error('Tracking could not be read. Check the local server and reload.');
    const data = await response.json();
    if (controller.signal.aborted) { const error = new Error('Seek superseded'); error.name = 'AbortError'; throw error; }
    state.cache.set(index, data.frames);
    // Keep a bounded cache around the current seek position.
    while (state.cache.size > 10) {
      const current = Math.floor(state.frame / CHUNK);
      const farthest = [...state.cache.keys()].sort((a, b) => Math.abs(b - current) - Math.abs(a - current))[0];
      state.cache.delete(farthest);
    }
    return data.frames;
  }).catch(error => {
    if (controller.signal.aborted) { const cancelled = new Error('Seek superseded'); cancelled.name = 'AbortError'; throw cancelled; }
    throw error;
  }).finally(() => {
    if (state.pending.get(index) === promise) { state.pending.delete(index); state.requests.delete(index); }
  });
  state.pending.set(index, promise);
  return promise;
}
function paintCurrentFrame() {
  if (state.manifest.predictions_only) {
    state.row = null; $('loading').textContent = 'Tracking not loaded';
    $('retry-tracking').hidden = true; drawSpatial(); return;
  }
  const index = Math.floor(state.frame / CHUNK), rows = state.cache.get(index);
  for (const [key, controller] of state.requests) {
    if (key !== index && !(state.playing && key === index + 1)) {
      controller.abort(); state.requests.delete(key); state.pending.delete(key);
    }
  }
  if (rows) {
    state.row = rows[state.frame - index * CHUNK];
    $('loading').textContent = 'Tracking ready';
    drawSpatial();
  } else {
    state.row = null;
    drawSpatial();
    $('loading').textContent = state.failedChunks.has(index) ? 'Tracking unavailable' : 'Loading tracking…';
    if (!state.failedChunks.has(index)) chunkAt(state.frame).then(() => {
      if (Math.floor(state.frame / CHUNK) === index) paintCurrentFrame();
    }).catch(error => {
      if (error.name === 'AbortError') return;
      state.failedChunks.add(index);
      if (Math.floor(state.frame / CHUNK) === index) { paintCurrentFrame(); notice(error.message); }
    });
  }
  $('retry-tracking').hidden = !state.failedChunks.has(index);
  if (state.playing && (index + 1) * CHUNK < state.manifest.n_frames && !state.failedChunks.has(index + 1)) {
    chunkAt((index + 1) * CHUNK).catch(error => { if (error.name !== 'AbortError') state.failedChunks.add(index + 1); });
  }
}
function videoCoversFrame(frame = state.frame) {
  return state.videoReady && Number.isFinite(video.duration) && frame / state.manifest.fps < video.duration;
}
function projectionFitsVideo() {
  return video.videoWidth === 1920 && video.videoHeight === 1080;
}
function paintVideoAvailability() {
  const outside = state.videoReady && !videoCoversFrame();
  $('video-placeholder').hidden = state.videoReady && !outside;
  $('video-placeholder').querySelector('h3').textContent = outside ? 'No video at this frame' : 'Your tactical view goes here';
  $('video-placeholder').querySelector('p').textContent = outside ?
    `${state.manifest?.predictions_only ? 'Predictions remain' : 'Tracking remains'} available. Choose a matching video to inspect this frame.` :
    `Open the matching local video to inspect it alongside the ${state.manifest?.predictions_only ? 'predictions' : 'tracking'}.`;
}
function setFrame(value, seekVideo = true) {
  if (!state.manifest || !Number.isFinite(value)) return;
  const frame = clamp(Math.round(value), 0, state.manifest.n_frames - 1);
  state.frame = frame;
  if (seekVideo) {
    state.clockStart = performance.now(); state.clockFrame = frame;
    if (videoCoversFrame(frame)) {
      const target = Math.min((frame + .1) / state.manifest.fps, Math.max(0, video.duration - .001));
      state.pendingSeek = video.seeking || Math.abs(video.currentTime - target) > 1e-7;
      if (state.pendingSeek) video.currentTime = target;
    }
  }
  if (state.videoReady && !videoCoversFrame(frame)) video.pause();
  paintVideoAvailability();
  if (document.activeElement !== $('frame-input')) $('frame-input').value = frame;
  $('scrubber').value = frame;
  $('scrubber').setAttribute('aria-valuetext', `Frame ${frame}, ${timecode(frame, state.manifest.fps)}`);
  $('time').textContent = timecode(frame, state.manifest.fps);
  $('video-frame').textContent = `FRAME ${String(frame).padStart(6, '0')}`;
  paintCurrentFrame(); drawTimeline(); renderDetails();
}
function paintPlayButton() {
  $('play').textContent = state.playing ? 'Ⅱ' : '▶';
  $('play').setAttribute('aria-label', state.playing ? 'Pause' : 'Play');
}
function pause() {
  state.playToken++; state.playing = false; video.pause(); paintPlayButton();
}
async function togglePlay() {
  if (!state.manifest) return;
  if (state.playing) return pause();
  if (state.frame >= state.manifest.n_frames - 1) setFrame(0);
  state.clockFrame = state.frame; state.clockStart = performance.now();
  const token = ++state.playToken;
  state.playing = true; paintPlayButton();
  if (videoCoversFrame()) {
    try { await video.play(); } catch {
      if (token === state.playToken) { pause(); notice('This video could not play. Try an MP4 with an H.264 video track.'); }
    }
  }
}
function clock(now) {
  if (state.playing && state.manifest && !videoCoversFrame()) {
    const next = state.clockFrame + Math.floor((now - state.clockStart) / 1000 * state.manifest.fps * state.rate);
    if (next !== state.frame) setFrame(next, false);
    if (next >= state.manifest.n_frames - 1) pause();
  }
  requestAnimationFrame(clock);
}
function syncFromVideo(seconds) {
  if (state.manifest && state.playing && videoCoversFrame() && !state.pendingSeek && !video.seeking && !video.paused) {
    const frame = frameFromTime(seconds, state.manifest.fps, state.manifest.n_frames);
    if (frame !== state.frame) setFrame(frame, false);
    if (frame === state.manifest.n_frames - 1) pause();
  }
}
function videoFrame(now, metadata) {
  syncFromVideo(metadata.mediaTime);
  video.requestVideoFrameCallback(videoFrame);
}
function step(delta) { pause(); setFrame(state.frame + delta); }
function navigateTransition(direction) {
  const source = state.manifest?.predictions[Number($('transition-source').value)];
  if (!source) return;
  const target = transition(source.segments, state.frame, direction);
  if (target !== null) { pause(); setFrame(target); }
}
function activeTags() {
  return state.manifest.tags.filter(tag => tag.start <= state.frame && tag.end > state.frame &&
    (!$('tag-filter').value || tag.code === $('tag-filter').value));
}
function renderDetails() {
  const m = state.manifest;
  if (!m) return;
  const segments = m.predictions.map(p => segmentAt(p.segments, state.frame));
  const tags = activeTags();
  const next = !tags.length && m.tags.find(tag => tag.start > state.frame && (!$('tag-filter').value || tag.code === $('tag-filter').value));
  const key = JSON.stringify([segments.map(s => s?.start), tags, next, $('tag-filter').value]);
  const source = m.predictions[Number($('transition-source').value)];
  $('prev-transition').disabled = !source || transition(source.segments, state.frame, -1) === null;
  $('next-transition').disabled = !source || transition(source.segments, state.frame, 1) === null;
  if (key === state.detailsKey) return;
  state.detailsKey = key;
  $('prediction-list').replaceChildren();
  if (!m.predictions.length) $('prediction-list').append(element('p', 'empty', 'No predictions loaded. Add --prediction path/to/file.csv when starting the viewer.'));
  for (let i = 0; i < m.predictions.length; i++) {
    const segment = segments[i];
    const row = element('div', 'prediction-item');
    const badge = element('span', `label-pill ${({H:'home', A:'away', D:'dead', X:'unknown'})[segment.label]}`, segment.label);
    const name = element('span', 'name', m.predictions[i].name); name.title = m.predictions[i].name;
    const duration = element('span', 'prediction-duration', `${((segment.end - segment.start) / m.fps).toFixed(2)} s`);
    duration.title = `Interval [${segment.start}, ${segment.end})`;
    row.append(badge, name, duration); $('prediction-list').append(row);
  }
  $('tag-count').textContent = `${tags.length} active`;
  $('tag-list').replaceChildren();
  if (!tags.length) {
    $('tag-list').append(element('p', 'empty', m.tags.length ? 'No active tags in this frame.' : 'No Smart Tagging file loaded.'));
    if (next) {
      const button = element('button', 'small', `Next: ${next.code} ↗`);
      button.addEventListener('click', () => { pause(); setFrame(next.start); }); $('tag-list').append(button);
    }
  }
  for (const tag of tags) {
    const card = element('div', 'tag-card');
    const button = element('button', '', timecode(tag.start, m.fps));
    button.title = `Seek to tag start, frame ${tag.start}`;
    button.addEventListener('click', () => { pause(); setFrame(tag.start); });
    card.append(button, element('strong', '', tag.code));
    card.append(element('p', '', Object.entries(tag.tags).map(([key, value]) => `${key}: ${value}`).join(' · ')));
    $('tag-list').append(card);
  }
}
function dot(ctx, x, y, radius, color, text, scale = 1) {
  ctx.beginPath(); ctx.arc(x, y, radius, 0, Math.PI * 2); ctx.fillStyle = color; ctx.fill();
  ctx.strokeStyle = '#101a1d'; ctx.lineWidth = 1.5 * scale; ctx.stroke();
  if (text) { ctx.font = `${10 * scale}px ui-monospace,monospace`; ctx.textAlign = 'center'; ctx.fillStyle = '#dce9e6'; ctx.fillText(text, x, y - radius - 5 * scale); }
}
function drawSpatial() {
  const row = state.row, m = state.manifest;
  if (!m) return;
  const canvas = $('pitch'), ctx = canvas.getContext('2d');
  const w = canvas.width, h = canvas.height, x = 40, y = 42, pw = w - 80, ph = pw * m.pitch.width / m.pitch.length;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = '#1c3732'; ctx.fillRect(x, y, pw, ph);
  for (let stripe = 0; stripe < 10; stripe += 2) { ctx.fillStyle = '#203c36'; ctx.fillRect(x + stripe * pw / 10, y, pw / 10, ph); }
  ctx.strokeStyle = '#6a8b79'; ctx.lineWidth = 1.5;
  ctx.strokeRect(x, y, pw, ph);
  ctx.beginPath(); ctx.moveTo(w / 2, y); ctx.lineTo(w / 2, y + ph); ctx.stroke();
  ctx.beginPath(); ctx.arc(w / 2, y + ph / 2, pw * 9.15 / m.pitch.length, 0, 2 * Math.PI); ctx.stroke();
  for (const side of [0, 1]) {
    const line = side ? x + pw : x;
    for (const [length, width] of [[16.5, 40.32], [5.5, 18.32]]) {
      const boxW = pw * length / m.pitch.length, boxH = ph * width / m.pitch.width;
      ctx.strokeRect(side ? line - boxW : line, y + (ph - boxH) / 2, boxW, boxH);
    }
    ctx.strokeRect(side ? line : line - 9, y + ph / 2 - 24, 9, 48);
  }
  ctx.font = '13px ui-monospace,monospace'; ctx.textAlign = 'left'; ctx.fillStyle = '#7e9c90';
  ctx.fillText(`${m.pitch.length} × ${m.pitch.width} m`, x, y + ph + 28);
  ctx.textAlign = 'right'; ctx.fillText('NORMALIZED PITCH COORDINATES', x + pw, y + ph + 28);
  if (row) {
    for (const player of row.players) dot(ctx, x + player.x * pw, y + player.y * ph, 8, COLORS[player.team], $('slots-toggle').checked ? String(player.slot) : '', 1.2);
    if (row.ball) dot(ctx, x + row.ball.x * pw, y + row.ball.y * ph, 5, '#f6df9b');
  }
  const nearest = row && nearestPlayer(row.players, row.ball, m.pitch);
  const unavailable = state.failedChunks.has(Math.floor(state.frame / CHUNK));
  $('player-count').textContent = m.predictions_only ? 'Not loaded' : row ? `${row.players.length} tracks` : unavailable ? 'Unavailable' : 'Loading…';
  $('ball-status').textContent = m.predictions_only ? 'Not loaded' : !row ? (unavailable ? 'Unavailable' : 'Loading…') : row.ball ? 'Visible' : 'Missing';
  $('ball-status').classList.toggle('missing', !!row && !row.ball);
  $('nearest-status').textContent = nearest ? `${nearest.team} #${nearest.slot} · ${nearest.distance.toFixed(1)} m` : '—';
  $('projection-status').textContent = row?.homography ? (row.reprojection_error?.toFixed(2) ?? '—') : 'Unavailable';
  const overlay = $('overlay');
  overlay.width = video.videoWidth || 1920; overlay.height = video.videoHeight || 1080;
  const oc = overlay.getContext('2d');
  oc.clearRect(0, 0, overlay.width, overlay.height);
  if (!row || state.pendingSeek || video.seeking || !videoCoversFrame() || !projectionFitsVideo() || !$('overlay-toggle').checked || !row.homography) return;
  for (const player of row.players) {
    const p = project(row.homography, player.x, player.y);
    if (p) dot(oc, p[0], p[1], 9, COLORS[player.team], $('slots-toggle').checked ? String(player.slot) : '', 1.5);
  }
  if (row.ball) { const p = project(row.homography, row.ball.x, row.ball.y); if (p) dot(oc, p[0], p[1], 7, '#f6df9b'); }
}
function drawTimeline() {
  const m = state.manifest, canvas = $('timeline');
  if (!m) return;
  const width = canvas.parentElement.clientWidth - 32;
  const height = 34 + (2 + m.predictions.length) * 27;
  canvas.style.height = `${height}px`;
  const ctx = canvasContext(canvas, width, height);
  const left = width < 550 ? 88 : 145, right = 12, plot = width - left - right;
  const [start, end] = state.dragBounds || timelineWindow(state.frame, Number($('zoom').value), m.fps, m.n_frames);
  state.timelineBounds = [start, end];
  state.timelineGeometry = {left, plot, width};
  const px = frame => left + (frame - start) / (end - start) * plot;
  ctx.font = '10px ui-monospace,monospace'; ctx.fillStyle = '#80959c'; ctx.textAlign = 'center';
  for (let i = 0; i <= 4; i++) {
    const frame = Math.round(start + i / 4 * (end - start));
    const at = px(frame);
    ctx.fillText(timecode(frame, m.fps).slice(0, -4), clamp(at, left + 20, width - 24), 12);
    ctx.strokeStyle = '#2c3b40'; ctx.beginPath(); ctx.moveTo(at, 23); ctx.lineTo(at, height); ctx.stroke();
  }
  const lanes = [
    {name: m.predictions_only ? 'Tracking not loaded' : 'Ball visible', intervals: m.visibility, color: item => item.label ? '#466c61' : '#745b38'},
    ...m.predictions.map(p => ({name: p.name, intervals: p.segments, color: item => COLORS[item.label]})),
    {name: 'Auto tags', intervals: m.tags, color: () => '#667d94'},
  ];
  lanes.forEach((lane, index) => {
    const y = 28 + index * 27;
    ctx.fillStyle = '#a4b5bb'; ctx.textAlign = 'left'; ctx.font = '10px -apple-system,sans-serif';
    let label = lane.name;
    while (ctx.measureText(label).width > left - 12 && label.length > 2) label = label.slice(0, -2) + '…';
    ctx.fillText(label, 0, y + 12);
    ctx.fillStyle = '#111c21'; ctx.fillRect(left, y, plot, 16);
    ctx.save(); ctx.beginPath(); ctx.rect(left, y, plot, 16); ctx.clip();
    if (index < lanes.length - 1) {
      for (const bin of timelineBins(lane.intervals, start, end, plot)) {
        ctx.fillStyle = bin.mixed ? '#c1ab7b' : lane.color(bin);
        ctx.fillRect(left + bin.x, y, bin.width, 16);
      }
    } else for (const item of lane.intervals) {
        if (item.end <= start || item.start >= end) continue;
        ctx.fillStyle = lane.color(item);
        ctx.fillRect(px(Math.max(start, item.start)), y, Math.max(1, px(Math.min(end, item.end)) - px(Math.max(start, item.start))), 16);
      }
    ctx.restore();
  });
  const playhead = px(state.frame);
  ctx.strokeStyle = '#f4dfae'; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.moveTo(playhead, 20); ctx.lineTo(playhead, height); ctx.stroke();
  ctx.fillStyle = '#f4dfae'; ctx.beginPath(); ctx.moveTo(playhead - 4, 18); ctx.lineTo(playhead + 4, 18); ctx.lineTo(playhead, 23); ctx.fill();
  $('window-label').textContent = `${timecode(start, m.fps)} – ${timecode(end, m.fps)} · ${m.fps} fps`;
}
function timelineSeek(event) {
  if (!state.timelineGeometry) return;
  const rect = $('timeline').getBoundingClientRect();
  const g = state.timelineGeometry;
  const x = (event.clientX - rect.left) * g.width / rect.width;
  if (x < g.left && !state.drag) return;
  pause(); setFrame(timelineFrame(x, g.left, g.plot, ...state.timelineBounds));
}
function prepareManifest(m) {
  state.manifest = m;
  $('match-title').textContent = m.title;
  $('mode-badge').textContent = m.demo ? 'Synthetic demo' : m.predictions_only ? 'Prediction files only' : 'Tactical dataset';
  $('dataset-info').textContent = `${m.n_frames.toLocaleString()} frames · ${m.fps} fps`;
  $('home-name').textContent = m.teams.H; $('away-name').textContent = m.teams.A;
  $('stage-label').textContent = `TACTICAL · ${m.fps} FPS`;
  $('overlay-toggle').disabled = !m.has_homography;
  $('slots-toggle').disabled = !!m.predictions_only;
  if (m.predictions_only) $('footer-info').textContent = 'CSV frame 0 = tactical timeline origin · Predictions only';
  $('total-time').textContent = `/ ${timecode(m.n_frames, m.fps)}`;
  $('scrubber').max = m.n_frames - 1; $('frame-input').max = m.n_frames - 1;
  $('visibility-summary').textContent = m.predictions_only ? 'Tracking not loaded' : `${(100 * m.ball_visible / m.n_frames).toFixed(1)}% visible`;
  if (datasetNotice()) notice(datasetNotice());
  if (m.predictions_only) $('gap-note').textContent = 'Tracking is not loaded; missing-ball intervals cannot be computed.';
  for (const block of m.half_blocks) option($('jump-half'), block.start, block.name);
  $('jump-half').hidden = !m.half_blocks.length;
  m.predictions.forEach((p, index) => option($('transition-source'), index, p.name));
  $('transition-source').disabled = !m.predictions.length;
  for (const code of [...new Set(m.tags.map(tag => tag.code))].sort()) option($('tag-filter'), code, code);
  const gaps = m.visibility.filter(item => !item.label);
  for (const gap of [...gaps].sort((a, b) => (b.end - b.start) - (a.end - a.start)).slice(0, 10)) {
    const button = element('button', 'gap-item');
    button.append(element('span', '', timecode(gap.start, m.fps)), element('span', '', `${((gap.end - gap.start) / m.fps).toFixed(2)} s ↗`));
    button.title = `Missing ball: frames ${gap.start}–${gap.end - 1}`;
    button.addEventListener('click', () => { pause(); setFrame(gap.start); }); $('gap-list').append(button);
  }
  if (!gaps.length) $('gap-list').append(element('p', 'empty', m.predictions_only ? 'No tracking file loaded.' : 'No missing ball observations.'));
  $('next-gap').disabled = !gaps.length;
  $('next-gap').addEventListener('click', () => {
    const next = gaps.find(g => g.start > state.frame) || gaps[0];
    if (next) { pause(); setFrame(next.start); }
  });
  const initial = Number(new URLSearchParams(location.search).get('frame'));
  setFrame(Number.isFinite(initial) ? initial : 0);
  if (state.objectURL) {
    if (video.readyState >= 1) loadVideoMetadata();
  } else if (m.video_url) { video.src = m.video_url; video.load(); }
}

$('play').addEventListener('click', togglePlay);
$('retry-tracking').addEventListener('click', () => {
  state.failedChunks.delete(Math.floor(state.frame / CHUNK)); paintCurrentFrame();
});
$('prev-frame').addEventListener('click', () => step(-1));
$('next-frame').addEventListener('click', () => step(1));
$('go-frame').addEventListener('click', () => { pause(); setFrame(Number($('frame-input').value)); $('frame-input').value = state.frame; });
$('frame-input').addEventListener('keydown', event => { if (event.key === 'Enter') $('go-frame').click(); });
$('scrubber').addEventListener('input', event => { pause(); setFrame(Number(event.target.value)); });
$('rate').addEventListener('change', () => {
  state.clockFrame = state.frame; state.clockStart = performance.now();
  state.rate = Number($('rate').value); video.playbackRate = state.rate;
});
$('zoom').addEventListener('change', drawTimeline);
$('slots-toggle').addEventListener('change', drawSpatial);
$('overlay-toggle').addEventListener('change', drawSpatial);
$('tag-filter').addEventListener('change', renderDetails);
$('transition-source').addEventListener('change', renderDetails);
$('prev-transition').addEventListener('click', () => navigateTransition(-1));
$('next-transition').addEventListener('click', () => navigateTransition(1));
$('jump-half').addEventListener('change', event => { if (event.target.value) { pause(); setFrame(Number(event.target.value)); event.target.value = ''; } });
$('help-button').addEventListener('click', () => $('help').showModal());
$('timeline').addEventListener('pointerdown', event => {
  if (!state.timelineGeometry) return;
  const rect = $('timeline').getBoundingClientRect();
  if (event.clientX - rect.left < state.timelineGeometry.left) return;
  state.dragBounds = [...state.timelineBounds]; state.drag = true;
  timelineSeek(event); $('timeline').setPointerCapture(event.pointerId);
});
$('timeline').addEventListener('pointermove', event => { if (state.drag) timelineSeek(event); });
function endTimelineDrag() { state.drag = false; state.dragBounds = null; drawTimeline(); }
$('timeline').addEventListener('pointerup', endTimelineDrag);
$('timeline').addEventListener('pointercancel', endTimelineDrag);
window.addEventListener('resize', () => { drawTimeline(); });
document.addEventListener('keydown', event => {
  if (!state.manifest || $('help').open || /INPUT|SELECT|TEXTAREA/.test(event.target.tagName) || event.ctrlKey || event.metaKey || event.altKey) return;
  if (event.code === 'Space' && event.target.tagName !== 'BUTTON') { event.preventDefault(); togglePlay(); }
  else if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); step((event.key === 'ArrowLeft' ? -1 : 1) * (event.shiftKey ? state.manifest.fps : 1)); }
  else if (event.key === '[' || event.key === ']') { event.preventDefault(); navigateTransition(event.key === '[' ? -1 : 1); }
  else if (event.key === '?') $('help').showModal();
});
for (const id of ['load-video', 'load-video-empty']) $(id).addEventListener('click', () => $('video-file').click());
$('video-file').addEventListener('change', event => {
  const file = event.target.files[0]; if (!file) return;
  pause(); state.videoReady = false;
  state.pendingSeek = false; paintVideoAvailability(); drawSpatial();
  if (state.objectURL) URL.revokeObjectURL(state.objectURL);
  state.objectURL = URL.createObjectURL(file); video.src = state.objectURL; video.load();
  $('video-status').textContent = file.name;
});
function loadVideoMetadata() {
  if (!state.manifest) return;
  state.videoReady = true;
  $('video-status').textContent = `${video.videoWidth} × ${video.videoHeight}`;
  const expected = state.manifest.n_frames / state.manifest.fps;
  const warnings = [];
  if (Math.abs(video.duration - expected) > 2 / state.manifest.fps)
    warnings.push(`Video duration differs from ${state.manifest.predictions_only ? 'the prediction timeline' : 'tracking'} (${video.duration.toFixed(2)} s vs ${expected.toFixed(2)} s). ${state.manifest.predictions_only ? 'Predictions remain' : 'Tracking remains'} available outside video coverage.`);
  if (state.manifest.has_homography && !projectionFitsVideo()) warnings.push('Tracking overlay disabled: calibration requires the original 1920 × 1080 video. No scaling is applied.');
  notice([...warnings, datasetNotice()].filter(Boolean).join(' '));
  video.playbackRate = state.rate; setFrame(state.frame);
}
video.addEventListener('loadedmetadata', loadVideoMetadata);
video.addEventListener('seeked', () => {
  state.pendingSeek = false; drawSpatial();
});
video.addEventListener('seeking', () => { state.pendingSeek = true; drawSpatial(); });
video.addEventListener('ended', pause);
video.addEventListener('error', () => {
  pause(); state.videoReady = false; state.pendingSeek = false; paintVideoAvailability(); drawSpatial();
  $('video-status').textContent = 'Video unavailable';
  notice(`The video could not be decoded. Open a local MP4 with an H.264 video track; ${state.manifest?.predictions_only ? 'prediction' : 'tracking'} inspection is still available.`);
});
if ('requestVideoFrameCallback' in video) video.requestVideoFrameCallback(videoFrame);
else video.addEventListener('timeupdate', () => syncFromVideo(video.currentTime));
requestAnimationFrame(clock);
fetch('/api/manifest').then(async response => {
  if (!response.ok) throw new Error('The local dataset could not be loaded. Check the server and reload.');
  prepareManifest(await response.json());
}).catch(error => { $('match-title').textContent = 'Workspace unavailable'; $('loading').textContent = ''; notice(error.message); });
