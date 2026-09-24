// Browser-independent state-machine tests. No real microphone or network access.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const source = readFileSync(new URL('../kevin/static/voice.js', import.meta.url), 'utf8');
const {initVoice} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const tick = () => new Promise(resolve => setImmediate(resolve));

function setup({available = true, getUserMedia, fetcher, api} = {}) {
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, {listeners: {}, disabled:false, hidden:false, value:'', textContent:'', files:[],
      addEventListener(type, listener) { this.listeners[type] = listener; }, setAttribute() {}});
    return elements.get(id);
  };
  let stopped = 0, applied = 0, uploads = 0;
  const stream = {getTracks: () => [{stop: () => stopped++}]};
  const calls = [];
  globalThis.document = {getElementById: element};
  globalThis.window = {MediaRecorder: true, addEventListener() {}};
  Object.defineProperty(globalThis, 'navigator', {value: {mediaDevices: {getUserMedia: getUserMedia || (async () => stream)}}, configurable:true});
  globalThis.MediaRecorder = class {
    static isTypeSupported() {return true;}
    constructor() {this.state='inactive'; this.mimeType='audio/webm';}
    start() {this.state='recording';}
    stop() {this.state='inactive'; queueMicrotask(() => {this.ondataavailable({data:new Blob(['audio'])}); this.onstop();});}
  };
  globalThis.fetch = async (...args) => {
    uploads++;
    if (fetcher) return fetcher(...args);
    return {ok:true,json:async()=>({text:'Like Arrival',seconds:2,processing_ms:50})};
  };
  initVoice({readSession:()=>({minutes:120}), voice:{available,message:'Test',max_bytes:100,max_seconds:30},
    api:async (path,data) => {calls.push({path,data}); return api ? api(path,data) : {command:{intent:'feedback',summary:'Like Arrival'}};},
    applyResult:async()=>{applied++;}});
  return {element, stream, calls, stopped:()=>stopped, applied:()=>applied, uploads:()=>uploads,
    fire:(id,type)=>element(id).listeners[type]({preventDefault(){}})};
}

test('typed preview and apply remain available when voice is disabled', async () => {
  const ui=setup({available:false});
  assert.equal(ui.element('record').disabled,true);
  assert.equal(ui.element('audio-file').disabled,true);
  ui.element('command-text').value='Like Arrival';
  await ui.fire('command-form','submit');
  assert.equal(ui.applied(),0);
  assert.equal(ui.element('apply-command').disabled,false);
  await ui.fire('apply-command','click');
  assert.equal(ui.applied(),1);
  assert.equal(ui.element('apply-command').disabled,true);
});

test('editing a transcript invalidates a preview', async () => {
  const ui=setup(); ui.element('command-text').value='Like Arrival';
  await ui.fire('command-form','submit');
  await ui.fire('command-text','input');
  await ui.fire('apply-command','click');
  assert.equal(ui.applied(),0);
  assert.equal(ui.element('apply-command').disabled,true);
});

test('unknown commands never enable apply', async () => {
  const ui=setup({api:async()=>({command:{intent:'unknown',summary:'Unknown'}})});
  ui.element('command-text').value='Like it';
  await ui.fire('command-form','submit');
  assert.equal(ui.element('apply-command').disabled,true);
});

test('permission denial restores the controls', async () => {
  const ui=setup({getUserMedia:async()=>{throw Object.assign(new Error(),{name:'NotAllowedError'});}});
  await ui.fire('record','click');
  assert.match(ui.element('voice-status').textContent,/denied/);
  assert.equal(ui.element('record').disabled,false);
  assert.equal(ui.uploads(),0);
});

test('cancelling a pending permission request stops late-arriving tracks', async () => {
  let resolve;
  const ui=setup({getUserMedia:()=>new Promise(r=>resolve=r)});
  const start=ui.fire('record','click');
  await ui.fire('cancel-recording','click');
  resolve(ui.stream); await start;
  assert.equal(ui.stopped(),1);
  assert.equal(ui.uploads(),0);
});

test('record then stop uploads audio, previews the transcript, but does not apply', async () => {
  const ui=setup();
  await ui.fire('record','click');
  assert.equal(ui.stopped(),0);
  await ui.fire('record','click'); await tick();
  assert.equal(ui.stopped(),1);
  assert.equal(ui.uploads(),1);
  assert.equal(ui.element('command-text').value,'Like Arrival');
  assert.equal(ui.applied(),0);
  assert.equal(ui.element('apply-command').disabled,false);
});

test('cancelling a recording releases the microphone without uploading', async () => {
  const ui=setup(); await ui.fire('record','click');
  await ui.fire('cancel-recording','click'); await tick();
  assert.equal(ui.stopped(),1);
  assert.equal(ui.uploads(),0);
  assert.equal(ui.element('record').disabled,false);
});

test('oversized files are rejected before upload', async () => {
  const ui=setup(); ui.element('audio-file').files=[new Blob(['x'.repeat(101)])];
  await ui.fire('audio-file','change'); await tick();
  assert.equal(ui.uploads(),0);
  assert.match(ui.element('voice-status').textContent,/no larger/);
});

test('cancelling transcription does not apply or preview a stale result', async () => {
  const ui=setup({fetcher:(_url,options)=>new Promise((_resolve,reject)=>options.signal.addEventListener('abort',()=>reject(Object.assign(new Error(),{name:'AbortError'}))))});
  ui.element('audio-file').files=[new Blob(['audio'])];
  await ui.fire('audio-file','change');
  await ui.fire('cancel-recording','click'); await tick();
  assert.equal(ui.calls.length,0);
  assert.equal(ui.applied(),0);
  assert.equal(ui.element('record').disabled,false);
  assert.match(ui.element('voice-status').textContent,/Cancelled/);
});
