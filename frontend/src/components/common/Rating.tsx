import { Star } from 'lucide-react';
import clsx from 'clsx';

interface RatingProps {
  value: number | null;
  onChange?: (v: number | null) => void;
  size?: number;
  readonly?: boolean;
}

export function Rating({ value, onChange, size = 16, readonly = false }: RatingProps) {
  const stars = [1, 2, 3, 4, 5];
  return (
    <div className="flex items-center gap-0.5">
      {stars.map((star) => (
        <button
          key={star}
          type="button"
          disabled={readonly}
          onClick={() => onChange?.(value === star ? null : star)}
          className={clsx(
            'transition-colors',
            !readonly && 'cursor-pointer hover:text-amber-400',
            readonly && 'cursor-default',
          )}
        >
          <Star
            size={size}
            className={clsx(
              star <= (value || 0) ? 'fill-amber-400 text-amber-400' : 'text-slate-300 dark:text-slate-600',
            )}
          />
        </button>
      ))}
    </div>
  );
}
