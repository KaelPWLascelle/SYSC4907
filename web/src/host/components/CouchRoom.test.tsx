import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { mockFetch } from '../../test/fetchMock';
import { useCouchHost } from '../hooks/useCouchHost';
import { DEFAULT_SESSION } from '../session';
import { CouchPanel } from './CouchPanel';

// The couch panel drawn as the room: seats that fill as phones join, bulbs that light when a guest has
// voted on everything, votes as bulbs under each title, and the spotlight on the group's pick.
const item = (id: string, title: string) => ({
  id,
  title,
  year: 2000,
  kind: 'movie',
  minutes: 100,
  genres: ['drama'],
  moods: [],
  intensity: 0.5,
  description: '',
  poster: false,
});
const live = {
  active: true,
  version: 1,
  code: 'K7QX2MPA',
  url: 'http://192.168.1.23:8770/join',
  join_url: 'http://192.168.1.23:8770/join#K7QX2MPA',
  items: [item('m1', 'Alpha'), item('m2', 'Beta')],
  revealed: false,
  results: null,
  game: null,
  expires_in: 100,
  player: { id: null, state: 'stopped', by: null },
  progress: [
    { name: 'Sam', voted: 2, total: 2 },
    { name: 'Priya', voted: 1, total: 2 },
  ],
};

function Harness() {
  const couch = useCouchHost(true);
  return <CouchPanel couch={couch} session={DEFAULT_SESSION} />;
}

test('each guest gets a seat, and their bulb lights once they have voted on everything', async () => {
  mockFetch({ 'GET /api/couch': () => [200, live] });
  render(<Harness />);
  const seats = await screen.findByRole('list', { name: 'Who’s voting' });
  expect(within(seats).getByText('Sam: 2 of 2').closest('li')).toHaveClass('is-done');
  expect(within(seats).getByText('Priya: 1 of 2').closest('li')).toHaveClass('is-voting');
  expect(screen.getByText('2 on the couch, 1 finished voting.')).toBeInTheDocument();
  // Two empty seats wait for more phones.
  expect(seats.querySelectorAll('.seat.is-empty')).toHaveLength(2);
  // Before the reveal, the shortlist shows no counts and nothing to play.
  const shortlist = screen.getByRole('list', { name: 'Shortlist' });
  expect(within(shortlist).queryByRole('img', { name: /yes/ })).toBeNull();
  expect(within(shortlist).queryByRole('button', { name: /^Play / })).toBeNull();
});

test('the reveal puts the spotlight on the group’s pick and shows every title’s votes as bulbs', async () => {
  const revealed = {
    ...live,
    revealed: true,
    progress: live.progress.map(p => ({ ...p, voted: 2 })),
    results: [
      { id: 'm2', yes: 2, no: 0, flicks_rank: 2, match: true },
      { id: 'm1', yes: 1, no: 1, flicks_rank: 1, match: false },
    ],
  };
  const { calls } = mockFetch({
    'GET /api/couch': () => [200, live],
    'POST /api/couch/reveal': () => [200, revealed],
    'POST /api/couch/player': () => [200, { ...revealed, player: { id: 'm2', state: 'playing', by: null } }],
  });
  render(<Harness />);
  await userEvent.click(await screen.findByRole('button', { name: 'Reveal results now' }));
  expect(
    await screen.findByText('Tonight it’s Beta, with 2 of 2 yes votes. It’s a match: everyone said yes.'),
  ).toBeInTheDocument();
  const shortlist = screen.getByRole('list', { name: 'Shortlist' });
  const winner = within(shortlist).getByRole('img', { name: 'Beta: 2 yes, 0 no' }).closest('li');
  expect(winner).toHaveClass('is-winner');
  expect(within(shortlist).getByRole('img', { name: 'Alpha: 1 yes, 1 no' }).closest('li')).not.toHaveClass('is-winner');
  expect(screen.getByRole('button', { name: 'Reveal results now' })).toBeDisabled();
  await userEvent.click(within(shortlist).getByRole('button', { name: 'Play Beta' }));
  expect(calls.find(c => c.path === '/api/couch/player')?.body).toEqual({ action: 'select', id: 'm2' });
  expect(await screen.findByText('Playing: Beta')).toBeInTheDocument();
});

test('an empty couch waits for the first phone', async () => {
  mockFetch({ 'GET /api/couch': () => [200, { ...live, progress: [] }] });
  render(<Harness />);
  expect(await screen.findByText('Waiting for the first phone.')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Reveal results now' })).toBeDisabled();
});
