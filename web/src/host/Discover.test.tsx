import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { Content, DiscoverItem, DiscoverMedia, PickPool } from '../api/types';
import { ALPHA, BETA, GAMMA, appState, content, pick } from '../test/fixtures';
import { mockFetch } from '../test/fetchMock';
import { App } from './App';

const DELTA = content('m4', 'Delta', { genres: ['comedy'] });
const card = (
  item: Content,
  stream: DiscoverItem['stream'],
  media: DiscoverMedia = { kind: null, trailer: null },
): DiscoverItem => ({
  ...pick(item),
  stream,
  why: stream === 'wildcard' ? 'Wildcard: comedy, which you haven’t rated yet' : 'A top pick for this scene',
  media,
});

interface DiscoverBody {
  seen: string[];
  online: boolean;
}

function setup(state = appState()) {
  return mockFetch({
    'GET /api/state': () => [200, state],
    'GET /api/history': () => [200, { items: [] }],
    'GET /api/titles': () => [200, { items: [], total: 0, understood: [] }],
    'POST /api/recommend': () => [200, { recommendations: [pick(GAMMA), pick(BETA)], cold_start: true }],
    'POST /api/feedback': body => {
      const { id, value } = body as { id: string; value: number };
      return [200, { feedback: value ? { [id]: value } : {} }];
    },
    'POST /api/discover': body => {
      const { seen } = body as DiscoverBody;
      const all = [
        card(ALPHA, 'for_you', { kind: 'file', trailer: null }),
        card(BETA, 'new', { kind: null, trailer: 'tn2ffzzvC4o' }),
        card(DELTA, 'wildcard'),
      ];
      return [200, { items: all.filter(item => !seen.includes(item.content.id)) }];
    },
    'POST /api/pick': body => {
      const { pool } = body as { pool: PickPool };
      return [
        200,
        pool === 'picks'
          ? { pick: pick(BETA), chance: 0.17, pool: 12 }
          : { pick: pick(DELTA), chance: 0.004, pool: 250 },
      ];
    },
  });
}

async function openDiscover() {
  render(<App />);
  await screen.findByRole('heading', { level: 1, name: 'Gamma' });
  await userEvent.click(screen.getByRole('button', { name: 'Discover' }));
  return screen.findByRole('dialog', { name: 'Discover' });
}

test('Discover shows why each film is in the feed, and a like is a rating that moves on', async () => {
  const { calls } = setup();
  const feed = await openDiscover();
  const alpha = await within(feed).findByRole('article', { name: 'Alpha' });
  expect(within(alpha).getByText('For you')).toBeInTheDocument();
  expect(within(alpha).getByText('A top pick for this scene')).toBeInTheDocument();
  expect(within(feed).getByRole('article', { name: 'Delta' })).toHaveTextContent('Wildcard: comedy');
  expect(alpha.querySelector('video')).not.toBeNull(); // a local film previews itself, offline
  await userEvent.click(within(alpha).getByRole('button', { name: 'Like: Alpha' }));
  await waitFor(() => expect(calls.some(c => c.path === '/api/feedback')).toBe(true));
  expect(calls.find(c => c.path === '/api/feedback')?.body).toEqual({ id: 'm1', value: 1 });
  expect(alpha.querySelector('video')).toBeNull(); // only the card in view plays
  const first = calls.find(c => c.path === '/api/discover')?.body as DiscoverBody;
  expect(first).toMatchObject({ seen: [], online: false });
});

test('keys move through the feed and rate the card in view', async () => {
  const { calls } = setup();
  const feed = await openDiscover();
  await within(feed).findByRole('article', { name: 'Alpha' });
  await userEvent.keyboard('j');
  await userEvent.keyboard('p');
  await waitFor(() =>
    expect(calls.filter(c => c.path === '/api/feedback').map(c => c.body)).toEqual([{ id: 'm2', value: -1 }]),
  );
});

test('trailers play only after the viewer allows YouTube, and the choice is remembered', async () => {
  localStorage.clear();
  setup(appState({ trailers: 120 }));
  const feed = await openDiscover();
  await within(feed).findByRole('article', { name: 'Alpha' });
  await userEvent.keyboard('j'); // on to Beta, which has a trailer: still its poster
  expect(feed.querySelector('iframe')).toBeNull();
  await userEvent.click(within(feed).getByRole('button', { name: 'Online trailers off' }));
  const consent = within(feed).getByRole('alertdialog', { name: 'Play trailers from YouTube?' });
  expect(consent).toHaveTextContent('YouTube will see your IP address');
  await userEvent.click(within(consent).getByRole('button', { name: 'Allow trailers' }));
  expect(localStorage.getItem('flicks.trailers.0')).toBe('on');
  const frame = feed.querySelector('iframe'); // at once, on the card in view
  expect(frame?.src).toMatch(/^https:\/\/www\.youtube-nocookie\.com\/embed\/tn2ffzzvC4o\?/);
  expect(frame?.getAttribute('referrerpolicy')).toBe('strict-origin-when-cross-origin');
  await userEvent.click(within(feed).getByRole('button', { name: 'Online trailers on' }));
  expect(feed.querySelector('iframe')).toBeNull(); // off again needs no confirmation
  localStorage.clear();
});

test('no trailer switch when the server has no trailers', async () => {
  setup();
  const feed = await openDiscover();
  await within(feed).findByRole('article', { name: 'Alpha' });
  expect(within(feed).queryByRole('button', { name: /Online trailers/ })).not.toBeInTheDocument();
});

test('“Pick for me” opens a random pick with its chance, and can draw from anything', async () => {
  const { calls } = setup();
  render(<App />);
  await screen.findByRole('heading', { level: 1, name: 'Gamma' });
  await userEvent.click(screen.getByRole('button', { name: 'Pick for me' }));
  const sheet = await screen.findByRole('dialog', { name: 'Beta' });
  expect(within(sheet).getByRole('status')).toHaveTextContent(
    'Picked at random from your top 12 picks: a 1 in 6 chance',
  );
  await userEvent.click(within(sheet).getByRole('button', { name: 'From anything' }));
  const anything = await screen.findByRole('dialog', { name: 'Delta' });
  expect(within(anything).getByRole('status')).toHaveTextContent('all 250 titles that fit this scene: a 0.4% chance');
  expect(calls.filter(c => c.path === '/api/pick').map(c => (c.body as { pool: string }).pool)).toEqual([
    'picks',
    'anything',
  ]);
});
