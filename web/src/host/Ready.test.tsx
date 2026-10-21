import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { Session } from '../api/types';
import { ALPHA, BETA, GAMMA, appState, pick } from '../test/fixtures';
import { mockFetch } from '../test/fetchMock';
import { App } from './App';

function setup() {
  return mockFetch({
    'GET /api/state': () => [200, appState()],
    'GET /api/history': () => [200, { items: [] }],
    'GET /api/titles': () => [200, { items: [], total: 0, understood: [] }],
    'POST /api/recommend': body => {
      const { session } = body as { session: Session };
      const picks = session.playable ? [ALPHA] : [GAMMA, BETA];
      return [200, { recommendations: picks.map(item => pick(item)), cold_start: true }];
    },
  });
}

test('a row offers what can be played now, ranked for you', async () => {
  const { calls } = setup();
  render(<App />);
  const row = await screen.findByRole('region', { name: 'Ready to watch now' });
  expect(within(row).getByRole('heading', { name: 'Alpha' })).toBeInTheDocument();
  const asked = calls.filter(c => c.path === '/api/recommend').map(c => (c.body as { session: Session }).session);
  expect(asked.some(s => s.playable && s.medium === 'watch')).toBe(true);
});

test('the scene can be limited to what can be played now', async () => {
  const { calls } = setup();
  render(<App />);
  await screen.findByRole('heading', { level: 1, name: 'Gamma' });
  await userEvent.click(screen.getByRole('button', { name: 'Ready to play' }));
  expect(await screen.findByRole('heading', { level: 1, name: 'Alpha' })).toBeInTheDocument();
  expect(screen.queryByRole('region', { name: 'Ready to watch now' })).not.toBeInTheDocument(); // the main row is it now
  const last = calls.filter(c => c.path === '/api/recommend').at(-1)?.body as { session: Session };
  expect(last.session.playable).toBe(true);
});

test('when a film ends, up next is the best playable pick that is not the film just watched', async () => {
  mockFetch({
    'GET /api/state': () => [
      200,
      appState({
        media: ['m1', 'm3'].map(id => ({
          id,
          direct_play: true,
          audio: false,
          remote: false,
          source: null,
          page: null,
        })),
      }),
    ],
    'GET /api/history': () => [200, { items: [] }],
    'GET /api/titles': () => [200, { items: [], total: 0, understood: [] }],
    'PUT /api/history/m1': () => [200, {}],
    'POST /api/recommend': body => {
      const { session } = body as { session: Session };
      const picks = session.playable ? [ALPHA, GAMMA] : [GAMMA, BETA];
      return [200, { recommendations: picks.map(item => pick(item)), cold_start: true }];
    },
  });
  render(<App />);
  const row = await screen.findByRole('region', { name: 'Ready to watch now' });
  await userEvent.click(within(row).getByRole('button', { name: /Alpha.*Details/ }));
  await userEvent.click(
    within(await screen.findByRole('dialog', { name: 'Alpha' })).getByRole('button', { name: 'Play' }),
  );
  const player = await screen.findByRole('dialog', { name: 'Playing Alpha' });
  const node = player.querySelector('video') as HTMLVideoElement;
  Object.defineProperty(node, 'duration', { configurable: true, value: 600 });
  Object.defineProperty(node, 'ended', { configurable: true, value: true });
  fireEvent.ended(node);
  const finished = within(player).getByRole('region', { name: 'Finished' });
  expect(within(finished).getByRole('heading', { name: 'Gamma' })).toBeInTheDocument();
});
