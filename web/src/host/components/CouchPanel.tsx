import type { Session } from '../../api/types';
import { Poster } from '../../components/Poster';
import type { useCouchHost } from '../hooks/useCouchHost';

const PLAYER_LABELS = { playing: 'Playing', paused: 'Paused', stopped: 'Stopped' } as const;

interface CouchPanelProps {
  couch: ReturnType<typeof useCouchHost>;
  session: Session;
}

/** The TV side of couch mode: QR to join, voting progress, results, and the shared player state. */
export function CouchPanel({ couch, session }: CouchPanelProps) {
  const { view, busy, error } = couch;
  const title = (id: string) => (view.active ? view.items.find(item => item.id === id)?.title : undefined) ?? id;

  return (
    <section id="couch" className="couch-panel" aria-labelledby="couch-heading">
      <div className="row-head">
        <div>
          <p className="eyebrow">Watching together</p>
          <h2 id="couch-heading">Couch mode</h2>
        </div>
        <span className="badge">Same Wi-Fi · no accounts</span>
      </div>

      {!view.active ? (
        <div className="couch-idle">
          <p>
            Everyone on this Wi-Fi scans a code, swipes through a shortlist built from your scene, and the group pick
            shows up here. Guests never see your ratings or history.
          </p>
          <button type="button" className="button button-primary" disabled={busy} onClick={() => couch.start(session)}>
            Start a couch session
          </button>
        </div>
      ) : (
        <div className="couch-live">
          <div className="couch-join">
            <img
              src={`/api/couch/qr.svg?code=${encodeURIComponent(view.code)}`}
              alt="QR code to join this couch session"
              width={220}
              height={220}
            />
            <p className="hint">
              Or open <strong>{view.url}</strong> and enter
            </p>
            <p className="couch-code">{view.code}</p>
          </div>
          <div className="couch-state">
            <h3>Who’s voting</h3>
            <ul className="progress-list">
              {view.progress.length ? (
                view.progress.map(p => (
                  <li key={p.name}>
                    {p.name}: {p.voted} of {p.total}
                    {p.voted === p.total && ' ✓'}
                  </li>
                ))
              ) : (
                <li>Nobody has joined yet.</li>
              )}
            </ul>
            <button
              type="button"
              className="button button-quiet"
              disabled={busy || view.revealed || !view.progress.length}
              onClick={() => couch.reveal()}
            >
              Reveal results now
            </button>

            {view.results && (
              <>
                <h3>Results</h3>
                <ol className="results-list">
                  {view.results.map((row, index) => {
                    const item = view.items.find(entry => entry.id === row.id);
                    if (!item) return null; // results only name shortlisted titles
                    return (
                      <li key={row.id}>
                        <span className="result-title">
                          <Poster item={item} hasPoster={item.poster} />
                          <span>
                            {item.title} — {row.yes} yes · {row.no} no{row.match && ' · it’s a match'}
                            {index === 0 && ' · group pick'}
                          </span>
                        </span>
                        <button
                          type="button"
                          className="button button-quiet"
                          aria-label={`Play ${item.title}`}
                          disabled={busy}
                          onClick={() => couch.player('select', row.id)}
                        >
                          ▶ Play
                        </button>
                      </li>
                    );
                  })}
                </ol>
              </>
            )}

            <h3>Now playing</h3>
            <p className="hint">
              {view.player.id
                ? `${PLAYER_LABELS[view.player.state]}: ${title(view.player.id)}${view.player.by ? ` · from ${view.player.by}` : ''}`
                : 'Nothing playing yet. Pick a title from the results.'}
            </p>
            <div className="remote-buttons">
              <button type="button" className="button button-danger" disabled={busy} onClick={() => couch.stop()}>
                End session
              </button>
            </div>
          </div>
        </div>
      )}
      {error && (
        <p className="notice" role="status">
          {error}
        </p>
      )}
    </section>
  );
}
