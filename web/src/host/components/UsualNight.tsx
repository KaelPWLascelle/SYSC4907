import { type CSSProperties, type KeyboardEvent, type PointerEvent, useEffect, useRef, useState } from 'react';

import { prefersReducedMotion } from '../../lib/motion';
import { describeNight, type Night, NIGHT_MINUTES, nightWord } from '../night';

const { min, max, step } = NIGHT_MINUTES;
const POINTS = 12;
const clamp = (value: number, low: number, high: number) => Math.min(high, Math.max(low, value));
const toY = (minutes: number) => (clamp(minutes, min, max) - min) / (max - min);
const toMinutes = (y: number) => clamp(Math.round((min + y * (max - min)) / step) * step, min, max);

/**
 * The blob: round and soft for a gentle night, a star with sharper points as it gets tense, bigger for a
 * longer night. Catmull-Rom through alternating long and short spokes; the corners sharpen with tension.
 */
function blobPath(tension: number, length: number, time: number, still: boolean): string {
  const base = 54 + length * 70;
  const pts: [number, number][] = [];
  for (let k = 0; k < POINTS; k++) {
    const a = (k / POINTS) * Math.PI * 2 - Math.PI / 2;
    const wobble = still ? 0 : Math.sin(time / 900 + k * 1.7) * (3 + tension * 5);
    const r = base * (k % 2 ? 1 - tension * 0.45 : 1 + tension * 0.35) + wobble;
    pts.push([200 + Math.cos(a) * r, 200 + Math.sin(a) * r]);
  }
  const smooth = 1 - tension * 0.75;
  const p = (k: number) => pts[(k + POINTS) % POINTS] ?? [200, 200];
  let d = `M${p(0)[0].toFixed(1)} ${p(0)[1].toFixed(1)}`;
  for (let k = 0; k < POINTS; k++) {
    const [p0, p1, p2, p3] = [p(k - 1), p(k), p(k + 1), p(k + 2)];
    const c1 = [p1[0] + ((p2[0] - p0[0]) / 6) * smooth, p1[1] + ((p2[1] - p0[1]) / 6) * smooth];
    const c2 = [p2[0] - ((p3[0] - p1[0]) / 6) * smooth, p2[1] - ((p3[1] - p1[1]) / 6) * smooth];
    d += `C${c1.map(v => v.toFixed(1)).join(' ')} ${c2.map(v => v.toFixed(1)).join(' ')} ${p2[0].toFixed(1)} ${p2[1].toFixed(1)}`;
  }
  return `${d}Z`;
}

interface UsualNightProps {
  night: Night;
  onNight: (night: Night) => void;
}

/**
 * "Your usual night", drawn instead of chosen from lists: drag across for how tense, up or down for how
 * long. Saved per profile; Tonight starts from it and can still ask for something different.
 */
export function UsualNight({ night, onNight }: UsualNightProps) {
  const [draft, setDraft] = useState(night);
  const [saved, setSaved] = useState(false);
  const pad = useRef<HTMLDivElement>(null);
  const blob = useRef<SVGPathElement>(null);
  const target = useRef(draft);
  useEffect(() => {
    target.current = draft;
  }, [draft]);

  // The shape eases toward where you point, and breathes a little while it waits.
  useEffect(() => {
    const still = prefersReducedMotion();
    let x = target.current.intensity;
    let y = toY(target.current.minutes);
    let frame = 0;
    const draw = (time: number) => {
      x += (target.current.intensity - x) * (still ? 1 : 0.12);
      y += (toY(target.current.minutes) - y) * (still ? 1 : 0.12);
      blob.current?.setAttribute('d', blobPath(x, y, time, still));
      pad.current?.style.setProperty('--px', `${x * 100}%`);
      pad.current?.style.setProperty('--py', `${(1 - y) * 100}%`);
      if (typeof requestAnimationFrame === 'function') frame = requestAnimationFrame(draw);
    };
    draw(0);
    return () => cancelAnimationFrame(frame);
  }, []);

  const change = (next: Night) => {
    setDraft(next);
    setSaved(false);
  };
  const point = (event: PointerEvent<HTMLDivElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    if (!box.width || !box.height) return;
    change({
      intensity: Math.round(clamp((event.clientX - box.left) / box.width, 0, 1) * 100) / 100,
      minutes: toMinutes(clamp(1 - (event.clientY - box.top) / box.height, 0, 1)),
    });
  };
  const key = (event: KeyboardEvent<HTMLDivElement>) => {
    const moves: Record<string, [number, number]> = {
      ArrowLeft: [-0.1, 0],
      ArrowRight: [0.1, 0],
      ArrowUp: [0, step],
      ArrowDown: [0, -step],
    };
    const move = moves[event.key];
    if (!move) return;
    event.preventDefault();
    change({
      intensity: Math.round(clamp(draft.intensity + move[0], 0, 1) * 100) / 100,
      minutes: clamp(draft.minutes + move[1], min, max),
    });
  };
  const unchanged = draft.intensity === night.intensity && draft.minutes === night.minutes;
  const sentence = describeNight(draft);

  return (
    <section className="taste-card usual-night" aria-labelledby="night-title">
      <div className="taste-card-head">
        <h3 id="night-title">Your usual night</h3>
      </div>
      <div className="night-body">
        <div
          ref={pad}
          className="night-pad"
          role="slider"
          tabIndex={0}
          aria-label="Your usual night: drag across for how tense, up or down for how long"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(draft.intensity * 100)}
          aria-valuetext={`${nightWord(draft.intensity)}, ${draft.minutes} minutes`}
          style={{ '--px': '50%', '--py': '50%' } as CSSProperties}
          onPointerDown={event => {
            point(event);
            event.currentTarget.setPointerCapture?.(event.pointerId);
          }}
          onPointerMove={event => event.buttons && point(event)}
          onKeyDown={key}
        >
          <svg viewBox="0 0 400 400" aria-hidden="true">
            <path ref={blob} className="night-blob" />
          </svg>
          <span className="night-axis night-left">Gentle</span>
          <span className="night-axis night-right">Tense</span>
          <span className="night-axis night-top">Long</span>
          <span className="night-axis night-bottom">Short</span>
        </div>
        <div className="night-copy">
          <p className="night-say">{sentence}</p>
          <p className="hint">
            Flicks plans for this evening when you don’t say otherwise. Tonight can still ask for something different.
          </p>
          <button
            type="button"
            className="button button-primary"
            disabled={unchanged}
            onClick={() => {
              onNight(draft);
              setSaved(true);
            }}
          >
            Use as my usual night
          </button>
          <p className="fine" role="status">
            {saved ? 'Saved. Tonight now starts from this night.' : ''}
          </p>
        </div>
      </div>
    </section>
  );
}
