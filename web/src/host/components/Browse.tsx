import { useState } from 'react';

import type { TitleFilter, TitleRef } from '../../api/types';
import { RadioChips } from '../../components/Chips';
import { Icon } from '../../components/Icon';
import { useTitles } from '../hooks/useTitles';
import { useLibrary } from '../library';
import { Tile } from './Tile';

const FILTERS = [
  { value: 'all', label: 'All' },
  { value: 'liked', label: 'Liked' },
  { value: 'passed', label: 'Passed' },
  { value: 'unrated', label: 'Unrated' },
] as const;

interface BrowseProps {
  /** The search text; the app sets it too, when Ask Flicks turns a request into a search. */
  query: string;
  onQuery: (query: string) => void;
  /** List titles like this one instead of searching ("more like Alien"). */
  similar: TitleRef | null;
  onClearSimilar: () => void;
}

/** Search and rate the whole catalogue: everyday-language search, most popular first when empty. */
export function Browse({ query, onQuery, similar, onClearSimilar }: BrowseProps) {
  const library = useLibrary();
  const [show, setShow] = useState<TitleFilter>('all');
  const titles = useTitles(similar ? '' : query, show, library.feedback, similar?.id ?? null);
  const ratings = Object.values(library.feedback);
  const liked = ratings.filter(v => v === 1).length;
  const passed = ratings.filter(v => v === -1).length;
  const count = `${titles.total.toLocaleString()} ${titles.total === 1 ? 'title' : 'titles'}`;

  return (
    <section className="browse" id="browse" aria-labelledby="browse-heading">
      <div className="row-head">
        <div>
          <h2 id="browse-heading">{similar ? `More like ${similar.title}` : 'Browse & search'}</h2>
          <p>
            {liked || passed
              ? `${liked} liked · ${passed} passed · saved on this device`
              : 'Like a few favourites to teach Flicks your taste.'}
          </p>
        </div>
        <div className="browse-tools">
          <RadioChips label="Show" className="segmented" options={FILTERS} value={show} onChange={setShow} />
          {similar ? (
            <button type="button" className="button button-quiet" onClick={onClearSimilar}>
              <Icon name="close" />
              Back to search
            </button>
          ) : (
            <label className="search">
              <span className="visually-hidden">Search the catalogue</span>
              <input
                type="search"
                placeholder="Try “funny films from the 90s” or “keaton”"
                value={query}
                onChange={event => onQuery(event.target.value)}
              />
            </label>
          )}
        </div>
      </div>
      <div className="hint browse-status" role="status" aria-live="polite">
        {titles.error ? (
          `Could not search the catalogue: ${titles.error}`
        ) : titles.loading ? (
          'Searching…'
        ) : titles.total ? (
          <>
            <span>
              <span>{count}</span>
              {!query.trim() && !similar && <span>, most popular first</span>}
            </span>
            {titles.understood.length > 0 && (
              <ul className="understood" aria-label="Search understood">
                {titles.understood.map(label => (
                  <li key={label}>{label}</li>
                ))}
              </ul>
            )}
          </>
        ) : (
          'No titles match. Try fewer words, or another filter.'
        )}
      </div>
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
