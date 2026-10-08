import { Icon } from '../../components/Icon';
import { Logo } from '../../components/Logo';

export function TopBar({ couch, onAsk }: { couch: boolean; onAsk: () => void }) {
  return (
    <header className="topbar">
      <a className="logo" href="#top" aria-label="Flicks home">
        <Logo />
      </a>
      <nav className="nav" aria-label="Sections">
        <a href="#top">Home</a>
        <a href="#browse">Browse</a>
        {couch && <a href="#couch">Couch</a>}
      </nav>
      <div className="topbar-end">
        <button type="button" className="ask-button" onClick={onAsk}>
          <Icon name="mic" />
          Ask Flicks <kbd>/</kbd>
        </button>
        <span className="privacy-chip" title="Ratings, voice and recommendations are computed on this device">
          <i aria-hidden="true" />
          On this device
        </span>
      </div>
    </header>
  );
}

export function Footer({ titles, posters, playable }: { titles: number; posters: boolean; playable: number }) {
  return (
    <footer className="footer">
      <span>
        <strong>flicks</strong> · SYSC 4907
      </span>
      <span>
        {titles} titles · {playable} playable · local taste profile + explainable scene ranking · your ratings and
        history never leave this device
      </span>
      {posters && <span>Posters: Wikipedia, cached locally for personal use</span>}
    </footer>
  );
}
