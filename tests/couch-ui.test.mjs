// Browser-independent tests for the couch-mode guest page (couch.js) and host panel (couch-host.js).
// A fake DOM and fetch; no network. Polling timers are disabled and driven explicitly.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const guestSource = readFileSync(new URL('../flicks/static/couch.js', import.meta.url), 'utf8');
const hostSource = readFileSync(new URL('../flicks/static/couch-host.js', import.meta.url), 'utf8');
const posterSource = readFileSync(new URL('../flicks/static/poster.js', import.meta.url), 'utf8');
const dataUrl = source => `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`;
let loads = 0;  // a unique suffix gives each test a fresh module instance
// Browsers resolve '/poster.js' against the page; here it is inlined as a data: URL.
const load = source => import(dataUrl(`${source.replace("'/poster.js'", `'${dataUrl(posterSource)}'`)}\n// load ${++loads}`));
const tick = async () => { for (let i = 0; i < 10; i++) await new Promise(resolve => setImmediate(resolve)); };
globalThis.setTimeout = () => 0;

const items = [
  {id: 'a', title: 'Alpha', year: 2000, minutes: 90, genres: ['Drama'], description: 'About Alpha'},
  {id: 'b', title: 'Beta', year: 2001, minutes: 95, genres: ['Comedy'], description: 'About Beta'},
];
const view = (over = {}) => ({active: true, version: 1, items, revealed: false, results: null, expires_in: 100,
  player: {id: null, state: 'stopped', by: null}, progress: [{name: 'Sam', voted: 0, total: 2}],
  you: {id: 'g1', name: 'Sam', votes: {}}, ...over});

function fakeDom({hash = '', hidden = false, token = null} = {}) {
  const elements = new Map(), listeners = {};
  const make = () => ({hidden: false, textContent: '', value: '', disabled: false, dataset: {}, children: [], listeners: {}, src: '', style: {setProperty() {}},
    addEventListener(type, listener) { this.listeners[type] = listener; }, setAttribute() {},
    focus() { dom.focused = this; }, append(...nodes) { this.children.push(...nodes); }, replaceChildren(...nodes) { this.children = nodes; }});
  const dom = {focused: null, replaced: null, store: token ? {'flicks-guest': token} : {}};
  globalThis.document = {hidden, getElementById: id => { if (!elements.has(id)) elements.set(id, make()); return elements.get(id); },
    createElement: make, addEventListener: (type, listener) => { listeners[type] = listener; }};
  globalThis.location = {hash, pathname: '/join'};
  globalThis.history = {replaceState: (...args) => { dom.replaced = args; }};
  globalThis.sessionStorage = {getItem: key => dom.store[key] ?? null, setItem: (key, value) => { dom.store[key] = value; },
    removeItem: key => { delete dom.store[key]; }};
  dom.el = id => document.getElementById(id);
  dom.fire = (id, type = 'click') => dom.el(id).listeners[type]({preventDefault() {}});
  dom.becomeVisible = () => { document.hidden = false; listeners.visibilitychange(); };
  return dom;
}

// Route-based fetch stub. `states` is a queue of GET /api/couch/state replies; the last one repeats.
function fakeServer({states = [[200, view()]], post = {}} = {}) {
  const calls = [];
  globalThis.fetch = async (path, options = {}) => {
    const body = options.body ? JSON.parse(options.body) : undefined;
    calls.push({path, body, headers: options.headers || {}});
    const reply = path === '/api/couch/state' ? (states.length > 1 ? states.shift() : states[0]) : post[path](body);
    const [status, json] = await reply;
    return {ok: status < 400, status, json: async () => json};
  };
  return calls;
}

test('the QR fragment fills in the code and is removed from the address bar', async () => {
  const dom = fakeDom({hash: '#abcd2345'});
  const calls = fakeServer();
  await load(guestSource); await tick();
  assert.equal(dom.el('code').value, 'ABCD2345');
  assert.deepEqual(dom.replaced, [null, '', '/join']);
  assert.equal(dom.focused, dom.el('name'));
  assert.equal(dom.el('join-screen').hidden, false);
  assert.equal(calls.length, 0);  // nothing is requested before joining
});

test('joining stores the token, sends it on every request and shows the first title', async () => {
  const dom = fakeDom({hash: '#ABCD2345'});
  const calls = fakeServer({post: {'/api/couch/join': () => [200, {token: 't1', name: 'Sam'}]}});
  await load(guestSource); await tick();
  dom.el('name').value = 'Sam';
  await dom.fire('join-form', 'submit'); await tick();
  assert.deepEqual(calls[0].body, {code: 'ABCD2345', name: 'Sam'});
  assert.equal(dom.store['flicks-guest'], 't1');
  assert.equal(calls[1].headers['X-Flicks-Guest'], 't1');
  assert.equal(dom.el('vote-screen').hidden, false);
  assert.equal(dom.el('vote-title').textContent, 'Alpha');
  assert.equal(dom.el('vote-progress').textContent, 'TITLE 1 OF 2');
  assert.equal(dom.el('remote').hidden, false);
});

test('a poll that started before a vote cannot overwrite the vote', async () => {
  let releaseStale;
  const stale = new Promise(resolve => { releaseStale = () => resolve([200, view({version: 2})]); });
  const dom = fakeDom({token: 't1', hidden: true});
  fakeServer({states: [[200, view()], stale],
    post: {'/api/couch/vote': () => [200, view({version: 3, you: {id: 'g1', name: 'Sam', votes: {a: 1}}})]}});
  await load(guestSource); await tick();
  assert.equal(dom.el('vote-title').textContent, 'Alpha');
  dom.becomeVisible();  // starts a refresh whose reply is held back
  await dom.fire('vote-yes'); await tick();
  assert.equal(dom.el('vote-title').textContent, 'Beta');
  releaseStale(); await tick();
  assert.equal(dom.el('vote-title').textContent, 'Beta');
});

test('an unknown or expired token goes back to the join screen', async () => {
  const dom = fakeDom({token: 'old'});
  fakeServer({states: [[401, {error: 'Join the couch session first'}]]});
  await load(guestSource); await tick();
  assert.equal(dom.el('join-screen').hidden, false);
  assert.equal(dom.store['flicks-guest'], undefined);
  assert.equal(dom.el('remote').hidden, true);
});

test('results show the match and the remote plays the chosen title', async () => {
  const results = [{id: 'b', yes: 2, no: 0, flicks_rank: 2, match: true}, {id: 'a', yes: 1, no: 1, flicks_rank: 1, match: false}];
  const revealed = view({revealed: true, results, progress: [{name: 'Sam', voted: 2, total: 2}, {name: 'Alex', voted: 2, total: 2}]});
  const dom = fakeDom({token: 't1'});
  const calls = fakeServer({states: [[200, revealed]],
    post: {'/api/couch/remote': body => [200, {...revealed, version: 2, player: {id: body.id, state: 'playing', by: 'Sam'}}]}});
  await load(guestSource); await tick();
  assert.equal(dom.el('results-eyebrow').textContent, 'IT’S A MATCH');
  assert.equal(dom.el('winner').textContent, 'Beta');
  assert.match(dom.el('winner-why').textContent, /^2 of 2 said yes\./);
  assert.equal(dom.el('remote-toggle').disabled, true);
  await dom.el('results').children[0].children[1].listeners.click(); await tick();
  assert.deepEqual(calls.at(-1).body, {action: 'select', id: 'b'});
  assert.equal(dom.el('now-playing').textContent, 'Playing: Beta (by Sam)');
  assert.equal(dom.el('remote-toggle').textContent, '❚❚ Pause');
});

function hostApi(replies) {
  const calls = [];
  return {calls, api: async (path, data) => { calls.push({path, data}); return replies[path](data); }};
}
const hostView = (over = {}) => ({...view(), code: 'K7QX2MPA', url: 'http://192.168.1.23:8770/join', you: undefined, ...over});

test('the host panel stays hidden and silent when couch mode is off', async () => {
  const dom = fakeDom();
  dom.el('couch-panel').hidden = true;
  const {calls, api} = hostApi({});
  (await load(hostSource)).initCouchHost({api, readSession: () => ({}), enabled: false});
  await tick();
  assert.equal(dom.el('couch-panel').hidden, true);
  assert.equal(calls.length, 0);
});

test('a background tab still shows a running session when it opens', async () => {
  const dom = fakeDom({hidden: true});
  const {api} = hostApi({'/api/couch': () => hostView()});
  (await load(hostSource)).initCouchHost({api, readSession: () => ({}), enabled: true});
  await tick();
  assert.equal(dom.el('couch-live').hidden, false);
  assert.equal(dom.el('couch-code').textContent, 'K7QX2MPA');
  assert.equal(dom.el('couch-qr').src, '/api/couch/qr.svg?code=K7QX2MPA');
  assert.equal(dom.el('couch-guests').children[0].textContent, 'Sam: 0 of 2');
});

test('starting a session sends the current scene', async () => {
  const dom = fakeDom();
  const {calls, api} = hostApi({'/api/couch': () => ({active: false}), '/api/couch/start': () => hostView()});
  (await load(hostSource)).initCouchHost({api, readSession: () => ({mood: 'relaxing', minutes: 100}), enabled: true});
  await tick();
  assert.equal(dom.el('couch-idle').hidden, false);
  await dom.fire('couch-start'); await tick();
  assert.deepEqual(calls.at(-1), {path: '/api/couch/start', data: {session: {mood: 'relaxing', minutes: 100}}});
  assert.equal(dom.el('couch-live').hidden, false);
});
