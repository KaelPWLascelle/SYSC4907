'use strict';
const $ = id => document.getElementById(id);
let catalog = [], feedback = {}, requestVersion = 0, busy = false;
async function api(path, data) {
  const response = await fetch(path, data === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Request failed');
  return result;
}
function status(message) { $('status').textContent = message; }
function actions(item, parent) {
  for (const [label, value] of [['Like', 1], ['Dislike', -1], ['Clear', 0]]) {
    const button = document.createElement('button');
    button.textContent = label;
    button.setAttribute('aria-label', `${label} ${item.title}`);
    if (value) button.setAttribute('aria-pressed', String(feedback[item.id] === value));
    button.disabled = busy || (value === 0 && !feedback[item.id]);
    button.addEventListener('click', async () => {
      if (busy) return;
      busy = true;
      document.querySelectorAll('.actions button').forEach(b => b.disabled = true);
      try {
        const result = await api('/api/feedback', {id: item.id, value});
        feedback = result.feedback;
        await recommend();
      } catch (error) { status(`Could not save feedback: ${error.message}`); }
      finally {
        busy = false;
        renderLibrary();
        document.querySelectorAll('#recommendations .actions').forEach(node => {
          const item = catalog.find(c => c.id === node.dataset.id);
          node.replaceChildren(); actions(item, node);
        });
      }
    });
    parent.append(button);
  }
}
function renderLibrary() {
  const query = $('search').value.toLowerCase().trim();
  $('catalog').replaceChildren();
  const values = Object.values(feedback);
  $('profile').textContent = `${values.filter(v => v === 1).length} liked · ${values.filter(v => v === -1).length} disliked · saved on this device`;
  const matches = catalog.filter(c => `${c.title} ${c.genres.join(' ')} ${c.tags.join(' ')}`.toLowerCase().includes(query));
  for (const item of matches) {
    const row = document.createElement('article'); row.className = 'library-item';
    const title = document.createElement('h3'); title.textContent = item.title;
    const meta = document.createElement('p'); meta.textContent = `${item.year} · ${item.minutes} min · ${item.genres.join(' / ')}`;
    const buttons = document.createElement('div'); buttons.className = 'actions';
    actions(item, buttons); row.append(title, meta, buttons); $('catalog').append(row);
  }
  if (!matches.length) $('catalog').textContent = 'No titles match that search.';
}
async function recommend() {
  const version = ++requestVersion;
  status('Finding your next watch…');
  const session = {mood: $('mood').value, minutes: Number($('minutes').value), intensity: Number($('intensity').value)/100, novelty: Number($('novelty').value)/100};
  try {
    const result = await api('/api/recommend', {session, mode: $('mode').value});
    if (version !== requestVersion) return;
    $('recommendations').replaceChildren();
    $('count').textContent = `${result.recommendations.length} picks`;
    status(result.recommendations.length ? (result.cold_start ? 'Like a few films to teach Kevin your taste. Discovery stays neutral until your first like.' : 'Your ratings shape taste. Open “Why this pick?” to inspect each score.') : 'Nothing fits yet. Increase your available time or clear a rating in the catalogue.');
    for (const row of result.recommendations) {
      const item = row.content;
      const card = $('card').content.firstElementChild.cloneNode(true);
      card.querySelector('.meta').textContent = `${item.year} / ${item.minutes} MIN / ${item.kind.toUpperCase()}`;
      card.querySelector('h3').textContent = item.title;
      card.querySelector('.description').textContent = item.description;
      card.querySelector('.tags').textContent = item.genres.join(' · ');
      const explanation = card.querySelector('.explanation');
      for (const [name, value] of Object.entries(row.factors)) {
        const p = document.createElement('p'); p.textContent = `${name}: ${value.toFixed(3)} weighted contribution`; explanation.append(p);
      }
      const p = document.createElement('p');
      p.textContent = `Total: ${row.score.toFixed(3)}. Fits your ${session.minutes}-minute limit. ${row.evidence.length ? `Positive profile terms: ${row.evidence.join(', ')}.` : 'No positive profile terms yet.'} ${row.negative_evidence.length ? `Disliked profile terms: ${row.negative_evidence.join(', ')}.` : ''} Mood tags: ${item.moods.join(', ')}. Editorial intensity: ${Math.round(item.intensity*100)}%.`;
      explanation.append(p);
      const buttons = card.querySelector('.actions'); buttons.dataset.id = item.id; actions(item, buttons);
      $('recommendations').append(card);
    }
  } catch (error) {
    if (version === requestVersion) {
      $('recommendations').replaceChildren(); $('count').textContent = '';
      status(`Could not load recommendations: ${error.message}. Please retry.`);
    }
  }
}
$('session').addEventListener('submit', event => { event.preventDefault(); recommend(); });
$('search').addEventListener('input', renderLibrary);
for (const key of ['intensity', 'novelty']) $(key).addEventListener('input', () => $(`${key}-value`).textContent = `${$(key).value}%`);
(async () => {
  try { const data = await api('/api/state'); catalog = data.catalog; feedback = data.feedback; $('catalog-size').textContent = catalog.length; renderLibrary(); await recommend(); }
  catch (error) { status(`Could not load Kevin: ${error.message}. Reload to retry.`); }
})();
