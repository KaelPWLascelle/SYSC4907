import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { TasteResponse } from '../api/types';
import { ALPHA, CATALOG, GAMMA, appState, pick } from '../test/fixtures';
import { mockFetch } from '../test/fetchMock';
import { App } from './App';

const TASTE: TasteResponse = {
  liked: 3,
  passed: 1,
  genres: [
    { genre: 'science-fiction', liked: 3, passed: 0, affinity: 0.6 },
    { genre: 'musical', liked: 0, passed: 1, affinity: -0.33 },
  ],
  themes: {
    liked: [
      { term: 'space', weight: 1 },
      { term: 'heist', weight: 0.5 },
    ],
    passed: [],
  },
  influences: [{ title: 'Alien', picks: 9 }],
};

function setup() {
  localStorage.clear();
  return mockFetch({
    'GET /api/state': () => [200, appState({ profile: { id: 1, name: 'Me', locked: false, chosen: false, count: 1 } })],
    'GET /api/history': () => [200, { items: [] }],
    'GET /api/titles': () => [200, { items: CATALOG, total: CATALOG.length, understood: [] }],
    'GET /api/taste': () => [200, TASTE],
    'POST /api/recommend': body => {
      const mix = (body as { session: { mix: number[] } }).session.mix;
      const order = mix[0] === 1 ? [GAMMA, ALPHA] : [ALPHA, GAMMA];
      return [200, { recommendations: order.map(item => pick(item)), cold_start: false }];
    },
  });
}

test('“Your taste” draws genres, themes and influences, with a table view and browse links', async () => {
  const { calls } = setup();
  render(<App />);
  await screen.findByRole('heading', { level: 1, name: 'Alpha' });
  await userEvent.click(screen.getByRole('button', { name: 'Your taste' }));
  const sheet = await screen.findByRole('dialog', { name: 'Your taste' });
  expect(await within(sheet).findByText(/Built from 3 likes and 1 pass/)).toBeInTheDocument();
  const genres = within(sheet).getByRole('list', { name: /Genre lean/ });
  expect(within(genres).getAllByRole('button')).toHaveLength(2);
  await userEvent.click(within(sheet).getByRole('button', { name: 'Show table' }));
  expect(within(sheet).getByRole('table')).toHaveTextContent('Science-fiction30+60');
  expect(within(sheet).getByText('Alien')).toBeInTheDocument();
  await userEvent.click(within(sheet).getByRole('button', { name: /space: 100%.*Browse/ }));
  await waitFor(() => expect(calls.some(c => c.path === '/api/titles' && c.params.get('q') === 'space')).toBe(true));
});

test('the mix tuner previews the new order and applies it to every pick request', async () => {
  const { calls } = setup();
  render(<App />);
  await screen.findByRole('heading', { level: 1, name: 'Alpha' });
  await userEvent.click(screen.getByRole('button', { name: 'Your taste' }));
  const sheet = await screen.findByRole('dialog', { name: 'Your taste' });
  const sliders = await within(sheet).findAllByRole('slider');
  expect(sliders).toHaveLength(4);
  for (const slider of sliders.slice(1)) fireEvent.change(slider, { target: { value: '0' } });
  expect(await within(sheet).findByText('Gamma', {}, { timeout: 2000 })).toBeInTheDocument();
  await userEvent.click(within(sheet).getByRole('button', { name: 'Use this mix' }));
  await waitFor(() =>
    expect(calls.filter(c => c.path === '/api/recommend').at(-1)?.body).toMatchObject({
      session: { mix: [1, 0, 0, 0] },
    }),
  );
  expect(JSON.parse(localStorage.getItem('flicks.mix.1') ?? 'null')).toEqual([1, 0, 0, 0]);
});
