import type { CSSProperties, PointerEvent } from 'react';

import type { Content } from '../../api/types';
import { Icon } from '../../components/Icon';
import { Poster } from '../../components/Poster';
import { RateButtons } from '../../components/RateButtons';
import { cx } from '../../lib/cx';
import { runtime, subtitle, timestamp } from '../../lib/format';
import { useLibrary } from '../library';

interface TileProps {
  item: Content;
  /** Position in a ranked rail (1-based). */
  rank?: number;
  /** Resume playback instead of opening details (continue watching). */
  resume?: boolean;
  /** Pointed at or focused: put this title under the spotlight. */
  onFeature?: () => void;
}

/** The card tilts toward the pointer and catches the light where it points, like a TV's focused poster. */
const tilt = (event: PointerEvent<HTMLButtonElement>) => {
  if (event.pointerType !== 'mouse') return;
  const node = event.currentTarget;
  const box = node.getBoundingClientRect();
  const x = (event.clientX - box.left) / box.width;
  const y = (event.clientY - box.top) / box.height;
  node.style.setProperty('--ry', `${((x - 0.5) * 12).toFixed(2)}deg`);
  node.style.setProperty('--rx', `${((0.5 - y) * 12).toFixed(2)}deg`);
  node.style.setProperty('--gx', `${(x * 100).toFixed(1)}%`);
  node.style.setProperty('--gy', `${(y * 100).toFixed(1)}%`);
};

export function Tile({ item, rank, resume = false, onFeature }: TileProps) {
  const library = useLibrary();
  const rating = library.feedback[item.id];
  const entry = library.media.get(item.id);
  const playable = entry !== undefined;
  const progress = library.progress.get(item.id);
  const resumeAt = resume && progress?.resumable ? progress.position_seconds : null;
  const watched = progress?.resumable ? progress.position_seconds / progress.duration_seconds : null;
  const left = progress?.resumable ? Math.round((progress.duration_seconds - progress.position_seconds) / 60) : null;
  const label =
    resumeAt !== null ? `Resume ${item.title} from ${timestamp(resumeAt)}` : `${item.title}, ${item.year}. Details`;

  return (
    <article
      className={cx('tile', rank && 'tile-ranked', rating === 1 && 'is-liked', rating === -1 && 'is-disliked')}
      // A resume stub is torn where you stopped.
      style={resume && watched !== null ? ({ '--torn': `${Math.round(watched * 100)}%` } as CSSProperties) : undefined}
    >
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
        onPointerEnter={onFeature}
        onFocus={onFeature}
        onPointerMove={tilt}
        onPointerLeave={event => {
          event.currentTarget.style.removeProperty('--rx');
          event.currentTarget.style.removeProperty('--ry');
        }}
      >
        <Poster item={item} hasPoster={library.posters.has(item.id)} />
        {playable && (
          <span className="tile-badge" aria-hidden="true">
            <Icon name="play" /> {resumeAt !== null ? timestamp(resumeAt) : entry.remote ? 'Stream' : 'Ready'}
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
        <p className="tile-sub">{resume && left !== null ? `${runtime(Math.max(1, left))} left` : subtitle(item)}</p>
      </div>
      <RateButtons title={item.title} rating={rating} onRate={value => library.rate(item.id, value)} />
    </article>
  );
}
