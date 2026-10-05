import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { DownloadStatus } from '../api/types';
import { ALPHA, appState, content, pick } from '../test/fixtures';
import { mockFetch } from '../test/fetchMock';
import { App } from './App';
import { Player } from './components/Player';

const EPISODE = content('pod1', 'The Gracchi', {
  kind: 'episode',
  series: 'In Our Time',
  minutes: 50,
  genres: ['history'],
});

function setup(downloads: () => Record<string, DownloadStatus>) {
  return mockFetch({
    'GET /api/state': () => [200, appState({ podcasts: true })],
    'GET /api/history': () => [200, { items: [] }],
    'GET /api/titles': () => [200, { items: [], total: 0 }],
    'GET /api/podcasts/downloads': () => [200, { downloads: downloads() }],
    'POST /api/recommend': body => {
      const medium = (body as { session: { medium: string } }).session.medium;
      return [
        200,
        { recommendations: (medium === 'watch' ? [ALPHA] : [EPISODE, ALPHA]).map(i => pick(i)), cold_start: true },
      ];
    },
    'POST /api/podcasts/pod1/download': () => [202, { state: 'queued' }],
  });
}

test('an episode can be downloaded from the hero and then played', async () => {
  let downloaded = false;
  const ready: Record<string, DownloadStatus> = { pod1: { state: 'ready', size: 1000 } };
  const { calls } = setup(() => (downloaded ? ready : {}));
  render(<App />);
  const hero = await screen.findByRole('region', { name: 'The Gracchi' });
  expect(within(hero).getByText(/Podcast · In Our Time · 50m/)).toBeInTheDocument();
  expect(within(hero).queryByRole('button', { name: /Play/ })).not.toBeInTheDocument();

  downloaded = true;
  await userEvent.click(within(hero).getByRole('button', { name: 'Download episode' }));
  expect(calls.some(c => c.method === 'POST' && c.path === '/api/podcasts/pod1/download')).toBe(true);
  await userEvent.click(await within(hero).findByRole('button', { name: 'Play' }));
  expect(await screen.findByText('Now listening')).toBeInTheDocument();
  expect(document.querySelector('audio')).toHaveAttribute('src', '/media/pod1');
  expect(document.querySelector('video')).toBeNull();
});

test('a failed download says why and offers to try again', async () => {
  setup(() => ({ pod1: { state: 'failed', error: 'Download failed: the server answered 404' } }));
  render(<App />);
  const hero = await screen.findByRole('region', { name: 'The Gracchi' });
  expect(await within(hero).findByRole('alert')).toHaveTextContent('the server answered 404');
  expect(within(hero).getByRole('button', { name: 'Try the download again' })).toBeInTheDocument();
});

test('the scene can ask for something to watch or to listen to', async () => {
  const { calls } = setup(() => ({}));
  render(<App />);
  await screen.findByRole('region', { name: 'The Gracchi' });
  const choice = screen.getByRole('radiogroup', { name: 'Watch or listen' });
  await userEvent.click(within(choice).getByRole('radio', { name: 'Watch' }));
  expect(await screen.findByRole('heading', { level: 1, name: 'Alpha' })).toBeInTheDocument();
  expect(calls.filter(c => c.path === '/api/recommend').at(-1)?.body).toMatchObject({ session: { medium: 'watch' } });
});

test('without a podcast catalogue there is no watch-or-listen choice and no download polling', async () => {
  const { calls } = mockFetch({
    'GET /api/state': () => [200, appState()],
    'GET /api/history': () => [200, { items: [] }],
    'GET /api/titles': () => [200, { items: [], total: 0 }],
    'POST /api/recommend': () => [200, { recommendations: [pick(ALPHA)], cold_start: true }],
  });
  render(<App />);
  await screen.findByRole('heading', { level: 1, name: 'Alpha' });
  expect(screen.queryByRole('radiogroup', { name: 'Watch or listen' })).not.toBeInTheDocument();
  expect(calls.some(c => c.path.startsWith('/api/podcasts'))).toBe(false);
});

test('the player shows audio for episodes', () => {
  render(<Player item={EPISODE} startAt={0} directPlay audio remote={null} onProgress={() => {}} onClose={() => {}} />);
  expect(screen.getByText('Now listening')).toBeInTheDocument();
  expect(document.querySelector('audio')).not.toBeNull();
  expect(document.querySelector('video')).toBeNull();
});
