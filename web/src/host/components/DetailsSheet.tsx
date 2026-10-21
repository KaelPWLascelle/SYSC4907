import { type CSSProperties, useEffect, useRef, useState } from 'react';

import { flicksApi } from '../../api/flicks';

import type { Content, Recommendation, Session } from '../../api/types';
import { Icon } from '../../components/Icon';
import { Poster } from '../../components/Poster';
import { RateButtons } from '../../components/RateButtons';
import { capitalize, subtitle, timestamp } from '../../lib/format';
import { useLibrary } from '../library';
import { explanation, FACTOR_LABELS, reasons, weightOf } from '../reasons';

interface DetailsSheetProps {
  item: Content | null;
  picks: Recommendation[];
  session: Session;
  /** A local language model is available to put the factors into words. */
  narrate?: boolean;
  /** Shown when the title was drawn by "Pick for me": its chance, and how to draw again. */
  drawn?: { chance: number; pool: number; anything: boolean; onAgain: (anything: boolean) => void };
  onClose: () => void;
}

type Narration = { state: 'idle' } | { state: 'loading' } | { state: 'done'; text: string } | { state: 'none' };

/** The pick's factors in plain words from the local model. Slow (seconds), so it never blocks the sheet. */
function useNarration(id: string | undefined, enabled: boolean, session: Session): Narration {
  const [narration, setNarration] = useState<{ key: string; value: Narration }>({ key: '', value: { state: 'idle' } });
  const key = enabled && id ? `${id}:${JSON.stringify(session)}` : '';
  useEffect(() => {
    if (!key || !id) return;
    const controller = new AbortController(); // until a reply for this key arrives, the state reads as loading
    flicksApi.explain(id, session, controller.signal).then(
      result =>
        setNarration({ key, value: result.narration ? { state: 'done', text: result.narration } : { state: 'none' } }),
      () => {
        if (!controller.signal.aborted) setNarration({ key, value: { state: 'none' } });
      },
    );
    return () => controller.abort();
    // `key` already encodes id and session.
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  return narration.key === key ? narration.value : { state: key ? 'loading' : 'idle' };
}

/** "1 in 7" for a chance of about 14%; "2%" below 1 in 50. */
function chanceText(chance: number) {
  const odds = Math.round(1 / chance);
  return odds <= 50 ? `1 in ${odds}` : `${Math.max(0.1, Math.round(chance * 1000) / 10)}%`;
}

/** "Why this pick" for any title: rank, reasons, the weighted factors behind the score, and actions. */
export function DetailsSheet({ item, picks, session, narrate = false, drawn, onClose }: DetailsSheetProps) {
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
  const narration = useNarration(pick?.content.id, narrate, session);

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
            {drawn && (
              <div className="drawn" role="status">
                <p>
                  Picked at random from{' '}
                  {drawn.anything ? `all ${drawn.pool} titles that fit this scene` : `your top ${drawn.pool} picks`}: a{' '}
                  {chanceText(drawn.chance)} chance{drawn.anything ? '' : ', higher for better matches'}.
                </p>
                <div className="drawn-actions">
                  <button type="button" className="chip" onClick={() => drawn.onAgain(drawn.anything)}>
                    Pick again
                  </button>
                  <button type="button" className="chip" onClick={() => drawn.onAgain(!drawn.anything)}>
                    {drawn.anything ? 'From my top picks' : 'From anything'}
                  </button>
                </div>
              </div>
            )}
            <p className="eyebrow">
              {pick
                ? `#${rank + 1} of ${picks.length} for this moment`
                : rating
                  ? 'Rated titles are hidden from picks'
                  : 'Not in your current picks'}
            </p>
            <h2 id="details-title">{item.title}</h2>
            <p className="hero-meta">
              {subtitle(item)} · {item.genres.map(capitalize).join(' · ')}
            </p>
            <p className="details-description">{item.description}</p>
            {pick && (
              <p className="narration" aria-label="In plain words">
                {narration.state === 'done' ? narration.text : explanation(pick, session)}
                {narration.state === 'done' && (
                  <span className="fine"> Reworded by a language model on this device from the factors below.</span>
                )}
              </p>
            )}
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
                </>
              )}
              <RateButtons title={item.title} rating={rating} large onRate={value => library.rate(item.id, value)} />
            </div>
            {media?.source && (
              <p className="fine">
                {`Streams from the ${media.source}, where this film is in the public domain in the United States.`}
                {media.page && (
                  <>
                    {' '}
                    <a href={media.page} target="_blank" rel="noopener noreferrer">
                      {`View it on the ${media.source}`}
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
                    const label = FACTOR_LABELS[key] ?? capitalize(key);
                    const max = weightOf(key, session);
                    return (
                      <div className="factor" key={key}>
                        <span className="factor-label">{label}</span>
                        <div className="factor-bar">
                          <span
                            style={{ '--fill': max > 0 ? Math.max(0, Math.min(1, value / max)) : 0 } as CSSProperties}
                          />
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
