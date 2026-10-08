import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { CouchGuestView } from '../api/types';
import { type Reply, deferred, mockFetch } from '../test/fetchMock';
import { GuestApp } from './GuestApp';

const items = [
  {
    id: 'a',
    title: 'Alpha',
    year: 2000,
    kind: 'movie',
    series: null,
    minutes: 90,
    genres: ['drama'],
    moods: [],
    intensity: 0.5,
    description: 'About Alpha',
    poster: false,
  },
  {
    id: 'b',
    title: 'Beta',
    year: 2001,
    kind: 'movie',
    series: null,
    minutes: 95,
    genres: ['comedy'],
    moods: [],
    intensity: 0.5,
    description: 'About Beta',
    poster: false,
  },
];
const view = (over: Partial<CouchGuestView> = {}): CouchGuestView => ({
  active: true,
  version: 1,
  items,
  revealed: false,
  results: null,
  expires_in: 100,
  player: { id: null, state: 'stopped', by: null },
  progress: [{ name: 'Sam', voted: 0, total: 2 }],
  you: { id: 'g1', name: 'Sam', votes: {} },
  ...over,
});

/** Replies to GET /api/couch/state in order; the last one repeats. */
function stateQueue(...replies: Reply[]): () => Reply {
  let next = 0;
  return () => replies[Math.min(next++, replies.length - 1)] ?? [500, { error: 'no reply queued' }];
}

test('the QR fragment fills in the code, leaves the address bar, and nothing is requested before joining', () => {
  window.history.replaceState(null, '', '/join#abcd2345');
  const { calls } = mockFetch({});
  render(<GuestApp />);
  expect(screen.getByLabelText('Code on the TV')).toHaveValue('ABCD2345');
  expect(window.location.href).not.toContain('#');
  expect(screen.getByLabelText('Your name')).toHaveFocus();
  expect(calls).toHaveLength(0);
});

test('joining stores the token, sends it on every request and shows the first title', async () => {
  window.history.replaceState(null, '', '/join#ABCD2345');
  const { calls } = mockFetch({
    'POST /api/couch/join': () => [200, { token: 't1', name: 'Sam' }],
    'GET /api/couch/state': () => [200, view()],
  });
  render(<GuestApp />);
  await userEvent.type(screen.getByLabelText('Your name'), 'Sam');
  await userEvent.click(screen.getByRole('button', { name: 'Join the couch' }));
  expect(await screen.findByRole('heading', { name: 'Alpha' })).toBeInTheDocument();
  expect(calls[0]).toMatchObject({ method: 'POST', path: '/api/couch/join', body: { code: 'ABCD2345', name: 'Sam' } });
  expect(calls.find(c => c.path === '/api/couch/state')?.headers['X-Flicks-Guest']).toBe('t1');
  expect(sessionStorage.getItem('flicks-guest')).toBe('t1');
  expect(screen.getByText('Title 1 of 2')).toBeInTheDocument();
});

test('a poll that started before a vote cannot overwrite the vote', async () => {
  sessionStorage.setItem('flicks-guest', 't1');
  const stale = deferred<[number, unknown]>();
  mockFetch({
    'GET /api/couch/state': stateQueue([200, view()], stale.promise),
    'POST /api/couch/vote': () => [200, view({ version: 3, you: { id: 'g1', name: 'Sam', votes: { a: 1 } } })],
  });
  render(<GuestApp />);
  expect(await screen.findByRole('heading', { name: 'Alpha' })).toBeInTheDocument();
  act(() => {
    document.dispatchEvent(new Event('visibilitychange')); // starts a poll whose reply is held back
  });
  await userEvent.click(screen.getByRole('button', { name: '✓ I’d watch it' }));
  expect(await screen.findByRole('heading', { name: 'Beta' })).toBeInTheDocument();
  await act(async () => stale.resolve([200, view({ version: 2 })]));
  expect(screen.getByRole('heading', { name: 'Beta' })).toBeInTheDocument();
});

test('an unknown or expired token goes back to the join screen', async () => {
  sessionStorage.setItem('flicks-guest', 'old');
  mockFetch({ 'GET /api/couch/state': () => [401, { error: 'Join the couch session first' }] });
  render(<GuestApp />);
  expect(await screen.findByRole('button', { name: 'Join the couch' })).toBeInTheDocument();
  expect(sessionStorage.getItem('flicks-guest')).toBeNull();
  expect(screen.queryByRole('region', { name: 'Remote control' })).not.toBeInTheDocument();
});

test('results show the match, and the remote plays the chosen title on the TV', async () => {
  sessionStorage.setItem('flicks-guest', 't1');
  const revealed = view({
    revealed: true,
    results: [
      { id: 'b', yes: 2, no: 0, flicks_rank: 2, match: true },
      { id: 'a', yes: 1, no: 1, flicks_rank: 1, match: false },
    ],
    progress: [
      { name: 'Sam', voted: 2, total: 2 },
      { name: 'Alex', voted: 2, total: 2 },
    ],
  });
  const { calls } = mockFetch({
    'GET /api/couch/state': () => [200, revealed],
    'POST /api/couch/remote': body => [
      200,
      { ...revealed, version: 2, player: { id: (body as { id: string }).id, state: 'playing', by: 'Sam' } },
    ],
  });
  render(<GuestApp />);
  expect(await screen.findByText('It’s a match')).toBeInTheDocument();
  expect(screen.getByRole('heading', { name: 'Beta' })).toBeInTheDocument();
  expect(screen.getByText(/^2 of 2 said yes\./)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '▶ Play' })).toBeDisabled(); // nothing selected yet
  await userEvent.click(screen.getByRole('button', { name: 'Play Beta on the TV' }));
  await waitFor(() => expect(screen.getByText('Playing: Beta (by Sam)')).toBeInTheDocument());
  expect(calls.at(-1)).toMatchObject({ path: '/api/couch/remote', body: { action: 'select', id: 'b' } });
  expect(screen.getByRole('button', { name: '❚❚ Pause' })).toBeEnabled();
});
