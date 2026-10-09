import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { Command } from '../api/types';
import { ALPHA, CATALOG, GAMMA, appState, pick } from '../test/fixtures';
import { mockFetch } from '../test/fetchMock';
import { App } from './App';

function setup(command: Command) {
  return mockFetch({
    'GET /api/state': () => [200, appState()],
    'GET /api/history': () => [200, { items: [] }],
    'GET /api/titles': () => [200, { items: CATALOG, total: CATALOG.length, understood: ['Comedy', '1990s'] }],
    'POST /api/recommend': () => [200, { recommendations: [pick(ALPHA)], cold_start: true }],
    'POST /api/command/preview': () => [200, { command, session: appState().feedback, feedback: {} }],
    'POST /api/command/apply': () => [
      200,
      {
        command,
        session: {
          mood: 'any',
          minutes: 120,
          intensity: 0.5,
          novelty: 0.3,
          excluded_genres: [],
          medium: 'any',
          playable: false,
        },
        feedback: {},
      },
    ],
  });
}

async function ask(text: string) {
  const input = await screen.findByRole('textbox', { name: /Ask Flicks/ });
  await userEvent.type(input, `${text}{Enter}`);
}

test('an everyday request searches the catalogue at once and shows what it understood', async () => {
  const { calls } = setup({
    intent: 'search',
    query: 'funny films from the 90s',
    summary: 'Search for Comedy · 1990s',
  });
  render(<App />);
  await ask('funny films from the 90s');
  const understood = await screen.findByRole('list', { name: 'Search understood' });
  expect(within(understood).getByText('1990s')).toBeInTheDocument();
  expect(screen.getByRole('searchbox')).toHaveValue('funny films from the 90s');
  expect(calls.some(c => c.path === '/api/command/apply')).toBe(true); // no separate Apply press for a search
  expect(screen.getByRole('textbox', { name: /Ask Flicks/ })).toHaveValue(''); // ready for the next request
});

test('“play” starts the title when it can be played', async () => {
  setup({ intent: 'play', id: 'm1', content: ALPHA, summary: 'Play Alpha' });
  render(<App />);
  await ask('play alpha');
  expect(await screen.findByRole('dialog', { name: 'Playing Alpha' })).toBeInTheDocument();
});

test('“play” opens the details, with a note, when the title cannot be played', async () => {
  setup({ intent: 'play', id: 'm3', content: GAMMA, summary: 'Play Gamma' });
  render(<App />);
  await ask('play gamma');
  expect(await screen.findByRole('dialog', { name: 'Gamma' })).toBeInTheDocument();
  expect(screen.getByRole('alert')).toHaveTextContent('Gamma can’t be played here');
});

test('“more like” lists similar titles, and can go back to search', async () => {
  const { calls } = setup({ intent: 'search', similar: 'm1', content: ALPHA, summary: 'Show titles like Alpha' });
  render(<App />);
  await ask('more like alpha');
  expect(await screen.findByRole('heading', { name: 'More like Alpha' })).toBeInTheDocument();
  expect(calls.some(c => c.path === '/api/titles' && c.params.get('similar') === 'm1')).toBe(true);
  await userEvent.click(screen.getByRole('button', { name: 'Back to search' }));
  expect(await screen.findByRole('heading', { name: 'Browse & search' })).toBeInTheDocument();
});
