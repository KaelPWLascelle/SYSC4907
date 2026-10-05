import type { CSSProperties } from 'react';

import type { Content } from '../../api/types';
import { Icon } from '../../components/Icon';
import { Poster } from '../../components/Poster';
import { RateButtons } from '../../components/RateButtons';
import { cx } from '../../lib/cx';
import { runtime, timestamp } from '../../lib/format';
import { useLibrary } from '../library';

interface TileProps {
  item: Content;
  /** Position in a ranked rail (1-based). */
  rank?: number;
  /** Resume playback instead of opening details (continue watching). */
  resume?: boolean;
}

export function Tile({ item, rank, resume = false }: TileProps) {
  const library = useLibrary();
  const rating = library.feedback[item.id];
  const playable = library.media.has(item.id);
  const progress = library.progress.get(item.id);
  const resumeAt = resume && progress?.resumable ? progress.position_seconds : null;
  const label =
    resumeAt !== null ? `Resume ${item.title} from ${timestamp(resumeAt)}` : `${item.title}, ${item.year}. Details`;

  return (
    <article className={cx('tile', rank && 'tile-ranked', rating === 1 && 'is-liked', rating === -1 && 'is-disliked')}>
      {rank !== undefined && (
        <span className="rank" aria-hidden="true">
          {rank}
        </span>
      )}
      <button
        type="button"
        className="tile-open"
        aria-label={label}
        onClick={() => (resumeAt !== null ? library.play(item) : library.openDetails(item))}
      >
        <Poster item={item} hasPoster={library.posters.has(item.id)} />
        {playable && (
          <span className="tile-badge" aria-hidden="true">
            <Icon name="play" /> {resumeAt !== null ? timestamp(resumeAt) : 'Ready'}
          </span>
        )}
        {progress?.resumable && (
          <span
            className="tile-progress"
            style={{ '--progress': progress.position_seconds / progress.duration_seconds } as CSSProperties}
            aria-hidden="true"
          />
        )}
      </button>
      <div className="tile-info">
        <h3 className="tile-title">{item.title}</h3>
        <p className="tile-sub">
          {item.year} · {runtime(item.minutes)}
        </p>
      </div>
      <RateButtons
        title={item.title}
        rating={rating}
        disabled={library.ratingBusy}
        onRate={value => library.rate(item.id, value)}
      />
    </article>
  );
}
