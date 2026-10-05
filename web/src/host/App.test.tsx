import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { MOODS } from '../api/types';
import { ALPHA, CATALOG, GAMMA, appState, pick } from '../test/fixtures';
import { mockFetch } from '../test/fetchMock';
import { App } from './App';

function setup(state = appState()) {
  return mockFetch({
    'GET /api/state': () => [200, state],
    'GET /api/history': () => [200, { items: [] }],
    'GET /api/titles': () => [200, { items: CATALOG, total: CATALOG.length }],
    'POST /api/recommend': body => {
      const mood = (body as { session: { mood: string } }).session.mood;
      const order = mood === 'tense' ? [GAMMA, ALPHA] : [ALPHA, GAMMA];
      return [200, { recommendations: order.map(item => pick(item)), cold_start: true }];
    },
    'POST /api/feedback': body => {
      const { id, value } = body as { id: string; value: number };
      return [200, { feedback: value ? { [id]: value } : {} }];
    },
    'PUT /api/history/m1': () => [200, {}],
  });
}

test('shows the top pick with reasons, and every mood is selectable', async () => {
  setup();
  render(<App />);
  expect(await screen.findByRole('heading', { level: 1, name: 'Alpha' })).toBeInTheDocument();
  const reasons = screen.getByRole('list', { name: 'Why this pick' });
  expect(within(reasons).getByText('Your taste: quiet')).toBeInTheDocument();
  const moods = within(screen.getByRole('radiogroup', { name: 'Mood' })).getAllByRole('radio');
  expect(moods).toHaveLength(MOODS.length);
});

test('a mood chip re-ranks the picks with the new scene', async () => {
  const { calls } = setup();
  render(<App />);
  await screen.findByRole('heading', { level: 1, name: 'Alpha' });
  await userEvent.click(screen.getByRole('radio', { name: 'Tense' }));
  expect(await screen.findByRole('heading', { level: 1, name: 'Gamma' })).toBeInTheDocument();
  const last = calls.filter(c => c.path === '/api/recommend').at(-1);
  expect(last?.body).toMatchObject({ session: { mood: 'tense' }, mode: 'session' });
});

test('rating from the hero saves it and toggles off on a second press', async () => {
  const { calls } = setup();
  render(<App />);
  await screen.findByRole('heading', { level: 1, name: 'Alpha' });
  const hero = screen.getByRole('region', { name: 'Alpha' });
  await userEvent.click(within(hero).getByRole('button', { name: 'Like: Alpha' }));
  await waitFor(() =>
    expect(within(hero).getByRole('button', { name: 'Clear rating: Alpha' })).toHaveAttribute('aria-pressed', 'true'),
  );
  expect(calls.find(c => c.path === '/api/feedback')?.body).toEqual({ id: 'm1', value: 1 });
  await userEvent.click(within(hero).getByRole('button', { name: 'Clear rating: Alpha' }));
  await waitFor(() =>
    expect(calls.filter(c => c.path === '/api/feedback').at(-1)?.body).toEqual({ id: 'm1', value: 0 }),
  );
});

test('the details sheet explains the score and a playable title opens the player', async () => {
  setup();
  render(<App />);
  await screen.findByRole('heading', { level: 1, name: 'Alpha' });
  await userEvent.click(screen.getByRole('button', { name: 'Why this pick' }));
  const sheet = screen.getByRole('dialog', { name: 'Alpha' });
  expect(within(sheet).getByText('#1 of 2 for this moment')).toBeInTheDocument();
  expect(within(sheet).getByText('Your taste')).toBeInTheDocument();
  expect(within(sheet).getByText('0.60')).toBeInTheDocument(); // total equals the score
  await userEvent.click(within(sheet).getByRole('button', { name: 'Play' }));
  expect(screen.getByRole('dialog', { name: 'Playing Alpha' })).toBeInTheDocument();
});

test('titles without a local file offer no play button', async () => {
  setup(appState({ media: [] }));
  render(<App />);
  await screen.findByRole('heading', { level: 1, name: 'Alpha' });
  expect(screen.queryByRole('button', { name: 'Play' })).not.toBeInTheDocument();
});

test('a load failure is reported instead of a blank page', async () => {
  mockFetch({ 'GET /api/state': () => [503, { error: 'Local storage is unavailable' }] });
  render(<App />);
  expect(await screen.findByText(/Could not load Flicks: Local storage is unavailable/)).toBeInTheDocument();
});
