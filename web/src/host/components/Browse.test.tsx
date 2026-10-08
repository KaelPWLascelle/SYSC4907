import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';

import type { Content } from '../../api/types';
import { content } from '../../test/fixtures';
import { PAGE_SIZE } from '../hooks/useTitles';
import { type Library, LibraryContext } from '../library';
import { Browse } from './Browse';

// Titles 0..52: one more page than fits, so paging is exercised.
const many = Array.from({ length: PAGE_SIZE + 5 }, (_, i) => content(`t${i}`, `Title ${i}`));

function library(feedback: Library['feedback'] = {}): Library {
  return {
    posters: new Set(),
    media: new Map(),
    feedback,
    progress: new Map(),
    downloads: new Map(),
    ratingBusy: false,
    rate: vi.fn(),
    openDetails: vi.fn(),
    play: vi.fn(),
    download: vi.fn(),
    removeDownload: vi.fn(),
  };
}

/** A tiny /api/titles: case-insensitive substring search plus offset/limit, like the real endpoint. */
function catalogServer(catalog: Content[]) {
  const calls: URLSearchParams[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const params = new URL(String(input), 'http://127.0.0.1').searchParams;
      calls.push(params);
      const q = (params.get('q') ?? '').toLowerCase();
      const offset = Number(params.get('offset'));
      const limit = Number(params.get('limit'));
      const matches = catalog.filter(item => item.title.toLowerCase().includes(q));
      return new Response(JSON.stringify({ items: matches.slice(offset, offset + limit), total: matches.length }), {
        headers: { 'Content-Type': 'application/json' },
      });
    }),
  );
  return calls;
}

function renderBrowse(value = library()) {
  return render(
    <LibraryContext.Provider value={value}>
      <Browse />
    </LibraryContext.Provider>,
  );
}

test('shows the first page and the total, and "Show more" appends the next page', async () => {
  catalogServer(many);
  renderBrowse();
  expect(await screen.findByText(`${many.length} titles`)).toBeInTheDocument();
  expect(screen.getAllByRole('article')).toHaveLength(PAGE_SIZE);
  await userEvent.click(screen.getByRole('button', { name: `Show more (${PAGE_SIZE} of ${many.length})` }));
  await waitFor(() => expect(screen.getAllByRole('article')).toHaveLength(many.length));
  expect(screen.queryByRole('button', { name: /Show more/ })).not.toBeInTheDocument();
});

test('searching asks the server and replaces the results', async () => {
  const calls = catalogServer(many);
  renderBrowse();
  await screen.findByText(`${many.length} titles`);
  await userEvent.type(screen.getByRole('searchbox', { name: 'Search the catalogue' }), 'Title 5');
  expect(await screen.findByText('4 titles')).toBeInTheDocument(); // Title 5, 50, 51, 52
  expect(screen.getAllByRole('article')).toHaveLength(4);
  expect(calls.at(-1)?.get('q')).toBe('Title 5');
});

test('a rating filter is sent to the server', async () => {
  const calls = catalogServer(many);
  renderBrowse(library({ t1: 1 }));
  await screen.findByText(`${many.length} titles`);
  await userEvent.click(screen.getByRole('radio', { name: 'Liked' }));
  await waitFor(() => expect(calls.at(-1)?.get('show')).toBe('liked'));
});
