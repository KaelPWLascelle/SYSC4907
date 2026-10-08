import { useEffect, useRef, useState } from 'react';

import type { CouchGuestView, CouchItem, CouchResult } from '../api/types';
import { Logo } from '../components/Logo';
import { Poster } from '../components/Poster';
import { tokenStore } from './api';
import { useCouchGuest } from './useCouchGuest';

const PLAYER_LABELS = { playing: 'Playing', paused: 'Paused', stopped: 'Stopped' } as const;

/** The QR code carries the join code in the URL fragment, which browsers never send to the server. */
function takeCodeFromUrl(): string {
  const code = window.location.hash.slice(1).toUpperCase();
  if (code) window.history.replaceState(null, '', window.location.pathname);
  return code;
}

export function GuestApp() {
  const couch = useCouchGuest();
  const [initialCode] = useState(takeCodeFromUrl);
  const reconnecting = !couch.joined && tokenStore.get() !== null && !couch.message;

  return (
    <div className="couch-guest">
      <header className="topbar">
        <span className="logo">
          <Logo />
        </span>
        <span className="topbar-end privacy-chip">
          <i aria-hidden="true" />
          Stays in this room
        </span>
      </header>
      <main>
        {couch.joined && couch.view ? (
          <Session view={couch.view} busy={couch.busy} onVote={couch.vote} onRemote={couch.remote} />
        ) : reconnecting ? (
          <p className="hint">Reconnecting to the TV…</p>
        ) : (
          <JoinForm initialCode={initialCode} busy={couch.busy} onJoin={couch.join} />
        )}
        <p className="guest-message" role="status" aria-live="polite">
          {couch.message}
        </p>
      </main>
    </div>
  );
}

function JoinForm({
  initialCode,
  busy,
  onJoin,
}: {
  initialCode: string;
  busy: boolean;
  onJoin: (code: string, name: string) => void;
}) {
  const [name, setName] = useState('');
  const [code, setCode] = useState(initialCode);
  const nameInput = useRef<HTMLInputElement>(null);
  const codeInput = useRef<HTMLInputElement>(null);
  useEffect(() => (initialCode ? nameInput : codeInput).current?.focus(), [initialCode]);

  return (
    <section>
      <p className="eyebrow">Couch mode</p>
      <h1>
        Pick <em>together.</em>
      </h1>
      <p>Swipe through tonight’s shortlist. Votes stay hidden until everyone’s done.</p>
      <form
        onSubmit={event => {
          event.preventDefault();
          onJoin(code, name);
        }}
      >
        <label htmlFor="name">Your name</label>
        <input
          id="name"
          ref={nameInput}
          maxLength={24}
          autoComplete="nickname"
          required
          value={name}
          onChange={e => setName(e.target.value)}
        />
        <label htmlFor="code">Code on the TV</label>
        <input
          id="code"
          ref={codeInput}
          maxLength={8}
          autoCapitalize="characters"
          autoComplete="off"
          spellCheck={false}
          required
          value={code}
          onChange={e => setCode(e.target.value)}
        />
        <button className="button button-primary" type="submit" disabled={busy}>
          Join the couch
        </button>
      </form>
      <p className="fine">
        No account, no app. Your name and votes live in memory on the TV and are forgotten when the session ends.
      </p>
    </section>
  );
}

interface SessionProps {
  view: CouchGuestView;
  busy: boolean;
  onVote: (id: string, value: 1 | -1 | 0) => void;
  onRemote: (action: 'play' | 'pause' | 'stop' | 'select', id?: string) => void;
}

function Session({ view, busy, onVote, onRemote }: SessionProps) {
  const votes = view.you.votes;
  const next = view.items.find(item => !(item.id in votes));
  const lastVoted = [...view.items].reverse().find(item => item.id in votes);
  const items = new Map(view.items.map(item => [item.id, item]));
  const player = view.player;
  const playingTitle = player.id ? (items.get(player.id)?.title ?? 'a title') : null;

  return (
    <>
      {view.revealed && view.results ? (
        <Results
          results={view.results}
          items={items}
          people={view.progress.length}
          busy={busy}
          onPlay={id => onRemote('select', id)}
        />
      ) : next ? (
        <section>
          <p className="eyebrow">
            Title {Object.keys(votes).length + 1} of {view.items.length}
          </p>
          <VoteCard item={next} />
          <div className="vote-buttons">
            <button type="button" className="button button-quiet" disabled={busy} onClick={() => onVote(next.id, -1)}>
              ✕ Not tonight
            </button>
            <button type="button" className="button button-primary" disabled={busy} onClick={() => onVote(next.id, 1)}>
              ✓ I’d watch it
            </button>
          </div>
          {lastVoted && (
            <button type="button" className="link" disabled={busy} onClick={() => onVote(lastVoted.id, 0)}>
              ← Change my last vote
            </button>
          )}
        </section>
      ) : (
        <section>
          <p className="eyebrow">All done</p>
          <h1>Nice picks.</h1>
          <p>Waiting for everyone else. Nobody sees anyone’s votes until the reveal.</p>
          <ul className="progress-list">
            {view.progress.map(p => (
              <li key={p.name}>
                {p.name}
                {p.name === view.you.name && ' (you)'}: {p.voted} of {p.total}
              </li>
            ))}
          </ul>
          {lastVoted && (
            <button type="button" className="link" disabled={busy} onClick={() => onVote(lastVoted.id, 0)}>
              ← Change my last vote
            </button>
          )}
        </section>
      )}
      <section className="remote" aria-label="Remote control">
        <div>
          <p className="eyebrow">Remote</p>
          <p>
            {playingTitle
              ? `${PLAYER_LABELS[player.state]}: ${playingTitle}${player.by ? ` (by ${player.by})` : ''}`
              : 'Nothing playing yet. Pick a title from the results.'}
          </p>
        </div>
        <div className="remote-buttons">
          <button
            type="button"
            className="button button-quiet"
            disabled={busy || !player.id}
            onClick={() => onRemote(player.state === 'playing' ? 'pause' : 'play')}
          >
            {player.state === 'playing' ? '❚❚ Pause' : '▶ Play'}
          </button>
          <button
            type="button"
            className="button button-quiet"
            disabled={busy || !player.id}
            onClick={() => onRemote('stop')}
          >
            ■ Stop
          </button>
        </div>
      </section>
    </>
  );
}

function VoteCard({ item }: { item: CouchItem }) {
  return (
    <article className="couch-card">
      <Poster item={item} hasPoster={item.poster} eager />
      <div className="couch-card-body">
        <p className="meta">
          {item.kind === 'episode' ? `PODCAST · ${item.series ?? ''}` : item.year} / {item.minutes} MIN
        </p>
        <h2>{item.title}</h2>
        <p className="description">{item.description}</p>
        <p className="tags">{item.genres.join(' · ')}</p>
      </div>
    </article>
  );
}

interface ResultsProps {
  results: CouchResult[];
  items: ReadonlyMap<string, CouchItem>;
  people: number;
  busy: boolean;
  onPlay: (id: string) => void;
}

function Results({ results, items, people, busy, onPlay }: ResultsProps) {
  const top = results[0];
  const best = top && items.get(top.id);
  if (!top || !best) return null; // results always name shortlisted titles
  return (
    <section>
      <p className="eyebrow">{top.match ? 'It’s a match' : 'The couch has spoken'}</p>
      <div className="winner">
        <Poster item={best} hasPoster={best.poster} eager />
        <div>
          <h2>{best.title}</h2>
          <p>
            {top.yes} of {people} said yes{top.no ? `, ${top.no} said no` : ''}. {best.minutes} min ·{' '}
            {best.genres.join(' / ')}. Ties go to Flicks’ own ranking (#{top.flicks_rank}).
          </p>
        </div>
      </div>
      <ol className="results-list">
        {results.map(row => {
          const item = items.get(row.id);
          if (!item) return null;
          return (
            <li key={row.id}>
              <span className="result-title">
                <Poster item={item} hasPoster={item.poster} />
                <span>
                  {item.title} — {row.yes} yes · {row.no} no{row.match && ' · everyone'}
                </span>
              </span>
              <button
                type="button"
                className="button button-quiet"
                aria-label={`Play ${item.title} on the TV`}
                disabled={busy}
                onClick={() => onPlay(row.id)}
              >
                ▶ Play
              </button>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
