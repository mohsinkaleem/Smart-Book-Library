import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { useStats } from '../../api/books';
import { useTheme } from '../../hooks/useTheme';
import { Spinner } from '../common/Spinner';
import { ErrorState } from '../common/ErrorBoundary';
import { formatBytes } from '../../utils/format';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts';

/**
 * Recharts wants real colour values, not classes, so the charts cannot pick
 * the palette up from CSS the way every other component does. Read the theme
 * variables instead — hardcoded indigo was the one part of the page that
 * ignored the theme entirely.
 */
function useChartColors() {
  const [theme] = useTheme();
  return useMemo(() => {
    const css = getComputedStyle(document.documentElement);
    const v = (name: string, fallback: string) =>
      css.getPropertyValue(name).trim() || fallback;
    return {
      // Carried through so the memo's dependency on `theme` is a real one:
      // the variables above are read from the DOM, and `theme` is what says
      // when that read is stale.
      theme,
      // Two shades of the accent, then fixed hues for the categorical series —
      // a pie needs distinguishable slices more than it needs to be on-brand.
      primary: v('--color-primary-500', '#6366f1'),
      primaryDeep: v('--color-primary-700', '#4338ca'),
      axis: v('--color-slate-400', '#94a3b8'),
      surface: v('--color-white', '#ffffff'),
      border: v('--color-slate-200', '#e2e8f0'),
      text: v('--color-slate-700', '#334155'),
      series: [
        v('--color-primary-500', '#6366f1'),
        '#8b5cf6', '#ec4899', '#f59e0b', '#10b981', '#3b82f6', '#ef4444', '#14b8a6',
      ],
    };
  }, [theme]);
}

/** `x / 0` rendered as `NaN%` on an empty library. */
function percent(part: number, whole: number): string {
  if (!whole) return '—';
  return `${Math.round((part / whole) * 100)}%`;
}

export function Dashboard() {
  const { data: stats, isLoading, isError, error, refetch } = useStats();
  const colors = useChartColors();

  const tooltipStyle = {
    backgroundColor: colors.surface,
    border: `1px solid ${colors.border}`,
    borderRadius: 8,
    color: colors.text,
    fontSize: 12,
  };

  if (isLoading) return <div className="flex h-full items-center justify-center"><Spinner /></div>;
  // This used to `return null` — a blank screen with no explanation.
  if (isError) {
    return (
      <ErrorState
        title="Couldn't load statistics"
        message={(error as Error)?.message}
        onRetry={() => refetch()}
      />
    );
  }
  if (!stats) return null;

  const typeData = Object.entries(stats.by_type).map(([name, value]) => ({ name: name.toUpperCase(), value }));
  const statusData = Object.entries(stats.by_status).map(([name, value]) => ({
    name: name.replace('_', ' ').replace(/\b\w/g, c => c.toUpperCase()), value,
  }));

  return (
    <div className="space-y-6 p-6">
      <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Library Statistics</h1>

      {/* Summary cards */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
        <StatCard label="Books" value={String(stats.total_books)} />
        <StatCard label="Total Size" value={formatBytes(stats.total_size_bytes)} />
        <StatCard label="With Covers" value={percent(stats.with_cover, stats.total_books)} />
        <StatCard label="Descriptions" value={percent(stats.with_description, stats.total_books)} />
        <StatCard label="Avg Rating" value={stats.avg_rating ? `★ ${stats.avg_rating}` : '—'} />
        {/* Detected by the pipeline since day one and never shown anywhere. */}
        <StatCard
          label="Possible duplicates"
          value={String(stats.duplicates)}
          to={stats.duplicates > 0 ? '/review' : undefined}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Categories chart */}
        <div className="rounded-xl bg-white p-6 shadow-sm ring-1 ring-slate-200/60 dark:bg-slate-800 dark:ring-slate-700">
          <h2 className="mb-4 text-sm font-bold text-slate-700 dark:text-slate-300">By Category</h2>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={stats.categories.slice(0, 10)} layout="vertical">
              <XAxis type="number" tick={{ fontSize: 11, fill: colors.axis }} stroke={colors.axis} />
              <YAxis
                type="category"
                dataKey="name"
                width={150}
                tick={{ fontSize: 11, fill: colors.axis }}
                stroke={colors.axis}
              />
              <Tooltip contentStyle={tooltipStyle} cursor={{ fill: colors.border, opacity: 0.3 }} />
              <Bar dataKey="count" fill={colors.primary} radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* File type pie */}
        <div className="rounded-xl bg-white p-6 shadow-sm ring-1 ring-slate-200/60 dark:bg-slate-800 dark:ring-slate-700">
          <h2 className="mb-4 text-sm font-bold text-slate-700 dark:text-slate-300">By File Type</h2>
          <ResponsiveContainer width="100%" height={200}>
            <PieChart>
              <Pie data={typeData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={80} label>
                {typeData.map((_, i) => (
                  <Cell key={i} fill={colors.series[i % colors.series.length]} />
                ))}
              </Pie>
              <Tooltip contentStyle={tooltipStyle} />
            </PieChart>
          </ResponsiveContainer>

          <h2 className="mb-4 mt-6 text-sm font-bold text-slate-700 dark:text-slate-300">Reading Status</h2>
          <div className="space-y-2">
            {statusData.map((s, i) => (
              <div key={s.name} className="flex items-center gap-3">
                <div
                  className="h-2.5 w-2.5 rounded-full"
                  style={{ backgroundColor: colors.series[i % colors.series.length] }}
                />
                <span className="flex-1 text-sm text-slate-600 dark:text-slate-400">{s.name}</span>
                <span className="text-sm font-bold text-slate-900 dark:text-white">{s.value}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Year histogram */}
        {stats.year_histogram.length > 0 && (
          <div className="rounded-xl bg-white p-6 shadow-sm ring-1 ring-slate-200/60 dark:bg-slate-800 dark:ring-slate-700 lg:col-span-2">
            <h2 className="mb-4 text-sm font-bold text-slate-700 dark:text-slate-300">Publication Years</h2>
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={stats.year_histogram}>
                <XAxis dataKey="year" tick={{ fontSize: 11, fill: colors.axis }} stroke={colors.axis} />
                <YAxis tick={{ fontSize: 11, fill: colors.axis }} stroke={colors.axis} />
                <Tooltip contentStyle={tooltipStyle} cursor={{ fill: colors.border, opacity: 0.3 }} />
                <Bar dataKey="count" fill={colors.primaryDeep} radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </div>
  );
}

function StatCard({ label, value, to }: { label: string; value: string; to?: string }) {
  const body = (
    <>
      <p className="text-2xl font-bold text-slate-900 dark:text-white">{value}</p>
      <p className="text-sm text-slate-500">{label}</p>
    </>
  );
  const className =
    'block rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200/60 dark:bg-slate-800 dark:ring-slate-700';

  if (!to) return <div className={className}>{body}</div>;
  return (
    <Link to={to} className={`${className} transition-shadow hover:shadow-md`}>
      {body}
    </Link>
  );
}
