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

  // A readonly rating with nothing to show is nothing to show. The list view
  // rendered five disabled `<button>`s in every row whether or not the book
  // had been rated — 593 rows of five focusable, screen-reader-announced
  // controls that do nothing, and five grey stars that read as "rated zero"
  // rather than "not rated".
  if (readonly) {
    if (!value) return null;
    return (
      <div className="flex items-center gap-0.5" role="img" aria-label={`Rated ${value} out of 5`}>
        {stars.map((star) => (
          <Star
            key={star}
            size={size}
            aria-hidden
            className={clsx(
              star <= value ? 'fill-amber-400 text-amber-400' : 'text-slate-300 dark:text-slate-600',
            )}
          />
        ))}
      </div>
    );
  }

  return (
    <div className="flex items-center gap-0.5">
      {stars.map((star) => (
        <button
          key={star}
          type="button"
          onClick={() => onChange?.(value === star ? null : star)}
          aria-label={value === star ? `Clear rating` : `Rate ${star} out of 5`}
          aria-pressed={star <= (value || 0)}
          className="cursor-pointer transition-colors hover:text-amber-400"
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
