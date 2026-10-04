'use strict';
// Poster art from the local cache (/posters/<id>), or a generated title card when there is none.
function hue(id) { let h = 0; for (const c of id) h = (h * 31 + c.charCodeAt(0)) % 360; return h; }

export function poster(item, hasPoster, className = 'poster', eager = false) {
  const frame = document.createElement('div');
  frame.className = className;
  const fallback = () => {
    const card = document.createElement('div');
    card.className = 'poster-fallback';
    card.style.setProperty('--hue', hue(item.id));
    const title = document.createElement('span'), year = document.createElement('span');
    title.className = 'poster-fallback-title'; title.textContent = item.title;
    year.className = 'poster-fallback-year'; year.textContent = String(item.year);
    card.append(title, year);
    frame.replaceChildren(card);
  };
  if (hasPoster) {
    const img = document.createElement('img');
    img.src = `/posters/${encodeURIComponent(item.id)}`; img.alt = ''; img.decoding = 'async';
    if (!eager) img.loading = 'lazy';
    img.addEventListener('error', fallback, {once: true});
    frame.append(img);
  } else fallback();
  return frame;
}
