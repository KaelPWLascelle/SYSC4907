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
  /** The house lights: the bulb on the i switches them. */
  dim?: boolean;
  onLights?: () => void;
}

export function TopBar({ couch, onAsk, profile, onProfile, onTaste, onDiscover, dim, onLights }: TopBarProps) {
  return (
    <header className="topbar">
      <div className="logo">
        <Logo onBulb={onLights} dim={dim} />
      </div>
      <nav className="nav" aria-label="Sections">
        <a href="#top" aria-current="page">
          Tonight
        </a>
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
        <button type="button" className="ask-button" onClick={onAsk} title="Ask Flicks (/)">
          <Icon name="mic" />
          <span className="ask-label">Ask Flicks</span>
          <kbd>/</kbd>
        </button>
        {profile && onProfile && (
          <button type="button" className="profile-button" onClick={onProfile} aria-label={`Profile: ${profile}`}>
            <span className="avatar" aria-hidden="true">
              {profile.slice(0, 1).toUpperCase()}
            </span>
          </button>
        )}
      </div>
    </header>
  );
}

interface FooterProps {
  titles: number;
  posters: boolean;
  playable: number;
  profile?: string;
}

/** The end credits: what made tonight's picks, and where your data went (nowhere). */
export function Footer({ titles, posters, playable, profile }: FooterProps) {
  return (
    <footer className="footer credits">
      <dl>
        {profile && (
          <>
            <dt>Picked for</dt>
            <dd>{profile}</dd>
          </>
        )}
        <dt>Recommendations by</dt>
        <dd>This computer</dd>
        <dt>Catalogue</dt>
        <dd>
          {titles.toLocaleString('en')} titles, {playable.toLocaleString('en')} ready to play
        </dd>
        <dt>Your ratings and history</dt>
        <dd>Never leave this device</dd>
        <dt>The cloud</dt>
        <dd>Not invited</dd>
        <dt>Snacks</dt>
        <dd>Your department</dd>
      </dl>
      <p>
        Flicks, a SYSC 4907 project. {posters && 'Artwork from Wikipedia, cached on this device for personal use. '}
        No data was harmed in the making of tonight’s pick.
      </p>
    </footer>
  );
}
