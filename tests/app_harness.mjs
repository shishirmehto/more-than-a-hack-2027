// Runs the actual application controller against deterministic DOM/media doubles.
import fs from 'node:fs';
import vm from 'node:vm';
import * as core from '../inspector/static/core.mjs';

export function harness(options = {}) {
  const nodes = new Map();
  function node(id) {
    if (!nodes.has(id)) {
      const arcs = [], counts = {fillRect:0};
      const ctx = new Proxy({measureText: () => ({width: 1}), arc: (...args) => arcs.push(args), fillRect:()=>counts.fillRect++}, {
        get: (target, key) => target[key] ?? (() => {}),
      });
      nodes.set(id, {id, value: '0', checked: true, hidden: false, width: 840, height: 590,
        style: {}, textContent: '', children: [], listeners: {}, arcs, counts, classList: {toggle() {}},
        parentElement: {clientWidth: 1000}, getContext: () => ctx,
        querySelector: selector => node(`${id}:${selector}`),
        setAttribute() {}, append(...items) { this.children.push(...items); },
        replaceChildren() { this.children = []; },
        addEventListener(event, listener) { this.listeners[event] = listener; },
        getBoundingClientRect: () => ({left: 0, width: 968}),
        load() {}, pause() { this.paused = true; },
        play() { this.paused = false; return Promise.resolve(); },
        requestVideoFrameCallback(callback) { this.callback = callback; },
      });
    }
    return nodes.get(id);
  }
  const video = node('video');
  Object.assign(video, {duration: 72, videoWidth: 1920, videoHeight: 1080,
    seeking: false, currentTime: 0, paused: true});
  const document = {activeElement: null, getElementById: node,
    createElement: () => node(`generated${nodes.size}`), addEventListener() {}};
  const context = vm.createContext({...core, document,
    window: {devicePixelRatio: 1, addEventListener() {}},
    performance: {now: () => 0}, requestAnimationFrame() {},
    URL: {revokeObjectURL() {}, createObjectURL: () => 'blob:new'},
    location: {search: ''}, URLSearchParams, AbortController, fetch: options.fetch ?? (() => new Promise(() => {})), console});
  const source = fs.readFileSync(new URL('../inspector/static/app.js', import.meta.url), 'utf8')
    .replace(/^import[\s\S]*?from '\.\/core\.mjs';/, '');
  vm.runInContext(source + '\nglobalThis.api={state,setFrame,pause,togglePlay,videoFrame,drawSpatial,clock,renderDetails,prepareManifest};', context);
  const {api} = context;
  api.state.manifest = {n_frames:1800, fps:25, pitch:{length:105.3,width:68},
    predictions:[], tags:[], visibility:[], half_blocks:[],has_homography:true};
  api.state.videoReady = true;
  return {api, node, video, document};
}
