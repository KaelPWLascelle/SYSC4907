import { useState } from 'react';

import type { TitleFilter } from '../../api/types';
import { RadioChips } from '../../components/Chips';
import { useTitles } from '../hooks/useTitles';
import { useLibrary } from '../library';
import { Tile } from './Tile';

const FILTERS = [
  { value: 'all', label: 'All' },
  { value: 'liked', label: 'Liked' },
  { value: 'passed', label: 'Passed' },
  { value: 'unrated', label: 'Unrated' },
] as const;

export function Browse() {
  const library = useLibrary();
  const [show, setShow] = useState<TitleFilter>('all');
  const [query, setQuery] = useState('');
  const titles = useTitles(query, show, library.feedback);
  const ratings = Object.values(library.feedback);
  const liked = ratings.filter(v => v === 1).length;
  const passed = ratings.filter(v => v === -1).length;

  return (
    <section className="browse" id="browse" aria-labelledby="browse-heading">
      <div className="row-head">
        <div>
          <h2 id="browse-heading">Browse &amp; rate</h2>
          <p>
            {liked || passed
              ? `${liked} liked · ${passed} passed · saved on this device`
              : 'Like a few favourites to teach Flicks your taste.'}
          </p>
        </div>
        <div className="browse-tools">
          <RadioChips label="Show" className="segmented" options={FILTERS} value={show} onChange={setShow} />
          <label className="search">
            <span className="visually-hidden">Search the catalogue</span>
            <input
              type="search"
              placeholder="Search titles, genres, themes, years"
              value={query}
              onChange={event => setQuery(event.target.value)}
            />
          </label>
        </div>
      </div>
      <p className="hint" role="status" aria-live="polite">
        {titles.error
          ? `Could not search the catalogue: ${titles.error}`
          : titles.loading
            ? 'Searching…'
            : titles.total
              ? `${titles.total.toLocaleString()} ${titles.total === 1 ? 'title' : 'titles'}`
              : 'No titles match. Try another search or filter.'}
      </p>
      <div className="grid" aria-busy={titles.loading}>
        {titles.items.map(item => (
          <Tile key={item.id} item={item} />
        ))}
      </div>
      {!titles.loading && titles.items.length < titles.total && (
        <div className="more">
          <button
            type="button"
            className="button button-quiet"
            disabled={titles.loadingMore}
            onClick={() => void titles.loadMore()}
          >
            {titles.loadingMore
              ? 'Loading…'
              : `Show more (${titles.items.length.toLocaleString()} of ${titles.total.toLocaleString()})`}
          </button>
        </div>
      )}
    </section>
  );
}
