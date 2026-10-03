'use strict';
// Guest page for couch mode, served by the LAN guest server. Talks only to that server.
const $ = id => document.getElementById(id);
const saved = {
  get() { try { return sessionStorage.getItem('flicks-guest'); } catch { return null; } },
  set(value) { try { value ? sessionStorage.setItem('flicks-guest', value) : sessionStorage.removeItem('flicks-guest'); } catch {} },
};
let token = saved.get(), state = null, busy = false, epoch = 0;  // epoch: drop polls that started before an action

async function api(path, data) {
  const headers = token ? {'X-Flicks-Guest': token} : {};
  const options = data === undefined ? {headers} : {method: 'POST', headers: {...headers, 'Content-Type': 'application/json'}, body: JSON.stringify(data)};
  const response = await fetch(path, options);
  const result = await response.json().catch(() => ({}));
  if ((response.status === 401 && token) || response.status === 410) { token = null; saved.set(null); state = null; render(); }
  if (!response.ok) throw new Error(result.error || 'Request failed');
  return result;
}
function message(text) { $('message').textContent = text; }
function show(screen) {
  for (const name of ['join', 'vote', 'wait', 'results']) $(`${name}-screen`).hidden = name !== screen;
  $('remote').hidden = screen === 'join';
}
const byId = id => state.items.find(item => item.id === id);
const PLAYER_LABELS = {playing: 'Playing', paused: 'Paused', stopped: 'Stopped'};
const lastVoted = () => [...state.items].reverse().find(item => item.id in state.you.votes);

function render() {
  if (!state) { show('join'); return; }
  const votes = state.you.votes;
  const next = state.items.find(item => !(item.id in votes));
  if (state.revealed) {
    show('results');
    const [top] = state.results;
    const best = byId(top.id);
    const people = state.progress.length;
    $('results-eyebrow').textContent = top.match ? 'IT’S A MATCH' : 'THE COUCH HAS SPOKEN';
    $('winner').textContent = best.title;
    $('winner-why').textContent = `${top.yes} of ${people} said yes${top.no ? `, ${top.no} said no` : ''}. ${best.minutes} min · ${best.genres.join(' / ')}. Ties go to Flicks’ own ranking (#${top.flicks_rank}).`;
    $('results').replaceChildren(...state.results.map(row => {
      const li = document.createElement('li');
      const label = document.createElement('span');
      label.textContent = `${byId(row.id).title} — ${row.yes} yes · ${row.no} no${row.match ? ' · everyone' : ''}`;
      const play = document.createElement('button');
      play.type = 'button'; play.textContent = '▶ Play this';
      play.setAttribute('aria-label', `Play ${byId(row.id).title} on the TV`);
      play.addEventListener('click', () => send('/api/couch/remote', {action: 'select', id: row.id}));
      li.append(label, play);
      return li;
    }));
  } else if (next) {
    show('vote');
    $('vote-progress').textContent = `TITLE ${Object.keys(votes).length + 1} OF ${state.items.length}`;
    $('vote-meta').textContent = `${next.year} / ${next.minutes} MIN`;
    $('vote-title').textContent = next.title;
    $('vote-description').textContent = next.description;
    $('vote-tags').textContent = next.genres.join(' · ');
    $('vote-yes').dataset.id = $('vote-no').dataset.id = next.id;
    $('vote-back').hidden = !lastVoted();
  } else {
    show('wait');
    $('wait-progress').replaceChildren(...state.progress.map(p => {
      const li = document.createElement('li');
      li.textContent = `${p.name}${p.name === state.you.name ? ' (you)' : ''}: ${p.voted} of ${p.total}`;
      return li;
    }));
  }
  const player = state.player;
  $('now-playing').textContent = player.id ? `${PLAYER_LABELS[player.state]}: ${byId(player.id).title}${player.by ? ` (by ${player.by})` : ''}` : 'Nothing playing yet. Pick a title from the results.';
  $('remote-toggle').textContent = player.state === 'playing' ? '❚❚ Pause' : '▶ Play';
  $('remote-toggle').disabled = $('remote-stop').disabled = busy || !player.id;
}

async function send(path, data) {
  if (busy) return;
  busy = true; epoch++;
  try { state = await api(path, data); message(''); }
  catch (error) { message(error.message); }
  finally { busy = false; render(); }
}
async function refresh() {
  if (!token) return;
  const started = epoch;
  try {
    const next = await api('/api/couch/state');
    if (started === epoch && !busy && (!state || next.version !== state.version)) { state = next; render(); }
  } catch { message('Can’t reach the TV. The couch session may have ended, or this phone left the Wi-Fi.'); }
}
async function poll() {
  if (!document.hidden && !busy) await refresh();  // a locked phone catches up on visibilitychange
  setTimeout(poll, 1500);
}
document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });

$('join-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (busy) return;
  busy = true;
  try {
    const joined = await api('/api/couch/join', {code: $('code').value.trim().toUpperCase(), name: $('name').value});
    token = joined.token; saved.set(token);
    state = await api('/api/couch/state');
    message(`You’re in, ${joined.name}.`);
  } catch (error) { message(error.message); }
  finally { busy = false; render(); }
});
for (const [id, value] of [['vote-yes', 1], ['vote-no', -1]]) {
  $(id).addEventListener('click', () => send('/api/couch/vote', {id: $(id).dataset.id, value}));
}
for (const id of ['vote-back', 'wait-back']) {
  $(id).addEventListener('click', () => { const last = lastVoted(); if (last) send('/api/couch/vote', {id: last.id, value: 0}); });
}
$('remote-toggle').addEventListener('click', () => send('/api/couch/remote', {action: state.player?.state === 'playing' ? 'pause' : 'play'}));
$('remote-stop').addEventListener('click', () => send('/api/couch/remote', {action: 'stop'}));

// The QR code carries the join code in the fragment, which browsers never send to the server.
const code = location.hash.slice(1).toUpperCase();
if (code) { $('code').value = code; history.replaceState(null, '', location.pathname); }
(async () => {
  if (token) {
    try { state = await api('/api/couch/state'); } catch { state = null; }
  }
  render();
  if (!token) $(code ? 'name' : 'code').focus();
  poll();
})();
