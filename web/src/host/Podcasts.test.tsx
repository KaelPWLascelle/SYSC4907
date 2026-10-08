import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { DownloadStatus, MediaEntry } from '../api/types';
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

const STREAMS: MediaEntry[] = [
  { id: 'pod1', direct_play: true, audio: true, remote: true, source: 'In Our Time', page: 'https://example.com/iot' },
  {
    id: 'm1',
    direct_play: true,
    audio: false,
    remote: true,
    source: 'Internet Archive',
    page: 'https://archive.org/details/a',
  },
];

function setup(downloads: () => Record<string, DownloadStatus>, media: MediaEntry[] = STREAMS) {
  return mockFetch({
    'GET /api/state': () => [200, appState({ podcasts: true, media })],
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

test('an episode streams from the hero at once, without downloading', async () => {
  const { calls } = setup(() => ({}));
  render(<App />);
  const hero = await screen.findByRole('region', { name: 'The Gracchi' });
  expect(within(hero).getByText(/Podcast · In Our Time · 50m/)).toBeInTheDocument();
  await userEvent.click(within(hero).getByRole('button', { name: 'Play' }));
  expect(await screen.findByText('Now listening')).toBeInTheDocument();
  expect(document.querySelector('audio')).toHaveAttribute('src', '/media/pod1');
  expect(calls.some(c => c.method === 'POST' && c.path.endsWith('/download'))).toBe(false);
});

test('an episode can be kept for offline listening from its details', async () => {
  let downloaded = false;
  const ready: Record<string, DownloadStatus> = { pod1: { state: 'ready', size: 1000 } };
  const { calls } = setup(() => (downloaded ? ready : {}));
  render(<App />);
  const hero = await screen.findByRole('region', { name: 'The Gracchi' });
  await userEvent.click(within(hero).getByRole('button', { name: 'Why this pick' }));
  const sheet = screen.getByRole('dialog', { name: 'The Gracchi' });
  expect(within(sheet).getByText(/Streams from In Our Time’s public feed/)).toBeInTheDocument();
  expect(within(sheet).getByRole('link', { name: 'Visit In Our Time’s page' })).toHaveAttribute(
    'href',
    'https://example.com/iot',
  );

  downloaded = true;
  await userEvent.click(within(sheet).getByRole('button', { name: 'Download for offline' }));
  expect(calls.some(c => c.method === 'POST' && c.path === '/api/podcasts/pod1/download')).toBe(true);
  expect(await within(sheet).findByRole('button', { name: 'Remove download' })).toBeInTheDocument();
});

test('a failed download says why and offers to try again', async () => {
  setup(() => ({ pod1: { state: 'failed', error: 'Download failed: the server answered 404' } }));
  render(<App />);
  const hero = await screen.findByRole('region', { name: 'The Gracchi' });
  await userEvent.click(within(hero).getByRole('button', { name: 'Why this pick' }));
  const sheet = screen.getByRole('dialog', { name: 'The Gracchi' });
  expect(await within(sheet).findByRole('alert')).toHaveTextContent('the server answered 404');
  expect(within(sheet).getByRole('button', { name: 'Try the download again' })).toBeInTheDocument();
});

test('a public-domain film streams from the Internet Archive, with credit', async () => {
  setup(() => ({}));
  render(<App />);
  const choice = await screen.findByRole('radiogroup', { name: 'Watch or listen' });
  await userEvent.click(within(choice).getByRole('radio', { name: 'Watch' }));
  const hero = await screen.findByRole('region', { name: 'Alpha' });
  await userEvent.click(within(hero).getByRole('button', { name: 'Why this pick' }));
  const sheet = screen.getByRole('dialog', { name: 'Alpha' });
  expect(
    within(sheet).getByText(/Streams from the Internet Archive, where this film is in the public domain/),
  ).toBeInTheDocument();
  expect(within(sheet).getByRole('link', { name: 'View it on the Internet Archive' })).toHaveAttribute(
    'href',
    'https://archive.org/details/a',
  );
  expect(within(sheet).queryByRole('button', { name: /Download/ })).not.toBeInTheDocument();
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

test('a stream that fails says where it was streaming from', () => {
  render(
    <Player
      item={EPISODE}
      startAt={0}
      directPlay
      audio
      streamedFrom="In Our Time"
      remote={null}
      onProgress={() => {}}
      onClose={() => {}}
    />,
  );
  const audio = document.querySelector('audio');
  if (!audio) throw new Error('no audio element');
  Object.defineProperty(audio, 'error', { configurable: true, value: { code: 2 } });
  fireEvent.error(audio);
  expect(screen.getByRole('alert')).toHaveTextContent('Couldn’t stream this from In Our Time');
});
