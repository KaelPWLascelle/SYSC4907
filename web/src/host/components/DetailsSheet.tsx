import { type CSSProperties, useEffect, useRef, useState } from 'react';

import { flicksApi } from '../../api/flicks';
import { type Content, type EpisodeInfo, isEpisode, type Recommendation, type Session } from '../../api/types';
import { Icon } from '../../components/Icon';
import { Poster } from '../../components/Poster';
import { RateButtons } from '../../components/RateButtons';
import { capitalize, subtitle, timestamp } from '../../lib/format';
import { useLibrary } from '../library';
import { FACTORS, reasons } from '../reasons';
import { DownloadButton } from './DownloadButton';

interface DetailsSheetProps {
  item: Content | null;
  picks: Recommendation[];
  session: Session;
  onClose: () => void;
}

/** "Why this pick" for any title: rank, reasons, the weighted factors behind the score, and actions. */
export function DetailsSheet({ item, picks, session, onClose }: DetailsSheetProps) {
  const dialog = useRef<HTMLDialogElement>(null);
  const library = useLibrary();

  useEffect(() => {
    const node = dialog.current;
    if (!node) return;
    if (item && !node.open) node.showModal();
    if (!item && node.open) node.close();
  }, [item]);

  const rank = item ? picks.findIndex(row => row.content.id === item.id) : -1;
  const pick = rank >= 0 ? picks[rank] : undefined;
  const media = item ? library.media.get(item.id) : undefined;
  const progress = item ? library.progress.get(item.id) : undefined;
  const rating = item ? library.feedback[item.id] : undefined;
  const episode = item !== null && isEpisode(item);

  // The show's own page, for attribution. Loaded per episode; a failure just leaves the link out.
  const [info, setInfo] = useState<EpisodeInfo | null>(null);
  const itemId = item?.id;
  useEffect(() => {
    if (!itemId || !episode) return;
    let current = true;
    flicksApi.podcasts.episode(itemId).then(
      next => {
        if (current) setInfo(next);
      },
      () => undefined,
    );
    return () => {
      current = false;
    };
  }, [itemId, episode]);
  const showPage = info?.id === itemId ? info?.link : undefined;

  return (
    <dialog
      ref={dialog}
      className="details"
      aria-labelledby="details-title"
      onClose={onClose}
      onClick={event => event.target === dialog.current && onClose()} // backdrop
    >
      {item && (
        <>
          <button type="button" className="round details-close" aria-label="Close" onClick={onClose}>
            <Icon name="close" />
          </button>
          <div className="details-art">
            <Poster item={item} hasPoster={library.posters.has(item.id)} className="poster poster-details" eager />
          </div>
          <div className="details-body">
            <p className="eyebrow">
              {pick
                ? `#${rank + 1} of ${picks.length} for this moment`
                : rating
                  ? 'Rated titles are hidden from picks'
                  : 'Not in your current picks'}
            </p>
            <h2 id="details-title">{item.title}</h2>
            <p className="hero-meta">
              {episode && 'Podcast · '}
              {subtitle(item)} · {item.genres.map(capitalize).join(' · ')}
            </p>
            <p className="details-description">{item.description}</p>
            {pick && (
              <ul className="reasons" aria-label="Why this pick">
                {reasons(pick, session).map(reason => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            )}
            <div className="details-actions">
              {media && (
                <>
                  <button type="button" className="button button-primary" onClick={() => library.play(item)}>
                    <Icon name="play" />
                    {progress?.resumable ? `Resume from ${timestamp(progress.position_seconds)}` : 'Play'}
                  </button>
                  {progress?.resumable && (
                    <button type="button" className="button button-quiet" onClick={() => library.play(item, true)}>
                      <Icon name="replay" />
                      Start over
                    </button>
                  )}
                  {episode && (
                    <button
                      type="button"
                      className="button button-quiet"
                      onClick={() => library.removeDownload(item.id)}
                    >
                      <Icon name="remove" />
                      Remove download
                    </button>
                  )}
                </>
              )}
              {episode && !media && <DownloadButton item={item} />}
              <RateButtons
                title={item.title}
                rating={rating}
                disabled={library.ratingBusy}
                large
                onRate={value => library.rate(item.id, value)}
              />
            </div>
            {episode && (
              <p className="fine">
                From the show’s public feed. Flicks downloads an episode only when you ask, for your own listening.
                {showPage && (
                  <>
                    {' '}
                    <a href={showPage} target="_blank" rel="noopener noreferrer">
                      Visit {item.series ?? 'the show'}’s page
                    </a>
                  </>
                )}
              </p>
            )}
            {media && !media.direct_play && (
              <p className="notice">
                This file’s format (MKV or MOV) may not play in every browser. MP4 (H.264/AAC) or WebM always works.
              </p>
            )}
            {pick ? (
              <>
                <h3>Why it ranks here</h3>
                <div className="factors">
                  {Object.entries(pick.factors).map(([key, value]) => {
                    const { label, max } = FACTORS[key] ?? { label: capitalize(key), max: 1 };
                    return (
                      <div className="factor" key={key}>
                        <span className="factor-label">{label}</span>
                        <div className="factor-bar">
                          <span style={{ '--fill': Math.max(0, Math.min(1, value / max)) } as CSSProperties} />
                        </div>
                        <span className="factor-value">
                          {value.toFixed(2)} / {max.toFixed(2)}
                        </span>
                      </div>
                    );
                  })}
                  <div className="factor factor-total">
                    <span className="factor-label">Total</span>
                    <span />
                    <span className="factor-value">{pick.score.toFixed(2)}</span>
                  </div>
                </div>
                <p className="fine">
                  Scores are ranking signals, not probabilities.
                  {pick.because.length > 0 &&
                    ` People who liked ${pick.because.join(' and ')} also rated this highly (MovieLens ratings).`}
                  {pick.popular &&
                    ' Widely liked in MovieLens ratings; popularity counts for less with every film you rate.'}
                  {pick.evidence.length > 0 && ` Terms shared with films you liked: ${pick.evidence.join(', ')}.`}
                  {pick.negative_evidence.length > 0 &&
                    ` Terms from films you passed on: ${pick.negative_evidence.join(', ')}.`}
                </p>
              </>
            ) : (
              <p className="fine">
                {rating
                  ? 'Clear the rating to let it back into your picks.'
                  : 'It doesn’t fit this scene, or ranks below the top picks. Try more time or a different mood.'}
              </p>
            )}
          </div>
        </>
      )}
    </dialog>
  );
}
