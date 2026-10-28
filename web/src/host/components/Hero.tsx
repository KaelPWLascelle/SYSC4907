import { type CSSProperties, useEffect, useState } from 'react';

import type { Content, Recommendation, Session } from '../../api/types';
import { Icon } from '../../components/Icon';
import { Poster } from '../../components/Poster';
import { RateButtons } from '../../components/RateButtons';
import { aired, capitalize, plural, runtime, spokenTime, timestamp } from '../../lib/format';
import { posterTone } from '../../lib/tone';
import { clockAfter, useNow } from '../../lib/useNow';
import { useLibrary } from '../library';
import { reasons } from '../reasons';

interface HeroProps {
  pick: Recommendation | undefined;
  session: Session;
  loading: boolean;
  /** "Pick for me": draw one of the top picks at random. */
  onPick?: () => void;
}

/** Most bulbs a meter shows; longer evenings make each bulb stand for more than ten minutes. */
const MAX_BULBS = 24;

/**
 * Tonight's pick, under a spotlight. The light takes its colour from the poster and its width from the
 * film: a wide wash for an easy watch, a tight spot for a tense one. The stage has a fixed height on wide
 * screens, so moving between picks never moves the buttons or the rows below.
 */
export function Hero({ pick, session, loading, onPick }: HeroProps) {
  const library = useLibrary();
  const item = pick?.content;
  const hasPoster = item ? library.posters.has(item.id) : false;

  useEffect(() => {
    if (!item) return;
    let current = true;
    void posterTone(item.id, hasPoster).then(tone => {
      if (current) document.documentElement.style.setProperty('--ambient', tone);
    });
    return () => {
      current = false;
    };
  }, [item, hasPoster]);

  if (!pick || !item) {
    return (
      <section className="hero hero-empty" aria-labelledby="hero-title">
        <div className="hero-copy">
          <h1 id="hero-title">{loading ? 'Something good, for right now.' : 'Widen the scene.'}</h1>
          <p className="hero-pitch">
            {loading
              ? 'Getting tonight ready…'
              : 'Give yourself more time, drop a genre you’re avoiding, or clear a rating below.'}
          </p>
        </div>
      </section>
    );
  }

  const progress = library.progress.get(item.id);
  const playable = library.media.has(item.id);
  const rating = library.feedback[item.id];
  // Tense films get a tight spot, easy ones a wide wash.
  const spread = Math.max(0, Math.min(1, (0.75 - item.intensity) / 0.4));
  return (
    <section
      className="hero"
      aria-labelledby="hero-title"
      aria-live="polite"
      style={{ '--spread': spread.toFixed(2) } as CSSProperties}
    >
      <div className="hero-copy" key={item.id}>
        <Title id="hero-title" text={item.title} />
        <p className="hero-meta">
          <span>{item.series ? aired(item.year, item.series) : item.year}</span>
          <span>
            {item.series
              ? `Series, ${plural(item.series.seasons, 'season')}, ${runtime(item.minutes)} episodes`
              : runtime(item.minutes)}
          </span>
          {item.genres[0] && <span>{capitalize(item.genres[0])}</span>}
        </p>
        <Meter item={item} budget={session.minutes} />
        <ul className="reasons" aria-label="Why this pick">
          {reasons(pick, session)
            .slice(0, -1) // the last reason is the runtime, which the bulbs already show
            .map(reason => (
              <li key={reason}>{reason}</li>
            ))}
        </ul>
        <div className="hero-actions">
          {playable && (
            <button type="button" className="button button-primary" onClick={() => library.play(item)}>
              <Icon name="play" />
              {progress?.resumable ? `Resume from ${timestamp(progress.position_seconds)}` : 'Play'}
            </button>
          )}
          <button
            type="button"
            className={playable ? 'button button-quiet' : 'button button-primary'}
            onClick={() => library.openDetails(item)}
          >
            Why this pick
          </button>
          {onPick && (
            <button type="button" className="button button-quiet" onClick={onPick}>
              <Icon name="shuffle" />
              Pick for me
            </button>
          )}
          <RateButtons title={item.title} rating={rating} onRate={value => library.rate(item.id, value)} />
        </div>
      </div>
      <div className={rating === 1 ? 'hero-art is-liked' : rating === -1 ? 'hero-art is-passed' : 'hero-art'}>
        <div className="beam" aria-hidden="true" />
        <Poster item={item} hasPoster={hasPoster} className="poster poster-hero" eager key={item.id} />
        <div className="uplight" aria-hidden="true" />
        <Motes />
      </div>
    </section>
  );
}

/** The title, set a letter at a time, sized so any title fits in two lines. */
function Title({ id, text }: { id: string; text: string }) {
  let index = 0;
  return (
    <h1 id={id} aria-label={text} style={{ '--chars': text.length } as CSSProperties}>
      <span aria-hidden="true">
        {text.split(' ').map((word, w) => (
          <span key={w}>
            {w > 0 && ' '}
            <span className="hero-word">
              {[...word].map(letter => (
                <span key={index} className="hero-letter" style={{ '--i': index++ } as CSSProperties}>
                  {letter}
                </span>
              ))}
            </span>
          </span>
        ))}
      </span>
    </h1>
  );
}

/**
 * Runtime as a row of bulbs against the time you said you have: lit for what the film fills, outlined
 * past the end of your evening. A series lights whole episodes, with a gap between them.
 */
function Meter({ item, budget }: { item: Content; budget: number }) {
  const now = useNow();
  const unit = Math.max(10, Math.ceil(budget / MAX_BULBS / 5) * 5);
  const slots = Math.max(1, Math.round(budget / unit));
  const bulbs: ('on' | 'over' | 'off' | 'gap')[] = [];
  let note: string;
  if (item.series) {
    const per = Math.max(1, Math.round(item.minutes / unit));
    const fit = Math.floor(budget / item.minutes);
    for (let e = 0; e < Math.max(1, Math.min(fit, Math.floor(MAX_BULBS / per))); e++) {
      if (e) bulbs.push('gap');
      for (let k = 0; k < per; k++) bulbs.push(fit ? 'on' : 'over');
    }
    note = fit
      ? `${plural(fit, 'episode')} ${fit === 1 ? 'fits' : 'fit'} your ${spokenTime(budget)}`
      : `An episode runs past your ${spokenTime(budget)}`;
  } else {
    const lit = Math.max(1, Math.round(item.minutes / unit));
    for (let k = 0; k < Math.min(MAX_BULBS, Math.max(slots, lit)); k++)
      bulbs.push(k < lit ? (k < slots ? 'on' : 'over') : 'off');
    const over = item.minutes - budget;
    note =
      over > 0
        ? `Runs ${runtime(over)} past your ${spokenTime(budget)}`
        : `Fits your ${spokenTime(budget)}, ends around ${clockAfter(now, item.minutes)}`;
  }
  let lit = 0;
  return (
    <div className="meter">
      <span className="bulbs" aria-hidden="true">
        {bulbs.map((state, k) =>
          state === 'gap' ? (
            <span key={k} className="bulb-gap" />
          ) : (
            <i key={k} className={`bulb ${state}`} style={{ '--i': lit++ } as CSSProperties} />
          ),
        )}
      </span>
      <span>{note}</span>
    </div>
  );
}

/** Dust in the light: a handful of motes, placed once. */
function Motes() {
  const [motes] = useState(() =>
    Array.from({ length: 18 }, () => ({
      '--x': `${25 + Math.random() * 50}%`,
      '--y': `${8 + Math.random() * 80}%`,
      '--s': `${1 + Math.random() * 2}px`,
      '--t': `${7 + Math.random() * 9}s`,
      '--d': `${-Math.random() * 12}s`,
      '--dx': `${(Math.random() - 0.5) * 40}px`,
    })),
  );
  return (
    <div className="motes" aria-hidden="true">
      {motes.map((style, k) => (
        <i key={k} style={style as CSSProperties} />
      ))}
    </div>
  );
}
