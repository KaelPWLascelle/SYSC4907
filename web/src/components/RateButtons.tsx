import type { Rating } from '../api/types';
import { Icon } from './Icon';

interface RateButtonsProps {
  title: string;
  rating: Rating | undefined;
  disabled?: boolean;
  large?: boolean;
  onRate: (value: Rating | 0) => void;
}

const OPTIONS = [
  { value: 1, label: 'Like', className: 'rate-up' },
  { value: -1, label: 'Not for me', className: 'rate-down' },
] as const;

/** Like / pass toggles. Pressing the active one clears the rating. */
export function RateButtons({ title, rating, disabled = false, large = false, onRate }: RateButtonsProps) {
  return (
    <div className={large ? 'rate rate-large' : 'rate'}>
      {OPTIONS.map(({ value, label, className }) => {
        const pressed = rating === value;
        const action = pressed ? 'Clear rating' : label;
        return (
          <button
            key={value}
            type="button"
            className={`rate-button ${className}`}
            aria-pressed={pressed}
            aria-label={`${action}: ${title}`}
            title={action}
            disabled={disabled}
            onClick={event => {
              event.stopPropagation();
              onRate(pressed ? 0 : value);
            }}
          >
            <Icon name="thumbUp" className={value === -1 ? 'flip' : undefined} />
            {large && <span>{label}</span>}
          </button>
        );
      })}
    </div>
  );
}
