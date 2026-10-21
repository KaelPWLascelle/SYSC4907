import { Icon } from '../../components/Icon';
import { Logo } from '../../components/Logo';

interface TopBarProps {
  couch: boolean;
  onAsk: () => void;
  /** The current profile's name, and how to open its menu. */
  profile?: string;
  onProfile?: () => void;
  /** Open "Your taste". */
  onTaste?: () => void;
  /** Open the Discover feed. */
  onDiscover?: () => void;
}

export function TopBar({ couch, onAsk, profile, onProfile, onTaste, onDiscover }: TopBarProps) {
  return (
    <header className="topbar">
      <a className="logo" href="#top" aria-label="Flicks home">
        <Logo />
      </a>
      <nav className="nav" aria-label="Sections">
        <a href="#top">Home</a>
        <a href="#browse">Browse</a>
        {onDiscover && (
          <button type="button" className="nav-button" onClick={onDiscover}>
            Discover
          </button>
        )}
        {couch && <a href="#couch">Couch</a>}
        {onTaste && (
          <button type="button" className="nav-button" onClick={onTaste}>
            Your taste
          </button>
        )}
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
        {profile && onProfile && (
          <button type="button" className="profile-button" onClick={onProfile} aria-label={`Profile: ${profile}`}>
            <span className="avatar" aria-hidden="true">
              {profile.slice(0, 1).toUpperCase()}
            </span>
            <span className="profile-name">{profile}</span>
          </button>
        )}
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
      {posters && <span>Artwork: Wikipedia and podcast feeds, cached on this device for personal use</span>}
    </footer>
  );
}
