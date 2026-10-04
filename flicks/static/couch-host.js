'use strict';
import { poster } from '/poster.js';
// Host (TV) side of couch mode. Runs on the loopback page; guests use couch.js on the LAN server.
export function initCouchHost({api, readSession, enabled}) {
  const $ = id => document.getElementById(id);
  if (!enabled) return;
  $('couch-panel').hidden = false;
  let state = {active: false}, busy = false, epoch = 0;  // epoch: drop polls that started before an action
  const title = id => (state.items.find(item => item.id === id) || {}).title || id;
  const status = text => { $('couch-status').textContent = text; };
  const PLAYER_LABELS = {playing: 'Playing', paused: 'Paused', stopped: 'Stopped'};

  function render() {
    $('couch-idle').hidden = state.active;
    $('couch-live').hidden = !state.active;
    $('couch-start').disabled = busy;
    if (!state.active) return;
    const qr = $('couch-qr');
    if (qr.dataset.code !== state.code) { qr.src = `/api/couch/qr.svg?code=${encodeURIComponent(state.code)}`; qr.dataset.code = state.code; }
    $('couch-url').textContent = state.url;
    $('couch-code').textContent = state.code;
    const people = state.progress;
    $('couch-guests').replaceChildren(...(people.length ? people : [null]).map(p => {
      const li = document.createElement('li');
      li.textContent = p ? `${p.name}: ${p.voted} of ${p.total}${p.voted === p.total ? ' ✓' : ''}` : 'Nobody has joined yet.';
      return li;
    }));
    $('couch-reveal').disabled = busy || state.revealed || !people.length;
    $('couch-results').replaceChildren(...(state.results || []).map((row, i) => {
      const li = document.createElement('li');
      const item = state.items.find(entry => entry.id === row.id);
      const label = document.createElement('span');
      label.className = 'result-title';
      const text = document.createElement('span');
      text.textContent = `${title(row.id)} — ${row.yes} yes · ${row.no} no${row.match ? ' · it’s a match' : ''}${i === 0 ? ' · group pick' : ''}`;
      label.append(poster(item, item.poster), text);
      const play = document.createElement('button');
      play.type = 'button'; play.className = 'button button-quiet'; play.textContent = '▶ Play';
      play.setAttribute('aria-label', `Play ${title(row.id)}`);
      play.addEventListener('click', () => send('/api/couch/player', {action: 'select', id: row.id}));
      li.append(label, play);
      return li;
    }));
    $('couch-results-head').hidden = !state.revealed;
    const player = state.player;
    $('couch-player').textContent = player.id ? `${PLAYER_LABELS[player.state]}: ${title(player.id)}${player.by ? ` · from ${player.by}` : ''}` : 'Nothing playing. Playback is a stub until the video player lands.';
    $('couch-toggle').textContent = player.state === 'playing' ? '❚❚ Pause' : '▶ Play';
    $('couch-toggle').disabled = $('couch-stop-playback').disabled = busy || !player.id;
  }
  async function send(path, data) {
    if (busy) return;
    busy = true; epoch++; render();
    try { state = await api(path, data); status(''); }
    catch (error) { status(error.message); }
    finally { busy = false; render(); }
  }
  async function refresh() {
    const started = epoch;
    try {
      const next = await api('/api/couch');
      if (started === epoch && !busy && (next.active !== state.active || next.version !== state.version)) { state = next; render(); }
    } catch (error) { status(`Couch mode: ${error.message}`); }
  }
  async function poll() {
    if (!busy && !document.hidden) await refresh();  // a hidden tab catches up on visibilitychange
    setTimeout(poll, 1500);
  }
  $('couch-start').addEventListener('click', () => send('/api/couch/start', {session: readSession()}));
  $('couch-end').addEventListener('click', () => send('/api/couch/stop', {}));
  $('couch-reveal').addEventListener('click', () => send('/api/couch/reveal', {}));
  $('couch-toggle').addEventListener('click', () => send('/api/couch/player', {action: state.player?.state === 'playing' ? 'pause' : 'play'}));
  $('couch-stop-playback').addEventListener('click', () => send('/api/couch/player', {action: 'stop'}));
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
  render();
  refresh().then(() => setTimeout(poll, 1500));
}
