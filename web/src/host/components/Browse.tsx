import { useState } from 'react';

import type { Content } from '../../api/types';
import { RadioChips } from '../../components/Chips';
import { useLibrary } from '../library';
import { Tile } from './Tile';

type Filter = 'all' | 'liked' | 'passed' | 'unrated';
const FILTERS = [
  { value: 'all', label: 'All' },
  { value: 'liked', label: 'Liked' },
  { value: 'passed', label: 'Passed' },
  { value: 'unrated', label: 'Unrated' },
] as const;

export function Browse({ catalog }: { catalog: Content[] }) {
  const library = useLibrary();
  const [filter, setFilter] = useState<Filter>('all');
  const [query, setQuery] = useState('');
  const ratings = Object.values(library.feedback);
  const liked = ratings.filter(v => v === 1).length;
  const passed = ratings.filter(v => v === -1).length;
  const needle = query.trim().toLowerCase();
  const matches = catalog.filter(item => {
    const rating = library.feedback[item.id];
    const keep =
      filter === 'all' ||
      (filter === 'liked' && rating === 1) ||
      (filter === 'passed' && rating === -1) ||
      (filter === 'unrated' && !rating);
    return keep && `${item.title} ${item.genres.join(' ')} ${item.tags.join(' ')}`.toLowerCase().includes(needle);
  });

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
          <RadioChips label="Show" className="segmented" options={FILTERS} value={filter} onChange={setFilter} />
          <label className="search">
            <span className="visually-hidden">Search the catalogue</span>
            <input
              type="search"
              placeholder="Search titles, genres, themes"
              value={query}
              onChange={event => setQuery(event.target.value)}
            />
          </label>
        </div>
      </div>
      <div className="grid">
        {matches.length ? (
          matches.map(item => <Tile key={item.id} item={item} />)
        ) : (
          <p className="empty">No titles match. Try another search or filter.</p>
        )}
      </div>
    </section>
  );
}
