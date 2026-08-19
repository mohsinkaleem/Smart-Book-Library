import { useMemo } from 'react';
import { Clock, Flame, BookOpenCheck, CalendarDays } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import { useSessionStats } from '../../api/threads';
import { Spinner } from '../common/Spinner';

/** "3h 42m", or "42m", or "—". Hours matter, seconds never do. */
export function formatDuration(seconds: number): string {
  if (!seconds) return '—';
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.round((seconds % 3600) / 60);
  if (hours && minutes) return `${hours}h ${minutes}m`;
  if (hours) return `${hours}h`;
  return `${minutes}m`;
}

function Tile({
  icon: Icon, label, value, hint,
}: {
  icon: typeof Clock; label: string; value: string; hint?: string;
}) {
  return (
    <div className="rounded-xl bg-white p-4 shadow-sm ring-1 ring-slate-200/60 dark:bg-slate-800 dark:ring-slate-700">
      <div className="flex items-center gap-1.5 text-xs font-medium text-slate-500 dark:text-slate-400">
        <Icon size={13} className="text-primary-500" />
        {label}
      </div>
      <p className="mt-1 text-xl font-bold tabular-nums text-slate-900 dark:text-white">{value}</p>
      {hint && <p className="mt-0.5 text-[11px] text-slate-400">{hint}</p>}
    </div>
  );
}

/**
 * Reading time, pages per week and streaks (Part 5).
 *
 * The catalog recorded *where* a reader was and never *when*, so the Dashboard
 * had counts of things and nothing about the activity of reading. All of this
 * comes from `reading_sessions`, which the readers fill by heartbeat.
 */
export function ReadingActivity({ colors, tooltipStyle }: {
  colors: { primary: string; axis: string };
  tooltipStyle: object;
}) {
  const { data, isLoading } = useSessionStats(30);

  const chart = useMemo(
    () =>
      (data?.daily ?? []).map((d) => ({
        // `2026-08-19` → `08-19`; the year is the same for every bar in a
        // 30-day window and just costs axis width.
        name: d.date.slice(5),
        minutes: Math.round(d.seconds / 60),
        pages: d.pages,
      })),
    [data],
  );

  if (isLoading) {
    return (
      <div className="flex h-32 items-center justify-center">
        <Spinner size={22} />
      </div>
    );
  }

  // No sessions is a real state, not an error: this data only starts existing
  // once someone opens a book after the feature shipped.
  if (!data || data.sessions === 0) {
    return (
      <div className="rounded-xl border border-dashed border-slate-300 p-8 text-center dark:border-slate-700">
        <Clock size={26} className="mx-auto mb-2 text-slate-300 dark:text-slate-600" />
        <p className="text-sm font-medium text-slate-600 dark:text-slate-300">
          No reading time recorded yet
        </p>
        <p className="mt-1 text-xs text-slate-400">
          Open a book in the reader and time is tracked from there.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Tile
          icon={Clock}
          label="Time reading"
          value={formatDuration(data.window_seconds)}
          hint={`last ${data.window_days} days`}
        />
        <Tile
          icon={BookOpenCheck}
          label="Pages / week"
          value={String(data.pages_per_week)}
          hint={`${data.window_pages} pages in ${data.window_days} days`}
        />
        <Tile
          icon={Flame}
          label="Current streak"
          value={`${data.current_streak} day${data.current_streak === 1 ? '' : 's'}`}
          hint={`longest ${data.longest_streak}`}
        />
        <Tile
          icon={CalendarDays}
          label="Books touched"
          value={String(data.window_books)}
          hint={`${data.sessions} sessions all time`}
        />
      </div>

      {chart.length > 0 && (
        <div className="rounded-xl bg-white p-6 shadow-sm ring-1 ring-slate-200/60 dark:bg-slate-800 dark:ring-slate-700">
          <h2 className="mb-4 text-sm font-bold text-slate-700 dark:text-slate-300">
            Minutes read per day
          </h2>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={chart}>
              <XAxis
                dataKey="name"
                tick={{ fontSize: 10, fill: colors.axis }}
                stroke={colors.axis}
                interval="preserveStartEnd"
              />
              <YAxis tick={{ fontSize: 10, fill: colors.axis }} stroke={colors.axis} />
              <Tooltip contentStyle={tooltipStyle} cursor={{ fill: 'transparent' }} />
              <Bar dataKey="minutes" fill={colors.primary} radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
