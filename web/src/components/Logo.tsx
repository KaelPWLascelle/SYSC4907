/**
 * The Flicks wordmark: "flicks" in Hanken Grotesk, with the dot on the i drawn as a warm bulb that catches
 * on load. The bulb is the brand's one colour; the same bulbs light runtime and scores across the app.
 * Pass `onBulb` to make the bulb a switch (the top bar uses it to dim the house lights). The app icon is
 * the same i, drawn by scripts/make_icons.py and web/public/favicon.svg.
 */
interface LogoProps {
  onBulb?: () => void;
  /** The house lights are down (the bulb shows it). */
  dim?: boolean;
}

export function Logo({ onBulb, dim = false }: LogoProps) {
  return (
    <span className="logo-word">
      <span aria-hidden="true">fl</span>
      <span className="logo-i">
        <span aria-hidden="true">ı</span>
        {onBulb ? (
          <button
            type="button"
            className="logo-bulb"
            aria-pressed={dim}
            aria-label={dim ? 'Bring the lights up' : 'Dim the lights'}
            title={dim ? 'Bring the lights up (L)' : 'Dim the lights (L)'}
            onClick={onBulb}
          />
        ) : (
          <span className="logo-bulb" aria-hidden="true" />
        )}
      </span>
      <span aria-hidden="true">cks</span>
      <span className="visually-hidden">Flicks</span>
    </span>
  );
}
