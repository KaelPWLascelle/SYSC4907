import { isEpisode, type Mode, type Recommendation, type Session } from '../../api/types';
import { Icon } from '../../components/Icon';
import { Poster } from '../../components/Poster';
import { RateButtons } from '../../components/RateButtons';
import { capitalize, subtitle, timestamp } from '../../lib/format';
import { useLibrary } from '../library';
import { reasons } from '../reasons';

interface HeroProps {
  pick: Recommendation | undefined;
  session: Session;
  mode: Mode;
  loading: boolean;
}

export function Hero({ pick, session, mode, loading }: HeroProps) {
  const library = useLibrary();
  if (!pick) {
    return (
      <section className="hero" aria-labelledby="hero-title">
        <div className="hero-inner">
          <div className="hero-copy">
            <p className="eyebrow">{loading ? 'Getting tonight ready…' : 'Nothing fits yet'}</p>
            <h1 id="hero-title">{loading ? 'Something good, for right now.' : 'Widen the scene.'}</h1>
            {!loading && (
              <p className="hero-description">
                Give yourself more time, drop a genre you’re avoiding, or clear a rating below.
              </p>
            )}
          </div>
        </div>
      </section>
    );
  }

  const item = pick.content;
  const hasPoster = library.posters.has(item.id);
  const progress = library.progress.get(item.id);
  const playable = library.media.has(item.id);
  const episode = isEpisode(item);
  return (
    <section className="hero" aria-labelledby="hero-title" aria-live="polite">
      {hasPoster && (
        <div className="hero-backdrop" aria-hidden="true">
          <Poster item={item} hasPoster className="backdrop-art" eager />
        </div>
      )}
      <div className="hero-inner">
        <div className="hero-copy">
          <p className="eyebrow">{mode === 'baseline' ? 'Top pick for your taste' : 'Top pick for tonight'}</p>
          <h1 id="hero-title">{item.title}</h1>
          <p className="hero-meta">
            {episode && 'Podcast · '}
            {subtitle(item)} · {item.genres.map(capitalize).join(' · ')}
          </p>
          <p className="hero-description">{item.description}</p>
          <ul className="reasons" aria-label="Why this pick">
            {reasons(pick, session).map(reason => (
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
              <Icon name="info" />
              Why this pick
            </button>
            <RateButtons
              title={item.title}
              rating={library.feedback[item.id]}
              disabled={library.ratingBusy}
              large
              onRate={value => library.rate(item.id, value)}
            />
          </div>
        </div>
        <div className="hero-poster" aria-hidden="true">
          <Poster item={item} hasPoster={hasPoster} className="poster poster-hero" eager />
        </div>
      </div>
    </section>
  );
}
