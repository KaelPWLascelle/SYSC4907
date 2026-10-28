import { type CSSProperties, useEffect, useMemo, useRef, useState } from 'react';

import { flicksApi } from '../../api/flicks';
import {
  DEFAULT_MIX,
  type Mix,
  type Rating,
  type Recommendation,
  type Session,
  type TasteResponse,
} from '../../api/types';
import { Icon } from '../../components/Icon';
import { Poster } from '../../components/Poster';
import { cx } from '../../lib/cx';
import { capitalize } from '../../lib/format';
import { normalizeMix, sameMix } from '../../lib/mix';
import { useDebounced } from '../../lib/useDebounced';
import { useLibrary } from '../library';
import type { Night } from '../night';
import { FACTOR_KEYS, FACTOR_LABELS } from '../reasons';
import { UsualNight } from './UsualNight';

interface TasteSheetProps {
  open: boolean;
  /** "Your usual night", and how to change it. */
  night: Night;
  onNight: (night: Night) => void;
  session: Session;
  /** Ratings; the view reloads whenever they change. */
  feedback: Record<string, Rating>;
  picks: Recommendation[];
  onClose: () => void;
  /** Use this mix for picks from now on. */
  onMix: (mix: Mix) => void;
  /** Show these titles in Browse (a genre or a theme). */
  onBrowse: (query: string) => void;
}

const message = (error: unknown) => (error instanceof Error ? error.message : String(error));
const percent = (value: number) => `${Math.round(value * 100)}%`;
/** "Your taste": what the ratings say, drawn from the same models that rank, and a tuner for the mix. */
export function TasteSheet({
  open,
  session,
  feedback,
  picks,
  night,
  onNight,
  onClose,
  onMix,
  onBrowse,
}: TasteSheetProps) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [taste, setTaste] = useState<{ key: string; data: TasteResponse | null; error: string }>({
    key: '',
    data: null,
    error: '',
  });
  const key = open ? JSON.stringify(feedback) : '';

  useEffect(() => {
    const node = dialog.current;
    if (!node) return;
    if (open && !node.open) node.showModal();
    if (!open && node.open) node.close();
  }, [open]);

  useEffect(() => {
    if (!key) return;
    const controller = new AbortController();
    flicksApi.taste(controller.signal).then(
      data => setTaste({ key, data, error: '' }),
      failure => {
        if (!controller.signal.aborted) setTaste({ key, data: null, error: message(failure) });
      },
    );
    return () => controller.abort();
  }, [key]);

  const data = taste.key === key ? taste.data : null;
  const error = taste.key === key ? taste.error : ''; // an old failure never hides a fresh load
  const browse = (query: string) => {
    onClose();
    onBrowse(query);
  };

  return (
    <dialog
      ref={dialog}
      className="details taste-sheet"
      aria-labelledby="taste-title"
      onClose={onClose}
      onClick={event => event.target === dialog.current && onClose()}
    >
      <button type="button" className="round details-close" aria-label="Close" onClick={onClose}>
        <Icon name="close" />
      </button>
      {open && (
        <div className="taste-body">
          <p className="eyebrow">Computed on this device from your ratings</p>
          <h2 id="taste-title">Your taste</h2>
          {error && (
            <p className="notice" role="alert">
              Could not load your taste: {error}
            </p>
          )}
          {!data && !error && (
            <p className="hint" role="status">
              Reading your ratings…
            </p>
          )}
          {data && (
            <>
              <p className="taste-lead">
                {data.liked + data.passed === 0
                  ? 'Like or pass on a few titles and this page fills in: the genres you lean toward, the themes behind them, and the films shaping your picks.'
                  : `Built from ${data.liked} ${data.liked === 1 ? 'like' : 'likes'} and ${data.passed} ${
                      data.passed === 1 ? 'pass' : 'passes'
                    }. Nothing here leaves this device.`}
              </p>
              <div className="taste-grid">
                <GenreChart genres={data.genres} rated={data.rated ?? []} liked={data.liked} onBrowse={browse} />
                <ThemeChart liked={data.themes.liked} passed={data.themes.passed} onBrowse={browse} />
                <Influences influences={data.influences} />
                <MixTuner session={session} picks={picks} onMix={onMix} />
                <UsualNight night={night} onNight={onNight} />
              </div>
            </>
          )}
        </div>
      )}
    </dialog>
  );
}

/** A tooltip that follows the hovered or focused mark inside a card. */
function useTooltip() {
  const [tip, setTip] = useState<{ text: string; x: number; y: number } | null>(null);
  const show = (text: string) => (event: React.MouseEvent<HTMLElement> | React.FocusEvent<HTMLElement>) => {
    const target = event.currentTarget;
    const card = target.closest('.taste-card')?.getBoundingClientRect();
    const box = target.getBoundingClientRect();
    if (card) setTip({ text, x: box.left - card.left + box.width / 2, y: box.top - card.top });
  };
  const hide = () => setTip(null);
  const node = tip && (
    <div className="viz-tip" role="tooltip" style={{ left: tip.x, top: tip.y } as CSSProperties}>
      {tip.text}
    </div>
  );
  return { show, hide, node };
}

function GenreChart({
  genres,
  rated,
  liked,
  onBrowse,
}: {
  genres: TasteResponse['genres'];
  rated: Rated;
  liked: number;
  onBrowse: (q: string) => void;
}) {
  const [table, setTable] = useState(false);
  const tip = useTooltip();
  const rows = genres.slice(0, 12);
  return (
    <section className="taste-card taste-genres" aria-labelledby="genres-title">
      <div className="taste-card-head">
        <h3 id="genres-title">Genres you lean toward</h3>
        {rows.length > 0 && (
          <button type="button" className="link" onClick={() => setTable(!table)} aria-pressed={table}>
            {table ? 'Show chart' : 'Show table'}
          </button>
        )}
      </div>
      {rows.length === 0 ? (
        <p className="hint">No rated genres yet.</p>
      ) : table ? (
        <table className="viz-table">
          <thead>
            <tr>
              <th scope="col">Genre</th>
              <th scope="col">Liked</th>
              <th scope="col">Passed</th>
              <th scope="col">Lean</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(g => (
              <tr key={g.genre}>
                <th scope="row">{capitalize(g.genre)}</th>
                <td>{g.liked}</td>
                <td>{g.passed}</td>
                <td>
                  {g.affinity > 0 ? '+' : ''}
                  {Math.round(g.affinity * 100)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <>
          <GenreWeb genres={rows} rated={rated} liked={liked} onBrowse={onBrowse} />
          <div className="diverging-legend" aria-hidden="true">
            <span>
              <span className="swatch swatch-pass" />
              Pass on
            </span>
            <span>
              <span className="swatch swatch-like" />
              Lean toward
            </span>
          </div>
          <ul className="diverging" aria-label="Genre lean, from passing on to leaning toward">
            {rows.map(g => {
              const text = `${capitalize(g.genre)}: liked ${g.liked}, passed ${g.passed}`;
              return (
                <li key={g.genre}>
                  <span className="diverging-label">{capitalize(g.genre)}</span>
                  <button
                    type="button"
                    className="diverging-track"
                    aria-label={`${text}. Browse ${g.genre}`}
                    onMouseEnter={tip.show(text)}
                    onFocus={tip.show(text)}
                    onMouseLeave={tip.hide}
                    onBlur={tip.hide}
                    onClick={() => onBrowse(g.genre)}
                  >
                    <span
                      className={g.affinity >= 0 ? 'diverging-bar like' : 'diverging-bar pass'}
                      style={{ '--size': Math.abs(g.affinity) } as CSSProperties}
                    />
                  </button>
                </li>
              );
            })}
          </ul>
        </>
      )}
      {tip.node}
    </section>
  );
}

type Rated = NonNullable<TasteResponse['rated']>;

/**
 * Your taste as a web: one thread per genre, spun from your ratings. Your shape is drawn on it; the dotted
 * middle ring is "no opinion", so genres you like pull the shape out and genres you pass on pull it in.
 * The films you rated hang in it, pulled toward their genres. Point at a thread to see what made it; the
 * list below stays the way to read and browse the same numbers.
 */
function GenreWeb({
  genres,
  rated,
  liked,
  onBrowse,
}: {
  genres: TasteResponse['genres'];
  rated: Rated;
  liked: number;
  onBrowse: (q: string) => void;
}) {
  const library = useLibrary();
  const [selected, setSelected] = useState<string | null>(null);
  const threads = genres.slice(0, 8);
  if (threads.length < 3) return null;
  const C = 160;
  const R = 120;
  const n = threads.length;
  const angle = (k: number) => (k / n) * Math.PI * 2 - Math.PI / 2;
  const at = (k: number, r: number) => [C + Math.cos(angle(k)) * r, C + Math.sin(angle(k)) * r] as const;
  // Rings sag a little between threads, the way silk does.
  const ring = (f: number) => {
    const r = R * f;
    let d = '';
    for (let k = 0; k < n; k++) {
      const [x1, y1] = at(k, r);
      const [x2, y2] = at(k + 1, r);
      const mid = (angle(k) + angle(k + 1)) / 2;
      const sag = r * 0.88;
      d += `${k ? '' : `M${x1.toFixed(1)} ${y1.toFixed(1)}`}Q${(C + Math.cos(mid) * sag).toFixed(1)} ${(C + Math.sin(mid) * sag).toFixed(1)} ${x2.toFixed(1)} ${y2.toFixed(1)}`;
    }
    return d;
  };
  const shape = threads.map((g, k) => at(k, R * (0.5 + Math.max(-1, Math.min(1, g.affinity)) * 0.5)));
  // Each rated film hangs between the threads of its genres: liked ones out toward the rim, passes near the middle.
  const drops = rated.flatMap((film, i) => {
    let x = 0;
    let y = 0;
    for (const genre of film.genres) {
      const k = threads.findIndex(t => t.genre === genre);
      if (k < 0) continue;
      x += Math.cos(angle(k));
      y += Math.sin(angle(k));
    }
    const length = Math.hypot(x, y);
    if (!length) return [];
    const r = R * (film.rating === 1 ? 0.7 : 0.28) + ((i * 29) % 24) - 12;
    return [{ film, x: C + (x / length) * r, y: C + (y / length) * r }];
  });
  const chosen = threads.find(t => t.genre === selected);
  const choose = (genre: string) => setSelected(genre);
  return (
    <div className="taste-web-wrap">
      <svg className="taste-web" viewBox="-70 -24 460 368" role="group" aria-label="Your taste as a web of genres">
        {[0.25, 0.5, 0.75, 1].map(f => (
          <path key={f} className={f === 0.5 ? 'web-ring web-zero' : 'web-ring'} d={ring(f)} aria-hidden="true" />
        ))}
        {threads.map((g, k) => {
          const [x, y] = at(k, R);
          const [lx, ly] = at(k, R + 20);
          const anchor = Math.abs(lx - C) < 8 ? 'middle' : lx > C ? 'start' : 'end';
          return (
            <g
              key={g.genre}
              className={cx('web-thread', g.affinity < 0 && 'is-pass', selected === g.genre && 'is-on')}
              role="button"
              tabIndex={0}
              aria-pressed={selected === g.genre}
              aria-label={`${capitalize(g.genre)}: liked ${g.liked}, passed ${g.passed}`}
              onPointerEnter={() => choose(g.genre)}
              onFocus={() => choose(g.genre)}
              onClick={() => choose(g.genre)}
              onKeyDown={event => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault();
                  choose(g.genre);
                }
              }}
            >
              <line className="web-hit" x1={C} y1={C} x2={x} y2={y} />
              <line x1={C} y1={C} x2={x} y2={y} />
              <text x={lx} y={ly + 5} textAnchor={anchor}>
                {capitalize(g.genre)}
              </text>
            </g>
          );
        })}
        <polygon
          className="web-shape"
          points={shape.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ')}
          aria-hidden="true"
        />
        {shape.map(([x, y], k) => (
          <circle key={k} className="web-knot" cx={x} cy={y} r={3.5} aria-hidden="true" />
        ))}
        {drops.map(({ film, x, y }, i) => (
          <circle
            key={film.id}
            className={cx(
              'web-drop',
              film.rating === -1 && 'is-pass',
              selected && !film.genres.includes(selected) && 'is-dim',
            )}
            cx={x}
            cy={y}
            r={4.5}
            style={{ '--n': i } as CSSProperties}
            aria-hidden="true"
          >
            <title>{`${film.title} (${film.rating === 1 ? 'liked' : 'passed'})`}</title>
          </circle>
        ))}
      </svg>
      <div className="web-detail" aria-live="polite">
        {chosen ? (
          <>
            <h4>{capitalize(chosen.genre)}</h4>
            <p>{threadSentence(chosen, liked)}</p>
            <div className="web-films">
              {rated
                .filter(film => film.genres.includes(chosen.genre))
                .slice(0, 6)
                .map(film => (
                  <Poster
                    key={film.id}
                    item={film}
                    hasPoster={library.posters.has(film.id)}
                    className={film.rating === 1 ? 'poster' : 'poster is-pass'}
                  />
                ))}
            </div>
            <button type="button" className="button button-quiet" onClick={() => onBrowse(chosen.genre)}>
              Browse {chosen.genre.replace('-', ' ')}
            </button>
          </>
        ) : (
          <p className="hint">Point at a thread to see what made it.</p>
        )}
      </div>
    </div>
  );
}

/** One plain sentence about a genre's thread, from the same counts the chart shows. */
function threadSentence(g: TasteResponse['genres'][number], likedTotal: number): string {
  const name = g.genre.replace('-', ' ');
  if (g.liked && !g.passed) {
    return g.liked === likedTotal && likedTotal > 1
      ? `Every film you liked is ${name}. It’s the strongest thread in your web, and many of your picks hang from it.`
      : `${g.liked} ${g.liked === 1 ? 'film' : 'films'} you liked ${g.liked === 1 ? 'is' : 'are'} ${name}, so your picks lean this way.`;
  }
  if (g.passed && !g.liked) {
    return `You passed on ${g.passed === 1 ? 'the one' : `all ${g.passed}`} ${name} ${g.passed === 1 ? 'title' : 'titles'} you rated, so Flicks keeps ${name} out of your picks unless you ask. One like would change that.`;
  }
  return `${g.liked} liked and ${g.passed} passed: a mixed thread, so Flicks only leans ${g.affinity >= 0 ? 'toward' : 'away from'} ${name} a little.`;
}

function ThemeChart({
  liked,
  passed,
  onBrowse,
}: {
  liked: TasteResponse['themes']['liked'];
  passed: TasteResponse['themes']['passed'];
  onBrowse: (q: string) => void;
}) {
  const tip = useTooltip();
  const bars = (items: TasteResponse['themes']['liked'], kind: 'like' | 'pass') => (
    <ul className="bars" aria-label={kind === 'like' ? 'Themes in what you like' : 'Themes in what you pass on'}>
      {items.slice(0, 8).map(t => {
        const text = `${t.term}: ${percent(t.weight)} of the strongest theme`;
        return (
          <li key={t.term}>
            <button
              type="button"
              className="bar-row"
              aria-label={`${text}. Browse “${t.term}”`}
              onMouseEnter={tip.show(text)}
              onFocus={tip.show(text)}
              onMouseLeave={tip.hide}
              onBlur={tip.hide}
              onClick={() => onBrowse(t.term)}
            >
              <span className="bar-label">{t.term}</span>
              <span className="bar-track">
                <span className={`bar-fill ${kind}`} style={{ '--size': t.weight } as CSSProperties} />
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
  return (
    <section className="taste-card" aria-labelledby="themes-title">
      <div className="taste-card-head">
        <h3 id="themes-title">Themes behind your picks</h3>
      </div>
      {liked.length === 0 && passed.length === 0 ? (
        <p className="hint">Themes appear once you rate a few titles.</p>
      ) : (
        <>
          {liked.length > 0 && bars(liked, 'like')}
          {passed.length > 0 && (
            <>
              <h4 className="bars-subhead">Themes you pass on</h4>
              {bars(passed, 'pass')}
            </>
          )}
          <p className="fine">
            Words from the descriptions of what you rated, weighted like the content model. Select one to browse it.
          </p>
        </>
      )}
      {tip.node}
    </section>
  );
}

/** Each bulb is one of your top picks that a liked film led to. */
function Influences({ influences }: { influences: TasteResponse['influences'] }) {
  return (
    <section className="taste-card" aria-labelledby="influences-title">
      <div className="taste-card-head">
        <h3 id="influences-title">Films shaping your picks</h3>
      </div>
      {influences.length === 0 ? (
        <p className="hint">Like a few films: those whose fans’ ratings point to other titles appear here.</p>
      ) : (
        <>
          <ul className="bars" aria-label="Films shaping your picks, by how many of your top 40 picks they shape">
            {influences.map(i => (
              <li key={i.title} className="bar-row static">
                <span className="bar-label">{i.title}</span>
                <span className="bulbs" aria-hidden="true">
                  {Array.from({ length: i.picks }, (_, k) => (
                    <i key={k} className="bulb on" style={{ '--i': k } as CSSProperties} />
                  ))}
                </span>
                <span className="bar-value">{i.picks}</span>
              </li>
            ))}
          </ul>
          <p className="fine">Each bulb is one of your top 40 picks that the film led to, through MovieLens ratings.</p>
        </>
      )}
    </section>
  );
}

const MIX_HINTS: Record<string, string> = {
  taste: 'Your ratings',
  mood: 'The mood you pick',
  intensity: 'How intense',
  novelty: 'Familiar or new',
};

function MixTuner({ session, picks, onMix }: { session: Session; picks: Recommendation[]; onMix: (mix: Mix) => void }) {
  // Slider values keep the mix's exact proportions (not rounded), so an untouched mix is never "changed".
  const [values, setValues] = useState(() => session.mix.map(w => w * 100));
  const mix = useMemo(() => normalizeMix(values), [values]);
  const changed = !sameMix(mix, session.mix);
  const preview = usePreview(session, mix, changed);
  const tip = useTooltip();
  const before = new Map(picks.map((p, i) => [p.content.id, i]));

  return (
    <section className="taste-card taste-mix" aria-labelledby="mix-title">
      <div className="taste-card-head">
        <h3 id="mix-title">How your picks are scored</h3>
        <button
          type="button"
          className="link"
          onClick={() => setValues(DEFAULT_MIX.map(w => w * 100))}
          disabled={sameMix(mix, DEFAULT_MIX)}
        >
          Reset
        </button>
      </div>
      <div
        className="mix-bar"
        role="img"
        aria-label={FACTOR_KEYS.map((k, i) => `${FACTOR_LABELS[k]} ${percent(mix[i] ?? 0)}`).join(', ')}
      >
        {FACTOR_KEYS.map((k, i) => (
          <span
            key={k}
            className={`mix-segment mix-${k}`}
            style={{ '--size': mix[i] ?? 0 } as CSSProperties}
            onMouseEnter={tip.show(`${FACTOR_LABELS[k]}: ${percent(mix[i] ?? 0)}`)}
            onMouseLeave={tip.hide}
          >
            {(mix[i] ?? 0) >= 0.12 && percent(mix[i] ?? 0)}
          </span>
        ))}
      </div>
      <div className="mix-sliders">
        {FACTOR_KEYS.map((k, i) => (
          <label key={k} className="mix-slider">
            <span className="mix-name">
              <span className={`swatch mix-${k}`} aria-hidden="true" />
              {FACTOR_LABELS[k]}
              <small>{MIX_HINTS[k]}</small>
            </span>
            <input
              type="range"
              min={0}
              max={100}
              value={values[i]}
              aria-valuetext={percent(mix[i] ?? 0)}
              onChange={event => {
                const next = [...values];
                next[i] = Number(event.target.value);
                setValues(next);
              }}
            />
            <output>{percent(mix[i] ?? 0)}</output>
          </label>
        ))}
      </div>
      {changed && (
        <div className="mix-preview" aria-live="polite">
          <h4 className="bars-subhead">Your top five with this mix</h4>
          {preview.error ? (
            <p className="notice">{preview.error}</p>
          ) : (
            <ol className={preview.loading ? 'is-loading' : undefined}>
              {preview.picks.slice(0, 5).map((p, i) => {
                const was = before.get(p.content.id);
                const move = was === undefined ? 'new' : was - i;
                return (
                  <li key={p.content.id}>
                    <span className="preview-title">{p.content.title}</span>
                    <span
                      className={`preview-move ${move === 'new' ? 'up' : move > 0 ? 'up' : move < 0 ? 'down' : ''}`}
                    >
                      {move === 'new' ? 'New' : move > 0 ? `▲ ${move}` : move < 0 ? `▼ ${-move}` : '–'}
                    </span>
                  </li>
                );
              })}
            </ol>
          )}
          <div className="details-actions">
            <button type="button" className="button button-primary" onClick={() => onMix(mix)}>
              Use this mix
            </button>
            <button
              type="button"
              className="button button-quiet"
              onClick={() => setValues(session.mix.map(w => w * 100))}
            >
              Undo changes
            </button>
          </div>
        </div>
      )}
      <p className="fine">
        Every pick’s score is these four parts added up, so you can always see why something ranks where it does.
      </p>
      {tip.node}
    </section>
  );
}

/** Top picks for the scene with a different mix, debounced while a slider moves. */
function usePreview(session: Session, mix: Mix, enabled: boolean) {
  const query = useDebounced(JSON.stringify(mix), 200);
  const [state, setState] = useState<{ query: string; picks: Recommendation[]; error: string }>({
    query: '',
    picks: [],
    error: '',
  });
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    flicksApi.recommend({ ...session, mix: JSON.parse(query) as Mix }, 'session', { signal: controller.signal }).then(
      response => setState({ query, picks: response.recommendations, error: '' }),
      failure => {
        if (!controller.signal.aborted) setState(previous => ({ ...previous, query, error: message(failure) }));
      },
    );
    return () => controller.abort();
  }, [query, enabled, session]);
  return { picks: state.picks, error: state.error, loading: state.query !== query };
}
