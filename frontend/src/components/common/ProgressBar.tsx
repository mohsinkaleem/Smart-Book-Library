import clsx from 'clsx';

interface ProgressBarProps {
  /** 0–100. Values outside the range are clamped rather than overflowing. */
  percent: number;
  className?: string;
}

/** Reading progress. Decorative — the numeric value is always shown beside it. */
export function ProgressBar({ percent, className }: ProgressBarProps) {
  const value = Math.min(100, Math.max(0, percent || 0));
  return (
    <div
      className={clsx('h-1 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700', className)}
      role="progressbar"
      aria-valuenow={Math.round(value)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label="Reading progress"
    >
      <div className="h-full rounded-full bg-primary-500 transition-[width] duration-300" style={{ width: `${value}%` }} />
    </div>
  );
}
