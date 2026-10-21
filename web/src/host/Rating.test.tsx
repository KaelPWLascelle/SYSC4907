import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { ALPHA, CATALOG, GAMMA, appState, pick } from '../test/fixtures';
import { deferred, mockFetch } from '../test/fetchMock';
import { App } from './App';

function setup(feedback: (body: { id: string; value: number }) => Promise<[number, unknown]> | [number, unknown]) {
  return mockFetch({
    'GET /api/state': () => [200, appState()],
    'GET /api/history': () => [200, { items: [] }],
    'GET /api/titles': () => [200, { items: CATALOG, total: CATALOG.length, understood: [] }],
    'POST /api/recommend': () => [200, { recommendations: [pick(ALPHA), pick(GAMMA)], cold_start: true }],
    'POST /api/feedback': body => feedback(body as { id: string; value: number }),
  });
}

test('a like shows at once, and no other rating button is disabled while it saves', async () => {
  const reply = deferred<[number, unknown]>();
  setup(() => reply.promise);
  render(<App />);
  const hero = await screen.findByRole('region', { name: 'Alpha' });
  await userEvent.click(within(hero).getByRole('button', { name: 'Like: Alpha' }));
  // Still saving, but the button already shows the like and every other button stays usable.
  expect(within(hero).getByRole('button', { name: 'Clear rating: Alpha' })).toHaveAttribute('aria-pressed', 'true');
  expect(
    screen.getAllByRole('button', { name: /^(Like|Not for me): / }).every(b => !(b as HTMLButtonElement).disabled),
  ).toBe(true);
  reply.resolve([200, { feedback: { m1: 1 } }]);
  await waitFor(() => expect(within(hero).getByRole('button', { name: 'Clear rating: Alpha' })).toBeInTheDocument());
});

test('a failed save puts back the previous rating and says so', async () => {
  setup(() => [503, { error: 'Local storage is unavailable' }]);
  render(<App />);
  const hero = await screen.findByRole('region', { name: 'Alpha' });
  await userEvent.click(within(hero).getByRole('button', { name: 'Like: Alpha' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not save your rating');
  expect(within(hero).getByRole('button', { name: 'Like: Alpha' })).toHaveAttribute('aria-pressed', 'false');
});

test('quick like-then-clear saves in order and ends cleared', async () => {
  const sent: number[] = [];
  setup(body => {
    sent.push(body.value);
    return [200, { feedback: body.value ? { [body.id]: body.value } : {} }];
  });
  render(<App />);
  const hero = await screen.findByRole('region', { name: 'Alpha' });
  await userEvent.click(within(hero).getByRole('button', { name: 'Like: Alpha' }));
  await userEvent.click(within(hero).getByRole('button', { name: 'Clear rating: Alpha' }));
  await waitFor(() => expect(sent).toEqual([1, 0]));
  expect(within(hero).getByRole('button', { name: 'Like: Alpha' })).toHaveAttribute('aria-pressed', 'false');
});
