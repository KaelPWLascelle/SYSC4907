import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { TasteResponse } from '../api/types';
import { ALPHA, CATALOG, GAMMA, appState, pick } from '../test/fixtures';
import { mockFetch } from '../test/fetchMock';
import { App } from './App';

// Your taste's web of genres, "Your usual night", and the room following the clock.
const TASTE: TasteResponse = {
  liked: 3,
  passed: 1,
  genres: [
    { genre: 'science-fiction', liked: 3, passed: 0, affinity: 0.6 },
    { genre: 'action', liked: 1, passed: 0, affinity: 0.33 },
    { genre: 'drama', liked: 1, passed: 1, affinity: 0 },
    { genre: 'musical', liked: 0, passed: 1, affinity: -0.33 },
  ],
  themes: { liked: [{ term: 'space', weight: 1 }], passed: [] },
  influences: [{ title: 'Alien', picks: 9 }],
  rated: [
    { id: 'm1', title: 'Alpha', year: 2001, genres: ['science-fiction', 'action'], rating: 1 },
    { id: 'm2', title: 'Beta', year: 2002, genres: ['science-fiction', 'drama'], rating: 1 },
    { id: 'm3', title: 'Gamma', year: 2003, genres: ['science-fiction'], rating: 1 },
    { id: 'm4', title: 'Delta', year: 2004, genres: ['musical', 'drama'], rating: -1 },
  ],
};

function setup() {
  return mockFetch({
    'GET /api/state': () => [200, appState({ profile: { id: 1, name: 'Me', locked: false, chosen: false, count: 1 } })],
    'GET /api/history': () => [200, { items: [] }],
    'GET /api/titles': () => [200, { items: CATALOG, total: CATALOG.length, understood: [] }],
    'GET /api/taste': () => [200, TASTE],
    'POST /api/recommend': () => [200, { recommendations: [ALPHA, GAMMA].map(item => pick(item)), cold_start: false }],
  });
}

async function openTaste() {
  render(<App />);
  await screen.findByRole('heading', { level: 1, name: 'Alpha' });
  await userEvent.click(screen.getByRole('button', { name: 'Your taste' }));
  return screen.findByRole('dialog', { name: 'Your taste' });
}

beforeEach(() => localStorage.clear());

test('the web has a thread per genre; choosing one explains it and offers to browse it', async () => {
  const { calls } = setup();
  const sheet = await openTaste();
  const web = await within(sheet).findByRole('group', { name: 'Your taste as a web of genres' });
  expect(web.querySelectorAll('.web-drop')).toHaveLength(4); // every rated film hangs in it
  expect(within(sheet).getByText('Point at a thread to see what made it.')).toBeInTheDocument();

  await userEvent.click(within(web).getByRole('button', { name: 'Science-fiction: liked 3, passed 0' }));
  expect(
    within(sheet).getByText(/^Every film you liked is science fiction\. It’s the strongest thread/),
  ).toBeInTheDocument();
  expect(web.querySelectorAll('.web-drop.is-dim')).toHaveLength(1); // Delta is not science fiction

  within(web).getByRole('button', { name: 'Musical: liked 0, passed 1' }).focus();
  expect(await within(sheet).findByText(/^You passed on the one musical title you rated/)).toBeInTheDocument();
  await userEvent.click(within(sheet).getByRole('button', { name: 'Browse musical' }));
  await waitFor(() => expect(calls.some(c => c.path === '/api/titles' && c.params.get('q') === 'musical')).toBe(true));
});

test('“Your usual night” is drawn, saved per profile, and becomes the scene Tonight starts from', async () => {
  const { calls } = setup();
  const sheet = await openTaste();
  const pad = within(sheet).getByRole('slider', { name: /Your usual night/ });
  const save = within(sheet).getByRole('button', { name: 'Use as my usual night' });
  expect(save).toBeDisabled(); // nothing changed yet
  expect(within(sheet).getByText('Most nights you want something balanced, about 2 hours.')).toBeInTheDocument();

  pad.focus();
  await userEvent.keyboard('{ArrowLeft}{ArrowLeft}{ArrowLeft}{ArrowDown}{ArrowDown}');
  expect(within(sheet).getByText('Most nights you want something gentle, about 1½ hours.')).toBeInTheDocument();
  expect(pad).toHaveAttribute('aria-valuetext', 'gentle, 90 minutes');
  await userEvent.click(save);
  expect(within(sheet).getByText('Saved. Tonight now starts from this night.')).toBeInTheDocument();
  expect(JSON.parse(localStorage.getItem('flicks.night.1') ?? 'null')).toEqual({ intensity: 0.2, minutes: 90 });
  // Tonight's picks are asked for with it (the "ready to watch" row keeps its own long evening).
  await waitFor(() =>
    expect(
      calls.some(c => {
        const scene = (c.body as { session?: { minutes: number; intensity: number } } | undefined)?.session;
        return c.path === '/api/recommend' && scene?.minutes === 90 && scene.intensity === 0.2;
      }),
    ).toBe(true),
  );

  // Back on Tonight the scene reads it, and Reset has nothing to undo: this is the starting point now.
  await userEvent.click(within(sheet).getByRole('button', { name: 'Close' }));
  expect(screen.getByRole('button', { name: 'Time: 1½ hours. Change' })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Reset scene' })).toBeNull();
});

test('late at night the room dims and offers picks that end sooner', async () => {
  setup();
  window.history.replaceState(null, '', '/?hour=23');
  render(<App />);
  await screen.findByRole('heading', { level: 1, name: 'Alpha' });
  expect(document.documentElement.dataset.time).toBe('late');
  await userEvent.click(screen.getByRole('button', { name: 'Show picks that end in 90 minutes' }));
  expect(screen.getByRole('button', { name: 'Time: 1½ hours. Change' })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Show picks that end in 90 minutes' })).toBeNull();
});

test('in the evening the room is warmer, and there is no late-night note', async () => {
  setup();
  window.history.replaceState(null, '', '/?hour=19');
  render(<App />);
  await screen.findByRole('heading', { level: 1, name: 'Alpha' });
  expect(document.documentElement.dataset.time).toBe('evening');
  expect(screen.queryByText(/It’s late/)).toBeNull();
});

test('a saved usual night is where the next visit starts', async () => {
  localStorage.setItem('flicks.night.1', JSON.stringify({ intensity: 0.9, minutes: 150 }));
  const { calls } = setup();
  render(<App />);
  await screen.findByRole('heading', { level: 1, name: 'Alpha' });
  expect(screen.getByRole('button', { name: 'Time: 2½ hours. Change' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Energy: intense. Change' })).toBeInTheDocument();
  const first = calls.find(c => c.path === '/api/recommend')?.body as { session: { minutes: number } };
  expect(first.session.minutes).toBe(150);
});

test('a damaged saved night is ignored', async () => {
  localStorage.setItem('flicks.night.1', JSON.stringify({ intensity: 7, minutes: 'late' }));
  setup();
  render(<App />);
  await screen.findByRole('heading', { level: 1, name: 'Alpha' });
  expect(screen.getByRole('button', { name: 'Time: 2 hours. Change' })).toBeInTheDocument();
});
