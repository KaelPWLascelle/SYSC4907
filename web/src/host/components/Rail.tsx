import { type ReactNode, useRef } from 'react';

import { Icon } from '../../components/Icon';

interface RailProps {
  id: string;
  title: string;
  status?: ReactNode;
  badge?: string;
  /** New results are on their way: the current ones dim slightly. */
  busy?: boolean;
  /** "stubs": ticket stubs torn where you stopped (continue watching). */
  variant?: 'stubs';
  children: ReactNode;
}

/** A titled, horizontally scrolling row with previous/next buttons on pointer devices. */
export function Rail({ id, title, status, badge, busy = false, variant, children }: RailProps) {
  const scroller = useRef<HTMLDivElement>(null);
  const scroll = (direction: 1 | -1) =>
    scroller.current?.scrollBy({ left: direction * scroller.current.clientWidth * 0.85, behavior: 'smooth' });
  return (
    <section className="row" id={id} aria-labelledby={`${id}-heading`}>
      <div className="row-head">
        <div>
          <h2 id={`${id}-heading`}>{title}</h2>
          {status !== undefined && (
            <p role="status" aria-live="polite">
              {status}
            </p>
          )}
        </div>
        <div className="row-tools">
          {badge && <span className="badge">{badge}</span>}
          <button type="button" className="round" aria-label={`Scroll ${title} left`} onClick={() => scroll(-1)}>
            <Icon name="chevronLeft" />
          </button>
          <button type="button" className="round" aria-label={`Scroll ${title} right`} onClick={() => scroll(1)}>
            <Icon name="chevronRight" />
          </button>
        </div>
      </div>
      <div className={variant ? `rail rail-${variant}` : 'rail'} ref={scroller} aria-busy={busy}>
        {children}
      </div>
    </section>
  );
}
