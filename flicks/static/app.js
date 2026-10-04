'use strict';
import { initVoice } from '/voice.js';
import { initCouchHost } from '/couch-host.js';
import { poster as drawPoster } from '/poster.js';
const $ = id => document.getElementById(id);
let catalog = [], feedback = {}, posters = new Set(), picks = [], requestVersion = 0, busy = false, filter = 'all', openId = null;

async function api(path, data) {
  const response = await fetch(path, data === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Request failed');
  return result;
}
function status(message) { $('status').textContent = message; }

// ---------- small DOM helpers ----------
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
const ICON_PATHS = {
  up: 'M1 21h4V9H1v12zm22-11c0-1.1-.9-2-2-2h-6.31l.95-4.57.03-.32c0-.41-.17-.79-.44-1.06L14.17 1 7.59 7.59C7.22 7.95 7 8.45 7 9v10c0 1.1.9 2 2 2h9c.83 0 1.54-.5 1.84-1.22l3.02-7.05c.09-.23.14-.47.14-.73v-2z',
};
function icon(name, className = '') {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('aria-hidden', 'true');
  if (className) svg.setAttribute('class', className);
  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  path.setAttribute('d', ICON_PATHS[name]); svg.append(path);
  return svg;
}
const capital = text => text.charAt(0).toUpperCase() + text.slice(1);
const runtime = minutes => minutes < 60 ? `${minutes}m` : `${Math.floor(minutes/60)}h${minutes % 60 ? ` ${minutes % 60}m` : ''}`;
const byId = id => catalog.find(item => item.id === id);
const poster = (item, className, eager) => drawPoster(item, posters.has(item.id), className, eager);

// ---------- ratings ----------
function rateButtons(item, large = false) {
  const wrap = el('div', large ? 'rate rate-large' : 'rate');
  for (const [value, label, cls] of [[1, 'Like', 'up'], [-1, 'Not for me', 'down']]) {
    const button = el('button', `rate-button rate-${cls}`);
    button.type = 'button';
    const pressed = feedback[item.id] === value;
    button.setAttribute('aria-pressed', String(pressed));
    button.setAttribute('aria-label', `${pressed ? 'Clear rating' : label}: ${item.title}`);
    button.title = pressed ? 'Clear rating' : label;
    button.disabled = busy;
    button.append(icon('up', cls === 'down' ? 'flip' : ''));
    if (large) button.append(el('span', '', label));
    button.addEventListener('click', event => { event.stopPropagation(); rate(item, pressed ? 0 : value); });
    wrap.append(button);
  }
  return wrap;
}
async function rate(item, value) {
  if (busy) return;
  busy = true;
  document.querySelectorAll('.rate-button').forEach(b => { b.disabled = true; });
  try {
    feedback = (await api('/api/feedback', {id: item.id, value})).feedback;
    await recommend();
  } catch (error) { status(`Could not save your rating: ${error.message}`); }
  finally { busy = false; renderLibrary(); renderHeroRate(); if (openId) renderDetails(openId); }
}

// ---------- scene controls ----------
function readSession() {
  return {mood: $('mood').value, minutes: Number($('minutes').value), intensity: Number($('intensity').value)/100,
          novelty: Number($('novelty').value)/100, excluded_genres: [...$('excluded-genres').selectedOptions].map(o => o.value)};
}
function setSession(session) {
  $('mood').value = session.mood; $('minutes').value = session.minutes;
  for (const key of ['intensity', 'novelty']) { $(key).value = Math.round(session[key]*100); $(`${key}-value`).textContent = `${Math.round(session[key]*100)}%`; }
  for (const option of $('excluded-genres').options) option.selected = session.excluded_genres.includes(option.value);
  syncChips();
}
const chipSyncs = [];
function syncChips() { chipSyncs.forEach(sync => sync()); }
// Chips are the visible control; the hidden <select> stays the single source of truth.
function bindChips(select, container, {multiple = false, labels = {}} = {}) {
  const buttons = [...select.options].map(option => {
    const chip = el('button', 'chip', labels[option.value] || option.textContent);
    chip.type = 'button';
    if (!multiple) chip.setAttribute('role', 'radio');
    chip.addEventListener('click', () => {
      if (multiple) option.selected = !option.selected; else select.value = option.value;
      syncChips();
      $('session').dispatchEvent(new Event('input', {bubbles: true}));
    });
    container.append(chip);
    return [option, chip];
  });
  chipSyncs.push(() => {
    for (const [option, chip] of buttons) {
      const on = multiple ? option.selected : select.value === option.value;
      chip.setAttribute(multiple ? 'aria-pressed' : 'aria-checked', String(on));
      if (!multiple) chip.tabIndex = on ? 0 : -1;
    }
  });
}
function buildScene() {
  bindChips($('mood'), $('mood-chips'), {labels: {any: 'Anything'}});
  bindChips($('mode'), $('mode-chips'), {labels: {session: 'Taste + scene', baseline: 'Taste only'}});
  const genres = [...new Set(catalog.flatMap(item => item.genres))].sort();
  for (const genre of genres) { const option = el('option', '', capital(genre)); option.value = genre; $('excluded-genres').append(option); }
  bindChips($('excluded-genres'), $('avoid-chips'), {multiple: true});
  chipSyncs.push(() => { const n = $('excluded-genres').selectedOptions.length; $('avoid-count').textContent = n ? `· ${n}` : ''; });
  for (const minutes of [45, 90, 120, 180]) {
    const chip = el('button', 'chip', runtime(minutes)); chip.type = 'button';
    chip.addEventListener('click', () => { $('minutes').value = minutes; syncChips(); $('session').dispatchEvent(new Event('input', {bubbles: true})); });
    $('time-chips').append(chip);
    chipSyncs.push(() => chip.setAttribute('aria-pressed', String(Number($('minutes').value) === minutes)));
  }
  for (const key of ['intensity', 'novelty']) $(key).addEventListener('input', () => { $(`${key}-value`).textContent = `${$(key).value}%`; });
  let timer = null;
  const changed = () => { clearTimeout(timer); timer = setTimeout(() => { syncChips(); recommend(); }, 160); };
  $('session').addEventListener('input', changed);
  $('session').addEventListener('change', changed);
  $('session').addEventListener('submit', event => { event.preventDefault(); recommend(); });
  syncChips();
}

// ---------- recommendations ----------
function reasons(row) {
  const item = row.content, session = readSession(), f = row.factors, list = [];
  if (session.mood !== 'any' && f.mood >= 0.19) list.push(`${capital(session.mood)} mood`);
  if (f.intensity !== undefined && f.intensity >= 0.135) list.push(item.intensity < 0.35 ? 'Easygoing' : item.intensity > 0.65 ? 'Full throttle' : 'Right intensity');
  if (row.evidence.length) list.push(`Your taste: ${row.evidence.slice(0, 2).join(' · ')}`);
  list.push(`${runtime(item.minutes)} · fits ${runtime(session.minutes)}`);
  return list;
}
function fillReasons(list, row) { list.replaceChildren(...reasons(row).map(text => el('li', '', text))); }

function renderHero() {
  const top = picks[0];
  $('hero-actions').hidden = !top;
  $('hero-backdrop').replaceChildren(); $('hero-poster').replaceChildren(); $('hero-reasons').replaceChildren();
  if (!top) {
    $('hero-eyebrow').textContent = 'Nothing fits yet';
    $('hero-title').textContent = 'Widen the scene.';
    $('hero-meta').textContent = '';
    $('hero-description').textContent = 'Give yourself more time, drop a genre you’re avoiding, or clear a rating below.';
    return;
  }
  const item = top.content;
  $('hero-eyebrow').textContent = $('mode').value === 'baseline' ? 'Top pick for your taste' : 'Top pick for tonight';
  $('hero-title').textContent = item.title;
  $('hero-meta').textContent = `${item.year} · ${runtime(item.minutes)} · ${item.genres.map(capital).join(' · ')}`;
  $('hero-description').textContent = item.description;
  fillReasons($('hero-reasons'), top);
  if (posters.has(item.id)) $('hero-backdrop').append(poster(item, 'backdrop-art', true));
  $('hero-poster').append(poster(item, 'poster poster-hero', true));
  renderHeroRate();
}
function renderHeroRate() { const top = picks[0]; if (top) $('hero-rate').replaceChildren(rateButtons(top.content, true)); }

function tile(item, rank) {
  const card = el('article', rank ? 'tile tile-ranked' : 'tile');
  const open = el('button', 'tile-open');
  open.type = 'button';
  open.setAttribute('aria-label', `${item.title}, ${item.year}. Details${rank ? ' and why it’s picked' : ''}`);
  open.append(poster(item));
  open.addEventListener('click', () => openDetails(item.id));
  if (rank) { const n = el('span', 'rank', String(rank)); n.setAttribute('aria-hidden', 'true'); card.append(n); }
  const info = el('div', 'tile-info');
  info.append(el('h3', 'tile-title', item.title), el('p', 'tile-sub', `${item.year} · ${runtime(item.minutes)}`));
  if (feedback[item.id]) card.classList.add(feedback[item.id] === 1 ? 'is-liked' : 'is-disliked');
  card.append(open, info, rateButtons(item));
  return card;
}

async function recommend() {
  const version = ++requestVersion;
  const session = readSession();
  if (!Number.isInteger(session.minutes) || session.minutes < 1 || session.minutes > 600) { status('Time must be a whole number of minutes from 1 to 600.'); return; }
  try {
    const result = await api('/api/recommend', {session, mode: $('mode').value});
    if (version !== requestVersion) return;
    picks = result.recommendations;
    $('count').textContent = picks.length ? `${picks.length} picks` : '';
    status(!picks.length ? 'Nothing fits yet. Add time, drop an avoided genre, or clear a rating.'
      : result.cold_start ? 'Like a few films below and Flicks learns your taste. Until then, picks follow your scene.'
      : 'Shaped by your ratings and this scene. Open any title to see why it ranks where it does.');
    $('recommendations').replaceChildren(...picks.map((row, i) => tile(row.content, i + 1)));
    renderHero();
    if (openId) renderDetails(openId);
  } catch (error) {
    if (version === requestVersion) { $('recommendations').replaceChildren(); $('count').textContent = ''; status(`Could not load picks: ${error.message}. Please retry.`); }
  }
}

// ---------- details sheet ----------
const FACTORS = {taste: ['Your taste', 0.55], mood: ['Mood', 0.20], intensity: ['Intensity', 0.15], novelty: ['Discovery', 0.10]};
function renderDetails(id) {
  const item = byId(id), rank = picks.findIndex(row => row.content.id === id), row = picks[rank];
  $('details-art').replaceChildren(poster(item, 'poster poster-details', true));
  $('details-eyebrow').textContent = row ? `#${rank + 1} of ${picks.length} for this moment` : feedback[id] ? 'Rated titles are hidden from picks' : 'Not in your current picks';
  $('details-title').textContent = item.title;
  $('details-meta').textContent = `${item.year} · ${runtime(item.minutes)} · ${item.genres.map(capital).join(' · ')}`;
  $('details-description').textContent = item.description;
  $('details-rate').replaceWith(Object.assign(rateButtons(item, true), {id: 'details-rate'}));
  $('details-reasons').replaceChildren();
  $('details-factors').replaceChildren();
  if (row) {
    fillReasons($('details-reasons'), row);
    for (const [key, value] of Object.entries(row.factors)) {
      const [label, max] = FACTORS[key] || [capital(key), 1];
      const line = el('div', 'factor'), bar = el('div', 'factor-bar'), fill = el('span');
      fill.style.setProperty('--fill', Math.max(0, Math.min(1, value / max)));
      bar.append(fill);
      line.append(el('span', 'factor-label', label), bar, el('span', 'factor-value', `${value.toFixed(2)} / ${max.toFixed(2)}`));
      $('details-factors').append(line);
    }
    const total = el('div', 'factor factor-total');
    total.append(el('span', 'factor-label', 'Total'), el('span'), el('span', 'factor-value', row.score.toFixed(2)));
    $('details-factors').append(total);
    $('details-note').textContent = `Scores are ranking signals, not probabilities.${row.evidence.length ? ` Terms shared with films you liked: ${row.evidence.join(', ')}.` : ''}${row.negative_evidence.length ? ` Terms from films you passed on: ${row.negative_evidence.join(', ')}.` : ''}`;
  } else {
    $('details-note').textContent = feedback[id] ? 'Clear the rating to let it back into your picks.' : 'It doesn’t fit this scene, or ranks below the top picks. Try more time or a different mood.';
  }
}
function openDetails(id) {
  openId = id; renderDetails(id);
  if (!$('details').open) $('details').showModal();
}

// ---------- browse ----------
const FILTERS = [['all', 'All'], ['liked', 'Liked'], ['disliked', 'Passed'], ['unrated', 'Unrated']];
function buildFilters() {
  for (const [value, label] of FILTERS) {
    const chip = el('button', 'chip', label); chip.type = 'button'; chip.setAttribute('role', 'radio');
    chip.addEventListener('click', () => { filter = value; renderLibrary(); });
    $('library-filter').append(chip);
  }
}
function renderLibrary() {
  const values = Object.values(feedback), liked = values.filter(v => v === 1).length, passed = values.filter(v => v === -1).length;
  $('profile').textContent = liked || passed ? `${liked} liked · ${passed} passed · saved on this device` : 'Like a few favourites to teach Flicks your taste.';
  [...$('library-filter').children].forEach((chip, i) => { const on = FILTERS[i][0] === filter; chip.setAttribute('aria-checked', String(on)); chip.tabIndex = on ? 0 : -1; });
  const query = $('search').value.toLowerCase().trim();
  const keep = item => (filter === 'all' || (filter === 'liked' && feedback[item.id] === 1) || (filter === 'disliked' && feedback[item.id] === -1) || (filter === 'unrated' && !feedback[item.id]))
    && `${item.title} ${item.genres.join(' ')} ${item.tags.join(' ')}`.toLowerCase().includes(query);
  const matches = catalog.filter(keep);
  $('catalog').replaceChildren(...(matches.length ? matches.map(item => tile(item)) : [el('p', 'empty', 'No titles match. Try another search or filter.')]));
}

// ---------- wiring ----------
$('search').addEventListener('input', renderLibrary);
$('rail-prev').addEventListener('click', () => $('recommendations').scrollBy({left: -$('recommendations').clientWidth * 0.85, behavior: 'smooth'}));
$('rail-next').addEventListener('click', () => $('recommendations').scrollBy({left: $('recommendations').clientWidth * 0.85, behavior: 'smooth'}));
$('hero-why').addEventListener('click', () => picks[0] && openDetails(picks[0].content.id));
$('details-close').addEventListener('click', () => $('details').close());
$('details').addEventListener('close', () => { openId = null; });
$('details').addEventListener('click', event => { if (event.target === $('details')) $('details').close(); });  // backdrop click
$('ask-shortcut').addEventListener('click', () => { $('command-text').focus(); $('command-text').scrollIntoView({block: 'center', behavior: 'smooth'}); });
$('command-text').addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); $('command-form').requestSubmit(); }
});
document.addEventListener('keydown', event => {
  if (event.key === '/' && !event.target.closest('input, textarea, select, [contenteditable]')) { event.preventDefault(); $('command-text').focus(); }
});
(async () => {
  try {
    const data = await api('/api/state');
    catalog = data.catalog; feedback = data.feedback; posters = new Set(data.posters || []);
    $('poster-credit').hidden = !posters.size;
    buildScene(); buildFilters();
    initVoice({api, readSession, voice: data.voice, applyResult: async result => { feedback = result.feedback; setSession(result.session); renderLibrary(); await recommend(); }});
    initCouchHost({api, readSession, enabled: data.couch});
    $('nav-couch').hidden = !data.couch;
    $('catalog-size').textContent = catalog.length;
    renderLibrary(); await recommend();
  } catch (error) { status(`Could not load Flicks: ${error.message}. Reload to retry.`); }
})();
